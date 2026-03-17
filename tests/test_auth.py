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
