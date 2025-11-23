"""
Take profit calculator with liquidity-based analysis and risk-reward optimization.

Calculates take profit levels using:
- Liquidity level analysis for target identification
- Risk-reward ratio calculation (minimum 1:1.5)
- Partial take-profit strategy with multiple levels
- Trailing stop integration for profit protection
"""

import logging
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.core.constants import PositionSide
from src.indicators.liquidity_zone import LiquidityLevel, LiquidityState, LiquidityType

logger = logging.getLogger(__name__)


class TakeProfitCalculationError(Exception):
    """Raised when take profit calculation fails."""


class TakeProfitStrategy(str, Enum):
    """Strategy for determining take profit placement."""

    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"  # Target liquidity sweep zones
    FIXED_RR = "FIXED_RR"  # Fixed risk-reward ratio
    SCALED = "SCALED"  # Multiple partial take-profit levels
    AUTO = "AUTO"  # Automatically select best strategy


@dataclass
class PartialTakeProfit:
    """Represents a partial take-profit level."""

    price: float
    percentage: float  # Percentage of position to close
    liquidity_level: Optional[LiquidityLevel] = None
    risk_reward_ratio: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "price": self.price,
            "percentage": self.percentage,
            "liquidity_level": self.liquidity_level.to_dict() if self.liquidity_level else None,
            "risk_reward_ratio": self.risk_reward_ratio,
        }


class TakeProfitCalculator:
    """
    Calculate take profit levels based on liquidity analysis and risk-reward ratios.

    Features:
    - Liquidity level detection and analysis
    - Risk-reward ratio calculation (minimum 1:1.5)
    - Partial take-profit levels (25%, 50%, 75%, 100%)
    - Trailing stop integration capability
    - Dynamic target adjustment based on market structure

    Attributes:
        min_risk_reward_ratio: Minimum acceptable risk-reward ratio (default: 1.5)
        partial_tp_percentages: Percentages for partial take-profits
        min_distance_pct: Minimum distance from entry for take profit
        max_distance_pct: Maximum distance from entry for take profit
        precision: Decimal places for take profit price
    """

    def __init__(
        self,
        min_risk_reward_ratio: float = 1.5,
        partial_tp_percentages: Optional[List[Tuple[float, float]]] = None,
        min_distance_pct: float = 0.5,
        max_distance_pct: float = 10.0,
        precision: int = 8,
    ):
        """
        Initialize take profit calculator.

        Args:
            min_risk_reward_ratio: Minimum risk-reward ratio (default: 1.5)
            partial_tp_percentages: List of (price_multiplier, close_percentage) tuples
                                   Default: [(1.0, 25%), (1.5, 25%), (2.0, 25%), (2.5, 25%)]
            min_distance_pct: Minimum distance from entry percentage (0.5%)
            max_distance_pct: Maximum distance from entry percentage (10.0%)
            precision: Decimal places for take profit price

        Raises:
            ValueError: If parameters are invalid
        """
        if min_risk_reward_ratio < 1.0:
            raise ValueError("min_risk_reward_ratio must be >= 1.0")

        if not (0 < min_distance_pct <= max_distance_pct):
            raise ValueError("Invalid distance range: min must be positive and <= max")

        if precision < 0:
            raise ValueError("precision must be non-negative")

        self.min_risk_reward_ratio = Decimal(str(min_risk_reward_ratio))
        self.min_distance_pct = Decimal(str(min_distance_pct))
        self.max_distance_pct = Decimal(str(max_distance_pct))
        self.precision = precision

        # Default partial TP: 25% at 1.5RR, 25% at 2.0RR, 25% at 2.5RR, 25% at 3.0RR
        if partial_tp_percentages is None:
            self.partial_tp_percentages = [
                (Decimal("1.5"), Decimal("25")),  # 25% at 1.5x risk
                (Decimal("2.0"), Decimal("25")),  # 25% at 2.0x risk
                (Decimal("2.5"), Decimal("25")),  # 25% at 2.5x risk
                (Decimal("3.0"), Decimal("25")),  # 25% at 3.0x risk
            ]
        else:
            self.partial_tp_percentages = [
                (Decimal(str(mult)), Decimal(str(pct))) for mult, pct in partial_tp_percentages
            ]

        # Validate partial percentages sum to 100%
        total_pct = sum(pct for _, pct in self.partial_tp_percentages)
        if abs(total_pct - Decimal("100")) > Decimal("0.01"):
            raise ValueError(f"Partial TP percentages must sum to 100%, got {float(total_pct)}%")

        logger.info(
            f"TakeProfitCalculator initialized: "
            f"min_RR={min_risk_reward_ratio}, "
            f"partial_levels={len(self.partial_tp_percentages)}, "
            f"distance={min_distance_pct}-{max_distance_pct}%"
        )

    def _find_target_liquidity_levels(
        self,
        liquidity_levels: List[LiquidityLevel],
        entry_price: float,
        position_side: PositionSide,
        count: int = 4,
    ) -> List[LiquidityLevel]:
        """
        Find target liquidity levels for take profit placement.

        Args:
            liquidity_levels: List of detected liquidity levels
            entry_price: Entry price for the trade
            position_side: LONG or SHORT position
            count: Number of target levels to find

        Returns:
            List of relevant liquidity levels sorted by proximity to entry
        """
        if not liquidity_levels:
            return []

        # Filter active liquidity levels
        active_levels = [
            level
            for level in liquidity_levels
            if level.state in (LiquidityState.ACTIVE, LiquidityState.PARTIAL)
        ]

        if not active_levels:
            logger.debug("No active liquidity levels found for take profit")
            return []

        relevant_levels = []

        if position_side == PositionSide.LONG:
            # For long positions, target buy-side liquidity above entry (where longs take profit)
            relevant_levels = [
                level
                for level in active_levels
                if level.type == LiquidityType.BUY_SIDE and level.price > entry_price
            ]
            # Sort by distance from entry (closest first, then farther)
            relevant_levels.sort(key=lambda level: level.price)
        else:  # SHORT
            # For short positions, target sell-side liquidity below entry (where shorts take profit)
            relevant_levels = [
                level
                for level in active_levels
                if level.type == LiquidityType.SELL_SIDE and level.price < entry_price
            ]
            # Sort by distance from entry (closest first, then farther)
            relevant_levels.sort(key=lambda level: level.price, reverse=True)

        if not relevant_levels:
            logger.debug(
                f"No relevant {position_side.value} liquidity levels found for take profit"
            )
            return []

        # Return up to 'count' levels, preferring higher strength levels
        # Sort by strength descending, then by distance
        relevant_levels.sort(key=lambda level: (-level.strength, abs(level.price - entry_price)))

        return relevant_levels[:count]

    def _calculate_risk_distance(self, entry_price: float, stop_loss_price: float) -> Decimal:
        """
        Calculate the risk distance (entry to stop loss).

        Args:
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price

        Returns:
            Absolute distance as Decimal
        """
        entry_decimal = Decimal(str(entry_price))
        stop_decimal = Decimal(str(stop_loss_price))

        return abs(entry_decimal - stop_decimal)

    def _calculate_tp_price_from_rr(
        self,
        entry_price: float,
        stop_loss_price: float,
        risk_reward_ratio: float,
        position_side: PositionSide,
    ) -> float:
        """
        Calculate take profit price based on risk-reward ratio.

        Formula:
        - For LONG: TP = entry + (risk_distance * RR)
        - For SHORT: TP = entry - (risk_distance * RR)

        Args:
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price
            risk_reward_ratio: Risk-reward ratio multiplier
            position_side: LONG or SHORT position

        Returns:
            Calculated take profit price
        """
        risk_distance = self._calculate_risk_distance(entry_price, stop_loss_price)
        entry_decimal = Decimal(str(entry_price))
        rr_decimal = Decimal(str(risk_reward_ratio))

        reward_distance = risk_distance * rr_decimal

        if position_side == PositionSide.LONG:
            tp_price = entry_decimal + reward_distance
        else:  # SHORT
            tp_price = entry_decimal - reward_distance

        logger.debug(
            f"RR-based TP: entry={entry_price:.8f}, "
            f"risk_dist={float(risk_distance):.8f}, "
            f"RR={risk_reward_ratio}, "
            f"tp={float(tp_price):.8f}"
        )

        return float(tp_price)

    def _validate_tp_distance(
        self, entry_price: float, tp_price: float, position_side: PositionSide
    ) -> bool:
        """
        Validate that take profit distance is within acceptable range.

        Args:
            entry_price: Entry price for the trade
            tp_price: Take profit price
            position_side: LONG or SHORT position

        Returns:
            True if distance is valid, False otherwise
        """
        entry_decimal = Decimal(str(entry_price))
        tp_decimal = Decimal(str(tp_price))

        # Calculate distance percentage
        distance = abs(entry_decimal - tp_decimal)
        distance_pct = (distance / entry_decimal) * Decimal("100")

        is_valid = self.min_distance_pct <= distance_pct <= self.max_distance_pct

        if not is_valid:
            logger.warning(
                f"TP distance {float(distance_pct):.2f}% outside valid range "
                f"[{float(self.min_distance_pct):.2f}%, {float(self.max_distance_pct):.2f}%]"
            )
        else:
            logger.debug(
                f"TP distance validated: {float(distance_pct):.2f}% "
                f"(entry={entry_price:.8f}, tp={tp_price:.8f})"
            )

        return is_valid

    def _round_tp_price(self, price: float) -> float:
        """
        Round take profit price to specified precision.

        Args:
            price: Take profit price to round

        Returns:
            Rounded take profit price
        """
        price_decimal = Decimal(str(price))
        quantize_value = Decimal("1") / Decimal(10**self.precision)
        rounded = price_decimal.quantize(quantize_value, rounding=ROUND_DOWN)

        if rounded != price_decimal:
            logger.debug(f"TP price rounded: {price:.8f} -> {float(rounded):.8f}")

        return float(rounded)

    def calculate_partial_take_profits(
        self,
        entry_price: float,
        stop_loss_price: float,
        position_side: PositionSide,
        liquidity_levels: Optional[List[LiquidityLevel]] = None,
    ) -> List[PartialTakeProfit]:
        """
        Calculate multiple partial take-profit levels.

        Strategy:
        1. Calculate RR-based levels using configured percentages
        2. Optionally align with nearby liquidity levels if available
        3. Validate each level meets minimum distance requirements

        Args:
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price
            position_side: LONG or SHORT position
            liquidity_levels: Optional list of liquidity levels for alignment

        Returns:
            List of PartialTakeProfit objects

        Raises:
            TakeProfitCalculationError: If calculation fails
        """
        try:
            logger.info(
                f"Calculating partial take profits: entry={entry_price}, "
                f"stop={stop_loss_price}, side={position_side.value}"
            )

            partial_tps = []

            # Find target liquidity levels if provided
            target_levels = []
            if liquidity_levels:
                target_levels = self._find_target_liquidity_levels(
                    liquidity_levels,
                    entry_price,
                    position_side,
                    count=len(self.partial_tp_percentages),
                )

            for i, (rr_multiplier, close_percentage) in enumerate(self.partial_tp_percentages):
                # Calculate TP price based on RR
                tp_price = self._calculate_tp_price_from_rr(
                    entry_price, stop_loss_price, float(rr_multiplier), position_side
                )

                # Try to align with liquidity level if available
                aligned_level = None
                if i < len(target_levels):
                    liquidity_level = target_levels[i]
                    # Check if liquidity level is close enough to RR-based price
                    price_diff_pct = abs(
                        (Decimal(str(tp_price)) - Decimal(str(liquidity_level.price)))
                        / Decimal(str(entry_price))
                    ) * Decimal("100")

                    # If within 1% of RR-based price, use liquidity level
                    if price_diff_pct <= Decimal("1.0"):
                        tp_price = liquidity_level.price
                        aligned_level = liquidity_level
                        logger.debug(f"Aligned TP level {i+1} with liquidity at {tp_price:.8f}")

                # Validate distance
                if not self._validate_tp_distance(entry_price, tp_price, position_side):
                    logger.warning(
                        f"TP level {i+1} at {tp_price:.8f} failed distance validation, "
                        f"but including anyway"
                    )

                # Round to precision
                tp_price = self._round_tp_price(tp_price)

                # Create partial TP
                partial_tp = PartialTakeProfit(
                    price=tp_price,
                    percentage=float(close_percentage),
                    liquidity_level=aligned_level,
                    risk_reward_ratio=float(rr_multiplier),
                )

                partial_tps.append(partial_tp)

                logger.info(
                    f"Partial TP level {i+1}: price={tp_price:.8f}, "
                    f"percentage={float(close_percentage)}%, "
                    f"RR={float(rr_multiplier)}, "
                    f"liquidity_aligned={aligned_level is not None}"
                )

            return partial_tps

        except TakeProfitCalculationError:
            raise
        except Exception as e:
            error_msg = f"Failed to calculate partial take profits: {e}"
            logger.error(error_msg, exc_info=True)
            raise TakeProfitCalculationError(error_msg) from e

    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss_price: float,
        position_side: PositionSide,
        liquidity_levels: Optional[List[LiquidityLevel]] = None,
        strategy: TakeProfitStrategy = TakeProfitStrategy.AUTO,
    ) -> Dict[str, Any]:
        """
        Calculate take profit levels based on strategy.

        This is the main method that orchestrates the calculation:
        1. Validate risk-reward ratio meets minimum requirements
        2. Calculate partial take-profit levels
        3. Identify potential trailing stop activation points
        4. Return comprehensive take profit plan

        Args:
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price
            position_side: LONG or SHORT position
            liquidity_levels: Optional list of liquidity levels
            strategy: Take profit placement strategy

        Returns:
            Dictionary containing:
            - 'partial_take_profits': List of PartialTakeProfit objects
            - 'final_target': Final take profit price (last partial level)
            - 'min_risk_reward_ratio': Minimum RR ratio met
            - 'actual_risk_reward_ratio': Actual RR of final target
            - 'risk_distance': Distance from entry to stop loss
            - 'reward_distance': Distance from entry to final target
            - 'trailing_stop_enabled': Whether trailing stop can be activated
            - 'trailing_activation_price': Price to activate trailing stop (after first TP)
            - 'strategy_used': Strategy that was used
            - 'valid': Whether take profit plan is valid

        Raises:
            TakeProfitCalculationError: If calculation fails
        """
        try:
            logger.info(
                f"Calculating take profit: entry={entry_price}, "
                f"stop={stop_loss_price}, side={position_side.value}, "
                f"strategy={strategy.value}"
            )

            # Calculate partial take profits
            partial_tps = self.calculate_partial_take_profits(
                entry_price, stop_loss_price, position_side, liquidity_levels
            )

            if not partial_tps:
                raise TakeProfitCalculationError("No partial take profit levels calculated")

            # Get final target (last partial TP)
            final_target = partial_tps[-1].price

            # Calculate risk and reward distances
            risk_distance = self._calculate_risk_distance(entry_price, stop_loss_price)
            entry_decimal = Decimal(str(entry_price))
            final_target_decimal = Decimal(str(final_target))
            reward_distance = abs(entry_decimal - final_target_decimal)

            # Calculate actual RR ratio
            actual_rr = reward_distance / risk_distance

            # Check if meets minimum RR requirement
            meets_min_rr = actual_rr >= self.min_risk_reward_ratio

            if not meets_min_rr:
                logger.warning(
                    f"Actual RR {float(actual_rr):.2f} below minimum {float(self.min_risk_reward_ratio):.2f}"
                )

            # Determine trailing stop activation (after first partial TP)
            trailing_activation_price = partial_tps[0].price if len(partial_tps) > 0 else None
            trailing_stop_enabled = trailing_activation_price is not None

            result = {
                "partial_take_profits": [tp.to_dict() for tp in partial_tps],
                "final_target": final_target,
                "min_risk_reward_ratio": float(self.min_risk_reward_ratio),
                "actual_risk_reward_ratio": float(actual_rr),
                "risk_distance": float(risk_distance),
                "reward_distance": float(reward_distance),
                "trailing_stop_enabled": trailing_stop_enabled,
                "trailing_activation_price": trailing_activation_price,
                "strategy_used": strategy.value,
                "valid": meets_min_rr,
                "entry_price": entry_price,
                "stop_loss_price": stop_loss_price,
                "position_side": position_side.value,
            }

            logger.info(
                f"Take profit calculated: final_target={final_target:.8f}, "
                f"actual_RR={float(actual_rr):.2f}, "
                f"partial_levels={len(partial_tps)}, "
                f"trailing_enabled={trailing_stop_enabled}"
            )

            return result

        except TakeProfitCalculationError:
            raise
        except Exception as e:
            error_msg = f"Failed to calculate take profit: {e}"
            logger.error(error_msg, exc_info=True)
            raise TakeProfitCalculationError(error_msg) from e

    def calculate_trailing_stop(
        self,
        current_price: float,
        entry_price: float,
        highest_price: float,  # For LONG positions
        lowest_price: float,  # For SHORT positions
        position_side: PositionSide,
        trailing_pct: float = 1.0,
    ) -> Optional[float]:
        """
        Calculate trailing stop price based on current market conditions.

        Args:
            current_price: Current market price
            entry_price: Original entry price
            highest_price: Highest price reached (for LONG)
            lowest_price: Lowest price reached (for SHORT)
            position_side: LONG or SHORT position
            trailing_pct: Trailing percentage (default: 1.0%)

        Returns:
            Trailing stop price, or None if not applicable

        Raises:
            TakeProfitCalculationError: If calculation fails
        """
        try:
            trailing_decimal = Decimal(str(trailing_pct)) / Decimal("100")

            if position_side == PositionSide.LONG:
                # Trail from highest price
                extreme_price = Decimal(str(highest_price))
                trailing_distance = extreme_price * trailing_decimal
                trailing_stop = extreme_price - trailing_distance

                # Don't move stop below entry (protect profit)
                entry_decimal = Decimal(str(entry_price))
                if trailing_stop < entry_decimal:
                    trailing_stop = entry_decimal

            else:  # SHORT
                # Trail from lowest price
                extreme_price = Decimal(str(lowest_price))
                trailing_distance = extreme_price * trailing_decimal
                trailing_stop = extreme_price + trailing_distance

                # Don't move stop above entry (protect profit)
                entry_decimal = Decimal(str(entry_price))
                if trailing_stop > entry_decimal:
                    trailing_stop = entry_decimal

            trailing_stop_price = self._round_tp_price(float(trailing_stop))

            logger.debug(
                f"Trailing stop calculated: {trailing_stop_price:.8f} "
                f"(extreme={float(extreme_price):.8f}, "
                f"trail_pct={trailing_pct}%, "
                f"side={position_side.value})"
            )

            return trailing_stop_price

        except Exception as e:
            error_msg = f"Failed to calculate trailing stop: {e}"
            logger.error(error_msg, exc_info=True)
            raise TakeProfitCalculationError(error_msg) from e

    def get_parameters(self) -> Dict[str, Any]:
        """
        Get current take profit calculator parameters.

        Returns:
            Dictionary with current parameters
        """
        return {
            "min_risk_reward_ratio": float(self.min_risk_reward_ratio),
            "partial_tp_percentages": [
                (float(mult), float(pct)) for mult, pct in self.partial_tp_percentages
            ],
            "min_distance_pct": float(self.min_distance_pct),
            "max_distance_pct": float(self.max_distance_pct),
            "precision": self.precision,
        }

    def update_parameters(
        self,
        min_risk_reward_ratio: Optional[float] = None,
        partial_tp_percentages: Optional[List[Tuple[float, float]]] = None,
        min_distance_pct: Optional[float] = None,
        max_distance_pct: Optional[float] = None,
    ) -> None:
        """
        Update take profit calculator parameters.

        Args:
            min_risk_reward_ratio: New minimum RR ratio (None = no change)
            partial_tp_percentages: New partial TP levels (None = no change)
            min_distance_pct: New minimum distance (None = no change)
            max_distance_pct: New maximum distance (None = no change)

        Raises:
            ValueError: If new parameters are invalid
        """
        if min_risk_reward_ratio is not None:
            if min_risk_reward_ratio < 1.0:
                raise ValueError("min_risk_reward_ratio must be >= 1.0")
            self.min_risk_reward_ratio = Decimal(str(min_risk_reward_ratio))
            logger.info(f"Minimum RR ratio updated to {min_risk_reward_ratio}")

        if partial_tp_percentages is not None:
            new_percentages = [
                (Decimal(str(mult)), Decimal(str(pct))) for mult, pct in partial_tp_percentages
            ]
            total_pct = sum(pct for _, pct in new_percentages)
            if abs(total_pct - Decimal("100")) > Decimal("0.01"):
                raise ValueError(
                    f"Partial TP percentages must sum to 100%, got {float(total_pct)}%"
                )
            self.partial_tp_percentages = new_percentages
            logger.info(f"Partial TP percentages updated to {len(new_percentages)} levels")

        if min_distance_pct is not None:
            if min_distance_pct <= 0:
                raise ValueError("min_distance_pct must be positive")
            self.min_distance_pct = Decimal(str(min_distance_pct))
            logger.info(f"Minimum distance updated to {min_distance_pct}%")

        if max_distance_pct is not None:
            if max_distance_pct <= 0:
                raise ValueError("max_distance_pct must be positive")
            self.max_distance_pct = Decimal(str(max_distance_pct))
            logger.info(f"Maximum distance updated to {max_distance_pct}%")

    def update_config(self, updates: Dict[str, Any]) -> None:
        """
        Update configuration from dictionary.

        Args:
            updates: Dictionary of configuration updates
        """
        # Currently no direct mapping from UI config to TakeProfitCalculator params
        # But we implement this for interface consistency
        pass
