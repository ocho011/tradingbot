"""
Signal Event Publishing System

Provides event-driven architecture for signal generation and tracking.
"""

from typing import Callable, List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

from src.services.strategy.signal import Signal

logger = logging.getLogger(__name__)


class SignalEventType(Enum):
    """Types of signal events"""
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_VALIDATED = "signal_validated"
    SIGNAL_REJECTED = "signal_rejected"
    SIGNAL_EXECUTED = "signal_executed"
    SIGNAL_CANCELLED = "signal_cancelled"


class SignalEvent:
    """
    Signal event data structure.

    Contains the signal and metadata about the event.
    """

    def __init__(
        self,
        event_type: SignalEventType,
        signal: Signal,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ):
        self.event_type = event_type
        self.signal = signal
        self.metadata = metadata or {}
        self.timestamp = timestamp or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization"""
        return {
            'event_type': self.event_type.value,
            'signal': self.signal.to_dict(),
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat(),
        }

    def __repr__(self) -> str:
        return f"SignalEvent({self.event_type.value}, signal_id={self.signal.signal_id[:8]}...)"


class SignalEventPublisher:
    """
    Event publisher for trading signals.

    Implements publish-subscribe pattern for signal events with support
    for both synchronous and asynchronous listeners.
    """

    def __init__(self, enable_async: bool = True, max_workers: int = 4):
        """
        Initialize event publisher.

        Args:
            enable_async: Enable asynchronous event handling
            max_workers: Maximum number of worker threads for async execution
        """
        self._listeners: Dict[SignalEventType, List[Callable]] = {
            event_type: [] for event_type in SignalEventType
        }
        self._enable_async = enable_async
        self._executor = ThreadPoolExecutor(max_workers=max_workers) if enable_async else None
        self._event_history: List[SignalEvent] = []
        self._max_history = 1000

        logger.info(
            f"SignalEventPublisher initialized (async={enable_async}, workers={max_workers})"
        )

    def subscribe(
        self,
        event_type: SignalEventType,
        callback: Callable[[SignalEvent], None],
    ):
        """
        Subscribe to a signal event type.

        Args:
            event_type: Type of event to subscribe to
            callback: Function to call when event occurs (receives SignalEvent)

        Example:
            def on_signal_generated(event: SignalEvent):
                print(f"New signal: {event.signal}")

            publisher.subscribe(SignalEventType.SIGNAL_GENERATED, on_signal_generated)
        """
        if callback not in self._listeners[event_type]:
            self._listeners[event_type].append(callback)
            logger.info(f"Subscribed {callback.__name__} to {event_type.value}")
        else:
            logger.warning(f"Callback {callback.__name__} already subscribed to {event_type.value}")

    def unsubscribe(
        self,
        event_type: SignalEventType,
        callback: Callable[[SignalEvent], None],
    ):
        """
        Unsubscribe from a signal event type.

        Args:
            event_type: Type of event to unsubscribe from
            callback: Callback function to remove
        """
        if callback in self._listeners[event_type]:
            self._listeners[event_type].remove(callback)
            logger.info(f"Unsubscribed {callback.__name__} from {event_type.value}")
        else:
            logger.warning(
                f"Callback {callback.__name__} not found in {event_type.value} listeners"
            )

    def publish(
        self,
        event_type: SignalEventType,
        signal: Signal,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Publish a signal event to all subscribers.

        Args:
            event_type: Type of event being published
            signal: Signal associated with the event
            metadata: Additional event metadata

        Example:
            publisher.publish(
                SignalEventType.SIGNAL_GENERATED,
                signal,
                metadata={'strategy': 'Strategy_A'}
            )
        """
        event = SignalEvent(event_type, signal, metadata)

        # Add to event history
        self._add_to_history(event)

        # Get listeners for this event type
        listeners = self._listeners.get(event_type, [])

        if not listeners:
            logger.debug(f"No listeners for {event_type.value}")
            return

        logger.info(
            f"Publishing {event_type.value} for signal {signal.signal_id[:8]}... "
            f"to {len(listeners)} listener(s)"
        )

        # Execute listeners
        if self._enable_async:
            self._publish_async(event, listeners)
        else:
            self._publish_sync(event, listeners)

    def _publish_sync(self, event: SignalEvent, listeners: List[Callable]):
        """
        Publish event synchronously to all listeners.

        Args:
            event: Event to publish
            listeners: List of callback functions
        """
        for callback in listeners:
            try:
                callback(event)
            except Exception as e:
                logger.error(
                    f"Error in listener {callback.__name__} for {event.event_type.value}: {e}",
                    exc_info=True
                )

    def _publish_async(self, event: SignalEvent, listeners: List[Callable]):
        """
        Publish event asynchronously to all listeners.

        Args:
            event: Event to publish
            listeners: List of callback functions
        """
        for callback in listeners:
            if self._executor:
                self._executor.submit(self._execute_listener, callback, event)

    def _execute_listener(self, callback: Callable, event: SignalEvent):
        """
        Execute a single listener callback with error handling.

        Args:
            callback: Callback function to execute
            event: Event to pass to callback
        """
        try:
            callback(event)
        except Exception as e:
            logger.error(
                f"Error in async listener {callback.__name__} for {event.event_type.value}: {e}",
                exc_info=True
            )

    def _add_to_history(self, event: SignalEvent):
        """
        Add event to history, maintaining max size.

        Args:
            event: Event to add to history
        """
        self._event_history.append(event)

        # Trim history if it exceeds max size
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

    def get_event_history(
        self,
        event_type: Optional[SignalEventType] = None,
        limit: Optional[int] = None,
    ) -> List[SignalEvent]:
        """
        Get event history, optionally filtered by type.

        Args:
            event_type: Filter by event type (None = all types)
            limit: Maximum number of events to return (most recent first)

        Returns:
            List of events in reverse chronological order
        """
        events = self._event_history

        # Filter by event type if specified
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        # Reverse to get most recent first
        events = list(reversed(events))

        # Apply limit if specified
        if limit:
            events = events[:limit]

        return events

    def get_listener_count(self, event_type: SignalEventType) -> int:
        """
        Get number of listeners for an event type.

        Args:
            event_type: Event type to check

        Returns:
            Number of registered listeners
        """
        return len(self._listeners.get(event_type, []))

    def clear_history(self):
        """Clear event history"""
        self._event_history.clear()
        logger.info("Event history cleared")

    def shutdown(self):
        """Shutdown event publisher and cleanup resources"""
        if self._executor:
            self._executor.shutdown(wait=True)
            logger.info("Event publisher executor shutdown")

    def __del__(self):
        """Cleanup on deletion"""
        self.shutdown()

    def __repr__(self) -> str:
        total_listeners = sum(len(listeners) for listeners in self._listeners.values())
        return (
            f"SignalEventPublisher(listeners={total_listeners}, "
            f"history={len(self._event_history)}, async={self._enable_async})"
        )


# Global event publisher instance
_global_publisher: Optional[SignalEventPublisher] = None


def get_event_publisher() -> SignalEventPublisher:
    """
    Get the global event publisher instance (singleton pattern).

    Returns:
        Global SignalEventPublisher instance
    """
    global _global_publisher

    if _global_publisher is None:
        _global_publisher = SignalEventPublisher(enable_async=True, max_workers=4)
        logger.info("Created global SignalEventPublisher instance")

    return _global_publisher


def publish_signal_generated(signal: Signal, metadata: Optional[Dict[str, Any]] = None):
    """
    Convenience function to publish signal_generated event.

    Args:
        signal: Signal that was generated
        metadata: Additional event metadata
    """
    publisher = get_event_publisher()
    publisher.publish(SignalEventType.SIGNAL_GENERATED, signal, metadata)


def publish_signal_validated(signal: Signal, metadata: Optional[Dict[str, Any]] = None):
    """
    Convenience function to publish signal_validated event.

    Args:
        signal: Signal that was validated
        metadata: Additional event metadata (e.g., validation results)
    """
    publisher = get_event_publisher()
    publisher.publish(SignalEventType.SIGNAL_VALIDATED, signal, metadata)


def publish_signal_rejected(signal: Signal, metadata: Optional[Dict[str, Any]] = None):
    """
    Convenience function to publish signal_rejected event.

    Args:
        signal: Signal that was rejected
        metadata: Additional event metadata (e.g., rejection reasons)
    """
    publisher = get_event_publisher()
    publisher.publish(SignalEventType.SIGNAL_REJECTED, signal, metadata)
