"""Versioned, host-scoped acknowledgement of the Academy user agreement."""

import hashlib
import hmac
import time


VERSION = "2026-10-20"
COOKIE_NAME = "academy_terms"
MAX_AGE = 24 * 3600


def signed_acceptance(master_key: str, now: float | None = None) -> str:
    accepted_at = int(time.time() if now is None else now)
    message = f"{VERSION}:{accepted_at}"
    signature = hmac.new(bytes.fromhex(master_key), message.encode(), hashlib.sha256).hexdigest()
    return f"{VERSION}.{accepted_at}.{signature}"


def accepted_at(cookie: str, master_key: str, now: float | None = None) -> int | None:
    try:
        version, timestamp, signature = cookie.split(".", 2)
        accepted = int(timestamp)
        current = time.time() if now is None else now
        if version != VERSION or accepted > current or current - accepted > MAX_AGE:
            return None
        message = f"{version}:{accepted}"
        expected = hmac.new(bytes.fromhex(master_key), message.encode(), hashlib.sha256).hexdigest()
        return accepted if hmac.compare_digest(signature, expected) else None
    except (ValueError, TypeError):
        return None
