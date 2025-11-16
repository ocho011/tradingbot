"""
Stop loss calculator with structural level analysis and tolerance application.

Calculates stop loss levels using:
- Structural level analysis (Order Blocks, Fair Value Gaps, Liquidity Zones)
- Price tolerance (0.1-0.3%) for buffer zones
- Entry price distance validation
- Position size verification based on risk
"""

import logging
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.constants import PositionSide
from src.indicators.fair_value_gap import FairValueGap, FVGState, FVGType
from src.indicators.liquidity_zone import LiquidityLevel, LiquidityState, LiquidityType
from src.indicators.order_block import OrderBlock, OrderBlockState, OrderBlockType
from src.services.risk.position_sizer import PositionSizer

logger = logging.getLogger(__name__)


class StopLossCalculationError(Exception):
    """Raised when stop loss calculation fails."""



class StopLossStrategy(str, Enum):
    """Strategy for determining stop loss placement."""

    ORDER_BLOCK = "ORDER_BLOCK"  # Use nearest active order block
    FAIR_VALUE_GAP = "FAIR_VALUE_GAP"  # Use nearest active FVG
    LIQUIDITY_ZONE = "LIQUIDITY_ZONE"  # Use nearest liquidity level
    AUTO = "AUTO"  # Automatically select best structural level


class StopLossCalculator:
    """
    Calculate stop loss levels based on structural analysis with tolerance.

    Features:
    - Structural level analysis (OB, FVG, Liquidity)
    - 0.1-0.3% tolerance application for buffer
    - Entry-to-stop distance validation
    - Position size recalculation based on risk
    - Dynamic strategy selection

    Attributes:
        position_sizer: Position sizer for risk verification
        min_tolerance_pct: Minimum tolerance percentage (default: 0.1%)
        max_tolerance_pct: Maximum tolerance percentage (default: 0.3%)
        default_tolerance_pct: Default tolerance percentage (default: 0.2%)
        min_stop_distance_pct: Minimum stop distance from entry (default: 0.3%)
        max_stop_distance_pct: Maximum stop distance from entry (default: 3.0%)
        precision: Decimal places for stop loss price
    """

    def __init__(
        self,
        position_sizer: PositionSizer,
        min_tolerance_pct: float = 0.1,
        max_tolerance_pct: float = 0.3,
        default_tolerance_pct: float = 0.2,
        min_stop_distance_pct: float = 0.3,
        max_stop_distance_pct: float = 3.0,
        precision: int = 8,
    ):
        """
        Initialize stop loss calculator.

        Args:
            position_sizer: Position sizer instance for risk verification
            min_tolerance_pct: Minimum tolerance percentage (0.1%)
            max_tolerance_pct: Maximum tolerance percentage (0.3%)
            default_tolerance_pct: Default tolerance percentage (0.2%)
            min_stop_distance_pct: Minimum stop distance percentage (0.3%)
            max_stop_distance_pct: Maximum stop distance percentage (3.0%)
            precision: Decimal places for stop loss price

        Raises:
            ValueError: If parameters are invalid
        """
        if not isinstance(position_sizer, PositionSizer):
            raise ValueError("position_sizer must be a PositionSizer instance")

        if not (0 < min_tolerance_pct <= max_tolerance_pct):
            raise ValueError("Invalid tolerance range: min must be positive and <= max")

        if not (min_tolerance_pct <= default_tolerance_pct <= max_tolerance_pct):
            raise ValueError("default_tolerance_pct must be between min and max")

        if not (0 < min_stop_distance_pct <= max_stop_distance_pct):
            raise ValueError("Invalid stop distance range")

        if precision < 0:
            raise ValueError("precision must be non-negative")

        self.position_sizer = position_sizer
        self.min_tolerance_pct = Decimal(str(min_tolerance_pct))
        self.max_tolerance_pct = Decimal(str(max_tolerance_pct))
        self.default_tolerance_pct = Decimal(str(default_tolerance_pct))
        self.min_stop_distance_pct = Decimal(str(min_stop_distance_pct))
        self.max_stop_distance_pct = Decimal(str(max_stop_distance_pct))
        self.precision = precision

        logger.info(
            f"StopLossCalculator initialized: "
            f"tolerance={min_tolerance_pct}-{max_tolerance_pct}% (default={default_tolerance_pct}%), "
            f"stop_distance={min_stop_distance_pct}-{max_stop_distance_pct}%"
        )

    def _find_nearest_order_block(
        self, order_blocks: List[OrderBlock], entry_price: float, position_side: PositionSide
    ) -> Optional[OrderBlock]:
        """
        Find the nearest relevant order block for stop loss placement.

        Args:
            order_blocks: List of detected order blocks
            entry_price: Entry price for the trade
            position_side: LONG or SHORT position

        Returns:
            Nearest relevant order block, or None if not found
        """
        if not order_blocks:
            return None

        # Filter active order blocks
        active_obs = [ob for ob in order_blocks if ob.state == OrderBlockState.ACTIVE]

        if not active_obs:
            logger.debug("No active order blocks found")
            return None

        relevant_obs = []

        if position_side == PositionSide.LONG:
            # For long positions, we want bullish OBs below entry price
            relevant_obs = [
                ob
                for ob in active_obs
                if ob.type == OrderBlockType.BULLISH and ob.high < entry_price
            ]
        else:  # SHORT
            # For short positions, we want bearish OBs above entry price
            relevant_obs = [
                ob
                for ob in active_obs
                if ob.type == OrderBlockType.BEARISH and ob.low > entry_price
            ]

        if not relevant_obs:
            logger.debug(f"No relevant {position_side.value} order blocks found")
            return None

        # Sort by proximity to entry price and return nearest
        if position_side == PositionSide.LONG:
            # Closest OB below entry (highest high below entry)
            return max(relevant_obs, key=lambda ob: ob.high)
        else:
            # Closest OB above entry (lowest low above entry)
            return min(relevant_obs, key=lambda ob: ob.low)

    def _find_nearest_fvg(
        self, fvgs: List[FairValueGap], entry_price: float, position_side: PositionSide
    ) -> Optional[FairValueGap]:
        """
        Find the nearest relevant FVG for stop loss placement.

        Args:
            fvgs: List of detected FVGs
            entry_price: Entry price for the trade
            position_side: LONG or SHORT position

        Returns:
            Nearest relevant FVG, or None if not found
        """
        if not fvgs:
            return None

        # Filter active FVGs (not filled)
        active_fvgs = [fvg for fvg in fvgs if fvg.state in (FVGState.ACTIVE, FVGState.PARTIAL)]

        if not active_fvgs:
            logger.debug("No active FVGs found")
            return None

        relevant_fvgs = []

        if position_side == PositionSide.LONG:
            # For long positions, we want bullish FVGs below entry price
            relevant_fvgs = [
                fvg for fvg in active_fvgs if fvg.type == FVGType.BULLISH and fvg.high < entry_price
            ]
        else:  # SHORT
            # For short positions, we want bearish FVGs above entry price
            relevant_fvgs = [
                fvg for fvg in active_fvgs if fvg.type == FVGType.BEARISH and fvg.low > entry_price
            ]

        if not relevant_fvgs:
            logger.debug(f"No relevant {position_side.value} FVGs found")
            return None

        # Sort by proximity to entry price and return nearest
        if position_side == PositionSide.LONG:
            # Closest FVG below entry (highest high below entry)
            return max(relevant_fvgs, key=lambda fvg: fvg.high)
        else:
            # Closest FVG above entry (lowest low above entry)
            return min(relevant_fvgs, key=lambda fvg: fvg.low)

    def _find_nearest_liquidity_level(
        self,
        liquidity_levels: List[LiquidityLevel],
        entry_price: float,
        position_side: PositionSide,
    ) -> Optional[LiquidityLevel]:
        """
        Find the nearest relevant liquidity level for stop loss placement.

        Args:
            liquidity_levels: List of detected liquidity levels
            entry_price: Entry price for the trade
            position_side: LONG or SHORT position

        Returns:
            Nearest relevant liquidity level, or None if not found
        """
        if not liquidity_levels:
            return None

        # Filter active liquidity levels
        active_levels = [
            level
            for level in liquidity_levels
            if level.state in (LiquidityState.ACTIVE, LiquidityState.PARTIAL)
        ]

        if not active_levels:
            logger.debug("No active liquidity levels found")
            return None

        relevant_levels = []

        if position_side == PositionSide.LONG:
            # For long positions, we want sell-side liquidity below entry price
            relevant_levels = [
                level
                for level in active_levels
                if level.type == LiquidityType.SELL_SIDE and level.price < entry_price
            ]
        else:  # SHORT
            # For short positions, we want buy-side liquidity above entry price
            relevant_levels = [
                level
                for level in active_levels
                if level.type == LiquidityType.BUY_SIDE and level.price > entry_price
            ]

        if not relevant_levels:
            logger.debug(f"No relevant {position_side.value} liquidity levels found")
            return None

        # Sort by proximity to entry price and return nearest
        if position_side == PositionSide.LONG:
            # Closest level below entry (highest price below entry)
            return max(relevant_levels, key=lambda level: level.price)
        else:
            # Closest level above entry (lowest price above entry)
            return min(relevant_levels, key=lambda level: level.price)

    def _get_structural_level_price(
        self, structural_level: Any, position_side: PositionSide
    ) -> float:
        """
        Extract the price from a structural level for stop loss placement.

        Args:
            structural_level: OrderBlock, FairValueGap, or LiquidityLevel
            position_side: LONG or SHORT position

        Returns:
            Price level for stop loss placement
        """
        if isinstance(structural_level, OrderBlock):
            # Use the boundary opposite to position direction
            return (
                structural_level.low
                if position_side == PositionSide.LONG
                else structural_level.high
            )

        elif isinstance(structural_level, FairValueGap):
            # Use the boundary opposite to position direction
            return (
                structural_level.low
                if position_side == PositionSide.LONG
                else structural_level.high
            )

        elif isinstance(structural_level, LiquidityLevel):
            # Use the exact price level
            return structural_level.price

        else:
            raise ValueError(f"Unsupported structural level type: {type(structural_level)}")

    def _apply_tolerance(
        self, base_price: float, position_side: PositionSide, tolerance_pct: Optional[float] = None
    ) -> float:
        """
        Apply tolerance buffer to the base stop loss price.

        Args:
            base_price: Base structural level price
            position_side: LONG or SHORT position
            tolerance_pct: Custom tolerance percentage (None = use default)

        Returns:
            Stop loss price with tolerance applied
        """
        if tolerance_pct is None:
            tolerance_pct = float(self.default_tolerance_pct)

        tolerance_decimal = Decimal(str(tolerance_pct)) / Decimal("100")
        price_decimal = Decimal(str(base_price))
        tolerance_amount = price_decimal * tolerance_decimal

        if position_side == PositionSide.LONG:
            # For long, place stop below structural level (more protection)
            stop_price = price_decimal - tolerance_amount
        else:  # SHORT
            # For short, place stop above structural level (more protection)
            stop_price = price_decimal + tolerance_amount

        logger.debug(
            f"Tolerance applied: base={base_price:.8f}, "
            f"tolerance={tolerance_pct}%, stop={float(stop_price):.8f}"
        )

        return float(stop_price)

    def _validate_stop_distance(
        self, entry_price: float, stop_loss_price: float, position_side: PositionSide
    ) -> bool:
        """
        Validate that stop loss distance is within acceptable range.

        Args:
            entry_price: Entry price for the trade
            stop_loss_price: Calculated stop loss price
            position_side: LONG or SHORT position

        Returns:
            True if distance is valid, False otherwise
        """
        entry_decimal = Decimal(str(entry_price))
        stop_decimal = Decimal(str(stop_loss_price))

        # Calculate distance percentage
        distance = abs(entry_decimal - stop_decimal)
        distance_pct = (distance / entry_decimal) * Decimal("100")

        is_valid = self.min_stop_distance_pct <= distance_pct <= self.max_stop_distance_pct

        if not is_valid:
            logger.warning(
                f"Stop distance {float(distance_pct):.2f}% outside valid range "
                f"[{float(self.min_stop_distance_pct):.2f}%, {float(self.max_stop_distance_pct):.2f}%]"
            )
        else:
            logger.debug(
                f"Stop distance validated: {float(distance_pct):.2f}% "
                f"(entry={entry_price:.8f}, stop={stop_loss_price:.8f})"
            )

        return is_valid

    def _round_stop_price(self, price: float) -> float:
        """
        Round stop loss price to specified precision.

        Args:
            price: Stop loss price to round

        Returns:
            Rounded stop loss price
        """
        price_decimal = Decimal(str(price))
        quantize_value = Decimal("1") / Decimal(10**self.precision)
        rounded = price_decimal.quantize(quantize_value, rounding=ROUND_DOWN)

        if rounded != price_decimal:
            logger.debug(f"Stop price rounded: {price:.8f} -> {float(rounded):.8f}")

        return float(rounded)

    async def calculate_position_size_for_stop(
        self, entry_price: float, stop_loss_price: float, risk_amount: float, leverage: int = 5
    ) -> float:
        """
        Recalculate position size based on entry-to-stop distance and risk amount.

        Formula: position_size = (risk_amount * leverage) / (distance_pct / 100)

        Args:
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price
            risk_amount: Maximum risk amount in USDT (2% of balance)
            leverage: Leverage multiplier (default: 5x)

        Returns:
            Recalculated position size in USDT

        Raises:
            StopLossError: If calculation fails
        """
        try:
            entry_decimal = Decimal(str(entry_price))
            stop_decimal = Decimal(str(stop_loss_price))
            risk_decimal = Decimal(str(risk_amount))

            # Calculate stop distance percentage
            distance = abs(entry_decimal - stop_decimal)
            distance_pct = (distance / entry_decimal) * Decimal("100")

            if distance_pct == 0:
                raise StopLossCalculationError("Stop loss distance is zero")

            # Calculate position size with leverage
            # position_size = (risk * leverage) / distance_pct
            position_size = (risk_decimal * Decimal(str(leverage))) / (
                distance_pct / Decimal("100")
            )

            logger.debug(
                f"Position size for stop: risk={risk_amount} USDT, "
                f"distance={float(distance_pct):.2f}%, "
                f"leverage={leverage}x, size={float(position_size):.2f} USDT"
            )

            return float(position_size)

        except Exception as e:
            error_msg = f"Failed to calculate position size for stop: {e}"
            logger.error(error_msg, exc_info=True)
            raise StopLossCalculationError(error_msg) from e

    def calculate_stop_loss(
        self,
        entry_price: float,
        position_side: PositionSide,
        order_blocks: Optional[List[OrderBlock]] = None,
        fvgs: Optional[List[FairValueGap]] = None,
        liquidity_levels: Optional[List[LiquidityLevel]] = None,
        strategy: StopLossStrategy = StopLossStrategy.AUTO,
        tolerance_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculate stop loss level based on structural analysis and tolerance.

        This is the main method that orchestrates the entire calculation:
        1. Find relevant structural level based on strategy
        2. Extract base price from structural level
        3. Apply tolerance buffer (0.1-0.3%)
        4. Validate stop distance from entry
        5. Round to exchange precision

        Args:
            entry_price: Entry price for the trade
            position_side: LONG or SHORT position
            order_blocks: List of detected order blocks (optional)
            fvgs: List of detected Fair Value Gaps (optional)
            liquidity_levels: List of detected liquidity levels (optional)
            strategy: Stop loss placement strategy (default: AUTO)
            tolerance_pct: Custom tolerance percentage (None = use default)

        Returns:
            Dictionary containing:
            - 'stop_loss_price': Calculated stop loss price
            - 'base_price': Structural level price before tolerance
            - 'tolerance_applied_pct': Tolerance percentage applied
            - 'distance_pct': Distance from entry as percentage
            - 'distance_usdt': Distance from entry in price units
            - 'structural_level_type': Type of structural level used
            - 'structural_level': The actual structural level object
            - 'strategy_used': Strategy that was used
            - 'valid': Whether stop loss is valid

        Raises:
            StopLossError: If calculation fails or no valid structural level found
        """
        try:
            logger.info(
                f"Calculating stop loss: entry={entry_price}, "
                f"side={position_side.value}, strategy={strategy.value}"
            )

            # Find structural level based on strategy
            structural_level = None
            structural_type = None
            strategy_used = strategy

            if strategy == StopLossStrategy.AUTO:
                # Try order blocks first, then FVGs, then liquidity
                structural_level = self._find_nearest_order_block(
                    order_blocks or [], entry_price, position_side
                )
                if structural_level:
                    structural_type = "ORDER_BLOCK"
                    strategy_used = StopLossStrategy.ORDER_BLOCK
                else:
                    structural_level = self._find_nearest_fvg(
                        fvgs or [], entry_price, position_side
                    )
                    if structural_level:
                        structural_type = "FAIR_VALUE_GAP"
                        strategy_used = StopLossStrategy.FAIR_VALUE_GAP
                    else:
                        structural_level = self._find_nearest_liquidity_level(
                            liquidity_levels or [], entry_price, position_side
                        )
                        if structural_level:
                            structural_type = "LIQUIDITY_ZONE"
                            strategy_used = StopLossStrategy.LIQUIDITY_ZONE

            elif strategy == StopLossStrategy.ORDER_BLOCK:
                structural_level = self._find_nearest_order_block(
                    order_blocks or [], entry_price, position_side
                )
                structural_type = "ORDER_BLOCK"

            elif strategy == StopLossStrategy.FAIR_VALUE_GAP:
                structural_level = self._find_nearest_fvg(fvgs or [], entry_price, position_side)
                structural_type = "FAIR_VALUE_GAP"

            elif strategy == StopLossStrategy.LIQUIDITY_ZONE:
                structural_level = self._find_nearest_liquidity_level(
                    liquidity_levels or [], entry_price, position_side
                )
                structural_type = "LIQUIDITY_ZONE"

            if structural_level is None:
                raise StopLossCalculationError(
                    f"No suitable structural level found for {position_side.value} position "
                    f"with strategy {strategy.value}"
                )

            # Extract base price from structural level
            base_price = self._get_structural_level_price(structural_level, position_side)

            logger.info(
                f"Found structural level: type={structural_type}, " f"base_price={base_price:.8f}"
            )

            # Apply tolerance
            stop_loss_price = self._apply_tolerance(base_price, position_side, tolerance_pct)

            # Validate stop distance
            is_valid = self._validate_stop_distance(entry_price, stop_loss_price, position_side)

            if not is_valid:
                logger.warning("Stop loss distance validation failed, but returning result anyway")

            # Round to precision
            stop_loss_price = self._round_stop_price(stop_loss_price)

            # Calculate distance metrics
            entry_decimal = Decimal(str(entry_price))
            stop_decimal = Decimal(str(stop_loss_price))
            distance = abs(entry_decimal - stop_decimal)
            distance_pct = (distance / entry_decimal) * Decimal("100")

            # Get applied tolerance
            applied_tolerance = (
                tolerance_pct if tolerance_pct is not None else float(self.default_tolerance_pct)
            )

            result = {
                "stop_loss_price": stop_loss_price,
                "base_price": base_price,
                "tolerance_applied_pct": applied_tolerance,
                "distance_pct": float(distance_pct),
                "distance_usdt": float(distance),
                "structural_level_type": structural_type,
                "structural_level": structural_level,
                "strategy_used": strategy_used.value,
                "valid": is_valid,
                "entry_price": entry_price,
                "position_side": position_side.value,
            }

            logger.info(
                f"Stop loss calculated: {stop_loss_price:.8f} "
                f"(distance: {float(distance_pct):.2f}%, "
                f"type: {structural_type}, "
                f"tolerance: {applied_tolerance}%)"
            )

            return result

        except StopLossCalculationError:
            raise
        except Exception as e:
            error_msg = f"Failed to calculate stop loss: {e}"
            logger.error(error_msg, exc_info=True)
            raise StopLossCalculationError(error_msg) from e

    def get_parameters(self) -> Dict[str, Any]:
        """
        Get current stop loss calculator parameters.

        Returns:
            Dictionary with current parameters
        """
        return {
            "min_tolerance_pct": float(self.min_tolerance_pct),
            "max_tolerance_pct": float(self.max_tolerance_pct),
            "default_tolerance_pct": float(self.default_tolerance_pct),
            "min_stop_distance_pct": float(self.min_stop_distance_pct),
            "max_stop_distance_pct": float(self.max_stop_distance_pct),
            "precision": self.precision,
        }

    def update_parameters(
        self,
        min_tolerance_pct: Optional[float] = None,
        max_tolerance_pct: Optional[float] = None,
        default_tolerance_pct: Optional[float] = None,
        min_stop_distance_pct: Optional[float] = None,
        max_stop_distance_pct: Optional[float] = None,
    ) -> None:
        """
        Update stop loss calculator parameters.

        Args:
            min_tolerance_pct: New minimum tolerance (None = no change)
            max_tolerance_pct: New maximum tolerance (None = no change)
            default_tolerance_pct: New default tolerance (None = no change)
            min_stop_distance_pct: New minimum stop distance (None = no change)
            max_stop_distance_pct: New maximum stop distance (None = no change)

        Raises:
            ValueError: If new parameters are invalid
        """
        if min_tolerance_pct is not None:
            if min_tolerance_pct <= 0:
                raise ValueError("min_tolerance_pct must be positive")
            self.min_tolerance_pct = Decimal(str(min_tolerance_pct))
            logger.info(f"Minimum tolerance updated to {min_tolerance_pct}%")

        if max_tolerance_pct is not None:
            if max_tolerance_pct <= 0:
                raise ValueError("max_tolerance_pct must be positive")
            self.max_tolerance_pct = Decimal(str(max_tolerance_pct))
            logger.info(f"Maximum tolerance updated to {max_tolerance_pct}%")

        if default_tolerance_pct is not None:
            if not (
                float(self.min_tolerance_pct)
                <= default_tolerance_pct
                <= float(self.max_tolerance_pct)
            ):
                raise ValueError("default_tolerance_pct must be between min and max")
            self.default_tolerance_pct = Decimal(str(default_tolerance_pct))
            logger.info(f"Default tolerance updated to {default_tolerance_pct}%")

        if min_stop_distance_pct is not None:
            if min_stop_distance_pct <= 0:
                raise ValueError("min_stop_distance_pct must be positive")
            self.min_stop_distance_pct = Decimal(str(min_stop_distance_pct))
            logger.info(f"Minimum stop distance updated to {min_stop_distance_pct}%")

        if max_stop_distance_pct is not None:
            if max_stop_distance_pct <= 0:
                raise ValueError("max_stop_distance_pct must be positive")
            self.max_stop_distance_pct = Decimal(str(max_stop_distance_pct))
            logger.info(f"Maximum stop distance updated to {max_stop_distance_pct}%")
