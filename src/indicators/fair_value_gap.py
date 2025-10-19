"""
Fair Value Gap (FVG) detection and analysis for ICT trading methodology.

This module implements the detection of Fair Value Gaps using 3-candle pattern
analysis. FVGs represent price imbalances that may attract price back to fill them,
serving as potential support/resistance zones and continuation signals.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import logging

from src.models.candle import Candle
from src.core.constants import TimeFrame


logger = logging.getLogger(__name__)


class FVGType(str, Enum):
    """Type of Fair Value Gap based on direction."""
    BULLISH = "BULLISH"  # Gap formed during upward movement
    BEARISH = "BEARISH"  # Gap formed during downward movement


class FVGState(str, Enum):
    """Current state of a Fair Value Gap."""
    ACTIVE = "ACTIVE"        # Currently valid and unfilled
    PARTIAL = "PARTIAL"      # Partially filled
    FILLED = "FILLED"        # Completely filled
    EXPIRED = "EXPIRED"      # Time-based expiration


@dataclass
class FairValueGap:
    """
    Represents an identified Fair Value Gap.

    A FVG forms when price moves aggressively, leaving a gap between consecutive
    candles that represents an imbalance in supply/demand.

    Attributes:
        type: Whether this is a bullish or bearish gap
        high: Upper boundary of the gap zone
        low: Lower boundary of the gap zone
        origin_timestamp: Timestamp when the gap was formed (middle candle)
        origin_candle_index: Index of the middle candle that created the gap
        symbol: Trading symbol
        timeframe: Timeframe where the gap was detected
        size_pips: Size of the gap in pips/points
        size_percentage: Size of the gap as percentage of price
        volume: Volume of the middle candle that created the gap
        state: Current state of the gap
        filled_percentage: Percentage of gap that has been filled (0-100)
        first_fill_timestamp: First time price entered the gap
    """

    type: FVGType
    high: float
    low: float
    origin_timestamp: int
    origin_candle_index: int
    symbol: str
    timeframe: TimeFrame
    size_pips: float
    size_percentage: float
    volume: float
    state: FVGState = FVGState.ACTIVE
    filled_percentage: float = 0.0
    first_fill_timestamp: Optional[int] = None

    def __post_init__(self):
        """Validate Fair Value Gap data."""
        if self.high <= self.low:
            raise ValueError(f"High ({self.high}) must be greater than low ({self.low})")
        if self.size_pips < 0:
            raise ValueError(f"Size pips must be non-negative, got {self.size_pips}")
        if self.size_percentage < 0:
            raise ValueError(f"Size percentage must be non-negative, got {self.size_percentage}")
        if not (0 <= self.filled_percentage <= 100):
            raise ValueError(f"Filled percentage must be between 0 and 100, got {self.filled_percentage}")
        if self.volume < 0:
            raise ValueError(f"Volume must be non-negative, got {self.volume}")

    def get_range(self) -> float:
        """Get the price range of the gap."""
        return self.high - self.low

    def get_midpoint(self) -> float:
        """Get the midpoint price of the gap."""
        return (self.high + self.low) / 2

    def contains_price(self, price: float) -> bool:
        """
        Check if a price is within the gap zone.

        Args:
            price: Price to check

        Returns:
            True if price is within the gap boundaries
        """
        return self.low <= price <= self.high

    def is_price_above(self, price: float) -> bool:
        """Check if price is above the gap."""
        return price > self.high

    def is_price_below(self, price: float) -> bool:
        """Check if price is below the gap."""
        return price < self.low

    def update_fill_status(self, current_price: float, timestamp: int) -> None:
        """
        Update the fill status of the gap based on current price.

        Args:
            current_price: Current market price
            timestamp: Current timestamp
        """
        if not self.contains_price(current_price):
            return

        # Record first fill
        if self.first_fill_timestamp is None:
            self.first_fill_timestamp = timestamp

        # Calculate fill percentage based on how deep price has penetrated
        gap_range = self.get_range()
        if gap_range == 0:
            self.filled_percentage = 100.0
            self.state = FVGState.FILLED
            return

        if self.type == FVGType.BULLISH:
            # For bullish FVG, measure from bottom
            fill_depth = current_price - self.low
        else:
            # For bearish FVG, measure from top
            fill_depth = self.high - current_price

        self.filled_percentage = min(100.0, (fill_depth / gap_range) * 100)

        # Update state based on fill percentage
        if self.filled_percentage >= 100:
            self.state = FVGState.FILLED
        elif self.filled_percentage > 0:
            self.state = FVGState.PARTIAL
        else:
            self.state = FVGState.ACTIVE

    def mark_expired(self) -> None:
        """Mark the gap as expired."""
        self.state = FVGState.EXPIRED

    def to_dict(self) -> Dict[str, Any]:
        """Convert Fair Value Gap to dictionary."""
        return {
            'type': self.type.value,
            'high': self.high,
            'low': self.low,
            'origin_timestamp': self.origin_timestamp,
            'origin_datetime': datetime.fromtimestamp(self.origin_timestamp / 1000).isoformat(),
            'origin_candle_index': self.origin_candle_index,
            'symbol': self.symbol,
            'timeframe': self.timeframe.value,
            'size_pips': self.size_pips,
            'size_percentage': self.size_percentage,
            'volume': self.volume,
            'state': self.state.value,
            'filled_percentage': self.filled_percentage,
            'first_fill_timestamp': self.first_fill_timestamp,
            'first_fill_datetime': (
                datetime.fromtimestamp(self.first_fill_timestamp / 1000).isoformat()
                if self.first_fill_timestamp else None
            ),
            'range': self.get_range(),
            'midpoint': self.get_midpoint()
        }

    def __repr__(self) -> str:
        """String representation of Fair Value Gap."""
        return (
            f"FairValueGap(type={self.type.value}, "
            f"range=[{self.low:.2f}-{self.high:.2f}], "
            f"size={self.size_pips:.2f}pips, "
            f"state={self.state.value}, "
            f"filled={self.filled_percentage:.1f}%)"
        )


class FVGDetector:
    """
    Detects Fair Value Gaps from candlestick data using 3-candle pattern analysis.

    A Fair Value Gap forms when:
    - Bullish FVG: candle[0].high < candle[2].low (gap between candle 0's high and candle 2's low)
    - Bearish FVG: candle[0].low > candle[2].high (gap between candle 0's low and candle 2's high)

    The middle candle (candle[1]) creates the gap with strong directional movement.
    """

    def __init__(
        self,
        min_gap_size_pips: float = 0.0,
        min_gap_size_percentage: float = 0.0,
        use_pip_threshold: bool = True,
        pip_size: float = 0.0001  # Default for forex (0.01 for JPY pairs)
    ):
        """
        Initialize Fair Value Gap detector.

        Args:
            min_gap_size_pips: Minimum gap size in pips for filtering (0 = no filter)
            min_gap_size_percentage: Minimum gap size as percentage for filtering (0 = no filter)
            use_pip_threshold: If True, use pip threshold; if False, use percentage threshold
            pip_size: Size of one pip for the symbol (0.0001 for most forex, 0.01 for JPY pairs)
        """
        self.min_gap_size_pips = min_gap_size_pips
        self.min_gap_size_percentage = min_gap_size_percentage
        self.use_pip_threshold = use_pip_threshold
        self.pip_size = pip_size
        self.logger = logging.getLogger(f"{__name__}.FVGDetector")

    def calculate_gap_size(
        self,
        gap_high: float,
        gap_low: float,
        reference_price: float
    ) -> tuple[float, float]:
        """
        Calculate gap size in both pips and percentage.

        Args:
            gap_high: Upper boundary of the gap
            gap_low: Lower boundary of the gap
            reference_price: Reference price for percentage calculation

        Returns:
            Tuple of (size_in_pips, size_in_percentage)
        """
        gap_range = gap_high - gap_low
        size_pips = gap_range / self.pip_size if self.pip_size > 0 else 0
        size_percentage = (gap_range / reference_price * 100) if reference_price > 0 else 0

        return size_pips, size_percentage

    def meets_threshold(self, size_pips: float, size_percentage: float) -> bool:
        """
        Check if gap size meets the configured threshold.

        Args:
            size_pips: Gap size in pips
            size_percentage: Gap size as percentage

        Returns:
            True if gap meets threshold criteria
        """
        if self.use_pip_threshold:
            return size_pips >= self.min_gap_size_pips
        else:
            return size_percentage >= self.min_gap_size_percentage

    def detect_bullish_fvg(
        self,
        candles: List[Candle],
        start_index: int
    ) -> Optional[FairValueGap]:
        """
        Detect a bullish Fair Value Gap at the given position.

        Bullish FVG pattern:
        - candle[0].high < candle[2].low
        - Gap between first candle's high and third candle's low
        - Middle candle creates gap with strong upward movement

        Args:
            candles: List of candles to analyze
            start_index: Starting index for the 3-candle pattern

        Returns:
            FairValueGap if pattern detected and meets threshold, None otherwise
        """
        if start_index + 2 >= len(candles):
            return None

        candle_0 = candles[start_index]
        candle_1 = candles[start_index + 1]
        candle_2 = candles[start_index + 2]

        # Check for bullish FVG pattern
        if candle_0.high >= candle_2.low:
            return None

        # Gap exists between candle_0.high and candle_2.low
        gap_low = candle_0.high
        gap_high = candle_2.low

        # Calculate gap size
        reference_price = candle_1.close
        size_pips, size_percentage = self.calculate_gap_size(
            gap_high, gap_low, reference_price
        )

        # Check threshold
        if not self.meets_threshold(size_pips, size_percentage):
            self.logger.debug(
                f"Bullish FVG at index {start_index + 1} filtered out: "
                f"size={size_pips:.2f}pips ({size_percentage:.3f}%)"
            )
            return None

        # Create FVG
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=gap_high,
            low=gap_low,
            origin_timestamp=candle_1.timestamp,
            origin_candle_index=start_index + 1,
            symbol=candle_1.symbol,
            timeframe=candle_1.timeframe,
            size_pips=size_pips,
            size_percentage=size_percentage,
            volume=candle_1.volume
        )

        self.logger.debug(f"Bullish FVG detected: {fvg}")
        return fvg

    def detect_bearish_fvg(
        self,
        candles: List[Candle],
        start_index: int
    ) -> Optional[FairValueGap]:
        """
        Detect a bearish Fair Value Gap at the given position.

        Bearish FVG pattern:
        - candle[0].low > candle[2].high
        - Gap between first candle's low and third candle's high
        - Middle candle creates gap with strong downward movement

        Args:
            candles: List of candles to analyze
            start_index: Starting index for the 3-candle pattern

        Returns:
            FairValueGap if pattern detected and meets threshold, None otherwise
        """
        if start_index + 2 >= len(candles):
            return None

        candle_0 = candles[start_index]
        candle_1 = candles[start_index + 1]
        candle_2 = candles[start_index + 2]

        # Check for bearish FVG pattern
        if candle_0.low <= candle_2.high:
            return None

        # Gap exists between candle_2.high and candle_0.low
        gap_low = candle_2.high
        gap_high = candle_0.low

        # Calculate gap size
        reference_price = candle_1.close
        size_pips, size_percentage = self.calculate_gap_size(
            gap_high, gap_low, reference_price
        )

        # Check threshold
        if not self.meets_threshold(size_pips, size_percentage):
            self.logger.debug(
                f"Bearish FVG at index {start_index + 1} filtered out: "
                f"size={size_pips:.2f}pips ({size_percentage:.3f}%)"
            )
            return None

        # Create FVG
        fvg = FairValueGap(
            type=FVGType.BEARISH,
            high=gap_high,
            low=gap_low,
            origin_timestamp=candle_1.timestamp,
            origin_candle_index=start_index + 1,
            symbol=candle_1.symbol,
            timeframe=candle_1.timeframe,
            size_pips=size_pips,
            size_percentage=size_percentage,
            volume=candle_1.volume
        )

        self.logger.debug(f"Bearish FVG detected: {fvg}")
        return fvg

    def detect_fair_value_gaps(self, candles: List[Candle]) -> List[FairValueGap]:
        """
        Detect all Fair Value Gaps from candle data.

        Args:
            candles: List of candles to analyze (must be in chronological order)

        Returns:
            List of detected Fair Value Gaps, sorted by timestamp

        Raises:
            ValueError: If insufficient candles provided
        """
        if len(candles) < 3:
            raise ValueError(
                f"Insufficient candles for FVG detection. "
                f"Need at least 3, got {len(candles)}"
            )

        self.logger.info(
            f"Detecting Fair Value Gaps in {len(candles)} candles "
            f"({candles[0].symbol}, {candles[0].timeframe.value})"
        )

        fvgs = []

        # Scan through candles with a 3-candle sliding window
        for i in range(len(candles) - 2):
            # Try to detect bullish FVG
            bullish_fvg = self.detect_bullish_fvg(candles, i)
            if bullish_fvg:
                fvgs.append(bullish_fvg)

            # Try to detect bearish FVG
            bearish_fvg = self.detect_bearish_fvg(candles, i)
            if bearish_fvg:
                fvgs.append(bearish_fvg)

        # Sort by timestamp
        fvgs.sort(key=lambda fvg: fvg.origin_timestamp)

        self.logger.info(
            f"Detected {len(fvgs)} Fair Value Gaps "
            f"(threshold: {self.min_gap_size_pips:.2f}pips / {self.min_gap_size_percentage:.3f}%)"
        )

        return fvgs

    def update_fvg_states(
        self,
        fvgs: List[FairValueGap],
        current_candles: List[Candle]
    ) -> None:
        """
        Update the state of FVGs based on current price action.

        Args:
            fvgs: List of FVGs to update
            current_candles: Recent candles to check against FVGs
        """
        for fvg in fvgs:
            if fvg.state == FVGState.FILLED or fvg.state == FVGState.EXPIRED:
                continue

            # Check recent candles for gap fills
            for candle in current_candles:
                if fvg.contains_price(candle.low) or fvg.contains_price(candle.high):
                    # Update fill status
                    check_price = candle.low if fvg.type == FVGType.BEARISH else candle.high
                    fvg.update_fill_status(check_price, candle.timestamp)

                # Check if price has completely broken through the gap
                if fvg.type == FVGType.BULLISH and candle.low < fvg.low:
                    fvg.state = FVGState.FILLED
                    fvg.filled_percentage = 100.0
                elif fvg.type == FVGType.BEARISH and candle.high > fvg.high:
                    fvg.state = FVGState.FILLED
                    fvg.filled_percentage = 100.0
