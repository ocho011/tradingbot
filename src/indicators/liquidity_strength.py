"""
Liquidity Strength Calculation and Market State Tracking for ICT methodology.

This module implements real-time tracking of:
- Liquidity strength based on touch count and volume
- Market state classification (Bullish/Bearish/Ranging)
- State transitions with event publishing
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.constants import EventType, TimeFrame
from src.core.events import Event, EventBus
from src.indicators.liquidity_zone import (
    LiquidityLevel,
    LiquidityState,
)
from src.indicators.market_structure_break import (
    BMSType,
    BreakOfMarketStructure,
)
from src.indicators.trend_recognition import TrendDirection, TrendState
from src.models.candle import Candle

logger = logging.getLogger(__name__)


class MarketState(str, Enum):
    """Current state of the market structure."""

    BULLISH = "BULLISH"  # Uptrend with BMS confirmation
    BEARISH = "BEARISH"  # Downtrend with BMS confirmation
    RANGING = "RANGING"  # No clear trend direction
    TRANSITIONING = "TRANSITIONING"  # Trend changing


class LiquidityStrengthLevel(str, Enum):
    """Classification of liquidity strength."""

    VERY_WEAK = "VERY_WEAK"  # 0-20
    WEAK = "WEAK"  # 21-40
    MODERATE = "MODERATE"  # 41-60
    STRONG = "STRONG"  # 61-80
    VERY_STRONG = "VERY_STRONG"  # 81-100


@dataclass
class LiquidityStrengthMetrics:
    """
    Metrics for liquidity level strength.

    Attributes:
        level: The liquidity level
        base_strength: Initial strength from swing significance
        touch_strength: Strength from touch count
        volume_strength: Strength from volume profile
        recency_strength: Strength from time relevance
        total_strength: Combined strength score (0-100)
        strength_level: Classified strength level
        last_calculated: When strength was last calculated
    """

    level: LiquidityLevel
    base_strength: float
    touch_strength: float
    volume_strength: float
    recency_strength: float
    total_strength: float
    strength_level: LiquidityStrengthLevel
    last_calculated: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "level": self.level.to_dict(),
            "base_strength": self.base_strength,
            "touch_strength": self.touch_strength,
            "volume_strength": self.volume_strength,
            "recency_strength": self.recency_strength,
            "total_strength": self.total_strength,
            "strength_level": self.strength_level.value,
            "last_calculated": self.last_calculated,
            "last_calculated_datetime": datetime.fromtimestamp(
                self.last_calculated / 1000
            ).isoformat(),
        }


@dataclass
class MarketStateData:
    """
    Complete market state information.

    Attributes:
        state: Current market state
        symbol: Trading symbol
        timeframe: Analysis timeframe
        trend_direction: Current trend direction
        trend_strength: Trend strength score (0-100)
        bms_count: Number of BMS in current state
        last_bms: Most recent BMS
        liquidity_profile: Summary of liquidity levels
        state_duration_candles: Candles in current state
        state_start_timestamp: When state began
        last_update_timestamp: Most recent update
        confidence_score: Confidence in current state (0-100)
    """

    state: MarketState
    symbol: str
    timeframe: TimeFrame
    trend_direction: TrendDirection
    trend_strength: float
    bms_count: int
    last_bms: Optional[BreakOfMarketStructure]
    liquidity_profile: Dict[str, Any]
    state_duration_candles: int
    state_start_timestamp: int
    last_update_timestamp: int
    confidence_score: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "state": self.state.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "trend_direction": self.trend_direction.value,
            "trend_strength": self.trend_strength,
            "bms_count": self.bms_count,
            "last_bms": self.last_bms.to_dict() if self.last_bms else None,
            "liquidity_profile": self.liquidity_profile,
            "state_duration_candles": self.state_duration_candles,
            "state_start_timestamp": self.state_start_timestamp,
            "state_start_datetime": datetime.fromtimestamp(
                self.state_start_timestamp / 1000
            ).isoformat(),
            "last_update_timestamp": self.last_update_timestamp,
            "last_update_datetime": datetime.fromtimestamp(
                self.last_update_timestamp / 1000
            ).isoformat(),
            "confidence_score": self.confidence_score,
        }


class LiquidityStrengthCalculator:
    """
    Calculates dynamic liquidity strength based on multiple factors.

    Strength calculation considers:
    - Base swing strength (structure significance)
    - Touch count (frequency of price interaction)
    - Volume profile (order flow intensity)
    - Recency (time-based relevance decay)
    - Market state context (trend alignment)
    """

    def __init__(
        self,
        base_weight: float = 0.25,
        touch_weight: float = 0.35,
        volume_weight: float = 0.25,
        recency_weight: float = 0.15,
        max_age_candles: int = 200,
        min_touches_for_strong: int = 3,
    ):
        """
        Initialize Liquidity Strength Calculator.

        Args:
            base_weight: Weight for base swing strength (0-1)
            touch_weight: Weight for touch count strength (0-1)
            volume_weight: Weight for volume strength (0-1)
            recency_weight: Weight for recency strength (0-1)
            max_age_candles: Maximum age before full decay
            min_touches_for_strong: Minimum touches for strong classification
        """
        # Validate weights sum to 1.0
        total_weight = base_weight + touch_weight + volume_weight + recency_weight
        if not (0.99 <= total_weight <= 1.01):
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")

        self.base_weight = base_weight
        self.touch_weight = touch_weight
        self.volume_weight = volume_weight
        self.recency_weight = recency_weight
        self.max_age_candles = max_age_candles
        self.min_touches_for_strong = min_touches_for_strong

        self.logger = logging.getLogger(f"{__name__}.LiquidityStrengthCalculator")

    def calculate_strength(
        self, level: LiquidityLevel, candles: List[Candle], current_index: int
    ) -> LiquidityStrengthMetrics:
        """
        Calculate comprehensive strength for a liquidity level.

        Args:
            level: The liquidity level to analyze
            candles: All candles for context
            current_index: Current candle index

        Returns:
            LiquidityStrengthMetrics with detailed strength breakdown
        """
        # Base strength from initial calculation (already in level)
        base_strength = level.strength

        # Touch strength (0-100 based on touch count)
        touch_strength = self._calculate_touch_strength(level)

        # Volume strength (0-100 based on volume profile)
        volume_strength = self._calculate_volume_strength(level, candles)

        # Recency strength (0-100 based on age)
        recency_strength = self._calculate_recency_strength(level, current_index)

        # Weighted total
        total_strength = (
            base_strength * self.base_weight
            + touch_strength * self.touch_weight
            + volume_strength * self.volume_weight
            + recency_strength * self.recency_weight
        )
        total_strength = min(100, max(0, total_strength))

        # Classify strength level
        strength_level = self._classify_strength(total_strength)

        return LiquidityStrengthMetrics(
            level=level,
            base_strength=base_strength,
            touch_strength=touch_strength,
            volume_strength=volume_strength,
            recency_strength=recency_strength,
            total_strength=total_strength,
            strength_level=strength_level,
            last_calculated=candles[current_index].timestamp,
        )

    def _calculate_touch_strength(self, level: LiquidityLevel) -> float:
        """
        Calculate strength from touch count.

        More touches = stronger level (with diminishing returns)

        Args:
            level: Liquidity level

        Returns:
            Touch strength score (0-100)
        """
        # Logarithmic scaling for diminishing returns
        if level.touch_count == 0:
            return 0.0

        # Each touch adds less value than the previous
        # 1 touch = 20, 2 = 35, 3 = 50, 5 = 65, 10 = 85, 20 = 100
        import math

        touch_score = 20 * math.log(level.touch_count + 1) / math.log(1.5)
        return min(100, max(0, touch_score))

    def _calculate_volume_strength(self, level: LiquidityLevel, candles: List[Candle]) -> float:
        """
        Calculate strength from volume profile.

        Higher volume at level = more institutional interest

        Args:
            level: Liquidity level
            candles: All candles for average calculation

        Returns:
            Volume strength score (0-100)
        """
        if not candles:
            return 0.0

        avg_volume = sum(c.volume for c in candles) / len(candles)
        if avg_volume == 0:
            return 50.0  # Neutral if no volume data

        # Compare level's volume to average
        volume_ratio = level.volume_profile / avg_volume

        # Scale: 0.5x = 25, 1.0x = 50, 1.5x = 75, 2.0x+ = 100
        volume_score = 25 + (volume_ratio - 0.5) * 50
        return min(100, max(0, volume_score))

    def _calculate_recency_strength(self, level: LiquidityLevel, current_index: int) -> float:
        """
        Calculate strength from recency (time decay).

        Older levels are less relevant

        Args:
            level: Liquidity level
            current_index: Current candle index

        Returns:
            Recency strength score (0-100)
        """
        age_candles = current_index - level.origin_candle_index

        if age_candles < 0:
            return 100.0  # Future level (shouldn't happen)

        # Linear decay over max_age_candles
        decay_ratio = 1.0 - (age_candles / self.max_age_candles)
        decay_ratio = max(0, min(1, decay_ratio))

        return decay_ratio * 100

    def _classify_strength(self, strength: float) -> LiquidityStrengthLevel:
        """
        Classify numeric strength into level.

        Args:
            strength: Numeric strength (0-100)

        Returns:
            Classified strength level
        """
        if strength >= 81:
            return LiquidityStrengthLevel.VERY_STRONG
        elif strength >= 61:
            return LiquidityStrengthLevel.STRONG
        elif strength >= 41:
            return LiquidityStrengthLevel.MODERATE
        elif strength >= 21:
            return LiquidityStrengthLevel.WEAK
        else:
            return LiquidityStrengthLevel.VERY_WEAK

    def calculate_all_strengths(
        self, levels: List[LiquidityLevel], candles: List[Candle], current_index: int
    ) -> List[LiquidityStrengthMetrics]:
        """
        Calculate strength for all liquidity levels.

        Args:
            levels: List of liquidity levels
            candles: All candles
            current_index: Current candle index

        Returns:
            List of strength metrics for each level
        """
        metrics = []
        for level in levels:
            # Only calculate for active/partial levels
            if level.state in (LiquidityState.ACTIVE, LiquidityState.PARTIAL):
                strength_metrics = self.calculate_strength(level, candles, current_index)
                metrics.append(strength_metrics)

        return metrics


class MarketStateTracker:
    """
    Tracks and classifies market state in real-time.

    Combines multiple ICT indicators to determine overall market state:
    - Trend direction and strength
    - Market structure breaks (BMS)
    - Liquidity sweeps and levels

    State determination logic:
    - BULLISH: Uptrend + bullish BMS + buy-side liquidity sweeps
    - BEARISH: Downtrend + bearish BMS + sell-side liquidity sweeps
    - RANGING: No clear trend + mixed BMS
    - TRANSITIONING: Trend change in progress
    """

    def __init__(
        self,
        min_bms_for_confirmation: int = 1,
        min_trend_strength: float = 40.0,
        min_confidence_for_state: float = 60.0,
        state_change_threshold: float = 30.0,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize Market State Tracker.

        Args:
            min_bms_for_confirmation: Minimum BMS for state confirmation
            min_trend_strength: Minimum trend strength for directional state
            min_confidence_for_state: Minimum confidence to maintain state
            state_change_threshold: Threshold for state transition
            event_bus: Optional EventBus for publishing state changes
        """
        self.min_bms_for_confirmation = min_bms_for_confirmation
        self.min_trend_strength = min_trend_strength
        self.min_confidence_for_state = min_confidence_for_state
        self.state_change_threshold = state_change_threshold
        self.event_bus = event_bus

        self._current_state: Optional[MarketStateData] = None
        self._state_history: List[MarketStateData] = []

        self.logger = logging.getLogger(f"{__name__}.MarketStateTracker")

    def update_state(
        self,
        candles: List[Candle],
        trend_state: Optional[TrendState],
        bms_list: List[BreakOfMarketStructure],
        buy_side_levels: List[LiquidityLevel],
        sell_side_levels: List[LiquidityLevel],
    ) -> Optional[MarketStateData]:
        """
        Update market state based on current indicators.

        Args:
            candles: Current candle data
            trend_state: Current trend state from TrendRecognitionEngine
            bms_list: List of recent BMS
            buy_side_levels: Active buy-side liquidity levels
            sell_side_levels: Active sell-side liquidity levels

        Returns:
            New MarketStateData if state changed, None otherwise
        """
        if not candles:
            return None

        # Determine new state
        new_market_state = self._determine_market_state(trend_state, bms_list)

        # Calculate confidence
        confidence = self._calculate_state_confidence(
            trend_state, bms_list, buy_side_levels, sell_side_levels
        )

        # Build liquidity profile
        liquidity_profile = self._build_liquidity_profile(buy_side_levels, sell_side_levels)

        # Check for state change
        if self._should_change_state(new_market_state, confidence):
            # Count BMS in recent period
            recent_bms = [
                bms
                for bms in bms_list
                if bms.bms_type
                == (BMSType.BULLISH if new_market_state == MarketState.BULLISH else BMSType.BEARISH)
            ]

            new_state_data = MarketStateData(
                state=new_market_state,
                symbol=candles[0].symbol,
                timeframe=candles[0].timeframe,
                trend_direction=trend_state.direction if trend_state else TrendDirection.RANGING,
                trend_strength=trend_state.strength if trend_state else 0.0,
                bms_count=len(recent_bms),
                last_bms=bms_list[-1] if bms_list else None,
                liquidity_profile=liquidity_profile,
                state_duration_candles=0,
                state_start_timestamp=candles[-1].timestamp,
                last_update_timestamp=candles[-1].timestamp,
                confidence_score=confidence,
            )

            # Update current state
            old_state = self._current_state
            self._current_state = new_state_data
            self._state_history.append(new_state_data)

            # Publish event
            if self.event_bus and old_state:
                self._publish_state_change_event(old_state, new_state_data)

            self.logger.info(
                f"Market state changed: {old_state.state.value if old_state else 'None'} "
                f"-> {new_market_state.value} (confidence={confidence:.1f})"
            )

            return new_state_data

        # No state change, update duration
        if self._current_state:
            self._current_state.state_duration_candles += 1
            self._current_state.last_update_timestamp = candles[-1].timestamp

        return None

    def _determine_market_state(
        self, trend_state: Optional[TrendState], bms_list: List[BreakOfMarketStructure]
    ) -> MarketState:
        """
        Determine market state from trend and BMS data.

        Args:
            trend_state: Current trend state
            bms_list: Recent BMS list

        Returns:
            Determined market state
        """
        if not trend_state:
            return MarketState.RANGING

        # Check for transition
        if trend_state.direction == TrendDirection.TRANSITION:
            return MarketState.TRANSITIONING

        # Check for ranging
        if trend_state.direction == TrendDirection.RANGING:
            return MarketState.RANGING

        # Check trend strength
        if trend_state.strength < self.min_trend_strength:
            return MarketState.RANGING

        # Check BMS confirmation
        if len(bms_list) < self.min_bms_for_confirmation:
            return MarketState.RANGING

        # Determine direction
        if trend_state.direction == TrendDirection.UPTREND:
            # Confirm with bullish BMS
            bullish_bms = [b for b in bms_list if b.bms_type == BMSType.BULLISH]
            if bullish_bms:
                return MarketState.BULLISH

        elif trend_state.direction == TrendDirection.DOWNTREND:
            # Confirm with bearish BMS
            bearish_bms = [b for b in bms_list if b.bms_type == BMSType.BEARISH]
            if bearish_bms:
                return MarketState.BEARISH

        return MarketState.RANGING

    def _calculate_state_confidence(
        self,
        trend_state: Optional[TrendState],
        bms_list: List[BreakOfMarketStructure],
        buy_side_levels: List[LiquidityLevel],
        sell_side_levels: List[LiquidityLevel],
    ) -> float:
        """
        Calculate confidence in current state determination.

        Confidence based on:
        - Trend strength and confirmation
        - BMS quantity and quality
        - Liquidity level alignment

        Args:
            trend_state: Current trend state
            bms_list: Recent BMS
            buy_side_levels: Buy-side liquidity levels
            sell_side_levels: Sell-side liquidity levels

        Returns:
            Confidence score (0-100)
        """
        # Trend confidence (0-40 points)
        if trend_state and trend_state.is_confirmed:
            trend_confidence = trend_state.strength * 0.4
        else:
            trend_confidence = 0

        # BMS confidence (0-35 points)
        if bms_list:
            avg_bms_confidence = sum(b.confidence_score for b in bms_list) / len(bms_list)
            bms_confidence = min(35, avg_bms_confidence * 0.35)
        else:
            bms_confidence = 0

        # Liquidity alignment confidence (0-25 points)
        # Check if liquidity levels align with trend direction
        buy_swept = sum(1 for l in buy_side_levels if l.state == LiquidityState.SWEPT)
        sell_swept = sum(1 for l in sell_side_levels if l.state == LiquidityState.SWEPT)
        total_swept = buy_swept + sell_swept

        if total_swept > 0:
            sweep_ratio = abs(buy_swept - sell_swept) / total_swept
            liquidity_confidence = sweep_ratio * 25
        else:
            liquidity_confidence = 15  # Neutral

        total_confidence = trend_confidence + bms_confidence + liquidity_confidence

        return min(100, max(0, total_confidence))

    def _build_liquidity_profile(
        self, buy_side_levels: List[LiquidityLevel], sell_side_levels: List[LiquidityLevel]
    ) -> Dict[str, Any]:
        """
        Build summary of liquidity levels.

        Args:
            buy_side_levels: Buy-side levels
            sell_side_levels: Sell-side levels

        Returns:
            Liquidity profile dictionary
        """

        def count_by_state(levels: List[LiquidityLevel]) -> Dict[str, int]:
            return {
                "active": sum(1 for l in levels if l.state == LiquidityState.ACTIVE),
                "partial": sum(1 for l in levels if l.state == LiquidityState.PARTIAL),
                "swept": sum(1 for l in levels if l.state == LiquidityState.SWEPT),
            }

        return {
            "buy_side": {
                "total": len(buy_side_levels),
                "by_state": count_by_state(buy_side_levels),
                "avg_strength": (
                    sum(l.strength for l in buy_side_levels) / len(buy_side_levels)
                    if buy_side_levels
                    else 0.0
                ),
            },
            "sell_side": {
                "total": len(sell_side_levels),
                "by_state": count_by_state(sell_side_levels),
                "avg_strength": (
                    sum(l.strength for l in sell_side_levels) / len(sell_side_levels)
                    if sell_side_levels
                    else 0.0
                ),
            },
        }

    def _should_change_state(self, new_state: MarketState, confidence: float) -> bool:
        """
        Check if state should change.

        Args:
            new_state: Proposed new state
            confidence: Confidence in new state

        Returns:
            True if state should change
        """
        # First state
        if self._current_state is None:
            return confidence >= self.min_confidence_for_state

        # Same state
        if self._current_state.state == new_state:
            return False

        # Check confidence threshold
        if confidence < self.min_confidence_for_state:
            return False

        # Check confidence difference
        confidence_diff = confidence - self._current_state.confidence_score
        return confidence_diff >= self.state_change_threshold

    def _publish_state_change_event(
        self, old_state: MarketStateData, new_state: MarketStateData
    ) -> None:
        """
        Publish market state change event.

        Args:
            old_state: Previous state
            new_state: New state
        """
        if not self.event_bus:
            return

        event = Event(
            priority=10,  # Highest priority
            event_type=EventType.MARKET_STRUCTURE_CHANGE,
            timestamp=datetime.now(),
            data={
                "old_state": old_state.to_dict(),
                "new_state": new_state.to_dict(),
                "change_type": "state_change",
            },
            source="MarketStateTracker",
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
            self.logger.error(f"Failed to publish state change event: {e}")

    def get_current_state(self) -> Optional[MarketStateData]:
        """
        Get current market state.

        Returns:
            Current MarketStateData or None
        """
        return self._current_state

    def get_state_history(self, limit: Optional[int] = None) -> List[MarketStateData]:
        """
        Get market state history.

        Args:
            limit: Maximum number of states to return

        Returns:
            List of historical market states
        """
        if limit is None:
            return self._state_history.copy()
        return self._state_history[-limit:]

    def clear_history(self) -> None:
        """Clear state history."""
        self._current_state = None
        self._state_history.clear()
        self.logger.debug("Cleared market state history")
