"""
Breaker Block detection and role transition logic for ICT trading methodology.

This module implements the detection of Breaker Blocks (BB), which are Order Blocks
that have been violated/broken and have reversed their role from support to resistance
or vice versa. This represents a key concept in ICT methodology where institutional
levels flip their market structure role.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.constants import TimeFrame
from src.indicators.order_block import OrderBlock, OrderBlockState, OrderBlockType
from src.models.candle import Candle

logger = logging.getLogger(__name__)


class BreakerBlockType(str, Enum):
    """Type of Breaker Block based on new role after transition."""

    BULLISH = "BULLISH"  # Former bearish OB, now acts as support
    BEARISH = "BEARISH"  # Former bullish OB, now acts as resistance


@dataclass
class BreakerBlock:
    """
    Represents a Breaker Block - an Order Block that has been broken and reversed its role.

    Key Concept:
    - Bullish OB (support) broken downward → Bearish BB (resistance)
    - Bearish OB (resistance) broken upward → Bullish BB (support)

    Attributes:
        type: New role of the breaker block (support/resistance after transition)
        original_type: Original Order Block type before role reversal
        high: Upper boundary of the breaker block zone
        low: Lower boundary of the breaker block zone
        origin_timestamp: Original OB formation timestamp
        transition_timestamp: When the OB transitioned to BB
        transition_candle_index: Index of candle that broke the OB
        symbol: Trading symbol
        timeframe: Timeframe where detected
        strength: Original strength score from OB
        volume: Volume of the transition/break candle
        original_ob_volume: Volume of original OB formation
        original_test_count: How many times OB was tested before breaking
        breach_percentage: How much price penetrated beyond the OB level
        state: Current state (active/tested/expired)
    """

    type: BreakerBlockType
    original_type: OrderBlockType
    high: float
    low: float
    origin_timestamp: int
    transition_timestamp: int
    transition_candle_index: int
    symbol: str
    timeframe: TimeFrame
    strength: float
    volume: float
    original_ob_volume: float
    original_test_count: int = 0
    breach_percentage: float = 0.0
    state: str = "ACTIVE"
    last_tested_timestamp: Optional[int] = None
    test_count: int = 0

    def __post_init__(self):
        """Validate breaker block data."""
        if self.high <= self.low:
            raise ValueError(f"High ({self.high}) must be greater than low ({self.low})")
        if self.strength < 0 or self.strength > 100:
            raise ValueError(f"Strength must be between 0 and 100, got {self.strength}")
        if self.volume < 0:
            raise ValueError(f"Volume must be non-negative, got {self.volume}")
        if self.breach_percentage < 0:
            raise ValueError(
                f"Breach percentage must be non-negative, got {self.breach_percentage}"
            )

    def get_range(self) -> float:
        """Get the price range of the breaker block."""
        return self.high - self.low

    def get_midpoint(self) -> float:
        """Get the midpoint price of the breaker block."""
        return (self.high + self.low) / 2

    def contains_price(self, price: float) -> bool:
        """
        Check if a price is within the breaker block zone.

        Args:
            price: Price to check

        Returns:
            True if price is within the block boundaries
        """
        return self.low <= price <= self.high

    def is_price_above(self, price: float) -> bool:
        """Check if price is above the breaker block."""
        return price > self.high

    def is_price_below(self, price: float) -> bool:
        """Check if price is below the breaker block."""
        return price < self.low

    def mark_tested(self, timestamp: int) -> None:
        """
        Mark the breaker block as tested by price.

        Args:
            timestamp: Timestamp when the test occurred
        """
        self.state = "TESTED"
        self.last_tested_timestamp = timestamp
        self.test_count += 1

    def mark_expired(self) -> None:
        """Mark the breaker block as expired."""
        self.state = "EXPIRED"

    def get_role_description(self) -> str:
        """Get a human-readable description of the role transition."""
        if self.type == BreakerBlockType.BULLISH:
            return "Former resistance (bearish OB) → Now support (bullish BB)"
        else:
            return "Former support (bullish OB) → Now resistance (bearish BB)"

    def to_dict(self) -> Dict[str, Any]:
        """Convert breaker block to dictionary."""
        return {
            "type": self.type.value,
            "original_type": self.original_type.value,
            "role_transition": self.get_role_description(),
            "high": self.high,
            "low": self.low,
            "origin_timestamp": self.origin_timestamp,
            "origin_datetime": datetime.fromtimestamp(self.origin_timestamp / 1000).isoformat(),
            "transition_timestamp": self.transition_timestamp,
            "transition_datetime": datetime.fromtimestamp(
                self.transition_timestamp / 1000
            ).isoformat(),
            "transition_candle_index": self.transition_candle_index,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "strength": self.strength,
            "volume": self.volume,
            "original_ob_volume": self.original_ob_volume,
            "original_test_count": self.original_test_count,
            "breach_percentage": self.breach_percentage,
            "state": self.state,
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
        """String representation of breaker block."""
        return (
            f"BreakerBlock(type={self.type.value}, "
            f"original={self.original_type.value}, "
            f"range=[{self.low:.2f}-{self.high:.2f}], "
            f"breach={self.breach_percentage:.1f}%, "
            f"state={self.state}, "
            f"tests={self.test_count})"
        )


class BreakerBlockDetector:
    """
    Detects when Order Blocks are broken and transition to Breaker Blocks.

    The detector monitors active Order Blocks and identifies when price violates
    them beyond a threshold, triggering a role reversal where:
    - Support becomes resistance
    - Resistance becomes support
    """

    def __init__(
        self,
        breach_threshold_percentage: float = 0.5,
        min_breach_candle_body_ratio: float = 0.3,
        require_close_beyond: bool = True,
    ):
        """
        Initialize Breaker Block detector.

        Args:
            breach_threshold_percentage: Minimum % penetration beyond OB to confirm breach
            min_breach_candle_body_ratio: Minimum body/range ratio for breach candle
            require_close_beyond: If True, candle must close beyond the OB level
        """
        self.breach_threshold_percentage = breach_threshold_percentage
        self.min_breach_candle_body_ratio = min_breach_candle_body_ratio
        self.require_close_beyond = require_close_beyond
        self.logger = logging.getLogger(f"{__name__}.BreakerBlockDetector")

    def calculate_breach_percentage(self, order_block: OrderBlock, breach_price: float) -> float:
        """
        Calculate how much price breached beyond the Order Block level.

        Args:
            order_block: The Order Block being breached
            breach_price: The price that breached the level

        Returns:
            Percentage of breach relative to OB range
        """
        ob_range = order_block.get_range()
        if ob_range == 0:
            return 0.0

        if order_block.type == OrderBlockType.BULLISH:
            # Bullish OB breach = price goes below low
            if breach_price >= order_block.low:
                return 0.0
            breach_distance = order_block.low - breach_price
        else:
            # Bearish OB breach = price goes above high
            if breach_price <= order_block.high:
                return 0.0
            breach_distance = breach_price - order_block.high

        return (breach_distance / ob_range) * 100

    def is_order_block_breached(self, order_block: OrderBlock, candle: Candle) -> bool:
        """
        Check if a candle breaches an Order Block beyond the threshold.

        Args:
            order_block: Order Block to check
            candle: Candle that potentially breaches the OB

        Returns:
            True if the candle breaches the OB according to criteria
        """
        # Check breach direction based on OB type
        if order_block.type == OrderBlockType.BULLISH:
            # Bullish OB (support) should be breached downward
            breach_price = candle.low
            close_breached = candle.close < order_block.low

            # Calculate how much it breached
            if breach_price >= order_block.low:
                return False

            breach_pct = self.calculate_breach_percentage(order_block, breach_price)

        else:  # BEARISH
            # Bearish OB (resistance) should be breached upward
            breach_price = candle.high
            close_breached = candle.close > order_block.high

            # Calculate how much it breached
            if breach_price <= order_block.high:
                return False

            breach_pct = self.calculate_breach_percentage(order_block, breach_price)

        # Check if breach meets threshold
        if breach_pct < self.breach_threshold_percentage:
            return False

        # Check if close requirement is met
        if self.require_close_beyond and not close_breached:
            return False

        # Check candle body strength
        body_ratio = (
            candle.get_body_size() / candle.get_total_range() if candle.get_total_range() > 0 else 0
        )
        if body_ratio < self.min_breach_candle_body_ratio:
            return False

        return True

    def convert_to_breaker_block(
        self, order_block: OrderBlock, breach_candle: Candle, breach_candle_index: int
    ) -> BreakerBlock:
        """
        Convert a breached Order Block into a Breaker Block.

        The role reverses:
        - Bullish OB (support) → Bearish BB (resistance)
        - Bearish OB (resistance) → Bullish BB (support)

        Args:
            order_block: The Order Block being converted
            breach_candle: Candle that breached the OB
            breach_candle_index: Index of the breach candle

        Returns:
            New BreakerBlock with reversed role
        """
        # Determine new type (role reversal)
        if order_block.type == OrderBlockType.BULLISH:
            new_type = BreakerBlockType.BEARISH  # Support becomes resistance
            breach_price = breach_candle.low
        else:
            new_type = BreakerBlockType.BULLISH  # Resistance becomes support
            breach_price = breach_candle.high

        # Calculate breach percentage
        breach_pct = self.calculate_breach_percentage(order_block, breach_price)

        breaker_block = BreakerBlock(
            type=new_type,
            original_type=order_block.type,
            high=order_block.high,
            low=order_block.low,
            origin_timestamp=order_block.origin_timestamp,
            transition_timestamp=breach_candle.timestamp,
            transition_candle_index=breach_candle_index,
            symbol=order_block.symbol,
            timeframe=order_block.timeframe,
            strength=order_block.strength,
            volume=breach_candle.volume,
            original_ob_volume=order_block.volume,
            original_test_count=order_block.test_count,
            breach_percentage=breach_pct,
            state="ACTIVE",
        )

        self.logger.info(
            f"Order Block converted to Breaker Block: "
            f"{order_block.type.value} OB → {new_type.value} BB "
            f"at {breach_candle.get_datetime_iso()}, "
            f"breach={breach_pct:.2f}%"
        )

        return breaker_block

    def detect_breaker_blocks(
        self, order_blocks: List[OrderBlock], candles: List[Candle], start_index: int = 0
    ) -> List[BreakerBlock]:
        """
        Detect Breaker Blocks from Order Blocks and candle data.

        Monitors active Order Blocks and identifies when they are breached,
        converting them to Breaker Blocks with reversed roles.

        Args:
            order_blocks: List of Order Blocks to monitor
            candles: Full candle data for breach detection
            start_index: Starting index in candles to check for breaches

        Returns:
            List of detected Breaker Blocks
        """
        breaker_blocks = []

        # Filter for active order blocks only
        active_obs = [ob for ob in order_blocks if ob.state == OrderBlockState.ACTIVE]

        self.logger.info(
            f"Monitoring {len(active_obs)} active Order Blocks for breaches "
            f"across {len(candles) - start_index} candles"
        )

        # Check each candle for potential OB breaches
        for i in range(start_index, len(candles)):
            candle = candles[i]

            for ob in active_obs:
                # Skip if OB was formed after this candle
                if ob.origin_candle_index >= i:
                    continue

                # Skip if already broken
                if ob.state == OrderBlockState.BROKEN:
                    continue

                # Check if this candle breaches the OB
                if self.is_order_block_breached(ob, candle):
                    # Convert to Breaker Block
                    bb = self.convert_to_breaker_block(ob, candle, i)
                    breaker_blocks.append(bb)

                    # Mark original OB as broken
                    ob.mark_broken()

                    self.logger.debug(
                        f"Breach detected at index {i}: {ob.type.value} OB → "
                        f"{bb.type.value} BB, price={candle.close:.2f}"
                    )

        # Sort by transition timestamp
        breaker_blocks.sort(key=lambda bb: bb.transition_timestamp)

        self.logger.info(f"Detected {len(breaker_blocks)} Breaker Block transitions")

        return breaker_blocks

    def update_breaker_block_states(
        self, breaker_blocks: List[BreakerBlock], candles: List[Candle], start_index: int = 0
    ) -> None:
        """
        Update the states of Breaker Blocks based on price action.

        Marks BBs as tested when price touches them, allowing tracking
        of how the market respects the new support/resistance levels.

        Args:
            breaker_blocks: List of Breaker Blocks to update
            candles: Candle data for state updates
            start_index: Starting index for updates
        """
        active_bbs = [bb for bb in breaker_blocks if bb.state == "ACTIVE"]

        for i in range(start_index, len(candles)):
            candle = candles[i]

            for bb in active_bbs:
                # Skip if BB was formed after this candle
                if bb.transition_candle_index >= i:
                    continue

                # Check if price is testing the BB
                if bb.contains_price(candle.low) or bb.contains_price(candle.high):
                    bb.mark_tested(candle.timestamp)
                    self.logger.debug(
                        f"Breaker Block tested at index {i}: "
                        f"{bb.type.value} BB, price range=[{candle.low:.2f}-{candle.high:.2f}]"
                    )

    def update_config(self, config: Dict[str, Any]) -> None:
        """
        Update detector configuration dynamically.

        Args:
            config: New configuration dictionary
        """
        # Handle direct parameter updates
        if "breach_threshold_percentage" in config:
            self.breach_threshold_percentage = float(config["breach_threshold_percentage"])
        if "min_breach_candle_body_ratio" in config:
            self.min_breach_candle_body_ratio = float(config["min_breach_candle_body_ratio"])
        if "require_close_beyond" in config:
            self.require_close_beyond = bool(config["require_close_beyond"])
