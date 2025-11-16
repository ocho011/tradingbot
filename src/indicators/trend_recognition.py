"""
Higher High/Lower Low (HH/LL) Trend Recognition Engine for ICT methodology.

This module implements automatic detection of market trend patterns through
analysis of swing high and low points:
- HH/HL (Higher High/Higher Low): Uptrend pattern
- LH/LL (Lower High/Lower Low): Downtrend pattern
- Trend strength calculation based on consistency and momentum
- Trend change detection with noise filtering
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.core.constants import EventType, TimeFrame
from src.core.events import Event, EventBus
from src.indicators.liquidity_zone import SwingPoint
from src.models.candle import Candle

logger = logging.getLogger(__name__)


class TrendPattern(str, Enum):
    """Types of trend patterns detected."""

    HIGHER_HIGH = "HIGHER_HIGH"  # HH - New high above previous high
    HIGHER_LOW = "HIGHER_LOW"  # HL - New low above previous low
    LOWER_HIGH = "LOWER_HIGH"  # LH - New high below previous high
    LOWER_LOW = "LOWER_LOW"  # LL - New low below previous low


class TrendDirection(str, Enum):
    """Overall trend direction."""

    UPTREND = "UPTREND"  # HH/HL pattern dominance
    DOWNTREND = "DOWNTREND"  # LH/LL pattern dominance
    RANGING = "RANGING"  # No clear trend
    TRANSITION = "TRANSITION"  # Trend change in progress


class TrendStrength(str, Enum):
    """Strength classification of detected trend."""

    VERY_WEAK = "VERY_WEAK"  # 0-20
    WEAK = "WEAK"  # 21-40
    MODERATE = "MODERATE"  # 41-60
    STRONG = "STRONG"  # 61-80
    VERY_STRONG = "VERY_STRONG"  # 81-100


@dataclass
class TrendStructure:
    """
    Represents a detected trend pattern structure.

    Attributes:
        pattern: Type of pattern (HH, HL, LH, LL)
        price: Price of the swing point
        timestamp: When the pattern was confirmed
        candle_index: Index of the confirming candle
        previous_swing_price: Price of the previous swing point
        previous_swing_index: Index of the previous swing point
        swing_length: Number of candles between swings
        price_change: Price difference from previous swing
        price_change_pct: Percentage change from previous swing
    """

    pattern: TrendPattern
    price: float
    timestamp: int
    candle_index: int
    previous_swing_price: float
    previous_swing_index: int
    swing_length: int
    price_change: float
    price_change_pct: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "pattern": self.pattern.value,
            "price": self.price,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp / 1000).isoformat(),
            "candle_index": self.candle_index,
            "previous_swing_price": self.previous_swing_price,
            "previous_swing_index": self.previous_swing_index,
            "swing_length": self.swing_length,
            "price_change": self.price_change,
            "price_change_pct": self.price_change_pct,
        }


@dataclass
class TrendState:
    """
    Current state of the market trend.

    Attributes:
        direction: Current trend direction
        strength: Trend strength score (0-100)
        strength_level: Classified strength level
        symbol: Trading symbol
        timeframe: Analysis timeframe
        start_timestamp: When this trend started
        start_candle_index: Candle index where trend began
        last_update_timestamp: Most recent update
        pattern_count: Number of confirming patterns
        consecutive_patterns: Consecutive patterns in same direction
        avg_swing_length: Average candles between swings
        avg_price_change_pct: Average percentage price change
        is_confirmed: Whether trend is confirmed (multiple patterns)
    """

    direction: TrendDirection
    strength: float
    strength_level: TrendStrength
    symbol: str
    timeframe: TimeFrame
    start_timestamp: int
    start_candle_index: int
    last_update_timestamp: int
    pattern_count: int = 0
    consecutive_patterns: int = 0
    avg_swing_length: int = 0
    avg_price_change_pct: float = 0.0
    is_confirmed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "direction": self.direction.value,
            "strength": self.strength,
            "strength_level": self.strength_level.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "start_timestamp": self.start_timestamp,
            "start_datetime": datetime.fromtimestamp(self.start_timestamp / 1000).isoformat(),
            "start_candle_index": self.start_candle_index,
            "last_update_timestamp": self.last_update_timestamp,
            "last_update_datetime": datetime.fromtimestamp(
                self.last_update_timestamp / 1000
            ).isoformat(),
            "pattern_count": self.pattern_count,
            "consecutive_patterns": self.consecutive_patterns,
            "avg_swing_length": self.avg_swing_length,
            "avg_price_change_pct": self.avg_price_change_pct,
            "is_confirmed": self.is_confirmed,
        }


class TrendRecognitionEngine:
    """
    Detects and analyzes Higher High/Lower Low trend patterns.

    The engine identifies trend patterns through systematic analysis of swing
    highs and lows, calculating trend strength and detecting transitions.

    Key Features:
    - HH/HL pattern detection for uptrends
    - LH/LL pattern detection for downtrends
    - ATR-based noise filtering
    - Trend strength calculation
    - Trend change detection with confirmation
    """

    def __init__(
        self,
        min_swing_strength: int = 3,
        min_patterns_for_confirmation: int = 2,
        min_price_change_atr_multiple: float = 0.5,
        atr_period: int = 14,
        transition_threshold: float = 40.0,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize Trend Recognition Engine.

        Args:
            min_swing_strength: Minimum candles on each side for swing detection
            min_patterns_for_confirmation: Minimum patterns to confirm trend
            min_price_change_atr_multiple: Minimum price change as ATR multiple
            atr_period: Period for ATR calculation
            transition_threshold: Strength threshold for trend transition
            event_bus: Optional EventBus for publishing events
        """
        self.min_swing_strength = min_swing_strength
        self.min_patterns_for_confirmation = min_patterns_for_confirmation
        self.min_price_change_atr_multiple = min_price_change_atr_multiple
        self.atr_period = atr_period
        self.transition_threshold = transition_threshold
        self.event_bus = event_bus

        self._current_trend: Optional[TrendState] = None
        self._trend_structures: List[TrendStructure] = []
        self._swing_highs: List[SwingPoint] = []
        self._swing_lows: List[SwingPoint] = []

        self.logger = logging.getLogger(f"{__name__}.TrendRecognitionEngine")

    def calculate_atr(self, candles: List[Candle], period: Optional[int] = None) -> float:
        """
        Calculate Average True Range for noise filtering.

        Args:
            candles: List of candles
            period: ATR period (uses default if None)

        Returns:
            ATR value
        """
        period = period or self.atr_period

        if len(candles) < period:
            self.logger.warning(f"Insufficient candles for ATR. Need {period}, got {len(candles)}")
            return 0.0

        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i - 1].close

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        # Use last 'period' true ranges
        relevant_trs = true_ranges[-period:]
        return sum(relevant_trs) / len(relevant_trs) if relevant_trs else 0.0

    def detect_swing_highs(
        self, candles: List[Candle], lookback: Optional[int] = None
    ) -> List[SwingPoint]:
        """
        Detect swing high points in candle data.

        A swing high is a candle whose high is higher than surrounding candles.

        Args:
            candles: List of candles to analyze
            lookback: Number of candles to check on each side

        Returns:
            List of detected swing high points
        """
        lookback = lookback or self.min_swing_strength

        if len(candles) < (lookback * 2 + 1):
            self.logger.warning(
                f"Insufficient candles for swing detection. "
                f"Need {lookback * 2 + 1}, got {len(candles)}"
            )
            return []

        swing_highs = []

        for i in range(lookback, len(candles) - lookback):
            current_high = candles[i].high

            # Check if higher than all previous lookback candles
            is_swing_high = all(current_high > candles[j].high for j in range(i - lookback, i))

            # Check if higher than all following lookback candles
            if is_swing_high:
                is_swing_high = all(
                    current_high > candles[j].high
                    for j in range(i + 1, min(i + lookback + 1, len(candles)))
                )

            if is_swing_high:
                swing_highs.append(
                    SwingPoint(
                        price=current_high,
                        timestamp=candles[i].timestamp,
                        candle_index=i,
                        is_high=True,
                        strength=lookback,
                        volume=candles[i].volume,
                    )
                )

        return swing_highs

    def detect_swing_lows(
        self, candles: List[Candle], lookback: Optional[int] = None
    ) -> List[SwingPoint]:
        """
        Detect swing low points in candle data.

        A swing low is a candle whose low is lower than surrounding candles.

        Args:
            candles: List of candles to analyze
            lookback: Number of candles to check on each side

        Returns:
            List of detected swing low points
        """
        lookback = lookback or self.min_swing_strength

        if len(candles) < (lookback * 2 + 1):
            self.logger.warning(
                f"Insufficient candles for swing detection. "
                f"Need {lookback * 2 + 1}, got {len(candles)}"
            )
            return []

        swing_lows = []

        for i in range(lookback, len(candles) - lookback):
            current_low = candles[i].low

            # Check if lower than all previous lookback candles
            is_swing_low = all(current_low < candles[j].low for j in range(i - lookback, i))

            # Check if lower than all following lookback candles
            if is_swing_low:
                is_swing_low = all(
                    current_low < candles[j].low
                    for j in range(i + 1, min(i + lookback + 1, len(candles)))
                )

            if is_swing_low:
                swing_lows.append(
                    SwingPoint(
                        price=current_low,
                        timestamp=candles[i].timestamp,
                        candle_index=i,
                        is_high=False,
                        strength=lookback,
                        volume=candles[i].volume,
                    )
                )

        return swing_lows

    def is_significant_move(self, price_change: float, candles: List[Candle]) -> bool:
        """
        Check if price move is significant using ATR filter.

        Args:
            price_change: Absolute price change
            candles: Candle data for ATR calculation

        Returns:
            True if move is significant (above noise threshold)
        """
        atr = self.calculate_atr(candles)
        if atr == 0:
            return True  # No ATR available, accept the move

        min_change = atr * self.min_price_change_atr_multiple
        return abs(price_change) >= min_change

    def identify_pattern(
        self, current_swing: SwingPoint, previous_swing: SwingPoint
    ) -> Optional[TrendPattern]:
        """
        Identify the trend pattern between two swing points.

        Args:
            current_swing: Current swing point
            previous_swing: Previous swing point

        Returns:
            Detected pattern or None
        """
        if current_swing.is_high and previous_swing.is_high:
            # Comparing two highs
            if current_swing.price > previous_swing.price:
                return TrendPattern.HIGHER_HIGH
            else:
                return TrendPattern.LOWER_HIGH

        elif not current_swing.is_high and not previous_swing.is_high:
            # Comparing two lows
            if current_swing.price > previous_swing.price:
                return TrendPattern.HIGHER_LOW
            else:
                return TrendPattern.LOWER_LOW

        return None

    def analyze_trend_patterns(
        self, candles: List[Candle]
    ) -> Tuple[List[TrendStructure], TrendDirection]:
        """
        Analyze candles to detect HH/HL/LH/LL patterns.

        Args:
            candles: List of candles to analyze

        Returns:
            Tuple of (trend structures, overall trend direction)
        """
        min_candles = self.min_swing_strength * 2 + 1
        if len(candles) < min_candles:
            raise ValueError(
                f"Insufficient candles for trend analysis. "
                f"Need at least {min_candles}, got {len(candles)}"
            )

        self.logger.info(
            f"Analyzing trend patterns in {len(candles)} candles "
            f"({candles[0].symbol}, {candles[0].timeframe.value})"
        )

        # Detect swing points
        swing_highs = self.detect_swing_highs(candles)
        swing_lows = self.detect_swing_lows(candles)

        self.logger.info(f"Found {len(swing_highs)} swing highs and {len(swing_lows)} swing lows")

        # Store for later use
        self._swing_highs = swing_highs
        self._swing_lows = swing_lows

        # Analyze high patterns (HH/LH)
        high_patterns = []
        for i in range(1, len(swing_highs)):
            current = swing_highs[i]
            previous = swing_highs[i - 1]

            price_change = current.price - previous.price

            # Apply noise filter
            if not self.is_significant_move(price_change, candles):
                continue

            pattern = self.identify_pattern(current, previous)
            if pattern:
                swing_length = current.candle_index - previous.candle_index
                price_change_pct = (price_change / previous.price) * 100

                structure = TrendStructure(
                    pattern=pattern,
                    price=current.price,
                    timestamp=current.timestamp,
                    candle_index=current.candle_index,
                    previous_swing_price=previous.price,
                    previous_swing_index=previous.candle_index,
                    swing_length=swing_length,
                    price_change=price_change,
                    price_change_pct=price_change_pct,
                )
                high_patterns.append(structure)

        # Analyze low patterns (HL/LL)
        low_patterns = []
        for i in range(1, len(swing_lows)):
            current = swing_lows[i]
            previous = swing_lows[i - 1]

            price_change = current.price - previous.price

            # Apply noise filter
            if not self.is_significant_move(price_change, candles):
                continue

            pattern = self.identify_pattern(current, previous)
            if pattern:
                swing_length = current.candle_index - previous.candle_index
                price_change_pct = (price_change / previous.price) * 100

                structure = TrendStructure(
                    pattern=pattern,
                    price=current.price,
                    timestamp=current.timestamp,
                    candle_index=current.candle_index,
                    previous_swing_price=previous.price,
                    previous_swing_index=previous.candle_index,
                    swing_length=swing_length,
                    price_change=price_change,
                    price_change_pct=price_change_pct,
                )
                low_patterns.append(structure)

        # Combine and sort by candle index
        all_structures = sorted(high_patterns + low_patterns, key=lambda s: s.candle_index)

        self._trend_structures = all_structures

        # Determine overall trend
        direction = self._determine_trend_direction(all_structures)

        self.logger.info(
            f"Detected {len(all_structures)} trend structures. "
            f"Overall direction: {direction.value}"
        )

        return all_structures, direction

    def _determine_trend_direction(self, structures: List[TrendStructure]) -> TrendDirection:
        """
        Determine overall trend direction from pattern structures.

        Args:
            structures: List of trend structures

        Returns:
            Overall trend direction
        """
        if not structures:
            return TrendDirection.RANGING

        # Count pattern types
        hh_count = sum(1 for s in structures if s.pattern == TrendPattern.HIGHER_HIGH)
        hl_count = sum(1 for s in structures if s.pattern == TrendPattern.HIGHER_LOW)
        lh_count = sum(1 for s in structures if s.pattern == TrendPattern.LOWER_HIGH)
        ll_count = sum(1 for s in structures if s.pattern == TrendPattern.LOWER_LOW)

        bullish_patterns = hh_count + hl_count
        lh_count + ll_count

        total_patterns = len(structures)
        bullish_ratio = bullish_patterns / total_patterns if total_patterns > 0 else 0

        # Check recent patterns (last 3-5)
        recent_count = min(5, len(structures))
        recent_structures = structures[-recent_count:]
        recent_bullish = sum(
            1
            for s in recent_structures
            if s.pattern in (TrendPattern.HIGHER_HIGH, TrendPattern.HIGHER_LOW)
        )
        recent_bearish = sum(
            1
            for s in recent_structures
            if s.pattern in (TrendPattern.LOWER_HIGH, TrendPattern.LOWER_LOW)
        )

        # Determine direction
        if bullish_ratio >= 0.65 and recent_bullish >= recent_bearish:
            return TrendDirection.UPTREND
        elif bullish_ratio <= 0.35 and recent_bearish >= recent_bullish:
            return TrendDirection.DOWNTREND
        elif abs(recent_bullish - recent_bearish) <= 1:
            return TrendDirection.RANGING
        else:
            return TrendDirection.TRANSITION

    def calculate_trend_strength(
        self, structures: List[TrendStructure], direction: TrendDirection
    ) -> Tuple[float, TrendStrength]:
        """
        Calculate trend strength score.

        Strength based on:
        - Pattern consistency (same direction patterns)
        - Consecutive patterns in trend direction
        - Average price change magnitude
        - Recent pattern momentum

        Args:
            structures: Trend structures
            direction: Trend direction

        Returns:
            Tuple of (strength score 0-100, strength level)
        """
        if not structures or direction == TrendDirection.RANGING:
            return 0.0, TrendStrength.VERY_WEAK

        # Pattern consistency score (0-35 points)
        if direction == TrendDirection.UPTREND:
            aligned_patterns = [
                s
                for s in structures
                if s.pattern in (TrendPattern.HIGHER_HIGH, TrendPattern.HIGHER_LOW)
            ]
        elif direction == TrendDirection.DOWNTREND:
            aligned_patterns = [
                s
                for s in structures
                if s.pattern in (TrendPattern.LOWER_HIGH, TrendPattern.LOWER_LOW)
            ]
        else:
            aligned_patterns = []

        consistency_ratio = len(aligned_patterns) / len(structures) if structures else 0
        consistency_score = consistency_ratio * 35

        # Consecutive patterns score (0-30 points)
        max_consecutive = self._count_max_consecutive(structures, direction)
        consecutive_score = min(30, max_consecutive * 6)

        # Average price change score (0-25 points)
        avg_price_change = (
            sum(abs(s.price_change_pct) for s in aligned_patterns) / len(aligned_patterns)
            if aligned_patterns
            else 0
        )
        price_change_score = min(25, avg_price_change * 5)

        # Recent momentum score (0-10 points)
        recent_count = min(3, len(structures))
        recent = structures[-recent_count:]
        recent_aligned = sum(
            1
            for s in recent
            if (
                direction == TrendDirection.UPTREND
                and s.pattern in (TrendPattern.HIGHER_HIGH, TrendPattern.HIGHER_LOW)
            )
            or (
                direction == TrendDirection.DOWNTREND
                and s.pattern in (TrendPattern.LOWER_HIGH, TrendPattern.LOWER_LOW)
            )
        )
        momentum_score = (recent_aligned / recent_count * 10) if recent_count > 0 else 0

        # Calculate total
        total_score = consistency_score + consecutive_score + price_change_score + momentum_score
        total_score = min(100, max(0, total_score))

        # Classify strength
        if total_score >= 81:
            strength_level = TrendStrength.VERY_STRONG
        elif total_score >= 61:
            strength_level = TrendStrength.STRONG
        elif total_score >= 41:
            strength_level = TrendStrength.MODERATE
        elif total_score >= 21:
            strength_level = TrendStrength.WEAK
        else:
            strength_level = TrendStrength.VERY_WEAK

        return total_score, strength_level

    def _count_max_consecutive(
        self, structures: List[TrendStructure], direction: TrendDirection
    ) -> int:
        """
        Count maximum consecutive patterns in trend direction.

        Args:
            structures: Trend structures
            direction: Trend direction

        Returns:
            Maximum consecutive count
        """
        if not structures:
            return 0

        max_count = 0
        current_count = 0

        for structure in structures:
            if direction == TrendDirection.UPTREND:
                is_aligned = structure.pattern in (
                    TrendPattern.HIGHER_HIGH,
                    TrendPattern.HIGHER_LOW,
                )
            elif direction == TrendDirection.DOWNTREND:
                is_aligned = structure.pattern in (TrendPattern.LOWER_HIGH, TrendPattern.LOWER_LOW)
            else:
                is_aligned = False

            if is_aligned:
                current_count += 1
                max_count = max(max_count, current_count)
            else:
                current_count = 0

        return max_count

    def detect_trend_change(self, candles: List[Candle]) -> Optional[TrendState]:
        """
        Detect if a trend change has occurred.

        Args:
            candles: Current candle data

        Returns:
            New TrendState if change detected, None otherwise
        """
        structures, direction = self.analyze_trend_patterns(candles)

        if not structures:
            return None

        strength, strength_level = self.calculate_trend_strength(structures, direction)

        # Check for trend change
        if self._current_trend is None:
            # First trend detection
            is_change = True
        elif self._current_trend.direction != direction:
            # Direction changed
            is_change = True
        elif abs(self._current_trend.strength - strength) > self.transition_threshold:
            # Significant strength change
            is_change = True
        else:
            is_change = False

        if is_change:
            # Calculate statistics
            avg_swing_length = (
                sum(s.swing_length for s in structures) / len(structures) if structures else 0
            )
            avg_price_change_pct = (
                sum(abs(s.price_change_pct) for s in structures) / len(structures)
                if structures
                else 0.0
            )

            new_trend = TrendState(
                direction=direction,
                strength=strength,
                strength_level=strength_level,
                symbol=candles[0].symbol,
                timeframe=candles[0].timeframe,
                start_timestamp=structures[0].timestamp if structures else candles[0].timestamp,
                start_candle_index=structures[0].candle_index if structures else 0,
                last_update_timestamp=candles[-1].timestamp,
                pattern_count=len(structures),
                consecutive_patterns=self._count_max_consecutive(structures, direction),
                avg_swing_length=int(avg_swing_length),
                avg_price_change_pct=avg_price_change_pct,
                is_confirmed=len(structures) >= self.min_patterns_for_confirmation,
            )

            self._current_trend = new_trend

            # Publish event
            if self.event_bus:
                self._publish_trend_event(new_trend)

            self.logger.info(
                f"Trend change detected: {direction.value} "
                f"(strength={strength:.1f}, patterns={len(structures)})"
            )

            return new_trend

        return None

    def _publish_trend_event(self, trend_state: TrendState) -> None:
        """
        Publish trend change event to EventBus.

        Args:
            trend_state: The new trend state
        """
        if not self.event_bus:
            return

        event = Event(
            priority=8,  # High priority
            event_type=EventType.MARKET_STRUCTURE_CHANGE,
            timestamp=datetime.now(),
            data=trend_state.to_dict(),
            source="TrendRecognitionEngine",
        )

        # Publish asynchronously
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.event_bus.publish(event))
            else:
                asyncio.run(self.event_bus.publish(event))
        except Exception as e:
            self.logger.error(f"Failed to publish trend event: {e}")

    def get_current_trend(self) -> Optional[TrendState]:
        """
        Get the current trend state.

        Returns:
            Current TrendState or None
        """
        return self._current_trend

    def get_trend_structures(self) -> List[TrendStructure]:
        """
        Get all detected trend structures.

        Returns:
            List of TrendStructure objects
        """
        return self._trend_structures.copy()

    def get_swing_points(self) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Get detected swing highs and lows.

        Returns:
            Tuple of (swing_highs, swing_lows)
        """
        return self._swing_highs.copy(), self._swing_lows.copy()

    def clear_history(self) -> None:
        """Clear trend history and reset state."""
        self._current_trend = None
        self._trend_structures.clear()
        self._swing_highs.clear()
        self._swing_lows.clear()
        self.logger.debug("Cleared trend recognition history")
