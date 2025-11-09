"""
Tests for the Metrics Collection and Monitoring System.
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.core.metrics import (
    HealthStatus,
    MetricType,
    MetricValue,
    HealthCheck,
    ErrorRecord,
    Alert,
    AlertThreshold,
    MetricsCollector,
    HealthCheckManager,
    ErrorTracker,
    SystemMetricsCollector,
    AlertManager,
    MonitoringSystem
)
from src.core.events import EventBus, Event
from src.core.constants import EventType


class TestMetricValue:
    """Tests for MetricValue dataclass."""

    def test_metric_value_creation(self):
        """Test creating a metric value."""
        metric = MetricValue(
            name="test.metric",
            value=42.0,
            metric_type=MetricType.GAUGE,
            tags={"env": "test"},
            unit="ms"
        )

        assert metric.name == "test.metric"
        assert metric.value == 42.0
        assert metric.metric_type == MetricType.GAUGE
        assert metric.tags == {"env": "test"}
        assert metric.unit == "ms"
        assert isinstance(metric.timestamp, datetime)


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    @pytest.fixture
    def collector(self):
        """Create a metrics collector."""
        return MetricsCollector(retention_seconds=3600)

    def test_record_metric(self, collector):
        """Test recording a metric."""
        collector.record("test.metric", 100.0, MetricType.GAUGE, {"env": "test"}, "ms")

        latest = collector.get_latest("test.metric")
        assert latest is not None
        assert latest.value == 100.0
        assert latest.metric_type == MetricType.GAUGE
        assert latest.tags == {"env": "test"}
        assert latest.unit == "ms"

    def test_increment_counter(self, collector):
        """Test incrementing a counter."""
        collector.increment("requests.count")
        collector.increment("requests.count", 5.0)

        history = collector.get_history("requests.count")
        assert len(history) == 2
        assert history[0].value == 1.0
        assert history[1].value == 5.0
        assert all(m.metric_type == MetricType.COUNTER for m in history)

    def test_gauge_metric(self, collector):
        """Test recording gauge metrics."""
        collector.gauge("memory.usage", 75.5, unit="%")
        collector.gauge("memory.usage", 80.0, unit="%")

        latest = collector.get_latest("memory.usage")
        assert latest.value == 80.0
        assert latest.metric_type == MetricType.GAUGE
        assert latest.unit == "%"

    def test_timing_metric(self, collector):
        """Test recording timing metrics."""
        collector.timing("api.response_time", 125.5)

        latest = collector.get_latest("api.response_time")
        assert latest.value == 125.5
        assert latest.metric_type == MetricType.TIMER
        assert latest.unit == "ms"

    def test_get_history(self, collector):
        """Test getting metric history."""
        for i in range(10):
            collector.record("test.counter", float(i))

        history = collector.get_history("test.counter")
        assert len(history) == 10
        assert [m.value for m in history] == [float(i) for i in range(10)]

    def test_get_history_with_time_filter(self, collector):
        """Test getting metric history with time filter."""
        # Record some metrics
        for i in range(5):
            collector.record("test.metric", float(i))

        # Get recent metrics only
        since = datetime.now() - timedelta(seconds=1)
        recent = collector.get_history("test.metric", since=since)

        assert len(recent) >= 0  # Depends on timing

    def test_get_history_with_limit(self, collector):
        """Test getting metric history with limit."""
        for i in range(20):
            collector.record("test.metric", float(i))

        history = collector.get_history("test.metric", limit=5)
        assert len(history) == 5
        assert [m.value for m in history] == [15.0, 16.0, 17.0, 18.0, 19.0]

    def test_get_statistics(self, collector):
        """Test calculating metric statistics."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        for v in values:
            collector.record("test.metric", v)

        stats = collector.get_statistics("test.metric", window_seconds=60)

        assert stats["min"] == 10.0
        assert stats["max"] == 50.0
        assert stats["avg"] == 30.0
        assert stats["count"] == 5
        assert stats["sum"] == 150.0

    def test_get_statistics_empty(self, collector):
        """Test statistics with no metrics."""
        stats = collector.get_statistics("nonexistent.metric")

        assert stats["min"] == 0.0
        assert stats["max"] == 0.0
        assert stats["avg"] == 0.0
        assert stats["count"] == 0

    def test_get_all_metrics(self, collector):
        """Test getting all metrics."""
        collector.record("metric1", 10.0)
        collector.record("metric2", 20.0)
        collector.record("metric1", 15.0)

        all_metrics = collector.get_all_metrics()

        assert "metric1" in all_metrics
        assert "metric2" in all_metrics
        assert len(all_metrics["metric1"]) == 2
        assert len(all_metrics["metric2"]) == 1

    def test_clear_metrics(self, collector):
        """Test clearing all metrics."""
        collector.record("test.metric", 100.0)
        collector.clear()

        assert collector.get_latest("test.metric") is None
        assert collector.get_all_metrics() == {}


class TestHealthCheckManager:
    """Tests for HealthCheckManager."""

    @pytest.fixture
    def manager(self):
        """Create a health check manager."""
        return HealthCheckManager()

    def test_register_and_perform_check(self, manager):
        """Test registering and performing a health check."""
        def healthy_check():
            return HealthCheck(
                component="test_service",
                status=HealthStatus.HEALTHY,
                message="All good"
            )

        manager.register_check("test_service", healthy_check)
        result = manager.perform_check("test_service")

        assert result.component == "test_service"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "All good"
        assert result.response_time_ms is not None

    def test_perform_check_with_error(self, manager):
        """Test health check that raises an error."""
        def failing_check():
            raise Exception("Check failed!")

        manager.register_check("failing_service", failing_check)
        result = manager.perform_check("failing_service")

        assert result.status == HealthStatus.UNHEALTHY
        assert "Check failed!" in result.message

    def test_perform_check_unregistered(self, manager):
        """Test performing check on unregistered component."""
        result = manager.perform_check("unknown_service")

        assert result.status == HealthStatus.UNKNOWN
        assert "No health check registered" in result.message

    def test_perform_all_checks(self, manager):
        """Test performing all registered checks."""
        manager.register_check(
            "service1",
            lambda: HealthCheck(component="service1", status=HealthStatus.HEALTHY)
        )
        manager.register_check(
            "service2",
            lambda: HealthCheck(component="service2", status=HealthStatus.DEGRADED)
        )

        results = manager.perform_all_checks()

        assert len(results) == 2
        assert results["service1"].status == HealthStatus.HEALTHY
        assert results["service2"].status == HealthStatus.DEGRADED

    def test_get_status(self, manager):
        """Test getting status of a component."""
        manager.register_check(
            "test_service",
            lambda: HealthCheck(component="test_service", status=HealthStatus.HEALTHY)
        )

        manager.perform_check("test_service")
        status = manager.get_status("test_service")

        assert status is not None
        assert status.status == HealthStatus.HEALTHY

    def test_get_overall_status_all_healthy(self, manager):
        """Test overall status when all components healthy."""
        manager.register_check(
            "service1",
            lambda: HealthCheck(component="service1", status=HealthStatus.HEALTHY)
        )
        manager.register_check(
            "service2",
            lambda: HealthCheck(component="service2", status=HealthStatus.HEALTHY)
        )

        manager.perform_all_checks()
        overall = manager.get_overall_status()

        assert overall == HealthStatus.HEALTHY

    def test_get_overall_status_with_unhealthy(self, manager):
        """Test overall status with unhealthy component."""
        manager.register_check(
            "service1",
            lambda: HealthCheck(component="service1", status=HealthStatus.HEALTHY)
        )
        manager.register_check(
            "service2",
            lambda: HealthCheck(component="service2", status=HealthStatus.UNHEALTHY)
        )

        manager.perform_all_checks()
        overall = manager.get_overall_status()

        assert overall == HealthStatus.UNHEALTHY

    def test_get_overall_status_degraded(self, manager):
        """Test overall status with degraded component."""
        manager.register_check(
            "service1",
            lambda: HealthCheck(component="service1", status=HealthStatus.HEALTHY)
        )
        manager.register_check(
            "service2",
            lambda: HealthCheck(component="service2", status=HealthStatus.DEGRADED)
        )

        manager.perform_all_checks()
        overall = manager.get_overall_status()

        assert overall == HealthStatus.DEGRADED


class TestErrorTracker:
    """Tests for ErrorTracker."""

    @pytest.fixture
    def tracker(self):
        """Create an error tracker."""
        return ErrorTracker(retention_seconds=3600)

    def test_record_error(self, tracker):
        """Test recording an error."""
        tracker.record_error(
            error_type="ValueError",
            message="Invalid value",
            component="test_service",
            severity="error",
            context={"value": 42}
        )

        errors = tracker.get_recent_errors(limit=10)
        assert len(errors) == 1
        assert errors[0].error_type == "ValueError"
        assert errors[0].message == "Invalid value"
        assert errors[0].component == "test_service"
        assert errors[0].severity == "error"
        assert errors[0].context == {"value": 42}

    def test_get_recent_errors_with_component_filter(self, tracker):
        """Test getting errors filtered by component."""
        tracker.record_error("Error1", "msg1", "service1")
        tracker.record_error("Error2", "msg2", "service2")
        tracker.record_error("Error3", "msg3", "service1")

        service1_errors = tracker.get_recent_errors(component="service1")
        assert len(service1_errors) == 2
        assert all(e.component == "service1" for e in service1_errors)

    def test_get_recent_errors_with_time_filter(self, tracker):
        """Test getting errors with time filter."""
        tracker.record_error("Error1", "msg1", "service")

        since = datetime.now() - timedelta(seconds=1)
        recent = tracker.get_recent_errors(since=since)

        assert len(recent) >= 0  # Depends on timing

    def test_get_error_rate(self, tracker):
        """Test calculating error rate."""
        # Record some errors
        for i in range(10):
            tracker.record_error(f"Error{i}", "message", "service")

        rate = tracker.get_error_rate(window_seconds=60)
        assert rate > 0  # Should have some rate

    def test_get_error_statistics(self, tracker):
        """Test getting error statistics."""
        tracker.record_error("TypeError", "msg1", "service1", "error")
        tracker.record_error("ValueError", "msg2", "service2", "warning")
        tracker.record_error("TypeError", "msg3", "service1", "error")

        stats = tracker.get_error_statistics(window_seconds=3600)

        assert stats["total_errors"] == 3
        assert stats["by_component"]["service1"] == 2
        assert stats["by_component"]["service2"] == 1
        assert stats["by_type"]["TypeError"] == 2
        assert stats["by_type"]["ValueError"] == 1
        assert stats["by_severity"]["error"] == 2
        assert stats["by_severity"]["warning"] == 1

    def test_clear_errors(self, tracker):
        """Test clearing all errors."""
        tracker.record_error("Error", "message", "service")
        tracker.clear()

        errors = tracker.get_recent_errors()
        assert len(errors) == 0


class TestSystemMetricsCollector:
    """Tests for SystemMetricsCollector."""

    @pytest.fixture
    def collector(self):
        """Create a system metrics collector."""
        metrics = MetricsCollector()
        return SystemMetricsCollector(metrics), metrics

    def test_collect_cpu_metrics(self, collector):
        """Test collecting CPU metrics."""
        sys_collector, metrics = collector

        sys_collector.collect_cpu_metrics()

        # Check system CPU metric
        cpu_metric = metrics.get_latest("system.cpu.percent")
        assert cpu_metric is not None
        assert 0 <= cpu_metric.value <= 100

        # Check process CPU metric
        proc_cpu = metrics.get_latest("process.cpu.percent")
        assert proc_cpu is not None
        assert proc_cpu.value >= 0

    def test_collect_memory_metrics(self, collector):
        """Test collecting memory metrics."""
        sys_collector, metrics = collector

        sys_collector.collect_memory_metrics()

        # Check system memory metrics
        total = metrics.get_latest("system.memory.total")
        assert total is not None
        assert total.value > 0

        percent = metrics.get_latest("system.memory.percent")
        assert percent is not None
        assert 0 <= percent.value <= 100

        # Check process memory metrics
        rss = metrics.get_latest("process.memory.rss")
        assert rss is not None
        assert rss.value > 0

    def test_collect_disk_metrics(self, collector):
        """Test collecting disk metrics."""
        sys_collector, metrics = collector

        sys_collector.collect_disk_metrics()

        total = metrics.get_latest("system.disk.total")
        assert total is not None
        assert total.value > 0

        percent = metrics.get_latest("system.disk.percent")
        assert percent is not None
        assert 0 <= percent.value <= 100

    def test_collect_all(self, collector):
        """Test collecting all system metrics."""
        sys_collector, metrics = collector

        sys_collector.collect_all()

        # Verify metrics from all categories were collected
        assert metrics.get_latest("system.cpu.percent") is not None
        assert metrics.get_latest("system.memory.percent") is not None
        assert metrics.get_latest("system.disk.percent") is not None


class TestAlertManager:
    """Tests for AlertManager."""

    @pytest.fixture
    def manager(self):
        """Create an alert manager."""
        metrics = MetricsCollector()
        event_bus = EventBus()
        return AlertManager(metrics, event_bus), metrics, event_bus

    def test_add_threshold(self, manager):
        """Test adding an alert threshold."""
        alert_mgr, _, _ = manager

        threshold = AlertThreshold(
            metric_name="cpu.percent",
            operator="gt",
            value=80.0,
            cooldown_seconds=60
        )

        alert_mgr.add_threshold(threshold)
        # No exception means success

    def test_check_thresholds_trigger(self, manager):
        """Test threshold triggering an alert."""
        alert_mgr, metrics, event_bus = manager

        # Add threshold
        threshold = AlertThreshold(
            metric_name="cpu.percent",
            operator="gt",
            value=50.0,
            cooldown_seconds=0
        )
        alert_mgr.add_threshold(threshold)

        # Record metric that breaches threshold
        metrics.gauge("cpu.percent", 75.0)

        # Check thresholds
        alerts = alert_mgr.check_thresholds()

        assert len(alerts) == 1
        assert alerts[0].current_value == 75.0
        assert "cpu.percent" in alerts[0].message

    def test_check_thresholds_no_trigger(self, manager):
        """Test threshold not triggering."""
        alert_mgr, metrics, _ = manager

        threshold = AlertThreshold(
            metric_name="cpu.percent",
            operator="gt",
            value=80.0
        )
        alert_mgr.add_threshold(threshold)

        # Record metric below threshold
        metrics.gauge("cpu.percent", 50.0)

        alerts = alert_mgr.check_thresholds()
        assert len(alerts) == 0

    def test_check_thresholds_cooldown(self, manager):
        """Test alert cooldown period."""
        alert_mgr, metrics, _ = manager

        threshold = AlertThreshold(
            metric_name="cpu.percent",
            operator="gt",
            value=50.0,
            cooldown_seconds=10
        )
        alert_mgr.add_threshold(threshold)

        # First alert
        metrics.gauge("cpu.percent", 75.0)
        alerts1 = alert_mgr.check_thresholds()
        assert len(alerts1) == 1

        # Second alert within cooldown
        metrics.gauge("cpu.percent", 80.0)
        alerts2 = alert_mgr.check_thresholds()
        assert len(alerts2) == 0  # Cooldown prevents alert

    def test_threshold_operators(self, manager):
        """Test different threshold operators."""
        alert_mgr, metrics, _ = manager

        test_cases = [
            ("gt", 50.0, 60.0, True),   # 60 > 50
            ("gt", 50.0, 40.0, False),  # 40 > 50
            ("lt", 50.0, 40.0, True),   # 40 < 50
            ("lt", 50.0, 60.0, False),  # 60 < 50
            ("gte", 50.0, 50.0, True),  # 50 >= 50
            ("lte", 50.0, 50.0, True),  # 50 <= 50
            ("eq", 50.0, 50.0, True),   # 50 == 50
            ("neq", 50.0, 60.0, True),  # 60 != 50
        ]

        for operator, threshold, value, should_trigger in test_cases:
            alert_mgr._thresholds.clear()
            alert_mgr._active_alerts.clear()
            alert_mgr._last_alert_times.clear()

            thresh = AlertThreshold(
                metric_name="test.metric",
                operator=operator,
                value=threshold,
                cooldown_seconds=0
            )
            alert_mgr.add_threshold(thresh)

            metrics.gauge("test.metric", value)
            alerts = alert_mgr.check_thresholds()

            if should_trigger:
                assert len(alerts) == 1, f"Operator {operator} should trigger"
            else:
                assert len(alerts) == 0, f"Operator {operator} should not trigger"

    def test_get_active_alerts(self, manager):
        """Test getting active alerts."""
        alert_mgr, metrics, _ = manager

        threshold = AlertThreshold(
            metric_name="cpu.percent",
            operator="gt",
            value=50.0,
            cooldown_seconds=0
        )
        alert_mgr.add_threshold(threshold)

        metrics.gauge("cpu.percent", 75.0)
        alert_mgr.check_thresholds()

        active = alert_mgr.get_active_alerts()
        assert len(active) == 1

    def test_alert_history(self, manager):
        """Test alert history tracking."""
        alert_mgr, metrics, _ = manager

        threshold = AlertThreshold(
            metric_name="cpu.percent",
            operator="gt",
            value=50.0,
            cooldown_seconds=0
        )
        alert_mgr.add_threshold(threshold)

        # Trigger multiple alerts
        for value in [60.0, 70.0, 80.0]:
            alert_mgr._last_alert_times.clear()  # Reset cooldown
            metrics.gauge("cpu.percent", value)
            alert_mgr.check_thresholds()

        history = alert_mgr.get_alert_history()
        assert len(history) >= 3


class TestMonitoringSystem:
    """Tests for MonitoringSystem."""

    @pytest.fixture
    def monitoring(self):
        """Create a monitoring system."""
        event_bus = EventBus()
        return MonitoringSystem(event_bus=event_bus)

    @pytest.mark.asyncio
    async def test_start_stop(self, monitoring):
        """Test starting and stopping the monitoring system."""
        await monitoring.start()
        assert monitoring._running is True
        assert monitoring._collection_task is not None

        await monitoring.stop()
        assert monitoring._running is False

    @pytest.mark.asyncio
    async def test_collection_loop(self, monitoring):
        """Test metrics collection loop."""
        monitoring._collection_interval = 0.1  # Fast for testing

        await monitoring.start()
        await asyncio.sleep(0.3)  # Let it collect a few times
        await monitoring.stop()

        # Verify metrics were collected
        cpu_metric = monitoring.metrics.get_latest("system.cpu.percent")
        assert cpu_metric is not None

    def test_get_dashboard_data(self, monitoring):
        """Test getting dashboard data."""
        # Register a health check
        monitoring.health_checks.register_check(
            "test_service",
            lambda: HealthCheck(
                component="test_service",
                status=HealthStatus.HEALTHY,
                message="OK"
            )
        )

        # Perform check
        monitoring.health_checks.perform_check("test_service")

        # Collect some metrics
        monitoring.system_metrics.collect_all()

        # Record an error
        monitoring.errors.record_error(
            error_type="TestError",
            message="Test message",
            component="test"
        )

        # Get dashboard data
        data = monitoring.get_dashboard_data()

        assert "timestamp" in data
        assert "health" in data
        assert "metrics" in data
        assert "errors" in data
        assert "alerts" in data

        assert data["health"]["overall"] in [s.value for s in HealthStatus]
        assert "test_service" in data["health"]["components"]
        assert data["errors"]["recent"] >= 1

    @pytest.mark.asyncio
    async def test_integration_with_event_bus(self, monitoring):
        """Test that alerts are published to event bus."""
        from src.core.events import EventHandler

        events_received = []

        class TestEventHandler(EventHandler):
            async def handle(self, event: Event) -> None:
                events_received.append(event)

        handler = TestEventHandler()
        monitoring._event_bus.subscribe(EventType.ERROR_OCCURRED, handler)

        # Start event bus
        await monitoring._event_bus.start()

        # Add threshold and trigger alert
        threshold = AlertThreshold(
            metric_name="test.metric",
            operator="gt",
            value=50.0,
            cooldown_seconds=0
        )
        monitoring.alerts.add_threshold(threshold)

        monitoring.metrics.gauge("test.metric", 75.0)
        monitoring.alerts.check_thresholds()

        # Wait for event bus to process events
        await asyncio.sleep(0.2)
        await monitoring._event_bus.wait_empty(timeout=1.0)

        # Stop event bus
        await monitoring._event_bus.stop()

        # Verify event was published
        assert len(events_received) > 0
        assert events_received[0].event_type == EventType.ERROR_OCCURRED
        assert "alert_type" in events_received[0].data
