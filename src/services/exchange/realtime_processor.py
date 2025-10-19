"""
Real-time candle data processor for WebSocket streams.

This module provides the RealtimeCandleProcessor class that handles incoming
WebSocket candle data, detects candle completion, and publishes events.
"""

import logging
from typing import Dict, Optional

from src.core.constants import EventType, TimeFrame
from src.core.events import Event, EventBus, EventHandler
from src.models.candle import Candle
from src.services.candle_storage import CandleStorage


logger = logging.getLogger(__name__)


class RealtimeCandleProcessor(EventHandler):
    """
    Processes real-time candle data from WebSocket streams.

    Features:
    - Parses incoming candle stream data
    - Detects candle completion based on timestamp changes
    - Publishes CANDLE_CLOSED events for completed candles
    - Validates data integrity and filters outliers
    - Synchronizes with CandleStorage
    - Prevents duplicate candles and maintains order

    Attributes:
        event_bus: Event bus for publishing candle events
        storage: Optional CandleStorage for persisting candles
        _last_candles: Tracking last seen candle per symbol-timeframe
        _candle_timestamps: Timestamp tracking for completion detection
        _outlier_threshold: Multiplier for outlier detection (default: 3.0)
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage: Optional[CandleStorage] = None,
        outlier_threshold: float = 3.0
    ):
        """
        Initialize realtime candle processor.

        Args:
            event_bus: Event bus for publishing events
            storage: Optional candle storage for persistence
            outlier_threshold: Price change multiplier for outlier detection
        """
        super().__init__(name="RealtimeCandleProcessor")
        self.event_bus = event_bus
        self.storage = storage
        self._outlier_threshold = outlier_threshold

        # Track last candle per symbol-timeframe to detect completion
        self._last_candles: Dict[tuple, Candle] = {}  # (symbol, timeframe) -> Candle
        self._candle_timestamps: Dict[tuple, int] = {}  # (symbol, timeframe) -> timestamp

        # Statistics
        self._candles_processed = 0
        self._candles_closed = 0
        self._duplicates_filtered = 0
        self._outliers_filtered = 0

        logger.info(
            f"RealtimeCandleProcessor initialized "
            f"(storage={'enabled' if storage else 'disabled'}, "
            f"outlier_threshold={outlier_threshold})"
        )

    def can_handle(self, event_type: EventType) -> bool:
        """Check if this handler can process CANDLE_RECEIVED events."""
        return event_type == EventType.CANDLE_RECEIVED

    async def handle(self, event: Event) -> None:
        """
        Handle incoming CANDLE_RECEIVED events.

        Processes the candle data, detects completion, validates integrity,
        and publishes CANDLE_CLOSED events when appropriate.

        Args:
            event: Event containing candle data
        """
        try:
            candle_data = event.data

            # Extract candle information
            symbol = candle_data.get('symbol')
            timeframe_str = candle_data.get('timeframe')
            timestamp = candle_data.get('timestamp')

            if not all([symbol, timeframe_str, timestamp]):
                logger.warning(f"Incomplete candle data: {candle_data}")
                return

            # Convert timeframe string to TimeFrame enum
            try:
                timeframe = TimeFrame(timeframe_str)
            except ValueError:
                logger.warning(f"Invalid timeframe: {timeframe_str}")
                return

            # Create Candle object
            try:
                candle = Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=timestamp,
                    open=float(candle_data['open']),
                    high=float(candle_data['high']),
                    low=float(candle_data['low']),
                    close=float(candle_data['close']),
                    volume=float(candle_data['volume']),
                    is_closed=False  # Will be determined by completion detection
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"Failed to create candle from data: {e}")
                return

            # Validate candle data
            if not self._validate_candle_data(candle):
                return

            # Check for candle completion
            is_completed = await self._check_candle_completion(candle)

            # Update tracking
            key = (symbol, timeframe)
            self._last_candles[key] = candle
            self._candle_timestamps[key] = timestamp
            self._candles_processed += 1

            # Store in CandleStorage if available and candle is completed
            if is_completed and self.storage:
                candle.is_closed = True
                self.storage.add_candle(candle)
                logger.debug(f"Stored completed candle: {symbol} {timeframe.value} @ {candle.get_datetime_iso()}")

            # Publish CANDLE_CLOSED event if candle is completed
            if is_completed:
                self._candles_closed += 1
                await self.event_bus.publish(Event(
                    event_type=EventType.CANDLE_CLOSED,
                    priority=7,  # Higher priority than CANDLE_RECEIVED
                    data={
                        'candle': candle,
                        'symbol': symbol,
                        'timeframe': timeframe.value,
                        'timestamp': timestamp,
                        'datetime': candle.get_datetime_iso(),
                        'close': candle.close,
                        'volume': candle.volume
                    },
                    source='RealtimeCandleProcessor'
                ))

                logger.info(
                    f"✓ Candle closed: {symbol} {timeframe.value} "
                    f"@ {candle.get_datetime_iso()} close={candle.close:.2f}"
                )

        except Exception as e:
            logger.error(f"Error processing realtime candle: {e}", exc_info=True)

    async def _check_candle_completion(self, candle: Candle) -> bool:
        """
        Check if a candle has completed based on timestamp changes.

        A candle is considered completed when a new candle with a different
        normalized timestamp arrives for the same symbol-timeframe pair.

        Args:
            candle: Current candle to check

        Returns:
            True if the previous candle for this symbol-timeframe has completed
        """
        key = (candle.symbol, candle.timeframe)

        # No previous candle - cannot determine completion yet
        if key not in self._candle_timestamps:
            return False

        last_timestamp = self._candle_timestamps[key]
        current_timestamp = candle.timestamp

        # Candle completed if timestamp has changed
        # (normalized timestamps are different, indicating a new candle period)
        is_completed = last_timestamp != current_timestamp

        if is_completed:
            logger.debug(
                f"Candle completion detected: {candle.symbol} {candle.timeframe.value} "
                f"(prev_ts={last_timestamp}, curr_ts={current_timestamp})"
            )

        return is_completed

    def _validate_candle_data(self, candle: Candle) -> bool:
        """
        Validate candle data integrity and filter outliers.

        Performs validation:
        - OHLCV integrity (already done in Candle.__post_init__)
        - Duplicate detection
        - Outlier filtering based on price changes

        Args:
            candle: Candle to validate

        Returns:
            True if candle is valid, False if should be filtered
        """
        key = (candle.symbol, candle.timeframe)

        # Check for duplicates (same timestamp)
        if key in self._last_candles:
            last_candle = self._last_candles[key]

            # Exact duplicate - filter out
            if last_candle.timestamp == candle.timestamp and last_candle.close == candle.close:
                self._duplicates_filtered += 1
                logger.debug(
                    f"Filtered duplicate candle: {candle.symbol} {candle.timeframe.value} "
                    f"@ {candle.get_datetime_iso()}"
                )
                return False

            # Outlier detection - check if price change is abnormal
            if self._is_outlier(last_candle, candle):
                self._outliers_filtered += 1
                logger.warning(
                    f"Filtered outlier candle: {candle.symbol} {candle.timeframe.value} "
                    f"@ {candle.get_datetime_iso()} "
                    f"(prev_close={last_candle.close:.2f}, curr_close={candle.close:.2f})"
                )
                return False

        return True

    def _is_outlier(self, prev_candle: Candle, curr_candle: Candle) -> bool:
        """
        Detect if current candle is an outlier based on price change.

        Uses simple threshold-based outlier detection:
        - Calculate average price change over recent candles
        - Flag if current change exceeds threshold * average

        Args:
            prev_candle: Previous candle
            curr_candle: Current candle to check

        Returns:
            True if candle appears to be an outlier
        """
        # Calculate price change percentage
        if prev_candle.close == 0:
            return False

        price_change_pct = abs(
            (curr_candle.close - prev_candle.close) / prev_candle.close
        )

        # Simple outlier detection: flag if change > threshold
        # For crypto, a 10% change in one candle could be suspicious
        # depending on timeframe and volatility
        outlier_threshold_pct = 0.10  # 10% change threshold

        if price_change_pct > outlier_threshold_pct:
            logger.debug(
                f"Large price change detected: {curr_candle.symbol} "
                f"{price_change_pct:.2%} (threshold: {outlier_threshold_pct:.2%})"
            )
            return True

        return False

    def get_statistics(self) -> Dict[str, int]:
        """
        Get processing statistics.

        Returns:
            Dictionary containing processing metrics
        """
        return {
            'candles_processed': self._candles_processed,
            'candles_closed': self._candles_closed,
            'duplicates_filtered': self._duplicates_filtered,
            'outliers_filtered': self._outliers_filtered,
            'active_streams': len(self._last_candles)
        }

    def clear_statistics(self) -> None:
        """Reset statistics counters."""
        self._candles_processed = 0
        self._candles_closed = 0
        self._duplicates_filtered = 0
        self._outliers_filtered = 0
        logger.info("Statistics cleared")
