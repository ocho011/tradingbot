"""
Tests for real-time candle data processor.
Test Coverage:
- Candle reception and processing
- Candle completion detection based on timestamp changes
- CANDLE_CLOSED event publishing
- Data validation and outlier filtering
- CandleStorage integration
- Duplicate detection
- Statistics tracking
"""

import asyncio

import pytest

from src.core.constants import TimeFrame
from src.core.events import Event, EventBus, EventHandler, EventType
from src.services.candle_storage import CandleStorage
from src.services.exchange.realtime_processor import RealtimeCandleProcessor


class CaptureHandler(EventHandler):
    """Test event handler for capturing events."""

    def __init__(self):
        super().__init__(name="CaptureHandler")
        self.captured_events = []

    async def handle(self, event: Event) -> None:
        """Capture events."""
        self.captured_events.append(event)


@pytest.fixture
async def event_bus():
    """Create and start event bus for testing."""
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
def storage():
    """Create candle storage for testing."""
    return CandleStorage(max_candles=100)


@pytest.fixture
def processor(event_bus, storage):
    """Create realtime candle processor for testing."""
    proc = RealtimeCandleProcessor(event_bus=event_bus, storage=storage, outlier_threshold=3.0)
    # Subscribe processor to CANDLE_RECEIVED events
    event_bus.subscribe(EventType.CANDLE_RECEIVED, proc)
    return proc


@pytest.fixture
def processor_no_storage(event_bus):
    """Create processor without storage."""
    proc = RealtimeCandleProcessor(event_bus=event_bus, storage=None)
    # Subscribe processor to CANDLE_RECEIVED events
    event_bus.subscribe(EventType.CANDLE_RECEIVED, proc)
    return proc


@pytest.fixture
def sample_candle_data():
    """Create sample candle data dict."""
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "timestamp": 1640000000000,
        "datetime": "2021-12-20T12:00:00",
        "open": 50000.0,
        "high": 50100.0,
        "low": 49900.0,
        "close": 50050.0,
        "volume": 10.5,
    }


class TestCandleReception:
    """Test candle reception and basic processing."""

    @pytest.mark.asyncio
    async def test_process_valid_candle(self, processor, sample_candle_data):
        """Test processing a valid candle event."""
        event = Event(
            event_type=EventType.CANDLE_RECEIVED,
            priority=6,
            data=sample_candle_data,
            source="BinanceManager",
        )
        await processor.handle(event)
        # Check statistics
        stats = processor.get_statistics()
        assert stats["candles_processed"] == 1
        assert stats["active_streams"] == 1

    @pytest.mark.asyncio
    async def test_process_incomplete_data(self, processor):
        """Test processing candle with missing fields."""
        incomplete_data = {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            # Missing required fields
        }
        event = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=incomplete_data)
        await processor.handle(event)
        # Should not process incomplete data
        stats = processor.get_statistics()
        assert stats["candles_processed"] == 0

    @pytest.mark.asyncio
    async def test_process_invalid_timeframe(self, processor, sample_candle_data):
        """Test processing candle with invalid timeframe."""
        sample_candle_data["timeframe"] = "INVALID"
        event = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data)
        await processor.handle(event)
        # Should not process invalid timeframe
        stats = processor.get_statistics()
        assert stats["candles_processed"] == 0


class TestCandleCompletion:
    """Test candle completion detection."""

    @pytest.mark.asyncio
    async def test_first_candle_not_completed(self, processor, sample_candle_data, event_bus):
        """Test that first candle is not marked as completed."""
        test_handler = CaptureHandler()
        event_bus.subscribe(EventType.CANDLE_CLOSED, test_handler)
        event = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data)
        await event_bus.publish(event)
        await asyncio.sleep(0.1)  # Allow event processing
        # First candle should not trigger CANDLE_CLOSED
        assert len(test_handler.captured_events) == 0
        stats = processor.get_statistics()
        assert stats["candles_closed"] == 0

    @pytest.mark.asyncio
    async def test_candle_completion_on_timestamp_change(
        self, processor, sample_candle_data, event_bus
    ):
        """Test candle completion when timestamp changes."""
        test_handler = CaptureHandler()
        event_bus.subscribe(EventType.CANDLE_CLOSED, test_handler)
        # First candle
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await event_bus.publish(event1)
        await asyncio.sleep(0.1)
        # Second candle with new timestamp (1 minute later)
        candle_data_2 = sample_candle_data.copy()
        candle_data_2["timestamp"] = 1640000060000  # +60 seconds
        candle_data_2["close"] = 50100.0
        event2 = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=candle_data_2)
        await event_bus.publish(event2)
        await asyncio.sleep(0.1)
        # Should have one CANDLE_CLOSED event
        assert len(test_handler.captured_events) == 1
        assert test_handler.captured_events[0].event_type == EventType.CANDLE_CLOSED
        stats = processor.get_statistics()
        assert stats["candles_closed"] == 1
        assert stats["candles_processed"] == 2

    @pytest.mark.asyncio
    async def test_multiple_symbols_independent_completion(self, processor, event_bus):
        """Test that different symbols track completion independently."""
        test_handler = CaptureHandler()
        event_bus.subscribe(EventType.CANDLE_CLOSED, test_handler)
        # BTC candle 1
        btc_data_1 = {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "timestamp": 1640000000000,
            "open": 50000.0,
            "high": 50100.0,
            "low": 49900.0,
            "close": 50050.0,
            "volume": 10.5,
        }
        # ETH candle 1
        eth_data_1 = {
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "timestamp": 1640000000000,
            "open": 4000.0,
            "high": 4050.0,
            "low": 3950.0,
            "close": 4025.0,
            "volume": 50.0,
        }
        await processor.handle(
            Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=btc_data_1)
        )
        await processor.handle(
            Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=eth_data_1)
        )
        await asyncio.sleep(0.1)
        # No completions yet
        assert len(test_handler.captured_events) == 0
        # BTC candle 2 (new timestamp)
        btc_data_2 = btc_data_1.copy()
        btc_data_2["timestamp"] = 1640000060000
        btc_data_2["close"] = 50100.0
        await processor.handle(
            Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=btc_data_2)
        )
        await asyncio.sleep(0.1)
        # BTC candle completed, but not ETH
        assert len(test_handler.captured_events) == 1
        assert test_handler.captured_events[0].data["symbol"] == "BTCUSDT"
        stats = processor.get_statistics()
        assert stats["active_streams"] == 2


class TestDataValidation:
    """Test data validation and outlier filtering."""

    @pytest.mark.asyncio
    async def test_duplicate_filtering(self, processor, sample_candle_data):
        """Test that exact duplicates are filtered."""
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        event2 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await processor.handle(event1)
        await processor.handle(event2)
        stats = processor.get_statistics()
        assert stats["candles_processed"] == 1
        assert stats["duplicates_filtered"] == 1

    @pytest.mark.asyncio
    async def test_outlier_filtering(self, processor, sample_candle_data):
        """Test that price outliers are filtered."""
        # First candle
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await processor.handle(event1)
        # Outlier candle (price jumped 20% - abnormal for 1m)
        outlier_data = sample_candle_data.copy()
        outlier_data["timestamp"] = 1640000060000
        outlier_data["close"] = 60000.0  # 20% increase
        outlier_data["high"] = 60100.0
        outlier_data["open"] = 50000.0
        outlier_data["low"] = 50000.0
        event2 = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=outlier_data)
        await processor.handle(event2)
        stats = processor.get_statistics()
        assert stats["outliers_filtered"] == 1

    @pytest.mark.asyncio
    async def test_valid_price_change_accepted(self, processor, sample_candle_data):
        """Test that reasonable price changes are accepted."""
        # First candle
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await processor.handle(event1)
        # Valid candle with 2% price change
        valid_data = sample_candle_data.copy()
        valid_data["timestamp"] = 1640000060000
        valid_data["close"] = 51000.0  # 2% increase
        valid_data["high"] = 51100.0
        valid_data["low"] = 50000.0
        event2 = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=valid_data)
        await processor.handle(event2)
        stats = processor.get_statistics()
        assert stats["candles_processed"] == 2
        assert stats["outliers_filtered"] == 0


class TestStorageIntegration:
    """Test CandleStorage integration."""

    @pytest.mark.asyncio
    async def test_storage_integration(self, processor, sample_candle_data, storage):
        """Test that completed candles are stored."""
        # First candle
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await processor.handle(event1)
        # Second candle triggers completion of first
        candle_data_2 = sample_candle_data.copy()
        candle_data_2["timestamp"] = 1640000060000
        candle_data_2["close"] = 50100.0
        event2 = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=candle_data_2)
        await processor.handle(event2)
        # Check storage
        candles = storage.get_candles("BTCUSDT", TimeFrame.M1)
        assert len(candles) == 1
        assert candles[0].symbol == "BTCUSDT"
        assert candles[0].close == 50050.0  # First candle that completed (not the trigger)
        assert candles[0].is_closed is True

    @pytest.mark.asyncio
    async def test_processor_without_storage(
        self, processor_no_storage, sample_candle_data, event_bus
    ):
        """Test processor operates correctly without storage."""
        test_handler = CaptureHandler()
        event_bus.subscribe(EventType.CANDLE_CLOSED, test_handler)
        # First candle
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await event_bus.publish(event1)
        # Second candle
        candle_data_2 = sample_candle_data.copy()
        candle_data_2["timestamp"] = 1640000060000
        event2 = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=candle_data_2)
        await event_bus.publish(event2)
        await asyncio.sleep(0.1)
        # Should still publish CANDLE_CLOSED event
        assert len(test_handler.captured_events) == 1
        assert test_handler.captured_events[0].event_type == EventType.CANDLE_CLOSED


class TestEventTiming:
    """Test event timing and order."""

    @pytest.mark.asyncio
    async def test_candle_closed_priority(self, processor, sample_candle_data, event_bus):
        """Test that CANDLE_CLOSED events have higher priority."""
        test_handler = CaptureHandler()
        event_bus.subscribe(EventType.CANDLE_CLOSED, test_handler)
        # Process two candles
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await event_bus.publish(event1)
        candle_data_2 = sample_candle_data.copy()
        candle_data_2["timestamp"] = 1640000060000
        event2 = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=candle_data_2)
        await event_bus.publish(event2)
        await asyncio.sleep(0.1)
        # Check CANDLE_CLOSED event priority
        assert len(test_handler.captured_events) == 1
        assert test_handler.captured_events[0].priority == 7  # Higher than CANDLE_RECEIVED (6)

    @pytest.mark.asyncio
    async def test_multiple_timeframes(self, processor, event_bus):
        """Test processing multiple timeframes for same symbol."""
        test_handler = CaptureHandler()
        event_bus.subscribe(EventType.CANDLE_CLOSED, test_handler)
        # 1m candles
        m1_data_1 = {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "timestamp": 1640000000000,
            "open": 50000.0,
            "high": 50100.0,
            "low": 49900.0,
            "close": 50050.0,
            "volume": 10.5,
        }
        m1_data_2 = m1_data_1.copy()
        m1_data_2["timestamp"] = 1640000060000
        m1_data_2["close"] = 50100.0
        # 5m candles
        m5_data_1 = {
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "timestamp": 1640000000000,
            "open": 50000.0,
            "high": 50200.0,
            "low": 49800.0,
            "close": 50150.0,
            "volume": 50.0,
        }
        m5_data_2 = m5_data_1.copy()
        m5_data_2["timestamp"] = 1640000300000  # +5 minutes
        m5_data_2["close"] = 50200.0
        # Process candles
        await processor.handle(
            Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=m1_data_1)
        )
        await processor.handle(
            Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=m5_data_1)
        )
        await processor.handle(
            Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=m1_data_2)
        )
        await processor.handle(
            Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=m5_data_2)
        )
        await asyncio.sleep(0.1)
        # Should have 2 completions (1m and 5m)
        assert len(test_handler.captured_events) == 2
        stats = processor.get_statistics()
        assert stats["active_streams"] == 2  # 1m and 5m for BTCUSDT


class TestStatistics:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_statistics_tracking(self, processor, sample_candle_data):
        """Test that statistics are correctly tracked."""
        # Process valid candle
        event1 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await processor.handle(event1)
        # Process duplicate
        event2 = Event(
            event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data.copy()
        )
        await processor.handle(event2)
        # Process candle with new timestamp
        candle_data_3 = sample_candle_data.copy()
        candle_data_3["timestamp"] = 1640000060000
        event3 = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=candle_data_3)
        await processor.handle(event3)
        stats = processor.get_statistics()
        assert stats["candles_processed"] == 2  # event1 and event3
        assert stats["candles_closed"] == 1  # event3 completed event1
        assert stats["duplicates_filtered"] == 1
        assert stats["active_streams"] == 1

    @pytest.mark.asyncio
    async def test_clear_statistics(self, processor, sample_candle_data):
        """Test clearing statistics."""
        event = Event(event_type=EventType.CANDLE_RECEIVED, priority=6, data=sample_candle_data)
        await processor.handle(event)
        processor.clear_statistics()
        stats = processor.get_statistics()
        assert stats["candles_processed"] == 0
        assert stats["candles_closed"] == 0
        assert stats["duplicates_filtered"] == 0
        assert stats["outliers_filtered"] == 0


class TestCanHandleMethod:
    """Test can_handle method."""

    def test_can_handle_candle_received(self, processor):
        """Test that processor can handle CANDLE_RECEIVED events."""
        assert processor.can_handle(EventType.CANDLE_RECEIVED) is True

    def test_cannot_handle_other_events(self, processor):
        """Test that processor cannot handle other event types."""
        assert processor.can_handle(EventType.CANDLE_CLOSED) is False
        assert processor.can_handle(EventType.ORDER_PLACED) is False
