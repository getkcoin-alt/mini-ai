"""Consent-based single-owner profile memory for the private Mini AI pilot.

Does not store conversation audio or transcripts. Multi-user separation is a
future milestone; remote gateway is currently restricted to the verified owner.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

FIELDS = {"name": 80, "miniName": 80, "relationship": 20, "tone": 20, "focus": 600, "boundaries": 600}


def db_path() -> Path:
    directory = Path(os.environ.get("MINI_VOICE_DATA_DIR") or (Path.home() / ".mini-ai" / "voice")).expanduser().parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory / "memory.sqlite3"


def connect():
    path = db_path()
    db = sqlite3.connect(str(path), timeout=5)
    db.execute("PRAGMA busy_timeout=3000")
    db.execute("CREATE TABLE IF NOT EXISTS owner_profile (id TEXT PRIMARY KEY, profile_json TEXT NOT NULL, updated_at TEXT NOT NULL)")
    path.chmod(0o600)
    return db


def get_profile():
    with connect() as db:
        row = db.execute("SELECT profile_json, updated_at FROM owner_profile WHERE id=?", ("primary",)).fetchone()
    if row is None:
        return {"saved": False, "profile": {}, "updatedAt": None}
    return {"saved": True, "profile": json.loads(row[0]), "updatedAt": row[1]}


def save_profile(payload: dict, consent: bool):
    if consent is not True:
        raise ValueError("Explicit permission to remember is required.")
    if not isinstance(payload, dict):
        raise ValueError("Profile must be an object.")
    if set(payload).difference(FIELDS):
        raise ValueError("Unknown profile fields were rejected.")
    profile = {}
    for field, limit in FIELDS.items():
        value = payload.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError("Invalid value for " + field)
        clean = " ".join(value.split())
        if clean:
            profile[field] = clean
    if len(json.dumps(profile)) > 2000:
        raise ValueError("Profile is too large.")
    updated = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute("INSERT INTO owner_profile(id, profile_json, updated_at) VALUES(?,?,?) "
                   "ON CONFLICT(id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at",
                   ("primary", json.dumps(profile, ensure_ascii=False), updated))
        db.commit()
    return {"saved": True, "profile": profile, "updatedAt": updated}


def delete_profile():
    with connect() as db:
        changed = db.execute("DELETE FROM owner_profile WHERE id=?", ("primary",)).rowcount
        db.commit()
    return {"deleted": bool(changed), "saved": False}
