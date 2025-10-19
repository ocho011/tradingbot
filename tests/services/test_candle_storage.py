"""
Comprehensive test suite for CandleStorage.

Tests cover:
- Basic operations (add, get, remove)
- LRU eviction behavior
- Thread safety
- Memory monitoring
- Edge cases and error handling
"""

import pytest
import time
import threading
from datetime import datetime, timezone

from src.core.constants import TimeFrame
from src.models.candle import Candle
from src.services.candle_storage import CandleStorage, StorageStats


# Test fixtures
@pytest.fixture
def storage():
    """Create a fresh CandleStorage instance for each test."""
    return CandleStorage(max_candles=10)


@pytest.fixture
def sample_candle():
    """Create a sample candle for testing."""
    return Candle(
        symbol='BTCUSDT',
        timeframe=TimeFrame.M1,
        timestamp=1704067200000,  # 2024-01-01 00:00:00 UTC
        open=42000.0,
        high=42500.0,
        low=41800.0,
        close=42300.0,
        volume=100.5,
        is_closed=True
    )


def create_test_candle(
    symbol: str = 'BTCUSDT',
    timeframe: TimeFrame = TimeFrame.M1,
    timestamp: int = 1704067200000,
    close: float = 42000.0
) -> Candle:
    """Helper to create test candles."""
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=close - 100,
        high=close + 100,
        low=close - 200,
        close=close,
        volume=100.0,
        is_closed=True
    )


class TestCandleStorageInit:
    """Test CandleStorage initialization."""

    def test_init_default(self):
        """Test default initialization."""
        storage = CandleStorage()
        assert storage.max_candles == 500
        assert storage.get_candle_count() == 0
        assert storage.get_storage_count() == 0

    def test_init_custom_max_candles(self):
        """Test initialization with custom max_candles."""
        storage = CandleStorage(max_candles=100)
        assert storage.max_candles == 100

    def test_init_invalid_max_candles(self):
        """Test initialization with invalid max_candles raises error."""
        with pytest.raises(ValueError, match="max_candles must be positive"):
            CandleStorage(max_candles=0)

        with pytest.raises(ValueError, match="max_candles must be positive"):
            CandleStorage(max_candles=-1)


class TestBasicOperations:
    """Test basic add/get/remove operations."""

    def test_add_single_candle(self, storage, sample_candle):
        """Test adding a single candle."""
        storage.add_candle(sample_candle)

        assert storage.get_candle_count() == 1
        assert storage.get_storage_count() == 1

        candles = storage.get_candles('BTCUSDT', TimeFrame.M1)
        assert len(candles) == 1
        assert candles[0] == sample_candle

    def test_add_multiple_candles_same_symbol(self, storage):
        """Test adding multiple candles for same symbol-timeframe."""
        candles_to_add = []
        for i in range(5):
            candle = create_test_candle(timestamp=1704067200000 + i * 60000)
            candles_to_add.append(candle)
            storage.add_candle(candle)

        assert storage.get_candle_count() == 5
        assert storage.get_storage_count() == 1

        retrieved = storage.get_candles('BTCUSDT', TimeFrame.M1)
        assert len(retrieved) == 5
        assert retrieved == candles_to_add

    def test_add_multiple_symbols(self, storage):
        """Test adding candles for different symbols."""
        btc_candle = create_test_candle(symbol='BTCUSDT')
        eth_candle = create_test_candle(symbol='ETHUSDT')

        storage.add_candle(btc_candle)
        storage.add_candle(eth_candle)

        assert storage.get_candle_count() == 2
        assert storage.get_storage_count() == 2

    def test_add_multiple_timeframes(self, storage):
        """Test adding candles for different timeframes."""
        m1_candle = create_test_candle(timeframe=TimeFrame.M1)
        m5_candle = create_test_candle(timeframe=TimeFrame.M5)

        storage.add_candle(m1_candle)
        storage.add_candle(m5_candle)

        assert storage.get_candle_count() == 2
        assert storage.get_storage_count() == 2

    def test_get_latest_candle(self, storage):
        """Test getting the most recent candle."""
        for i in range(3):
            candle = create_test_candle(timestamp=1704067200000 + i * 60000, close=42000.0 + i)
            storage.add_candle(candle)

        latest = storage.get_latest_candle('BTCUSDT', TimeFrame.M1)
        assert latest is not None
        assert latest.close == 42002.0  # Last candle

    def test_get_latest_candle_empty_storage(self, storage):
        """Test getting latest candle from empty storage."""
        latest = storage.get_latest_candle('BTCUSDT', TimeFrame.M1)
        assert latest is None

    def test_get_candles_with_limit(self, storage):
        """Test getting candles with limit parameter."""
        for i in range(10):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        candles = storage.get_candles('BTCUSDT', TimeFrame.M1, limit=5)
        assert len(candles) == 5

        # Should get the 5 most recent candles
        assert candles[0].timestamp == 1704067200000 + 5 * 60000

    def test_get_candles_with_time_range(self, storage):
        """Test getting candles with time range filter."""
        base_time = 1704067200000
        for i in range(10):
            storage.add_candle(create_test_candle(timestamp=base_time + i * 60000))

        # Get candles in middle range
        start_time = base_time + 3 * 60000
        end_time = base_time + 6 * 60000

        candles = storage.get_candles(
            'BTCUSDT',
            TimeFrame.M1,
            start_time=start_time,
            end_time=end_time
        )

        assert len(candles) == 4  # Timestamps 3, 4, 5, 6
        assert all(start_time <= c.timestamp <= end_time for c in candles)

    def test_remove_candles_before_timestamp(self, storage):
        """Test removing candles before a timestamp."""
        base_time = 1704067200000
        for i in range(10):
            storage.add_candle(create_test_candle(timestamp=base_time + i * 60000))

        # Remove candles before timestamp 5
        before_time = base_time + 5 * 60000
        removed = storage.remove_candles('BTCUSDT', TimeFrame.M1, before_timestamp=before_time)

        assert removed == 5
        assert storage.get_candle_count() == 5

        remaining = storage.get_candles('BTCUSDT', TimeFrame.M1)
        assert all(c.timestamp >= before_time for c in remaining)

    def test_remove_all_candles_for_pair(self, storage):
        """Test removing all candles for symbol-timeframe pair."""
        for i in range(5):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        removed = storage.remove_candles('BTCUSDT', TimeFrame.M1)

        assert removed == 5
        assert storage.get_candle_count() == 0
        assert storage.get_storage_count() == 0

    def test_remove_nonexistent_pair(self, storage):
        """Test removing candles for non-existent pair returns 0."""
        removed = storage.remove_candles('ETHUSDT', TimeFrame.M1)
        assert removed == 0


class TestLRUEviction:
    """Test LRU eviction behavior."""

    def test_eviction_at_max_capacity(self, storage):
        """Test that oldest candle is evicted when max capacity reached."""
        # Add max_candles (10) + 1
        for i in range(11):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        # Should have exactly max_candles
        assert storage.get_candle_count() == 10

        # First candle should be evicted
        candles = storage.get_candles('BTCUSDT', TimeFrame.M1)
        assert candles[0].timestamp == 1704067200000 + 60000  # Second candle

    def test_eviction_counter(self, storage):
        """Test eviction counter increments correctly."""
        # Add more than max capacity
        for i in range(15):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        stats = storage.get_stats()
        assert stats.evictions == 5  # 15 - 10

    def test_no_eviction_below_capacity(self, storage):
        """Test no eviction when below max capacity."""
        for i in range(5):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        stats = storage.get_stats()
        assert stats.evictions == 0
        assert storage.get_candle_count() == 5

    def test_eviction_per_storage(self, storage):
        """Test eviction happens independently per symbol-timeframe."""
        # Fill BTC M1 storage
        for i in range(15):
            storage.add_candle(create_test_candle(symbol='BTCUSDT', timestamp=1704067200000 + i * 60000))

        # Fill ETH M1 storage
        for i in range(8):
            storage.add_candle(create_test_candle(symbol='ETHUSDT', timestamp=1704067200000 + i * 60000))

        # BTC should have max_candles, ETH should have 8
        assert storage.get_candle_count('BTCUSDT', TimeFrame.M1) == 10
        assert storage.get_candle_count('ETHUSDT', TimeFrame.M1) == 8


class TestThreadSafety:
    """Test thread-safe concurrent operations."""

    def test_concurrent_adds(self, storage):
        """Test concurrent add operations are thread-safe."""
        num_threads = 10
        candles_per_thread = 20

        def add_candles(thread_id):
            for i in range(candles_per_thread):
                timestamp = 1704067200000 + (thread_id * candles_per_thread + i) * 60000
                storage.add_candle(create_test_candle(timestamp=timestamp))

        threads = [threading.Thread(target=add_candles, args=(i,)) for i in range(num_threads)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Should have exactly max_candles (10) due to LRU eviction
        assert storage.get_candle_count() == 10

    def test_concurrent_reads_writes(self, storage):
        """Test concurrent read and write operations."""
        # Pre-populate storage
        for i in range(5):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        results = []

        def write_candles():
            for i in range(10):
                storage.add_candle(create_test_candle(timestamp=1704067200000 + (i + 5) * 60000))
                time.sleep(0.001)

        def read_candles():
            for _ in range(10):
                candles = storage.get_candles('BTCUSDT', TimeFrame.M1)
                results.append(len(candles))
                time.sleep(0.001)

        write_thread = threading.Thread(target=write_candles)
        read_thread = threading.Thread(target=read_candles)

        write_thread.start()
        read_thread.start()

        write_thread.join()
        read_thread.join()

        # All reads should have succeeded (no exceptions)
        assert len(results) == 10
        assert all(isinstance(r, int) for r in results)

    def test_concurrent_clear(self, storage):
        """Test clearing storage during concurrent operations."""
        for i in range(5):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        def add_candles():
            for i in range(10):
                try:
                    storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))
                except Exception:
                    pass
                time.sleep(0.001)

        def clear_storage():
            time.sleep(0.005)
            storage.clear()

        add_thread = threading.Thread(target=add_candles)
        clear_thread = threading.Thread(target=clear_storage)

        add_thread.start()
        clear_thread.start()

        add_thread.join()
        clear_thread.join()

        # Should complete without errors
        assert isinstance(storage.get_candle_count(), int)


class TestMemoryMonitoring:
    """Test memory usage monitoring."""

    def test_get_memory_usage(self, storage):
        """Test memory usage calculation."""
        initial_memory = storage.get_memory_usage()
        assert initial_memory > 0

        # Add candles and check memory increases
        for i in range(10):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        after_memory = storage.get_memory_usage()
        assert after_memory > initial_memory

    def test_storage_stats(self, storage):
        """Test comprehensive storage statistics."""
        # Add candles to multiple storages
        for i in range(5):
            storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M1, timestamp=1704067200000 + i * 60000))
            storage.add_candle(create_test_candle(symbol='ETHUSDT', timeframe=TimeFrame.M5, timestamp=1704067200000 + i * 300000))

        stats = storage.get_stats()

        assert stats.total_candles == 10
        assert stats.storage_count == 2
        assert stats.memory_bytes > 0
        assert stats.evictions == 0

        # Test to_dict conversion
        stats_dict = stats.to_dict()
        assert 'total_candles' in stats_dict
        assert 'memory_mb' in stats_dict
        assert stats_dict['memory_mb'] >= 0  # Can be 0.0 for small storage

    def test_memory_usage_after_clear(self, storage):
        """Test memory is reduced after clearing storage."""
        for i in range(10):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        before_clear = storage.get_memory_usage()
        storage.clear()
        after_clear = storage.get_memory_usage()

        assert after_clear < before_clear


class TestClearOperations:
    """Test various clear operations."""

    def test_clear_all(self, storage):
        """Test clearing all storage."""
        storage.add_candle(create_test_candle(symbol='BTCUSDT'))
        storage.add_candle(create_test_candle(symbol='ETHUSDT'))

        removed = storage.clear()

        assert removed == 2
        assert storage.get_candle_count() == 0
        assert storage.get_storage_count() == 0

    def test_clear_symbol(self, storage):
        """Test clearing all timeframes for a symbol."""
        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M1))
        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M5))
        storage.add_candle(create_test_candle(symbol='ETHUSDT', timeframe=TimeFrame.M1))

        removed = storage.clear(symbol='BTCUSDT')

        assert removed == 2
        assert storage.get_candle_count('BTCUSDT') == 0
        assert storage.get_candle_count('ETHUSDT') == 1

    def test_clear_symbol_timeframe(self, storage):
        """Test clearing specific symbol-timeframe."""
        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M1))
        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M5))

        removed = storage.clear(symbol='BTCUSDT', timeframe=TimeFrame.M1)

        assert removed == 1
        assert storage.get_candle_count('BTCUSDT', TimeFrame.M1) == 0
        assert storage.get_candle_count('BTCUSDT', TimeFrame.M5) == 1


class TestUtilityMethods:
    """Test utility and helper methods."""

    def test_get_symbols(self, storage):
        """Test getting list of stored symbols."""
        storage.add_candle(create_test_candle(symbol='BTCUSDT'))
        storage.add_candle(create_test_candle(symbol='ETHUSDT'))
        storage.add_candle(create_test_candle(symbol='BNBUSDT'))

        symbols = storage.get_symbols()

        assert len(symbols) == 3
        assert 'BTCUSDT' in symbols
        assert 'ETHUSDT' in symbols
        assert 'BNBUSDT' in symbols
        assert symbols == sorted(symbols)  # Should be sorted

    def test_get_timeframes(self, storage):
        """Test getting timeframes for a symbol."""
        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M1))
        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.H1))
        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M5))

        timeframes = storage.get_timeframes('BTCUSDT')

        assert len(timeframes) == 3
        # Should be sorted by duration
        assert timeframes[0] == TimeFrame.M1
        assert timeframes[1] == TimeFrame.M5
        assert timeframes[2] == TimeFrame.H1

    def test_get_storage_count(self, storage):
        """Test getting storage count."""
        assert storage.get_storage_count() == 0

        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M1))
        assert storage.get_storage_count() == 1

        storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M5))
        assert storage.get_storage_count() == 2

        # Test filtering by symbol
        storage.add_candle(create_test_candle(symbol='ETHUSDT', timeframe=TimeFrame.M1))
        assert storage.get_storage_count('BTCUSDT') == 2
        assert storage.get_storage_count('ETHUSDT') == 1

    def test_get_candle_count(self, storage):
        """Test getting candle count."""
        assert storage.get_candle_count() == 0

        for i in range(3):
            storage.add_candle(create_test_candle(symbol='BTCUSDT', timeframe=TimeFrame.M1, timestamp=1704067200000 + i * 60000))

        for i in range(2):
            storage.add_candle(create_test_candle(symbol='ETHUSDT', timeframe=TimeFrame.M1, timestamp=1704067200000 + i * 60000))

        assert storage.get_candle_count() == 5
        assert storage.get_candle_count('BTCUSDT') == 3
        assert storage.get_candle_count('ETHUSDT') == 2
        assert storage.get_candle_count('BTCUSDT', TimeFrame.M1) == 3

    def test_repr_and_str(self, storage):
        """Test string representations."""
        storage.add_candle(create_test_candle())

        repr_str = repr(storage)
        assert 'CandleStorage' in repr_str
        assert 'max_candles=10' in repr_str

        str_str = str(storage)
        assert 'candles' in str_str.lower()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_case_insensitive_symbols(self, storage):
        """Test that symbol lookups are case-insensitive."""
        storage.add_candle(create_test_candle(symbol='btcusdt'))

        candles_lower = storage.get_candles('btcusdt', TimeFrame.M1)
        candles_upper = storage.get_candles('BTCUSDT', TimeFrame.M1)
        candles_mixed = storage.get_candles('BtcUsDt', TimeFrame.M1)

        assert len(candles_lower) == 1
        assert len(candles_upper) == 1
        assert len(candles_mixed) == 1

    def test_empty_storage_operations(self, storage):
        """Test operations on empty storage don't raise errors."""
        assert storage.get_candles('BTCUSDT', TimeFrame.M1) == []
        assert storage.get_latest_candle('BTCUSDT', TimeFrame.M1) is None
        assert storage.remove_candles('BTCUSDT', TimeFrame.M1) == 0
        assert storage.clear() == 0
        assert storage.get_symbols() == []
        assert storage.get_timeframes('BTCUSDT') == []

    def test_get_candles_limit_exceeds_available(self, storage):
        """Test limit exceeding available candles returns all available."""
        for i in range(3):
            storage.add_candle(create_test_candle(timestamp=1704067200000 + i * 60000))

        candles = storage.get_candles('BTCUSDT', TimeFrame.M1, limit=100)
        assert len(candles) == 3

    def test_negative_limit(self, storage):
        """Test negative limit returns empty list."""
        storage.add_candle(create_test_candle())
        candles = storage.get_candles('BTCUSDT', TimeFrame.M1, limit=-1)
        assert len(candles) == 0

    def test_time_range_no_matches(self, storage):
        """Test time range with no matches returns empty list."""
        storage.add_candle(create_test_candle(timestamp=1704067200000))

        candles = storage.get_candles(
            'BTCUSDT',
            TimeFrame.M1,
            start_time=1704153600000,  # Much later time
            end_time=1704240000000
        )

        assert len(candles) == 0
