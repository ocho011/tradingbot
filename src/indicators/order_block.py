"""
Order Block detection and analysis for ICT trading methodology.

This module implements the detection of Order Blocks (OB) using swing high/low
analysis and candlestick patterns. Order Blocks represent institutional trading
zones where significant buying or selling occurred.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.constants import TimeFrame
from src.models.candle import Candle

logger = logging.getLogger(__name__)


class OrderBlockType(str, Enum):
    """Type of Order Block based on direction."""

    BULLISH = "BULLISH"  # Support zone - buying interest
    BEARISH = "BEARISH"  # Resistance zone - selling interest


class OrderBlockState(str, Enum):
    """Current state of an Order Block."""

    ACTIVE = "ACTIVE"  # Currently valid and untested
    TESTED = "TESTED"  # Price has reacted to the block
    BROKEN = "BROKEN"  # Price has broken through the block
    EXPIRED = "EXPIRED"  # Time-based expiration


@dataclass
class OrderBlock:
    """
    Represents an identified Order Block zone.

    Attributes:
        type: Whether this is a bullish (support) or bearish (resistance) block
        high: Upper boundary of the order block zone
        low: Lower boundary of the order block zone
        origin_timestamp: Timestamp when the order block was formed
        origin_candle_index: Index of the candle that formed the order block
        symbol: Trading symbol
        timeframe: Timeframe where the order block was detected
        strength: Strength score (0-100) based on volume and price action
        volume: Volume of the order block formation candle
        state: Current state of the order block
        last_tested_timestamp: Last time price touched this block
        test_count: Number of times price has tested this block
    """

    type: OrderBlockType
    high: float
    low: float
    origin_timestamp: int
    origin_candle_index: int
    symbol: str
    timeframe: TimeFrame
    strength: float
    volume: float
    state: OrderBlockState = OrderBlockState.ACTIVE
    last_tested_timestamp: Optional[int] = None
    test_count: int = 0

    def __post_init__(self):
        """Validate order block data."""
        if self.high <= self.low:
            raise ValueError(f"High ({self.high}) must be greater than low ({self.low})")
        if self.strength < 0 or self.strength > 100:
            raise ValueError(f"Strength must be between 0 and 100, got {self.strength}")
        if self.volume < 0:
            raise ValueError(f"Volume must be non-negative, got {self.volume}")

    def get_range(self) -> float:
        """Get the price range of the order block."""
        return self.high - self.low

    def get_midpoint(self) -> float:
        """Get the midpoint price of the order block."""
        return (self.high + self.low) / 2

    def contains_price(self, price: float) -> bool:
        """
        Check if a price is within the order block zone.

        Args:
            price: Price to check

        Returns:
            True if price is within the block boundaries
        """
        return self.low <= price <= self.high

    def is_price_above(self, price: float) -> bool:
        """Check if price is above the order block."""
        return price > self.high

    def is_price_below(self, price: float) -> bool:
        """Check if price is below the order block."""
        return price < self.low

    def mark_tested(self, timestamp: int) -> None:
        """
        Mark the order block as tested by price.

        Args:
            timestamp: Timestamp when the test occurred
        """
        self.state = OrderBlockState.TESTED
        self.last_tested_timestamp = timestamp
        self.test_count += 1

    def mark_broken(self) -> None:
        """Mark the order block as broken through by price."""
        self.state = OrderBlockState.BROKEN

    def mark_expired(self) -> None:
        """Mark the order block as expired."""
        self.state = OrderBlockState.EXPIRED

    def to_dict(self) -> Dict[str, Any]:
        """Convert order block to dictionary."""
        return {
            "type": self.type.value,
            "high": self.high,
            "low": self.low,
            "origin_timestamp": self.origin_timestamp,
            "origin_datetime": datetime.fromtimestamp(self.origin_timestamp / 1000).isoformat(),
            "origin_candle_index": self.origin_candle_index,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "strength": self.strength,
            "volume": self.volume,
            "state": self.state.value,
            "last_tested_timestamp": self.last_tested_timestamp,
            "last_tested_datetime": (
                datetime.fromtimestamp(self.last_tested_timestamp / 1000).isoformat()
                if self.last_tested_timestamp
                else None
            ),
            "test_count": self.test_count,
            "range": self.get_range(),
            "midpoint": self.get_midpoint(),
        }

    def __repr__(self) -> str:
        """String representation of order block."""
        return (
            f"OrderBlock(type={self.type.value}, "
            f"range=[{self.low:.2f}-{self.high:.2f}], "
            f"strength={self.strength:.1f}, "
            f"state={self.state.value}, "
            f"tests={self.test_count})"
        )


@dataclass
class SwingPoint:
    """
    Represents a swing high or swing low point.

    Attributes:
        price: Price at the swing point
        timestamp: Timestamp of the swing point
        candle_index: Index of the candle forming the swing point
        is_high: True for swing high, False for swing low
        strength: Strength of the swing point (number of lower/higher candles on each side)
    """

    price: float
    timestamp: int
    candle_index: int
    is_high: bool
    strength: int = 1


class OrderBlockDetector:
    """
    Detects Order Blocks from candlestick data using swing high/low analysis.

    Order Blocks are formed at the last candle before a strong move away from
    a swing high or swing low. The detector identifies these zones where
    institutional orders likely accumulated.
    """

    def __init__(
        self,
        min_swing_strength: int = 2,
        min_candles_for_ob: int = 3,
        max_candles_for_ob: int = 5,
        volume_multiplier_threshold: float = 1.2,
    ):
        """
        Initialize Order Block detector.

        Args:
            min_swing_strength: Minimum number of candles on each side for swing detection
            min_candles_for_ob: Minimum candles required in historical data
            max_candles_for_ob: Maximum lookback for order block formation
            volume_multiplier_threshold: Minimum volume multiplier for strong blocks
        """
        self.min_swing_strength = min_swing_strength
        self.min_candles_for_ob = min_candles_for_ob
        self.max_candles_for_ob = max_candles_for_ob
        self.volume_multiplier_threshold = volume_multiplier_threshold
        self.logger = logging.getLogger(f"{__name__}.OrderBlockDetector")

    def detect_swing_highs(self, candles: List[Candle], lookback: int = 5) -> List[SwingPoint]:
        """
        Detect swing high points in candle data.

        A swing high is a candle whose high is higher than the highs of
        'lookback' candles before and after it.

        Args:
            candles: List of candles to analyze
            lookback: Number of candles to check on each side

        Returns:
            List of detected swing high points
        """
        if len(candles) < (lookback * 2 + 1):
            return []

        swing_highs = []

        for i in range(lookback, len(candles) - lookback):
            current_high = candles[i].high

            # Check if this is higher than all previous lookback candles
            is_swing_high = all(current_high > candles[j].high for j in range(i - lookback, i))

            # Check if this is higher than all following lookback candles
            if is_swing_high:
                is_swing_high = all(
                    current_high > candles[j].high for j in range(i + 1, i + lookback + 1)
                )

            if is_swing_high:
                swing_highs.append(
                    SwingPoint(
                        price=current_high,
                        timestamp=candles[i].timestamp,
                        candle_index=i,
                        is_high=True,
                        strength=lookback,
                    )
                )
                self.logger.debug(
                    f"Swing high detected at index {i}: "
                    f"price={current_high:.2f}, time={candles[i].get_datetime_iso()}"
                )

        return swing_highs

    def detect_swing_lows(self, candles: List[Candle], lookback: int = 5) -> List[SwingPoint]:
        """
        Detect swing low points in candle data.

        A swing low is a candle whose low is lower than the lows of
        'lookback' candles before and after it.

        Args:
            candles: List of candles to analyze
            lookback: Number of candles to check on each side

        Returns:
            List of detected swing low points
        """
        if len(candles) < (lookback * 2 + 1):
            return []

        swing_lows = []

        for i in range(lookback, len(candles) - lookback):
            current_low = candles[i].low

            # Check if this is lower than all previous lookback candles
            is_swing_low = all(current_low < candles[j].low for j in range(i - lookback, i))

            # Check if this is lower than all following lookback candles
            if is_swing_low:
                is_swing_low = all(
                    current_low < candles[j].low for j in range(i + 1, i + lookback + 1)
                )

            if is_swing_low:
                swing_lows.append(
                    SwingPoint(
                        price=current_low,
                        timestamp=candles[i].timestamp,
                        candle_index=i,
                        is_high=False,
                        strength=lookback,
                    )
                )
                self.logger.debug(
                    f"Swing low detected at index {i}: "
                    f"price={current_low:.2f}, time={candles[i].get_datetime_iso()}"
                )

        return swing_lows

    def calculate_order_block_strength(
        self, ob_candle: Candle, candles: List[Candle], ob_candle_index: int
    ) -> float:
        """
        Calculate strength score for an order block.

        Strength is based on:
        - Volume relative to recent average
        - Body size relative to total range
        - Proximity to swing point

        Args:
            ob_candle: The candle forming the order block
            candles: Full list of candles for context
            ob_candle_index: Index of the OB candle

        Returns:
            Strength score between 0 and 100
        """
        # Calculate average volume of recent candles
        lookback_vol = min(20, ob_candle_index)
        if lookback_vol == 0:
            avg_volume = ob_candle.volume
        else:
            recent_candles = candles[max(0, ob_candle_index - lookback_vol) : ob_candle_index]
            avg_volume = sum(c.volume for c in recent_candles) / len(recent_candles)

        # Volume factor (0-40 points)
        volume_ratio = ob_candle.volume / avg_volume if avg_volume > 0 else 1.0
        volume_score = min(40, volume_ratio * 20)

        # Body size factor (0-30 points)
        total_range = ob_candle.get_total_range()
        if total_range > 0:
            body_ratio = ob_candle.get_body_size() / total_range
            body_score = body_ratio * 30
        else:
            body_score = 0

        # Wick factor - prefer candles with small wicks (0-30 points)
        if total_range > 0:
            upper_wick_ratio = ob_candle.get_upper_wick() / total_range
            lower_wick_ratio = ob_candle.get_lower_wick() / total_range
            wick_score = 30 * (1 - (upper_wick_ratio + lower_wick_ratio) / 2)
        else:
            wick_score = 0

        total_score = volume_score + body_score + wick_score
        return min(100, max(0, total_score))

    def detect_bullish_order_blocks(
        self, candles: List[Candle], swing_lows: List[SwingPoint]
    ) -> List[OrderBlock]:
        """
        Detect bullish (support) order blocks.

        Bullish OBs form at the last down candle before a strong move up from a swing low.

        Args:
            candles: List of candles to analyze
            swing_lows: Detected swing low points

        Returns:
            List of detected bullish order blocks
        """
        order_blocks = []

        for swing_low in swing_lows:
            swing_idx = swing_low.candle_index

            # Look for the last bearish candle before the swing low
            # within the max_candles_for_ob window
            for i in range(max(0, swing_idx - self.max_candles_for_ob), swing_idx):
                candle = candles[i]

                # Must be a bearish candle (or at least not bullish)
                if not candle.is_bullish():
                    # Verify there's a strong move up after this candle
                    # Check if price moved significantly above this candle
                    if swing_idx < len(candles) - 1:
                        move_up_confirmed = any(
                            c.close > candle.high
                            for c in candles[i + 1 : min(len(candles), swing_idx + 3)]
                        )

                        if move_up_confirmed:
                            strength = self.calculate_order_block_strength(candle, candles, i)

                            ob = OrderBlock(
                                type=OrderBlockType.BULLISH,
                                high=candle.high,
                                low=candle.low,
                                origin_timestamp=candle.timestamp,
                                origin_candle_index=i,
                                symbol=candle.symbol,
                                timeframe=candle.timeframe,
                                strength=strength,
                                volume=candle.volume,
                            )

                            order_blocks.append(ob)
                            self.logger.debug(f"Bullish OB detected: {ob}")
                            break  # Found the OB for this swing low

        return order_blocks

    def detect_bearish_order_blocks(
        self, candles: List[Candle], swing_highs: List[SwingPoint]
    ) -> List[OrderBlock]:
        """
        Detect bearish (resistance) order blocks.

        Bearish OBs form at the last up candle before a strong move down from a swing high.

        Args:
            candles: List of candles to analyze
            swing_highs: Detected swing high points

        Returns:
            List of detected bearish order blocks
        """
        order_blocks = []

        for swing_high in swing_highs:
            swing_idx = swing_high.candle_index

            # Look for the last bullish candle before the swing high
            # within the max_candles_for_ob window
            for i in range(max(0, swing_idx - self.max_candles_for_ob), swing_idx):
                candle = candles[i]

                # Must be a bullish candle
                if candle.is_bullish():
                    # Verify there's a strong move down after this candle
                    if swing_idx < len(candles) - 1:
                        move_down_confirmed = any(
                            c.close < candle.low
                            for c in candles[i + 1 : min(len(candles), swing_idx + 3)]
                        )

                        if move_down_confirmed:
                            strength = self.calculate_order_block_strength(candle, candles, i)

                            ob = OrderBlock(
                                type=OrderBlockType.BEARISH,
                                high=candle.high,
                                low=candle.low,
                                origin_timestamp=candle.timestamp,
                                origin_candle_index=i,
                                symbol=candle.symbol,
                                timeframe=candle.timeframe,
                                strength=strength,
                                volume=candle.volume,
                            )

                            order_blocks.append(ob)
                            self.logger.debug(f"Bearish OB detected: {ob}")
                            break  # Found the OB for this swing high

        return order_blocks

    def detect_order_blocks(self, candles: List[Candle]) -> List[OrderBlock]:
        """
        Detect all order blocks (both bullish and bearish) from candle data.

        Args:
            candles: List of candles to analyze (must be in chronological order)

        Returns:
            List of detected order blocks, sorted by timestamp

        Raises:
            ValueError: If insufficient candles provided
        """
        if len(candles) < self.min_candles_for_ob:
            raise ValueError(
                f"Insufficient candles for order block detection. "
                f"Need at least {self.min_candles_for_ob}, got {len(candles)}"
            )

        self.logger.info(
            f"Detecting order blocks in {len(candles)} candles "
            f"({candles[0].symbol}, {candles[0].timeframe.value})"
        )

        # Detect swing points
        swing_highs = self.detect_swing_highs(candles, self.min_swing_strength)
        swing_lows = self.detect_swing_lows(candles, self.min_swing_strength)

        self.logger.info(f"Found {len(swing_highs)} swing highs and {len(swing_lows)} swing lows")

        # Detect order blocks
        bullish_obs = self.detect_bullish_order_blocks(candles, swing_lows)
        bearish_obs = self.detect_bearish_order_blocks(candles, swing_highs)

        all_obs = bullish_obs + bearish_obs
        all_obs.sort(key=lambda ob: ob.origin_timestamp)

        self.logger.info(
            f"Detected {len(bullish_obs)} bullish and {len(bearish_obs)} bearish order blocks"
        )

        return all_obs

    def update_config(self, config: Dict[str, Any]) -> None:
        """
        Update detector configuration dynamically.

        Args:
            config: New configuration dictionary
        """
        # Handle direct parameter updates
        if "min_swing_strength" in config:
            self.min_swing_strength = int(config["min_swing_strength"])
        if "min_candles_for_ob" in config:
            self.min_candles_for_ob = int(config["min_candles_for_ob"])
        if "max_candles_for_ob" in config:
            self.max_candles_for_ob = int(config["max_candles_for_ob"])
        if "volume_multiplier_threshold" in config:
            self.volume_multiplier_threshold = float(config["volume_multiplier_threshold"])

        # Handle ICT specific config keys from UI
        if "ob_lookback_periods" in config:
            # Map ob_lookback_periods to max_candles_for_ob
            self.max_candles_for_ob = int(config["ob_lookback_periods"])
            self.logger.info(f"Updated max_candles_for_ob to {self.max_candles_for_ob}")
