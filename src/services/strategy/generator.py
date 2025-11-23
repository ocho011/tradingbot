"""
Signal Generator Base Interface

Defines the abstract base class for all trading signal generators.
"""

import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

import pandas as pd

from src.core.constants import PositionSide
from src.monitoring.metrics import ExecutionTimer, record_signal_generated
from src.monitoring.tracing import get_tracer
from src.services.strategy.signal import Signal, SignalDirection
from src.strategies.strategy_a import StrategyA
from src.strategies.strategy_a import StrategyA

logger = logging.getLogger(__name__)


class SignalGenerator(ABC):
    """
    Abstract base class for signal generators.

    Each trading strategy should implement this interface to generate signals
    based on market data and strategy-specific logic.
    """

    def __init__(self, strategy_name: str):
        """
        Initialize signal generator.

        Args:
            strategy_name: Name of the strategy (e.g., 'Strategy_A', 'Strategy_B')
        """
        self.strategy_name = strategy_name
        self._last_signal: Optional[Signal] = None
        self._metrics_enabled = True  # Enable metrics collection by default

    @abstractmethod
    def _generate_signal_impl(
        self, symbol: str, current_price: Decimal, candles: pd.DataFrame, **kwargs
    ) -> Optional[Signal]:
        """
        Internal signal generation implementation.

        Subclasses should implement this method instead of generate_signal
        to ensure metrics collection is applied consistently.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            current_price: Current market price
            candles: Historical candle data (OHLCV)
            **kwargs: Additional strategy-specific parameters

        Returns:
            Signal object if conditions are met, None otherwise

        Raises:
            ValueError: If input data is invalid
        """

    def generate_signal(
        self, symbol: str, current_price: Decimal, candles: pd.DataFrame, **kwargs
    ) -> Optional[Signal]:
        """
        Generate a trading signal based on current market conditions.

        This method wraps the internal implementation with metrics collection and tracing.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            current_price: Current market price
            candles: Historical candle data (OHLCV)
            **kwargs: Additional strategy-specific parameters

        Returns:
            Signal object if conditions are met, None otherwise

        Raises:
            ValueError: If input data is invalid
        """
        tracer = get_tracer()

        # Create span for signal generation
        with tracer.start_span(
            f"signal_generation.{self.strategy_name}",
            attributes={
                "strategy.name": self.strategy_name,
                "trading.symbol": symbol,
                "trading.price": str(current_price),
                "market.candles_count": len(candles) if candles is not None else 0,
            },
        ) as span:
            # Time the strategy execution
            with ExecutionTimer(self.strategy_name, symbol):
                # Call internal implementation
                signal = self._generate_signal_impl(symbol, current_price, candles, **kwargs)

                # Add signal result to span
                if span:
                    if signal:
                        span.set_attribute("signal.generated", True)
                        span.set_attribute("signal.direction", signal.direction)
                        span.set_attribute("signal.confidence", signal.confidence)
                        span.set_attribute("signal.entry_price", str(signal.entry_price))
                        tracer.add_event(
                            "signal_generated",
                            {
                                "direction": signal.direction,
                                "symbol": symbol,
                                "strategy": self.strategy_name,
                            },
                        )
                    else:
                        span.set_attribute("signal.generated", False)

                # Record signal generation metric if signal was generated
                if signal and self._metrics_enabled:
                    record_signal_generated(
                        strategy=self.strategy_name, symbol=symbol, direction=signal.direction
                    )

                return signal

    @abstractmethod
    def calculate_stop_loss(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """
        Calculate stop loss level for the signal.

        Args:
            entry_price: Proposed entry price
            direction: Trade direction ('LONG' or 'SHORT')
            candles: Historical candle data
            **kwargs: Strategy-specific parameters

        Returns:
            Stop loss price level
        """

    @abstractmethod
    def calculate_take_profit(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """
        Calculate take profit level for the signal.

        Args:
            entry_price: Proposed entry price
            direction: Trade direction ('LONG' or 'SHORT')
            candles: Historical candle data
            **kwargs: Strategy-specific parameters

        Returns:
            Take profit price level
        """

    @abstractmethod
    def calculate_confidence(self, candles: pd.DataFrame, **kwargs) -> float:
        """
        Calculate confidence score for the signal (0-100).

        Args:
            candles: Historical candle data
            **kwargs: Strategy-specific parameters

        Returns:
            Confidence score between 0 and 100
        """

    def validate_market_conditions(self, candles: pd.DataFrame, min_candles: int = 100) -> bool:
        """
        Validate that market conditions are suitable for signal generation.

        Args:
            candles: Historical candle data
            min_candles: Minimum number of candles required

        Returns:
            True if conditions are valid, False otherwise
        """
        if candles is None or candles.empty:
            return False

        if len(candles) < min_candles:
            return False

        # Check for required columns
        required_columns = ["open", "high", "low", "close", "volume"]
        if not all(col in candles.columns for col in required_columns):
            return False

        # Check for null values
        if candles[required_columns].isnull().any().any():
            return False

        return True

    @property
    def last_signal(self) -> Optional[Signal]:
        """Get the last generated signal"""
        return self._last_signal

    def __repr__(self) -> str:
        """String representation"""
        return f"{self.__class__.__name__}(strategy={self.strategy_name})"


class StrategyAGenerator(SignalGenerator):
    """
    Conservative Strategy A signal generator.

    Implements conservative entry logic with tight risk management.
    """

    def __init__(self):
        super().__init__("Strategy_A_Conservative")
        self.strategy = StrategyA()

    def _generate_signal_impl(
        self, symbol: str, current_price: Decimal, candles: pd.DataFrame, **kwargs
    ) -> Optional[Signal]:
        """
        Generate signal for Strategy A (Conservative).
        """
        # Extract indicators from kwargs
        indicators = kwargs.get("indicators")
        if not indicators:
            return None

        # Prepare market data for StrategyA
        market_data = {
            "indicators": indicators,
            "current_price": float(current_price),
            "symbol": symbol,
        }

        # Analyze using StrategyA
        trading_signal = self.strategy.analyze(market_data)

        if not trading_signal:
            return None

        # Convert TradingSignal to Signal
        direction = (
            SignalDirection.LONG
            if trading_signal.direction == PositionSide.LONG
            else SignalDirection.SHORT
        )

        return Signal(
            entry_price=Decimal(str(trading_signal.entry_price)),
            direction=direction,
            confidence=trading_signal.confidence * 100,  # Convert 0-1 to 0-100
            stop_loss=Decimal(str(trading_signal.stop_loss)),
            take_profit=Decimal(str(trading_signal.take_profit)),
            symbol=symbol,
            strategy_name=self.strategy_name,
            metadata=trading_signal.metadata or {},
        )

    def calculate_stop_loss(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """Calculate conservative stop loss (tight risk management)"""
        # Placeholder - implement in Task 8.1
        kwargs.get("atr_multiplier", 1.5)
        # This should use actual ATR calculation
        return (
            entry_price * Decimal("0.98") if direction == "LONG" else entry_price * Decimal("1.02")
        )

    def calculate_take_profit(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """Calculate conservative take profit"""
        # Placeholder - implement in Task 8.1
        return (
            entry_price * Decimal("1.03") if direction == "LONG" else entry_price * Decimal("0.97")
        )

    def calculate_confidence(self, candles: pd.DataFrame, **kwargs) -> float:
        """Calculate confidence for conservative strategy"""
        # Placeholder - implement in Task 8.1
        return 70.0


class StrategyBGenerator(SignalGenerator):
    """
    Aggressive Strategy B signal generator.

    Implements aggressive entry logic with wider risk tolerance.
    """

    def __init__(self):
        super().__init__("Strategy_B_Aggressive")

    def _generate_signal_impl(
        self, symbol: str, current_price: Decimal, candles: pd.DataFrame, **kwargs
    ) -> Optional[Signal]:
        """
        Generate signal for Strategy B (Aggressive).

        This is a placeholder that should be implemented based on
        Task 8.2 specifications.
        """
        # This will be implemented in Task 8.2
        return None

    def calculate_stop_loss(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """Calculate aggressive stop loss (wider risk tolerance)"""
        # Placeholder - implement in Task 8.2
        return (
            entry_price * Decimal("0.95") if direction == "LONG" else entry_price * Decimal("1.05")
        )

    def calculate_take_profit(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """Calculate aggressive take profit (higher targets)"""
        # Placeholder - implement in Task 8.2
        return (
            entry_price * Decimal("1.06") if direction == "LONG" else entry_price * Decimal("0.94")
        )

    def calculate_confidence(self, candles: pd.DataFrame, **kwargs) -> float:
        """Calculate confidence for aggressive strategy"""
        # Placeholder - implement in Task 8.2
        return 65.0


class StrategyCGenerator(SignalGenerator):
    """
    Hybrid Strategy C signal generator.

    Implements hybrid approach combining conservative and aggressive elements.
    """

    def __init__(self):
        super().__init__("Strategy_C_Hybrid")

    def _generate_signal_impl(
        self, symbol: str, current_price: Decimal, candles: pd.DataFrame, **kwargs
    ) -> Optional[Signal]:
        """
        Generate signal for Strategy C (Hybrid).

        This is a placeholder that should be implemented based on
        Task 8.3 specifications.
        """
        # This will be implemented in Task 8.3
        return None

    def calculate_stop_loss(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """Calculate hybrid stop loss (adaptive based on conditions)"""
        # Placeholder - implement in Task 8.3
        return (
            entry_price * Decimal("0.97") if direction == "LONG" else entry_price * Decimal("1.03")
        )

    def calculate_take_profit(
        self, entry_price: Decimal, direction: str, candles: pd.DataFrame, **kwargs
    ) -> Decimal:
        """Calculate hybrid take profit (adaptive targets)"""
        # Placeholder - implement in Task 8.3
        return (
            entry_price * Decimal("1.045")
            if direction == "LONG"
            else entry_price * Decimal("0.955")
        )

    def calculate_confidence(self, candles: pd.DataFrame, **kwargs) -> float:
        """Calculate confidence for hybrid strategy"""
        # Placeholder - implement in Task 8.3
        return 75.0
