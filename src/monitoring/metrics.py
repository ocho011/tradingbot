"""
Prometheus metrics definitions for trading system.

Provides custom metrics for comprehensive system observability:
- trading_signals_generated: Counter for tracking signal generation by strategy/symbol
- order_execution_latency: Histogram for order execution timing
- risk_violations: Counter for risk management violations by type
- position_pnl: Gauge for current position profit/loss by symbol
"""

import logging
import time
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, REGISTRY

logger = logging.getLogger(__name__)


# ==========================================================================
# Custom Metrics Registry
# ==========================================================================

class TradingMetrics:
    """
    Container for all trading-related Prometheus metrics.

    Provides centralized access to custom metrics with consistent labeling
    and documentation for monitoring trading system performance and behavior.
    """

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """
        Initialize trading metrics.

        Args:
            registry: Prometheus registry to use (defaults to REGISTRY)
        """
        self.registry = registry or REGISTRY

        # Trading signal generation counter
        self.signals_generated = Counter(
            name='trading_signals_generated_total',
            documentation='Total number of trading signals generated',
            labelnames=['strategy', 'symbol', 'direction'],
            registry=self.registry
        )

        # Order execution latency histogram
        self.order_execution_latency = Histogram(
            name='order_execution_latency_seconds',
            documentation='Time taken to execute orders from signal to fill',
            labelnames=['symbol', 'order_type', 'side'],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=self.registry
        )

        # Risk violations counter
        self.risk_violations = Counter(
            name='risk_violations_total',
            documentation='Total number of risk management violations',
            labelnames=['violation_type', 'symbol', 'severity'],
            registry=self.registry
        )

        # Position P&L gauge
        self.position_pnl = Gauge(
            name='position_pnl_usdt',
            documentation='Current position profit/loss in USDT',
            labelnames=['symbol', 'side'],
            registry=self.registry
        )

        # System health metrics
        self.websocket_connections = Gauge(
            name='websocket_connections_active',
            documentation='Number of active WebSocket connections',
            labelnames=['exchange', 'stream_type'],
            registry=self.registry
        )

        self.api_errors = Counter(
            name='api_errors_total',
            documentation='Total number of API errors',
            labelnames=['exchange', 'endpoint', 'error_type'],
            registry=self.registry
        )

        self.strategy_execution_time = Histogram(
            name='strategy_execution_seconds',
            documentation='Time taken to execute strategy logic',
            labelnames=['strategy', 'symbol'],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self.registry
        )

        logger.info("Trading metrics initialized successfully")

    def get_registry(self) -> CollectorRegistry:
        """Get the metrics registry."""
        return self.registry


# Global metrics instance
trading_metrics = TradingMetrics()


# ==========================================================================
# Helper Functions for Recording Metrics
# ==========================================================================

def record_signal_generated(
    strategy: str,
    symbol: str,
    direction: str
) -> None:
    """
    Record a trading signal generation event.

    Args:
        strategy: Strategy name (e.g., 'Strategy_A_Conservative')
        symbol: Trading pair symbol (e.g., 'BTCUSDT')
        direction: Signal direction ('LONG' or 'SHORT')
    """
    try:
        trading_metrics.signals_generated.labels(
            strategy=strategy,
            symbol=symbol,
            direction=direction
        ).inc()
        logger.debug(f"Recorded signal: {strategy} {symbol} {direction}")
    except Exception as e:
        logger.error(f"Failed to record signal metric: {e}")


def record_order_execution(
    symbol: str,
    order_type: str,
    side: str,
    execution_time: float
) -> None:
    """
    Record order execution latency.

    Args:
        symbol: Trading pair symbol
        order_type: Order type ('market', 'limit', etc.)
        side: Order side ('buy' or 'sell')
        execution_time: Execution time in seconds
    """
    try:
        trading_metrics.order_execution_latency.labels(
            symbol=symbol,
            order_type=order_type,
            side=side
        ).observe(execution_time)
        logger.debug(f"Recorded order execution: {symbol} {side} took {execution_time:.3f}s")
    except Exception as e:
        logger.error(f"Failed to record order execution metric: {e}")


def record_risk_violation(
    violation_type: str,
    symbol: str,
    severity: str = 'medium'
) -> None:
    """
    Record a risk management violation.

    Args:
        violation_type: Type of violation (e.g., 'max_position_exceeded', 'max_daily_loss')
        symbol: Trading pair symbol
        severity: Violation severity ('low', 'medium', 'high', 'critical')
    """
    try:
        trading_metrics.risk_violations.labels(
            violation_type=violation_type,
            symbol=symbol,
            severity=severity
        ).inc()
        logger.warning(f"Recorded risk violation: {violation_type} for {symbol} (severity: {severity})")
    except Exception as e:
        logger.error(f"Failed to record risk violation metric: {e}")


def update_position_pnl(
    symbol: str,
    side: str,
    pnl: float
) -> None:
    """
    Update position P&L gauge.

    Args:
        symbol: Trading pair symbol
        side: Position side ('long' or 'short')
        pnl: Current profit/loss in USDT
    """
    try:
        trading_metrics.position_pnl.labels(
            symbol=symbol,
            side=side
        ).set(pnl)
        logger.debug(f"Updated position P&L: {symbol} {side} = {pnl:.2f} USDT")
    except Exception as e:
        logger.error(f"Failed to update position P&L metric: {e}")


def record_websocket_connection(
    exchange: str,
    stream_type: str,
    active: bool
) -> None:
    """
    Update WebSocket connection count.

    Args:
        exchange: Exchange name (e.g., 'binance')
        stream_type: Stream type (e.g., 'candles', 'orders')
        active: Whether connection is active (True) or disconnected (False)
    """
    try:
        if active:
            trading_metrics.websocket_connections.labels(
                exchange=exchange,
                stream_type=stream_type
            ).inc()
        else:
            trading_metrics.websocket_connections.labels(
                exchange=exchange,
                stream_type=stream_type
            ).dec()
        logger.debug(f"Updated WebSocket connection: {exchange} {stream_type} active={active}")
    except Exception as e:
        logger.error(f"Failed to update WebSocket connection metric: {e}")


def record_api_error(
    exchange: str,
    endpoint: str,
    error_type: str
) -> None:
    """
    Record an API error.

    Args:
        exchange: Exchange name
        endpoint: API endpoint that failed
        error_type: Error type (e.g., 'timeout', 'rate_limit', 'auth_error')
    """
    try:
        trading_metrics.api_errors.labels(
            exchange=exchange,
            endpoint=endpoint,
            error_type=error_type
        ).inc()
        logger.debug(f"Recorded API error: {exchange} {endpoint} {error_type}")
    except Exception as e:
        logger.error(f"Failed to record API error metric: {e}")


class ExecutionTimer:
    """
    Context manager for timing strategy execution.

    Usage:
        with ExecutionTimer('Strategy_A', 'BTCUSDT'):
            # Execute strategy logic
            pass
    """

    def __init__(self, strategy: str, symbol: str):
        """
        Initialize execution timer.

        Args:
            strategy: Strategy name
            symbol: Trading pair symbol
        """
        self.strategy = strategy
        self.symbol = symbol
        self.start_time: Optional[float] = None

    def __enter__(self) -> 'ExecutionTimer':
        """Start timing."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and record metric."""
        if self.start_time is not None:
            execution_time = time.time() - self.start_time
            try:
                trading_metrics.strategy_execution_time.labels(
                    strategy=self.strategy,
                    symbol=self.symbol
                ).observe(execution_time)
                logger.debug(
                    f"Strategy execution: {self.strategy} {self.symbol} "
                    f"took {execution_time:.3f}s"
                )
            except Exception as e:
                logger.error(f"Failed to record strategy execution time: {e}")
