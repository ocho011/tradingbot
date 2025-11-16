"""
Signal Duplicate Filtering System

Detects and filters duplicate signals based on time windows, price ranges,
and cross-strategy similarity to prevent redundant trade entries.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.services.strategy.signal import Signal

logger = logging.getLogger(__name__)


class FilterConfig:
    """
    Configuration for signal filtering rules.

    Allows runtime adjustment of filtering thresholds and behavior.
    """

    def __init__(
        self,
        time_window_minutes: int = 5,
        price_threshold_pct: float = 1.0,
        enabled: bool = True,
        filter_cross_strategy: bool = True,
        check_position_conflicts: bool = True,
    ):
        """
        Initialize filter configuration.

        Args:
            time_window_minutes: Time window for duplicate detection (default: 5 minutes)
            price_threshold_pct: Price difference threshold in percentage (default: 1.0%)
            enabled: Enable/disable filtering (default: True)
            filter_cross_strategy: Filter similar signals across different strategies (default: True)
            check_position_conflicts: Check for conflicts with active positions (default: True)
        """
        self.time_window_minutes = time_window_minutes
        self.price_threshold_pct = price_threshold_pct
        self.enabled = enabled
        self.filter_cross_strategy = filter_cross_strategy
        self.check_position_conflicts = check_position_conflicts

    @property
    def time_window(self) -> timedelta:
        """Get time window as timedelta"""
        return timedelta(minutes=self.time_window_minutes)

    @property
    def price_threshold_decimal(self) -> Decimal:
        """Get price threshold as decimal"""
        return Decimal(str(self.price_threshold_pct / 100))

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            "time_window_minutes": self.time_window_minutes,
            "price_threshold_pct": self.price_threshold_pct,
            "enabled": self.enabled,
            "filter_cross_strategy": self.filter_cross_strategy,
            "check_position_conflicts": self.check_position_conflicts,
        }

    def __repr__(self) -> str:
        return (
            f"FilterConfig(window={self.time_window_minutes}min, "
            f"price_threshold={self.price_threshold_pct}%, enabled={self.enabled})"
        )


class SignalFilter:
    """
    Signal duplicate filtering system.

    Detects and filters duplicate signals based on:
    - Time window (default: 5 minutes)
    - Price range (default: 1% threshold)
    - Cross-strategy similarity
    - Position conflicts
    """

    def __init__(
        self,
        config: Optional[FilterConfig] = None,
        active_positions: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Initialize signal filter.

        Args:
            config: Filter configuration (creates default if None)
            active_positions: List of active trading positions for conflict detection
        """
        self.config = config or FilterConfig()
        self.recent_signals: List[Signal] = []
        self.active_positions = active_positions or []
        self.filtered_count = 0
        self.total_processed = 0

        logger.info(f"SignalFilter initialized with config: {self.config}")

    def should_filter_signal(self, signal: Signal) -> tuple[bool, Optional[str]]:
        """
        Determine if a signal should be filtered (is duplicate).

        Args:
            signal: Signal to check

        Returns:
            Tuple of (should_filter: bool, reason: Optional[str])
            - should_filter: True if signal should be filtered out
            - reason: Explanation of why signal was filtered (None if not filtered)
        """
        self.total_processed += 1

        # If filtering is disabled, accept all signals
        if not self.config.enabled:
            return False, None

        # Clean up old signals outside time window
        self._cleanup_old_signals()

        # Check for duplicates
        for existing_signal in self.recent_signals:
            is_duplicate, reason = self._is_duplicate(signal, existing_signal)
            if is_duplicate:
                self.filtered_count += 1
                logger.info(
                    f"Filtering duplicate signal {signal.signal_id[:8]}... "
                    f"(reason: {reason}, original: {existing_signal.signal_id[:8]}...)"
                )
                return True, reason

        # Check for position conflicts if enabled
        if self.config.check_position_conflicts:
            has_conflict, conflict_reason = self._check_position_conflict(signal)
            if has_conflict:
                self.filtered_count += 1
                logger.info(
                    f"Filtering signal {signal.signal_id[:8]}... due to position conflict: {conflict_reason}"
                )
                return True, conflict_reason

        # No duplicate or conflict found
        return False, None

    def add_signal(self, signal: Signal) -> bool:
        """
        Add signal to filter cache if not duplicate.

        Args:
            signal: Signal to add

        Returns:
            True if signal was added (not duplicate), False if filtered
        """
        should_filter, reason = self.should_filter_signal(signal)

        if should_filter:
            logger.debug(f"Signal {signal.signal_id[:8]}... filtered: {reason}")
            return False

        # Add to recent signals cache
        self.recent_signals.append(signal)
        logger.debug(
            f"Signal {signal.signal_id[:8]}... added to filter cache "
            f"(cache size: {len(self.recent_signals)})"
        )
        return True

    def _is_duplicate(
        self, new_signal: Signal, existing_signal: Signal
    ) -> tuple[bool, Optional[str]]:
        """
        Check if new signal is duplicate of existing signal.

        Args:
            new_signal: New signal to check
            existing_signal: Existing signal to compare against

        Returns:
            Tuple of (is_duplicate: bool, reason: Optional[str])
        """
        # Check 1: Time window
        time_diff = abs(new_signal.timestamp - existing_signal.timestamp)
        if time_diff > self.config.time_window:
            return False, None

        # Check 2: Symbol must match
        if new_signal.symbol != existing_signal.symbol:
            return False, None

        # Check 3: Direction must match (opposite directions are not duplicates)
        if new_signal.direction != existing_signal.direction:
            return False, None

        # Check 4: Price range (1% threshold by default)
        price_diff_pct = abs(
            (new_signal.entry_price - existing_signal.entry_price) / existing_signal.entry_price
        )

        if price_diff_pct > self.config.price_threshold_decimal:
            return False, None

        # Check 5: Cross-strategy filtering (optional)
        if not self.config.filter_cross_strategy:
            # If cross-strategy filtering is disabled, only filter same-strategy signals
            if new_signal.strategy_name != existing_signal.strategy_name:
                return False, None

        # All conditions met - this is a duplicate
        reason = (
            f"time_diff={time_diff.total_seconds():.1f}s "
            f"(< {self.config.time_window_minutes}min), "
            f"price_diff={float(price_diff_pct) * 100:.2f}% "
            f"(< {self.config.price_threshold_pct}%), "
            f"same_symbol={new_signal.symbol}, "
            f"same_direction={new_signal.direction.value}"
        )

        if self.config.filter_cross_strategy:
            reason += f", strategies={new_signal.strategy_name} vs {existing_signal.strategy_name}"

        return True, reason

    def _check_position_conflict(self, signal: Signal) -> tuple[bool, Optional[str]]:
        """
        Check if signal conflicts with active positions.

        Args:
            signal: Signal to check

        Returns:
            Tuple of (has_conflict: bool, reason: Optional[str])
        """
        if not self.active_positions:
            return False, None

        for position in self.active_positions:
            # Check if position is for the same symbol
            if position.get("symbol") != signal.symbol:
                continue

            # Check if position has the same direction
            position_direction = position.get("direction", "").upper()
            if position_direction == signal.direction.value:
                reason = (
                    f"Active {position_direction} position exists for {signal.symbol} "
                    f"(entry: {position.get('entry_price')})"
                )
                return True, reason

            # Check for opposite direction (hedging scenario)
            # This is generally allowed but could be configured
            # For now, we don't filter opposite directions

        return False, None

    def _cleanup_old_signals(self):
        """Remove signals outside the time window"""
        if not self.recent_signals:
            return

        cutoff_time = datetime.utcnow() - self.config.time_window
        original_count = len(self.recent_signals)

        self.recent_signals = [s for s in self.recent_signals if s.timestamp > cutoff_time]

        removed_count = original_count - len(self.recent_signals)
        if removed_count > 0:
            logger.debug(f"Cleaned up {removed_count} old signals from cache")

    def update_active_positions(self, positions: List[Dict[str, Any]]):
        """
        Update active positions for conflict detection.

        Args:
            positions: List of active position dictionaries
        """
        self.active_positions = positions
        logger.debug(f"Updated active positions: {len(positions)} positions")

    def update_config(self, **kwargs):
        """
        Update filter configuration at runtime.

        Args:
            **kwargs: Configuration parameters to update

        Example:
            filter.update_config(time_window_minutes=10, price_threshold_pct=2.0)
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"Updated filter config: {key}={value}")
            else:
                logger.warning(f"Unknown config parameter: {key}")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get filtering statistics.

        Returns:
            Dictionary with filtering metrics
        """
        filter_rate = (
            (self.filtered_count / self.total_processed * 100) if self.total_processed > 0 else 0.0
        )

        return {
            "total_processed": self.total_processed,
            "filtered_count": self.filtered_count,
            "accepted_count": self.total_processed - self.filtered_count,
            "filter_rate_pct": filter_rate,
            "cache_size": len(self.recent_signals),
            "active_positions": len(self.active_positions),
            "config": self.config.to_dict(),
        }

    def clear_cache(self):
        """Clear the signal cache"""
        self.recent_signals.clear()
        logger.info("Signal filter cache cleared")

    def reset_statistics(self):
        """Reset filtering statistics"""
        self.filtered_count = 0
        self.total_processed = 0
        logger.info("Signal filter statistics reset")

    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (
            f"SignalFilter(processed={stats['total_processed']}, "
            f"filtered={stats['filtered_count']}, "
            f"filter_rate={stats['filter_rate_pct']:.1f}%, "
            f"cache={stats['cache_size']})"
        )
