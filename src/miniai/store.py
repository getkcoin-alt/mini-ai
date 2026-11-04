from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
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
    @contextmanager
    def _connect(path: Path):
        conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

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
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    next_step TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkins (
                    id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                    note TEXT NOT NULL,
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

    def preferences(self, slug: str) -> dict:
        self._init_tenant_db(slug)
        with self._lock, self._connect(self._tenant_path(slug)) as conn:
            row = conn.execute("SELECT data FROM preferences WHERE id = 1").fetchone()
        defaults = {
            "onboarded": False,
            "tone": "warm",
            "focus": "",
            "memory_enabled": False,
            "mode": "friend",
        }
        if row:
            defaults.update(json.loads(row["data"]))
        return defaults

    def save_preferences(self, slug: str, values: dict) -> dict:
        with self._lock:
            prefs = self.preferences(slug)
            prefs.update(values)
            with self._connect(self._tenant_path(slug)) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO preferences VALUES (1, ?)", (json.dumps(prefs),)
                )
            return prefs

    def memories(self, slug: str) -> list[dict]:
        self._init_tenant_db(slug)
        with self._lock, self._connect(self._tenant_path(slug)) as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM memories ORDER BY updated_at DESC, id DESC"
                ).fetchall()
            ]

    def save_memory(self, slug: str, content: str, memory_id: str | None = None) -> dict:
        text = content.strip()
        if not text or len(text) > 2000:
            raise ValueError("Memory must contain 1 to 2000 characters")
        with self._lock:
            self._init_tenant_db(slug)
            with self._connect(self._tenant_path(slug)) as conn:
                if memory_id:
                    cur = conn.execute(
                        "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
                        (text, _now(), memory_id),
                    )
                    if not cur.rowcount:
                        raise KeyError(memory_id)
                else:
                    duplicate = conn.execute(
                        "SELECT * FROM memories WHERE content = ?", (text,)
                    ).fetchone()
                    if duplicate:
                        return dict(duplicate)
                    count = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
                    if count >= 200:
                        raise ValueError(
                            "Your memory notebook is full. Remove an old memory first."
                        )
                    memory_id = str(uuid4())
                    conn.execute(
                        "INSERT INTO memories VALUES (?, ?, ?, ?)",
                        (memory_id, text, _now(), _now()),
                    )
                return dict(
                    conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
                )

    def delete_memory(self, slug: str, memory_id: str) -> bool:
        with self._lock, self._connect(self._tenant_path(slug)) as conn:
            return bool(conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount)

    def recall(self, slug: str, query: str) -> list[dict]:
        # Bounded lexical recall; no external embedding service or shared Vault writes.
        tokens = set(re.findall(r"\w{3,}", query.casefold()))
        rows = self.memories(slug)
        rows.sort(
            key=lambda r: len(tokens & set(re.findall(r"\w{3,}", r["content"].casefold()))),
            reverse=True,
        )
        return rows[:8]

    def goals(self, slug: str) -> list[dict]:
        self._init_tenant_db(slug)
        with self._lock, self._connect(self._tenant_path(slug)) as conn:
            rows = [
                dict(r)
                for r in conn.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
            ]
            for row in rows:
                row["checkins"] = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM checkins WHERE goal_id = ? ORDER BY created_at DESC",
                        (row["id"],),
                    ).fetchall()
                ]
        return rows

    def create_goal(self, slug: str, title: str, next_step: str) -> dict:
        with self._lock:
            self._init_tenant_db(slug)
            with self._connect(self._tenant_path(slug)) as conn:
                if conn.execute("SELECT 1 FROM goals WHERE status = 'active'").fetchone():
                    raise ValueError("Complete your current goal before starting another.")
                goal_id = str(uuid4())
                conn.execute(
                    "INSERT INTO goals VALUES (?, ?, ?, 'active', ?)",
                    (goal_id, title.strip(), next_step.strip(), _now()),
                )
            return next(r for r in self.goals(slug) if r["id"] == goal_id)

    def checkin(self, slug: str, goal_id: str, note: str, next_step: str, complete: bool) -> dict:
        with self._lock, self._connect(self._tenant_path(slug)) as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND status = 'active'", (goal_id,)
            ).fetchone()
            if not row:
                raise KeyError(goal_id)
            conn.execute(
                "INSERT INTO checkins VALUES (?, ?, ?, ?)",
                (str(uuid4()), goal_id, note.strip(), _now()),
            )
            conn.execute(
                "UPDATE goals SET next_step = ?, status = ? WHERE id = ?",
                (next_step.strip(), "complete" if complete else "active", goal_id),
            )
        return next(r for r in self.goals(slug) if r["id"] == goal_id)

    def rotate_pin(self, slug: str, pin: str) -> bool:
        encoded = hash_pin(pin)
        with self._lock, self._connect(self.registry_path) as conn:
            return bool(
                conn.execute(
                    "UPDATE tenants SET pin_hash = ? WHERE slug = ? AND active = 1", (encoded, slug)
                ).rowcount
            )

    def export(self, slug: str) -> dict:
        with self._lock:
            prefs, memories, goals = self.preferences(slug), self.memories(slug), self.goals(slug)
            with self._connect(self._tenant_path(slug)) as conn:
                messages = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT role, content, created_at FROM messages ORDER BY rowid"
                    ).fetchall()
                ]
        return {
            "exported_at": _now(),
            "preferences": prefs,
            "memories": memories,
            "goals": goals,
            "messages": messages,
            "scope": "Mini data only; separately shared Vault Zeta records are not included.",
        }

    def erase(self, slug: str) -> bool:
        with self._lock:
            if self.get(slug) is None:
                return False
            # Keep a deactivated registry tombstone so an old personal link is never reassigned.
            path = self._tenant_path(slug)
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
            with self._connect(self.registry_path) as conn:
                conn.execute(
                    "UPDATE tenants SET active = 0, owner_name = '', pin_hash = '', "
                    "vault_enabled = 0 WHERE slug = ?",
                    (slug,),
                )
            return True
