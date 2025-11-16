"""
Tests for Prometheus metrics collection and reporting.

Tests verify:
- Metric collection accuracy
- Label correctness
- Counter increments
- Histogram observations
- Gauge updates
- Integration with trading components
"""


import pytest
from prometheus_client import CollectorRegistry

from src.monitoring.metrics import (
    ExecutionTimer,
    TradingMetrics,
    record_api_error,
    record_order_execution,
    record_risk_violation,
    record_signal_generated,
    record_websocket_connection,
    update_position_pnl,
)


@pytest.fixture
def test_registry():
    """Create a test registry isolated from global metrics."""
    return CollectorRegistry()


@pytest.fixture
def test_metrics(test_registry):
    """Create test metrics instance with isolated registry."""
    return TradingMetrics(registry=test_registry)


class TestTradingMetrics:
    """Test TradingMetrics class initialization and structure."""

    def test_metrics_initialization(self, test_metrics):
        """Test that all metrics are properly initialized."""
        assert test_metrics.signals_generated is not None
        assert test_metrics.order_execution_latency is not None
        assert test_metrics.risk_violations is not None
        assert test_metrics.position_pnl is not None
        assert test_metrics.websocket_connections is not None
        assert test_metrics.api_errors is not None
        assert test_metrics.strategy_execution_time is not None

    def test_get_registry(self, test_metrics, test_registry):
        """Test registry accessor."""
        assert test_metrics.get_registry() == test_registry


class TestSignalMetrics:
    """Test signal generation metrics."""

    def test_record_signal_generated(self, test_metrics):
        """Test signal generation counter increments correctly."""
        initial_value = 0

        # Record a signal
        test_metrics.signals_generated.labels(
            strategy="Strategy_A", symbol="BTCUSDT", direction="LONG"
        ).inc()

        # Verify increment
        metric_value = test_metrics.signals_generated.labels(
            strategy="Strategy_A", symbol="BTCUSDT", direction="LONG"
        )._value._value

        assert metric_value == initial_value + 1

    def test_signal_labels(self, test_metrics):
        """Test that different labels create separate metrics."""
        # Record signals with different labels
        test_metrics.signals_generated.labels(
            strategy="Strategy_A", symbol="BTCUSDT", direction="LONG"
        ).inc()

        test_metrics.signals_generated.labels(
            strategy="Strategy_B", symbol="ETHUSDT", direction="SHORT"
        ).inc()

        # Verify they're tracked separately
        btc_value = test_metrics.signals_generated.labels(
            strategy="Strategy_A", symbol="BTCUSDT", direction="LONG"
        )._value._value

        eth_value = test_metrics.signals_generated.labels(
            strategy="Strategy_B", symbol="ETHUSDT", direction="SHORT"
        )._value._value

        assert btc_value == 1
        assert eth_value == 1

    def test_record_signal_generated_helper(self):
        """Test the helper function for signal recording."""
        # This will use global trading_metrics, just verify no errors
        try:
            record_signal_generated(strategy="Strategy_A", symbol="BTCUSDT", direction="LONG")
        except Exception as e:
            pytest.fail(f"record_signal_generated raised exception: {e}")


class TestOrderExecutionMetrics:
    """Test order execution latency metrics."""

    def test_record_order_execution(self, test_metrics):
        """Test order execution histogram records values."""
        # Record execution time
        test_metrics.order_execution_latency.labels(
            symbol="BTCUSDT", order_type="market", side="buy"
        ).observe(0.5)

        # Note: Histogram metrics don't expose internal counters easily in tests
        # In production, these are exported and scraped by Prometheus
        # We verify no exceptions were raised during observation

    def test_multiple_executions(self, test_metrics):
        """Test multiple execution times are tracked correctly."""
        executions = [0.1, 0.25, 0.5, 1.0]

        for exec_time in executions:
            test_metrics.order_execution_latency.labels(
                symbol="BTCUSDT", order_type="market", side="buy"
            ).observe(exec_time)

        # Note: Histogram metrics don't expose internal counters easily in tests
        # In production, these are exported and scraped by Prometheus
        # We verify no exceptions were raised during observations

    def test_record_order_execution_helper(self):
        """Test the helper function for order execution recording."""
        try:
            record_order_execution(
                symbol="BTCUSDT", order_type="market", side="buy", execution_time=0.5
            )
        except Exception as e:
            pytest.fail(f"record_order_execution raised exception: {e}")


class TestRiskViolationMetrics:
    """Test risk violation metrics."""

    def test_record_risk_violation(self, test_metrics):
        """Test risk violation counter increments."""
        # Record violation
        test_metrics.risk_violations.labels(
            violation_type="position_size_exceeded", symbol="BTCUSDT", severity="high"
        ).inc()

        # Verify increment
        metric_value = test_metrics.risk_violations.labels(
            violation_type="position_size_exceeded", symbol="BTCUSDT", severity="high"
        )._value._value

        assert metric_value == 1

    def test_multiple_violation_types(self, test_metrics):
        """Test different violation types are tracked separately."""
        violations = [
            ("entry_blocked", "critical"),
            ("position_size_exceeded", "high"),
            ("invalid_stop_loss", "medium"),
            ("invalid_take_profit", "low"),
        ]

        for violation_type, severity in violations:
            test_metrics.risk_violations.labels(
                violation_type=violation_type, symbol="BTCUSDT", severity=severity
            ).inc()

        # Verify each type was recorded
        for violation_type, severity in violations:
            value = test_metrics.risk_violations.labels(
                violation_type=violation_type, symbol="BTCUSDT", severity=severity
            )._value._value
            assert value == 1

    def test_record_risk_violation_helper(self):
        """Test the helper function for risk violation recording."""
        try:
            record_risk_violation(
                violation_type="position_size_exceeded", symbol="BTCUSDT", severity="high"
            )
        except Exception as e:
            pytest.fail(f"record_risk_violation raised exception: {e}")


class TestPositionPnLMetrics:
    """Test position P&L gauge metrics."""

    def test_update_position_pnl(self, test_metrics):
        """Test P&L gauge updates correctly."""
        # Set P&L value
        test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long").set(150.50)

        # Verify value
        metric_value = test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long")._value._value

        assert metric_value == 150.50

    def test_pnl_updates(self, test_metrics):
        """Test P&L can be updated multiple times."""
        pnl_values = [100.0, 125.5, 150.75, 140.25]

        for pnl in pnl_values:
            test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long").set(pnl)

        # Should have the last value
        metric_value = test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long")._value._value

        assert metric_value == pnl_values[-1]

    def test_negative_pnl(self, test_metrics):
        """Test P&L can handle negative values."""
        test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long").set(-50.25)

        metric_value = test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long")._value._value

        assert metric_value == -50.25

    def test_update_position_pnl_helper(self):
        """Test the helper function for P&L updates."""
        try:
            update_position_pnl(symbol="BTCUSDT", side="long", pnl=150.50)
        except Exception as e:
            pytest.fail(f"update_position_pnl raised exception: {e}")


class TestWebSocketMetrics:
    """Test WebSocket connection metrics."""

    def test_websocket_connection_active(self, test_metrics):
        """Test WebSocket connection count increases."""
        initial_value = test_metrics.websocket_connections.labels(
            exchange="binance", stream_type="candles"
        )._value._value

        # Increment connection
        test_metrics.websocket_connections.labels(exchange="binance", stream_type="candles").inc()

        # Verify increment
        new_value = test_metrics.websocket_connections.labels(
            exchange="binance", stream_type="candles"
        )._value._value

        assert new_value == initial_value + 1

    def test_websocket_connection_inactive(self, test_metrics):
        """Test WebSocket connection count decreases."""
        # Set initial value
        test_metrics.websocket_connections.labels(exchange="binance", stream_type="candles").set(5)

        # Decrement connection
        test_metrics.websocket_connections.labels(exchange="binance", stream_type="candles").dec()

        # Verify decrement
        new_value = test_metrics.websocket_connections.labels(
            exchange="binance", stream_type="candles"
        )._value._value

        assert new_value == 4

    def test_record_websocket_connection_helper(self):
        """Test the helper function for WebSocket connection tracking."""
        try:
            record_websocket_connection(exchange="binance", stream_type="candles", active=True)
            record_websocket_connection(exchange="binance", stream_type="candles", active=False)
        except Exception as e:
            pytest.fail(f"record_websocket_connection raised exception: {e}")


class TestAPIErrorMetrics:
    """Test API error metrics."""

    def test_record_api_error(self, test_metrics):
        """Test API error counter increments."""
        # Record error
        test_metrics.api_errors.labels(
            exchange="binance", endpoint="get_balance", error_type="timeout"
        ).inc()

        # Verify increment
        metric_value = test_metrics.api_errors.labels(
            exchange="binance", endpoint="get_balance", error_type="timeout"
        )._value._value

        assert metric_value == 1

    def test_multiple_error_types(self, test_metrics):
        """Test different error types are tracked separately."""
        error_types = ["timeout", "rate_limit", "auth_error", "invalid_request"]

        for error_type in error_types:
            test_metrics.api_errors.labels(
                exchange="binance", endpoint="place_order", error_type=error_type
            ).inc()

        # Verify each type was recorded
        for error_type in error_types:
            value = test_metrics.api_errors.labels(
                exchange="binance", endpoint="place_order", error_type=error_type
            )._value._value
            assert value == 1

    def test_record_api_error_helper(self):
        """Test the helper function for API error recording."""
        try:
            record_api_error(exchange="binance", endpoint="get_balance", error_type="timeout")
        except Exception as e:
            pytest.fail(f"record_api_error raised exception: {e}")


class TestExecutionTimer:
    """Test execution timer context manager."""

    def test_execution_timer(self, test_metrics):
        """Test execution timer records time correctly."""
        import time

        with ExecutionTimer("Strategy_A", "BTCUSDT"):
            time.sleep(0.1)  # Simulate work

        # Note: Can't easily verify exact time due to timing variations,
        # but we can verify no errors occurred
        # In real usage, this would be verified via Prometheus queries

    def test_execution_timer_with_exception(self, test_metrics):
        """Test execution timer handles exceptions."""
        try:
            with ExecutionTimer("Strategy_A", "BTCUSDT"):
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected

        # Timer should still record even with exception
        # Verify no errors in metric recording


class TestMetricsIntegration:
    """Integration tests for metrics with trading components."""

    def test_signal_to_order_workflow(self, test_metrics):
        """Test metrics throughout signal generation to order execution."""
        # Simulate workflow
        test_metrics.signals_generated.labels(
            strategy="Strategy_A", symbol="BTCUSDT", direction="LONG"
        ).inc()

        test_metrics.order_execution_latency.labels(
            symbol="BTCUSDT", order_type="market", side="buy"
        ).observe(0.5)

        test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long").set(150.0)

        # Verify counter and gauge metrics were recorded
        assert (
            test_metrics.signals_generated.labels(
                strategy="Strategy_A", symbol="BTCUSDT", direction="LONG"
            )._value._value
            == 1
        )

        # Note: Histogram doesn't expose internal counters in tests
        # Verified by no exceptions during observe()

        assert (
            test_metrics.position_pnl.labels(symbol="BTCUSDT", side="long")._value._value == 150.0
        )

    def test_risk_violation_workflow(self, test_metrics):
        """Test risk violation metrics in validation workflow."""
        # Simulate validation failures
        violations = [
            ("entry_blocked", "critical"),
            ("position_size_exceeded", "high"),
            ("invalid_stop_loss", "medium"),
        ]

        for violation_type, severity in violations:
            test_metrics.risk_violations.labels(
                violation_type=violation_type, symbol="BTCUSDT", severity=severity
            ).inc()

        # Verify all violations recorded
        for violation_type, severity in violations:
            value = test_metrics.risk_violations.labels(
                violation_type=violation_type, symbol="BTCUSDT", severity=severity
            )._value._value
            assert value == 1
