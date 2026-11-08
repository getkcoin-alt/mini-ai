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
