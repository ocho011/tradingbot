"""
Monitoring module for Prometheus metrics collection and distributed tracing.

Provides custom metrics for trading system observability including:
- Trading signal generation tracking
- Order execution latency monitoring
- Risk violation tracking
- Position P&L metrics

And distributed tracing with OpenTelemetry:
- End-to-end workflow tracing (signal → order execution)
- Exchange API call instrumentation
- Database operation tracking
- Performance monitoring with minimal overhead
"""

from src.monitoring.metrics import (
    trading_metrics,
    record_signal_generated,
    record_order_execution,
    record_risk_violation,
    update_position_pnl,
)
from src.monitoring.tracing import (
    TradingTracer,
    TracingConfig,
    get_tracer,
    init_tracing,
    shutdown_tracing,
)

__all__ = [
    # Metrics
    'trading_metrics',
    'record_signal_generated',
    'record_order_execution',
    'record_risk_violation',
    'update_position_pnl',
    # Tracing
    'TradingTracer',
    'TracingConfig',
    'get_tracer',
    'init_tracing',
    'shutdown_tracing',
]
