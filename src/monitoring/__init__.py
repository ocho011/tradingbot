"""
Monitoring module for Prometheus metrics collection.

Provides custom metrics for trading system observability including:
- Trading signal generation tracking
- Order execution latency monitoring
- Risk violation tracking
- Position P&L metrics
"""

from src.monitoring.metrics import (
    trading_metrics,
    record_signal_generated,
    record_order_execution,
    record_risk_violation,
    update_position_pnl,
)

__all__ = [
    'trading_metrics',
    'record_signal_generated',
    'record_order_execution',
    'record_risk_violation',
    'update_position_pnl',
]
