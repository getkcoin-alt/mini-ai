"""Where Mini's models run: our own server ("local") or API providers ("api").

The super admin picks a global default and may override it per user. Only the
*infrastructure* changes; Mini's mind, prompts, single voice, safety rules and
limits are identical in both modes.

  local  faster-whisper + Ollama + Chatterbox on this server (as configured)
  api    Groq Whisper (hearing) + Groq / Gemini / OpenRouter (thinking) +
         hosted Chatterbox with Mini's same voice (Resemble)

Mini's voice is its own choice ("voice"): auto (follows the mode: Resemble in
API mode), server (always our Chatterbox), elevenlabs or resemble (that hosted
voice even when hearing/thinking stay on our server). A hosted voice that runs
out of credit or fails falls back to our server's voice.

Each stage falls back on its own: an API stage that is not configured or
fails uses the local model, and a local-mode session that would have to wait
for the busy local floor runs on the API instead (when the API is ready).
Events record stage/provider/error type only, never what anyone said.

API keys can be added from the Super admin card. They are kept in
infra-keys.json next to the settings, readable only by the worker user (0600,
the same protection as /etc/mini-ai/worker.env), override the environment, and
are never returned: the card sees only "added", where from, and the last 4.

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
               "model": "gemini-2.5-flash-lite"},
    # OpenRouter's own router picks a currently-working free model for each request.
    "openrouter": {"base": "https://openrouter.ai/api/v1", "key": "MINI_OPENROUTER_API_KEY",
                   "model": "openrouter/free"},
}
# Free models only (owner decision 2026-11-10). When the chosen model is rate
# limited on every key, try this lighter free model at the same provider first.
LIGHT_MODEL = {"groq": "llama-3.1-8b-instant"}
KEYS_PER_PROVIDER = 5  # e.g. several free Groq accounts: when one runs out, the next takes over
PROVIDER_ORDER = ("groq", "gemini", "openrouter")
STT_KEY = "MINI_GROQ_API_KEY"
STT_MODEL_DEFAULT = "whisper-large-v3-turbo"
TTS_KEYS = ("MINI_RESEMBLE_API_KEY", "MINI_RESEMBLE_VOICE_UUID")
VOICE_KEYS = {"resemble": TTS_KEYS, "elevenlabs": ("MINI_ELEVENLABS_API_KEY", "MINI_ELEVENLABS_VOICE_ID")}
VOICES = ("auto", "server", "elevenlabs", "resemble")
MAX_OVERRIDES = 100
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")
_EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$")

# Everything the admin may set from the card (values never leave the worker).
def _slot(base: str, n: int) -> str:
    return base if n == 1 else f"{base}_{n}"


SECRET_NAMES = {
    **{_slot(p["key"], n): {"label": f"{label} key {n}", "secret": True, "provider": name}
       for name, label, p in (("groq", "Groq", LLM_PROVIDERS["groq"]), ("gemini", "Gemini", LLM_PROVIDERS["gemini"]),
                              ("openrouter", "OpenRouter", LLM_PROVIDERS["openrouter"]))
       for n in range(1, KEYS_PER_PROVIDER + 1)},
    "MINI_RESEMBLE_API_KEY": {"label": "Resemble API key", "secret": True},
    "MINI_RESEMBLE_VOICE_UUID": {"label": "Mini's voice id at Resemble", "secret": False},
    "MINI_RESEMBLE_PROJECT_UUID": {"label": "Resemble project id (optional)", "secret": False},
    # One account only: rotating several free accounts breaks ElevenLabs' terms.
    "MINI_ELEVENLABS_API_KEY": {"label": "ElevenLabs API key", "secret": True, "provider": "elevenlabs"},
    "MINI_ELEVENLABS_VOICE_ID": {"label": "Mini's voice id at ElevenLabs", "secret": False, "provider": "elevenlabs"},
}
_VALUE_RE = re.compile(r"^[A-Za-z0-9._:/+=-]{8,400}$")

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


def _keys_path() -> Path:
    return _path().with_name("infra-keys.json")


_secret_cache: dict = {"mtime": None, "values": {}}


def _stored_secrets() -> dict:
    path = _keys_path()
    try:
        st = path.stat()
        mtime = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return {}
    if _secret_cache["mtime"] != mtime:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            values = {k: v for k, v in raw.items() if k in SECRET_NAMES and isinstance(v, str)}
        except (OSError, ValueError):
            values = {}
        _secret_cache.update(mtime=mtime, values=values)
    return dict(_secret_cache["values"])


def secret(name: str) -> str:
    """Admin-added value first, then the worker environment."""
    return (_stored_secrets().get(name) or os.environ.get(name, "")).strip()


def has(name: str) -> bool:
    return len(secret(name)) >= 8


def _write_secrets(values: dict) -> None:
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(values, fh)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    _secret_cache["mtime"] = None  # never serve a stale key after a change


def set_secret(name: str, value: str, *, by: str = "") -> None:
    if name not in SECRET_NAMES:
        raise SettingsError("unknown key name")
    value = (value or "").strip()
    if not _VALUE_RE.match(value):
        raise SettingsError("that does not look like a key (8-400 letters, digits or ._:/+=-)")
    with _lock:
        values = _stored_secrets()
        values[name] = value
        _write_secrets(values)
    record("key", "added", SECRET_NAMES[name]["label"], by=by)


def remove_secret(name: str, *, by: str = "") -> None:
    if name not in SECRET_NAMES:
        raise SettingsError("unknown key name")
    with _lock:
        values = _stored_secrets()
        values.pop(name, None)
        _write_secrets(values)
    record("key", "removed", SECRET_NAMES[name]["label"], by=by)


def key_summary() -> dict:
    """What the card may see about each key: never the value itself."""
    stored = _stored_secrets()
    out = {}
    for name, meta in SECRET_NAMES.items():
        value = secret(name)
        source = "admin" if stored.get(name) else ("server" if os.environ.get(name, "").strip() else None)
        entry = {"label": meta["label"], "set": bool(value), "source": source,
                 "provider": meta.get("provider", "resemble")}
        if value:
            entry["hint"] = ("…" + value[-4:]) if meta["secret"] else value
        out[name] = entry
    return out


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
    if "stt_model" in raw:
        stt = str(raw.get("stt_model") or "").strip()
        if stt and not _MODEL_RE.match(stt):
            raise SettingsError("stt_model has unexpected characters")
        out["stt_model"] = stt
    if raw.get("voice") not in (None, ""):
        if raw["voice"] not in VOICES:
            raise SettingsError("voice must be one of " + ", ".join(VOICES))
        out["voice"] = raw["voice"]
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


def provider_keys(provider: str) -> list[tuple[str, str]]:
    """(slot name, key) for every key added for this provider, in slot order."""
    base = LLM_PROVIDERS[provider]["key"]
    out = []
    for n in range(1, KEYS_PER_PROVIDER + 1):
        name = _slot(base, n)
        if has(name):
            out.append((name, secret(name)))
    return out


# Key health: a key that hit its limit rests, the next one is used meanwhile.
_cooling: dict[str, tuple[float, str]] = {}
_turn: dict[str, int] = {}


def usable_keys(provider: str) -> list[tuple[str, str]]:
    """Healthy keys, rotated so load spreads across accounts (per-minute limits)."""
    now = time.monotonic()
    with _lock:
        keys = [k for k in provider_keys(provider) if _cooling.get(k[0], (0, ""))[0] <= now]
        if not keys:
            return []
        start = _turn.get(provider, 0) % len(keys)
        _turn[provider] = start + 1
    return keys[start:] + keys[:start]


def rest_key(name: str, status: int, retry_after: float | None = None) -> None:
    """Let a key rest after a limit or auth failure (the value is never recorded)."""
    if status == 429:
        seconds, why = min(max(retry_after or 60.0, 5.0), 3600.0), "rate limited"
    elif status in (401, 403):
        seconds, why = 3600.0, "refused (check the key)"
    elif status == 402:
        seconds, why = 6 * 3600.0, "out of credit"
    else:
        seconds, why = 30.0, f"error {status}"
    with _lock:
        _cooling[name] = (time.monotonic() + seconds, why)
    record("key", "resting", SECRET_NAMES.get(name, {}).get("label", "key"), why)


def key_health() -> dict:
    now = time.monotonic()
    with _lock:
        return {name: {"resting_seconds": int(until - now), "why": why}
                for name, (until, why) in _cooling.items() if until > now}


def voice_ready(provider: str) -> bool:
    """A hosted voice has its key + voice id, and the key is not resting."""
    keys = VOICE_KEYS.get(provider)
    if not keys or not all(has(k) for k in keys):
        return False
    with _lock:
        return _cooling.get(keys[0], (0, ""))[0] <= time.monotonic()


def readiness() -> dict:
    """Which API stages have their keys (values are never returned)."""
    return {
        "stt": bool(provider_keys("groq")),
        "llm": {name: bool(provider_keys(name)) for name in LLM_PROVIDERS},
        "tts": voice_ready("resemble"),
        "voices": {name: voice_ready(name) for name in VOICE_KEYS},
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
    voice = choice.get("voice") or "auto"
    tts_provider = voice if voice in VOICE_KEYS else "resemble"
    hosted_voice = (voice in VOICE_KEYS or (voice == "auto" and api)) and ready["voices"][tts_provider]
    return {
        "chosen": choice["mode"],
        "stt": "api" if api and ready["stt"] else "local",
        # any provider with a key is enough: replies route across providers
        "llm": "api" if api and any(ready["llm"].values()) else "local",
        "tts": "api" if hosted_voice else "local",
        "voice": voice,
        "tts_provider": tts_provider,
        "llm_provider": provider,
        "llm_model": model,
        "stt_model": choice.get("stt_model") or STT_MODEL_DEFAULT,
        "overridden": bool(override),
    }


def api_fully_ready(plan: dict) -> bool:
    ready = readiness()
    if plan.get("voice") == "server":
        return False  # the admin wants our server's voice: wait for it rather than switch voices
    return ready["stt"] and any(ready["llm"].values()) and voice_ready(plan.get("tts_provider", "resemble"))


def llm_route(plan: dict) -> list[tuple[str, str]]:
    """(provider, model) attempts for one reply: chosen model, lighter free model, other providers."""
    ready = readiness()["llm"]
    first = plan["llm_provider"]
    route = []
    if ready.get(first):
        route.append((first, plan.get("llm_model") or LLM_PROVIDERS[first]["model"]))
        light = LIGHT_MODEL.get(first)
        if light and light != route[0][1]:
            route.append((first, light))
    for name in PROVIDER_ORDER:
        if name != first and ready.get(name):
            route.append((name, LLM_PROVIDERS[name]["model"]))
    return route


def as_api(plan: dict) -> dict:
    """Same plan with every stage on the API (used when the local floor is busy)."""
    return {**plan, "stt": "api", "llm": "api", "tts": "api"}


def uses_api(plan: dict) -> bool:
    """Runs without the local conversation floor (thinking happens on the API)."""
    return plan["llm"] == "api"


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
    return {"settings": load(), "readiness": readiness(), "keys": key_summary(), "key_health": key_health(),
            "providers": {
        name: {"default_model": p["model"]} for name, p in LLM_PROVIDERS.items()},
        "stt_model": load()["default"].get("stt_model") or STT_MODEL_DEFAULT,
        "api_sessions": active, "api_max_sessions": max_api_sessions(), "events": events}
