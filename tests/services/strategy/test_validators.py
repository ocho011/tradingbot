"""
Tests for Signal Validation
"""

from decimal import Decimal

from src.services.strategy.signal import Signal, SignalDirection
from src.services.strategy.validators import SignalValidator, ValidationResult


class TestValidationResult:
    """Test ValidationResult class"""

    def test_valid_result(self):
        """Test valid validation result"""
        result = ValidationResult(is_valid=True)

        assert result.is_valid
        assert bool(result)
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_invalid_result(self):
        """Test invalid validation result"""
        result = ValidationResult(
            is_valid=False, errors=["Error 1", "Error 2"], warnings=["Warning 1"]
        )

        assert not result.is_valid
        assert not bool(result)
        assert len(result.errors) == 2
        assert len(result.warnings) == 1


class TestSignalValidator:
    """Test SignalValidator functionality"""

    def test_validator_initialization(self):
        """Test validator initialization with custom thresholds"""
        validator = SignalValidator(
            min_confidence=60.0,
            min_risk_reward=1.5,
            max_stop_loss_pct=3.0,
            max_take_profit_pct=15.0,
        )

        assert validator.min_confidence == 60.0
        assert validator.min_risk_reward == 1.5
        assert validator.max_stop_loss_pct == 3.0
        assert validator.max_take_profit_pct == 15.0

    def test_validate_good_signal(self):
        """Test validating a good quality signal"""
        validator = SignalValidator(
            min_confidence=50.0,
            min_risk_reward=1.0,
        )

        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        result = validator.validate(signal)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_low_confidence(self):
        """Test that low confidence signal fails validation"""
        validator = SignalValidator(min_confidence=70.0)

        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=50.0,  # Below threshold
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        result = validator.validate(signal)

        assert not result.is_valid
        assert any("Confidence" in error for error in result.errors)

    def test_validate_poor_risk_reward(self):
        """Test that poor risk-reward ratio fails validation"""
        validator = SignalValidator(min_risk_reward=2.0)

        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("48000"),  # 2000 risk
            take_profit=Decimal("51000"),  # 1000 reward = 0.5 R:R
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        result = validator.validate(signal)

        assert not result.is_valid
        assert any("Risk-reward" in error for error in result.errors)

    def test_validate_excessive_stop_loss(self):
        """Test that excessive stop loss distance fails validation"""
        validator = SignalValidator(max_stop_loss_pct=2.0)

        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("47500"),  # 5% stop loss (exceeds max)
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        result = validator.validate(signal)

        assert not result.is_valid
        assert any("Stop loss" in error for error in result.errors)

    def test_validate_excessive_take_profit_warning(self):
        """Test that excessive take profit creates warning"""
        validator = SignalValidator(max_take_profit_pct=10.0)

        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("56000"),  # 12% take profit (exceeds typical max)
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        result = validator.validate(signal)

        # Should still be valid but with warning
        assert result.is_valid
        assert len(result.warnings) > 0
        assert any("Take profit" in warning for warning in result.warnings)

    def test_validate_multiple_errors(self):
        """Test signal with multiple validation errors"""
        validator = SignalValidator(
            min_confidence=70.0,
            min_risk_reward=2.0,
        )

        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=50.0,  # Too low
            stop_loss=Decimal("48000"),  # Poor R:R
            take_profit=Decimal("51000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        result = validator.validate(signal)

        assert not result.is_valid
        assert len(result.errors) >= 2

    def test_validate_batch(self):
        """Test batch validation of multiple signals"""
        validator = SignalValidator(min_confidence=60.0)

        good_signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        bad_signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=50.0,  # Too low
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        valid, invalid = validator.validate_batch([good_signal, bad_signal, good_signal])

        assert len(valid) == 2
        assert len(invalid) == 1

    def test_update_thresholds(self):
        """Test updating validation thresholds dynamically"""
        validator = SignalValidator(min_confidence=50.0)

        assert validator.min_confidence == 50.0

        validator.update_thresholds(min_confidence=70.0)

        assert validator.min_confidence == 70.0

    def test_price_sanity_check(self):
        """Test that extreme price levels fail validation"""
        validator = SignalValidator()

        # Create signal with stop loss 60% away from entry (should fail sanity check)
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("20000"),  # 60% away!
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        result = validator.validate(signal)

        assert not result.is_valid
        assert any("unreasonable" in error.lower() for error in result.errors)
