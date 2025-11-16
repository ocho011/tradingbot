"""
Break of Market Structure (BMS) detection for ICT trading methodology.

This module implements detection of BMS patterns where price decisively breaks
through established market structure levels, signaling potential trend reversals
or continuations. BMS is a critical confirmation signal in ICT methodology.

Key Concepts:
- BMS occurs when price breaks a significant swing high/low
- Validates structural change in the market
- Confirms new structure formation after the break
- Filters false breakouts using multiple confirmation criteria
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.core.constants import EventType, TimeFrame
from src.core.events import Event, EventBus
from src.indicators.liquidity_zone import SwingPoint
from src.indicators.trend_recognition import (
    TrendDirection,
    TrendRecognitionEngine,
)
from src.models.candle import Candle

logger = logging.getLogger(__name__)


class BMSType(str, Enum):
    """Type of BMS based on direction."""

    BULLISH = "BULLISH"  # Break above previous high (bullish structure)
    BEARISH = "BEARISH"  # Break below previous low (bearish structure)


class BMSState(str, Enum):
    """State of BMS detection."""

    POTENTIAL = "POTENTIAL"  # Level broken but not confirmed
    CONFIRMED = "CONFIRMED"  # BMS confirmed with all criteria
    INVALIDATED = "INVALIDATED"  # Failed confirmation criteria
    ESTABLISHED = "ESTABLISHED"  # New structure formed after BMS


class BMSConfidenceLevel(str, Enum):
    """Confidence level of BMS signal."""

    LOW = "LOW"  # 0-40
    MEDIUM = "MEDIUM"  # 41-70
    HIGH = "HIGH"  # 71-100


@dataclass
class BreakOfMarketStructure:
    """
    Represents a detected Break of Market Structure.

    Attributes:
        bms_type: Direction of the BMS (bullish/bearish)
        broken_level: The structural level that was broken
        break_timestamp: When the break occurred
        break_candle_index: Index of the breaking candle
        confirmation_timestamp: When BMS was confirmed
        confirmation_candle_index: Index of confirmation candle
        break_distance: Distance of break beyond level (pips)
        follow_through_distance: Distance of follow-through move (pips)
        confidence_score: Confidence score (0-100)
        confidence_level: Classified confidence level
        state: Current state of the BMS
        symbol: Trading symbol
        timeframe: Timeframe where detected
        volume_confirmation: Whether volume confirmed the break
        structure_significance: Significance of the broken structure (0-100)
        new_structure_formed: Whether new structure has formed
    """

    bms_type: BMSType
    broken_level: SwingPoint
    break_timestamp: int
    break_candle_index: int
    confirmation_timestamp: Optional[int] = None
    confirmation_candle_index: Optional[int] = None
    break_distance: float = 0.0
    follow_through_distance: float = 0.0
    confidence_score: float = 0.0
    confidence_level: BMSConfidenceLevel = BMSConfidenceLevel.LOW
    state: BMSState = BMSState.POTENTIAL
    symbol: str = ""
    timeframe: TimeFrame = TimeFrame.M1
    volume_confirmation: bool = False
    structure_significance: float = 0.0
    new_structure_formed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert BMS to dictionary format."""
        return {
            "bms_type": self.bms_type.value,
            "broken_level": {
                "price": self.broken_level.price,
                "is_high": self.broken_level.is_high,
                "candle_index": self.broken_level.candle_index,
            },
            "break_timestamp": self.break_timestamp,
            "break_datetime": datetime.fromtimestamp(self.break_timestamp / 1000).isoformat(),
            "break_candle_index": self.break_candle_index,
            "confirmation_timestamp": self.confirmation_timestamp,
            "confirmation_datetime": (
                datetime.fromtimestamp(self.confirmation_timestamp / 1000).isoformat()
                if self.confirmation_timestamp
                else None
            ),
            "confirmation_candle_index": self.confirmation_candle_index,
            "break_distance": self.break_distance,
            "follow_through_distance": self.follow_through_distance,
            "confidence_score": self.confidence_score,
            "confidence_level": self.confidence_level.value,
            "state": self.state.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "volume_confirmation": self.volume_confirmation,
            "structure_significance": self.structure_significance,
            "new_structure_formed": self.new_structure_formed,
        }

    def __repr__(self) -> str:
        """String representation of BMS."""
        return (
            f"BMS({self.bms_type.value}, "
            f"level={self.broken_level.price:.2f}, "
            f"confidence={self.confidence_score:.1f}, "
            f"state={self.state.value})"
        )


@dataclass
class BMSCandidate:
    """
    Tracks a potential BMS in progress.

    Used internally to monitor breaks until they are confirmed or invalidated.
    """

    broken_level: SwingPoint
    bms_type: BMSType
    break_candle_index: int
    break_timestamp: int
    break_price: float
    state: BMSState = BMSState.POTENTIAL
    confirmation_candle_index: Optional[int] = None
    confirmation_timestamp: Optional[int] = None


class MarketStructureBreakDetector:
    """
    Detects Break of Market Structure (BMS) patterns in real-time.

    The detector identifies when price decisively breaks through key structural
    levels (swing highs/lows) and confirms the break through multiple criteria:
    - Clean break distance
    - Close beyond the level
    - Follow-through price action
    - Volume confirmation
    - New structure formation
    """

    def __init__(
        self,
        min_break_distance_pips: float = 2.0,
        max_break_distance_pips: float = 50.0,
        min_follow_through_pips: float = 5.0,
        confirmation_candles: int = 3,
        volume_threshold_multiple: float = 1.2,
        min_structure_significance: float = 30.0,
        min_confidence_for_confirmed: float = 60.0,
        pip_size: float = 0.0001,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize Market Structure Break detector.

        Args:
            min_break_distance_pips: Minimum pips beyond level for valid break
            max_break_distance_pips: Maximum pips for valid break (filters gaps)
            min_follow_through_pips: Minimum follow-through distance after break
            confirmation_candles: Candles to wait for confirmation
            volume_threshold_multiple: Volume multiplier for confirmation
            min_structure_significance: Minimum significance score for important levels
            min_confidence_for_confirmed: Minimum confidence to confirm BMS
            pip_size: Size of one pip (0.0001 for most forex, 0.01 for JPY)
            event_bus: Optional EventBus for publishing BMS events
        """
        self.min_break_distance_pips = min_break_distance_pips
        self.max_break_distance_pips = max_break_distance_pips
        self.min_follow_through_pips = min_follow_through_pips
        self.confirmation_candles = confirmation_candles
        self.volume_threshold_multiple = volume_threshold_multiple
        self.min_structure_significance = min_structure_significance
        self.min_confidence_for_confirmed = min_confidence_for_confirmed
        self.pip_size = pip_size
        self.event_bus = event_bus

        self._candidates: List[BMSCandidate] = []
        self._confirmed_bms: List[BreakOfMarketStructure] = []
        self._trend_engine: Optional[TrendRecognitionEngine] = None

        self.logger = logging.getLogger(f"{__name__}.MarketStructureBreakDetector")

    def set_trend_engine(self, trend_engine: TrendRecognitionEngine) -> None:
        """
        Set the trend recognition engine for structure analysis.

        Args:
            trend_engine: TrendRecognitionEngine instance
        """
        self._trend_engine = trend_engine

    def detect_bms(
        self,
        candles: List[Candle],
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint],
        start_index: int = 0,
    ) -> List[BreakOfMarketStructure]:
        """
        Detect BMS patterns in candle data.

        Args:
            candles: List of candles to analyze
            swing_highs: Detected swing high points
            swing_lows: Detected swing low points
            start_index: Starting candle index for detection

        Returns:
            List of detected and confirmed BMS patterns
        """
        if not candles or (not swing_highs and not swing_lows):
            return []

        self.logger.info(
            f"Detecting BMS in {len(candles)} candles with "
            f"{len(swing_highs)} highs and {len(swing_lows)} lows "
            f"(start_index={start_index})"
        )

        bms_detected = []

        for i in range(start_index, len(candles)):
            candle = candles[i]

            # Check for breaks of swing highs (bullish BMS)
            for swing_high in swing_highs:
                # Skip if swing formed after this candle
                if swing_high.candle_index >= i:
                    continue

                # Skip if already have candidate for this level
                if any(c.broken_level == swing_high for c in self._candidates):
                    continue

                # Skip if already have confirmed BMS for this level
                if any(bms.broken_level == swing_high for bms in self._confirmed_bms):
                    continue

                # Check for break
                candidate = self._check_high_break(candle, swing_high, i)
                if candidate:
                    self._candidates.append(candidate)
                    self.logger.debug(
                        f"Potential bullish BMS: level {swing_high.price:.5f} "
                        f"broken at index {i}"
                    )

            # Check for breaks of swing lows (bearish BMS)
            for swing_low in swing_lows:
                # Skip if swing formed after this candle
                if swing_low.candle_index >= i:
                    continue

                # Skip if already have candidate for this level
                if any(c.broken_level == swing_low for c in self._candidates):
                    continue

                # Skip if already have confirmed BMS for this level
                if any(bms.broken_level == swing_low for bms in self._confirmed_bms):
                    continue

                # Check for break
                candidate = self._check_low_break(candle, swing_low, i)
                if candidate:
                    self._candidates.append(candidate)
                    self.logger.debug(
                        f"Potential bearish BMS: level {swing_low.price:.5f} "
                        f"broken at index {i}"
                    )

            # Update existing candidates
            self._update_candidates(candle, i, candles, swing_highs, swing_lows)

            # Check for confirmed BMS
            confirmed = self._check_confirmations(candles, swing_highs, swing_lows)
            bms_detected.extend(confirmed)

        # Clean up stale candidates
        self._cleanup_candidates(len(candles) - 1)

        self.logger.info(f"Detected {len(bms_detected)} confirmed BMS patterns")
        return bms_detected

    def _check_high_break(
        self, candle: Candle, swing_high: SwingPoint, candle_index: int
    ) -> Optional[BMSCandidate]:
        """
        Check if a candle breaks above a swing high.

        Args:
            candle: The candle to check
            swing_high: The swing high level
            candle_index: Index of the candle

        Returns:
            BMSCandidate if break detected, None otherwise
        """
        if candle.high > swing_high.price:
            break_distance_pips = (candle.high - swing_high.price) / self.pip_size

            # Filter extreme moves and insufficient breaks
            if break_distance_pips < self.min_break_distance_pips:
                return None
            if break_distance_pips > self.max_break_distance_pips:
                self.logger.debug(
                    f"Break too far: {break_distance_pips:.1f} pips "
                    f"(max {self.max_break_distance_pips})"
                )
                return None

            return BMSCandidate(
                broken_level=swing_high,
                bms_type=BMSType.BULLISH,
                break_candle_index=candle_index,
                break_timestamp=candle.timestamp,
                break_price=candle.high,
                state=BMSState.POTENTIAL,
            )

        return None

    def _check_low_break(
        self, candle: Candle, swing_low: SwingPoint, candle_index: int
    ) -> Optional[BMSCandidate]:
        """
        Check if a candle breaks below a swing low.

        Args:
            candle: The candle to check
            swing_low: The swing low level
            candle_index: Index of the candle

        Returns:
            BMSCandidate if break detected, None otherwise
        """
        if candle.low < swing_low.price:
            break_distance_pips = (swing_low.price - candle.low) / self.pip_size

            # Filter extreme moves and insufficient breaks
            if break_distance_pips < self.min_break_distance_pips:
                return None
            if break_distance_pips > self.max_break_distance_pips:
                self.logger.debug(
                    f"Break too far: {break_distance_pips:.1f} pips "
                    f"(max {self.max_break_distance_pips})"
                )
                return None

            return BMSCandidate(
                broken_level=swing_low,
                bms_type=BMSType.BEARISH,
                break_candle_index=candle_index,
                break_timestamp=candle.timestamp,
                break_price=candle.low,
                state=BMSState.POTENTIAL,
            )

        return None

    def _update_candidates(
        self,
        candle: Candle,
        candle_index: int,
        all_candles: List[Candle],
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint],
    ) -> None:
        """
        Update state of existing BMS candidates.

        Args:
            candle: Current candle
            candle_index: Index of current candle
            all_candles: Full list of candles
            swing_highs: All swing highs
            swing_lows: All swing lows
        """
        for candidate in self._candidates:
            if candidate.state == BMSState.POTENTIAL:
                candles_since_break = candle_index - candidate.break_candle_index

                # Check if enough candles have passed for confirmation
                if candles_since_break >= self.confirmation_candles:
                    # Evaluate confirmation
                    if self._evaluate_confirmation(
                        candidate, all_candles, candle_index, swing_highs, swing_lows
                    ):
                        candidate.state = BMSState.CONFIRMED
                        candidate.confirmation_candle_index = candle_index
                        candidate.confirmation_timestamp = candle.timestamp
                        self.logger.info(
                            f"BMS confirmed: {candidate.bms_type.value} at "
                            f"{candidate.broken_level.price:.5f}"
                        )
                    else:
                        candidate.state = BMSState.INVALIDATED
                        self.logger.debug(
                            f"BMS invalidated: {candidate.bms_type.value} at "
                            f"{candidate.broken_level.price:.5f}"
                        )

    def _evaluate_confirmation(
        self,
        candidate: BMSCandidate,
        candles: List[Candle],
        current_index: int,
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint],
    ) -> bool:
        """
        Evaluate if a BMS candidate should be confirmed.

        Checks multiple criteria:
        - Close beyond the level
        - Follow-through price action
        - Volume confirmation
        - No immediate reversal

        Args:
            candidate: The BMS candidate
            candles: All candles
            current_index: Current candle index
            swing_highs: All swing highs
            swing_lows: All swing lows

        Returns:
            True if BMS should be confirmed
        """
        level_price = candidate.broken_level.price
        confirmation_candles = candles[candidate.break_candle_index : current_index + 1]

        if not confirmation_candles:
            return False

        # Check 1: Close beyond level
        last_candle = confirmation_candles[-1]
        if candidate.bms_type == BMSType.BULLISH:
            close_beyond = last_candle.close > level_price
        else:
            close_beyond = last_candle.close < level_price

        if not close_beyond:
            return False

        # Check 2: Follow-through distance
        if candidate.bms_type == BMSType.BULLISH:
            follow_through = max(c.high for c in confirmation_candles) - level_price
        else:
            follow_through = level_price - min(c.low for c in confirmation_candles)

        follow_through_pips = follow_through / self.pip_size
        if follow_through_pips < self.min_follow_through_pips:
            return False

        # Check 3: No immediate reversal back across level
        for candle in confirmation_candles[1:]:  # Skip break candle
            if candidate.bms_type == BMSType.BULLISH:
                # For bullish BMS, check if price reversed below level
                if candle.close < level_price:
                    return False
            else:
                # For bearish BMS, check if price reversed above level
                if candle.close > level_price:
                    return False

        # Check 4: Volume confirmation (optional but increases confidence)
        avg_volume = sum(c.volume for c in candles) / len(candles) if candles else 1.0
        break_candle = candles[candidate.break_candle_index]
        volume_confirmed = break_candle.volume >= (avg_volume * self.volume_threshold_multiple)

        # BMS is confirmed if basic criteria met
        # Volume is used for confidence score but not required for confirmation
        return True

    def _check_confirmations(
        self, candles: List[Candle], swing_highs: List[SwingPoint], swing_lows: List[SwingPoint]
    ) -> List[BreakOfMarketStructure]:
        """
        Check for confirmed BMS and create BreakOfMarketStructure objects.

        Args:
            candles: All candles
            swing_highs: All swing highs
            swing_lows: All swing lows

        Returns:
            List of confirmed BMS
        """
        confirmed = []
        remaining_candidates = []

        for candidate in self._candidates:
            if candidate.state == BMSState.CONFIRMED:
                # Calculate all metrics
                break_distance_pips = (
                    abs(candidate.break_price - candidate.broken_level.price) / self.pip_size
                )

                level_price = candidate.broken_level.price
                confirmation_candles = candles[
                    candidate.break_candle_index : (
                        candidate.confirmation_candle_index or len(candles)
                    )
                    + 1
                ]

                if candidate.bms_type == BMSType.BULLISH:
                    follow_through = max(c.high for c in confirmation_candles) - level_price
                else:
                    follow_through = level_price - min(c.low for c in confirmation_candles)

                follow_through_pips = follow_through / self.pip_size

                # Calculate structure significance
                structure_significance = self._calculate_structure_significance(
                    candidate.broken_level,
                    swing_highs if candidate.broken_level.is_high else swing_lows,
                    candles,
                )

                # Calculate confidence score
                confidence_score, confidence_level, volume_confirmed = self._calculate_confidence(
                    candidate,
                    break_distance_pips,
                    follow_through_pips,
                    structure_significance,
                    candles,
                )

                # Only confirm if confidence meets threshold
                if confidence_score >= self.min_confidence_for_confirmed:
                    bms = BreakOfMarketStructure(
                        bms_type=candidate.bms_type,
                        broken_level=candidate.broken_level,
                        break_timestamp=candidate.break_timestamp,
                        break_candle_index=candidate.break_candle_index,
                        confirmation_timestamp=candidate.confirmation_timestamp,
                        confirmation_candle_index=candidate.confirmation_candle_index,
                        break_distance=break_distance_pips,
                        follow_through_distance=follow_through_pips,
                        confidence_score=confidence_score,
                        confidence_level=confidence_level,
                        state=BMSState.CONFIRMED,
                        symbol=candles[0].symbol,
                        timeframe=candles[0].timeframe,
                        volume_confirmation=volume_confirmed,
                        structure_significance=structure_significance,
                        new_structure_formed=False,
                    )

                    confirmed.append(bms)
                    self._confirmed_bms.append(bms)

                    # Publish event
                    if self.event_bus:
                        self._publish_bms_event(bms)
                else:
                    # Not confident enough, invalidate
                    candidate.state = BMSState.INVALIDATED

            elif candidate.state == BMSState.POTENTIAL:
                # Keep pending candidates
                remaining_candidates.append(candidate)

        self._candidates = remaining_candidates
        return confirmed

    def _calculate_structure_significance(
        self, broken_level: SwingPoint, all_swings: List[SwingPoint], candles: List[Candle]
    ) -> float:
        """
        Calculate significance of the broken structure.

        Significance based on:
        - Swing strength (confirmation candles)
        - Number of touches at the level
        - Time since formation
        - Relative position in recent structure

        Args:
            broken_level: The swing point that was broken
            all_swings: All swing points of same type
            candles: All candles

        Returns:
            Significance score (0-100)
        """
        # Swing strength factor (0-30 points)
        max_swing_strength = 10
        swing_score = min(30, (broken_level.strength / max_swing_strength) * 30)

        # Historical touches factor (0-25 points)
        # Count how many times price approached this level
        touch_count = 0
        tolerance_pips = 2.0
        tolerance = tolerance_pips * self.pip_size

        for candle in candles[: broken_level.candle_index]:
            if broken_level.is_high:
                near_level = abs(candle.high - broken_level.price) <= tolerance
            else:
                near_level = abs(candle.low - broken_level.price) <= tolerance

            if near_level:
                touch_count += 1

        touch_score = min(25, touch_count * 5)

        # Recency factor (0-25 points)
        candles_since_formation = len(candles) - broken_level.candle_index
        max_age = 100  # candles
        recency_ratio = max(0, 1 - (candles_since_formation / max_age))
        recency_score = recency_ratio * 25

        # Relative significance (0-20 points)
        # More significant if it's a major swing in recent structure
        recent_swings = [s for s in all_swings if s.candle_index < broken_level.candle_index][-5:]
        if recent_swings:
            if broken_level.is_high:
                is_highest = broken_level.price == max(s.price for s in recent_swings)
            else:
                is_highest = broken_level.price == min(s.price for s in recent_swings)

            relative_score = 20 if is_highest else 10
        else:
            relative_score = 10

        total_score = swing_score + touch_score + recency_score + relative_score
        return min(100, max(0, total_score))

    def _calculate_confidence(
        self,
        candidate: BMSCandidate,
        break_distance_pips: float,
        follow_through_pips: float,
        structure_significance: float,
        candles: List[Candle],
    ) -> Tuple[float, BMSConfidenceLevel, bool]:
        """
        Calculate confidence score for BMS.

        Confidence based on:
        - Break distance (clean vs. marginal)
        - Follow-through strength
        - Structure significance
        - Volume confirmation
        - Trend alignment

        Args:
            candidate: The BMS candidate
            break_distance_pips: Distance of break in pips
            follow_through_pips: Follow-through distance in pips
            structure_significance: Significance of broken structure
            candles: All candles

        Returns:
            Tuple of (confidence score, confidence level, volume_confirmed)
        """
        # Break cleanliness factor (0-25 points)
        ideal_break = 5.0  # pips
        break_ratio = min(1.0, break_distance_pips / ideal_break)
        break_score = break_ratio * 25

        # Follow-through factor (0-30 points)
        ideal_follow_through = 10.0  # pips
        follow_through_ratio = min(1.0, follow_through_pips / ideal_follow_through)
        follow_through_score = follow_through_ratio * 30

        # Structure significance factor (0-25 points)
        significance_score = structure_significance * 0.25

        # Volume confirmation factor (0-15 points)
        avg_volume = sum(c.volume for c in candles) / len(candles) if candles else 1.0
        break_candle = candles[candidate.break_candle_index]
        volume_ratio = break_candle.volume / avg_volume if avg_volume > 0 else 1.0
        volume_confirmed = volume_ratio >= self.volume_threshold_multiple
        volume_score = min(15, volume_ratio * 10) if volume_confirmed else 5

        # Trend alignment factor (0-5 points)
        # If we have trend engine, check if BMS aligns with trend
        trend_score = 0
        if self._trend_engine and self._trend_engine.get_current_trend():
            current_trend = self._trend_engine.get_current_trend()
            if current_trend:
                if (
                    candidate.bms_type == BMSType.BULLISH
                    and current_trend.direction == TrendDirection.UPTREND
                ) or (
                    candidate.bms_type == BMSType.BEARISH
                    and current_trend.direction == TrendDirection.DOWNTREND
                ):
                    trend_score = 5

        total_score = (
            break_score + follow_through_score + significance_score + volume_score + trend_score
        )
        total_score = min(100, max(0, total_score))

        # Classify confidence level
        if total_score >= 71:
            confidence_level = BMSConfidenceLevel.HIGH
        elif total_score >= 41:
            confidence_level = BMSConfidenceLevel.MEDIUM
        else:
            confidence_level = BMSConfidenceLevel.LOW

        return total_score, confidence_level, volume_confirmed

    def _cleanup_candidates(self, current_index: int) -> None:
        """
        Remove stale candidates that timed out.

        Args:
            current_index: Current candle index
        """
        max_candles_for_decision = self.confirmation_candles + 5
        active_candidates = []

        for candidate in self._candidates:
            candles_since_break = current_index - candidate.break_candle_index

            if candidate.state == BMSState.POTENTIAL:
                # Keep if within decision window
                if candles_since_break <= max_candles_for_decision:
                    active_candidates.append(candidate)

        removed_count = len(self._candidates) - len(active_candidates)
        if removed_count > 0:
            self.logger.debug(f"Cleaned up {removed_count} stale BMS candidates")

        self._candidates = active_candidates

    def _publish_bms_event(self, bms: BreakOfMarketStructure) -> None:
        """
        Publish BMS detection event to EventBus.

        Args:
            bms: The confirmed BMS
        """
        if not self.event_bus:
            return

        event = Event(
            priority=9,  # Very high priority for structural changes
            event_type=EventType.MARKET_STRUCTURE_BREAK,
            timestamp=datetime.now(),
            data=bms.to_dict(),
            source="MarketStructureBreakDetector",
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
            self.logger.error(f"Failed to publish BMS event: {e}")

    def get_confirmed_bms(
        self, bms_type: Optional[BMSType] = None, min_confidence: Optional[float] = None
    ) -> List[BreakOfMarketStructure]:
        """
        Get confirmed BMS with optional filtering.

        Args:
            bms_type: Filter by BMS type
            min_confidence: Minimum confidence score

        Returns:
            List of confirmed BMS matching filters
        """
        bms_list = self._confirmed_bms

        if bms_type:
            bms_list = [b for b in bms_list if b.bms_type == bms_type]

        if min_confidence is not None:
            bms_list = [b for b in bms_list if b.confidence_score >= min_confidence]

        return bms_list

    def get_active_candidates(self) -> List[BMSCandidate]:
        """
        Get list of active BMS candidates (for monitoring).

        Returns:
            List of candidates currently being tracked
        """
        return self._candidates.copy()

    def clear_history(self) -> None:
        """Clear confirmed BMS and candidates history."""
        self._confirmed_bms.clear()
        self._candidates.clear()
        self.logger.debug("Cleared BMS detection history")
