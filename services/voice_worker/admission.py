"""Who gets to talk to Mini, and for how long.

The CPU worker can hold ONE live conversation at a time. Everyone else waits
in a short first-come-first-served queue and is told their position. Each
person also has a per-conversation limit, an idle hang-up and a daily
allowance, so one user cannot block Mini for everybody.

Dependency-free (asyncio + sqlite3) so it can be unit-tested in CI.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def max_session_seconds() -> int:
    return _int_env("MINI_SESSION_MAX_SECONDS", 600)


def idle_seconds() -> int:
    return _int_env("MINI_SESSION_IDLE_SECONDS", 60)


def daily_seconds() -> int:
    return _int_env("MINI_DAILY_SECONDS", 1800)


def max_waiting() -> int:
    return _int_env("MINI_QUEUE_MAX", 5)


class ConversationFloor:
    """One holder at a time; FIFO waiters with live position updates."""

    def __init__(self):
        self.holder: str | None = None
        self._waiting: list[tuple[str, asyncio.Event]] = []

    @property
    def waiting(self) -> int:
        return len(self._waiting)

    def _kick(self):
        for _key, event in self._waiting:
            event.set()

    async def acquire(self, key: str, on_position: Callable[[int], Awaitable[None]],
                      limit: int | None = None) -> bool:
        """Wait for the floor. False if the queue is full. Cancellation-safe."""
        if self.holder is None and not self._waiting:
            self.holder = key
            return True
        if len(self._waiting) >= (max_waiting() if limit is None else limit):
            return False
        entry = (key, asyncio.Event())
        self._waiting.append(entry)
        last = None
        try:
            while True:
                if self.holder is None and self._waiting and self._waiting[0] is entry:
                    self._waiting.pop(0)
                    self.holder = key
                    self._kick()  # everyone behind moves up one place
                    return True
                position = self._waiting.index(entry) + 1
                if position != last:
                    last = position
                    await on_position(position)
                entry[1].clear()
                await entry[1].wait()
        finally:
            if entry in self._waiting:
                self._waiting.remove(entry)
                self._kick()

    def release(self, key: str):
        if self.holder == key:
            self.holder = None
            self._kick()


FLOOR = ConversationFloor()


class DailyUsage:
    """Seconds of live conversation per user per local day (IST by default)."""

    def __init__(self, path: Path | None = None):
        self.path = path

    def _db_path(self) -> Path:
        if self.path:
            return self.path
        base = Path(os.environ.get("MINI_VOICE_DATA_DIR") or (Path.home() / ".mini-ai" / "voice")).expanduser().parent
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        return base / "usage.sqlite3"

    def _connect(self):
        db = sqlite3.connect(str(self._db_path()), timeout=5)
        db.execute("CREATE TABLE IF NOT EXISTS usage (user_id TEXT NOT NULL, day TEXT NOT NULL, "
                   "seconds REAL NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day))")
        return db

    @staticmethod
    def today(now: float | None = None) -> str:
        offset = timedelta(minutes=_int_env("MINI_QUOTA_UTC_OFFSET_MINUTES", 330))
        moment = datetime.fromtimestamp(time.time() if now is None else now, tz=timezone.utc) + offset
        return moment.strftime("%Y-%m-%d")

    def used(self, user_id: str, now: float | None = None) -> float:
        with closing(self._connect()) as db:
            row = db.execute("SELECT seconds FROM usage WHERE user_id=? AND day=?",
                             (user_id, self.today(now))).fetchone()
        return float(row[0]) if row else 0.0

    def add(self, user_id: str, seconds: float, now: float | None = None):
        if seconds <= 0:
            return
        with closing(self._connect()) as db:
            db.execute("INSERT INTO usage (user_id, day, seconds) VALUES (?, ?, ?) "
                       "ON CONFLICT(user_id, day) DO UPDATE SET seconds = seconds + excluded.seconds",
                       (user_id, self.today(now), float(seconds)))
            db.execute("DELETE FROM usage WHERE day < ?", (self.today((now or time.time()) - 7 * 86400),))
            db.commit()

    def remaining(self, user_id: str, now: float | None = None) -> float:
        return max(0.0, daily_seconds() - self.used(user_id, now))


USAGE = DailyUsage()


class RateLimiter:
    """Sliding-window counter per key (in memory, per worker process)."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and hits[0] <= now - window_s:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


STARTS = RateLimiter()


class ConnectionCounter:
    """Open live connections per client IP."""

    def __init__(self):
        self._open: dict[str, int] = defaultdict(int)

    def try_open(self, ip: str, limit: int) -> bool:
        if self._open[ip] >= limit:
            return False
        self._open[ip] += 1
        return True

    def close(self, ip: str):
        if self._open.get(ip, 0) > 0:
            self._open[ip] -= 1
            if not self._open[ip]:
                del self._open[ip]


CONNECTIONS = ConnectionCounter()
