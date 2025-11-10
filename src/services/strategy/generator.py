"""
Signal Generator Base Interface

Defines the abstract base class for all trading signal generators.
"""

from abc import ABC, abstractmethod
from typing import Optional, List
from decimal import Decimal
import pandas as pd

from src.services.strategy.signal import Signal
from src.monitoring.metrics import record_signal_generated, ExecutionTimer


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
        self,
        symbol: str,
        current_price: Decimal,
        candles: pd.DataFrame,
        **kwargs
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
        pass

    def generate_signal(
        self,
        symbol: str,
        current_price: Decimal,
        candles: pd.DataFrame,
        **kwargs
    ) -> Optional[Signal]:
        """
        Generate a trading signal based on current market conditions.

        This method wraps the internal implementation with metrics collection.

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
        # Time the strategy execution
        with ExecutionTimer(self.strategy_name, symbol):
            # Call internal implementation
            signal = self._generate_signal_impl(symbol, current_price, candles, **kwargs)

            # Record signal generation metric if signal was generated
            if signal and self._metrics_enabled:
                record_signal_generated(
                    strategy=self.strategy_name,
                    symbol=symbol,
                    direction=signal.direction
                )

            return signal

    @abstractmethod
    def calculate_stop_loss(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
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
        pass

    @abstractmethod
    def calculate_take_profit(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
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
        pass

    @abstractmethod
    def calculate_confidence(
        self,
        candles: pd.DataFrame,
        **kwargs
    ) -> float:
        """
        Calculate confidence score for the signal (0-100).

        Args:
            candles: Historical candle data
            **kwargs: Strategy-specific parameters

        Returns:
            Confidence score between 0 and 100
        """
        pass

    def validate_market_conditions(
        self,
        candles: pd.DataFrame,
        min_candles: int = 100
    ) -> bool:
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
        required_columns = ['open', 'high', 'low', 'close', 'volume']
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

    def _generate_signal_impl(
        self,
        symbol: str,
        current_price: Decimal,
        candles: pd.DataFrame,
        **kwargs
    ) -> Optional[Signal]:
        """
        Generate signal for Strategy A (Conservative).

        This is a placeholder that should be implemented based on
        Task 8.1 specifications.
        """
        # This will be implemented in Task 8.1
        # For now, return None (no signal)
        return None

    def calculate_stop_loss(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
    ) -> Decimal:
        """Calculate conservative stop loss (tight risk management)"""
        # Placeholder - implement in Task 8.1
        atr_multiplier = kwargs.get('atr_multiplier', 1.5)
        # This should use actual ATR calculation
        return entry_price * Decimal('0.98') if direction == 'LONG' else entry_price * Decimal('1.02')

    def calculate_take_profit(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
    ) -> Decimal:
        """Calculate conservative take profit"""
        # Placeholder - implement in Task 8.1
        return entry_price * Decimal('1.03') if direction == 'LONG' else entry_price * Decimal('0.97')

    def calculate_confidence(
        self,
        candles: pd.DataFrame,
        **kwargs
    ) -> float:
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
        self,
        symbol: str,
        current_price: Decimal,
        candles: pd.DataFrame,
        **kwargs
    ) -> Optional[Signal]:
        """
        Generate signal for Strategy B (Aggressive).

        This is a placeholder that should be implemented based on
        Task 8.2 specifications.
        """
        # This will be implemented in Task 8.2
        return None

    def calculate_stop_loss(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
    ) -> Decimal:
        """Calculate aggressive stop loss (wider risk tolerance)"""
        # Placeholder - implement in Task 8.2
        return entry_price * Decimal('0.95') if direction == 'LONG' else entry_price * Decimal('1.05')

    def calculate_take_profit(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
    ) -> Decimal:
        """Calculate aggressive take profit (higher targets)"""
        # Placeholder - implement in Task 8.2
        return entry_price * Decimal('1.06') if direction == 'LONG' else entry_price * Decimal('0.94')

    def calculate_confidence(
        self,
        candles: pd.DataFrame,
        **kwargs
    ) -> float:
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
        self,
        symbol: str,
        current_price: Decimal,
        candles: pd.DataFrame,
        **kwargs
    ) -> Optional[Signal]:
        """
        Generate signal for Strategy C (Hybrid).

        This is a placeholder that should be implemented based on
        Task 8.3 specifications.
        """
        # This will be implemented in Task 8.3
        return None

    def calculate_stop_loss(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
    ) -> Decimal:
        """Calculate hybrid stop loss (adaptive based on conditions)"""
        # Placeholder - implement in Task 8.3
        return entry_price * Decimal('0.97') if direction == 'LONG' else entry_price * Decimal('1.03')

    def calculate_take_profit(
        self,
        entry_price: Decimal,
        direction: str,
        candles: pd.DataFrame,
        **kwargs
    ) -> Decimal:
        """Calculate hybrid take profit (adaptive targets)"""
        # Placeholder - implement in Task 8.3
        return entry_price * Decimal('1.045') if direction == 'LONG' else entry_price * Decimal('0.955')

    def calculate_confidence(
        self,
        candles: pd.DataFrame,
        **kwargs
    ) -> float:
        """Calculate confidence for hybrid strategy"""
        # Placeholder - implement in Task 8.3
        return 75.0
