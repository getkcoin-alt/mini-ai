"""Where Mini's models run: our own server ("local") or API providers ("api").

The super admin picks a global default and may override it per user. Only the
*infrastructure* changes; Mini's mind, prompts, single voice, safety rules and
limits are identical in both modes.

  local  faster-whisper + Ollama + Chatterbox on this server (as configured)
  api    Groq Whisper (hearing) + Groq / Gemini / OpenRouter (thinking) +
         hosted Chatterbox with Mini's same voice (Resemble)

Each stage falls back on its own: an API stage that is not configured or
fails uses the local model, and a local-mode session that would have to wait
for the busy local floor runs on the API instead (when the API is ready).
Events record stage/provider/error type only, never what anyone said.

Dependency-free so it can be unit-tested in CI.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from pathlib import Path

MODES = ("local", "api")
LLM_PROVIDERS = {
    "groq": {"base": "https://api.groq.com/openai/v1", "key": "MINI_GROQ_API_KEY",
             "model": "llama-3.3-70b-versatile"},
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta/openai", "key": "MINI_GEMINI_API_KEY",
               "model": "gemini-2.5-flash"},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "key": "MINI_OPENROUTER_API_KEY",
                   "model": "meta-llama/llama-3.3-70b-instruct"},
}
STT_KEY = "MINI_GROQ_API_KEY"
STT_MODEL_DEFAULT = "whisper-large-v3-turbo"
TTS_KEYS = ("MINI_RESEMBLE_API_KEY", "MINI_RESEMBLE_VOICE_UUID")
MAX_OVERRIDES = 100
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")
_EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$")

DEFAULT_SETTINGS = {"default": {"mode": "local", "llm_provider": "groq", "llm_model": ""}, "users": {}}

_lock = threading.Lock()
_events: deque = deque(maxlen=60)
_api_sessions = 0


class SettingsError(ValueError):
    pass


def _path() -> Path:
    if os.environ.get("MINI_INFRA_FILE"):
        return Path(os.environ["MINI_INFRA_FILE"])
    base = Path(os.environ.get("MINI_VOICE_DATA_DIR") or (Path.home() / ".mini-ai" / "voice")).expanduser().parent
    return base / "infra.json"


def has(name: str) -> bool:
    return len(os.environ.get(name, "").strip()) >= 8


def _clean_choice(raw, *, partial: bool) -> dict:
    if not isinstance(raw, dict):
        raise SettingsError("settings must be an object")
    out = {}
    if "mode" in raw or not partial:
        if raw.get("mode") not in MODES:
            raise SettingsError("mode must be local or api")
        out["mode"] = raw["mode"]
    if "llm_provider" in raw or not partial:
        if raw.get("llm_provider") not in LLM_PROVIDERS:
            raise SettingsError("llm_provider must be one of " + ", ".join(LLM_PROVIDERS))
        out["llm_provider"] = raw["llm_provider"]
    if "llm_model" in raw or not partial:
        model = str(raw.get("llm_model") or "").strip()
        if model and not _MODEL_RE.match(model):
            raise SettingsError("llm_model has unexpected characters")
        out["llm_model"] = model
    return out


def validate(raw) -> dict:
    """Return a clean settings document or raise SettingsError."""
    if not isinstance(raw, dict):
        raise SettingsError("settings must be an object")
    default = _clean_choice(raw.get("default"), partial=False)
    users_in = raw.get("users") or {}
    if not isinstance(users_in, dict) or len(users_in) > MAX_OVERRIDES:
        raise SettingsError(f"users must be an object with at most {MAX_OVERRIDES} entries")
    users = {}
    for email, choice in users_in.items():
        email = str(email).strip().lower()
        if not _EMAIL_RE.match(email):
            raise SettingsError(f"not an email: {email[:60]}")
        clean = _clean_choice(choice, partial=True)
        if clean:
            users[email] = clean
    return {"default": default, "users": users}


def load() -> dict:
    try:
        return validate(json.loads(_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_SETTINGS))


def save(raw, *, by: str = "") -> dict:
    clean = validate(raw)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(clean, indent=1, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    record("settings", "saved", by=by)
    return clean


def readiness() -> dict:
    """Which API stages have their keys (values are never returned)."""
    return {
        "stt": has(STT_KEY),
        "llm": {name: has(p["key"]) for name, p in LLM_PROVIDERS.items()},
        "tts": all(has(k) for k in TTS_KEYS),
    }


def resolve(email: str | None, settings: dict | None = None) -> dict:
    """The plan for one session: what the admin chose, then what is actually usable."""
    settings = settings or load()
    choice = dict(settings["default"])
    override = settings["users"].get((email or "").strip().lower())
    if override:
        choice.update(override)
    provider = choice["llm_provider"]
    model = choice.get("llm_model") or LLM_PROVIDERS[provider]["model"]
    ready = readiness()
    api = choice["mode"] == "api"
    return {
        "chosen": choice["mode"],
        "stt": "api" if api and ready["stt"] else "local",
        "llm": "api" if api and ready["llm"][provider] else "local",
        "tts": "api" if api and ready["tts"] else "local",
        "llm_provider": provider,
        "llm_model": model,
        "overridden": bool(override),
    }


def api_fully_ready(plan: dict) -> bool:
    ready = readiness()
    return ready["stt"] and ready["llm"].get(plan["llm_provider"], False) and ready["tts"]


def as_api(plan: dict) -> dict:
    """Same plan with every stage on the API (used when the local floor is busy)."""
    return {**plan, "stt": "api", "llm": "api", "tts": "api"}


def uses_api(plan: dict) -> bool:
    return plan["llm"] == "api" or plan["tts"] == "api"


def max_api_sessions() -> int:
    try:
        return max(1, int(os.environ.get("MINI_API_MAX_SESSIONS", "10")))
    except ValueError:
        return 10


def claim_api_session() -> bool:
    global _api_sessions
    with _lock:
        if _api_sessions >= max_api_sessions():
            return False
        _api_sessions += 1
        return True


def release_api_session() -> None:
    global _api_sessions
    with _lock:
        _api_sessions = max(0, _api_sessions - 1)


def record(kind: str, stage: str, provider: str = "", error: str = "", by: str = "") -> None:
    """Admin-visible event. Never pass transcripts or user text here."""
    event = {"at": int(time.time()), "kind": kind, "stage": stage}
    if provider:
        event["provider"] = provider[:40]
    if error:
        event["error"] = error[:80]
    if by:
        event["by"] = by[:120]
    with _lock:
        _events.append(event)


def status() -> dict:
    with _lock:
        events = list(_events)[::-1]
        active = _api_sessions
    return {"settings": load(), "readiness": readiness(), "providers": {
        name: {"default_model": p["model"]} for name, p in LLM_PROVIDERS.items()},
        "stt_model": os.environ.get("MINI_GROQ_STT_MODEL", STT_MODEL_DEFAULT),
        "api_sessions": active, "api_max_sessions": max_api_sessions(), "events": events}
