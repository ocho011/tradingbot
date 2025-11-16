"""
Trading Signal Data Class

Defines the core Signal data structure with validation and metadata.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict


class SignalDirection(Enum):
    """Trading signal direction"""

    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Signal:
    """
    Trading signal with entry price, direction, confidence, and risk management levels.

    Attributes:
        entry_price: Precise entry price for the trade
        direction: Trade direction (LONG/SHORT)
        confidence: Signal confidence score (0-100)
        stop_loss: Risk management stop loss level
        take_profit: Profit target level
        timestamp: Signal generation time
        signal_id: Unique identifier for the signal
        strategy_name: Name of the strategy that generated the signal
        symbol: Trading pair symbol (e.g., 'BTCUSDT')
        metadata: Additional context and strategy-specific data
    """

    entry_price: Decimal
    direction: SignalDirection
    confidence: float
    stop_loss: Decimal
    take_profit: Decimal
    symbol: str
    strategy_name: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate signal fields after initialization"""
        self._validate_prices()
        self._validate_confidence()
        self._validate_risk_reward()
        self._validate_symbol()

    def _validate_prices(self):
        """Validate price fields"""
        if self.entry_price <= 0:
            raise ValueError(f"Entry price must be positive, got {self.entry_price}")

        if self.stop_loss <= 0:
            raise ValueError(f"Stop loss must be positive, got {self.stop_loss}")

        if self.take_profit <= 0:
            raise ValueError(f"Take profit must be positive, got {self.take_profit}")

        # Validate stop loss position relative to entry
        if self.direction == SignalDirection.LONG:
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"For LONG, stop loss ({self.stop_loss}) must be below entry ({self.entry_price})"
                )
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"For LONG, take profit ({self.take_profit}) must be above entry ({self.entry_price})"
                )
        else:  # SHORT
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"For SHORT, stop loss ({self.stop_loss}) must be above entry ({self.entry_price})"
                )
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"For SHORT, take profit ({self.take_profit}) must be below entry ({self.entry_price})"
                )

    def _validate_confidence(self):
        """Validate confidence score bounds"""
        if not 0 <= self.confidence <= 100:
            raise ValueError(f"Confidence must be between 0-100, got {self.confidence}")

    def _validate_risk_reward(self):
        """Validate risk-reward ratio is reasonable"""
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)

        if risk == 0:
            raise ValueError("Risk (distance to stop loss) cannot be zero")

        risk_reward_ratio = float(reward / risk)

        # Warn if risk-reward ratio is unfavorable (less than 1:1)
        if risk_reward_ratio < 1.0:
            # Store warning in metadata rather than raising
            self.metadata["risk_reward_warning"] = (
                f"Unfavorable risk-reward ratio: {risk_reward_ratio:.2f}:1"
            )

    def _validate_symbol(self):
        """Validate symbol format"""
        if not self.symbol or not isinstance(self.symbol, str):
            raise ValueError(f"Symbol must be a non-empty string, got {self.symbol}")

        # Ensure uppercase for consistency
        self.symbol = self.symbol.upper()

    @property
    def risk_amount(self) -> Decimal:
        """Calculate risk amount (distance to stop loss)"""
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_amount(self) -> Decimal:
        """Calculate reward amount (distance to take profit)"""
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward_ratio(self) -> float:
        """Calculate risk-reward ratio"""
        if self.risk_amount == 0:
            return 0.0
        return float(self.reward_amount / self.risk_amount)

    @property
    def stop_loss_pct(self) -> float:
        """Calculate stop loss percentage from entry"""
        return float(abs(self.stop_loss - self.entry_price) / self.entry_price * 100)

    @property
    def take_profit_pct(self) -> float:
        """Calculate take profit percentage from entry"""
        return float(abs(self.take_profit - self.entry_price) / self.entry_price * 100)

    def to_dict(self) -> Dict[str, Any]:
        """Convert signal to dictionary for serialization"""
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "entry_price": str(self.entry_price),
            "direction": self.direction.value,
            "confidence": self.confidence,
            "stop_loss": str(self.stop_loss),
            "take_profit": str(self.take_profit),
            "risk_amount": str(self.risk_amount),
            "reward_amount": str(self.reward_amount),
            "risk_reward_ratio": self.risk_reward_ratio,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        """String representation for logging"""
        return (
            f"Signal(id={self.signal_id[:8]}..., {self.symbol}, "
            f"{self.direction.value}, entry={self.entry_price}, "
            f"confidence={self.confidence:.1f}%, R:R={self.risk_reward_ratio:.2f})"
        )
