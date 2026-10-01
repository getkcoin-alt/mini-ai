from __future__ import annotations

import hashlib
import hmac
import secrets

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def generate_pin() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def validate_pin(pin: str) -> str:
    value = (pin or "").strip()
    if not value.isdigit() or not 4 <= len(value) <= 12:
        raise ValueError("PIN must contain 4 to 12 digits")
    return value


def hash_pin(pin: str) -> str:
    value = validate_pin(pin)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        value.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            (pin or "").encode(),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected)),
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (TypeError, ValueError):
        return False

