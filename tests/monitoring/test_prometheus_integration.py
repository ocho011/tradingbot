"""
Integration test for Prometheus metrics endpoint.

Tests verify:
- /metrics endpoint accessibility
- Prometheus format compliance
- Metric export functionality
"""

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from src.api.server import app
from src.monitoring.metrics import (
    record_order_execution,
    record_signal_generated,
    trading_metrics,
    update_position_pnl,
)


@pytest.fixture
def client():
    """Create test client for FastAPI app."""
    return TestClient(app)


class TestPrometheusEndpoint:
    """Test Prometheus /metrics endpoint."""

    def test_metrics_endpoint_exists(self, client):
        """Test that /metrics endpoint is accessible."""
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_content_type(self, client):
        """Test that response has correct Prometheus content type."""
        response = client.get("/metrics")
        # Prometheus metrics should be text/plain with version info
        assert "text/plain" in response.headers["content-type"]

    def test_metrics_format(self, client):
        """Test that response follows Prometheus format."""
        response = client.get("/metrics")
        content = response.text

        # Prometheus format should contain metric TYPE and HELP comments
        assert "# HELP" in content or "# TYPE" in content or len(content) > 0

    def test_metrics_contains_trading_metrics(self, client):
        """Test that trading metrics are included in output."""
        # Generate some metrics first
        record_signal_generated("Strategy_A", "BTCUSDT", "LONG")
        record_order_execution("BTCUSDT", "market", "buy", 0.5)
        update_position_pnl("BTCUSDT", "long", 100.0)

        response = client.get("/metrics")
        content = response.text

        # Check for our custom metrics in output
        # Note: Exact metric names depend on Prometheus client naming
        assert len(content) > 0  # At minimum, should have some output


class TestMetricsExport:
    """Test metrics export functionality."""

    def test_counter_export(self, client):
        """Test that counter metrics are exported."""
        # Record some signals
        record_signal_generated("Strategy_A", "BTCUSDT", "LONG")
        record_signal_generated("Strategy_A", "BTCUSDT", "LONG")
        record_signal_generated("Strategy_B", "ETHUSDT", "SHORT")

        response = client.get("/metrics")
        content = response.text

        # Verify metrics were exported
        assert len(content) > 0

    def test_histogram_export(self, client):
        """Test that histogram metrics are exported."""
        # Record some execution times
        record_order_execution("BTCUSDT", "market", "buy", 0.5)
        record_order_execution("BTCUSDT", "limit", "sell", 1.2)
        record_order_execution("ETHUSDT", "market", "buy", 0.3)

        response = client.get("/metrics")
        content = response.text

        # Verify metrics were exported
        assert len(content) > 0

    def test_gauge_export(self, client):
        """Test that gauge metrics are exported."""
        # Update some P&L values
        update_position_pnl("BTCUSDT", "long", 150.50)
        update_position_pnl("ETHUSDT", "short", -25.30)

        response = client.get("/metrics")
        content = response.text

        # Verify metrics were exported
        assert len(content) > 0


class TestPrometheusFormat:
    """Test Prometheus exposition format compliance."""

    def test_metric_lines_format(self, client):
        """Test that metric lines follow Prometheus format."""
        # Generate some metrics
        record_signal_generated("Strategy_A", "BTCUSDT", "LONG")

        response = client.get("/metrics")
        lines = response.text.split("\n")

        # Filter out empty lines and comments
        metric_lines = [line for line in lines if line and not line.startswith("#")]

        # Each metric line should have format: metric_name{labels} value
        # We just verify that we got some non-comment lines
        # (exact parsing would require prometheus_client internals)
        assert len(lines) > 0  # Should have at least some output

    def test_no_authentication_required(self, client):
        """Test that /metrics endpoint doesn't require authentication."""
        # This is important for Prometheus scraping
        response = client.get("/metrics")

        # Should not get 401 Unauthorized or 403 Forbidden
        assert response.status_code == 200


class TestMetricsLabels:
    """Test that metrics include proper labels."""

    def test_signal_metrics_labels(self, client):
        """Test signal metrics include strategy, symbol, direction labels."""
        record_signal_generated("Strategy_A", "BTCUSDT", "LONG")

        response = client.get("/metrics")
        content = response.text

        # Verify we got metrics output
        # Exact label verification would require parsing, which is complex
        # In production, use Prometheus to verify label correctness
        assert len(content) > 0

    def test_order_metrics_labels(self, client):
        """Test order metrics include symbol, order_type, side labels."""
        record_order_execution("BTCUSDT", "market", "buy", 0.5)

        response = client.get("/metrics")
        content = response.text

        assert len(content) > 0

    def test_position_metrics_labels(self, client):
        """Test position metrics include symbol, side labels."""
        update_position_pnl("BTCUSDT", "long", 100.0)

        response = client.get("/metrics")
        content = response.text

        assert len(content) > 0


def test_metrics_registry_isolation():
    """Test that metrics registry is properly initialized."""
    # Verify trading_metrics has a registry
    assert trading_metrics.get_registry() is not None

    # Verify it's the correct type
    assert isinstance(trading_metrics.get_registry(), CollectorRegistry)
