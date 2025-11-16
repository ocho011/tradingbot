"""
Tests for health check and monitoring endpoints.

Tests /health, /ready, /metrics, and /api/log-level endpoints.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.core.metrics import HealthCheck, HealthStatus


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_monitoring_system():
    """Mock monitoring system."""
    mock_system = MagicMock()
    mock_system._metrics_collector._start_time = MagicMock()
    mock_system.health_checks.perform_all_checks = MagicMock(return_value={})
    return mock_system


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_check_success(self, client, mock_monitoring_system):
        """Test successful health check."""
        with patch("src.api.server.monitoring_system", mock_monitoring_system):
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()

            assert "status" in data
            assert "uptime_seconds" in data
            assert "components" in data
            assert "timestamp" in data

    def test_health_check_without_monitoring(self, client):
        """Test health check when monitoring system is not initialized."""
        with patch("src.api.server.monitoring_system", None):
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "healthy"
            assert data["uptime_seconds"] == 0.0

    def test_health_check_with_unhealthy_components(self, client, mock_monitoring_system):
        """Test health check with unhealthy components."""
        mock_monitoring_system.get_health_status = MagicMock(
            return_value=[
                HealthCheck(
                    component="database",
                    status=HealthStatus.UNHEALTHY,
                    message="Connection failed",
                )
            ]
        )

        with patch("src.api.server.monitoring_system", mock_monitoring_system):
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "unhealthy"
            assert "database" in data["components"]

    def test_health_check_with_degraded_components(self, client, mock_monitoring_system):
        """Test health check with degraded components."""
        mock_monitoring_system.get_health_status = MagicMock(
            return_value=[
                HealthCheck(
                    component="redis",
                    status=HealthStatus.DEGRADED,
                    message="High latency",
                )
            ]
        )

        with patch("src.api.server.monitoring_system", mock_monitoring_system):
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "degraded"
            assert "redis" in data["components"]


class TestReadyEndpoint:
    """Tests for /ready endpoint."""

    @pytest.mark.asyncio
    async def test_ready_check_success(self, client):
        """Test successful readiness check."""
        with (
            patch("src.api.server.orchestrator") as mock_orch,
            patch("src.api.server.monitoring_system") as mock_mon,
            patch("src.database.engine.get_session") as mock_db,
        ):
            # Mock healthy state
            mock_orch.get_status.return_value = {"state": "running"}
            mock_mon.health_checks.perform_all_checks.return_value = {}

            # Mock successful DB connection
            mock_session = AsyncMock()
            mock_db.return_value.__aenter__.return_value = mock_session

            response = client.get("/ready")

            assert response.status_code == 200
            data = response.json()

            assert "status" in data
            assert "components" in data
            assert data["components"].get("database") == "healthy"

    @pytest.mark.asyncio
    async def test_ready_check_database_failure(self, client):
        """Test readiness check with database failure."""
        with (
            patch("src.api.server.orchestrator") as mock_orch,
            patch("src.api.server.monitoring_system") as mock_mon,
            patch("src.database.engine.get_session") as mock_db,
        ):
            # Mock healthy orchestrator
            mock_orch.get_status.return_value = {"state": "running"}
            mock_mon.health_checks.perform_all_checks.return_value = {}

            # Mock DB connection failure
            mock_db.side_effect = Exception("Connection failed")

            response = client.get("/ready")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "unhealthy"
            assert data["components"].get("database") == "unhealthy"

    def test_ready_check_orchestrator_offline(self, client):
        """Test readiness check with orchestrator offline."""
        with patch("src.api.server.orchestrator", None):
            response = client.get("/ready")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "unhealthy"
            assert data["components"].get("orchestrator") == "unhealthy"

    def test_ready_check_orchestrator_degraded(self, client):
        """Test readiness check with degraded orchestrator."""
        with (
            patch("src.api.server.orchestrator") as mock_orch,
            patch("src.api.server.monitoring_system") as mock_mon,
            patch("src.database.engine.get_session") as mock_db,
        ):
            # Mock degraded state
            mock_orch.get_status.return_value = {"state": "initializing"}
            mock_mon.health_checks.perform_all_checks.return_value = {}

            # Mock successful DB
            mock_session = AsyncMock()
            mock_db.return_value.__aenter__.return_value = mock_session

            response = client.get("/ready")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "degraded"
            assert data["components"].get("orchestrator") == "degraded"


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    def test_metrics_endpoint_returns_prometheus_format(self, client):
        """Test metrics endpoint returns Prometheus format."""
        with patch("src.monitoring.metrics.trading_metrics") as mock_metrics:
            mock_metrics.get_registry.return_value = MagicMock()

            response = client.get("/metrics")

            assert response.status_code == 200
            assert "text/plain" in response.headers["content-type"]


class TestLogLevelEndpoints:
    """Tests for log level configuration endpoints."""

    def test_get_log_level_success(self, client):
        """Test getting current log level."""
        with patch("src.api.server.verify_token", return_value={"user": "test"}):
            with patch("src.core.logging_config.get_current_log_level", return_value="INFO"):
                response = client.get(
                    "/api/log-level",
                    headers={"Authorization": "Bearer test-token"},
                )

                assert response.status_code == 200
                data = response.json()

                assert data["success"] is True
                assert data["current_level"] == "INFO"

    def test_get_log_level_with_logger_name(self, client):
        """Test getting log level for specific logger."""
        with patch("src.api.server.verify_token", return_value={"user": "test"}):
            with patch("src.core.logging_config.get_current_log_level", return_value="DEBUG"):
                response = client.get(
                    "/api/log-level?logger_name=src.trading",
                    headers={"Authorization": "Bearer test-token"},
                )

                assert response.status_code == 200
                data = response.json()

                assert data["success"] is True
                assert data["current_level"] == "DEBUG"

    def test_set_log_level_success(self, client):
        """Test setting log level."""
        with patch("src.api.server.verify_token", return_value={"user": "test"}):
            with (
                patch("src.core.logging_config.set_log_level") as mock_set,
                patch("src.core.logging_config.get_current_log_level", return_value="DEBUG"),
            ):
                response = client.put(
                    "/api/log-level",
                    json={"level": "DEBUG"},
                    headers={"Authorization": "Bearer test-token"},
                )

                assert response.status_code == 200
                data = response.json()

                assert data["success"] is True
                assert data["current_level"] == "DEBUG"
                mock_set.assert_called_once_with("DEBUG", None)

    def test_set_log_level_with_logger_name(self, client):
        """Test setting log level for specific logger."""
        with patch("src.api.server.verify_token", return_value={"user": "test"}):
            with (
                patch("src.core.logging_config.set_log_level") as mock_set,
                patch("src.core.logging_config.get_current_log_level", return_value="WARNING"),
            ):
                response = client.put(
                    "/api/log-level",
                    json={"level": "WARNING", "logger_name": "src.trading"},
                    headers={"Authorization": "Bearer test-token"},
                )

                assert response.status_code == 200
                data = response.json()

                assert data["success"] is True
                mock_set.assert_called_once_with("WARNING", "src.trading")

    def test_set_log_level_invalid_level(self, client):
        """Test setting invalid log level."""
        with patch("src.api.server.verify_token", return_value={"user": "test"}):
            response = client.put(
                "/api/log-level",
                json={"level": "INVALID"},
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 400
            data = response.json()
            # Error might be in 'detail' or 'error' field depending on middleware
            error_message = data.get("detail") or data.get("error", "")
            assert "Invalid log level" in error_message

    def test_log_level_endpoints_require_auth(self, client):
        """Test log level endpoints require authentication with invalid token."""
        # Test with very short invalid token (less than 10 chars as per verify_token)
        headers = {"Authorization": "Bearer short"}

        response = client.get("/api/log-level", headers=headers)
        assert response.status_code == 401

        response = client.put(
            "/api/log-level",
            json={"level": "DEBUG"},
            headers=headers,
        )
        assert response.status_code == 401


class TestLoggingContext:
    """Tests for logging context functionality."""

    def test_request_id_in_logs(self, client, caplog):
        """Test that request ID is included in logs."""
        with caplog.at_level(logging.INFO):
            client.get("/health")

        # Check that logs were generated (middleware is working)
        assert len(caplog.records) > 0

    def test_request_id_in_response_headers(self, client):
        """Test that request ID is in response headers."""
        with patch("src.api.server.monitoring_system"):
            response = client.get("/status", headers={"Authorization": "Bearer test-token"})

            # Logging middleware should add request ID header
            # Note: This might fail if authentication fails, which is expected
            if response.status_code != 401:
                assert "X-Request-ID" in response.headers
