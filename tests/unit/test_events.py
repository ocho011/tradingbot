"""
Unit tests for the event system.

Tests cover:
- Event data class creation and validation
- EventHandler abstract base class
- EventQueue priority queue implementation
- EventBus pub/sub pattern
- Event dispatcher with error isolation
- Concurrent event processing
"""

import asyncio
from datetime import datetime
from typing import List

import pytest

from src.core.constants import EventType
from src.core.events import Event, EventBus, EventHandler, EventQueue


class TestEvent:
    """Test Event data class."""

    def test_event_creation(self):
        """Test basic event creation."""
        event = Event(
            priority=5,
            event_type=EventType.CANDLE_RECEIVED,
            data={"symbol": "BTCUSDT", "price": 50000},
        )
        assert event.priority == 5
        assert event.event_type == EventType.CANDLE_RECEIVED
        assert event.data["symbol"] == "BTCUSDT"
        assert event.source is None
        assert isinstance(event.timestamp, datetime)

    def test_event_with_source(self):
        """Test event creation with source."""
        event = Event(
            priority=3,
            event_type=EventType.SIGNAL_GENERATED,
            data={"action": "BUY"},
            source="StrategyEngine",
        )
        assert event.source == "StrategyEngine"

    def test_event_priority_validation(self):
        """Test event priority validation."""
        # Valid priorities
        Event(priority=0, event_type=EventType.SYSTEM_START)
        Event(priority=10, event_type=EventType.SYSTEM_START)

        # Invalid priorities
        with pytest.raises(ValueError):
            Event(priority=-1, event_type=EventType.SYSTEM_START)
        with pytest.raises(ValueError):
            Event(priority=11, event_type=EventType.SYSTEM_START)

    def test_event_type_validation(self):
        """Test event type validation."""
        with pytest.raises(TypeError):
            Event(priority=5, event_type="invalid_type")

    def test_event_comparison(self):
        """Test event comparison for priority ordering."""
        event1 = Event(priority=5, event_type=EventType.CANDLE_RECEIVED)
        event2 = Event(priority=3, event_type=EventType.SIGNAL_GENERATED)
        event3 = Event(priority=5, event_type=EventType.ORDER_PLACED)

        # Lower priority value means lower priority (3 < 5)
        assert event2 < event1  # 3 < 5 in numeric comparison
        # Same priority compares by timestamp
        assert event1 < event3 or event3 < event1


class MockHandler(EventHandler):
    """Mock event handler for testing."""

    def __init__(self, name: str = "MockHandler"):
        super().__init__(name)
        self.handled_events: List[Event] = []
        self.errors: List[Exception] = []
        self.should_raise = False

    async def handle(self, event: Event) -> None:
        """Handle event and record it."""
        self.handled_events.append(event)
        if self.should_raise:
            raise RuntimeError(f"Mock error from {self.name}")

    async def on_error(self, event: Event, error: Exception) -> None:
        """Record errors."""
        self.errors.append(error)


class FilteringHandler(EventHandler):
    """Handler that filters specific event types."""

    def __init__(self, allowed_types: List[EventType]):
        super().__init__("FilteringHandler")
        self.allowed_types = allowed_types
        self.handled_events: List[Event] = []

    def can_handle(self, event_type: EventType) -> bool:
        """Filter event types."""
        return event_type in self.allowed_types

    async def handle(self, event: Event) -> None:
        """Handle event."""
        self.handled_events.append(event)


class TestEventHandler:
    """Test EventHandler abstract base class."""

    def test_handler_initialization(self):
        """Test handler initialization."""
        handler = MockHandler("TestHandler")
        assert handler.name == "TestHandler"

    def test_handler_default_name(self):
        """Test handler with default name."""
        handler = MockHandler()
        assert handler.name == "MockHandler"

    @pytest.mark.asyncio
    async def test_handler_can_handle(self):
        """Test handler can_handle method."""
        handler = MockHandler()
        # Default implementation returns True for all
        assert handler.can_handle(EventType.CANDLE_RECEIVED)
        assert handler.can_handle(EventType.SIGNAL_GENERATED)

    @pytest.mark.asyncio
    async def test_filtering_handler(self):
        """Test handler with event type filtering."""
        handler = FilteringHandler([EventType.CANDLE_RECEIVED, EventType.ORDER_PLACED])

        assert handler.can_handle(EventType.CANDLE_RECEIVED)
        assert handler.can_handle(EventType.ORDER_PLACED)
        assert not handler.can_handle(EventType.SIGNAL_GENERATED)


class TestEventQueue:
    """Test EventQueue priority queue implementation."""

    @pytest.mark.asyncio
    async def test_queue_basic_operations(self):
        """Test basic queue operations."""
        queue = EventQueue()
        assert queue.empty()
        assert queue.size() == 0

        event = Event(priority=5, event_type=EventType.CANDLE_RECEIVED)
        await queue.put(event)

        assert not queue.empty()
        assert queue.size() == 1

        retrieved = await queue.get()
        assert retrieved == event
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_queue_priority_ordering(self):
        """Test queue processes events by priority."""
        queue = EventQueue()

        # Add events with different priorities
        event_low = Event(priority=3, event_type=EventType.SYSTEM_START)
        event_medium = Event(priority=5, event_type=EventType.CANDLE_RECEIVED)
        event_high = Event(priority=8, event_type=EventType.SIGNAL_GENERATED)

        await queue.put(event_medium)
        await queue.put(event_low)
        await queue.put(event_high)

        # Should retrieve in priority order (high to low)
        assert (await queue.get()).priority == 8
        assert (await queue.get()).priority == 5
        assert (await queue.get()).priority == 3

    @pytest.mark.asyncio
    async def test_queue_fifo_within_priority(self):
        """Test FIFO ordering within same priority."""
        queue = EventQueue()

        # Add multiple events with same priority
        events = [
            Event(priority=5, event_type=EventType.CANDLE_RECEIVED, data={"id": i})
            for i in range(5)
        ]

        for event in events:
            await queue.put(event)

        # Should retrieve in FIFO order
        for i in range(5):
            retrieved = await queue.get()
            assert retrieved.data["id"] == i

    @pytest.mark.asyncio
    async def test_queue_peek(self):
        """Test queue peek operation."""
        queue = EventQueue()

        assert await queue.peek() is None

        event = Event(priority=5, event_type=EventType.CANDLE_RECEIVED)
        await queue.put(event)

        peeked = await queue.peek()
        assert peeked == event
        assert queue.size() == 1  # Peek doesn't remove

    @pytest.mark.asyncio
    async def test_queue_clear(self):
        """Test queue clear operation."""
        queue = EventQueue()

        # Add multiple events
        for i in range(10):
            await queue.put(Event(priority=i, event_type=EventType.CANDLE_RECEIVED))

        assert queue.size() == 10

        await queue.clear()
        assert queue.empty()
        assert queue.size() == 0

    @pytest.mark.asyncio
    async def test_queue_empty_get_raises(self):
        """Test that getting from empty queue raises error."""
        queue = EventQueue()

        with pytest.raises(IndexError):
            await queue.get()


class TestEventBus:
    """Test EventBus pub/sub implementation."""

    @pytest.mark.asyncio
    async def test_bus_subscription(self):
        """Test handler subscription."""
        bus = EventBus()
        handler = MockHandler()

        bus.subscribe(EventType.CANDLE_RECEIVED, handler)

        # Verify subscription
        assert EventType.CANDLE_RECEIVED in bus._subscribers
        assert handler in bus._subscribers[EventType.CANDLE_RECEIVED]

    @pytest.mark.asyncio
    async def test_bus_global_subscription(self):
        """Test global handler subscription."""
        bus = EventBus()
        handler = MockHandler()

        bus.subscribe_all(handler)

        assert handler in bus._global_handlers

    @pytest.mark.asyncio
    async def test_bus_unsubscription(self):
        """Test handler unsubscription."""
        bus = EventBus()
        handler = MockHandler()

        bus.subscribe(EventType.CANDLE_RECEIVED, handler)
        bus.unsubscribe(EventType.CANDLE_RECEIVED, handler)

        assert EventType.CANDLE_RECEIVED not in bus._subscribers

    @pytest.mark.asyncio
    async def test_bus_publish_and_dispatch(self):
        """Test event publishing and dispatching."""
        bus = EventBus()
        handler = MockHandler()

        bus.subscribe(EventType.CANDLE_RECEIVED, handler)

        await bus.start()

        event = Event(priority=5, event_type=EventType.CANDLE_RECEIVED, data={"test": True})
        await bus.publish(event)

        # Wait for processing
        await bus.wait_empty(timeout=1.0)

        await bus.stop()

        # Verify handler received event
        assert len(handler.handled_events) == 1
        assert handler.handled_events[0].data["test"] is True

    @pytest.mark.asyncio
    async def test_bus_multiple_handlers(self):
        """Test multiple handlers for same event."""
        bus = EventBus()
        handler1 = MockHandler("Handler1")
        handler2 = MockHandler("Handler2")

        bus.subscribe(EventType.CANDLE_RECEIVED, handler1)
        bus.subscribe(EventType.CANDLE_RECEIVED, handler2)

        await bus.start()

        event = Event(priority=5, event_type=EventType.CANDLE_RECEIVED)
        await bus.publish(event)

        await bus.wait_empty(timeout=1.0)
        await bus.stop()

        # Both handlers should receive event
        assert len(handler1.handled_events) == 1
        assert len(handler2.handled_events) == 1

    @pytest.mark.asyncio
    async def test_bus_global_handlers_receive_all(self):
        """Test global handlers receive all events."""
        bus = EventBus()
        global_handler = MockHandler("Global")

        bus.subscribe_all(global_handler)

        await bus.start()

        # Publish different event types
        events = [
            Event(priority=5, event_type=EventType.CANDLE_RECEIVED),
            Event(priority=5, event_type=EventType.SIGNAL_GENERATED),
            Event(priority=5, event_type=EventType.ORDER_PLACED),
        ]

        for event in events:
            await bus.publish(event)

        await bus.wait_empty(timeout=1.0)
        await bus.stop()

        # Global handler should receive all events
        assert len(global_handler.handled_events) == 3

    @pytest.mark.asyncio
    async def test_bus_error_isolation(self):
        """Test that handler errors don't affect other handlers."""
        bus = EventBus()
        good_handler = MockHandler("Good")
        bad_handler = MockHandler("Bad")
        bad_handler.should_raise = True

        bus.subscribe(EventType.CANDLE_RECEIVED, good_handler)
        bus.subscribe(EventType.CANDLE_RECEIVED, bad_handler)

        await bus.start()

        event = Event(priority=5, event_type=EventType.CANDLE_RECEIVED)
        await bus.publish(event)

        await bus.wait_empty(timeout=1.0)
        await bus.stop()

        # Good handler should still receive event
        assert len(good_handler.handled_events) == 1
        # Bad handler's error should be recorded
        assert len(bad_handler.errors) == 1

    @pytest.mark.asyncio
    async def test_bus_priority_processing(self):
        """Test events are processed by priority."""
        bus = EventBus()
        handler = MockHandler()

        bus.subscribe_all(handler)

        await bus.start()

        # Publish events with different priorities
        event_low = Event(priority=3, event_type=EventType.CANDLE_RECEIVED, data={"priority": 3})
        event_high = Event(priority=8, event_type=EventType.SIGNAL_GENERATED, data={"priority": 8})
        event_medium = Event(priority=5, event_type=EventType.ORDER_PLACED, data={"priority": 5})

        await bus.publish(event_low)
        await bus.publish(event_high)
        await bus.publish(event_medium)

        await bus.wait_empty(timeout=1.0)
        await bus.stop()

        # Should process in priority order
        assert len(handler.handled_events) == 3
        assert handler.handled_events[0].data["priority"] == 8
        assert handler.handled_events[1].data["priority"] == 5
        assert handler.handled_events[2].data["priority"] == 3

    @pytest.mark.asyncio
    async def test_bus_max_queue_size(self):
        """Test queue size limit."""
        bus = EventBus(max_queue_size=5)

        # Fill queue
        for i in range(5):
            result = await bus.publish(Event(priority=5, event_type=EventType.CANDLE_RECEIVED))
            assert result is True

        # Next publish should fail
        result = await bus.publish(Event(priority=5, event_type=EventType.CANDLE_RECEIVED))
        assert result is False

        stats = bus.get_stats()
        assert stats["dropped"] == 1

    @pytest.mark.asyncio
    async def test_bus_filtering_handler(self):
        """Test handlers with event type filtering."""
        bus = EventBus()
        candle_handler = FilteringHandler([EventType.CANDLE_RECEIVED])
        signal_handler = FilteringHandler([EventType.SIGNAL_GENERATED])

        bus.subscribe(EventType.CANDLE_RECEIVED, candle_handler)
        bus.subscribe(EventType.SIGNAL_GENERATED, signal_handler)
        # Also subscribe both to opposite types to test filtering
        bus.subscribe(EventType.CANDLE_RECEIVED, signal_handler)
        bus.subscribe(EventType.SIGNAL_GENERATED, candle_handler)

        await bus.start()

        candle_event = Event(priority=5, event_type=EventType.CANDLE_RECEIVED)
        signal_event = Event(priority=5, event_type=EventType.SIGNAL_GENERATED)

        await bus.publish(candle_event)
        await bus.publish(signal_event)

        await bus.wait_empty(timeout=1.0)
        await bus.stop()

        # Each handler should only receive their filtered events
        assert len(candle_handler.handled_events) == 1
        assert candle_handler.handled_events[0].event_type == EventType.CANDLE_RECEIVED

        assert len(signal_handler.handled_events) == 1
        assert signal_handler.handled_events[0].event_type == EventType.SIGNAL_GENERATED

    @pytest.mark.asyncio
    async def test_bus_statistics(self):
        """Test event bus statistics tracking."""
        bus = EventBus()
        handler = MockHandler()

        bus.subscribe(EventType.CANDLE_RECEIVED, handler)

        await bus.start()

        # Publish some events
        for i in range(5):
            await bus.publish(Event(priority=5, event_type=EventType.CANDLE_RECEIVED))

        await bus.wait_empty(timeout=1.0)
        await bus.stop()

        stats = bus.get_stats()
        assert stats["published"] == 5
        assert stats["processed"] == 5
        assert stats["errors"] == 0
        assert stats["dropped"] == 0

    @pytest.mark.asyncio
    async def test_bus_concurrent_publishing(self):
        """Test concurrent event publishing."""
        bus = EventBus()
        handler = MockHandler()

        bus.subscribe_all(handler)

        await bus.start()

        # Publish events concurrently
        async def publish_events(count: int):
            for i in range(count):
                await bus.publish(
                    Event(priority=5, event_type=EventType.CANDLE_RECEIVED, data={"id": i})
                )

        await asyncio.gather(publish_events(10), publish_events(10), publish_events(10))

        await bus.wait_empty(timeout=2.0)
        await bus.stop()

        # All events should be processed
        assert len(handler.handled_events) == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
