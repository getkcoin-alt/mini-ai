from __future__ import annotations

import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from miniai.security import generate_pin, hash_pin, validate_pin, verify_pin


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "mini")[:48]


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    slug: str
    owner_name: str
    pin_hash: str
    vault_enabled: bool
    active: bool
    created_at: str


class TenantStore:
    """Registry plus one SQLite conversation database per tenant.

    The registry stores only a scrypt PIN hash. Every tenant's messages live in a
    different file, preserving the original Mini one-person/one-memory boundary.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.tenants_dir = self.root / "tenants"
        self.registry_path = self.root / "registry.sqlite3"
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.tenants_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._init_registry()

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_registry(self) -> None:
        with self._lock, self._connect(self.registry_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    slug TEXT UNIQUE NOT NULL,
                    owner_name TEXT NOT NULL,
                    pin_hash TEXT NOT NULL,
                    vault_enabled INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                """
            )
        self._restrict(self.registry_path)

    @staticmethod
    def _restrict(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _tenant_path(self, slug: str) -> Path:
        return self.tenants_dir / f"{slug}.sqlite3"

    def _init_tenant_db(self, slug: str) -> None:
        path = self._tenant_path(slug)
        with self._lock, self._connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_created
                    ON messages(created_at DESC);
                """
            )
        self._restrict(path)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> Tenant | None:
        if row is None:
            return None
        return Tenant(
            id=row["id"],
            slug=row["slug"],
            owner_name=row["owner_name"],
            pin_hash=row["pin_hash"],
            vault_enabled=bool(row["vault_enabled"]),
            active=bool(row["active"]),
            created_at=row["created_at"],
        )

    def onboard(
        self, owner_name: str, *, pin: str | None = None, vault_enabled: bool = False
    ) -> tuple[Tenant, str]:
        owner = (owner_name or "").strip()
        if not 1 <= len(owner) <= 80:
            raise ValueError("owner_name must contain 1 to 80 characters")
        raw_pin = validate_pin(pin) if pin is not None else generate_pin()
        base = _slugify(owner)
        with self._lock, self._connect(self.registry_path) as conn:
            slug = base
            suffix = 2
            while conn.execute("SELECT 1 FROM tenants WHERE slug = ?", (slug,)).fetchone():
                slug = f"{base[:42]}-{suffix}"
                suffix += 1
            tenant = Tenant(
                id=str(uuid4()),
                slug=slug,
                owner_name=owner,
                pin_hash=hash_pin(raw_pin),
                vault_enabled=bool(vault_enabled),
                active=True,
                created_at=_now(),
            )
            conn.execute(
                """
                INSERT INTO tenants
                    (id, slug, owner_name, pin_hash, vault_enabled, active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    tenant.id,
                    tenant.slug,
                    tenant.owner_name,
                    tenant.pin_hash,
                    int(tenant.vault_enabled),
                    tenant.created_at,
                ),
            )
        self._init_tenant_db(tenant.slug)
        return tenant, raw_pin

    def get(self, slug: str, *, include_inactive: bool = False) -> Tenant | None:
        sql = "SELECT * FROM tenants WHERE slug = ?"
        params: tuple[object, ...] = (slug,)
        if not include_inactive:
            sql += " AND active = 1"
        with self._lock, self._connect(self.registry_path) as conn:
            return self._row(conn.execute(sql, params).fetchone())

    def list(self) -> list[Tenant]:
        with self._lock, self._connect(self.registry_path) as conn:
            rows = conn.execute("SELECT * FROM tenants ORDER BY created_at DESC").fetchall()
        return [tenant for row in rows if (tenant := self._row(row)) is not None]

    def authenticate(self, slug: str, pin: str) -> Tenant | None:
        tenant = self.get(slug)
        if tenant is None or not verify_pin(pin, tenant.pin_hash):
            return None
        return tenant

    def deactivate(self, slug: str) -> bool:
        with self._lock, self._connect(self.registry_path) as conn:
            cur = conn.execute("UPDATE tenants SET active = 0 WHERE slug = ?", (slug,))
            return cur.rowcount > 0

    def append_message(self, slug: str, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("invalid message role")
        text = (content or "").strip()
        if not text:
            return
        self._init_tenant_db(slug)
        with self._lock, self._connect(self._tenant_path(slug)) as conn:
            conn.execute(
                "INSERT INTO messages (id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid4()), role, text, _now()),
            )

    def history(self, slug: str, *, limit: int = 20) -> list[dict[str, str]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        self._init_tenant_db(slug)
        with self._lock, self._connect(self._tenant_path(slug)) as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at FROM (
                    SELECT role, content, created_at, rowid
                    FROM messages ORDER BY rowid DESC LIMIT ?
                ) ORDER BY rowid ASC
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def check(self) -> None:
        with self._lock, self._connect(self.registry_path) as conn:
            conn.execute("SELECT 1").fetchone()

