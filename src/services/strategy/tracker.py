"""
Signal Logging and Tracking System

Provides database persistence and performance tracking for trading signals.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.services.strategy.events import (
    SignalEvent,
    SignalEventPublisher,
    SignalEventType,
    get_event_publisher,
)
from src.services.strategy.signal import Signal

logger = logging.getLogger(__name__)


class SignalTracker:
    """
    Tracks signals and their outcomes for performance analysis.

    Provides in-memory tracking and performance metrics.
    Database persistence will be added in Task 8.5/8.6.
    """

    def __init__(
        self,
        event_publisher: Optional[SignalEventPublisher] = None,
        auto_subscribe: bool = True,
    ):
        """
        Initialize signal tracker.

        Args:
            event_publisher: Event publisher for signal events
            auto_subscribe: Automatically subscribe to signal events
        """
        self.event_publisher = event_publisher or get_event_publisher()

        # In-memory signal storage
        self._signals: List[Signal] = []

        # Statistics
        self._signals_tracked = 0
        self._signals_executed = 0
        self._signals_rejected = 0

        logger.info("SignalTracker initialized")

        # Auto-subscribe to events if requested
        if auto_subscribe:
            self._subscribe_to_events()

    def _subscribe_to_events(self):
        """Subscribe to signal events for automatic tracking"""
        self.event_publisher.subscribe(SignalEventType.SIGNAL_GENERATED, self._on_signal_generated)
        self.event_publisher.subscribe(SignalEventType.SIGNAL_VALIDATED, self._on_signal_validated)
        self.event_publisher.subscribe(SignalEventType.SIGNAL_REJECTED, self._on_signal_rejected)

        logger.info("SignalTracker subscribed to signal events")

    def _on_signal_generated(self, event: SignalEvent):
        """
        Handle signal_generated event.

        Args:
            event: Signal generation event
        """
        try:
            self.log_signal(event.signal, event.metadata)
            self._signals_tracked += 1
        except Exception as e:
            logger.error(f"Error handling signal_generated event: {e}", exc_info=True)

    def _on_signal_validated(self, event: SignalEvent):
        """
        Handle signal_validated event.

        Args:
            event: Signal validation event
        """
        logger.info(f"Signal validated: {event.signal.signal_id}")

    def _on_signal_rejected(self, event: SignalEvent):
        """
        Handle signal_rejected event.

        Args:
            event: Signal rejection event
        """
        self._signals_rejected += 1
        rejection_reason = event.metadata.get("reason", "Unknown")
        logger.warning(f"Signal rejected: {event.signal.signal_id}, reason: {rejection_reason}")

    def log_signal(self, signal: Signal, metadata: Optional[Dict[str, Any]] = None):
        """
        Log a signal to in-memory storage.

        Args:
            signal: Signal to log
            metadata: Additional metadata to store

        Note:
            Database persistence will be added in Task 8.5/8.6.
        """
        # Store in memory for now
        self._signals.append(signal)

        logger.info(
            f"Logged signal {signal.signal_id} "
            f"({signal.symbol} {signal.direction.value} @ {signal.entry_price})"
        )

    def get_signal_performance(
        self,
        strategy_name: Optional[str] = None,
        symbol: Optional[str] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get performance metrics for signals.

        Args:
            strategy_name: Filter by strategy (None = all strategies)
            symbol: Filter by symbol (None = all symbols)
            days: Number of days to analyze

        Returns:
            Dictionary with performance metrics

        Note:
            Currently returns basic in-memory metrics.
            Full database-backed metrics will be added in Task 8.5/8.6.
        """
        # Filter signals
        filtered_signals = self._signals

        if strategy_name:
            filtered_signals = [s for s in filtered_signals if s.strategy_name == strategy_name]

        if symbol:
            filtered_signals = [s for s in filtered_signals if s.symbol == symbol]

        # Time filter
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        filtered_signals = [s for s in filtered_signals if s.timestamp >= cutoff_date]

        metrics = {
            "total_signals": len(filtered_signals),
            "executed_signals": self._signals_executed,
            "pending_signals": len(filtered_signals),
            "winning_trades": 0,  # Will be tracked in Task 8.5/8.6
            "losing_trades": 0,  # Will be tracked in Task 8.5/8.6
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "average_pnl": 0.0,
            "strategy": strategy_name or "all",
            "symbol": symbol or "all",
            "period_days": days,
        }

        logger.info(f"Signal performance metrics: {metrics}")
        return metrics

    def get_recent_signals(
        self,
        limit: int = 10,
        strategy_name: Optional[str] = None,
    ) -> List[Signal]:
        """
        Get recent signals.

        Args:
            limit: Maximum number of signals to return
            strategy_name: Filter by strategy (None = all strategies)

        Returns:
            List of recent Signal objects
        """
        signals = self._signals

        if strategy_name:
            signals = [s for s in signals if s.strategy_name == strategy_name]

        # Sort by timestamp (most recent first) and limit
        signals = sorted(signals, key=lambda s: s.timestamp, reverse=True)[:limit]

        logger.debug(f"Retrieved {len(signals)} recent signals")
        return signals

    def get_statistics(self) -> Dict[str, int]:
        """
        Get tracker statistics.

        Returns:
            Dictionary with tracking statistics
        """
        return {
            "signals_tracked": self._signals_tracked,
            "signals_executed": self._signals_executed,
            "signals_rejected": self._signals_rejected,
        }

    def __repr__(self) -> str:
        return (
            f"SignalTracker(tracked={self._signals_tracked}, "
            f"executed={self._signals_executed}, rejected={self._signals_rejected})"
        )


# Global tracker instance
_global_tracker: Optional[SignalTracker] = None


def get_signal_tracker() -> SignalTracker:
    """
    Get the global signal tracker instance (singleton pattern).

    Returns:
        Global SignalTracker instance
    """
    global _global_tracker

    if _global_tracker is None:
        _global_tracker = SignalTracker(auto_subscribe=True)
        logger.info("Created global SignalTracker instance")

    return _global_tracker
