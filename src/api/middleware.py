"""
FastAPI Security Middleware.

Provides security middleware for:
- Rate limiting
- IP whitelisting
- Security headers
- Request validation
"""

import logging
from typing import Callable, Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.core.security import SecurityManager

logger = logging.getLogger(__name__)


# ============================================================================
# Rate Limiting Middleware
# ============================================================================


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using token bucket algorithm.

    Features:
    - Per-IP rate limiting
    - Per-endpoint configuration
    - Proper retry-after headers
    """

    def __init__(self, app: ASGIApp, security_manager: SecurityManager, enabled: bool = True):
        """
        Initialize rate limiting middleware.

        Args:
            app: ASGI application
            security_manager: Security manager instance
            enabled: Whether rate limiting is enabled
        """
        super().__init__(app)
        self.security_manager = security_manager
        self.enabled = enabled

        logger.info(f"Rate limiting middleware initialized: {'enabled' if enabled else 'disabled'}")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with rate limiting.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response
        """
        if not self.enabled:
            return await call_next(request)

        # Get client identifier (IP address)
        client_ip = request.client.host if request.client else "unknown"

        # Get endpoint path
        endpoint = request.url.path

        # Check rate limit
        allowed, retry_after = self.security_manager.rate_limiter.check_rate_limit(
            identifier=client_ip, endpoint=endpoint
        )

        if not allowed:
            logger.warning(
                f"Rate limit exceeded for {client_ip} on {endpoint}. "
                f"Retry after: {retry_after:.2f}s"
            )

            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Too many requests. Please retry after {retry_after:.2f} seconds",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        stats = self.security_manager.rate_limiter.get_stats(client_ip, endpoint)
        response.headers["X-RateLimit-Limit"] = str(int(stats["capacity"]))
        response.headers["X-RateLimit-Remaining"] = str(int(stats["available_tokens"]))
        response.headers["X-RateLimit-Reset"] = str(int(stats["refill_rate"]))

        return response


# ============================================================================
# IP Whitelist Middleware
# ============================================================================


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """
    IP whitelist middleware for access control.

    Features:
    - Configurable whitelist
    - Support for individual IPs and CIDR ranges
    - Bypass for health checks
    """

    def __init__(
        self,
        app: ASGIApp,
        security_manager: SecurityManager,
        enabled: bool = False,
        bypass_paths: Optional[list] = None,
    ):
        """
        Initialize IP whitelist middleware.

        Args:
            app: ASGI application
            security_manager: Security manager instance
            enabled: Whether IP whitelisting is enabled
            bypass_paths: Paths to bypass whitelist check (e.g., ["/health"])
        """
        super().__init__(app)
        self.security_manager = security_manager
        self.enabled = enabled
        self.bypass_paths = set(bypass_paths or ["/health", "/metrics"])

        logger.info(f"IP whitelist middleware initialized: {'enabled' if enabled else 'disabled'}")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with IP whitelist check.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response
        """
        if not self.enabled or not self.security_manager.ip_whitelist.is_enabled():
            return await call_next(request)

        # Check if path should bypass whitelist
        if request.url.path in self.bypass_paths:
            return await call_next(request)

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"

        # Check whitelist
        if not self.security_manager.ip_whitelist.is_allowed(client_ip):
            logger.warning(f"IP {client_ip} not in whitelist, denying access to {request.url.path}")

            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "Access forbidden",
                    "detail": f"IP address {client_ip} is not authorized to access this resource",
                },
            )

        return await call_next(request)


# ============================================================================
# Security Headers Middleware
# ============================================================================


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Security headers middleware.

    Adds comprehensive security headers to all responses:
    - HSTS (HTTP Strict Transport Security)
    - CSP (Content Security Policy)
    - X-Frame-Options
    - X-Content-Type-Options
    - X-XSS-Protection
    - Referrer-Policy
    - Permissions-Policy
    """

    def __init__(
        self,
        app: ASGIApp,
        enable_hsts: bool = True,
        hsts_max_age: int = 31536000,  # 1 year
        csp_policy: Optional[str] = None,
    ):
        """
        Initialize security headers middleware.

        Args:
            app: ASGI application
            enable_hsts: Enable HSTS header
            hsts_max_age: HSTS max-age in seconds
            csp_policy: Content Security Policy string
        """
        super().__init__(app)
        self.enable_hsts = enable_hsts
        self.hsts_max_age = hsts_max_age
        self.csp_policy = (
            csp_policy
            or "default-src 'self'; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:;"
        )

        logger.info("Security headers middleware initialized")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Add security headers to response.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response with security headers
        """
        response = await call_next(request)

        # HSTS - HTTP Strict Transport Security
        if self.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self.hsts_max_age}; includeSubDomains; preload"
            )

        # CSP - Content Security Policy
        response.headers["Content-Security-Policy"] = self.csp_policy

        # X-Frame-Options - Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # X-Content-Type-Options - Prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-XSS-Protection - Enable XSS filtering
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy - Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy - Control browser features
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # X-Permitted-Cross-Domain-Policies - Adobe products policy
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        return response


# ============================================================================
# Combined Security Middleware
# ============================================================================


def configure_security_middleware(
    app: ASGIApp,
    security_manager: SecurityManager,
    rate_limit_enabled: bool = True,
    ip_whitelist_enabled: bool = False,
    security_headers_enabled: bool = True,
) -> None:
    """
    Configure all security middleware for the application.

    Args:
        app: FastAPI application
        security_manager: Security manager instance
        rate_limit_enabled: Enable rate limiting
        ip_whitelist_enabled: Enable IP whitelisting
        security_headers_enabled: Enable security headers
    """
    # Add middleware in reverse order (last added is executed first)

    # Security headers (should be last to apply to all responses)
    if security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware)
        logger.info("Security headers middleware configured")

    # Rate limiting (executes after IP whitelist)
    if rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware, security_manager=security_manager, enabled=rate_limit_enabled
        )
        logger.info("Rate limiting middleware configured")

    # IP whitelist (executes first, before rate limiting)
    if ip_whitelist_enabled:
        app.add_middleware(
            IPWhitelistMiddleware, security_manager=security_manager, enabled=ip_whitelist_enabled
        )
        logger.info("IP whitelist middleware configured")

    logger.info("All security middleware configured successfully")
