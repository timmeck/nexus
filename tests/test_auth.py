"""Tests for the Auth Layer — API key generation and HMAC signing."""

from __future__ import annotations

import time

from nexus.auth import generate_api_key, sign_request, verify_signature


class TestApiKeyGeneration:
    def test_key_has_prefix(self):
        key = generate_api_key()
        assert key.startswith("nxs_")

    def test_key_length(self):
        key = generate_api_key()
        assert len(key) == 4 + 64  # "nxs_" + 32 bytes hex

    def test_keys_are_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100


class TestHmacSigning:
    def test_sign_and_verify(self):
        key = generate_api_key()
        payload = '{"query": "hello world"}'
        headers = sign_request(payload, key)

        assert "X-Nexus-Timestamp" in headers
        assert "X-Nexus-Signature" in headers

        valid = verify_signature(payload, key, headers["X-Nexus-Timestamp"], headers["X-Nexus-Signature"])
        assert valid is True

    def test_wrong_key_fails(self):
        key1 = generate_api_key()
        key2 = generate_api_key()
        payload = '{"query": "test"}'
        headers = sign_request(payload, key1)

        valid = verify_signature(payload, key2, headers["X-Nexus-Timestamp"], headers["X-Nexus-Signature"])
        assert valid is False

    def test_tampered_payload_fails(self):
        key = generate_api_key()
        payload = '{"query": "original"}'
        headers = sign_request(payload, key)

        valid = verify_signature(
            '{"query": "tampered"}', key, headers["X-Nexus-Timestamp"], headers["X-Nexus-Signature"]
        )
        assert valid is False

    def test_expired_timestamp_fails(self):
        key = generate_api_key()
        payload = '{"query": "test"}'
        old_ts = int(time.time()) - 600  # 10 minutes ago
        headers = sign_request(payload, key, timestamp=old_ts)

        valid = verify_signature(
            payload,
            key,
            headers["X-Nexus-Timestamp"],
            headers["X-Nexus-Signature"],
            max_age_seconds=300,
        )
        assert valid is False

    def test_invalid_timestamp_fails(self):
        key = generate_api_key()
        valid = verify_signature("{}", key, "not-a-number", "somesig")
        assert valid is False

    def test_replay_same_signature_rejected(self):
        """Same signature used twice must be rejected (replay cache)."""
        from nexus.auth import _replay_cache

        _replay_cache.clear()  # Clean state

        key = generate_api_key()
        payload = '{"query": "replay test"}'
        headers = sign_request(payload, key)

        # First use — should pass
        valid1 = verify_signature(payload, key, headers["X-Nexus-Timestamp"], headers["X-Nexus-Signature"])
        assert valid1 is True

        # Second use — same signature, must fail
        valid2 = verify_signature(payload, key, headers["X-Nexus-Timestamp"], headers["X-Nexus-Signature"])
        assert valid2 is False

    def test_same_timestamp_different_payload_rejected(self):
        """Same timestamp + key but different payload must produce different signature.

        This tests that payload is properly bound to the signature scope.
        """
        from nexus.auth import _replay_cache

        _replay_cache.clear()

        key = generate_api_key()
        ts = int(time.time())

        headers1 = sign_request('{"query": "original"}', key, timestamp=ts)
        headers2 = sign_request('{"query": "tampered"}', key, timestamp=ts)

        # Signatures must be different (payload binding)
        assert headers1["X-Nexus-Signature"] != headers2["X-Nexus-Signature"]

        # First passes
        valid1 = verify_signature('{"query": "original"}', key, str(ts), headers1["X-Nexus-Signature"])
        assert valid1 is True

        # Second with different payload also passes (different signature)
        valid2 = verify_signature('{"query": "tampered"}', key, str(ts), headers2["X-Nexus-Signature"])
        assert valid2 is True

        # But replaying first signature with second payload fails (tampered)
        valid3 = verify_signature('{"query": "tampered"}', key, str(ts), headers1["X-Nexus-Signature"])
        assert valid3 is False
