"""
Multi-Timeframe Indicator Calculation Engine for ICT trading methodology.

This module implements parallel calculation of ICT indicators (Order Blocks, FVG, Breaker Blocks)
across multiple timeframes (1m, 15m, 1h) with synchronized data management and efficient
cross-timeframe analysis capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Callable, Any
import logging
import asyncio
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
    BreakerBlockDetector
)
from src.indicators.liquidity_zone import (
    LiquidityLevel,
    LiquidityZoneDetector
)
from src.indicators.liquidity_sweep import (
    LiquiditySweep,
    LiquiditySweepDetector
)
from src.indicators.trend_recognition import (
    TrendRecognitionEngine,
    TrendState,
    TrendStructure
)
from src.indicators.expiration_manager import (
    IndicatorExpirationManager,
    ExpirationRules
)
from src.core.events import EventBus, Event
from src.core.constants import EventType


logger = logging.getLogger(__name__)


class IndicatorType(str, Enum):
    """Types of ICT indicators supported."""
    ORDER_BLOCK = "order_block"
    FAIR_VALUE_GAP = "fair_value_gap"
    BREAKER_BLOCK = "breaker_block"

    LIQUIDITY_ZONE = "liquidity_zone"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    TREND_RECOGNITION = "trend_recognition"


@dataclass
class TimeframeIndicators:
    """
    Container for all indicators detected in a specific timeframe.

    Attributes:
        timeframe: The timeframe these indicators belong to
        order_blocks: List of detected Order Blocks
        fair_value_gaps: List of detected Fair Value Gaps
        breaker_blocks: List of detected Breaker Blocks
        liquidity_levels: List of detected Liquidity Levels
        liquidity_sweeps: List of detected Liquidity Sweeps
        trend_structures: List of detected Trend Structures (HH/HL/LH/LL)
        trend_state: Current trend state (direction, strength, etc.)
        last_update_timestamp: Last time indicators were calculated
        candle_count: Number of candles processed
    """
    timeframe: TimeFrame
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fair_value_gaps: List[FairValueGap] = field(default_factory=list)
    breaker_blocks: List[BreakerBlock] = field(default_factory=list)
    liquidity_levels: List[LiquidityLevel] = field(default_factory=list)
    liquidity_sweeps: List[LiquiditySweep] = field(default_factory=list)
    trend_structures: List[TrendStructure] = field(default_factory=list)
    trend_state: Optional[TrendState] = None
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
        self.liquidity_levels.clear()
        self.liquidity_sweeps.clear()
        self.trend_structures.clear()
        self.trend_state = None
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
        liquidity_zone_config: Optional[Dict[str, Any]] = None,
        liquidity_sweep_config: Optional[Dict[str, Any]] = None,
        trend_recognition_config: Optional[Dict[str, Any]] = None,
        expiration_rules: Optional[ExpirationRules] = None,
        auto_remove_expired: bool = True,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize multi-timeframe indicator engine.

        Args:
            timeframes: List of timeframes to track (default: [1m, 15m, 1h])
            max_candles_per_timeframe: Max candles to retain per timeframe
            ob_detector_config: Configuration for Order Block detector
            fvg_detector_config: Configuration for FVG detector
            bb_detector_config: Configuration for Breaker Block detector
            liquidity_zone_config: Configuration for Liquidity Zone detector
            liquidity_sweep_config: Configuration for Liquidity Sweep detector
            trend_recognition_config: Configuration for Trend Recognition engine
            expiration_rules: Custom expiration rules, or None for defaults
            auto_remove_expired: If True, automatically remove expired indicators
            event_bus: Optional event bus for publishing indicator events
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
        self.liquidity_zone_detector = LiquidityZoneDetector(**(liquidity_zone_config or {}))
        self.liquidity_sweep_detector = LiquiditySweepDetector(
            **(liquidity_sweep_config or {}),
            event_bus=event_bus
        )
        self.trend_recognition_engine = TrendRecognitionEngine(
            **(trend_recognition_config or {}),
            event_bus=event_bus
        )

        # Initialize expiration manager
        self.expiration_manager = IndicatorExpirationManager(
            expiration_rules=expiration_rules,
            auto_remove_expired=auto_remove_expired
        )

        # Event bus for publishing indicator events
        self.event_bus = event_bus

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
            newly_detected_obs = []
            for ob in new_obs:
                if ob.origin_timestamp not in existing_timestamps:
                    tf_data.indicators.order_blocks.append(ob)
                    newly_detected_obs.append(ob)
                    self._trigger_callbacks(IndicatorType.ORDER_BLOCK, timeframe, [ob])

            # Publish ORDER_BLOCK_DETECTED event for new OBs
            if newly_detected_obs:
                self._publish_event_sync(
                    EventType.ORDER_BLOCK_DETECTED,
                    timeframe,
                    {
                        'count': len(newly_detected_obs),
                        'order_blocks': [ob.to_dict() for ob in newly_detected_obs]
                    },
                    priority=7
                )

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
            newly_detected_fvgs = []
            for fvg in new_fvgs:
                if fvg.origin_timestamp not in existing_fvg_timestamps:
                    tf_data.indicators.fair_value_gaps.append(fvg)
                    newly_detected_fvgs.append(fvg)
                    self._trigger_callbacks(IndicatorType.FAIR_VALUE_GAP, timeframe, [fvg])

            # Publish FVG_DETECTED event for new FVGs
            if newly_detected_fvgs:
                self._publish_event_sync(
                    EventType.FVG_DETECTED,
                    timeframe,
                    {
                        'count': len(newly_detected_fvgs),
                        'fair_value_gaps': [fvg.to_dict() for fvg in newly_detected_fvgs]
                    },
                    priority=7
                )

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
            newly_detected_bbs = []
            for bb in new_bbs:
                if bb.transition_timestamp not in existing_bb_timestamps:
                    tf_data.indicators.breaker_blocks.append(bb)
                    newly_detected_bbs.append(bb)
                    self._trigger_callbacks(IndicatorType.BREAKER_BLOCK, timeframe, [bb])

            # Publish BREAKER_BLOCK_DETECTED event for new BBs
            if newly_detected_bbs:
                self._publish_event_sync(
                    EventType.BREAKER_BLOCK_DETECTED,
                    timeframe,
                    {
                        'count': len(newly_detected_bbs),
                        'breaker_blocks': [bb.to_dict() for bb in newly_detected_bbs]
                    },
                    priority=7
                )

            # Detect Liquidity Zones (levels)
            buy_side_levels, sell_side_levels = self.liquidity_zone_detector.detect_liquidity_levels(
                tf_data.candles
            )

            # Combine buy and sell side levels for storage
            all_liquidity_levels = buy_side_levels + sell_side_levels

            # Replace existing liquidity levels (full recalculation approach)
            tf_data.indicators.liquidity_levels = all_liquidity_levels

            # Detect Liquidity Sweeps
            if all_liquidity_levels:
                # Detect sweeps across all candles
                # Look back 50 candles max to detect sweeps
                start_index = max(0, len(tf_data.candles) - 50)

                detected_sweeps = self.liquidity_sweep_detector.detect_sweeps(
                    tf_data.candles,
                    all_liquidity_levels,
                    start_index=start_index
                )

                # Add new sweeps that weren't detected before
                if detected_sweeps:
                    existing_sweep_timestamps = {
                        s.sweep_timestamp for s in tf_data.indicators.liquidity_sweeps
                    }
                    new_sweeps = [
                        sweep for sweep in detected_sweeps
                        if sweep.sweep_timestamp not in existing_sweep_timestamps
                    ]

                    if new_sweeps:
                        tf_data.indicators.liquidity_sweeps.extend(new_sweeps)
                        self._trigger_callbacks(IndicatorType.LIQUIDITY_SWEEP, timeframe, new_sweeps)

            # Detect Trend Patterns (HH/HL/LH/LL)
            trend_structures, trend_direction = self.trend_recognition_engine.analyze_trend_patterns(
                tf_data.candles
            )

            # Update trend structures
            tf_data.indicators.trend_structures = trend_structures

            # Calculate trend strength and update trend state
            if trend_structures:
                strength_score, strength_level = self.trend_recognition_engine.calculate_trend_strength(
                    trend_structures,
                    trend_direction
                )

                latest_candle = tf_data.get_latest_candle()
                if latest_candle:
                    # Update trend state
                    previous_trend = tf_data.indicators.trend_state

                    # Check if we need to create new trend state or update existing
                    if previous_trend is None or previous_trend.direction != trend_direction:
                        # New trend state
                        tf_data.indicators.trend_state = TrendState(
                            direction=trend_direction,
                            strength=strength_score,
                            strength_level=strength_level,
                            symbol=tf_data.candles[0].symbol if tf_data.candles else "UNKNOWN",
                            timeframe=timeframe,
                            start_timestamp=latest_candle.timestamp,
                            start_candle_index=len(tf_data.candles) - 1,
                            last_update_timestamp=latest_candle.timestamp,
                            pattern_count=len(trend_structures),
                            is_confirmed=len(trend_structures) >= self.trend_recognition_engine.min_patterns_for_confirmation
                        )
                    else:
                        # Update existing trend state
                        tf_data.indicators.trend_state.strength = strength_score
                        tf_data.indicators.trend_state.strength_level = strength_level
                        tf_data.indicators.trend_state.last_update_timestamp = latest_candle.timestamp
                        tf_data.indicators.trend_state.pattern_count = len(trend_structures)
                        tf_data.indicators.trend_state.is_confirmed = (
                            len(trend_structures) >= self.trend_recognition_engine.min_patterns_for_confirmation
                        )

                    # Detect trend change (will publish event if changed)
                    if previous_trend:
                        self.trend_recognition_engine.detect_trend_change(
                            previous_trend,
                            tf_data.indicators.trend_state,
                            trend_structures
                        )

            # Apply expiration logic
            latest = tf_data.get_latest_candle()
            if latest:
                candle_count = len(tf_data.candles)

                # Track original counts for expiration events
                original_ob_count = len(tf_data.indicators.order_blocks)
                original_fvg_count = len(tf_data.indicators.fair_value_gaps)
                original_bb_count = len(tf_data.indicators.breaker_blocks)

                # Expire Order Blocks
                tf_data.indicators.order_blocks = self.expiration_manager.expire_order_blocks(
                    tf_data.indicators.order_blocks,
                    latest,
                    candle_count
                )
                expired_ob_count = original_ob_count - len(tf_data.indicators.order_blocks)
                if expired_ob_count > 0:
                    self._publish_event_sync(
                        EventType.INDICATOR_EXPIRED,
                        timeframe,
                        {
                            'indicator_type': 'order_block',
                            'expired_count': expired_ob_count,
                            'remaining_count': len(tf_data.indicators.order_blocks)
                        },
                        priority=6
                    )

                # Expire Fair Value Gaps
                tf_data.indicators.fair_value_gaps = self.expiration_manager.expire_fair_value_gaps(
                    tf_data.indicators.fair_value_gaps,
                    latest,
                    candle_count
                )
                expired_fvg_count = original_fvg_count - len(tf_data.indicators.fair_value_gaps)
                if expired_fvg_count > 0:
                    self._publish_event_sync(
                        EventType.INDICATOR_EXPIRED,
                        timeframe,
                        {
                            'indicator_type': 'fair_value_gap',
                            'expired_count': expired_fvg_count,
                            'remaining_count': len(tf_data.indicators.fair_value_gaps)
                        },
                        priority=6
                    )

                # Expire Breaker Blocks
                tf_data.indicators.breaker_blocks = self.expiration_manager.expire_breaker_blocks(
                    tf_data.indicators.breaker_blocks,
                    latest,
                    candle_count
                )
                expired_bb_count = original_bb_count - len(tf_data.indicators.breaker_blocks)
                if expired_bb_count > 0:
                    self._publish_event_sync(
                        EventType.INDICATOR_EXPIRED,
                        timeframe,
                        {
                            'indicator_type': 'breaker_block',
                            'expired_count': expired_bb_count,
                            'remaining_count': len(tf_data.indicators.breaker_blocks)
                        },
                        priority=6
                    )

                # Update timestamp
                tf_data.indicators.last_update_timestamp = latest.timestamp
                tf_data.indicators.candle_count = candle_count

                # Publish INDICATORS_UPDATED event with summary
                self._publish_event_sync(
                    EventType.INDICATORS_UPDATED,
                    timeframe,
                    {
                        'order_blocks_count': len(tf_data.indicators.order_blocks),
                        'fair_value_gaps_count': len(tf_data.indicators.fair_value_gaps),
                        'breaker_blocks_count': len(tf_data.indicators.breaker_blocks),
                        'liquidity_levels_count': len(tf_data.indicators.liquidity_levels),
                        'liquidity_sweeps_count': len(tf_data.indicators.liquidity_sweeps),
                        'trend_structures_count': len(tf_data.indicators.trend_structures),
                        'trend_direction': tf_data.indicators.trend_state.direction.value if tf_data.indicators.trend_state else None,
                        'trend_strength': tf_data.indicators.trend_state.strength if tf_data.indicators.trend_state else None,
                        'total_indicators': (
                            len(tf_data.indicators.order_blocks) +
                            len(tf_data.indicators.fair_value_gaps) +
                            len(tf_data.indicators.breaker_blocks) +
                            len(tf_data.indicators.liquidity_levels) +
                            len(tf_data.indicators.liquidity_sweeps) +
                            len(tf_data.indicators.trend_structures)
                        ),
                        'timestamp': latest.timestamp
                    },
                    priority=5
                )

            logger.info(
                f"Updated {timeframe.value} indicators: "
                f"OBs={len(tf_data.indicators.order_blocks)}, "
                f"FVGs={len(tf_data.indicators.fair_value_gaps)}, "
                f"BBs={len(tf_data.indicators.breaker_blocks)}, "
                f"Liquidity={len(tf_data.indicators.liquidity_levels)}, "
                f"Sweeps={len(tf_data.indicators.liquidity_sweeps)}, "
                f"Trends={len(tf_data.indicators.trend_structures)}, "
                f"Direction={tf_data.indicators.trend_state.direction.value if tf_data.indicators.trend_state else 'N/A'}"
            )

        except Exception as e:
            logger.error(
                f"Error updating indicators for {timeframe.value}: {e}",
                exc_info=True
            )

    def _publish_event_sync(
        self,
        event_type: EventType,
        timeframe: TimeFrame,
        data: Dict[str, Any],
        priority: int = 5
    ) -> None:
        """
        Publish an event to the event bus if available (synchronous wrapper).

        This method creates a task in the event loop if one is running.
        If no event loop is running, the event is logged but not published.

        Args:
            event_type: Type of event to publish
            timeframe: Timeframe the event relates to
            data: Event payload data
            priority: Event priority (0-10, higher = more important)
        """
        if self.event_bus:
            try:
                event = Event(
                    priority=priority,
                    event_type=event_type,
                    data={
                        'timeframe': timeframe.value,
                        **data
                    },
                    source='MultiTimeframeIndicatorEngine'
                )

                # Try to get the running event loop
                try:
                    asyncio.get_running_loop()
                    # Schedule event publishing in the loop
                    asyncio.create_task(self.event_bus.publish(event))
                    logger.debug(
                        f"Scheduled {event_type.value} event for {timeframe.value}"
                    )
                except RuntimeError:
                    # No event loop running, log instead
                    logger.warning(
                        f"No event loop running, cannot publish {event_type.value} event"
                    )
            except Exception as e:
                logger.error(
                    f"Error publishing {event_type.value} event: {e}",
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


class MarketStructure(str, Enum):
    """Overall market structure classification."""
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    RANGING = "RANGING"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


class ConsistencyLevel(str, Enum):
    """Level of consistency across multiple timeframes."""
    PERFECT = "PERFECT"        # All 3 timeframes perfectly aligned
    HIGH = "HIGH"              # 2 of 3 timeframes aligned
    MODERATE = "MODERATE"      # Partial alignment with minor conflicts
    LOW = "LOW"                # Significant conflicts
    CONFLICT = "CONFLICT"      # Direct contradictions


class StructureBias(str, Enum):
    """Overall market bias considering all timeframes."""
    STRONGLY_BULLISH = "STRONGLY_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONGLY_BEARISH = "STRONGLY_BEARISH"


@dataclass
class TimeframeMarketStructure:
    """
    Complete market structure analysis for a single timeframe.
    
    Integrates all ICT pattern analysis (liquidity, sweeps, BMS, trend)
    to provide comprehensive market state view.
    
    Attributes:
        timeframe: The timeframe this analysis belongs to
        timestamp: Analysis timestamp (milliseconds)
        
        # Trend Analysis
        trend_state: Current trend state (direction, strength)
        trend_structures: HH/HL/LH/LL patterns
        
        # Liquidity Analysis
        buy_side_levels: Buy-side liquidity levels (above price)
        sell_side_levels: Sell-side liquidity levels (below price)
        recent_sweeps: Recent liquidity sweep patterns
        
        # Structure Analysis
        recent_bms: Recent Break of Market Structure events
        swing_highs: Detected swing high points
        swing_lows: Detected swing low points
        
        # Overall Assessment
        market_structure: Overall structure classification
        structure_strength: Strength of current structure (0-10)
        dominant_liquidity_side: Which side has more liquidity ("BUY" or "SELL")
    """
    timeframe: TimeFrame
    timestamp: int
    
    # Trend
    trend_state: Optional[TrendState] = None
    trend_structures: List[TrendStructure] = field(default_factory=list)
    
    # Liquidity
    buy_side_levels: List[LiquidityLevel] = field(default_factory=list)
    sell_side_levels: List[LiquidityLevel] = field(default_factory=list)
    recent_sweeps: List[LiquiditySweep] = field(default_factory=list)
    
    # Structure
    recent_bms: List['BreakOfMarketStructure'] = field(default_factory=list)
    swing_highs: List['SwingPoint'] = field(default_factory=list)
    swing_lows: List['SwingPoint'] = field(default_factory=list)
    
    # Assessment
    market_structure: MarketStructure = MarketStructure.RANGING
    structure_strength: float = 0.0
    dominant_liquidity_side: str = "NEUTRAL"
    
    def get_liquidity_balance(self) -> float:
        """
        Calculate liquidity balance between buy and sell sides.
        
        Returns:
            Balance score: > 0 means buy-side dominant, < 0 means sell-side dominant
        """
        buy_count = len(self.buy_side_levels)
        sell_count = len(self.sell_side_levels)
        
        if buy_count + sell_count == 0:
            return 0.0
        
        return (buy_count - sell_count) / (buy_count + sell_count)
    
    def has_recent_sweep(self, side: str, within_candles: int = 10) -> bool:
        """
        Check if there was a recent liquidity sweep.
        
        Args:
            side: "BUY" or "SELL"
            within_candles: Look back this many candles
            
        Returns:
            True if recent sweep detected
        """
        if not self.recent_sweeps:
            return False
        
        # Check sweeps on specified side
        for sweep in self.recent_sweeps[-within_candles:]:
            if side == "BUY" and sweep.liquidity_level.side == "SELL":
                # Buy-side sweep takes sell-side liquidity
                return True
            elif side == "SELL" and sweep.liquidity_level.side == "BUY":
                # Sell-side sweep takes buy-side liquidity
                return True
        
        return False


@dataclass
class MultiTimeframeMarketStructure:
    """
    Integrated market structure analysis across multiple timeframes.
    
    Provides unified view of market state by analyzing and reconciling
    structure across H1, M15, and M1 timeframes with intelligent
    conflict resolution.
    
    Attributes:
        symbol: Trading pair symbol
        timestamp: Analysis timestamp (milliseconds)
        
        # Timeframe Analysis
        h1_structure: 1-hour timeframe analysis
        m15_structure: 15-minute timeframe analysis
        m1_structure: 1-minute timeframe analysis
        
        # Integration Results
        consistency_level: How well timeframes align
        overall_bias: Integrated directional bias
        bias_strength: Strength of overall bias (0-10)
        primary_timeframe: Which timeframe dominates (usually H1)
        
        # Conflict Management
        conflicts: List of detected conflicts between timeframes
        recommendations: Trading recommendations based on analysis
    """
    symbol: str
    timestamp: int
    
    # Timeframe Structures
    h1_structure: Optional[TimeframeMarketStructure] = None
    m15_structure: Optional[TimeframeMarketStructure] = None
    m1_structure: Optional[TimeframeMarketStructure] = None
    
    # Integration
    consistency_level: ConsistencyLevel = ConsistencyLevel.MODERATE
    overall_bias: StructureBias = StructureBias.NEUTRAL
    bias_strength: float = 0.0
    primary_timeframe: TimeFrame = TimeFrame.H1
    
    # Guidance
    conflicts: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def get_timeframe_alignment_score(self) -> float:
        """
        Calculate alignment score across timeframes.
        
        Returns:
            Score 0-10 where 10 = perfect alignment
        """
        if not all([self.h1_structure, self.m15_structure, self.m1_structure]):
            return 0.0
        
        # Compare trend directions
        directions = []
        if self.h1_structure and self.h1_structure.trend_state:
            directions.append(self.h1_structure.trend_state.direction.value)
        if self.m15_structure and self.m15_structure.trend_state:
            directions.append(self.m15_structure.trend_state.direction.value)
        if self.m1_structure and self.m1_structure.trend_state:
            directions.append(self.m1_structure.trend_state.direction.value)
        
        if len(directions) < 2:
            return 5.0  # Neutral if insufficient data
        
        # Count matching directions
        from collections import Counter
        direction_counts = Counter(directions)
        most_common_count = direction_counts.most_common(1)[0][1]
        
        # Perfect alignment = 10, 2/3 = 7, none = 0
        if most_common_count == 3:
            return 10.0
        elif most_common_count == 2:
            return 7.0
        else:
            return 3.0
    
    def is_strong_trend(self) -> bool:
        """Check if we're in a strong trending market."""
        return (
            self.consistency_level in [ConsistencyLevel.PERFECT, ConsistencyLevel.HIGH] and
            self.overall_bias in [StructureBias.STRONGLY_BULLISH, StructureBias.STRONGLY_BEARISH] and
            self.bias_strength >= 7.0
        )
    
    def is_ranging_market(self) -> bool:
        """Check if we're in a ranging market."""
        return (
            self.overall_bias == StructureBias.NEUTRAL or
            self.consistency_level == ConsistencyLevel.CONFLICT or
            self.bias_strength < 4.0
        )
    
    def get_entry_timeframe_recommendation(self) -> Optional[TimeFrame]:
        """
        Recommend which timeframe to use for entry timing.
        
        Returns:
            Recommended timeframe for precise entries
        """
        if self.is_strong_trend():
            # In strong trend, use M15 for entries
            return TimeFrame.M15
        elif self.is_ranging_market():
            # In ranging, wait for clearer structure
            return None
        else:
            # Moderate conditions, use M1 for precision
            return TimeFrame.M1


class MultiTimeframeMarketStructureAnalyzer:
    """
    Orchestrates market structure analysis across multiple timeframes.
    
    Integrates liquidity zones, sweeps, BMS, and trend recognition
    to provide comprehensive multi-timeframe market view with
    intelligent conflict resolution.
    
    Key Features:
    - Independent analysis per timeframe
    - Consistency verification across timeframes
    - Higher timeframe priority (H1 > M15 > M1)
    - Conflict detection and resolution
    - Trading recommendations based on alignment
    """
    
    def __init__(
        self,
        liquidity_zone_detector: Optional[LiquidityZoneDetector] = None,
        liquidity_sweep_detector: Optional[LiquiditySweepDetector] = None,
        trend_recognition_engine: Optional[TrendRecognitionEngine] = None,
        bms_detector: Optional['MarketStructureBreakDetector'] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize multi-timeframe market structure analyzer.
        
        Args:
            liquidity_zone_detector: Detector for liquidity levels
            liquidity_sweep_detector: Detector for liquidity sweeps
            trend_recognition_engine: Engine for trend pattern recognition
            bms_detector: Detector for Break of Market Structure
            event_bus: Optional event bus for publishing analysis events
        """
        # Initialize detectors (create new instances if not provided)
        self.liquidity_zone_detector = liquidity_zone_detector or LiquidityZoneDetector()
        self.liquidity_sweep_detector = liquidity_sweep_detector or LiquiditySweepDetector(
            event_bus=event_bus
        )
        self.trend_recognition_engine = trend_recognition_engine or TrendRecognitionEngine(
            event_bus=event_bus
        )
        
        # BMS detector needs to be imported at runtime to avoid circular dependency
        if bms_detector is None:
            from src.indicators.market_structure_break import MarketStructureBreakDetector
            self.bms_detector = MarketStructureBreakDetector(event_bus=event_bus)
        else:
            self.bms_detector = bms_detector
        
        self.event_bus = event_bus
        
        logger.info("Initialized MultiTimeframeMarketStructureAnalyzer")
    
    def analyze_timeframe(
        self,
        candles: List[Candle],
        timeframe: TimeFrame
    ) -> TimeframeMarketStructure:
        """
        Perform complete market structure analysis for a single timeframe.
        
        Steps:
        1. Detect liquidity levels (buy-side and sell-side)
        2. Analyze trend patterns (HH/HL/LH/LL)
        3. Detect BMS (Break of Market Structure) events
        4. Detect liquidity sweeps
        5. Determine overall market structure and strength
        
        Args:
            candles: Candle data for this timeframe
            timeframe: The timeframe being analyzed
            
        Returns:
            Complete market structure analysis
        """
        if not candles or len(candles) < 10:
            logger.warning(f"Insufficient candles for {timeframe.value} analysis")
            return TimeframeMarketStructure(
                timeframe=timeframe,
                timestamp=candles[-1].timestamp if candles else 0
            )
        
        latest_candle = candles[-1]
        timestamp = latest_candle.timestamp
        
        # 1. Detect Liquidity Levels
        buy_side_levels, sell_side_levels = self.liquidity_zone_detector.detect_liquidity_levels(
            candles
        )
        
        # Get swing points for structure analysis
        swing_highs = self.liquidity_zone_detector.detect_swing_highs(candles)
        swing_lows = self.liquidity_zone_detector.detect_swing_lows(candles)
        
        logger.debug(
            f"{timeframe.value}: Detected {len(buy_side_levels)} buy-side and "
            f"{len(sell_side_levels)} sell-side liquidity levels"
        )
        
        # 2. Analyze Trend Patterns
        trend_structures, trend_direction = self.trend_recognition_engine.analyze_trend_patterns(
            candles
        )
        
        # Calculate trend strength
        strength_score = 0.0
        trend_state = None
        
        if trend_structures:
            strength_score, strength_level = self.trend_recognition_engine.calculate_trend_strength(
                trend_structures,
                trend_direction
            )
            
            from src.indicators.trend_recognition import TrendState
            trend_state = TrendState(
                direction=trend_direction,
                strength=strength_score,
                strength_level=strength_level,
                symbol=candles[0].symbol,
                timeframe=timeframe,
                start_timestamp=timestamp,
                start_candle_index=len(candles) - 1,
                last_update_timestamp=timestamp,
                pattern_count=len(trend_structures),
                is_confirmed=len(trend_structures) >= 2
            )
        
        logger.debug(
            f"{timeframe.value}: Trend={trend_direction.value if trend_state else 'N/A'}, "
            f"Strength={strength_score:.1f}, Patterns={len(trend_structures)}"
        )
        
        # 3. Detect Break of Market Structure (BMS)
        recent_bms = self.bms_detector.detect_bms(
            candles,
            swing_highs,
            swing_lows,
            start_index=max(0, len(candles) - 50)
        )
        
        logger.debug(f"{timeframe.value}: Detected {len(recent_bms)} BMS events")
        
        # 4. Detect Liquidity Sweeps
        all_liquidity_levels = buy_side_levels + sell_side_levels
        recent_sweeps = []
        
        if all_liquidity_levels:
            recent_sweeps = self.liquidity_sweep_detector.detect_sweeps(
                candles,
                all_liquidity_levels,
                start_index=max(0, len(candles) - 50)
            )
        
        logger.debug(f"{timeframe.value}: Detected {len(recent_sweeps)} liquidity sweeps")
        
        # 5. Determine Overall Market Structure
        market_structure, structure_strength = self._determine_market_structure(
            trend_state,
            trend_direction,
            strength_score,
            recent_bms,
            recent_sweeps
        )
        
        # Determine dominant liquidity side
        dominant_side = self._determine_dominant_liquidity(
            buy_side_levels,
            sell_side_levels,
            recent_sweeps
        )
        
        logger.info(
            f"{timeframe.value} Analysis: Structure={market_structure.value}, "
            f"Strength={structure_strength:.1f}, Liquidity={dominant_side}"
        )
        
        return TimeframeMarketStructure(
            timeframe=timeframe,
            timestamp=timestamp,
            trend_state=trend_state,
            trend_structures=trend_structures,
            buy_side_levels=buy_side_levels,
            sell_side_levels=sell_side_levels,
            recent_sweeps=recent_sweeps,
            recent_bms=recent_bms,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            market_structure=market_structure,
            structure_strength=structure_strength,
            dominant_liquidity_side=dominant_side
        )
    
    def _determine_market_structure(
        self,
        trend_state: Optional[TrendState],
        trend_direction: 'TrendDirection',
        strength_score: float,
        recent_bms: List['BreakOfMarketStructure'],
        recent_sweeps: List[LiquiditySweep]
    ) -> tuple[MarketStructure, float]:
        """
        Determine overall market structure classification.
        
        Args:
            trend_state: Current trend state
            trend_direction: Trend direction
            strength_score: Trend strength score
            recent_bms: Recent BMS events
            recent_sweeps: Recent liquidity sweeps
            
        Returns:
            (market_structure, structure_strength)
        """
        from src.indicators.trend_recognition import TrendDirection
        
        # Base structure on trend
        if not trend_state or trend_direction == TrendDirection.RANGING:
            return MarketStructure.RANGING, strength_score

        # Strong trending
        if strength_score >= 7.0:
            if trend_direction == TrendDirection.UPTREND:
                return MarketStructure.STRONG_BULLISH, strength_score
            else:
                return MarketStructure.STRONG_BEARISH, strength_score
        
        # Moderate trending
        elif strength_score >= 5.0:
            if trend_direction == TrendDirection.UPTREND:
                return MarketStructure.BULLISH, strength_score
            else:
                return MarketStructure.BEARISH, strength_score
        
        # Weak trend = ranging
        else:
            return MarketStructure.RANGING, strength_score
    
    def _determine_dominant_liquidity(
        self,
        buy_side_levels: List[LiquidityLevel],
        sell_side_levels: List[LiquidityLevel],
        recent_sweeps: List[LiquiditySweep]
    ) -> str:
        """
        Determine which side has dominant liquidity.
        
        Args:
            buy_side_levels: Buy-side liquidity levels
            sell_side_levels: Sell-side liquidity levels
            recent_sweeps: Recent sweep activity
            
        Returns:
            "BUY", "SELL", or "NEUTRAL"
        """
        buy_count = len(buy_side_levels)
        sell_count = len(sell_side_levels)
        
        # Factor in recent sweep activity
        recent_buy_sweeps = sum(
            1 for sweep in recent_sweeps[-5:]
            if sweep.liquidity_level.side == "BUY"
        )
        recent_sell_sweeps = sum(
            1 for sweep in recent_sweeps[-5:]
            if sweep.liquidity_level.side == "SELL"
        )
        
        # Adjust counts based on sweep activity
        # Swept liquidity reduces that side's dominance
        effective_buy = max(0, buy_count - recent_buy_sweeps)
        effective_sell = max(0, sell_count - recent_sell_sweeps)
        
        if effective_buy > effective_sell * 1.2:
            return "BUY"
        elif effective_sell > effective_buy * 1.2:
            return "SELL"
        else:
            return "NEUTRAL"
    
    def analyze_multi_timeframe(
        self,
        h1_candles: List[Candle],
        m15_candles: List[Candle],
        m1_candles: List[Candle]
    ) -> MultiTimeframeMarketStructure:
        """
        Integrate market structure analysis across all timeframes.
        
        Performs the following:
        1. Analyze each timeframe independently
        2. Verify consistency across timeframes
        3. Resolve conflicts using higher timeframe priority
        4. Generate trading recommendations
        
        Args:
            h1_candles: 1-hour candles
            m15_candles: 15-minute candles
            m1_candles: 1-minute candles
            
        Returns:
            Integrated multi-timeframe market structure
        """
        if not h1_candles or not m15_candles or not m1_candles:
            logger.warning("Insufficient candle data for multi-timeframe analysis")
            return MultiTimeframeMarketStructure(
                symbol=h1_candles[0].symbol if h1_candles else "UNKNOWN",
                timestamp=h1_candles[-1].timestamp if h1_candles else 0
            )
        
        symbol = h1_candles[0].symbol
        timestamp = h1_candles[-1].timestamp
        
        logger.info(f"Starting multi-timeframe analysis for {symbol}")
        
        # 1. Analyze each timeframe independently
        h1_structure = self.analyze_timeframe(h1_candles, TimeFrame.H1)
        m15_structure = self.analyze_timeframe(m15_candles, TimeFrame.M15)
        m1_structure = self.analyze_timeframe(m1_candles, TimeFrame.M1)
        
        # 2. Verify consistency
        consistency_level = self._verify_consistency(
            h1_structure,
            m15_structure,
            m1_structure
        )
        
        # 3. Resolve conflicts and determine overall bias
        overall_bias, bias_strength, primary_tf, conflicts = self._resolve_conflicts(
            h1_structure,
            m15_structure,
            m1_structure
        )
        
        # 4. Generate recommendations
        recommendations = self._generate_recommendations(
            h1_structure,
            m15_structure,
            m1_structure,
            overall_bias,
            consistency_level
        )
        
        result = MultiTimeframeMarketStructure(
            symbol=symbol,
            timestamp=timestamp,
            h1_structure=h1_structure,
            m15_structure=m15_structure,
            m1_structure=m1_structure,
            consistency_level=consistency_level,
            overall_bias=overall_bias,
            bias_strength=bias_strength,
            primary_timeframe=primary_tf,
            conflicts=conflicts,
            recommendations=recommendations
        )
        
        # Publish multi-timeframe analysis event
        if self.event_bus:
            try:
                asyncio.get_running_loop()
                event = Event(
                    priority=8,
                    event_type=EventType.MULTI_TIMEFRAME_ANALYSIS,
                    data={
                        'symbol': symbol,
                        'consistency_level': consistency_level.value,
                        'overall_bias': overall_bias.value,
                        'bias_strength': bias_strength,
                        'primary_timeframe': primary_tf.value,
                        'conflict_count': len(conflicts),
                        'recommendation_count': len(recommendations),
                        'timestamp': timestamp
                    },
                    source='MultiTimeframeMarketStructureAnalyzer'
                )
                asyncio.create_task(self.event_bus.publish(event))
            except RuntimeError:
                pass  # No event loop running
        
        logger.info(
            f"Multi-timeframe analysis complete: "
            f"Consistency={consistency_level.value}, "
            f"Bias={overall_bias.value}, "
            f"Strength={bias_strength:.1f}"
        )
        
        return result
    
    def _verify_consistency(
        self,
        h1: TimeframeMarketStructure,
        m15: TimeframeMarketStructure,
        m1: TimeframeMarketStructure
    ) -> ConsistencyLevel:
        """
        Verify consistency across timeframes.
        
        Checks alignment of:
        - Trend directions
        - Market structure classifications
        - Liquidity dominance
        
        Args:
            h1: 1-hour structure
            m15: 15-minute structure
            m1: 1-minute structure
            
        Returns:
            Consistency level classification
        """
        from src.indicators.trend_recognition import TrendDirection
        
        # Extract trend directions
        h1_dir = h1.trend_state.direction if h1.trend_state else TrendDirection.RANGING
        m15_dir = m15.trend_state.direction if m15.trend_state else TrendDirection.RANGING
        m1_dir = m1.trend_state.direction if m1.trend_state else TrendDirection.RANGING
        
        # Count agreements
        directions = [h1_dir, m15_dir, m1_dir]
        from collections import Counter
        direction_counts = Counter(directions)
        most_common_count = direction_counts.most_common(1)[0][1]
        
        # Extract market structures
        structures = [h1.market_structure, m15.market_structure, m1.market_structure]
        structure_counts = Counter(structures)
        structure_agreement = structure_counts.most_common(1)[0][1]
        
        # Extract liquidity dominance
        liquidity_sides = [h1.dominant_liquidity_side, m15.dominant_liquidity_side, m1.dominant_liquidity_side]
        liquidity_counts = Counter(liquidity_sides)
        liquidity_agreement = liquidity_counts.most_common(1)[0][1]
        
        # Calculate overall consistency
        total_agreement = most_common_count + structure_agreement + liquidity_agreement
        
        # Perfect: all 3 agree on all aspects
        if total_agreement == 9:
            return ConsistencyLevel.PERFECT
        
        # High: 2/3 agree on most aspects
        elif total_agreement >= 7:
            return ConsistencyLevel.HIGH
        
        # Moderate: some agreement
        elif total_agreement >= 5:
            return ConsistencyLevel.MODERATE
        
        # Low: minimal agreement
        elif total_agreement >= 3:
            return ConsistencyLevel.LOW
        
        # Conflict: no clear agreement
        else:
            return ConsistencyLevel.CONFLICT
    
    def _resolve_conflicts(
        self,
        h1: TimeframeMarketStructure,
        m15: TimeframeMarketStructure,
        m1: TimeframeMarketStructure
    ) -> tuple[StructureBias, float, TimeFrame, List[str]]:
        """
        Resolve conflicts between timeframes using higher timeframe priority.
        
        Priority: H1 > M15 > M1
        
        Args:
            h1: 1-hour structure
            m15: 15-minute structure
            m1: 1-minute structure
            
        Returns:
            (overall_bias, bias_strength, primary_timeframe, conflicts)
        """
        from src.indicators.trend_recognition import TrendDirection
        
        conflicts = []
        
        # Primary decision comes from H1
        primary_tf = TimeFrame.H1
        
        # Get H1 trend direction and strength
        h1_dir = h1.trend_state.direction if h1.trend_state else TrendDirection.RANGING
        h1_strength = h1.structure_strength
        
        # Get M15 and M1 directions for comparison
        m15_dir = m15.trend_state.direction if m15.trend_state else TrendDirection.RANGING
        m1_dir = m1.trend_state.direction if m1.trend_state else TrendDirection.RANGING
        
        # Check for conflicts
        if h1_dir != m15_dir and m15_dir != TrendDirection.RANGING:
            conflicts.append(f"H1 ({h1_dir.value}) conflicts with M15 ({m15_dir.value})")
        
        if h1_dir != m1_dir and m1_dir != TrendDirection.RANGING:
            conflicts.append(f"H1 ({h1_dir.value}) conflicts with M1 ({m1_dir.value})")
        
        if m15_dir != m1_dir and m15_dir != TrendDirection.RANGING and m1_dir != TrendDirection.RANGING:
            conflicts.append(f"M15 ({m15_dir.value}) conflicts with M1 ({m1_dir.value})")
        
        # Determine overall bias based on H1 (primary timeframe)
        if h1_dir == TrendDirection.RANGING:
            overall_bias = StructureBias.NEUTRAL
            bias_strength = h1_strength

        elif h1_dir == TrendDirection.UPTREND:
            # Check if lower timeframes confirm
            if m15_dir == TrendDirection.UPTREND and m1_dir == TrendDirection.UPTREND:
                overall_bias = StructureBias.STRONGLY_BULLISH
                bias_strength = min(10.0, h1_strength + 2.0)
            elif m15_dir == TrendDirection.UPTREND or m1_dir == TrendDirection.UPTREND:
                overall_bias = StructureBias.BULLISH
                bias_strength = h1_strength
            else:
                overall_bias = StructureBias.BULLISH
                bias_strength = max(0.0, h1_strength - 1.0)

        else:  # DOWNTREND
            # Check if lower timeframes confirm
            if m15_dir == TrendDirection.DOWNTREND and m1_dir == TrendDirection.DOWNTREND:
                overall_bias = StructureBias.STRONGLY_BEARISH
                bias_strength = min(10.0, h1_strength + 2.0)
            elif m15_dir == TrendDirection.DOWNTREND or m1_dir == TrendDirection.DOWNTREND:
                overall_bias = StructureBias.BEARISH
                bias_strength = h1_strength
            else:
                overall_bias = StructureBias.BEARISH
                bias_strength = max(0.0, h1_strength - 1.0)
        
        return overall_bias, bias_strength, primary_tf, conflicts
    
    def _generate_recommendations(
        self,
        h1: TimeframeMarketStructure,
        m15: TimeframeMarketStructure,
        m1: TimeframeMarketStructure,
        overall_bias: StructureBias,
        consistency: ConsistencyLevel
    ) -> List[str]:
        """
        Generate trading recommendations based on multi-timeframe analysis.
        
        Args:
            h1: 1-hour structure
            m15: 15-minute structure
            m1: 1-minute structure
            overall_bias: Overall directional bias
            consistency: Consistency level across timeframes
            
        Returns:
            List of actionable trading recommendations
        """
        recommendations = []
        
        # Consistency-based recommendations
        if consistency == ConsistencyLevel.PERFECT:
            recommendations.append(
                f"✅ Perfect alignment across all timeframes - High confidence {overall_bias.value} bias"
            )
        elif consistency == ConsistencyLevel.HIGH:
            recommendations.append(
                f"✅ Strong alignment - Good trading conditions for {overall_bias.value} bias"
            )
        elif consistency == ConsistencyLevel.MODERATE:
            recommendations.append(
                "⚠️ Moderate alignment - Use caution, wait for clearer structure"
            )
        elif consistency == ConsistencyLevel.LOW:
            recommendations.append(
                "⚠️ Low alignment - Consider staying out until structure clarifies"
            )
        else:  # CONFLICT
            recommendations.append(
                "❌ Timeframe conflict detected - Avoid trading until alignment improves"
            )
        
        # Bias-specific recommendations
        if overall_bias in [StructureBias.STRONGLY_BULLISH, StructureBias.STRONGLY_BEARISH]:
            direction = "long" if "BULLISH" in overall_bias.value else "short"
            recommendations.append(
                f"📈 Strong {direction} bias - Look for {direction} entry opportunities on pullbacks"
            )
            
            # Entry timing
            if m1.has_recent_sweep(side="SELL" if "BULLISH" in overall_bias.value else "BUY"):
                recommendations.append(
                    f"🎯 Recent liquidity sweep detected on M1 - Good {direction} entry setup"
                )
        
        elif overall_bias != StructureBias.NEUTRAL:
            direction = "long" if "BULLISH" in overall_bias.value else "short"
            recommendations.append(
                f"📊 Moderate {direction} bias - Wait for M15 confirmation before entering {direction}"
            )
        
        # Liquidity-based recommendations
        if h1.dominant_liquidity_side != "NEUTRAL":
            side = h1.dominant_liquidity_side.lower()
            recommendations.append(
                f"💧 H1 liquidity dominated by {side}-side - Expect price to target these levels"
            )
        
        # BMS-based recommendations
        if h1.recent_bms and len(h1.recent_bms) > 0:
            latest_bms = h1.recent_bms[-1]
            recommendations.append(
                f"🔨 Recent H1 BMS detected - Structure change confirmed, follow new direction"
            )
        
        # Structure strength warnings
        if h1.structure_strength < 4.0:
            recommendations.append(
                "⚠️ Weak H1 structure - Market may be consolidating, reduce position sizes"
            )
        
        return recommendations
