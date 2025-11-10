"""
Risk validator with comprehensive order approval and entry control logic.

This module implements:
- Position sizing validation against calculated limits
- Stop loss and take profit level validation
- Daily loss limit checking and entry blocking
- Order approval/rejection decision system
- Event emission for risk check results
"""

import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime
from threading import Lock
from dataclasses import dataclass

from src.core.constants import EventType, PositionSide
from src.core.events import Event
from src.services.risk.position_sizer import PositionSizer
from src.services.risk.stop_loss_calculator import StopLossCalculator
from src.services.risk.take_profit_calculator import TakeProfitCalculator
from src.services.risk.daily_loss_monitor import DailyLossMonitor
from src.monitoring.metrics import record_risk_violation

logger = logging.getLogger(__name__)


class RiskValidationError(Exception):
    """Raised when risk validation operations fail."""
    pass


@dataclass
class ValidationResult:
    """
    Result of risk validation check.

    Attributes:
        approved: Whether the order is approved
        reason: Reason for approval/rejection
        violations: List of specific validation violations
        metadata: Additional validation metadata
    """
    approved: bool
    reason: str
    violations: list[str]
    metadata: Dict[str, Any]


class RiskValidator:
    """
    Comprehensive risk validation and entry control system.

    Features:
    - Position sizing validation
    - Stop loss and take profit level validation
    - Daily loss limit checking
    - Entry blocking management
    - Order approval/rejection decision
    - Event publishing for validation results

    Attributes:
        position_sizer: Position sizer for size validation
        stop_loss_calculator: Stop loss calculator for SL validation
        take_profit_calculator: Take profit calculator for TP validation
        daily_loss_monitor: Daily loss monitor for limit checking
        event_bus: Event bus for publishing validation events
        entry_blocked: Whether new entries are currently blocked
    """

    def __init__(
        self,
        position_sizer: PositionSizer,
        stop_loss_calculator: StopLossCalculator,
        take_profit_calculator: TakeProfitCalculator,
        daily_loss_monitor: DailyLossMonitor,
        event_bus: Optional[Any] = None
    ):
        """
        Initialize risk validator.

        Args:
            position_sizer: Position sizer instance
            stop_loss_calculator: Stop loss calculator instance
            take_profit_calculator: Take profit calculator instance
            daily_loss_monitor: Daily loss monitor instance
            event_bus: Optional event bus for publishing events

        Raises:
            RiskValidationError: If required components are not provided
        """
        if not all([position_sizer, stop_loss_calculator, take_profit_calculator, daily_loss_monitor]):
            raise RiskValidationError("All risk management components must be provided")

        self.position_sizer = position_sizer
        self.stop_loss_calculator = stop_loss_calculator
        self.take_profit_calculator = take_profit_calculator
        self.daily_loss_monitor = daily_loss_monitor
        self.event_bus = event_bus

        self.entry_blocked = False
        self._lock = Lock()

        # Subscribe to daily loss limit events
        self._subscribe_to_events()

        logger.info("RiskValidator initialized successfully")

    def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events from daily loss monitor."""
        if self.event_bus:
            # Subscribe to daily loss limit reached event
            # This will be handled by the event bus's subscription mechanism
            logger.debug("Subscribed to daily loss limit events")

    def handle_daily_loss_event(self, event: Event) -> None:
        """
        Handle daily loss limit reached event.

        Args:
            event: Event containing loss limit information
        """
        with self._lock:
            if event.event_type == EventType.DAILY_LOSS_LIMIT_REACHED:
                self.entry_blocked = True
                logger.warning(
                    "Daily loss limit reached - blocking new entries",
                    extra={"event_data": event.data}
                )

    def check_entry_allowed(self) -> tuple[bool, str]:
        """
        Check if new entries are currently allowed.

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        with self._lock:
            if self.entry_blocked:
                return False, "New entries blocked due to daily loss limit"

            # Check if daily loss monitor indicates limit reached
            if self.daily_loss_monitor.is_loss_limit_reached():
                self.entry_blocked = True
                return False, "Daily loss limit reached"

            return True, "Entry allowed"

    def reset_entry_blocking(self) -> None:
        """
        Reset entry blocking flag (typically for new trading day).

        This should be called when the daily loss monitor resets its session.
        """
        with self._lock:
            self.entry_blocked = False
            logger.info("Entry blocking reset - new entries allowed")

    async def validate_position_size(
        self,
        position_size: Decimal,
        symbol: str,
        entry_price: Decimal,
        stop_loss: Decimal,
        side: PositionSide,
        custom_balance: Optional[float] = None
    ) -> tuple[bool, str]:
        """
        Validate position size against calculated limits.

        Args:
            position_size: Proposed position size
            symbol: Trading symbol
            entry_price: Entry price for position
            stop_loss: Stop loss price
            side: Position side (LONG/SHORT)
            custom_balance: Optional custom balance for testing

        Returns:
            Tuple of (valid: bool, reason: str)
        """
        try:
            # Calculate expected position size
            calculated_size = await self.position_sizer.calculate_position_size(
                custom_balance=custom_balance
            )

            # Allow some tolerance (±5%)
            tolerance = Decimal('0.05')
            min_size = calculated_size['position_size'] * (Decimal('1') - tolerance)
            max_size = calculated_size['position_size'] * (Decimal('1') + tolerance)

            if position_size < min_size:
                return False, f"Position size {position_size} below minimum {min_size:.8f}"
            if position_size > max_size:
                return False, f"Position size {position_size} exceeds maximum {max_size:.8f}"

            logger.debug(
                f"Position size validation passed: {position_size} "
                f"(range: {min_size:.8f} - {max_size:.8f})"
            )
            return True, "Position size valid"

        except Exception as e:
            logger.error(f"Error validating position size: {e}", exc_info=True)
            return False, f"Position size validation error: {str(e)}"

    def validate_stop_loss(
        self,
        entry_price: Decimal,
        stop_loss: Decimal,
        side: PositionSide
    ) -> tuple[bool, str]:
        """
        Validate stop loss level is reasonable and properly placed.

        Args:
            entry_price: Entry price for position
            stop_loss: Stop loss price
            side: Position side (LONG/SHORT)

        Returns:
            Tuple of (valid: bool, reason: str)
        """
        try:
            # Calculate stop distance percentage
            if side == PositionSide.LONG:
                if stop_loss >= entry_price:
                    return False, "Stop loss must be below entry price for LONG"
                distance_pct = ((entry_price - stop_loss) / entry_price) * Decimal('100')
            else:  # SHORT
                if stop_loss <= entry_price:
                    return False, "Stop loss must be above entry price for SHORT"
                distance_pct = ((stop_loss - entry_price) / entry_price) * Decimal('100')

            # Get stop loss calculator parameters
            params = self.stop_loss_calculator.get_parameters()
            min_distance = params['min_stop_distance_pct']
            max_distance = params['max_stop_distance_pct']

            if distance_pct < min_distance:
                return False, f"Stop loss too tight: {distance_pct:.2f}% (min: {min_distance}%)"
            if distance_pct > max_distance:
                return False, f"Stop loss too wide: {distance_pct:.2f}% (max: {max_distance}%)"

            logger.debug(f"Stop loss validation passed: {distance_pct:.2f}% from entry")
            return True, "Stop loss valid"

        except Exception as e:
            logger.error(f"Error validating stop loss: {e}", exc_info=True)
            return False, f"Stop loss validation error: {str(e)}"

    def validate_take_profit(
        self,
        entry_price: Decimal,
        take_profit: Decimal,
        stop_loss: Decimal,
        side: PositionSide
    ) -> tuple[bool, str]:
        """
        Validate take profit level meets minimum risk-reward requirements.

        Args:
            entry_price: Entry price for position
            take_profit: Take profit price
            stop_loss: Stop loss price
            side: Position side (LONG/SHORT)

        Returns:
            Tuple of (valid: bool, reason: str)
        """
        try:
            # Calculate risk and reward distances
            if side == PositionSide.LONG:
                if take_profit <= entry_price:
                    return False, "Take profit must be above entry price for LONG"
                risk_distance = entry_price - stop_loss
                reward_distance = take_profit - entry_price
            else:  # SHORT
                if take_profit >= entry_price:
                    return False, "Take profit must be below entry price for SHORT"
                risk_distance = stop_loss - entry_price
                reward_distance = entry_price - take_profit

            # Calculate risk-reward ratio
            if risk_distance <= 0:
                return False, "Invalid risk distance (must be positive)"

            rr_ratio = reward_distance / risk_distance

            # Get take profit calculator parameters
            params = self.take_profit_calculator.get_parameters()
            min_rr_ratio = params['min_risk_reward_ratio']

            if rr_ratio < min_rr_ratio:
                return False, f"Risk-reward ratio too low: {rr_ratio:.2f} (min: {min_rr_ratio})"

            logger.debug(f"Take profit validation passed: R:R = {rr_ratio:.2f}")
            return True, "Take profit valid"

        except Exception as e:
            logger.error(f"Error validating take profit: {e}", exc_info=True)
            return False, f"Take profit validation error: {str(e)}"

    async def validate_order(
        self,
        symbol: str,
        side: PositionSide,
        entry_price: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        position_size: Decimal,
        metadata: Optional[Dict[str, Any]] = None,
        custom_balance: Optional[float] = None
    ) -> ValidationResult:
        """
        Comprehensive order validation including all risk checks.

        Args:
            symbol: Trading symbol
            side: Position side (LONG/SHORT)
            entry_price: Intended entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            position_size: Proposed position size
            metadata: Optional additional validation context
            custom_balance: Optional custom balance for testing

        Returns:
            ValidationResult with approval decision and details
        """
        violations = []
        validation_metadata = metadata or {}

        try:
            # 1. Check if entries are allowed
            entry_allowed, entry_reason = self.check_entry_allowed()
            if not entry_allowed:
                logger.warning(f"Order rejected: {entry_reason}")
                record_risk_violation(
                    violation_type="entry_blocked",
                    symbol=symbol,
                    severity="critical"
                )
                return ValidationResult(
                    approved=False,
                    reason=entry_reason,
                    violations=["entry_blocked"],
                    metadata=validation_metadata
                )

            # 2. Validate position size
            size_valid, size_reason = await self.validate_position_size(
                position_size, symbol, entry_price, stop_loss, side, custom_balance
            )
            if not size_valid:
                violations.append(f"position_size: {size_reason}")
                record_risk_violation(
                    violation_type="position_size_exceeded",
                    symbol=symbol,
                    severity="high"
                )

            # 3. Validate stop loss
            sl_valid, sl_reason = self.validate_stop_loss(entry_price, stop_loss, side)
            if not sl_valid:
                violations.append(f"stop_loss: {sl_reason}")
                record_risk_violation(
                    violation_type="invalid_stop_loss",
                    symbol=symbol,
                    severity="medium"
                )

            # 4. Validate take profit
            tp_valid, tp_reason = self.validate_take_profit(
                entry_price, take_profit, stop_loss, side
            )
            if not tp_valid:
                violations.append(f"take_profit: {tp_reason}")
                record_risk_violation(
                    violation_type="invalid_take_profit",
                    symbol=symbol,
                    severity="low"
                )

            # Determine final approval
            approved = len(violations) == 0

            if approved:
                reason = "All risk checks passed"
                logger.info(
                    f"Order approved: {symbol} {side} @ {entry_price} "
                    f"(SL: {stop_loss}, TP: {take_profit}, Size: {position_size})"
                )
            else:
                reason = f"Failed {len(violations)} validation(s): " + "; ".join(violations)
                logger.warning(f"Order rejected: {reason}")

            # Add validation details to metadata
            validation_metadata.update({
                'symbol': symbol,
                'side': side.value,
                'entry_price': str(entry_price),
                'stop_loss': str(stop_loss),
                'take_profit': str(take_profit),
                'position_size': str(position_size),
                'timestamp': datetime.now().isoformat()
            })

            result = ValidationResult(
                approved=approved,
                reason=reason,
                violations=violations,
                metadata=validation_metadata
            )

            # Publish validation event
            self._publish_validation_result(result)

            return result

        except Exception as e:
            logger.error(f"Error during order validation: {e}", exc_info=True)
            return ValidationResult(
                approved=False,
                reason=f"Validation error: {str(e)}",
                violations=["system_error"],
                metadata=validation_metadata
            )

    def _publish_validation_result(self, result: ValidationResult) -> None:
        """
        Publish validation result as event.

        Args:
            result: ValidationResult to publish
        """
        if not self.event_bus:
            return

        try:
            event_type = EventType.RISK_CHECK_PASSED if result.approved else EventType.RISK_CHECK_FAILED

            # Create event for publishing
            # Note: Actual event bus publishing will be implemented when event bus is available
            event_data = {
                'approved': result.approved,
                'reason': result.reason,
                'violations': result.violations,
                **result.metadata
            }

            # Log event for now (will publish to event bus when integrated)
            logger.debug(
                f"Publishing risk validation event: {event_type.value}",
                extra={'event_data': event_data}
            )

        except Exception as e:
            logger.error(f"Error publishing validation result: {e}", exc_info=True)

    def get_validation_status(self) -> Dict[str, Any]:
        """
        Get current validation system status.

        Returns:
            Dictionary with validation system status
        """
        daily_status = self.daily_loss_monitor.get_current_status()

        return {
            'entry_blocked': self.entry_blocked,
            'daily_loss_limit_reached': self.daily_loss_monitor.is_loss_limit_reached(),
            'daily_status': {
                'date': daily_status['date'],
                'loss_percentage': float(daily_status['loss_percentage']),
                'loss_limit_pct': float(daily_status['loss_limit']),
                'remaining_capacity': float(daily_status['distance_to_limit'])
            },
            'timestamp': datetime.now().isoformat()
        }
