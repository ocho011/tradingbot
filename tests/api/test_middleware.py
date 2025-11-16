"""
Tests for API security middleware.

Tests cover:
- Rate limiting middleware
- IP whitelist middleware
- Security headers middleware
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import (
    IPWhitelistMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    configure_security_middleware,
)
from src.core.security import SecurityManager

# ============================================================================
# Test Application Setup
# ============================================================================


@pytest.fixture
def app():
    """Create test FastAPI application."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"message": "success"}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "healthy"}

    return app


@pytest.fixture
def security_manager():
    """Create security manager for testing."""
    return SecurityManager(
        encryption_key="test-key-32-characters-minimum!",
        rate_limit_capacity=10,
        rate_limit_refill_rate=10.0,
        ip_whitelist=[
            "127.0.0.1",
            "192.168.1.1",
            "testclient",
        ],  # TestClient uses "testclient" as IP
    )


# ============================================================================
# Rate Limiting Middleware Tests
# ============================================================================


class TestRateLimitMiddleware:
    """Test rate limiting middleware."""

    def test_rate_limit_allows_within_limit(self, app, security_manager):
        """Test requests within rate limit are allowed."""
        app.add_middleware(RateLimitMiddleware, security_manager=security_manager, enabled=True)
        client = TestClient(app)

        # First 10 requests should succeed
        for _ in range(10):
            response = client.get("/test")
            assert response.status_code == 200

    def test_rate_limit_blocks_over_limit(self, app, security_manager):
        """Test requests over rate limit are blocked."""
        app.add_middleware(RateLimitMiddleware, security_manager=security_manager, enabled=True)
        client = TestClient(app)

        # Exhaust rate limit
        for _ in range(10):
            client.get("/test")

        # Next request should be rate limited
        response = client.get("/test")
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["error"]
        assert "Retry-After" in response.headers

    def test_rate_limit_headers_present(self, app, security_manager):
        """Test rate limit headers are added to responses."""
        app.add_middleware(RateLimitMiddleware, security_manager=security_manager, enabled=True)
        client = TestClient(app)

        response = client.get("/test")
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_rate_limit_disabled(self, app, security_manager):
        """Test rate limiting can be disabled."""
        app.add_middleware(RateLimitMiddleware, security_manager=security_manager, enabled=False)
        client = TestClient(app)

        # Should allow unlimited requests
        for _ in range(20):
            response = client.get("/test")
            assert response.status_code == 200


# ============================================================================
# IP Whitelist Middleware Tests
# ============================================================================


class TestIPWhitelistMiddleware:
    """Test IP whitelist middleware."""

    def test_whitelist_allows_whitelisted_ip(self, app, security_manager):
        """Test whitelisted IPs are allowed."""
        app.add_middleware(IPWhitelistMiddleware, security_manager=security_manager, enabled=True)
        client = TestClient(app)

        # TestClient uses 127.0.0.1 which is whitelisted
        response = client.get("/test")
        assert response.status_code == 200

    def test_whitelist_blocks_non_whitelisted_ip(self, app, security_manager):
        """Test non-whitelisted IPs are blocked."""
        # Modify security manager to have strict whitelist
        security_manager.ip_whitelist.clear()
        security_manager.ip_whitelist.add_ip("192.168.1.100")

        app.add_middleware(IPWhitelistMiddleware, security_manager=security_manager, enabled=True)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 403
        assert "Access forbidden" in response.json()["error"]

    def test_whitelist_bypass_paths(self, app, security_manager):
        """Test bypass paths are not checked against whitelist."""
        # Strict whitelist
        security_manager.ip_whitelist.clear()
        security_manager.ip_whitelist.add_ip("192.168.1.100")

        app.add_middleware(
            IPWhitelistMiddleware,
            security_manager=security_manager,
            enabled=True,
            bypass_paths=["/health"],
        )
        client = TestClient(app)

        # Health endpoint should bypass
        response = client.get("/health")
        assert response.status_code == 200

        # Other endpoints should be blocked
        response = client.get("/test")
        assert response.status_code == 403

    def test_whitelist_disabled(self, app, security_manager):
        """Test whitelist can be disabled."""
        app.add_middleware(IPWhitelistMiddleware, security_manager=security_manager, enabled=False)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200


# ============================================================================
# Security Headers Middleware Tests
# ============================================================================


class TestSecurityHeadersMiddleware:
    """Test security headers middleware."""

    def test_hsts_header_added(self, app):
        """Test HSTS header is added."""
        app.add_middleware(SecurityHeadersMiddleware, enable_hsts=True, hsts_max_age=31536000)
        client = TestClient(app)

        response = client.get("/test")
        assert "Strict-Transport-Security" in response.headers
        assert "max-age=31536000" in response.headers["Strict-Transport-Security"]
        assert "includeSubDomains" in response.headers["Strict-Transport-Security"]

    def test_csp_header_added(self, app):
        """Test CSP header is added."""
        csp_policy = "default-src 'self'; script-src 'self'"
        app.add_middleware(SecurityHeadersMiddleware, csp_policy=csp_policy)
        client = TestClient(app)

        response = client.get("/test")
        assert "Content-Security-Policy" in response.headers
        assert response.headers["Content-Security-Policy"] == csp_policy

    def test_all_security_headers_present(self, app):
        """Test all security headers are present."""
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)

        response = client.get("/test")

        expected_headers = [
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "X-XSS-Protection",
            "Referrer-Policy",
            "Permissions-Policy",
            "X-Permitted-Cross-Domain-Policies",
        ]

        for header in expected_headers:
            assert header in response.headers

    def test_x_frame_options(self, app):
        """Test X-Frame-Options header."""
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)

        response = client.get("/test")
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_x_content_type_options(self, app):
        """Test X-Content-Type-Options header."""
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)

        response = client.get("/test")
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_xss_protection(self, app):
        """Test X-XSS-Protection header."""
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)

        response = client.get("/test")
        assert response.headers["X-XSS-Protection"] == "1; mode=block"

    def test_referrer_policy(self, app):
        """Test Referrer-Policy header."""
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)

        response = client.get("/test")
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


# ============================================================================
# Combined Middleware Tests
# ============================================================================


class TestCombinedMiddleware:
    """Test combined security middleware configuration."""

    def test_configure_all_middleware(self, app, security_manager):
        """Test configuring all security middleware together."""
        configure_security_middleware(
            app=app,
            security_manager=security_manager,
            rate_limit_enabled=True,
            ip_whitelist_enabled=True,
            security_headers_enabled=True,
        )
        client = TestClient(app)

        response = client.get("/test")

        # Should have security headers
        assert "Strict-Transport-Security" in response.headers
        assert "X-Frame-Options" in response.headers

        # Should have rate limit headers
        assert "X-RateLimit-Limit" in response.headers

    def test_middleware_order(self, app, security_manager):
        """Test middleware are applied in correct order."""
        # Strict IP whitelist
        security_manager.ip_whitelist.clear()
        security_manager.ip_whitelist.add_ip("192.168.1.100")

        configure_security_middleware(
            app=app,
            security_manager=security_manager,
            rate_limit_enabled=True,
            ip_whitelist_enabled=True,
            security_headers_enabled=True,
        )
        client = TestClient(app)

        # IP whitelist should block before rate limiting
        response = client.get("/test")
        assert response.status_code == 403

        # Should not have rate limit headers (blocked before reaching rate limiter)
        assert "X-RateLimit-Limit" not in response.headers

        # Note: Security headers are not added when middleware returns early
        # This is expected behavior with FastAPI/Starlette middleware architecture


# ============================================================================
# Performance Tests
# ============================================================================


class TestMiddlewarePerformance:
    """Test middleware performance."""

    def test_middleware_overhead(self, app, security_manager):
        """Test middleware adds minimal overhead."""
        import time

        configure_security_middleware(
            app=app,
            security_manager=security_manager,
            rate_limit_enabled=True,
            ip_whitelist_enabled=False,
            security_headers_enabled=True,
        )
        client = TestClient(app)

        # Warm up
        for _ in range(10):
            client.get("/test")

        # Measure time for 100 requests
        start = time.time()
        for _ in range(100):
            client.get("/test")
        duration = time.time() - start

        # Should complete in reasonable time (< 1 second for 100 requests)
        assert duration < 1.0
