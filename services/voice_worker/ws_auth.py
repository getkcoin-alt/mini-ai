"""Authentication decisions for the private voice worker.

Kept free of FastAPI/model imports so the rules can be unit-tested in
lightweight CI. Every function fails closed.
"""
from __future__ import annotations

import hmac
import os
from urllib.parse import urlsplit

LOOPBACK_CLIENTS = ("127.0.0.1", "::1")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
MIN_SECRET_LENGTH = 32


def worker_token_ok(supplied: str | None) -> bool:
    """Service-to-service token required on every /v1/* route."""
    expected = os.environ.get("MINI_WORKER_TOKEN", "")
    return (len(expected) >= MIN_SECRET_LENGTH and isinstance(supplied, str) and bool(supplied)
            and hmac.compare_digest(expected.encode(), supplied.encode()))


def local_connection_error(client_host: str, requested_host: str, port: int | None,
                           origin: str | None, allowed_schemes: tuple[str, ...] = ("http",)) -> str | None:
    """Return a refusal reason unless this is a direct loopback request.

    A reverse proxy exposing the worker publicly must never reach the
    uncredentialed local preview routes.
    """
    if client_host not in LOOPBACK_CLIENTS or (requested_host or "").lower() not in LOOPBACK_HOSTS:
        return "This preview endpoint is localhost-only."
    if origin:
        try:
            parsed = urlsplit(origin)
            if (parsed.scheme not in allowed_schemes or parsed.hostname != (requested_host or "").lower()
                    or parsed.port != port):
                return "Cross-origin access denied."
        except ValueError:
            return "Invalid request origin."
    return None


def local_dev_identity(access_token: str | None, allow_local_dev: bool) -> dict | None:
    """Optional identity for loopback end-to-end tests only.

    Enabled only when the operator sets MINI_REALTIME_DEV_TOKEN (32+ chars)
    on the worker, the caller presents exactly that value, AND the session
    arrived through the loopback-only preview route. Never valid on /v1/*.
    """
    expected = os.environ.get("MINI_REALTIME_DEV_TOKEN", "")
    if (not allow_local_dev or len(expected) < MIN_SECRET_LENGTH or not isinstance(access_token, str)
            or not hmac.compare_digest(expected.encode(), access_token.encode())):
        return None
    return {"id": "local-dev-owner", "role": "local-dev"}


def browser_origin_refused(path: str, origin: str | None) -> bool:
    """CORS policy for the public worker domain: server-to-server only.

    /v1/* is called by the Vercel gateway (no Origin header). Browsers always
    send Origin on cross-origin fetch and on every WebSocket handshake, so any
    /v1 request carrying one is refused. No Access-Control-* headers are ever
    emitted, so browsers also block reading responses.
    """
    return path.startswith("/v1/") and bool(origin)


# --- Browser live voice (Phase A) -------------------------------------------
# The browser cannot hold the worker token, and Vercel functions cannot proxy
# WebSockets. Vercel therefore issues the signed-in owner a short-lived ticket
# signed with the shared worker token, and the browser connects straight to
# /v1/realtime/browser. The worker also re-verifies the Supabase session and
# requires both to name the same user.

TICKET_CONTEXT = b"mini.realtime.ticket.v1."
TICKET_MAX_TTL = 300
_USED_NONCES: dict[str, int] = {}


def realtime_origin_allowed(origin: str | None) -> bool:
    allowed = {o.strip().rstrip("/") for o in os.environ.get("MINI_REALTIME_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    return bool(origin) and origin.rstrip("/") in allowed


def _b64url_decode(value: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_realtime_ticket(ticket: str | None, now: float | None = None) -> str | None:
    """Return the ticket's user id if it is authentic, unexpired and unused."""
    import json
    import time
    secret = os.environ.get("MINI_WORKER_TOKEN", "")
    if len(secret) < MIN_SECRET_LENGTH or not isinstance(ticket, str) or len(ticket) > 1024 or ticket.count(".") != 1:
        return None
    payload_b64, sig_b64 = ticket.split(".")
    expected = hmac.new(secret.encode(), TICKET_CONTEXT + payload_b64.encode(), "sha256").digest()
    try:
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError):
        return None
    now = time.time() if now is None else now
    sub, exp, nonce = payload.get("sub"), payload.get("exp"), payload.get("nonce")
    if (not isinstance(sub, str) or not sub or not isinstance(exp, int) or not isinstance(nonce, str)
            or not 16 <= len(nonce) <= 64 or exp <= now or exp > now + TICKET_MAX_TTL):
        return None
    for old, old_exp in list(_USED_NONCES.items()):
        if old_exp <= now:
            del _USED_NONCES[old]
    if nonce in _USED_NONCES:
        return None
    _USED_NONCES[nonce] = exp
    return sub
