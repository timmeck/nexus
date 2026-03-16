"""Authentication Layer — API key management and HMAC request signing."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

log = logging.getLogger("nexus.auth")

# Key prefix for easy identification
KEY_PREFIX = "nxs_"
KEY_LENGTH = 32


def generate_api_key() -> str:
    """Generate a new API key for an agent."""
    return KEY_PREFIX + secrets.token_hex(KEY_LENGTH)


def sign_request(payload: str, api_key: str, timestamp: int | None = None) -> dict:
    """Create HMAC-SHA256 signature for a request payload.

    Returns a dict with the headers to attach to the outgoing request.
    """
    ts = timestamp or int(time.time())
    message = f"{ts}.{payload}".encode()
    signature = hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    return {
        "X-Nexus-Timestamp": str(ts),
        "X-Nexus-Signature": signature,
    }


def verify_signature(
    payload: str,
    api_key: str,
    timestamp: str,
    signature: str,
    max_age_seconds: int = 300,
) -> bool:
    """Verify an HMAC-SHA256 signature from an incoming request.

    Returns True if the signature is valid and the timestamp is fresh.
    """
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        log.warning("Invalid timestamp in signature verification")
        return False

    # Check for replay attacks
    age = abs(int(time.time()) - ts)
    if age > max_age_seconds:
        log.warning("Signature too old: %d seconds", age)
        return False

    message = f"{ts}.{payload}".encode()
    expected = hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
