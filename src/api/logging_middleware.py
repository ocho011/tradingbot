"""
Logging Middleware for FastAPI.

Provides automatic request/response logging with contextual information.
"""

import logging
import time
import uuid
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.core.logging_config import clear_request_context, set_request_context

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests and responses with context.

    Automatically:
    - Generates and tracks request IDs
    - Logs request details (method, path, headers)
    - Logs response details (status code, duration)
    - Sets logging context variables for downstream logging
    """

    def __init__(
        self,
        app: ASGIApp,
        excluded_paths: Optional[list] = None,
    ):
        """
        Initialize logging middleware.

        Args:
            app: ASGI application
            excluded_paths: List of paths to exclude from logging (e.g., ["/health", "/metrics"])
        """
        super().__init__(app)
        self.excluded_paths = excluded_paths or []

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and log details.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response from downstream handlers
        """
        # Skip logging for excluded paths
        if any(request.url.path.startswith(path) for path in self.excluded_paths):
            return await call_next(request)

        # Generate request ID
        request_id = str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-ID", request_id)

        # Extract user ID from auth header if present
        user_id = None
        auth_header = request.headers.get("authorization")
        if auth_header:
            # This is a simplified extraction - actual implementation depends on your auth
            user_id = "authenticated"  # Placeholder

        # Set logging context
        set_request_context(
            request_id=request_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

        # Log request
        start_time = time.time()
        logger.info(
            "Incoming request",
            extra={
                "event": "request_started",
                "method": request.method,
                "path": request.url.path,
                "query_params": str(request.query_params),
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )

        # Process request
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            # Log response
            logger.info(
                "Request completed",
                extra={
                    "event": "request_completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id

            return response

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            logger.error(
                "Request failed",
                extra={
                    "event": "request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            raise

        finally:
            # Clear context
            clear_request_context()
