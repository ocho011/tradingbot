"""
Tests for Signal Event Publishing System
"""

import pytest
from decimal import Decimal
from time import sleep

from src.services.strategy.signal import Signal, SignalDirection
from src.services.strategy.events import (
    SignalEventPublisher,
    SignalEventType,
    SignalEvent,
)


class TestSignalEvent:
    """Test SignalEvent class"""

    def test_create_event(self):
        """Test creating a signal event"""
        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        event = SignalEvent(
            event_type=SignalEventType.SIGNAL_GENERATED,
            signal=signal,
            metadata={'test': 'data'}
        )

        assert event.event_type == SignalEventType.SIGNAL_GENERATED
        assert event.signal == signal
        assert event.metadata['test'] == 'data'
        assert event.timestamp is not None

    def test_event_to_dict(self):
        """Test converting event to dictionary"""
        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        event = SignalEvent(
            event_type=SignalEventType.SIGNAL_VALIDATED,
            signal=signal,
        )

        data = event.to_dict()

        assert data['event_type'] == 'signal_validated'
        assert 'signal' in data
        assert 'timestamp' in data


class TestSignalEventPublisher:
    """Test SignalEventPublisher functionality"""

    def test_publisher_initialization(self):
        """Test publisher initialization"""
        publisher = SignalEventPublisher(enable_async=False)

        assert publisher._enable_async is False
        assert len(publisher._listeners) == len(SignalEventType)

    def test_subscribe_and_publish_sync(self):
        """Test subscribing and publishing events synchronously"""
        publisher = SignalEventPublisher(enable_async=False)
        events_received = []

        def on_signal(event: SignalEvent):
            events_received.append(event)

        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, on_signal)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)

        assert len(events_received) == 1
        assert events_received[0].signal == signal

    def test_subscribe_and_publish_async(self):
        """Test subscribing and publishing events asynchronously"""
        publisher = SignalEventPublisher(enable_async=True, max_workers=2)
        events_received = []

        def on_signal(event: SignalEvent):
            events_received.append(event)

        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, on_signal)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)

        # Wait for async execution
        sleep(0.1)

        assert len(events_received) == 1
        assert events_received[0].signal == signal

        publisher.shutdown()

    def test_multiple_listeners(self):
        """Test multiple listeners for same event"""
        publisher = SignalEventPublisher(enable_async=False)
        events1 = []
        events2 = []

        def listener1(event: SignalEvent):
            events1.append(event)

        def listener2(event: SignalEvent):
            events2.append(event)

        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, listener1)
        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, listener2)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)

        assert len(events1) == 1
        assert len(events2) == 1

    def test_unsubscribe(self):
        """Test unsubscribing from events"""
        publisher = SignalEventPublisher(enable_async=False)
        events_received = []

        def on_signal(event: SignalEvent):
            events_received.append(event)

        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, on_signal)
        publisher.unsubscribe(SignalEventType.SIGNAL_GENERATED, on_signal)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)

        assert len(events_received) == 0

    def test_event_history(self):
        """Test event history tracking"""
        publisher = SignalEventPublisher(enable_async=False)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)
        publisher.publish(SignalEventType.SIGNAL_VALIDATED, signal)

        history = publisher.get_event_history()

        assert len(history) == 2
        assert history[0].event_type == SignalEventType.SIGNAL_VALIDATED  # Most recent first

    def test_event_history_filtered(self):
        """Test filtering event history by type"""
        publisher = SignalEventPublisher(enable_async=False)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)
        publisher.publish(SignalEventType.SIGNAL_VALIDATED, signal)
        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)

        generated_history = publisher.get_event_history(
            event_type=SignalEventType.SIGNAL_GENERATED
        )

        assert len(generated_history) == 2
        assert all(e.event_type == SignalEventType.SIGNAL_GENERATED for e in generated_history)

    def test_event_history_limit(self):
        """Test limiting event history results"""
        publisher = SignalEventPublisher(enable_async=False)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        for _ in range(5):
            publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)

        limited_history = publisher.get_event_history(limit=3)

        assert len(limited_history) == 3

    def test_clear_history(self):
        """Test clearing event history"""
        publisher = SignalEventPublisher(enable_async=False)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)
        assert len(publisher.get_event_history()) == 1

        publisher.clear_history()
        assert len(publisher.get_event_history()) == 0

    def test_listener_count(self):
        """Test getting listener count"""
        publisher = SignalEventPublisher(enable_async=False)

        def listener1(event):
            pass

        def listener2(event):
            pass

        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, listener1)
        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, listener2)

        count = publisher.get_listener_count(SignalEventType.SIGNAL_GENERATED)

        assert count == 2

    def test_listener_error_handling(self):
        """Test that errors in listeners don't crash the publisher"""
        publisher = SignalEventPublisher(enable_async=False)

        def bad_listener(event):
            raise ValueError("Test error")

        publisher.subscribe(SignalEventType.SIGNAL_GENERATED, bad_listener)

        signal = Signal(
            entry_price=Decimal('50000'),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal('49000'),
            take_profit=Decimal('52000'),
            symbol='BTCUSDT',
            strategy_name='Strategy_A',
        )

        # Should not raise error
        publisher.publish(SignalEventType.SIGNAL_GENERATED, signal)

        # Event should still be in history
        assert len(publisher.get_event_history()) == 1
