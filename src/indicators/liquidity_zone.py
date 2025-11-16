"""
Liquidity Zone detection and analysis for ICT trading methodology.

This module implements Buy-Side and Sell-Side Liquidity Level identification
based on swing highs and lows. Liquidity zones represent areas where stop losses
and pending orders accumulate, often becoming targets for institutional traders.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.core.constants import TimeFrame
from src.models.candle import Candle

logger = logging.getLogger(__name__)


class LiquidityType(str, Enum):
    """Type of liquidity based on location."""

    BUY_SIDE = "BUY_SIDE"  # Liquidity above swing highs (sell stops, buy limits)
    SELL_SIDE = "SELL_SIDE"  # Liquidity below swing lows (buy stops, sell limits)


class LiquidityState(str, Enum):
    """Current state of a liquidity level."""

    ACTIVE = "ACTIVE"  # Currently valid and untouched
    SWEPT = "SWEPT"  # Price has swept through the level
    PARTIAL = "PARTIAL"  # Price has touched but not fully swept
    EXPIRED = "EXPIRED"  # Time-based expiration


@dataclass
class LiquidityLevel:
    """
    Represents an identified Liquidity Level/Zone.

    Liquidity accumulates at key levels where traders place stop losses
    and pending orders. In ICT methodology:
    - Buy-Side Liquidity: Above swing highs (stops from shorts, buy limit orders)
    - Sell-Side Liquidity: Below swing lows (stops from longs, sell limit orders)

    Attributes:
        type: Buy-side (above highs) or Sell-side (below lows)
        price: Price level where liquidity accumulates
        origin_timestamp: When the swing point was formed
        origin_candle_index: Index of the swing candle
        symbol: Trading symbol
        timeframe: Timeframe where detected
        touch_count: Number of times price approached this level
        strength: Strength score based on swing significance and touches
        volume_profile: Average volume near this level
        state: Current state of the liquidity level
        last_touch_timestamp: Most recent approach to this level
        swept_timestamp: When the level was swept (if applicable)
    """

    type: LiquidityType
    price: float
    origin_timestamp: int
    origin_candle_index: int
    symbol: str
    timeframe: TimeFrame
    touch_count: int = 0
    strength: float = 0.0
    volume_profile: float = 0.0
    state: LiquidityState = LiquidityState.ACTIVE
    last_touch_timestamp: Optional[int] = None
    swept_timestamp: Optional[int] = None

    def __post_init__(self):
        """Validate liquidity level data."""
        if self.price <= 0:
            raise ValueError(f"Price must be positive, got {self.price}")
        if self.strength < 0 or self.strength > 100:
            raise ValueError(f"Strength must be between 0 and 100, got {self.strength}")
        if self.touch_count < 0:
            raise ValueError(f"Touch count must be non-negative, got {self.touch_count}")
        if self.volume_profile < 0:
            raise ValueError(f"Volume profile must be non-negative, got {self.volume_profile}")

    def is_price_near(
        self, price: float, tolerance_pips: float = 2.0, pip_size: float = 0.0001
    ) -> bool:
        """
        Check if a price is near this liquidity level.

        Args:
            price: Price to check
            tolerance_pips: Tolerance in pips for "near" determination
            pip_size: Size of one pip for the symbol

        Returns:
            True if price is within tolerance of the level
        """
        tolerance = tolerance_pips * pip_size
        return abs(price - self.price) <= tolerance

    def mark_touched(self, timestamp: int) -> None:
        """
        Mark the level as touched by price.

        Args:
            timestamp: Timestamp when the touch occurred
        """
        self.touch_count += 1
        self.last_touch_timestamp = timestamp
        if self.state == LiquidityState.ACTIVE:
            self.state = LiquidityState.PARTIAL

    def mark_swept(self, timestamp: int) -> None:
        """
        Mark the level as swept by price.

        Args:
            timestamp: Timestamp when the sweep occurred
        """
        self.state = LiquidityState.SWEPT
        self.swept_timestamp = timestamp

    def mark_expired(self) -> None:
        """Mark the level as expired."""
        self.state = LiquidityState.EXPIRED

    def to_dict(self) -> Dict[str, Any]:
        """Convert liquidity level to dictionary."""
        return {
            "type": self.type.value,
            "price": self.price,
            "origin_timestamp": self.origin_timestamp,
            "origin_datetime": datetime.fromtimestamp(self.origin_timestamp / 1000).isoformat(),
            "origin_candle_index": self.origin_candle_index,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "touch_count": self.touch_count,
            "strength": self.strength,
            "volume_profile": self.volume_profile,
            "state": self.state.value,
            "last_touch_timestamp": self.last_touch_timestamp,
            "last_touch_datetime": (
                datetime.fromtimestamp(self.last_touch_timestamp / 1000).isoformat()
                if self.last_touch_timestamp
                else None
            ),
            "swept_timestamp": self.swept_timestamp,
            "swept_datetime": (
                datetime.fromtimestamp(self.swept_timestamp / 1000).isoformat()
                if self.swept_timestamp
                else None
            ),
        }

    def __repr__(self) -> str:
        """String representation of liquidity level."""
        return (
            f"LiquidityLevel(type={self.type.value}, "
            f"price={self.price:.2f}, "
            f"touches={self.touch_count}, "
            f"strength={self.strength:.1f}, "
            f"state={self.state.value})"
        )


@dataclass
class SwingPoint:
    """
    Represents a swing high or swing low point for liquidity identification.

    Attributes:
        price: Price at the swing point
        timestamp: Timestamp of the swing point
        candle_index: Index of the candle forming the swing point
        is_high: True for swing high, False for swing low
        strength: Number of candles confirming the swing
        volume: Volume at the swing candle
    """

    price: float
    timestamp: int
    candle_index: int
    is_high: bool
    strength: int = 1
    volume: float = 0.0


class LiquidityZoneDetector:
    """
    Detects Buy-Side and Sell-Side Liquidity Levels from candlestick data.

    The detector identifies swing highs and lows, which represent areas where
    liquidity accumulates due to stop losses and pending orders.

    Key Concepts:
    - Buy-Side Liquidity: Above swing highs (attracts price upward sweeps)
    - Sell-Side Liquidity: Below swing lows (attracts price downward sweeps)
    """

    def __init__(
        self,
        min_swing_strength: int = 3,
        proximity_tolerance_pips: float = 2.0,
        min_touches_for_strong: int = 2,
        pip_size: float = 0.0001,
        volume_lookback: int = 20,
    ):
        """
        Initialize Liquidity Zone detector.

        Args:
            min_swing_strength: Minimum candles on each side for swing detection
            proximity_tolerance_pips: Pips tolerance for level clustering
            min_touches_for_strong: Minimum touches to classify as strong liquidity
            pip_size: Size of one pip for the symbol (0.0001 for most forex, 0.01 for JPY)
            volume_lookback: Number of candles for volume profile calculation
        """
        self.min_swing_strength = min_swing_strength
        self.proximity_tolerance_pips = proximity_tolerance_pips
        self.min_touches_for_strong = min_touches_for_strong
        self.pip_size = pip_size
        self.volume_lookback = volume_lookback
        self.logger = logging.getLogger(f"{__name__}.LiquidityZoneDetector")

    def detect_swing_highs(
        self, candles: List[Candle], lookback: Optional[int] = None
    ) -> List[SwingPoint]:
        """
        Detect swing high points in candle data.

        A swing high is a candle whose high is higher than the highs of
        surrounding candles.

        Args:
            candles: List of candles to analyze
            lookback: Number of candles to check on each side (uses min_swing_strength if None)

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

            # Check if this is higher than all previous lookback candles
            is_swing_high = all(current_high > candles[j].high for j in range(i - lookback, i))

            # Check if this is higher than all following lookback candles
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
                self.logger.debug(
                    f"Swing high detected at index {i}: "
                    f"price={current_high:.5f}, time={candles[i].get_datetime_iso()}"
                )

        return swing_highs

    def detect_swing_lows(
        self, candles: List[Candle], lookback: Optional[int] = None
    ) -> List[SwingPoint]:
        """
        Detect swing low points in candle data.

        A swing low is a candle whose low is lower than the lows of
        surrounding candles.

        Args:
            candles: List of candles to analyze
            lookback: Number of candles to check on each side (uses min_swing_strength if None)

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

            # Check if this is lower than all previous lookback candles
            is_swing_low = all(current_low < candles[j].low for j in range(i - lookback, i))

            # Check if this is lower than all following lookback candles
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
                self.logger.debug(
                    f"Swing low detected at index {i}: "
                    f"price={current_low:.5f}, time={candles[i].get_datetime_iso()}"
                )

        return swing_lows

    def calculate_volume_profile(self, candles: List[Candle], center_index: int) -> float:
        """
        Calculate average volume around a liquidity level.

        Args:
            candles: List of candles
            center_index: Index of the swing point

        Returns:
            Average volume in the surrounding area
        """
        start_idx = max(0, center_index - self.volume_lookback // 2)
        end_idx = min(len(candles), center_index + self.volume_lookback // 2)

        relevant_candles = candles[start_idx:end_idx]
        if not relevant_candles:
            return 0.0

        return sum(c.volume for c in relevant_candles) / len(relevant_candles)

    def calculate_liquidity_strength(
        self, swing_point: SwingPoint, candles: List[Candle], touch_count: int = 0
    ) -> float:
        """
        Calculate strength score for a liquidity level.

        Strength is based on:
        - Swing strength (confirmation candles)
        - Touch count (more touches = stronger level)
        - Volume at the swing point
        - Proximity to recent price action

        Args:
            swing_point: The swing point forming the liquidity level
            candles: Full list of candles for context
            touch_count: Number of times price has touched this level

        Returns:
            Strength score between 0 and 100
        """
        # Swing strength factor (0-30 points)
        max_swing_strength = 10
        swing_score = min(30, (swing_point.strength / max_swing_strength) * 30)

        # Touch count factor (0-40 points)
        touch_score = min(40, touch_count * 10)

        # Volume factor (0-30 points)
        volume_profile = self.calculate_volume_profile(candles, swing_point.candle_index)
        avg_volume = sum(c.volume for c in candles) / len(candles) if candles else 1.0
        volume_ratio = (
            (swing_point.volume + volume_profile) / (2 * avg_volume) if avg_volume > 0 else 1.0
        )
        volume_score = min(30, volume_ratio * 15)

        total_score = swing_score + touch_score + volume_score
        return min(100, max(0, total_score))

    def cluster_nearby_levels(self, levels: List[LiquidityLevel]) -> List[LiquidityLevel]:
        """
        Cluster nearby liquidity levels into single stronger levels.

        When multiple swing points are very close together, they represent
        a stronger cumulative liquidity zone.

        Args:
            levels: List of liquidity levels to cluster

        Returns:
            Clustered list with combined strength for nearby levels
        """
        if not levels:
            return []

        # Sort by price
        sorted_levels = sorted(levels, key=lambda l: l.price)
        clustered = []

        current_cluster = [sorted_levels[0]]
        tolerance = self.proximity_tolerance_pips * self.pip_size

        for level in sorted_levels[1:]:
            # Check if this level is close to the current cluster
            cluster_price = sum(l.price for l in current_cluster) / len(current_cluster)

            if abs(level.price - cluster_price) <= tolerance:
                # Add to current cluster
                current_cluster.append(level)
            else:
                # Finalize current cluster and start new one
                clustered.append(self._merge_cluster(current_cluster))
                current_cluster = [level]

        # Don't forget the last cluster
        if current_cluster:
            clustered.append(self._merge_cluster(current_cluster))

        return clustered

    def _merge_cluster(self, cluster: List[LiquidityLevel]) -> LiquidityLevel:
        """
        Merge multiple nearby levels into one stronger level.

        Args:
            cluster: List of nearby liquidity levels

        Returns:
            Single merged liquidity level with combined attributes
        """
        if len(cluster) == 1:
            return cluster[0]

        # Use the strongest level as base
        base_level = max(cluster, key=lambda l: l.strength)

        # Calculate weighted average price
        total_strength = sum(l.strength for l in cluster)
        if total_strength > 0:
            weighted_price = sum(l.price * l.strength for l in cluster) / total_strength
        else:
            weighted_price = sum(l.price for l in cluster) / len(cluster)

        # Combine touch counts
        total_touches = sum(l.touch_count for l in cluster)

        # Combine strengths (with diminishing returns)
        combined_strength = min(
            100, base_level.strength + sum(l.strength * 0.3 for l in cluster if l != base_level)
        )

        # Use earliest timestamp
        earliest_timestamp = min(l.origin_timestamp for l in cluster)
        earliest_level = next(l for l in cluster if l.origin_timestamp == earliest_timestamp)

        return LiquidityLevel(
            type=base_level.type,
            price=weighted_price,
            origin_timestamp=earliest_timestamp,
            origin_candle_index=earliest_level.origin_candle_index,
            symbol=base_level.symbol,
            timeframe=base_level.timeframe,
            touch_count=total_touches,
            strength=combined_strength,
            volume_profile=max(l.volume_profile for l in cluster),
            state=base_level.state,
            last_touch_timestamp=max(
                (l.last_touch_timestamp for l in cluster if l.last_touch_timestamp), default=None
            ),
            swept_timestamp=None,
        )

    def detect_liquidity_levels(
        self, candles: List[Candle]
    ) -> Tuple[List[LiquidityLevel], List[LiquidityLevel]]:
        """
        Detect all liquidity levels (both buy-side and sell-side) from candle data.

        Args:
            candles: List of candles to analyze (must be in chronological order)

        Returns:
            Tuple of (buy_side_levels, sell_side_levels)

        Raises:
            ValueError: If insufficient candles provided
        """
        min_candles = self.min_swing_strength * 2 + 1
        if len(candles) < min_candles:
            raise ValueError(
                f"Insufficient candles for liquidity detection. "
                f"Need at least {min_candles}, got {len(candles)}"
            )

        self.logger.info(
            f"Detecting liquidity levels in {len(candles)} candles "
            f"({candles[0].symbol}, {candles[0].timeframe.value})"
        )

        # Detect swing points
        swing_highs = self.detect_swing_highs(candles)
        swing_lows = self.detect_swing_lows(candles)

        self.logger.info(f"Found {len(swing_highs)} swing highs and {len(swing_lows)} swing lows")

        # Convert swing highs to buy-side liquidity (above highs)
        buy_side_levels = []
        for swing_high in swing_highs:
            strength = self.calculate_liquidity_strength(swing_high, candles)
            volume_profile = self.calculate_volume_profile(candles, swing_high.candle_index)

            level = LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=swing_high.price,
                origin_timestamp=swing_high.timestamp,
                origin_candle_index=swing_high.candle_index,
                symbol=candles[0].symbol,
                timeframe=candles[0].timeframe,
                strength=strength,
                volume_profile=volume_profile,
            )
            buy_side_levels.append(level)

        # Convert swing lows to sell-side liquidity (below lows)
        sell_side_levels = []
        for swing_low in swing_lows:
            strength = self.calculate_liquidity_strength(swing_low, candles)
            volume_profile = self.calculate_volume_profile(candles, swing_low.candle_index)

            level = LiquidityLevel(
                type=LiquidityType.SELL_SIDE,
                price=swing_low.price,
                origin_timestamp=swing_low.timestamp,
                origin_candle_index=swing_low.candle_index,
                symbol=candles[0].symbol,
                timeframe=candles[0].timeframe,
                strength=strength,
                volume_profile=volume_profile,
            )
            sell_side_levels.append(level)

        # Cluster nearby levels
        buy_side_levels = self.cluster_nearby_levels(buy_side_levels)
        sell_side_levels = self.cluster_nearby_levels(sell_side_levels)

        self.logger.info(
            f"Detected {len(buy_side_levels)} buy-side and {len(sell_side_levels)} sell-side liquidity levels "
            f"(after clustering)"
        )

        return buy_side_levels, sell_side_levels

    def update_liquidity_states(
        self,
        buy_side_levels: List[LiquidityLevel],
        sell_side_levels: List[LiquidityLevel],
        candles: List[Candle],
        start_index: int = 0,
    ) -> None:
        """
        Update the state of liquidity levels based on price action.

        Tracks touches and sweeps of liquidity levels.

        Args:
            buy_side_levels: List of buy-side liquidity levels
            sell_side_levels: List of sell-side liquidity levels
            candles: Candle data for state updates
            start_index: Starting index for updates
        """
        all_levels = buy_side_levels + sell_side_levels
        active_levels = [
            l for l in all_levels if l.state in (LiquidityState.ACTIVE, LiquidityState.PARTIAL)
        ]

        for i in range(start_index, len(candles)):
            candle = candles[i]

            for level in active_levels:
                # Skip if level was formed after this candle
                if level.origin_candle_index >= i:
                    continue

                # Check for touches and sweeps
                if level.type == LiquidityType.BUY_SIDE:
                    # Buy-side liquidity above highs - check if price swept up through it
                    if candle.high >= level.price:
                        # Check if it's a full sweep (close above) or just a touch
                        if candle.close > level.price:
                            level.mark_swept(candle.timestamp)
                            self.logger.debug(
                                f"Buy-side liquidity swept at index {i}: "
                                f"level={level.price:.5f}, high={candle.high:.5f}"
                            )
                        else:
                            level.mark_touched(candle.timestamp)

                else:  # SELL_SIDE
                    # Sell-side liquidity below lows - check if price swept down through it
                    if candle.low <= level.price:
                        # Check if it's a full sweep (close below) or just a touch
                        if candle.close < level.price:
                            level.mark_swept(candle.timestamp)
                            self.logger.debug(
                                f"Sell-side liquidity swept at index {i}: "
                                f"level={level.price:.5f}, low={candle.low:.5f}"
                            )
                        else:
                            level.mark_touched(candle.timestamp)
