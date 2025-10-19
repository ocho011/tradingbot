"""
Candle data model for OHLCV market data.

This module provides the Candle class for representing candlestick data
with validation, normalization, and utility methods.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging

from src.core.constants import TimeFrame


logger = logging.getLogger(__name__)


@dataclass
class Candle:
    """
    Represents a single candlestick (OHLCV) data point.

    Attributes:
        symbol: Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
        timeframe: Candle timeframe (e.g., '1m', '15m', '1h')
        timestamp: Unix timestamp in milliseconds
        open: Opening price
        high: Highest price during the period
        low: Lowest price during the period
        close: Closing price
        volume: Trading volume during the period
        is_closed: Whether this candle is finalized (True) or still being formed (False)
    """

    symbol: str
    timeframe: TimeFrame
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = False

    def __post_init__(self):
        """Validate candle data after initialization."""
        self.validate_ohlcv()
        self.timestamp = self.normalize_timestamp(self.timestamp, self.timeframe)

    def validate_ohlcv(self) -> None:
        """
        Validate OHLCV data integrity.

        Ensures that:
        - All price values are positive
        - Volume is non-negative
        - High is the maximum price
        - Low is the minimum price
        - Open and close are within [low, high] range

        Raises:
            ValueError: If any validation check fails
        """
        # Check for non-positive prices
        if any(price <= 0 for price in [self.open, self.high, self.low, self.close]):
            raise ValueError(
                f"All prices must be positive. Got: open={self.open}, "
                f"high={self.high}, low={self.low}, close={self.close}"
            )

        # Check for negative volume
        if self.volume < 0:
            raise ValueError(f"Volume must be non-negative. Got: {self.volume}")

        # Validate OHLC relationships
        if not (self.low <= self.open <= self.high):
            raise ValueError(
                f"Open price must be within [low, high]. "
                f"Got: low={self.low}, open={self.open}, high={self.high}"
            )

        if not (self.low <= self.close <= self.high):
            raise ValueError(
                f"Close price must be within [low, high]. "
                f"Got: low={self.low}, close={self.close}, high={self.high}"
            )

        # Ensure high is actually the highest
        if not (self.high >= max(self.open, self.close, self.low)):
            raise ValueError(
                f"High must be the maximum price. "
                f"Got: open={self.open}, high={self.high}, low={self.low}, close={self.close}"
            )

        # Ensure low is actually the lowest
        if not (self.low <= min(self.open, self.close, self.high)):
            raise ValueError(
                f"Low must be the minimum price. "
                f"Got: open={self.open}, high={self.high}, low={self.low}, close={self.close}"
            )

    @staticmethod
    def normalize_timestamp(timestamp: int, timeframe: TimeFrame) -> int:
        """
        Normalize timestamp to the start of the candle period.

        Rounds down the timestamp to the beginning of the timeframe period.
        For example, for a 15-minute candle at 10:37:00, returns 10:30:00.

        Args:
            timestamp: Unix timestamp in milliseconds
            timeframe: Timeframe to normalize to

        Returns:
            Normalized timestamp in milliseconds (start of period)

        Example:
            >>> # For 15-minute candle at 2024-01-01 10:37:00
            >>> ts = 1704106620000  # 10:37:00
            >>> normalized = Candle.normalize_timestamp(ts, TimeFrame.M15)
            >>> # Returns 1704106200000 (10:30:00)
        """
        # Get interval in milliseconds
        interval_ms = Candle.get_timeframe_milliseconds(timeframe)

        # Round down to the start of the period
        return (timestamp // interval_ms) * interval_ms

    @staticmethod
    def get_timeframe_milliseconds(timeframe: TimeFrame) -> int:
        """
        Get the duration of a timeframe in milliseconds.

        Args:
            timeframe: TimeFrame to convert

        Returns:
            Duration in milliseconds

        Raises:
            ValueError: If timeframe is not recognized
        """
        # Mapping of timeframes to milliseconds
        timeframe_ms = {
            TimeFrame.M1: 60 * 1000,           # 1 minute
            TimeFrame.M5: 5 * 60 * 1000,       # 5 minutes
            TimeFrame.M15: 15 * 60 * 1000,     # 15 minutes
            TimeFrame.M30: 30 * 60 * 1000,     # 30 minutes
            TimeFrame.H1: 60 * 60 * 1000,      # 1 hour
            TimeFrame.H4: 4 * 60 * 60 * 1000,  # 4 hours
            TimeFrame.D1: 24 * 60 * 60 * 1000,  # 1 day
        }

        if timeframe not in timeframe_ms:
            raise ValueError(f"Unknown timeframe: {timeframe}")

        return timeframe_ms[timeframe]

    @staticmethod
    def calculate_next_candle_time(timestamp: int, timeframe: TimeFrame) -> int:
        """
        Calculate the timestamp for the next candle period.

        Args:
            timestamp: Current timestamp in milliseconds
            timeframe: Timeframe interval

        Returns:
            Timestamp for the start of the next candle period
        """
        normalized = Candle.normalize_timestamp(timestamp, timeframe)
        interval_ms = Candle.get_timeframe_milliseconds(timeframe)
        return normalized + interval_ms

    def is_complete(self, current_time: Optional[int] = None) -> bool:
        """
        Check if this candle period is complete.

        A candle is complete if:
        1. It's explicitly marked as closed, OR
        2. The current time is past the end of this candle's period

        Args:
            current_time: Current timestamp in milliseconds (uses current UTC time if None)

        Returns:
            True if candle is complete, False if still being formed
        """
        if self.is_closed:
            return True

        if current_time is None:
            current_time = int(datetime.now(timezone.utc).timestamp() * 1000)

        next_candle_time = self.calculate_next_candle_time(self.timestamp, self.timeframe)
        return current_time >= next_candle_time

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert candle to dictionary format.

        Returns:
            Dictionary with all candle data including ISO datetime
        """
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe.value,
            'timestamp': self.timestamp,
            'datetime': self.get_datetime_iso(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'is_closed': self.is_closed,
        }

    def get_datetime(self) -> datetime:
        """
        Get datetime object from timestamp.

        Returns:
            Timezone-aware datetime object in UTC
        """
        return datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc)

    def get_datetime_iso(self) -> str:
        """
        Get ISO format datetime string.

        Returns:
            ISO 8601 formatted datetime string
        """
        return self.get_datetime().isoformat()

    def get_body_size(self) -> float:
        """
        Calculate the size of the candle body (difference between open and close).

        Returns:
            Absolute difference between close and open prices
        """
        return abs(self.close - self.open)

    def get_upper_wick(self) -> float:
        """
        Calculate the size of the upper wick.

        Returns:
            Length of upper wick (high - max(open, close))
        """
        return self.high - max(self.open, self.close)

    def get_lower_wick(self) -> float:
        """
        Calculate the size of the lower wick.

        Returns:
            Length of lower wick (min(open, close) - low)
        """
        return min(self.open, self.close) - self.low

    def get_total_range(self) -> float:
        """
        Calculate the total price range of the candle.

        Returns:
            Difference between high and low
        """
        return self.high - self.low

    def is_bullish(self) -> bool:
        """
        Check if candle is bullish (close > open).

        Returns:
            True if bullish, False otherwise
        """
        return self.close > self.open

    def is_bearish(self) -> bool:
        """
        Check if candle is bearish (close < open).

        Returns:
            True if bearish, False otherwise
        """
        return self.close < self.open

    def is_doji(self, threshold_percent: float = 0.1) -> bool:
        """
        Check if candle is a doji (open ≈ close).

        Args:
            threshold_percent: Maximum body size as percentage of total range

        Returns:
            True if body size is within threshold of total range
        """
        total_range = self.get_total_range()
        if total_range == 0:
            return True

        body_percent = (self.get_body_size() / total_range) * 100
        return body_percent <= threshold_percent

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Candle':
        """
        Create Candle instance from dictionary.

        Args:
            data: Dictionary with candle data

        Returns:
            Candle instance

        Raises:
            ValueError: If required fields are missing or invalid
        """
        required_fields = ['symbol', 'timeframe', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
        missing_fields = [field for field in required_fields if field not in data]

        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")

        # Handle timeframe conversion
        timeframe = data['timeframe']
        if isinstance(timeframe, str):
            timeframe = TimeFrame(timeframe)

        return cls(
            symbol=data['symbol'],
            timeframe=timeframe,
            timestamp=int(data['timestamp']),
            open=float(data['open']),
            high=float(data['high']),
            low=float(data['low']),
            close=float(data['close']),
            volume=float(data['volume']),
            is_closed=data.get('is_closed', False)
        )

    @classmethod
    def from_ccxt_ohlcv(cls, symbol: str, timeframe: TimeFrame, ohlcv: list, is_closed: bool = False) -> 'Candle':
        """
        Create Candle from CCXT OHLCV array format.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            ohlcv: CCXT OHLCV array [timestamp, open, high, low, close, volume]
            is_closed: Whether this candle is finalized

        Returns:
            Candle instance

        Raises:
            ValueError: If OHLCV array is invalid
        """
        if not ohlcv or len(ohlcv) < 6:
            raise ValueError(f"Invalid OHLCV array. Expected 6 elements, got {len(ohlcv) if ohlcv else 0}")

        return cls(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=int(ohlcv[0]),
            open=float(ohlcv[1]),
            high=float(ohlcv[2]),
            low=float(ohlcv[3]),
            close=float(ohlcv[4]),
            volume=float(ohlcv[5]),
            is_closed=is_closed
        )

    def __repr__(self) -> str:
        """String representation of candle."""
        return (
            f"Candle(symbol='{self.symbol}', timeframe={self.timeframe.value}, "
            f"datetime='{self.get_datetime_iso()}', "
            f"O={self.open:.2f}, H={self.high:.2f}, L={self.low:.2f}, C={self.close:.2f}, "
            f"V={self.volume:.2f}, closed={self.is_closed})"
        )

    def __str__(self) -> str:
        """Human-readable string representation."""
        direction = "🟢" if self.is_bullish() else "🔴" if self.is_bearish() else "⚪"
        return (
            f"{direction} {self.symbol} {self.timeframe.value} @ {self.get_datetime_iso()}: "
            f"O={self.open:.2f} H={self.high:.2f} L={self.low:.2f} C={self.close:.2f} V={self.volume:.2f}"
        )
