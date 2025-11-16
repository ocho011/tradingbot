"""
Tests for Signal data class and validation
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.services.strategy.signal import Signal, SignalDirection


class TestSignalCreation:
    """Test Signal creation and initialization"""

    def test_create_valid_long_signal(self):
        """Test creating a valid LONG signal"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        assert signal.entry_price == Decimal("50000")
        assert signal.direction == SignalDirection.LONG
        assert signal.confidence == 75.0
        assert signal.stop_loss == Decimal("49000")
        assert signal.take_profit == Decimal("52000")
        assert signal.symbol == "BTCUSDT"
        assert signal.strategy_name == "Strategy_A"
        assert isinstance(signal.timestamp, datetime)
        assert len(signal.signal_id) == 36  # UUID length

    def test_create_valid_short_signal(self):
        """Test creating a valid SHORT signal"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.SHORT,
            confidence=80.0,
            stop_loss=Decimal("51000"),
            take_profit=Decimal("48000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B",
        )

        assert signal.direction == SignalDirection.SHORT
        assert signal.stop_loss > signal.entry_price
        assert signal.take_profit < signal.entry_price

    def test_symbol_uppercased(self):
        """Test that symbol is converted to uppercase"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="btcusdt",  # lowercase
            strategy_name="Strategy_A",
        )

        assert signal.symbol == "BTCUSDT"


class TestSignalValidation:
    """Test Signal validation logic"""

    def test_negative_entry_price(self):
        """Test that negative entry price raises error"""
        with pytest.raises(ValueError, match="Entry price must be positive"):
            Signal(
                entry_price=Decimal("-50000"),
                direction=SignalDirection.LONG,
                confidence=75.0,
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
            )

    def test_invalid_confidence_too_high(self):
        """Test that confidence > 100 raises error"""
        with pytest.raises(ValueError, match="Confidence must be between 0-100"):
            Signal(
                entry_price=Decimal("50000"),
                direction=SignalDirection.LONG,
                confidence=150.0,
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
            )

    def test_invalid_confidence_too_low(self):
        """Test that confidence < 0 raises error"""
        with pytest.raises(ValueError, match="Confidence must be between 0-100"):
            Signal(
                entry_price=Decimal("50000"),
                direction=SignalDirection.LONG,
                confidence=-10.0,
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
            )

    def test_long_stop_loss_above_entry(self):
        """Test that LONG stop loss above entry raises error"""
        with pytest.raises(ValueError, match="stop loss.*must be below entry"):
            Signal(
                entry_price=Decimal("50000"),
                direction=SignalDirection.LONG,
                confidence=75.0,
                stop_loss=Decimal("51000"),  # Above entry!
                take_profit=Decimal("52000"),
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
            )

    def test_long_take_profit_below_entry(self):
        """Test that LONG take profit below entry raises error"""
        with pytest.raises(ValueError, match="take profit.*must be above entry"):
            Signal(
                entry_price=Decimal("50000"),
                direction=SignalDirection.LONG,
                confidence=75.0,
                stop_loss=Decimal("49000"),
                take_profit=Decimal("48000"),  # Below entry!
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
            )

    def test_short_stop_loss_below_entry(self):
        """Test that SHORT stop loss below entry raises error"""
        with pytest.raises(ValueError, match="stop loss.*must be above entry"):
            Signal(
                entry_price=Decimal("50000"),
                direction=SignalDirection.SHORT,
                confidence=75.0,
                stop_loss=Decimal("49000"),  # Below entry!
                take_profit=Decimal("48000"),
                symbol="BTCUSDT",
                strategy_name="Strategy_B",
            )

    def test_short_take_profit_above_entry(self):
        """Test that SHORT take profit above entry raises error"""
        with pytest.raises(ValueError, match="take profit.*must be below entry"):
            Signal(
                entry_price=Decimal("50000"),
                direction=SignalDirection.SHORT,
                confidence=75.0,
                stop_loss=Decimal("51000"),
                take_profit=Decimal("52000"),  # Above entry!
                symbol="BTCUSDT",
                strategy_name="Strategy_B",
            )

    def test_unfavorable_risk_reward_warning(self):
        """Test that unfavorable risk-reward creates warning in metadata"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("48000"),  # 2000 risk
            take_profit=Decimal("51000"),  # 1000 reward - unfavorable!
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        assert "risk_reward_warning" in signal.metadata
        assert "0.50:1" in signal.metadata["risk_reward_warning"]


class TestSignalProperties:
    """Test Signal calculated properties"""

    def test_risk_amount(self):
        """Test risk amount calculation"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        assert signal.risk_amount == Decimal("1000")

    def test_reward_amount(self):
        """Test reward amount calculation"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        assert signal.reward_amount == Decimal("2000")

    def test_risk_reward_ratio(self):
        """Test risk-reward ratio calculation"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        assert signal.risk_reward_ratio == 2.0

    def test_stop_loss_pct(self):
        """Test stop loss percentage calculation"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        assert signal.stop_loss_pct == pytest.approx(2.0, rel=0.01)

    def test_take_profit_pct(self):
        """Test take profit percentage calculation"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        assert signal.take_profit_pct == pytest.approx(4.0, rel=0.01)


class TestSignalSerialization:
    """Test Signal serialization methods"""

    def test_to_dict(self):
        """Test converting signal to dictionary"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        data = signal.to_dict()

        assert data["symbol"] == "BTCUSDT"
        assert data["strategy_name"] == "Strategy_A"
        assert data["entry_price"] == "50000"
        assert data["direction"] == "LONG"
        assert data["confidence"] == 75.0
        assert data["stop_loss"] == "49000"
        assert data["take_profit"] == "52000"
        assert data["risk_reward_ratio"] == 2.0
        assert "signal_id" in data
        assert "timestamp" in data

    def test_repr(self):
        """Test string representation"""
        signal = Signal(
            entry_price=Decimal("50000"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
        )

        repr_str = repr(signal)

        assert "Signal" in repr_str
        assert "BTCUSDT" in repr_str
        assert "LONG" in repr_str
        assert "50000" in repr_str
