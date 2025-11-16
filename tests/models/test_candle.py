"""
Unit tests for the Candle data model.

Tests cover:
- Candle creation and validation
- Timestamp normalization
- Time calculation utilities
- Data integrity checks
- Conversion methods
- Utility methods
"""

from datetime import datetime, timezone

import pytest

from src.core.constants import TimeFrame
from src.models.candle import Candle


class TestCandleCreation:
    """Tests for Candle instance creation."""

    def test_create_valid_candle(self):
        """Test creating a valid candle with proper OHLCV data."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,  # 2024-01-01 10:30:00
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        assert candle.symbol == "BTCUSDT"
        assert candle.timeframe == TimeFrame.M15
        assert candle.open == 42000.0
        assert candle.high == 42500.0
        assert candle.low == 41800.0
        assert candle.close == 42300.0
        assert candle.volume == 150.5
        assert candle.is_closed is False

    def test_create_candle_with_closed_flag(self):
        """Test creating a closed candle."""
        candle = Candle(
            symbol="ETHUSDT",
            timeframe=TimeFrame.M1,
            timestamp=1704106200000,
            open=2200.0,
            high=2210.0,
            low=2195.0,
            close=2205.0,
            volume=50.0,
            is_closed=True,
        )

        assert candle.is_closed is True


class TestCandleValidation:
    """Tests for OHLCV data validation."""

    def test_validation_rejects_negative_prices(self):
        """Test that negative prices are rejected."""
        with pytest.raises(ValueError, match="All prices must be positive"):
            Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1704106200000,
                open=-42000.0,  # Invalid
                high=42500.0,
                low=41800.0,
                close=42300.0,
                volume=150.5,
            )

    def test_validation_rejects_zero_prices(self):
        """Test that zero prices are rejected."""
        with pytest.raises(ValueError, match="All prices must be positive"):
            Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1704106200000,
                open=42000.0,
                high=0.0,  # Invalid
                low=41800.0,
                close=42300.0,
                volume=150.5,
            )

    def test_validation_rejects_negative_volume(self):
        """Test that negative volume is rejected."""
        with pytest.raises(ValueError, match="Volume must be non-negative"):
            Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1704106200000,
                open=42000.0,
                high=42500.0,
                low=41800.0,
                close=42300.0,
                volume=-150.5,  # Invalid
            )

    def test_validation_rejects_invalid_ohlc_relationships(self):
        """Test that invalid OHLC relationships are rejected."""
        # Open above high
        with pytest.raises(ValueError):
            Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1704106200000,
                open=43000.0,  # Invalid: above high
                high=42500.0,
                low=41800.0,
                close=42300.0,
                volume=150.5,
            )

        # Close below low
        with pytest.raises(ValueError):
            Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1704106200000,
                open=42000.0,
                high=42500.0,
                low=41800.0,
                close=41700.0,  # Invalid: below low
                volume=150.5,
            )

        # Close above high (which makes it the new high, should fail)
        with pytest.raises(ValueError):
            Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1704106200000,
                open=42000.0,
                high=42300.0,
                low=41800.0,
                close=42500.0,  # Invalid: above high
                volume=150.5,
            )


class TestTimestampNormalization:
    """Tests for timestamp normalization."""

    def test_normalize_timestamp_1m(self):
        """Test normalizing timestamps for 1-minute candles."""
        # 10:37:25 -> 10:37:00
        ts = 1704106645000  # Random seconds
        normalized = Candle.normalize_timestamp(ts, TimeFrame.M1)
        expected = 1704106620000  # Start of minute

        assert normalized == expected

    def test_normalize_timestamp_15m(self):
        """Test normalizing timestamps for 15-minute candles."""
        # 10:52:00 -> 10:45:00
        ts = 1704106320000  # 10:52:00
        normalized = Candle.normalize_timestamp(ts, TimeFrame.M15)
        expected = 1704105900000  # 10:45:00

        assert normalized == expected

    def test_normalize_timestamp_1h(self):
        """Test normalizing timestamps for 1-hour candles."""
        # 10:37:00 -> 10:00:00
        ts = 1704106620000
        normalized = Candle.normalize_timestamp(ts, TimeFrame.H1)
        expected = 1704103200000  # 10:00:00

        assert normalized == expected

    def test_normalize_timestamp_1d(self):
        """Test normalizing timestamps for daily candles."""
        # 2024-01-01 10:37:00 -> 2024-01-01 00:00:00
        ts = 1704106620000
        normalized = Candle.normalize_timestamp(ts, TimeFrame.D1)
        expected = 1704067200000  # Midnight UTC

        assert normalized == expected

    def test_timestamp_auto_normalized_on_creation(self):
        """Test that timestamps are automatically normalized when creating candles."""
        # Create candle with non-normalized timestamp
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106320000,  # 10:52:00
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        # Should be normalized to 10:45:00
        assert candle.timestamp == 1704105900000


class TestTimeCalculations:
    """Tests for time-related calculations."""

    def test_get_timeframe_milliseconds(self):
        """Test converting timeframes to milliseconds."""
        assert Candle.get_timeframe_milliseconds(TimeFrame.M1) == 60_000
        assert Candle.get_timeframe_milliseconds(TimeFrame.M5) == 300_000
        assert Candle.get_timeframe_milliseconds(TimeFrame.M15) == 900_000
        assert Candle.get_timeframe_milliseconds(TimeFrame.M30) == 1_800_000
        assert Candle.get_timeframe_milliseconds(TimeFrame.H1) == 3_600_000
        assert Candle.get_timeframe_milliseconds(TimeFrame.H4) == 14_400_000
        assert Candle.get_timeframe_milliseconds(TimeFrame.D1) == 86_400_000

    def test_calculate_next_candle_time(self):
        """Test calculating next candle period start time."""
        # 10:45:00 + 15 minutes = 11:00:00
        current = 1704105900000  # 10:45:00
        next_time = Candle.calculate_next_candle_time(current, TimeFrame.M15)
        expected = 1704106800000  # 11:00:00

        assert next_time == expected

    def test_is_complete_with_explicit_flag(self):
        """Test candle completion check with explicit is_closed flag."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
            is_closed=True,
        )

        assert candle.is_complete() is True

    def test_is_complete_with_current_time(self):
        """Test candle completion based on current time."""
        # Candle at 10:45:00 (normalized from 10:50:00)
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,  # Will normalize to 10:45:00
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
            is_closed=False,
        )

        # Current time before 11:00:00 - not complete
        assert candle.is_complete(current_time=1704106500000) is False  # 10:55:00

        # Current time at 11:00:00 - complete
        assert candle.is_complete(current_time=1704106800000) is True  # 11:00:00

        # Current time after 11:00:00 - complete
        assert candle.is_complete(current_time=1704107100000) is True  # 11:05:00


class TestConversionMethods:
    """Tests for data conversion methods."""

    def test_to_dict(self):
        """Test converting candle to dictionary."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,  # Will normalize to 10:45:00
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
            is_closed=True,
        )

        data = candle.to_dict()

        assert data["symbol"] == "BTCUSDT"
        assert data["timeframe"] == "15m"
        assert data["timestamp"] == 1704105900000  # Normalized timestamp
        assert "datetime" in data
        assert data["open"] == 42000.0
        assert data["high"] == 42500.0
        assert data["low"] == 41800.0
        assert data["close"] == 42300.0
        assert data["volume"] == 150.5
        assert data["is_closed"] is True

    def test_from_dict(self):
        """Test creating candle from dictionary."""
        data = {
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "timestamp": 1704106200000,
            "open": 2200.0,
            "high": 2210.0,
            "low": 2195.0,
            "close": 2205.0,
            "volume": 50.0,
            "is_closed": True,
        }

        candle = Candle.from_dict(data)

        assert candle.symbol == "ETHUSDT"
        assert candle.timeframe == TimeFrame.M1
        assert candle.open == 2200.0
        assert candle.is_closed is True

    def test_from_dict_missing_fields(self):
        """Test that from_dict raises error for missing fields."""
        data = {
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            # Missing timestamp, OHLCV
        }

        with pytest.raises(ValueError, match="Missing required fields"):
            Candle.from_dict(data)

    def test_from_ccxt_ohlcv(self):
        """Test creating candle from CCXT OHLCV array."""
        ohlcv = [1704106200000, 42000.0, 42500.0, 41800.0, 42300.0, 150.5]

        candle = Candle.from_ccxt_ohlcv(
            symbol="BTCUSDT", timeframe=TimeFrame.M15, ohlcv=ohlcv, is_closed=True
        )

        assert candle.symbol == "BTCUSDT"
        assert candle.timestamp == 1704105900000  # Normalized timestamp
        assert candle.open == 42000.0
        assert candle.high == 42500.0
        assert candle.low == 41800.0
        assert candle.close == 42300.0
        assert candle.volume == 150.5
        assert candle.is_closed is True

    def test_from_ccxt_ohlcv_invalid_array(self):
        """Test that from_ccxt_ohlcv raises error for invalid array."""
        with pytest.raises(ValueError, match="Invalid OHLCV array"):
            Candle.from_ccxt_ohlcv(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                ohlcv=[1704106200000, 42000.0],  # Too short
                is_closed=False,
            )


class TestUtilityMethods:
    """Tests for utility methods."""

    def test_get_datetime(self):
        """Test getting datetime object from timestamp."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        dt = candle.get_datetime()

        assert isinstance(dt, datetime)
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1

    def test_get_datetime_iso(self):
        """Test getting ISO format datetime string."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        iso_str = candle.get_datetime_iso()

        assert isinstance(iso_str, str)
        assert iso_str.startswith("2024-01-01")

    def test_get_body_size(self):
        """Test calculating candle body size."""
        # Bullish candle
        bullish = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )
        assert bullish.get_body_size() == 300.0

        # Bearish candle
        bearish = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42300.0,
            high=42500.0,
            low=41800.0,
            close=42000.0,
            volume=150.5,
        )
        assert bearish.get_body_size() == 300.0

    def test_get_wicks(self):
        """Test calculating upper and lower wicks."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        # Upper wick: 42500 - 42300 = 200
        assert candle.get_upper_wick() == 200.0

        # Lower wick: 42000 - 41800 = 200
        assert candle.get_lower_wick() == 200.0

    def test_get_total_range(self):
        """Test calculating total price range."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        # 42500 - 41800 = 700
        assert candle.get_total_range() == 700.0

    def test_is_bullish(self):
        """Test bullish candle detection."""
        bullish = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )
        assert bullish.is_bullish() is True
        assert bullish.is_bearish() is False

    def test_is_bearish(self):
        """Test bearish candle detection."""
        bearish = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42300.0,
            high=42500.0,
            low=41800.0,
            close=42000.0,
            volume=150.5,
        )
        assert bearish.is_bearish() is True
        assert bearish.is_bullish() is False

    def test_is_doji(self):
        """Test doji candle detection."""
        # Exact doji (open = close)
        doji = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42000.0,
            volume=150.5,
        )
        assert doji.is_doji() is True

        # Near-doji (small body)
        near_doji = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42005.0,  # Only 5 points difference on 700 range
            volume=150.5,
        )
        assert near_doji.is_doji(threshold_percent=1.0) is True

        # Not a doji (large body)
        not_doji = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )
        assert not_doji.is_doji() is False


class TestStringRepresentations:
    """Tests for string representations."""

    def test_repr(self):
        """Test __repr__ method."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        repr_str = repr(candle)

        assert "Candle" in repr_str
        assert "BTCUSDT" in repr_str
        assert "15m" in repr_str

    def test_str_bullish(self):
        """Test __str__ method for bullish candle."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42300.0,
            volume=150.5,
        )

        str_repr = str(candle)

        assert "🟢" in str_repr  # Bullish indicator
        assert "BTCUSDT" in str_repr

    def test_str_bearish(self):
        """Test __str__ method for bearish candle."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42300.0,
            high=42500.0,
            low=41800.0,
            close=42000.0,
            volume=150.5,
        )

        str_repr = str(candle)

        assert "🔴" in str_repr  # Bearish indicator

    def test_str_doji(self):
        """Test __str__ method for doji candle."""
        candle = Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=1704106200000,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42000.0,
            volume=150.5,
        )

        str_repr = str(candle)

        assert "⚪" in str_repr  # Doji indicator
