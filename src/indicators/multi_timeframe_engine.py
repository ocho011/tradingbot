"""
Multi-Timeframe Indicator Calculation Engine for ICT trading methodology.

This module implements parallel calculation of ICT indicators (Order Blocks, FVG, Breaker Blocks)
across multiple timeframes (1m, 15m, 1h) with synchronized data management and efficient
cross-timeframe analysis capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Set, Callable, Any
import logging
from collections import defaultdict
from threading import Lock

from src.models.candle import Candle
from src.core.constants import TimeFrame
from src.indicators.order_block import (
    OrderBlock,
    OrderBlockDetector,
    OrderBlockType,
    OrderBlockState
)
from src.indicators.fair_value_gap import (
    FairValueGap,
    FVGDetector,
    FVGType,
    FVGState
)
from src.indicators.breaker_block import (
    BreakerBlock,
    BreakerBlockDetector,
    BreakerBlockType
)
from src.indicators.expiration_manager import (
    IndicatorExpirationManager,
    ExpirationRules
)


logger = logging.getLogger(__name__)


class IndicatorType(str, Enum):
    """Types of ICT indicators supported."""
    ORDER_BLOCK = "order_block"
    FAIR_VALUE_GAP = "fair_value_gap"
    BREAKER_BLOCK = "breaker_block"


@dataclass
class TimeframeIndicators:
    """
    Container for all indicators detected in a specific timeframe.

    Attributes:
        timeframe: The timeframe these indicators belong to
        order_blocks: List of detected Order Blocks
        fair_value_gaps: List of detected Fair Value Gaps
        breaker_blocks: List of detected Breaker Blocks
        last_update_timestamp: Last time indicators were calculated
        candle_count: Number of candles processed
    """
    timeframe: TimeFrame
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fair_value_gaps: List[FairValueGap] = field(default_factory=list)
    breaker_blocks: List[BreakerBlock] = field(default_factory=list)
    last_update_timestamp: Optional[int] = None
    candle_count: int = 0

    def get_active_order_blocks(self) -> List[OrderBlock]:
        """Get all active (non-broken) Order Blocks."""
        return [ob for ob in self.order_blocks if ob.state == OrderBlockState.ACTIVE]

    def get_active_fvgs(self) -> List[FairValueGap]:
        """Get all active (unfilled) Fair Value Gaps."""
        return [fvg for fvg in self.fair_value_gaps if fvg.state == FVGState.ACTIVE]

    def get_active_breaker_blocks(self) -> List[BreakerBlock]:
        """Get all active Breaker Blocks."""
        return [bb for bb in self.breaker_blocks if bb.state == "ACTIVE"]

    def clear(self) -> None:
        """Clear all indicators."""
        self.order_blocks.clear()
        self.fair_value_gaps.clear()
        self.breaker_blocks.clear()
        self.last_update_timestamp = None
        self.candle_count = 0


@dataclass
class TimeframeData:
    """
    Storage for candle data and indicators for a specific timeframe.

    Attributes:
        timeframe: The timeframe
        candles: Historical candle data (limited to max_candles)
        indicators: Detected indicators for this timeframe
        max_candles: Maximum number of candles to retain
    """
    timeframe: TimeFrame
    candles: List[Candle] = field(default_factory=list)
    indicators: TimeframeIndicators = field(default_factory=lambda: TimeframeIndicators(TimeFrame.M1))
    max_candles: int = 1000

    def __post_init__(self):
        """Initialize indicators with correct timeframe."""
        self.indicators = TimeframeIndicators(timeframe=self.timeframe)

    def add_candle(self, candle: Candle) -> None:
        """
        Add a new candle, maintaining max_candles limit.

        Args:
            candle: New candle to add
        """
        # Ensure candle is for this timeframe
        if candle.timeframe != self.timeframe:
            raise ValueError(
                f"Candle timeframe {candle.timeframe} doesn't match "
                f"TimeframeData timeframe {self.timeframe}"
            )

        # Add candle
        self.candles.append(candle)

        # Trim to max_candles
        if len(self.candles) > self.max_candles:
            # Remove oldest candles
            excess = len(self.candles) - self.max_candles
            self.candles = self.candles[excess:]
            logger.debug(
                f"Trimmed {excess} candles from {self.timeframe.value}, "
                f"now have {len(self.candles)} candles"
            )

    def get_latest_candle(self) -> Optional[Candle]:
        """Get the most recent candle."""
        return self.candles[-1] if self.candles else None

    def get_candles_since(self, timestamp: int) -> List[Candle]:
        """Get all candles after a specific timestamp."""
        return [c for c in self.candles if c.timestamp > timestamp]


class MultiTimeframeIndicatorEngine:
    """
    Multi-timeframe indicator calculation engine.

    Manages parallel calculation of ICT indicators across multiple timeframes
    with data synchronization, efficient updates, and cross-timeframe analysis.

    Key Features:
    - Independent indicator state per timeframe
    - Automatic candle aggregation (1m → 15m → 1h)
    - Event-driven updates on new candle data
    - Thread-safe operations
    - Memory-efficient with configurable retention
    """

    def __init__(
        self,
        timeframes: Optional[List[TimeFrame]] = None,
        max_candles_per_timeframe: int = 1000,
        ob_detector_config: Optional[Dict[str, Any]] = None,
        fvg_detector_config: Optional[Dict[str, Any]] = None,
        bb_detector_config: Optional[Dict[str, Any]] = None,
        expiration_rules: Optional[ExpirationRules] = None,
        auto_remove_expired: bool = True,
    ):
        """
        Initialize multi-timeframe indicator engine.

        Args:
            timeframes: List of timeframes to track (default: [1m, 15m, 1h])
            max_candles_per_timeframe: Max candles to retain per timeframe
            ob_detector_config: Configuration for Order Block detector
            fvg_detector_config: Configuration for FVG detector
            bb_detector_config: Configuration for Breaker Block detector
            expiration_rules: Custom expiration rules, or None for defaults
            auto_remove_expired: If True, automatically remove expired indicators
        """
        # Default timeframes: 1m, 15m, 1h
        self.timeframes = timeframes or [TimeFrame.M1, TimeFrame.M15, TimeFrame.H1]

        # Validate timeframes are in ascending order
        self._validate_timeframes()

        # Initialize storage for each timeframe
        self.timeframe_data: Dict[TimeFrame, TimeframeData] = {
            tf: TimeframeData(
                timeframe=tf,
                max_candles=max_candles_per_timeframe
            )
            for tf in self.timeframes
        }

        # Initialize detectors
        self.ob_detector = OrderBlockDetector(**(ob_detector_config or {}))
        self.fvg_detector = FVGDetector(**(fvg_detector_config or {}))
        self.bb_detector = BreakerBlockDetector(**(bb_detector_config or {}))

        # Initialize expiration manager
        self.expiration_manager = IndicatorExpirationManager(
            expiration_rules=expiration_rules,
            auto_remove_expired=auto_remove_expired
        )

        # Thread safety
        self._lock = Lock()

        # Event callbacks
        self._callbacks: Dict[IndicatorType, List[Callable]] = defaultdict(list)

        logger.info(
            f"Initialized MultiTimeframeIndicatorEngine with timeframes: "
            f"{[tf.value for tf in self.timeframes]}, "
            f"auto_remove_expired={auto_remove_expired}"
        )

    def _validate_timeframes(self) -> None:
        """Validate that timeframes are in ascending order of duration."""
        tf_durations = {
            TimeFrame.M1: 1,
            TimeFrame.M5: 5,
            TimeFrame.M15: 15,
            TimeFrame.M30: 30,
            TimeFrame.H1: 60,
            TimeFrame.H4: 240,
            TimeFrame.D1: 1440,
        }

        durations = [tf_durations[tf] for tf in self.timeframes]
        if durations != sorted(durations):
            raise ValueError(
                f"Timeframes must be in ascending order. Got: "
                f"{[tf.value for tf in self.timeframes]}"
            )

    def register_callback(
        self,
        indicator_type: IndicatorType,
        callback: Callable[[TimeFrame, Any], None]
    ) -> None:
        """
        Register a callback for indicator detection events.

        Args:
            indicator_type: Type of indicator to listen for
            callback: Function(timeframe, indicator) to call when detected
        """
        self._callbacks[indicator_type].append(callback)
        logger.debug(
            f"Registered callback for {indicator_type.value} events"
        )

    def _trigger_callbacks(
        self,
        indicator_type: IndicatorType,
        timeframe: TimeFrame,
        indicators: List[Any]
    ) -> None:
        """Trigger callbacks for detected indicators."""
        for callback in self._callbacks[indicator_type]:
            try:
                for indicator in indicators:
                    callback(timeframe, indicator)
            except Exception as e:
                logger.error(
                    f"Error in callback for {indicator_type.value}: {e}",
                    exc_info=True
                )

    def add_candle(self, candle: Candle) -> None:
        """
        Add a new candle to the engine.

        Automatically determines which timeframes need updating based on
        the candle's timeframe and triggers indicator calculations.

        Args:
            candle: New candle data
        """
        with self._lock:
            timeframe = candle.timeframe

            # Validate timeframe is tracked
            if timeframe not in self.timeframe_data:
                raise ValueError(
                    f"Timeframe {timeframe.value} not configured. "
                    f"Available: {[tf.value for tf in self.timeframes]}"
                )

            # Add to appropriate timeframe
            self.timeframe_data[timeframe].add_candle(candle)

            logger.debug(
                f"Added candle to {timeframe.value}: {candle.symbol} @ "
                f"{candle.get_datetime_iso()}"
            )

            # Update indicators for this timeframe
            self._update_indicators(timeframe)

            # Check if higher timeframes need aggregation
            if candle.is_closed:
                self._aggregate_to_higher_timeframes(candle)

    def _aggregate_to_higher_timeframes(self, base_candle: Candle) -> None:
        """
        Aggregate base candle to higher timeframes if a new period starts.

        Args:
            base_candle: Closed candle from base timeframe
        """
        base_tf = base_candle.timeframe

        # Find position of base timeframe
        try:
            base_idx = self.timeframes.index(base_tf)
        except ValueError:
            return

        # Check each higher timeframe
        for higher_tf in self.timeframes[base_idx + 1:]:
            # Check if we need to create a new higher timeframe candle
            if self._should_aggregate_to_timeframe(base_candle, higher_tf):
                aggregated = self._create_aggregated_candle(base_candle, higher_tf)
                if aggregated:
                    self.timeframe_data[higher_tf].add_candle(aggregated)
                    logger.info(
                        f"Aggregated {base_tf.value} → {higher_tf.value}: "
                        f"{aggregated.get_datetime_iso()}"
                    )

                    # Update indicators for aggregated timeframe
                    self._update_indicators(higher_tf)

    def _should_aggregate_to_timeframe(
        self,
        candle: Candle,
        target_tf: TimeFrame
    ) -> bool:
        """
        Check if candle should trigger aggregation to target timeframe.

        A candle triggers aggregation when the NEXT candle would start
        a new target timeframe period.

        Args:
            candle: Base candle
            target_tf: Target timeframe to aggregate to

        Returns:
            True if aggregation should occur
        """
        # Get target timeframe duration in milliseconds
        target_ms = Candle.get_timeframe_milliseconds(target_tf)

        # Calculate what the next candle's timestamp would be
        next_candle_ts = Candle.calculate_next_candle_time(
            candle.timestamp,
            candle.timeframe
        )

        # Check if next candle starts a new target timeframe period
        # This happens when next_candle_ts is aligned to target boundary
        return (next_candle_ts % target_ms) == 0

    def _create_aggregated_candle(
        self,
        base_candle: Candle,
        target_tf: TimeFrame
    ) -> Optional[Candle]:
        """
        Create aggregated candle for higher timeframe.

        Args:
            base_candle: Base candle that triggered aggregation
            target_tf: Target timeframe

        Returns:
            Aggregated candle or None if insufficient data
        """
        # Get base timeframe data
        base_tf = base_candle.timeframe
        base_data = self.timeframe_data[base_tf]

        # Calculate how many base candles make up one target candle
        base_ms = Candle.get_timeframe_milliseconds(base_tf)
        target_ms = Candle.get_timeframe_milliseconds(target_tf)
        candles_per_period = target_ms // base_ms

        # Get last N base candles for aggregation
        recent_candles = base_data.candles[-candles_per_period:]

        if len(recent_candles) < candles_per_period:
            logger.warning(
                f"Insufficient candles for aggregation: "
                f"need {candles_per_period}, have {len(recent_candles)}"
            )
            return None

        # Calculate aggregated OHLCV
        normalized_timestamp = Candle.normalize_timestamp(
            base_candle.timestamp,
            target_tf
        )

        aggregated = Candle(
            symbol=base_candle.symbol,
            timeframe=target_tf,
            timestamp=normalized_timestamp,
            open=recent_candles[0].open,
            high=max(c.high for c in recent_candles),
            low=min(c.low for c in recent_candles),
            close=recent_candles[-1].close,
            volume=sum(c.volume for c in recent_candles),
            is_closed=True
        )

        return aggregated

    def _update_indicators(self, timeframe: TimeFrame) -> None:
        """
        Update all indicators for a specific timeframe.

        Args:
            timeframe: Timeframe to update
        """
        tf_data = self.timeframe_data[timeframe]

        # Need sufficient candles for analysis
        if len(tf_data.candles) < 10:
            logger.debug(
                f"Insufficient candles for {timeframe.value} indicators: "
                f"{len(tf_data.candles)}"
            )
            return

        try:
            # Detect Order Blocks
            new_obs = self.ob_detector.detect_order_blocks(tf_data.candles)

            # Update existing OBs
            existing_obs = tf_data.indicators.order_blocks
            for ob in existing_obs:
                if ob.state == OrderBlockState.ACTIVE:
                    # Check if OB is tested by recent price
                    latest = tf_data.get_latest_candle()
                    if latest and ob.contains_price(latest.close):
                        ob.mark_tested(latest.timestamp)

            # Add new OBs (avoid duplicates by timestamp)
            existing_timestamps = {ob.origin_timestamp for ob in existing_obs}
            for ob in new_obs:
                if ob.origin_timestamp not in existing_timestamps:
                    tf_data.indicators.order_blocks.append(ob)
                    self._trigger_callbacks(IndicatorType.ORDER_BLOCK, timeframe, [ob])

            # Detect Fair Value Gaps
            new_fvgs = self.fvg_detector.detect_fair_value_gaps(tf_data.candles)

            # Update existing FVGs
            self.fvg_detector.update_fvg_states(
                tf_data.indicators.fair_value_gaps,
                tf_data.candles[-10:]  # Check last 10 candles
            )

            # Add new FVGs
            existing_fvg_timestamps = {
                fvg.origin_timestamp for fvg in tf_data.indicators.fair_value_gaps
            }
            for fvg in new_fvgs:
                if fvg.origin_timestamp not in existing_fvg_timestamps:
                    tf_data.indicators.fair_value_gaps.append(fvg)
                    self._trigger_callbacks(IndicatorType.FAIR_VALUE_GAP, timeframe, [fvg])

            # Detect Breaker Blocks
            new_bbs = self.bb_detector.detect_breaker_blocks(
                tf_data.indicators.order_blocks,
                tf_data.candles,
                start_index=max(0, len(tf_data.candles) - 100)
            )

            # Add new BBs
            existing_bb_timestamps = {
                bb.transition_timestamp for bb in tf_data.indicators.breaker_blocks
            }
            for bb in new_bbs:
                if bb.transition_timestamp not in existing_bb_timestamps:
                    tf_data.indicators.breaker_blocks.append(bb)
                    self._trigger_callbacks(IndicatorType.BREAKER_BLOCK, timeframe, [bb])

            # Apply expiration logic
            latest = tf_data.get_latest_candle()
            if latest:
                candle_count = len(tf_data.candles)

                # Expire Order Blocks
                tf_data.indicators.order_blocks = self.expiration_manager.expire_order_blocks(
                    tf_data.indicators.order_blocks,
                    latest,
                    candle_count
                )

                # Expire Fair Value Gaps
                tf_data.indicators.fair_value_gaps = self.expiration_manager.expire_fair_value_gaps(
                    tf_data.indicators.fair_value_gaps,
                    latest,
                    candle_count
                )

                # Expire Breaker Blocks
                tf_data.indicators.breaker_blocks = self.expiration_manager.expire_breaker_blocks(
                    tf_data.indicators.breaker_blocks,
                    latest,
                    candle_count
                )

                # Update timestamp
                tf_data.indicators.last_update_timestamp = latest.timestamp
                tf_data.indicators.candle_count = candle_count

            logger.info(
                f"Updated {timeframe.value} indicators: "
                f"OBs={len(tf_data.indicators.order_blocks)}, "
                f"FVGs={len(tf_data.indicators.fair_value_gaps)}, "
                f"BBs={len(tf_data.indicators.breaker_blocks)}"
            )

        except Exception as e:
            logger.error(
                f"Error updating indicators for {timeframe.value}: {e}",
                exc_info=True
            )

    def get_indicators(
        self,
        timeframe: TimeFrame
    ) -> Optional[TimeframeIndicators]:
        """
        Get all indicators for a specific timeframe.

        Args:
            timeframe: Timeframe to query

        Returns:
            TimeframeIndicators or None if timeframe not found
        """
        with self._lock:
            tf_data = self.timeframe_data.get(timeframe)
            return tf_data.indicators if tf_data else None

    def get_active_indicators(
        self,
        timeframe: TimeFrame
    ) -> Dict[str, List[Any]]:
        """
        Get only active indicators for a timeframe.

        Args:
            timeframe: Timeframe to query

        Returns:
            Dictionary with active indicators by type
        """
        indicators = self.get_indicators(timeframe)
        if not indicators:
            return {}

        return {
            'order_blocks': indicators.get_active_order_blocks(),
            'fair_value_gaps': indicators.get_active_fvgs(),
            'breaker_blocks': indicators.get_active_breaker_blocks()
        }

    def get_cross_timeframe_confirmations(
        self,
        indicator_type: IndicatorType,
        price: float,
        tolerance_percent: float = 0.5
    ) -> Dict[TimeFrame, List[Any]]:
        """
        Find indicators across multiple timeframes near a specific price.

        Useful for finding confluence zones where multiple timeframes
        have indicators at similar price levels.

        Args:
            indicator_type: Type of indicator to search for
            price: Price level to search around
            tolerance_percent: Price tolerance as percentage

        Returns:
            Dictionary mapping timeframes to matching indicators
        """
        confirmations = {}
        tolerance = price * (tolerance_percent / 100)

        with self._lock:
            for tf, tf_data in self.timeframe_data.items():
                matches = []

                if indicator_type == IndicatorType.ORDER_BLOCK:
                    indicators = tf_data.indicators.get_active_order_blocks()
                    matches = [
                        ob for ob in indicators
                        if abs(ob.get_midpoint() - price) <= tolerance
                    ]
                elif indicator_type == IndicatorType.FAIR_VALUE_GAP:
                    indicators = tf_data.indicators.get_active_fvgs()
                    matches = [
                        fvg for fvg in indicators
                        if abs(fvg.get_midpoint() - price) <= tolerance
                    ]
                elif indicator_type == IndicatorType.BREAKER_BLOCK:
                    indicators = tf_data.indicators.get_active_breaker_blocks()
                    matches = [
                        bb for bb in indicators
                        if abs(bb.get_midpoint() - price) <= tolerance
                    ]

                if matches:
                    confirmations[tf] = matches

        return confirmations

    def clear_timeframe(self, timeframe: TimeFrame) -> None:
        """
        Clear all data and indicators for a specific timeframe.

        Args:
            timeframe: Timeframe to clear
        """
        with self._lock:
            if timeframe in self.timeframe_data:
                self.timeframe_data[timeframe].candles.clear()
                self.timeframe_data[timeframe].indicators.clear()
                logger.info(f"Cleared data for {timeframe.value}")

    def clear_all(self) -> None:
        """Clear all data and indicators across all timeframes."""
        with self._lock:
            for tf_data in self.timeframe_data.values():
                tf_data.candles.clear()
                tf_data.indicators.clear()
            logger.info("Cleared all timeframe data")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about current state of the engine.

        Returns:
            Dictionary with statistics per timeframe
        """
        stats = {}

        with self._lock:
            for tf, tf_data in self.timeframe_data.items():
                indicators = tf_data.indicators
                stats[tf.value] = {
                    'candle_count': len(tf_data.candles),
                    'order_blocks': {
                        'total': len(indicators.order_blocks),
                        'active': len(indicators.get_active_order_blocks()),
                        'bullish': sum(
                            1 for ob in indicators.order_blocks
                            if ob.type == OrderBlockType.BULLISH
                        ),
                        'bearish': sum(
                            1 for ob in indicators.order_blocks
                            if ob.type == OrderBlockType.BEARISH
                        ),
                    },
                    'fair_value_gaps': {
                        'total': len(indicators.fair_value_gaps),
                        'active': len(indicators.get_active_fvgs()),
                        'bullish': sum(
                            1 for fvg in indicators.fair_value_gaps
                            if fvg.type == FVGType.BULLISH
                        ),
                        'bearish': sum(
                            1 for fvg in indicators.fair_value_gaps
                            if fvg.type == FVGType.BEARISH
                        ),
                    },
                    'breaker_blocks': {
                        'total': len(indicators.breaker_blocks),
                        'active': len(indicators.get_active_breaker_blocks()),
                    },
                    'last_update': (
                        datetime.fromtimestamp(
                            indicators.last_update_timestamp / 1000
                        ).isoformat()
                        if indicators.last_update_timestamp else None
                    )
                }

            # Add expiration statistics
            stats['expiration'] = self.expiration_manager.get_statistics()

        return stats
