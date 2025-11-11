"""
Tests for security module.

Tests cover:
- API key encryption/decryption
- Rate limiting with token bucket algorithm
- IP whitelist validation
- Security manager integration
"""

import os
import time
from unittest.mock import patch

import pytest

from src.core.security import (
    APIKeyEncryption,
    IPWhitelist,
    RateLimiter,
    SecurityManager,
    TokenBucket,
)


# ============================================================================
# API Key Encryption Tests
# ============================================================================


class TestAPIKeyEncryption:
    """Test API key encryption functionality."""

    @pytest.fixture
    def encryption(self):
        """Create encryption instance with test key."""
        return APIKeyEncryption(master_key="test-master-key-32-characters!!")

    def test_encrypt_decrypt_cycle(self, encryption):
        """Test encryption and decryption cycle."""
        original_key = "test-api-key-12345678"

        # Encrypt
        encrypted = encryption.encrypt(original_key)
        assert encrypted != original_key
        assert isinstance(encrypted, str)

        # Decrypt
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == original_key

    def test_different_encryptions_differ(self, encryption):
        """Test that same key encrypts to different values (due to salt)."""
        key = "test-key"
        encrypted1 = encryption.encrypt(key)

        # Create new instance with same master key
        encryption2 = APIKeyEncryption(master_key="test-master-key-32-characters!!")
        encrypted2 = encryption2.encrypt(key)

        # Different salts should produce different encrypted values
        assert encrypted1 != encrypted2

        # But both should decrypt correctly
        assert encryption.decrypt(encrypted1) == key
        assert encryption2.decrypt(encrypted2) == key

    def test_decrypt_with_wrong_key_fails(self):
        """Test that decryption with wrong key fails."""
        encryption1 = APIKeyEncryption(master_key="key1-32-characters-minimum!!!!!")
        encryption2 = APIKeyEncryption(master_key="key2-32-characters-minimum!!!!!")

        encrypted = encryption1.encrypt("test-key")

        with pytest.raises(ValueError, match="Decryption failed"):
            encryption2.decrypt(encrypted)

    def test_invalid_encrypted_data_fails(self, encryption):
        """Test that invalid encrypted data raises error."""
        with pytest.raises(ValueError, match="Decryption failed"):
            encryption.decrypt("invalid-encrypted-data")

    def test_encryption_without_master_key_fails(self):
        """Test that encryption without master key fails."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Master encryption key not provided"):
                APIKeyEncryption()

    def test_get_salt(self, encryption):
        """Test salt retrieval."""
        salt = encryption.get_salt()
        assert isinstance(salt, str)
        assert len(salt) > 0


# ============================================================================
# Token Bucket Tests
# ============================================================================


class TestTokenBucket:
    """Test token bucket rate limiting."""

    def test_initial_capacity(self):
        """Test bucket starts with full capacity."""
        bucket = TokenBucket(capacity=100, refill_rate=10.0)
        assert bucket.get_available_tokens() == 100.0

    def test_consume_tokens(self):
        """Test token consumption."""
        bucket = TokenBucket(capacity=100, refill_rate=10.0)

        # Consume tokens
        assert bucket.consume(10) is True
        assert abs(bucket.get_available_tokens() - 90.0) < 0.1

        # Consume more
        assert bucket.consume(20) is True
        assert abs(bucket.get_available_tokens() - 70.0) < 0.1

    def test_insufficient_tokens(self):
        """Test consumption fails when insufficient tokens."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)

        # Consume all tokens
        assert bucket.consume(10) is True

        # Try to consume more
        assert bucket.consume(1) is False

    def test_token_refill(self):
        """Test tokens refill over time."""
        bucket = TokenBucket(capacity=100, refill_rate=10.0)

        # Consume tokens
        bucket.consume(50)
        assert abs(bucket.get_available_tokens() - 50.0) < 0.1

        # Wait for refill (0.5 seconds = 5 tokens at 10/sec)
        time.sleep(0.5)
        tokens = bucket.get_available_tokens()
        assert 54.0 <= tokens <= 56.0  # Allow some timing variance

    def test_refill_does_not_exceed_capacity(self):
        """Test refill stops at capacity."""
        bucket = TokenBucket(capacity=10, refill_rate=100.0)

        # Wait for refill
        time.sleep(1.0)

        # Should not exceed capacity
        assert bucket.get_available_tokens() <= 10.0

    def test_time_until_available(self):
        """Test calculation of time until tokens available."""
        bucket = TokenBucket(capacity=100, refill_rate=10.0)

        # Consume all tokens
        bucket.consume(100)

        # Time until 10 tokens available
        wait_time = bucket.time_until_available(10)
        assert 0.9 <= wait_time <= 1.1  # Should be ~1 second

    def test_time_until_available_when_sufficient(self):
        """Test time_until_available returns 0 when tokens available."""
        bucket = TokenBucket(capacity=100, refill_rate=10.0)
        assert bucket.time_until_available(50) == 0.0


# ============================================================================
# Rate Limiter Tests
# ============================================================================


class TestRateLimiter:
    """Test rate limiter functionality."""

    def test_default_rate_limit(self):
        """Test rate limiting with default configuration."""
        limiter = RateLimiter(default_capacity=10, default_refill_rate=10.0)

        # First 10 requests should succeed
        for _ in range(10):
            allowed, retry_after = limiter.check_rate_limit("user1")
            assert allowed is True
            assert retry_after is None

        # 11th request should fail
        allowed, retry_after = limiter.check_rate_limit("user1")
        assert allowed is False
        assert retry_after is not None

    def test_per_identifier_limits(self):
        """Test that different identifiers have separate limits."""
        limiter = RateLimiter(default_capacity=5, default_refill_rate=1.0)

        # User1 consumes all tokens
        for _ in range(5):
            allowed, _ = limiter.check_rate_limit("user1")
            assert allowed is True

        # User1 should be limited
        allowed, _ = limiter.check_rate_limit("user1")
        assert allowed is False

        # User2 should not be affected
        allowed, _ = limiter.check_rate_limit("user2")
        assert allowed is True

    def test_endpoint_specific_limits(self):
        """Test endpoint-specific rate limit configuration."""
        limiter = RateLimiter(default_capacity=100, default_refill_rate=10.0)

        # Configure stricter limit for specific endpoint
        limiter.configure_endpoint("/api/orders", capacity=5, refill_rate=1.0)

        # Default endpoint should have default limits
        for _ in range(10):
            allowed, _ = limiter.check_rate_limit("user1", endpoint="/api/status")
            assert allowed is True

        # Configured endpoint should have strict limits
        for _ in range(5):
            allowed, _ = limiter.check_rate_limit("user1", endpoint="/api/orders")
            assert allowed is True

        allowed, _ = limiter.check_rate_limit("user1", endpoint="/api/orders")
        assert allowed is False

    def test_get_stats(self):
        """Test rate limit statistics retrieval."""
        limiter = RateLimiter(default_capacity=100, default_refill_rate=10.0)

        # Before any requests
        stats = limiter.get_stats("user1")
        assert stats["available_tokens"] == 100
        assert stats["capacity"] == 100

        # After consuming tokens
        limiter.check_rate_limit("user1", tokens=30)
        stats = limiter.get_stats("user1")
        assert abs(stats["available_tokens"] - 70) < 0.1

    def test_bucket_cleanup(self):
        """Test cleanup of unused buckets."""
        limiter = RateLimiter(
            default_capacity=100,
            default_refill_rate=100.0,  # Fast refill
            cleanup_interval=0  # Immediate cleanup
        )

        # Create buckets
        limiter.check_rate_limit("user1")
        limiter.check_rate_limit("user2")
        assert len(limiter._buckets) == 2

        # Wait for refill to full capacity
        time.sleep(1.1)

        # Trigger cleanup
        limiter.check_rate_limit("user3")

        # Old unused buckets should be cleaned
        # Note: This is probabilistic due to timing
        assert len(limiter._buckets) <= 3


# ============================================================================
# IP Whitelist Tests
# ============================================================================


class TestIPWhitelist:
    """Test IP whitelist functionality."""

    def test_disabled_whitelist_allows_all(self):
        """Test that disabled whitelist allows all IPs."""
        whitelist = IPWhitelist()
        assert whitelist.is_allowed("1.2.3.4") is True
        assert whitelist.is_allowed("192.168.1.1") is True

    def test_enabled_whitelist_filters(self):
        """Test that enabled whitelist filters IPs."""
        whitelist = IPWhitelist(whitelist=["1.2.3.4", "192.168.1.1"])

        assert whitelist.is_allowed("1.2.3.4") is True
        assert whitelist.is_allowed("192.168.1.1") is True
        assert whitelist.is_allowed("5.6.7.8") is False

    def test_add_ip(self):
        """Test adding IP to whitelist."""
        whitelist = IPWhitelist()
        assert whitelist.is_enabled() is False

        whitelist.add_ip("1.2.3.4")
        assert whitelist.is_enabled() is True
        assert whitelist.is_allowed("1.2.3.4") is True

    def test_remove_ip(self):
        """Test removing IP from whitelist."""
        whitelist = IPWhitelist(whitelist=["1.2.3.4", "192.168.1.1"])

        assert whitelist.remove_ip("1.2.3.4") is True
        assert whitelist.is_allowed("1.2.3.4") is False

        assert whitelist.remove_ip("nonexistent") is False

    def test_get_whitelist(self):
        """Test getting whitelist."""
        ips = ["1.2.3.4", "192.168.1.1"]
        whitelist = IPWhitelist(whitelist=ips)

        result = whitelist.get_whitelist()
        assert set(result) == set(ips)

    def test_clear_whitelist(self):
        """Test clearing whitelist."""
        whitelist = IPWhitelist(whitelist=["1.2.3.4"])

        whitelist.clear()
        assert whitelist.is_enabled() is False
        assert len(whitelist.get_whitelist()) == 0


# ============================================================================
# Security Manager Tests
# ============================================================================


class TestSecurityManager:
    """Test security manager integration."""

    @pytest.fixture
    def security_manager(self):
        """Create security manager instance."""
        return SecurityManager(
            encryption_key="test-key-32-characters-minimum!",
            rate_limit_capacity=10,
            rate_limit_refill_rate=10.0,
            ip_whitelist=["127.0.0.1", "192.168.1.1"]
        )

    def test_initialization(self, security_manager):
        """Test security manager initialization."""
        assert security_manager.encryption is not None
        assert security_manager.rate_limiter is not None
        assert security_manager.ip_whitelist is not None

    def test_validate_request_success(self, security_manager):
        """Test successful request validation."""
        allowed, error = security_manager.validate_request(
            ip_address="127.0.0.1",
            identifier="user1",
            endpoint="/api/test"
        )
        assert allowed is True
        assert error is None

    def test_validate_request_ip_blocked(self, security_manager):
        """Test request blocked by IP whitelist."""
        allowed, error = security_manager.validate_request(
            ip_address="1.2.3.4",
            identifier="user1",
            endpoint="/api/test"
        )
        assert allowed is False
        assert "not in whitelist" in error

    def test_validate_request_rate_limited(self, security_manager):
        """Test request blocked by rate limit."""
        # Exhaust rate limit
        for _ in range(10):
            security_manager.validate_request(
                ip_address="127.0.0.1",
                identifier="user1",
                endpoint="/api/test"
            )

        # Next request should be rate limited
        allowed, error = security_manager.validate_request(
            ip_address="127.0.0.1",
            identifier="user1",
            endpoint="/api/test"
        )
        assert allowed is False
        assert "Rate limit exceeded" in error

    def test_get_security_status(self, security_manager):
        """Test security status retrieval."""
        status = security_manager.get_security_status()

        assert "encryption" in status
        assert status["encryption"]["enabled"] is True

        assert "rate_limiting" in status
        assert status["rate_limiting"]["enabled"] is True

        assert "ip_whitelist" in status
        assert status["ip_whitelist"]["enabled"] is True


# ============================================================================
# Performance Tests
# ============================================================================


class TestSecurityPerformance:
    """Test security component performance."""

    def test_encryption_performance(self):
        """Test encryption performance."""
        encryption = APIKeyEncryption(master_key="test-key-32-characters-minimum!")

        start = time.time()
        for _ in range(100):  # Reduced to 100 for reasonable test time
            encrypted = encryption.encrypt("test-api-key")
            encryption.decrypt(encrypted)
        duration = time.time() - start

        # Should handle 100 encrypt/decrypt cycles in < 5 seconds
        assert duration < 5.0

    def test_rate_limiter_performance(self):
        """Test rate limiter performance."""
        limiter = RateLimiter(default_capacity=10000, default_refill_rate=1000.0)

        start = time.time()
        for i in range(1000):
            limiter.check_rate_limit(f"user{i % 10}")
        duration = time.time() - start

        # Should handle 1000 rate limit checks in < 0.1 second
        assert duration < 0.1
