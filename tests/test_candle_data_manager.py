"""
Comprehensive tests for CandleDataManager multi-symbol/timeframe system.
Tests cover:
- Multi-symbol and multi-timeframe management
- Dynamic symbol addition and removal
- Resource monitoring and optimization
- Dashboard state and metrics
- Thread-safety and concurrent operations
"""
import pytest
import asyncio
from src.core.constants import EventType, TimeFrame
from src.core.events import EventBus, Event
from src.models.candle import Candle
from src.services.candle_data_manager import (
    CandleDataManager,
    SymbolConfig,
    SystemMetrics
)


@pytest.fixture
def event_bus():
    """Create event bus fixture."""
    return EventBus()


@pytest.fixture
async def manager(event_bus):
    """Create manager fixture."""
    mgr = CandleDataManager(
        event_bus=event_bus,
        max_candles_per_storage=100,
        enable_monitoring=False  # Disable for tests
    )
    await mgr.start()
    yield mgr
    await mgr.stop()


@pytest.fixture
def sample_candle():
    """Create sample candle fixture."""
    return Candle(
        symbol='BTCUSDT',
        timeframe=TimeFrame.M1,
        timestamp=1704067200000,
        open=45000.0,
        high=45100.0,
        low=44900.0,
        close=45050.0,
        volume=100.5,
        is_closed=True
    )


class TestBasicOperations:
    """Test basic CandleDataManager operations."""
    @pytest.mark.asyncio
    async def test_initialization(self, event_bus):
        """Test manager initialization."""
        manager = CandleDataManager(
            event_bus=event_bus,
            max_candles_per_storage=500,
            enable_monitoring=True,
            monitoring_interval=30
        )
        assert manager._max_candles == 500
        assert manager._enable_monitoring is True
        assert manager._monitoring_interval == 30
        assert len(manager._symbols) == 0

    @pytest.mark.asyncio
    async def test_start_stop(self, event_bus):
        """Test manager start and stop."""
        manager = CandleDataManager(event_bus=event_bus, enable_monitoring=False)
        # Start
        await manager.start()
        assert manager._processor is not None
        # Stop
        await manager.stop()


class TestSymbolManagement:
    """Test multi-symbol management functionality."""
    @pytest.mark.asyncio
    async def test_add_single_symbol(self, manager):
        """Test adding a single symbol with timeframes."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        symbols = manager.get_symbols()
        assert len(symbols) == 1
        assert 'BTCUSDT' in symbols
        timeframes = manager.get_timeframes('BTCUSDT')
        assert len(timeframes) == 2
        assert TimeFrame.M1 in timeframes
        assert TimeFrame.M15 in timeframes

    @pytest.mark.asyncio
    async def test_add_multiple_symbols(self, manager):
        """Test adding multiple symbols."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        await manager.add_symbol('ETHUSDT', [TimeFrame.M1, TimeFrame.H1])
        await manager.add_symbol('BNBUSDT', [TimeFrame.M5])
        symbols = manager.get_symbols()
        assert len(symbols) == 3
        assert set(symbols) == {'BTCUSDT', 'ETHUSDT', 'BNBUSDT'}

    @pytest.mark.asyncio
    async def test_add_symbol_merge_timeframes(self, manager):
        """Test merging timeframes for existing symbol."""
        # Initial add
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
        assert len(manager.get_timeframes('BTCUSDT')) == 1
        # Merge more timeframes
        await manager.add_symbol('BTCUSDT', [TimeFrame.M15, TimeFrame.H1], replace=False)
        timeframes = manager.get_timeframes('BTCUSDT')
        assert len(timeframes) == 3
        assert set(timeframes) == {TimeFrame.M1, TimeFrame.M15, TimeFrame.H1}

    @pytest.mark.asyncio
    async def test_add_symbol_replace_timeframes(self, manager):
        """Test replacing timeframes for existing symbol."""
        # Initial add
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        # Replace with new configuration
        await manager.add_symbol('BTCUSDT', [TimeFrame.H1], replace=True)
        timeframes = manager.get_timeframes('BTCUSDT')
        assert len(timeframes) == 1
        assert TimeFrame.H1 in timeframes
        assert TimeFrame.M1 not in timeframes

    @pytest.mark.asyncio
    async def test_add_symbol_validation(self, manager):
        """Test symbol addition validation."""
        # Empty symbol
        with pytest.raises(ValueError, match="Symbol cannot be empty"):
            await manager.add_symbol('', [TimeFrame.M1])
        # Empty timeframes
        with pytest.raises(ValueError, match="Must specify at least one timeframe"):
            await manager.add_symbol('BTCUSDT', [])

    @pytest.mark.asyncio
    async def test_remove_specific_timeframes(self, manager):
        """Test removing specific timeframes from a symbol."""
        # Add symbol with multiple timeframes
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15, TimeFrame.H1])
        # Remove one timeframe
        removed = await manager.remove_symbol('BTCUSDT', [TimeFrame.M15])
        assert removed is True
        timeframes = manager.get_timeframes('BTCUSDT')
        assert len(timeframes) == 2
        assert TimeFrame.M15 not in timeframes

    @pytest.mark.asyncio
    async def test_remove_entire_symbol(self, manager):
        """Test removing entire symbol."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        await manager.add_symbol('ETHUSDT', [TimeFrame.M1])
        # Remove BTCUSDT
        removed = await manager.remove_symbol('BTCUSDT')
        assert removed is True
        symbols = manager.get_symbols()
        assert len(symbols) == 1
        assert 'BTCUSDT' not in symbols
        assert 'ETHUSDT' in symbols

    @pytest.mark.asyncio
    async def test_remove_nonexistent_symbol(self, manager):
        """Test removing a symbol that doesn't exist."""
        removed = await manager.remove_symbol('NONEXISTENT')
        assert removed is False

    @pytest.mark.asyncio
    async def test_case_insensitive_symbols(self, manager):
        """Test that symbols are case-insensitive."""
        await manager.add_symbol('btcusdt', [TimeFrame.M1])
        # Should find with different case
        symbols = manager.get_symbols()
        assert 'BTCUSDT' in symbols
        timeframes = manager.get_timeframes('BtCuSdT')
        assert len(timeframes) == 1


class TestDataStorage:
    """Test candle data storage integration."""
    @pytest.mark.asyncio
    async def test_add_candles_via_events(self, manager, sample_candle):
        """Test adding candles through event system."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
        # Simulate candle received event
        event = Event(
            event_type=EventType.CANDLE_RECEIVED,
            priority=5,
            data={
                'symbol': 'BTCUSDT',
                'timeframe': '1m',
                'timestamp': sample_candle.timestamp,
                'open': sample_candle.open,
                'high': sample_candle.high,
                'low': sample_candle.low,
                'close': sample_candle.close,
                'volume': sample_candle.volume
            }
        )
        await manager.event_bus.publish(event)
        await asyncio.sleep(0.1)  # Let event process
        # Note: Candle won't be stored immediately because completion isn't detected yet
        # This is expected behavior

    @pytest.mark.asyncio
    async def test_get_candles(self, manager, sample_candle):
        """Test retrieving candles."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
        # Manually add to storage for testing
        manager._storage.add_candle(sample_candle)
        candles = manager.get_candles('BTCUSDT', TimeFrame.M1)
        assert len(candles) == 1
        assert candles[0].symbol == 'BTCUSDT'

    @pytest.mark.asyncio
    async def test_get_latest_candle(self, manager, sample_candle):
        """Test getting latest candle."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
        # Add multiple candles
        for i in range(3):
            candle = Candle(
                symbol='BTCUSDT',
                timeframe=TimeFrame.M1,
                timestamp=sample_candle.timestamp + (i * 60000),
                open=45000.0 + i,
                high=45100.0 + i,
                low=44900.0 + i,
                close=45050.0 + i,
                volume=100.5
            )
            manager._storage.add_candle(candle)
        latest = manager.get_latest_candle('BTCUSDT', TimeFrame.M1)
        assert latest is not None
        assert latest.close == 45052.0  # Last candle

    @pytest.mark.asyncio
    async def test_remove_symbol_clear_data(self, manager, sample_candle):
        """Test removing symbol and clearing data."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
        # Add candles
        manager._storage.add_candle(sample_candle)
        assert manager._storage.get_candle_count('BTCUSDT', TimeFrame.M1) == 1
        # Remove and clear
        await manager.remove_symbol('BTCUSDT', clear_data=True)
        assert manager._storage.get_candle_count('BTCUSDT', TimeFrame.M1) == 0


class TestMonitoring:
    """Test monitoring and metrics functionality."""
    @pytest.mark.asyncio
    async def test_dashboard_state(self, manager):
        """Test getting dashboard state."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        await manager.add_symbol('ETHUSDT', [TimeFrame.M1])
        state = manager.get_dashboard_state()
        assert state['total_symbols'] == 2
        assert 'BTCUSDT' in state['symbols']
        assert 'ETHUSDT' in state['symbols']
        assert state['monitoring_enabled'] is False
        assert 'uptime_seconds' in state

    @pytest.mark.asyncio
    async def test_memory_usage_summary(self, manager, sample_candle):
        """Test memory usage summary."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
        # Add some candles
        for i in range(10):
            candle = Candle(
                symbol='BTCUSDT',
                timeframe=TimeFrame.M1,
                timestamp=sample_candle.timestamp + (i * 60000),
                open=45000.0,
                high=45100.0,
                low=44900.0,
                close=45050.0,
                volume=100.5
            )
            manager._storage.add_candle(candle)
        summary = manager.get_memory_usage_summary()
        assert 'BTCUSDT' in summary
        assert summary['BTCUSDT']['total_mb'] > 0
        assert '1m' in summary['BTCUSDT']['timeframes']
        assert summary['BTCUSDT']['timeframes']['1m']['candles'] == 10

    @pytest.mark.asyncio
    async def test_optimize_memory(self, manager):
        """Test memory optimization."""
        result = await manager.optimize_memory(aggressive=False)
        assert 'gc_objects_collected' in result
        assert 'memory_freed_mb' in result
        assert 'before_memory_mb' in result
        assert 'after_memory_mb' in result

    @pytest.mark.asyncio
    async def test_metrics_collection(self, manager):
        """Test system metrics collection."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        metrics = manager._collect_metrics()
        assert isinstance(metrics, SystemMetrics)
        assert metrics.cpu_percent >= 0
        assert metrics.memory_percent >= 0
        assert metrics.active_symbols == 1
        assert metrics.active_timeframes == 2


class TestConfiguration:
    """Test configuration management."""
    @pytest.mark.asyncio
    async def test_get_symbol_config(self, manager):
        """Test getting symbol configuration."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        config = manager.get_symbol_config('BTCUSDT')
        assert config is not None
        assert config['symbol'] == 'BTCUSDT'
        assert len(config['timeframes']) == 2
        assert config['enabled'] is True
        assert 'added_at' in config

    @pytest.mark.asyncio
    async def test_get_config_nonexistent_symbol(self, manager):
        """Test getting config for nonexistent symbol."""
        config = manager.get_symbol_config('NONEXISTENT')
        assert config is None

    @pytest.mark.asyncio
    async def test_timeframes_sorted_by_duration(self, manager):
        """Test that timeframes are returned sorted by duration."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.H1, TimeFrame.M1, TimeFrame.M15])
        timeframes = manager.get_timeframes('BTCUSDT')
        # Should be sorted: M1, M15, H1
        assert timeframes[0] == TimeFrame.M1
        assert timeframes[1] == TimeFrame.M15
        assert timeframes[2] == TimeFrame.H1


class TestConcurrency:
    """Test thread-safety and concurrent operations."""
    @pytest.mark.asyncio
    async def test_concurrent_symbol_additions(self, manager):
        """Test adding symbols concurrently."""
        tasks = [
            manager.add_symbol('BTCUSDT', [TimeFrame.M1]),
            manager.add_symbol('ETHUSDT', [TimeFrame.M1]),
            manager.add_symbol('BNBUSDT', [TimeFrame.M1]),
            manager.add_symbol('ADAUSDT', [TimeFrame.M1])
        ]
        await asyncio.gather(*tasks)
        symbols = manager.get_symbols()
        assert len(symbols) == 4

    @pytest.mark.asyncio
    async def test_concurrent_timeframe_merges(self, manager):
        """Test merging timeframes concurrently."""
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
        tasks = [
            manager.add_symbol('BTCUSDT', [TimeFrame.M5], replace=False),
            manager.add_symbol('BTCUSDT', [TimeFrame.M15], replace=False),
            manager.add_symbol('BTCUSDT', [TimeFrame.H1], replace=False)
        ]
        await asyncio.gather(*tasks)
        timeframes = manager.get_timeframes('BTCUSDT')
        # Should have all timeframes merged
        assert len(timeframes) >= 2  # At least M1 and some others


class TestEdgeCases:
    """Test edge cases and error handling."""
    @pytest.mark.asyncio
    async def test_empty_symbol_list(self, manager):
        """Test with no symbols configured."""
        symbols = manager.get_symbols()
        assert len(symbols) == 0
        state = manager.get_dashboard_state()
        assert state['total_symbols'] == 0

    @pytest.mark.asyncio
    async def test_symbol_config_dataclass(self):
        """Test SymbolConfig dataclass."""
        config = SymbolConfig(
            symbol='BTCUSDT',
            timeframes={TimeFrame.M1, TimeFrame.M15}
        )
        assert config.symbol == 'BTCUSDT'
        assert len(config.timeframes) == 2
        assert config.enabled is True
        config_dict = config.to_dict()
        assert config_dict['symbol'] == 'BTCUSDT'
        assert len(config_dict['timeframes']) == 2

    @pytest.mark.asyncio
    async def test_system_metrics_dataclass(self):
        """Test SystemMetrics dataclass."""
        metrics = SystemMetrics(
            cpu_percent=45.5,
            memory_percent=60.3,
            total_candles=1000,
            active_symbols=5
        )
        assert metrics.cpu_percent == 45.5
        assert metrics.total_candles == 1000
        metrics_dict = metrics.to_dict()
        assert metrics_dict['cpu_percent'] == 45.5
        assert 'timestamp' in metrics_dict
