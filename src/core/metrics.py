"""
Metrics Collection and Monitoring System.

Provides comprehensive monitoring for system health, performance metrics,
error tracking, and alerting capabilities.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import RLock
from typing import Any, Callable, Deque, Dict, List, Optional

import psutil

from src.core.constants import EventType
from src.core.events import Event, EventBus

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Component health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class MetricType(Enum):
    """Types of metrics collected."""

    COUNTER = "counter"  # Monotonically increasing value
    GAUGE = "gauge"  # Point-in-time value
    HISTOGRAM = "histogram"  # Distribution of values
    TIMER = "timer"  # Duration measurement


@dataclass
class MetricValue:
    """Individual metric measurement."""

    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime = field(default_factory=datetime.now)
    tags: Dict[str, str] = field(default_factory=dict)
    unit: Optional[str] = None


@dataclass
class HealthCheck:
    """Component health check result."""

    component: str
    status: HealthStatus
    timestamp: datetime = field(default_factory=datetime.now)
    message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    response_time_ms: Optional[float] = None


@dataclass
class ErrorRecord:
    """Error occurrence record."""

    error_type: str
    message: str
    component: str
    timestamp: datetime = field(default_factory=datetime.now)
    severity: str = "error"  # debug, info, warning, error, critical
    stack_trace: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertThreshold:
    """Alert threshold configuration."""

    metric_name: str
    operator: str  # gt, lt, gte, lte, eq, neq
    value: float
    duration_seconds: int = 0  # Alert only if condition persists
    cooldown_seconds: int = 300  # Minimum time between alerts


@dataclass
class Alert:
    """Triggered alert."""

    threshold: AlertThreshold
    current_value: float
    timestamp: datetime = field(default_factory=datetime.now)
    message: str = ""
    severity: str = "warning"


class MetricsCollector:
    """
    Collects and aggregates metrics from various sources.
    """

    def __init__(self, retention_seconds: int = 3600):
        """
        Initialize metrics collector.

        Args:
            retention_seconds: How long to retain metric history
        """
        self._metrics: Dict[str, Deque[MetricValue]] = defaultdict(lambda: deque(maxlen=10000))
        self._retention_seconds = retention_seconds
        self._lock = RLock()
        self._start_time = datetime.now()

    def record(
        self,
        name: str,
        value: float,
        metric_type: MetricType = MetricType.GAUGE,
        tags: Optional[Dict[str, str]] = None,
        unit: Optional[str] = None,
    ) -> None:
        """
        Record a metric value.

        Args:
            name: Metric name
            value: Metric value
            metric_type: Type of metric
            tags: Additional tags for the metric
            unit: Unit of measurement
        """
        metric = MetricValue(
            name=name, value=value, metric_type=metric_type, tags=tags or {}, unit=unit
        )

        with self._lock:
            self._metrics[name].append(metric)
            self._cleanup_old_metrics(name)

    def increment(
        self, name: str, value: float = 1.0, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Increment a counter metric.

        Args:
            name: Counter name
            value: Increment value
            tags: Additional tags
        """
        self.record(name, value, MetricType.COUNTER, tags)

    def gauge(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
        unit: Optional[str] = None,
    ) -> None:
        """
        Record a gauge metric.

        Args:
            name: Gauge name
            value: Current value
            tags: Additional tags
            unit: Unit of measurement
        """
        self.record(name, value, MetricType.GAUGE, tags, unit)

    def timing(self, name: str, duration_ms: float, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Record a timing metric.

        Args:
            name: Timer name
            duration_ms: Duration in milliseconds
            tags: Additional tags
        """
        self.record(name, duration_ms, MetricType.TIMER, tags, "ms")

    def get_latest(self, name: str) -> Optional[MetricValue]:
        """
        Get the latest value for a metric.

        Args:
            name: Metric name

        Returns:
            Latest metric value or None
        """
        with self._lock:
            metrics = self._metrics.get(name)
            return metrics[-1] if metrics else None

    def get_history(
        self, name: str, since: Optional[datetime] = None, limit: Optional[int] = None
    ) -> List[MetricValue]:
        """
        Get metric history.

        Args:
            name: Metric name
            since: Only return metrics after this time
            limit: Maximum number of metrics to return

        Returns:
            List of metric values
        """
        with self._lock:
            metrics = list(self._metrics.get(name, []))

            if since:
                metrics = [m for m in metrics if m.timestamp >= since]

            if limit:
                metrics = metrics[-limit:]

            return metrics

    def get_statistics(self, name: str, window_seconds: int = 60) -> Dict[str, float]:
        """
        Calculate statistics for a metric over a time window.

        Args:
            name: Metric name
            window_seconds: Time window in seconds

        Returns:
            Dictionary with min, max, avg, count
        """
        since = datetime.now() - timedelta(seconds=window_seconds)
        metrics = self.get_history(name, since=since)

        if not metrics:
            return {"min": 0.0, "max": 0.0, "avg": 0.0, "count": 0}

        values = [m.value for m in metrics]
        return {
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "count": len(values),
            "sum": sum(values),
        }

    def _cleanup_old_metrics(self, name: str) -> None:
        """Remove metrics older than retention period."""
        cutoff = datetime.now() - timedelta(seconds=self._retention_seconds)
        metrics = self._metrics[name]

        # Remove old metrics from the front of the deque
        while metrics and metrics[0].timestamp < cutoff:
            metrics.popleft()

    def get_all_metrics(self) -> Dict[str, List[MetricValue]]:
        """Get all current metrics."""
        with self._lock:
            return {name: list(metrics) for name, metrics in self._metrics.items()}

    def clear(self) -> None:
        """Clear all metrics."""
        with self._lock:
            self._metrics.clear()


class HealthCheckManager:
    """
    Manages component health checks.
    """

    def __init__(self):
        self._health_checks: Dict[str, HealthCheck] = {}
        self._check_functions: Dict[str, Callable[[], HealthCheck]] = {}
        self._lock = RLock()

    def register_check(self, component: str, check_fn: Callable[[], HealthCheck]) -> None:
        """
        Register a health check function for a component.

        Args:
            component: Component name
            check_fn: Function that performs the health check
        """
        with self._lock:
            self._check_functions[component] = check_fn

    def perform_check(self, component: str) -> HealthCheck:
        """
        Perform health check for a component.

        Args:
            component: Component name

        Returns:
            Health check result
        """
        with self._lock:
            check_fn = self._check_functions.get(component)

            if not check_fn:
                return HealthCheck(
                    component=component,
                    status=HealthStatus.UNKNOWN,
                    message="No health check registered",
                )

            try:
                start = time.time()
                result = check_fn()
                result.response_time_ms = (time.time() - start) * 1000
                self._health_checks[component] = result
                return result
            except Exception as e:
                logger.error(f"Health check failed for {component}: {e}", exc_info=True)
                result = HealthCheck(
                    component=component,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check error: {str(e)}",
                )
                self._health_checks[component] = result
                return result

    def perform_all_checks(self) -> Dict[str, HealthCheck]:
        """
        Perform all registered health checks.

        Returns:
            Dictionary of component health checks
        """
        results = {}
        for component in list(self._check_functions.keys()):
            results[component] = self.perform_check(component)
        return results

    def get_status(self, component: str) -> Optional[HealthCheck]:
        """Get the last health check result for a component."""
        with self._lock:
            return self._health_checks.get(component)

    def get_all_statuses(self) -> Dict[str, HealthCheck]:
        """Get all health check statuses."""
        with self._lock:
            return self._health_checks.copy()

    def get_overall_status(self) -> HealthStatus:
        """
        Get overall system health status.

        Returns:
            HEALTHY if all healthy, UNHEALTHY if any unhealthy, DEGRADED otherwise
        """
        with self._lock:
            if not self._health_checks:
                return HealthStatus.UNKNOWN

            statuses = [check.status for check in self._health_checks.values()]

            if all(s == HealthStatus.HEALTHY for s in statuses):
                return HealthStatus.HEALTHY
            elif any(s == HealthStatus.UNHEALTHY for s in statuses):
                return HealthStatus.UNHEALTHY
            else:
                return HealthStatus.DEGRADED


class ErrorTracker:
    """
    Tracks and analyzes error occurrences.
    """

    def __init__(self, retention_seconds: int = 3600):
        """
        Initialize error tracker.

        Args:
            retention_seconds: How long to retain error history
        """
        self._errors: Deque[ErrorRecord] = deque(maxlen=10000)
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._retention_seconds = retention_seconds
        self._lock = RLock()

    def record_error(
        self,
        error_type: str,
        message: str,
        component: str,
        severity: str = "error",
        stack_trace: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an error occurrence.

        Args:
            error_type: Type/class of error
            message: Error message
            component: Component where error occurred
            severity: Error severity level
            stack_trace: Optional stack trace
            context: Additional context
        """
        error = ErrorRecord(
            error_type=error_type,
            message=message,
            component=component,
            severity=severity,
            stack_trace=stack_trace,
            context=context or {},
        )

        with self._lock:
            self._errors.append(error)
            self._error_counts[f"{component}:{error_type}"] += 1
            self._cleanup_old_errors()

    def get_recent_errors(
        self, component: Optional[str] = None, since: Optional[datetime] = None, limit: int = 100
    ) -> List[ErrorRecord]:
        """
        Get recent errors.

        Args:
            component: Filter by component
            since: Only return errors after this time
            limit: Maximum number of errors

        Returns:
            List of error records
        """
        with self._lock:
            errors = list(self._errors)

            if component:
                errors = [e for e in errors if e.component == component]

            if since:
                errors = [e for e in errors if e.timestamp >= since]

            return errors[-limit:]

    def get_error_rate(self, component: Optional[str] = None, window_seconds: int = 60) -> float:
        """
        Calculate error rate (errors per second).

        Args:
            component: Optional component filter
            window_seconds: Time window

        Returns:
            Errors per second
        """
        since = datetime.now() - timedelta(seconds=window_seconds)
        errors = self.get_recent_errors(component=component, since=since)
        return len(errors) / window_seconds if window_seconds > 0 else 0.0

    def get_error_statistics(self, window_seconds: int = 3600) -> Dict[str, Any]:
        """
        Get error statistics.

        Args:
            window_seconds: Time window

        Returns:
            Error statistics by component and type
        """
        since = datetime.now() - timedelta(seconds=window_seconds)
        errors = self.get_recent_errors(since=since, limit=10000)

        stats = {
            "total_errors": len(errors),
            "by_component": defaultdict(int),
            "by_type": defaultdict(int),
            "by_severity": defaultdict(int),
        }

        for error in errors:
            stats["by_component"][error.component] += 1
            stats["by_type"][error.error_type] += 1
            stats["by_severity"][error.severity] += 1

        return dict(stats)

    def _cleanup_old_errors(self) -> None:
        """Remove errors older than retention period."""
        cutoff = datetime.now() - timedelta(seconds=self._retention_seconds)

        while self._errors and self._errors[0].timestamp < cutoff:
            self._errors.popleft()

    def clear(self) -> None:
        """Clear all error records."""
        with self._lock:
            self._errors.clear()
            self._error_counts.clear()


class SystemMetricsCollector:
    """
    Collects system-level performance metrics (CPU, memory, etc.).
    """

    def __init__(self, metrics_collector: MetricsCollector):
        """
        Initialize system metrics collector.

        Args:
            metrics_collector: MetricsCollector instance to record metrics
        """
        self._collector = metrics_collector
        self._process = psutil.Process()

    def collect_cpu_metrics(self) -> None:
        """Collect CPU usage metrics."""
        try:
            # System-wide CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self._collector.gauge("system.cpu.percent", cpu_percent, unit="%")

            # Per-CPU
            cpu_percents = psutil.cpu_percent(interval=0.1, percpu=True)
            for i, percent in enumerate(cpu_percents):
                self._collector.gauge("system.cpu.percent", percent, tags={"cpu": str(i)}, unit="%")

            # Process CPU
            process_cpu = self._process.cpu_percent(interval=0.1)
            self._collector.gauge("process.cpu.percent", process_cpu, unit="%")

        except Exception as e:
            logger.error(f"Error collecting CPU metrics: {e}")

    def collect_memory_metrics(self) -> None:
        """Collect memory usage metrics."""
        try:
            # System memory
            mem = psutil.virtual_memory()
            self._collector.gauge("system.memory.total", mem.total, unit="bytes")
            self._collector.gauge("system.memory.available", mem.available, unit="bytes")
            self._collector.gauge("system.memory.used", mem.used, unit="bytes")
            self._collector.gauge("system.memory.percent", mem.percent, unit="%")

            # Process memory
            proc_mem = self._process.memory_info()
            self._collector.gauge("process.memory.rss", proc_mem.rss, unit="bytes")
            self._collector.gauge("process.memory.vms", proc_mem.vms, unit="bytes")

            # Memory percent for process
            proc_mem_percent = self._process.memory_percent()
            self._collector.gauge("process.memory.percent", proc_mem_percent, unit="%")

        except Exception as e:
            logger.error(f"Error collecting memory metrics: {e}")

    def collect_disk_metrics(self) -> None:
        """Collect disk usage metrics."""
        try:
            disk = psutil.disk_usage("/")
            self._collector.gauge("system.disk.total", disk.total, unit="bytes")
            self._collector.gauge("system.disk.used", disk.used, unit="bytes")
            self._collector.gauge("system.disk.free", disk.free, unit="bytes")
            self._collector.gauge("system.disk.percent", disk.percent, unit="%")

        except Exception as e:
            logger.error(f"Error collecting disk metrics: {e}")

    def collect_all(self) -> None:
        """Collect all system metrics."""
        self.collect_cpu_metrics()
        self.collect_memory_metrics()
        self.collect_disk_metrics()


class AlertManager:
    """
    Manages threshold-based alerting.
    """

    def __init__(self, metrics_collector: MetricsCollector, event_bus: Optional[EventBus] = None):
        """
        Initialize alert manager.

        Args:
            metrics_collector: MetricsCollector to monitor
            event_bus: Optional EventBus for alert notifications
        """
        self._collector = metrics_collector
        self._event_bus = event_bus
        self._thresholds: Dict[str, AlertThreshold] = {}
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: Deque[Alert] = deque(maxlen=1000)
        self._last_alert_times: Dict[str, datetime] = {}
        self._lock = RLock()

    def add_threshold(self, threshold: AlertThreshold) -> None:
        """
        Add an alert threshold.

        Args:
            threshold: Threshold configuration
        """
        with self._lock:
            key = f"{threshold.metric_name}:{threshold.operator}:{threshold.value}"
            self._thresholds[key] = threshold

    def remove_threshold(self, metric_name: str, operator: str, value: float) -> None:
        """Remove an alert threshold."""
        with self._lock:
            key = f"{metric_name}:{operator}:{value}"
            self._thresholds.pop(key, None)

    def check_thresholds(self) -> List[Alert]:
        """
        Check all thresholds and trigger alerts.

        Returns:
            List of triggered alerts
        """
        triggered_alerts = []

        with self._lock:
            for key, threshold in self._thresholds.items():
                metric = self._collector.get_latest(threshold.metric_name)

                if not metric:
                    continue

                # Check if threshold is breached
                if self._check_condition(metric.value, threshold.operator, threshold.value):
                    # Check cooldown period
                    last_alert = self._last_alert_times.get(key)
                    if last_alert:
                        cooldown = timedelta(seconds=threshold.cooldown_seconds)
                        if datetime.now() - last_alert < cooldown:
                            continue

                    # Create alert
                    alert = Alert(
                        threshold=threshold,
                        current_value=metric.value,
                        message=f"{threshold.metric_name} {threshold.operator} {threshold.value} (current: {metric.value})",
                    )

                    self._active_alerts[key] = alert
                    self._alert_history.append(alert)
                    self._last_alert_times[key] = datetime.now()
                    triggered_alerts.append(alert)

                    # Publish alert event
                    if self._event_bus:
                        try:
                            asyncio.create_task(
                                self._event_bus.publish(
                                    Event(
                                        priority=7,
                                        event_type=EventType.ERROR_OCCURRED,
                                        data={
                                            "alert_type": "threshold_breach",
                                            "metric": threshold.metric_name,
                                            "value": metric.value,
                                            "threshold": threshold.value,
                                            "message": alert.message,
                                        },
                                        source="AlertManager",
                                    )
                                )
                            )
                        except RuntimeError:
                            # No event loop running, skip event publishing
                            pass

                else:
                    # Clear active alert if condition no longer met
                    self._active_alerts.pop(key, None)

        return triggered_alerts

    def _check_condition(self, value: float, operator: str, threshold: float) -> bool:
        """Check if value meets threshold condition."""
        operators = {
            "gt": lambda v, t: v > t,
            "lt": lambda v, t: v < t,
            "gte": lambda v, t: v >= t,
            "lte": lambda v, t: v <= t,
            "eq": lambda v, t: v == t,
            "neq": lambda v, t: v != t,
        }
        op_func = operators.get(operator)
        return op_func(value, threshold) if op_func else False

    def get_active_alerts(self) -> List[Alert]:
        """Get currently active alerts."""
        with self._lock:
            return list(self._active_alerts.values())

    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """Get alert history."""
        with self._lock:
            return list(self._alert_history)[-limit:]


class MonitoringSystem:
    """
    Comprehensive monitoring system integrating all monitoring components.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        metrics_retention_seconds: int = 3600,
        error_retention_seconds: int = 3600,
    ):
        """
        Initialize monitoring system.

        Args:
            event_bus: Optional EventBus for notifications
            metrics_retention_seconds: Metric retention period
            error_retention_seconds: Error retention period
        """
        self.metrics = MetricsCollector(retention_seconds=metrics_retention_seconds)
        self.health_checks = HealthCheckManager()
        self.errors = ErrorTracker(retention_seconds=error_retention_seconds)
        self.system_metrics = SystemMetricsCollector(self.metrics)
        self.alerts = AlertManager(self.metrics, event_bus)

        self._event_bus = event_bus
        self._running = False
        self._collection_task: Optional[asyncio.Task] = None
        self._collection_interval = 10  # seconds

    async def start(self) -> None:
        """Start the monitoring system."""
        if self._running:
            return

        self._running = True
        self._collection_task = asyncio.create_task(self._collection_loop())
        logger.info("Monitoring system started")

    async def stop(self) -> None:
        """Stop the monitoring system."""
        self._running = False

        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass

        logger.info("Monitoring system stopped")

    async def _collection_loop(self) -> None:
        """Periodic metrics collection loop."""
        while self._running:
            try:
                # Collect system metrics
                self.system_metrics.collect_all()

                # Perform health checks
                self.health_checks.perform_all_checks()

                # Check alert thresholds
                alerts = self.alerts.check_thresholds()
                if alerts:
                    logger.warning(f"Triggered {len(alerts)} alerts")

                await asyncio.sleep(self._collection_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring collection loop: {e}", exc_info=True)
                self.errors.record_error(
                    error_type=type(e).__name__,
                    message=str(e),
                    component="MonitoringSystem",
                    severity="error",
                )
                await asyncio.sleep(self._collection_interval)

    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get real-time dashboard data.

        Returns:
            Dictionary with current system status and metrics
        """
        return {
            "timestamp": datetime.now().isoformat(),
            "health": {
                "overall": self.health_checks.get_overall_status().value,
                "components": {
                    name: {
                        "status": check.status.value,
                        "message": check.message,
                        "response_time_ms": check.response_time_ms,
                    }
                    for name, check in self.health_checks.get_all_statuses().items()
                },
            },
            "metrics": {
                "cpu": (
                    self.metrics.get_latest("system.cpu.percent").value
                    if self.metrics.get_latest("system.cpu.percent")
                    else 0
                ),
                "memory": (
                    self.metrics.get_latest("system.memory.percent").value
                    if self.metrics.get_latest("system.memory.percent")
                    else 0
                ),
                "disk": (
                    self.metrics.get_latest("system.disk.percent").value
                    if self.metrics.get_latest("system.disk.percent")
                    else 0
                ),
            },
            "errors": {
                "recent": len(self.errors.get_recent_errors(limit=100)),
                "rate_per_second": self.errors.get_error_rate(window_seconds=60),
                "statistics": self.errors.get_error_statistics(window_seconds=3600),
            },
            "alerts": {
                "active": len(self.alerts.get_active_alerts()),
                "recent": [
                    {
                        "message": alert.message,
                        "severity": alert.severity,
                        "timestamp": alert.timestamp.isoformat(),
                    }
                    for alert in self.alerts.get_alert_history(limit=10)
                ],
            },
        }
