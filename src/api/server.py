"""
FastAPI-based REST API Server for Trading System.

Provides endpoints for system status, configuration management, metrics monitoring,
and real-time system control. Includes authentication, CORS, and comprehensive
API documentation via Swagger UI.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Security,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src.api.logging_middleware import LoggingMiddleware
from src.api.middleware import SecurityHeadersMiddleware, configure_security_middleware
from src.api.websocket import WebSocketManager
from src.core.config_manager import ConfigurationManager
from src.core.events import EventBus
from src.core.metrics import MetricsCollector, MonitoringSystem
from src.core.orchestrator import TradingSystemOrchestrator
from src.core.security import SecurityManager

logger = logging.getLogger(__name__)

# Security
security = HTTPBearer(auto_error=False)

# Global instances (will be initialized in lifespan)
orchestrator: Optional[TradingSystemOrchestrator] = None
config_manager: Optional[ConfigurationManager] = None
metrics_collector: Optional[MetricsCollector] = None
monitoring_system: Optional[MonitoringSystem] = None
event_bus: Optional[EventBus] = None
ws_manager: Optional[WebSocketManager] = None
security_manager: Optional[SecurityManager] = None


# ============================================================================
# Request/Response Models
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Health status: healthy, degraded, unhealthy")
    timestamp: datetime = Field(default_factory=datetime.now)
    uptime_seconds: float = Field(..., description="System uptime in seconds")
    components: Dict[str, str] = Field(
        default_factory=dict, description="Component health statuses"
    )


class SystemStatusResponse(BaseModel):
    """Detailed system status response."""

    system_state: str = Field(..., description="Current system state")
    environment: str = Field(..., description="Environment: testnet or mainnet")
    trading_mode: str = Field(..., description="Trading mode")
    services: Dict[str, Any] = Field(default_factory=dict, description="Service states")
    uptime_seconds: float = Field(..., description="System uptime")
    timestamp: datetime = Field(default_factory=datetime.now)


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    section: str = Field(..., description="Configuration section to update")
    updates: Dict[str, Any] = Field(..., description="Configuration updates")
    validate: bool = Field(True, description="Validate before applying")


class ConfigUpdateResponse(BaseModel):
    """Configuration update response."""

    success: bool
    message: str
    section: str
    applied_updates: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)


class EnvironmentSwitchRequest(BaseModel):
    """Environment switch request."""

    to_testnet: bool = Field(..., description="True for testnet, False for mainnet")


class RollbackRequest(BaseModel):
    """Configuration rollback request."""

    steps: int = Field(1, ge=1, le=10, description="Number of steps to rollback")


class MetricsResponse(BaseModel):
    """Metrics response."""

    timestamp: datetime = Field(default_factory=datetime.now)
    system_metrics: Dict[str, Any] = Field(default_factory=dict)
    component_metrics: Dict[str, Any] = Field(default_factory=dict)
    performance_metrics: Dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================================
# Authentication & Authorization
# ============================================================================


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Dict[str, Any]:
    """
    Verify authentication token.

    Currently implements a simple token verification.
    In production, integrate with proper OAuth2/JWT validation.

    Args:
        credentials: HTTP authorization credentials

    Returns:
        User information dict

    Raises:
        HTTPException: If authentication fails
    """
    if credentials is None:
        # For development/testing, allow anonymous access
        # In production, raise HTTPException
        return {"user": "anonymous", "role": "read-only"}

    token = credentials.credentials

    # TODO: Implement proper JWT/OAuth2 validation
    # For now, simple token check
    if not token or len(token) < 10:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Mock user info - replace with real JWT decoding
    return {
        "user": "authenticated_user",
        "role": "admin",  # Could be: admin, trader, read-only
        "token": token,
    }


async def require_admin(_user: Dict[str, Any] = Depends(verify_token)) -> Dict[str, Any]:
    """
    Require admin role for protected endpoints.

    Args:
        _user: User information from verify_token (prefixed with _ to indicate unused in endpoint body)

    Returns:
        User information if authorized

    Raises:
        HTTPException: If user lacks admin permissions
    """
    if _user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this operation",
        )
    return _user


# ============================================================================
# Application Lifecycle
# ============================================================================


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Application lifespan context manager.

    Handles startup and shutdown of the trading system and all services.
    """
    logger.info("Starting API server and trading system...")

    try:
        # Initialize core systems
        # Note: In production, these would be injected via dependency injection
        # For now, we'll initialize them here

        # These will be initialized by the main application
        # and passed to the API server

        # Configure security middleware if security manager is available
        if security_manager:
            import os

            configure_security_middleware(
                app=_app,
                security_manager=security_manager,
                rate_limit_enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true",
                ip_whitelist_enabled=os.getenv("IP_WHITELIST_ENABLED", "false").lower() == "true",
                security_headers_enabled=True,
            )
            logger.info("Security middleware configured")

        # Start WebSocket manager if event bus is available
        if event_bus and ws_manager:
            await ws_manager.start()
            logger.info("WebSocket manager started")

        logger.info("API server initialized successfully")

        yield  # Application runs

    except Exception as e:
        logger.error(f"Error during API server startup: {e}", exc_info=True)
        raise
    finally:
        logger.info("Shutting down API server...")

        # Stop WebSocket manager
        if ws_manager:
            await ws_manager.stop()
            logger.info("WebSocket manager stopped")

        # Cleanup will be handled by the orchestrator
        # when the main application shuts down

        logger.info("API server shutdown complete")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Trading System API",
    description="REST API for cryptocurrency trading system management and monitoring",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ============================================================================
# CORS Configuration
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React development
        "http://localhost:8080",  # Vue development
        "http://localhost:5173",  # Vite development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ============================================================================
# Security Headers Middleware
# ============================================================================
# Add security headers to all responses (independent of security_manager)
app.add_middleware(SecurityHeadersMiddleware)

# ============================================================================
# Logging Middleware
# ============================================================================
app.add_middleware(
    LoggingMiddleware,
    excluded_paths=["/health", "/metrics"],  # Don't log health checks
)


# ============================================================================
# Additional Security Middleware
# ============================================================================
# Rate limiting and IP whitelisting are configured in lifespan if security_manager exists


# ============================================================================
# Health & Status Endpoints
# ============================================================================


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Quick health check endpoint for load balancers and monitoring systems",
    tags=["System"],
)
async def health_check() -> HealthResponse:
    """
    Quick health check endpoint.

    Returns basic health status without requiring authentication.
    Suitable for load balancer health checks.
    """
    try:
        # Calculate uptime
        uptime = 0.0
        if monitoring_system:
            uptime = (
                datetime.now() - monitoring_system.metrics._start_time
            ).total_seconds()

        # Get component health if available
        components = {}
        if monitoring_system:
            health_checks = monitoring_system.health_checks.get_all_statuses()
            components = {check.component: check.status.value for check in health_checks}

        # Determine overall health
        if components:
            unhealthy_count = sum(1 for status in components.values() if status == "unhealthy")
            degraded_count = sum(1 for status in components.values() if status == "degraded")

            if unhealthy_count > 0:
                overall_status = "unhealthy"
            elif degraded_count > 0:
                overall_status = "degraded"
            else:
                overall_status = "healthy"
        else:
            overall_status = "healthy"

        return HealthResponse(status=overall_status, uptime_seconds=uptime, components=components)

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(status="unhealthy", uptime_seconds=0.0, components={"error": str(e)})


@app.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness Check",
    description="Kubernetes-style readiness probe checking all dependencies",
    tags=["System"],
)
async def readiness_check() -> HealthResponse:
    """
    Readiness check endpoint.

    Verifies that the application and all its dependencies are ready to serve traffic.
    Checks database connectivity, Redis, and other critical services.

    Returns:
        HealthResponse with detailed dependency status
    """
    try:
        components = {}
        overall_status = "healthy"

        # Check database connectivity
        try:
            from src.database.engine import get_session

            async with get_session() as session:
                await session.execute("SELECT 1")
            components["database"] = "healthy"
        except Exception as db_error:
            logger.error(f"Database readiness check failed: {db_error}")
            components["database"] = "unhealthy"
            overall_status = "unhealthy"

        # Check orchestrator
        if orchestrator:
            status = orchestrator.get_status()
            state = status.get("state", "offline")
            if state in ["initializing", "offline", "error"]:
                components["orchestrator"] = "degraded"
                if overall_status == "healthy":
                    overall_status = "degraded"
            else:
                components["orchestrator"] = "healthy"
        else:
            components["orchestrator"] = "unhealthy"
            overall_status = "unhealthy"

        # Check monitoring system
        if monitoring_system:
            health_checks = monitoring_system.health_checks.perform_all_checks()
            for component, check in health_checks.items():
                components[f"monitor_{component}"] = check.status.value
                if check.status.value == "unhealthy" and overall_status != "unhealthy":
                    overall_status = "unhealthy"
                elif check.status.value == "degraded" and overall_status == "healthy":
                    overall_status = "degraded"
        else:
            components["monitoring"] = "degraded"
            if overall_status == "healthy":
                overall_status = "degraded"

        # Calculate uptime
        uptime = 0.0
        if monitoring_system:
            uptime = (
                datetime.now() - monitoring_system.metrics._start_time
            ).total_seconds()

        return HealthResponse(
            status=overall_status,
            uptime_seconds=uptime,
            components=components,
        )

    except Exception as e:
        logger.error(f"Readiness check failed: {e}", exc_info=True)
        return HealthResponse(
            status="unhealthy",
            uptime_seconds=0.0,
            components={"error": str(e)},
        )


@app.get(
    "/metrics",
    summary="Prometheus Metrics",
    description="Prometheus metrics endpoint for scraping",
    tags=["System"],
)
async def get_metrics():
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format for scraping.
    No authentication required to allow Prometheus to scrape metrics.
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    from src.monitoring.metrics import trading_metrics

    # Generate Prometheus metrics
    metrics_output = generate_latest(trading_metrics.get_registry())

    return Response(content=metrics_output, media_type=CONTENT_TYPE_LATEST)


@app.get(
    "/status",
    response_model=SystemStatusResponse,
    summary="System Status",
    description="Get detailed system status including all services and components",
    tags=["System"],
)
async def get_system_status(_user: Dict[str, Any] = Depends(verify_token)) -> SystemStatusResponse:
    """
    Get comprehensive system status.

    Requires authentication. Returns detailed information about
    system state, services, and configuration.
    """
    try:
        # Get orchestrator status
        system_state = "offline"
        services = {}

        if orchestrator:
            system_state = orchestrator.get_system_state().value
            services = orchestrator.get_service_states()

        # Get configuration
        environment = "unknown"
        trading_mode = "unknown"

        if config_manager:
            config_status = config_manager.get_status()
            environment = config_status.get("environment", "unknown")
            trading_mode = config_status.get("trading_mode", "unknown")

        # Calculate uptime
        uptime = 0.0
        if monitoring_system:
            uptime = (
                datetime.now() - monitoring_system.metrics._start_time
            ).total_seconds()

        return SystemStatusResponse(
            system_state=system_state,
            environment=environment,
            trading_mode=trading_mode,
            services=services,
            uptime_seconds=uptime,
        )

    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve system status: {str(e)}",
        )


# ============================================================================
# Logging Configuration Endpoints
# ============================================================================


class LogLevelRequest(BaseModel):
    """Log level configuration request."""

    level: str = Field(..., description="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    logger_name: Optional[str] = Field(None, description="Specific logger name or None for root")


class LogLevelResponse(BaseModel):
    """Log level configuration response."""

    success: bool
    message: str
    current_level: str
    logger_name: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


@app.get(
    "/api/log-level",
    response_model=LogLevelResponse,
    summary="Get Current Log Level",
    description="Get the current log level configuration",
    tags=["Configuration"],
)
async def get_log_level(
    logger_name: Optional[str] = None,
    _user: Dict[str, Any] = Depends(verify_token),
) -> LogLevelResponse:
    """
    Get current log level.

    Requires authentication.

    Args:
        logger_name: Optional logger name (None for root logger)

    Returns:
        Current log level configuration
    """
    try:
        from src.core.logging_config import get_current_log_level

        current_level = get_current_log_level(logger_name)

        return LogLevelResponse(
            success=True,
            message="Current log level retrieved",
            current_level=current_level,
            logger_name=logger_name,
        )

    except Exception as e:
        logger.error(f"Failed to get log level: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get log level: {str(e)}",
        )


@app.put(
    "/api/log-level",
    response_model=LogLevelResponse,
    summary="Set Log Level",
    description="Dynamically change the log level at runtime",
    tags=["Configuration"],
)
async def set_log_level_endpoint(
    request: LogLevelRequest,
    _user: Dict[str, Any] = Depends(verify_token),
) -> LogLevelResponse:
    """
    Set log level dynamically.

    Requires authentication. Allows runtime adjustment of logging verbosity
    without restarting the application.

    Args:
        request: Log level configuration

    Returns:
        Updated log level configuration
    """
    try:
        from src.core.logging_config import get_current_log_level, set_log_level

        # Validate log level
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if request.level.upper() not in valid_levels:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid log level. Must be one of: {', '.join(valid_levels)}",
            )

        # Set log level
        set_log_level(request.level.upper(), request.logger_name)

        # Get updated level
        current_level = get_current_log_level(request.logger_name)

        logger.info(
            f"Log level changed to {current_level}",
            extra={"logger_name": request.logger_name or "root"},
        )

        return LogLevelResponse(
            success=True,
            message=f"Log level set to {current_level}",
            current_level=current_level,
            logger_name=request.logger_name,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set log level: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set log level: {str(e)}",
        )


# ============================================================================
# Configuration Management Endpoints
# ============================================================================


@app.get(
    "/config",
    summary="Get Configuration",
    description="Get current system configuration",
    tags=["Configuration"],
)
async def get_configuration(_user: Dict[str, Any] = Depends(verify_token)) -> Dict[str, Any]:
    """
    Get current system configuration.

    Returns the complete current configuration including all sections.
    """
    if not config_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration manager not available",
        )

    try:
        config_status = config_manager.get_status()
        return {
            "success": True,
            "configuration": config_status.get("current_config", {}),
            "metadata": {
                "environment": config_status.get("environment"),
                "trading_mode": config_status.get("trading_mode"),
                "history_size": config_status.get("history_size"),
                "file_watching_enabled": config_status.get("file_watching_enabled"),
                "auto_save_enabled": config_status.get("auto_save_enabled"),
            },
            "timestamp": datetime.now(),
        }
    except Exception as e:
        logger.error(f"Failed to get configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve configuration: {str(e)}",
        )


@app.post(
    "/config/update",
    response_model=ConfigUpdateResponse,
    summary="Update Configuration",
    description="Update specific configuration section at runtime",
    tags=["Configuration"],
)
async def update_configuration(
    request: ConfigUpdateRequest, _user: Dict[str, Any] = Depends(require_admin)
) -> ConfigUpdateResponse:
    """
    Update configuration at runtime.

    Requires admin privileges. Updates are validated before being applied
    and can be rolled back if needed.
    """
    if not config_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration manager not available",
        )

    try:
        success = config_manager.update_config(
            section=request.section, updates=request.updates, validate=request.validate
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Configuration update failed validation",
            )

        return ConfigUpdateResponse(
            success=True,
            message=f"Configuration section '{request.section}' updated successfully",
            section=request.section,
            applied_updates=request.updates,
        )

    except HTTPException:
        # Re-raise HTTP exceptions (like validation failures)
        raise
    except Exception as e:
        logger.error(f"Configuration update failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Configuration update failed: {str(e)}",
        )


@app.post(
    "/config/switch-environment",
    summary="Switch Environment",
    description="Switch between testnet and mainnet environments",
    tags=["Configuration"],
)
async def switch_environment(
    request: EnvironmentSwitchRequest, _user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Switch between testnet and mainnet.

    Requires admin privileges. This is a critical operation that
    requires system restart for full effect.
    """
    if not config_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration manager not available",
        )

    try:
        success = config_manager.switch_environment(to_testnet=request.to_testnet)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Environment switch failed"
            )

        target_env = "testnet" if request.to_testnet else "mainnet"

        return {
            "success": True,
            "message": f"Successfully switched to {target_env}",
            "environment": target_env,
            "warning": "System restart recommended for full effect",
            "timestamp": datetime.now(),
        }

    except Exception as e:
        logger.error(f"Environment switch failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Environment switch failed: {str(e)}",
        )


@app.post(
    "/config/rollback",
    summary="Rollback Configuration",
    description="Rollback to previous configuration state",
    tags=["Configuration"],
)
async def rollback_configuration(
    request: RollbackRequest, _user: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Rollback configuration to previous state.

    Requires admin privileges. Can rollback up to 10 steps.
    """
    if not config_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration manager not available",
        )

    try:
        success = config_manager.rollback(steps=request.steps)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Configuration rollback failed - no history available",
            )

        return {
            "success": True,
            "message": f"Successfully rolled back {request.steps} step(s)",
            "steps": request.steps,
            "timestamp": datetime.now(),
        }

    except HTTPException:
        # Re-raise HTTP exceptions (like validation failures)
        raise
    except Exception as e:
        logger.error(f"Configuration rollback failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Configuration rollback failed: {str(e)}",
        )


@app.get(
    "/config/history",
    summary="Configuration History",
    description="Get configuration change history",
    tags=["Configuration"],
)
async def get_config_history(
    limit: int = 10, _user: Dict[str, Any] = Depends(verify_token)
) -> Dict[str, Any]:
    """
    Get configuration change history.

    Returns up to 'limit' most recent configuration changes.
    """
    if not config_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration manager not available",
        )

    try:
        history = config_manager.get_history(limit=min(limit, 50))

        return {
            "success": True,
            "history": history,
            "count": len(history),
            "timestamp": datetime.now(),
        }

    except Exception as e:
        logger.error(f"Failed to get configuration history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve configuration history: {str(e)}",
        )


# ============================================================================
# Metrics & Monitoring Endpoints
# ============================================================================


@app.get(
    "/api/metrics",
    response_model=MetricsResponse,
    summary="System Metrics",
    description="Get comprehensive system metrics and performance data",
    tags=["Metrics"],
)
async def get_system_metrics(
    _user: Dict[str, Any] = Depends(verify_token),
) -> MetricsResponse:
    """
    Get comprehensive system metrics.

    Returns performance metrics, component health, and system statistics.
    """
    try:
        system_metrics = {}
        component_metrics = {}
        performance_metrics = {}

        if monitoring_system:
            # System metrics from system metrics collector
            sys_metrics = monitoring_system._system_metrics
            system_metrics = {
                "cpu_percent": sys_metrics.get_cpu_usage(),
                "memory_percent": sys_metrics.get_memory_usage(),
                "disk_percent": sys_metrics.get_disk_usage(),
                "uptime_seconds": (
                    datetime.now() - monitoring_system.metrics._start_time
                ).total_seconds(),
            }

            # Performance metrics (would be collected from components)
            performance_metrics = {"api_latency_ms": 0, "throughput_per_sec": 0, "error_rate": 0}

        if metrics_collector:
            # Component-specific metrics
            # This would aggregate metrics from various components
            pass

        return MetricsResponse(
            system_metrics=system_metrics,
            component_metrics=component_metrics,
            performance_metrics=performance_metrics,
        )

    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve metrics: {str(e)}",
        )


@app.get(
    "/metrics/components/{component_name}",
    summary="Component Metrics",
    description="Get metrics for a specific component",
    tags=["Metrics"],
)
async def get_component_metrics(
    component_name: str, _user: Dict[str, Any] = Depends(verify_token)
) -> Dict[str, Any]:
    """
    Get metrics for a specific component.

    Args:
        component_name: Name of the component (e.g., 'binance', 'strategy', 'risk')
    """
    if not monitoring_system:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monitoring system not available",
        )

    try:
        # Get component health
        health_checks = monitoring_system.health_checks.get_all_statuses()
        component_health = next(
            (check for check in health_checks if check.component == component_name), None
        )

        if not component_health:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Component '{component_name}' not found",
            )

        return {
            "component": component_name,
            "health": component_health.status.value,
            "message": component_health.message,
            "details": component_health.details,
            "response_time_ms": component_health.response_time_ms,
            "timestamp": component_health.timestamp,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get component metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve component metrics: {str(e)}",
        )


# ============================================================================
# WebSocket Endpoints
# ============================================================================


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication.

    Clients can connect to receive real-time updates on:
    - Candle data
    - Trading signals
    - Order updates
    - Position updates
    - Indicator updates
    - System status

    Message format (client to server):
    {
        "type": "subscribe|unsubscribe|ping|get_subscriptions",
        "topics": ["candles", "signals", "orders", "positions", "indicators", "system"],
        "filters": {"symbol": "BTCUSDT"}  // Optional
    }

    Message format (server to client):
    {
        "type": "candle_update|signal|order_update|position_update|indicator_update|system_status|error|pong",
        "timestamp": "2024-01-01T00:00:00",
        "data": {...}
    }
    """
    if not ws_manager:
        await websocket.close(code=1011, reason="WebSocket service not available")
        return

    connection_id = await ws_manager.connect(websocket)

    try:
        while True:
            # Receive message from client
            message = await websocket.receive_text()
            await ws_manager.handle_message(connection_id, message)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error for connection {connection_id}: {e}", exc_info=True)
    finally:
        await ws_manager.disconnect(connection_id)


@app.get(
    "/ws/stats",
    summary="WebSocket Statistics",
    description="Get WebSocket connection statistics",
    tags=["WebSocket"],
)
async def get_websocket_stats(_user: Dict[str, Any] = Depends(verify_token)) -> Dict[str, Any]:
    """
    Get WebSocket statistics.

    Returns information about active connections, message counts,
    and subscription details.
    """
    if not ws_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WebSocket service not available",
        )

    try:
        stats = ws_manager.get_stats()
        return {"success": True, "stats": stats, "timestamp": datetime.now()}
    except Exception as e:
        logger.error(f"Failed to get WebSocket stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve WebSocket statistics: {str(e)}",
        )


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc: HTTPException):
    """Handle HTTP exceptions with structured error response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(_request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": str(exc) if logger.level <= logging.DEBUG else None,
            "timestamp": datetime.now().isoformat(),
        },
    )


# ============================================================================
# Server Runner
# ============================================================================


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    log_level: str = "info",
    orchestrator_instance: Optional[TradingSystemOrchestrator] = None,
    config_manager_instance: Optional[ConfigurationManager] = None,
    metrics_collector_instance: Optional[MetricsCollector] = None,
    monitoring_system_instance: Optional[MonitoringSystem] = None,
    event_bus_instance: Optional[EventBus] = None,
    security_manager_instance: Optional[SecurityManager] = None,
) -> None:
    """
    Run the FastAPI server.

    Args:
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload for development
        log_level: Logging level
        orchestrator_instance: TradingSystemOrchestrator instance
        config_manager_instance: ConfigurationManager instance
        metrics_collector_instance: MetricsCollector instance
        monitoring_system_instance: MonitoringSystem instance
        event_bus_instance: EventBus instance for WebSocket integration
        security_manager_instance: SecurityManager instance
    """
    global orchestrator, config_manager, metrics_collector, monitoring_system, event_bus, ws_manager, security_manager

    # Set global instances
    orchestrator = orchestrator_instance
    config_manager = config_manager_instance
    metrics_collector = metrics_collector_instance
    monitoring_system = monitoring_system_instance
    event_bus = event_bus_instance
    security_manager = security_manager_instance

    # Initialize WebSocket manager if event bus is available
    if event_bus:
        ws_manager = WebSocketManager(event_bus=event_bus)
        logger.info("WebSocket manager initialized")

    logger.info(f"Starting API server on {host}:{port}")

    uvicorn.run(
        "src.api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        access_log=True,
    )


if __name__ == "__main__":
    # For development/testing
    run_server(reload=True, log_level="debug")
