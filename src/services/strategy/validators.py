"""
Signal Validation Logic

Provides validation for signals before they are published to ensure quality and safety.
"""

import logging
from typing import List, Optional, Tuple

from src.services.strategy.signal import Signal

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of signal validation"""

    def __init__(
        self,
        is_valid: bool,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []

    def __bool__(self) -> bool:
        """Allow using ValidationResult in boolean context"""
        return self.is_valid

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        return (
            f"ValidationResult({status}, errors={len(self.errors)}, warnings={len(self.warnings)})"
        )


class SignalValidator:
    """
    Validates trading signals before publishing.

    Ensures signals meet minimum quality and safety requirements.
    """

    def __init__(
        self,
        min_confidence: float = 50.0,
        min_risk_reward: float = 1.0,
        max_stop_loss_pct: float = 5.0,
        max_take_profit_pct: float = 20.0,
    ):
        """
        Initialize signal validator.

        Args:
            min_confidence: Minimum confidence score to accept (0-100)
            min_risk_reward: Minimum risk-reward ratio (1.0 = 1:1)
            max_stop_loss_pct: Maximum stop loss percentage from entry
            max_take_profit_pct: Maximum take profit percentage from entry
        """
        self.min_confidence = min_confidence
        self.min_risk_reward = min_risk_reward
        self.max_stop_loss_pct = max_stop_loss_pct
        self.max_take_profit_pct = max_take_profit_pct

        logger.info(
            f"SignalValidator initialized: min_confidence={min_confidence}%, "
            f"min_RR={min_risk_reward}, max_SL={max_stop_loss_pct}%, max_TP={max_take_profit_pct}%"
        )

    def validate(self, signal: Signal) -> ValidationResult:
        """
        Validate a signal against all quality and safety checks.

        Args:
            signal: Signal to validate

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors: List[str] = []
        warnings: List[str] = []

        # Check confidence threshold
        if signal.confidence < self.min_confidence:
            errors.append(
                f"Confidence {signal.confidence:.1f}% below minimum {self.min_confidence}%"
            )

        # Check risk-reward ratio
        if signal.risk_reward_ratio < self.min_risk_reward:
            errors.append(
                f"Risk-reward ratio {signal.risk_reward_ratio:.2f} below minimum {self.min_risk_reward}"
            )

        # Check stop loss distance
        if signal.stop_loss_pct > self.max_stop_loss_pct:
            errors.append(
                f"Stop loss {signal.stop_loss_pct:.2f}% exceeds maximum {self.max_stop_loss_pct}%"
            )

        # Check take profit distance
        if signal.take_profit_pct > self.max_take_profit_pct:
            warnings.append(
                f"Take profit {signal.take_profit_pct:.2f}% exceeds typical maximum {self.max_take_profit_pct}%"
            )

        # Validate price consistency (already done in Signal.__post_init__, but double-check)
        try:
            signal._validate_prices()
        except ValueError as e:
            errors.append(f"Price validation failed: {str(e)}")

        # Check for reasonable price levels (not extreme)
        if not self._validate_price_sanity(signal):
            errors.append("Price levels appear unreasonable or extreme")

        # Check metadata for any warnings from signal creation
        if "risk_reward_warning" in signal.metadata:
            warnings.append(signal.metadata["risk_reward_warning"])

        is_valid = len(errors) == 0

        result = ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

        if not is_valid:
            logger.warning(f"Signal validation failed for {signal}: {errors}")
        elif warnings:
            logger.info(f"Signal validation passed with warnings for {signal}: {warnings}")
        else:
            logger.debug(f"Signal validation passed for {signal}")

        return result

    def _validate_price_sanity(self, signal: Signal) -> bool:
        """
        Check if price levels are reasonable (not extreme outliers).

        Args:
            signal: Signal to check

        Returns:
            True if prices appear sane, False otherwise
        """
        # Check that stop loss and take profit are within reasonable bounds
        # (e.g., not more than 50% away from entry)
        entry = float(signal.entry_price)
        stop = float(signal.stop_loss)
        tp = float(signal.take_profit)

        max_deviation = 0.5  # 50%

        if abs(stop - entry) / entry > max_deviation:
            logger.warning(f"Stop loss {stop} is more than 50% from entry {entry}")
            return False

        if abs(tp - entry) / entry > max_deviation:
            logger.warning(f"Take profit {tp} is more than 50% from entry {entry}")
            return False

        # All checks passed
        return True

    def validate_batch(self, signals: List[Signal]) -> Tuple[List[Signal], List[Signal]]:
        """
        Validate a batch of signals.

        Args:
            signals: List of signals to validate

        Returns:
            Tuple of (valid_signals, invalid_signals)
        """
        valid_signals = []
        invalid_signals = []

        for signal in signals:
            result = self.validate(signal)
            if result.is_valid:
                valid_signals.append(signal)
            else:
                invalid_signals.append(signal)
                logger.info(f"Rejected signal {signal.signal_id}: {result.errors}")

        logger.info(
            f"Batch validation: {len(valid_signals)} valid, {len(invalid_signals)} invalid "
            f"out of {len(signals)} total"
        )

        return valid_signals, invalid_signals

    def update_thresholds(
        self,
        min_confidence: Optional[float] = None,
        min_risk_reward: Optional[float] = None,
        max_stop_loss_pct: Optional[float] = None,
        max_take_profit_pct: Optional[float] = None,
    ):
        """
        Update validation thresholds dynamically.

        Args:
            min_confidence: New minimum confidence threshold
            min_risk_reward: New minimum risk-reward ratio
            max_stop_loss_pct: New maximum stop loss percentage
            max_take_profit_pct: New maximum take profit percentage
        """
        if min_confidence is not None:
            self.min_confidence = min_confidence
            logger.info(f"Updated min_confidence to {min_confidence}%")

        if min_risk_reward is not None:
            self.min_risk_reward = min_risk_reward
            logger.info(f"Updated min_risk_reward to {min_risk_reward}")

        if max_stop_loss_pct is not None:
            self.max_stop_loss_pct = max_stop_loss_pct
            logger.info(f"Updated max_stop_loss_pct to {max_stop_loss_pct}%")

        if max_take_profit_pct is not None:
            self.max_take_profit_pct = max_take_profit_pct
            logger.info(f"Updated max_take_profit_pct to {max_take_profit_pct}%")

    def __repr__(self) -> str:
        return (
            f"SignalValidator(min_conf={self.min_confidence}%, "
            f"min_RR={self.min_risk_reward}, "
            f"max_SL={self.max_stop_loss_pct}%, max_TP={self.max_take_profit_pct}%)"
        )
