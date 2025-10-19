"""
Tests for HistoricalDataLoader.

Tests cover:
- Historical data loading with rate limiting
- Batch processing and pagination
- Data validation (time ordering, gaps, duplicates)
- Integration with CandleStorage
- Error handling and retry logic
- Multiple symbol loading
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone
import time

from src.services.exchange.historical_loader import HistoricalDataLoader
from src.services.exchange.binance_manager import BinanceManager, BinanceConnectionError
from src.services.candle_storage import CandleStorage
from src.models.candle import Candle
from src.core.constants import TimeFrame


@pytest.fixture
def mock_binance_manager():
    """Create mock BinanceManager."""
    manager = Mock(spec=BinanceManager)
    manager.fetch_ohlcv = AsyncMock()
    return manager


@pytest.fixture
def candle_storage():
    """Create CandleStorage instance."""
    return CandleStorage(max_candles=1000)


@pytest.fixture
def historical_loader(mock_binance_manager, candle_storage):
    """Create HistoricalDataLoader instance."""
    return HistoricalDataLoader(
        binance_manager=mock_binance_manager,
        candle_storage=candle_storage,
        enable_rate_limiting=False  # Disable for faster tests
    )


@pytest.fixture
def sample_ohlcv_data():
    """Generate sample OHLCV data."""
    base_timestamp = 1704067200000  # 2024-01-01 00:00:00
    interval_ms = 15 * 60 * 1000  # 15 minutes

    def generate_candles(count: int, start_index: int = 0):
        candles = []
        for i in range(count):
            timestamp = base_timestamp + (start_index + i) * interval_ms
            # [timestamp, open, high, low, close, volume]
            candles.append([
                timestamp,
                100.0 + i,  # open
                105.0 + i,  # high
                95.0 + i,   # low
                102.0 + i,  # close
                1000.0      # volume
            ])
        return candles

    return generate_candles


class TestHistoricalDataLoader:
    """Test suite for HistoricalDataLoader."""

    @pytest.mark.asyncio
    async def test_load_historical_data_success(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test successful historical data loading."""
        # Setup mock
        ohlcv_data = sample_ohlcv_data(100)
        mock_binance_manager.fetch_ohlcv.return_value = ohlcv_data

        # Load data
        candles = await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=100
        )

        # Verify results
        assert len(candles) == 100
        assert all(isinstance(c, Candle) for c in candles)
        assert candles[0].symbol == 'BTCUSDT'
        assert candles[0].timeframe == TimeFrame.M15
        assert candles[0].is_closed is True

        # Verify API called correctly
        mock_binance_manager.fetch_ohlcv.assert_called_once_with(
            symbol='BTCUSDT',
            timeframe='15m',
            since=None,
            limit=100
        )

        # Verify statistics
        stats = historical_loader.get_stats()
        assert stats['total_candles_loaded'] == 100
        assert stats['total_requests'] == 1

    @pytest.mark.asyncio
    async def test_load_historical_data_with_storage(
        self,
        historical_loader,
        mock_binance_manager,
        candle_storage,
        sample_ohlcv_data
    ):
        """Test that loaded data is stored in CandleStorage."""
        # Setup mock
        ohlcv_data = sample_ohlcv_data(50)
        mock_binance_manager.fetch_ohlcv.return_value = ohlcv_data

        # Load with storage enabled
        await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=50,
            store=True
        )

        # Verify data is in storage
        stored_candles = candle_storage.get_candles('BTCUSDT', TimeFrame.M15)
        assert len(stored_candles) == 50
        assert stored_candles[0].symbol == 'BTCUSDT'

    @pytest.mark.asyncio
    async def test_load_historical_data_without_storage(
        self,
        historical_loader,
        mock_binance_manager,
        candle_storage,
        sample_ohlcv_data
    ):
        """Test loading without storing in CandleStorage."""
        # Setup mock
        ohlcv_data = sample_ohlcv_data(50)
        mock_binance_manager.fetch_ohlcv.return_value = ohlcv_data

        # Load without storage
        await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=50,
            store=False
        )

        # Verify no data in storage
        stored_candles = candle_storage.get_candles('BTCUSDT', TimeFrame.M15)
        assert len(stored_candles) == 0

    @pytest.mark.asyncio
    async def test_data_validation_success(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test data validation with valid data."""
        # Setup mock with sequential data
        ohlcv_data = sample_ohlcv_data(100)
        mock_binance_manager.fetch_ohlcv.return_value = ohlcv_data

        # Load with validation enabled
        candles = await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=100,
            validate=True
        )

        # Validate
        validation = historical_loader._validate_candles(candles)
        assert validation['valid'] is True
        assert len(validation['issues']) == 0
        assert len(validation['gaps']) == 0
        assert len(validation['duplicates']) == 0

    @pytest.mark.asyncio
    async def test_data_validation_with_gaps(
        self,
        historical_loader,
        sample_ohlcv_data
    ):
        """Test gap detection in candle data."""
        # Create data with gaps
        data_part1 = sample_ohlcv_data(10, start_index=0)
        data_part2 = sample_ohlcv_data(10, start_index=15)  # 5 candle gap
        ohlcv_data = data_part1 + data_part2

        # Convert to Candle objects
        candles = [
            Candle.from_ccxt_ohlcv('BTCUSDT', TimeFrame.M15, ohlcv, is_closed=True)
            for ohlcv in ohlcv_data
        ]

        # Validate
        validation = historical_loader._validate_candles(candles)
        assert validation['valid'] is False
        assert len(validation['gaps']) == 1
        assert validation['gaps'][0]['missing_candles'] == 5

    @pytest.mark.asyncio
    async def test_data_validation_with_duplicates(
        self,
        historical_loader,
        sample_ohlcv_data
    ):
        """Test duplicate detection in candle data."""
        # Create data with duplicates
        ohlcv_data = sample_ohlcv_data(10)
        ohlcv_data.append(ohlcv_data[5])  # Add duplicate

        # Convert to Candle objects
        candles = [
            Candle.from_ccxt_ohlcv('BTCUSDT', TimeFrame.M15, ohlcv, is_closed=True)
            for ohlcv in ohlcv_data
        ]

        # Validate
        validation = historical_loader._validate_candles(candles)
        assert validation['valid'] is False
        assert len(validation['duplicates']) == 1

    @pytest.mark.asyncio
    async def test_data_validation_with_wrong_order(
        self,
        historical_loader,
        sample_ohlcv_data
    ):
        """Test time ordering validation."""
        # Create data in wrong order
        ohlcv_data = sample_ohlcv_data(10)
        # Swap two candles
        ohlcv_data[3], ohlcv_data[7] = ohlcv_data[7], ohlcv_data[3]

        # Convert to Candle objects
        candles = [
            Candle.from_ccxt_ohlcv('BTCUSDT', TimeFrame.M15, ohlcv, is_closed=True)
            for ohlcv in ohlcv_data
        ]

        # Validate
        validation = historical_loader._validate_candles(candles)
        assert validation['valid'] is False
        assert any('Time ordering violation' in issue for issue in validation['issues'])

    @pytest.mark.asyncio
    async def test_retry_on_error(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test retry logic on API errors."""
        # Setup mock to fail twice then succeed
        ohlcv_data = sample_ohlcv_data(50)
        mock_binance_manager.fetch_ohlcv.side_effect = [
            Exception("Network error"),
            Exception("Timeout"),
            ohlcv_data
        ]

        # Load data (should retry and succeed)
        candles = await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=50
        )

        # Verify success after retries
        assert len(candles) == 50
        assert mock_binance_manager.fetch_ohlcv.call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(
        self,
        historical_loader,
        mock_binance_manager
    ):
        """Test that max retries limit is enforced."""
        # Setup mock to always fail
        mock_binance_manager.fetch_ohlcv.side_effect = Exception("Network error")

        # Should raise after max retries
        with pytest.raises(BinanceConnectionError):
            await historical_loader.load_historical_data(
                symbol='BTCUSDT',
                timeframe=TimeFrame.M15,
                limit=50
            )

        # Verify max retries attempted
        assert mock_binance_manager.fetch_ohlcv.call_count == historical_loader.MAX_RETRIES

    @pytest.mark.asyncio
    async def test_invalid_limit(self, historical_loader):
        """Test validation of limit parameter."""
        # Test zero limit
        with pytest.raises(ValueError, match="limit must be between"):
            await historical_loader.load_historical_data(
                symbol='BTCUSDT',
                timeframe=TimeFrame.M15,
                limit=0
            )

        # Test exceeding max limit
        with pytest.raises(ValueError, match="limit must be between"):
            await historical_loader.load_historical_data(
                symbol='BTCUSDT',
                timeframe=TimeFrame.M15,
                limit=1001
            )

    @pytest.mark.asyncio
    async def test_load_multiple_symbols_parallel(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test loading multiple symbols in parallel."""
        # Setup mock
        mock_binance_manager.fetch_ohlcv.return_value = sample_ohlcv_data(50)

        # Load multiple symbols
        results = await historical_loader.load_multiple_symbols(
            symbols=['BTCUSDT', 'ETHUSDT'],
            timeframes=[TimeFrame.M15, TimeFrame.H1],
            limit=50,
            parallel=True
        )

        # Verify results
        assert 'BTCUSDT' in results
        assert 'ETHUSDT' in results
        assert TimeFrame.M15 in results['BTCUSDT']
        assert TimeFrame.H1 in results['BTCUSDT']
        assert len(results['BTCUSDT'][TimeFrame.M15]) == 50
        assert len(results['ETHUSDT'][TimeFrame.H1]) == 50

        # Verify API called for all combinations (2 symbols × 2 timeframes)
        assert mock_binance_manager.fetch_ohlcv.call_count == 4

    @pytest.mark.asyncio
    async def test_load_multiple_symbols_sequential(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test loading multiple symbols sequentially."""
        # Setup mock
        mock_binance_manager.fetch_ohlcv.return_value = sample_ohlcv_data(50)

        # Load multiple symbols sequentially
        results = await historical_loader.load_multiple_symbols(
            symbols=['BTCUSDT', 'ETHUSDT'],
            timeframes=[TimeFrame.M15],
            limit=50,
            parallel=False
        )

        # Verify results
        assert len(results) == 2
        assert all(len(results[sym][TimeFrame.M15]) == 50 for sym in results)

    @pytest.mark.asyncio
    async def test_load_multiple_symbols_with_errors(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test handling of errors when loading multiple symbols."""
        # Setup mock to fail for one symbol
        def side_effect(symbol, timeframe, since, limit):
            if symbol == 'BTCUSDT':
                return sample_ohlcv_data(50)
            else:
                raise Exception("API Error")

        mock_binance_manager.fetch_ohlcv.side_effect = side_effect

        # Load multiple symbols
        results = await historical_loader.load_multiple_symbols(
            symbols=['BTCUSDT', 'ETHUSDT'],
            timeframes=[TimeFrame.M15],
            limit=50,
            parallel=True
        )

        # Verify BTCUSDT succeeded
        assert len(results['BTCUSDT'][TimeFrame.M15]) == 50

        # Verify ETHUSDT failed gracefully (empty list)
        assert len(results['ETHUSDT'][TimeFrame.M15]) == 0

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Test rate limiting mechanism."""
        # Create loader with rate limiting enabled
        mock_manager = Mock(spec=BinanceManager)
        mock_manager.fetch_ohlcv = AsyncMock(return_value=[])
        storage = CandleStorage()

        loader = HistoricalDataLoader(
            binance_manager=mock_manager,
            candle_storage=storage,
            enable_rate_limiting=True
        )

        # Simulate rapid requests
        start_time = time.time()

        # Make many requests that would exceed rate limit
        tasks = [
            loader.load_historical_data('BTCUSDT', TimeFrame.M15, limit=50, store=False)
            for _ in range(10)
        ]

        await asyncio.gather(*tasks)

        elapsed = time.time() - start_time

        # Verify rate limiting was applied (should take some time)
        # Note: This is a simple test - in practice rate limiting would delay
        # if we exceeded the limit
        assert loader.get_stats()['total_requests'] == 10

    @pytest.mark.asyncio
    async def test_statistics_tracking(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test statistics tracking."""
        # Setup mock
        mock_binance_manager.fetch_ohlcv.return_value = sample_ohlcv_data(100)

        # Initial stats
        stats = historical_loader.get_stats()
        assert stats['total_candles_loaded'] == 0
        assert stats['total_requests'] == 0

        # Load data
        await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=100
        )

        # Check updated stats
        stats = historical_loader.get_stats()
        assert stats['total_candles_loaded'] == 100
        assert stats['total_requests'] == 1

        # Reset stats
        historical_loader.reset_stats()
        stats = historical_loader.get_stats()
        assert stats['total_candles_loaded'] == 0
        assert stats['total_requests'] == 0

    @pytest.mark.asyncio
    async def test_empty_response(
        self,
        historical_loader,
        mock_binance_manager
    ):
        """Test handling of empty API response."""
        # Setup mock to return empty data
        mock_binance_manager.fetch_ohlcv.return_value = []

        # Load data
        candles = await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=100
        )

        # Verify empty result
        assert len(candles) == 0

    @pytest.mark.asyncio
    async def test_partial_data_corruption(
        self,
        historical_loader,
        mock_binance_manager,
        sample_ohlcv_data
    ):
        """Test handling of partially corrupted data."""
        # Create mix of good and bad data
        good_data = sample_ohlcv_data(10)
        bad_data = [[1, 2, 3]]  # Invalid OHLCV (too few elements)
        ohlcv_data = good_data[:5] + [bad_data[0]] + good_data[5:]

        mock_binance_manager.fetch_ohlcv.return_value = ohlcv_data

        # Load data (should skip corrupted candles)
        candles = await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=11
        )

        # Should have 10 good candles (corrupted one skipped)
        assert len(candles) == 10


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_window(self):
        """Test rate limit sliding window."""
        mock_manager = Mock(spec=BinanceManager)
        mock_manager.fetch_ohlcv = AsyncMock(return_value=[])
        storage = CandleStorage()

        loader = HistoricalDataLoader(
            binance_manager=mock_manager,
            candle_storage=storage,
            enable_rate_limiting=True
        )

        # Track delays
        initial_time = time.time()

        # Make requests
        for _ in range(5):
            await loader._wait_for_rate_limit()

        elapsed = time.time() - initial_time

        # Should complete quickly (under rate limit)
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_rate_limit_disabled(self):
        """Test that rate limiting can be disabled."""
        mock_manager = Mock(spec=BinanceManager)
        mock_manager.fetch_ohlcv = AsyncMock(return_value=[])
        storage = CandleStorage()

        loader = HistoricalDataLoader(
            binance_manager=mock_manager,
            candle_storage=storage,
            enable_rate_limiting=False
        )

        # Should complete instantly when disabled
        start = time.time()
        for _ in range(100):
            await loader._wait_for_rate_limit()
        elapsed = time.time() - start

        assert elapsed < 0.1  # Should be very fast
