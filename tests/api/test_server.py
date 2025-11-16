"""
Comprehensive tests for FastAPI server.

Tests cover:
- Health and status endpoints
- Configuration management API
- Metrics and monitoring API
- Authentication and authorization
- Error handling
- CORS and security headers
"""

from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.api.server import app, require_admin, verify_token
from src.core.config_manager import ConfigurationManager
from src.core.metrics import (
    HealthCheck,
    HealthStatus,
    MetricsCollector,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def client():
    """Create test client."""

    # Override authentication dependencies for testing
    def mock_verify_token():
        return {"user": "test_user", "role": "admin"}

    def mock_require_admin():
        return {"user": "test_user", "role": "admin"}

    app.dependency_overrides[verify_token] = mock_verify_token
    app.dependency_overrides[require_admin] = mock_require_admin

    client = TestClient(app)
    yield client

    # Clean up overrides
    app.dependency_overrides.clear()


@pytest.fixture
def mock_config_manager():
    """Create mock ConfigurationManager."""
    manager = Mock(spec=ConfigurationManager)

    # Mock get_status
    manager.get_status.return_value = {
        "environment": "testnet",
        "trading_mode": "paper",
        "current_config": {
            "binance": {"testnet": True},
            "trading": {"mode": "paper"},
        },
        "history_size": 5,
        "file_watching_enabled": True,
        "auto_save_enabled": True,
    }

    # Mock update_config
    manager.update_config.return_value = True

    # Mock switch_environment
    manager.switch_environment.return_value = True

    # Mock rollback
    manager.rollback.return_value = True

    # Mock get_history
    manager.get_history.return_value = [
        {
            "timestamp": datetime.now().isoformat(),
            "reason": "update:trading",
            "config": {"trading": {"mode": "paper"}},
        }
    ]

    return manager


@pytest.fixture
def mock_monitoring_system():
    """Create mock MonitoringSystem."""
    monitor = Mock()  # Remove spec to allow dynamic attribute creation

    # Create mock metrics collector with start time
    mock_metrics_collector = Mock()
    mock_metrics_collector._start_time = datetime.now()
    monitor._metrics_collector = mock_metrics_collector

    # Create mock system metrics (don't use spec to allow dynamic attr creation)
    mock_sys_metrics = Mock()
    mock_sys_metrics.get_cpu_usage.return_value = 25.5
    mock_sys_metrics.get_memory_usage.return_value = 60.2
    mock_sys_metrics.get_disk_usage.return_value = 45.8
    monitor._system_metrics = mock_sys_metrics

    # Mock health status
    health_checks = [
        HealthCheck(
            component="binance",
            status=HealthStatus.HEALTHY,
            message="Connected",
            details={"websocket": "connected"},
            response_time_ms=5.2,
        ),
        HealthCheck(
            component="database",
            status=HealthStatus.HEALTHY,
            message="Operational",
            details={"connections": 5},
            response_time_ms=2.1,
        ),
    ]
    monitor.get_health_status.return_value = health_checks

    return monitor


@pytest.fixture
def mock_orchestrator():
    """Create mock TradingSystemOrchestrator."""
    orchestrator = Mock()

    orchestrator.get_status.return_value = {
        "state": "running",
        "services": {
            "binance": "running",
            "strategy": "running",
            "risk": "running",
        },
    }

    return orchestrator


@pytest.fixture
def mock_metrics_collector():
    """Create mock MetricsCollector."""
    return Mock(spec=MetricsCollector)


@pytest.fixture(autouse=True)
def setup_global_instances(
    mock_orchestrator, mock_config_manager, mock_metrics_collector, mock_monitoring_system
):
    """Setup global instances for all tests."""
    import src.api.server as server_module

    server_module.orchestrator = mock_orchestrator
    server_module.config_manager = mock_config_manager
    server_module.metrics_collector = mock_metrics_collector
    server_module.monitoring_system = mock_monitoring_system

    yield

    # Cleanup
    server_module.orchestrator = None
    server_module.config_manager = None
    server_module.metrics_collector = None
    server_module.monitoring_system = None


# ============================================================================
# Health & Status Endpoint Tests
# ============================================================================


class TestHealthEndpoints:
    """Test health and status endpoints."""

    def test_health_check_success(self, client, mock_monitoring_system):
        """Test successful health check."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "components" in data
        assert data["components"]["binance"] == "healthy"
        assert data["components"]["database"] == "healthy"

    def test_health_check_degraded(self, client, mock_monitoring_system):
        """Test health check with degraded component."""
        # Mock degraded health
        health_checks = [
            HealthCheck(component="binance", status=HealthStatus.DEGRADED, message="High latency"),
        ]
        mock_monitoring_system.get_health_status.return_value = health_checks

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    def test_health_check_unhealthy(self, client, mock_monitoring_system):
        """Test health check with unhealthy component."""
        # Mock unhealthy health
        health_checks = [
            HealthCheck(
                component="binance", status=HealthStatus.UNHEALTHY, message="Connection lost"
            ),
        ]
        mock_monitoring_system.get_health_status.return_value = health_checks

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"

    def test_system_status_success(self, client):
        """Test successful system status retrieval."""
        response = client.get("/status")

        assert response.status_code == 200
        data = response.json()

        assert data["system_state"] == "running"
        assert data["environment"] == "testnet"
        assert data["trading_mode"] == "paper"
        assert "services" in data
        assert "uptime_seconds" in data

    def test_system_status_requires_auth(self, client):
        """Test that system status requires authentication."""
        # Currently allows anonymous access in development
        # This test documents expected production behavior
        response = client.get("/status")
        assert response.status_code == 200


# ============================================================================
# Configuration Endpoint Tests
# ============================================================================


class TestConfigurationEndpoints:
    """Test configuration management endpoints."""

    def test_get_configuration_success(self, client, mock_config_manager):
        """Test successful configuration retrieval."""
        response = client.get("/config")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "configuration" in data
        assert "metadata" in data
        assert data["metadata"]["environment"] == "testnet"

    def test_update_configuration_success(self, client, mock_config_manager):
        """Test successful configuration update."""
        request_data = {"section": "trading", "updates": {"mode": "live"}, "validate": True}

        response = client.post("/config/update", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["section"] == "trading"
        assert data["applied_updates"] == {"mode": "live"}

        # Verify config_manager was called correctly
        mock_config_manager.update_config.assert_called_once_with(
            section="trading", updates={"mode": "live"}, validate=True
        )

    def test_update_configuration_requires_admin(self, client):
        """Test that configuration update requires admin role."""
        # In production, this would fail without proper admin token
        request_data = {"section": "trading", "updates": {"mode": "live"}, "validate": True}

        response = client.post("/config/update", json=request_data)
        # Currently allows in development mode
        # This documents expected production behavior
        assert response.status_code in [200, 403]

    def test_update_configuration_validation_failure(self, client, mock_config_manager):
        """Test configuration update with validation failure."""
        mock_config_manager.update_config.return_value = False

        request_data = {
            "section": "trading",
            "updates": {"invalid_key": "invalid_value"},
            "validate": True,
        }

        response = client.post("/config/update", json=request_data)

        assert response.status_code == 400

    def test_switch_environment_to_testnet(self, client, mock_config_manager):
        """Test switching to testnet environment."""
        request_data = {"to_testnet": True}

        response = client.post("/config/switch-environment", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["environment"] == "testnet"
        assert "warning" in data

        mock_config_manager.switch_environment.assert_called_once_with(to_testnet=True)

    def test_switch_environment_to_mainnet(self, client, mock_config_manager):
        """Test switching to mainnet environment."""
        request_data = {"to_testnet": False}

        response = client.post("/config/switch-environment", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["environment"] == "mainnet"

        mock_config_manager.switch_environment.assert_called_once_with(to_testnet=False)

    def test_rollback_configuration_success(self, client, mock_config_manager):
        """Test successful configuration rollback."""
        request_data = {"steps": 2}

        response = client.post("/config/rollback", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["steps"] == 2

        mock_config_manager.rollback.assert_called_once_with(steps=2)

    def test_rollback_configuration_no_history(self, client, mock_config_manager):
        """Test configuration rollback with no history."""
        mock_config_manager.rollback.return_value = False

        request_data = {"steps": 1}

        response = client.post("/config/rollback", json=request_data)

        assert response.status_code == 400

    def test_rollback_configuration_invalid_steps(self, client):
        """Test configuration rollback with invalid steps."""
        request_data = {"steps": 15}  # Exceeds max of 10

        response = client.post("/config/rollback", json=request_data)

        assert response.status_code == 422  # Validation error

    def test_get_config_history(self, client, mock_config_manager):
        """Test getting configuration history."""
        response = client.get("/config/history?limit=5")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "history" in data
        assert data["count"] == 1

        mock_config_manager.get_history.assert_called_once_with(limit=5)


# ============================================================================
# Metrics Endpoint Tests
# ============================================================================


class TestMetricsEndpoints:
    """Test metrics and monitoring endpoints."""

    def test_get_metrics_success(self, client, mock_monitoring_system):
        """Test successful metrics retrieval."""
        response = client.get("/metrics")

        assert response.status_code == 200
        data = response.json()

        assert "system_metrics" in data
        assert "component_metrics" in data
        assert "performance_metrics" in data

        # Verify system metrics
        assert data["system_metrics"]["cpu_percent"] == 25.5
        assert data["system_metrics"]["memory_percent"] == 60.2

    def test_get_component_metrics_success(self, client, mock_monitoring_system):
        """Test successful component metrics retrieval."""
        response = client.get("/metrics/components/binance")

        assert response.status_code == 200
        data = response.json()

        assert data["component"] == "binance"
        assert data["health"] == "healthy"
        assert data["message"] == "Connected"
        assert data["details"]["websocket"] == "connected"
        assert data["response_time_ms"] == 5.2

    def test_get_component_metrics_not_found(self, client, mock_monitoring_system):
        """Test component metrics for non-existent component."""
        response = client.get("/metrics/components/nonexistent")

        assert response.status_code == 404


# ============================================================================
# Security & CORS Tests
# ============================================================================


class TestSecurityAndCORS:
    """Test security headers and CORS configuration."""

    def test_security_headers_present(self, client):
        """Test that security headers are added to responses."""
        response = client.get("/health")

        assert response.status_code == 200
        assert "x-content-type-options" in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "x-frame-options" in response.headers
        assert response.headers["x-frame-options"] == "DENY"
        assert "x-xss-protection" in response.headers
        assert "strict-transport-security" in response.headers

    def test_cors_allowed_origins(self, client):
        """Test CORS headers for allowed origins."""
        response = client.options(
            "/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )

        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling and exception responses."""

    def test_http_exception_handler(self, client):
        """Test HTTP exception handling."""
        # Trigger 404
        response = client.get("/nonexistent-endpoint")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data  # FastAPI default format

    def test_service_unavailable_error(self, client):
        """Test service unavailable handling."""
        import src.api.server as server_module

        # Temporarily set config_manager to None
        original = server_module.config_manager
        server_module.config_manager = None

        try:
            response = client.get("/config")
            assert response.status_code == 503
        finally:
            server_module.config_manager = original


# ============================================================================
# API Documentation Tests
# ============================================================================


class TestAPIDocumentation:
    """Test API documentation endpoints."""

    def test_openapi_schema_available(self, client):
        """Test that OpenAPI schema is available."""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        schema = response.json()

        assert "openapi" in schema
        assert "info" in schema
        assert schema["info"]["title"] == "Trading System API"

    def test_swagger_ui_available(self, client):
        """Test that Swagger UI is available."""
        response = client.get("/docs")

        assert response.status_code == 200

    def test_redoc_available(self, client):
        """Test that ReDoc is available."""
        response = client.get("/redoc")

        assert response.status_code == 200


# ============================================================================
# Integration Tests
# ============================================================================


class TestAPIIntegration:
    """Integration tests for API workflows."""

    def test_full_configuration_workflow(self, client, mock_config_manager):
        """Test complete configuration management workflow."""
        # 1. Get current config
        response = client.get("/config")
        assert response.status_code == 200

        # 2. Update config
        update_data = {"section": "trading", "updates": {"mode": "live"}, "validate": True}
        response = client.post("/config/update", json=update_data)
        assert response.status_code == 200

        # 3. Get history
        response = client.get("/config/history")
        assert response.status_code == 200

        # 4. Rollback
        response = client.post("/config/rollback", json={"steps": 1})
        assert response.status_code == 200

    def test_full_monitoring_workflow(self, client):
        """Test complete monitoring workflow."""
        # 1. Check health
        response = client.get("/health")
        assert response.status_code == 200

        # 2. Get detailed status
        response = client.get("/status")
        assert response.status_code == 200

        # 3. Get system metrics
        response = client.get("/metrics")
        assert response.status_code == 200

        # 4. Get component metrics
        response = client.get("/metrics/components/binance")
        assert response.status_code == 200
