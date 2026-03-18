"""Authentication Layer — API key management, HMAC signing, replay protection."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections import OrderedDict

log = logging.getLogger("nexus.auth")

# Key prefix for easy identification
KEY_PREFIX = "nxs_"
KEY_LENGTH = 32

# Replay cache: stores seen signatures to prevent reuse within the time window.
# Max size prevents unbounded memory growth.
_REPLAY_CACHE_MAX = 10000
_replay_cache: OrderedDict[str, float] = OrderedDict()


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

    Three-layer replay protection:
    1. Timestamp freshness (max_age_seconds window)
    2. Signature correctness (HMAC-SHA256)
    3. Replay cache (same signature rejected within window)
    """
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        log.warning("Invalid timestamp in signature verification")
        return False

    # Layer 1: Check timestamp freshness
    age = abs(int(time.time()) - ts)
    if age > max_age_seconds:
        log.warning("Signature too old: %d seconds", age)
        return False

    # Layer 2: Verify HMAC
    message = f"{ts}.{payload}".encode()
    expected = hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False

    # Layer 3: Replay cache — reject if same signature seen before
    if signature in _replay_cache:
        log.warning("Replay detected: signature already used")
        return False

    # Store in cache
    _replay_cache[signature] = time.time()

    # Evict old entries
    _evict_replay_cache(max_age_seconds)

    return True


def _evict_replay_cache(max_age: int) -> None:
    """Remove expired entries from replay cache."""
    now = time.time()
    while _replay_cache:
        oldest_sig, oldest_time = next(iter(_replay_cache.items()))
        if now - oldest_time > max_age:
            _replay_cache.pop(oldest_sig)
        else:
            break

    # Hard cap on size
    while len(_replay_cache) > _REPLAY_CACHE_MAX:
        _replay_cache.popitem(last=False)
