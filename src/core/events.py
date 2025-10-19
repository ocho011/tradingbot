"""
Event system implementation for the trading bot.

This module provides a priority-based event system with pub/sub pattern
for decoupling components and handling asynchronous event processing.
"""

import asyncio
import heapq
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from src.core.constants import EventType

logger = logging.getLogger(__name__)


@dataclass(order=True)
class Event:
    """
    Event data class representing a system event.

    Events are ordered by priority (higher priority first) and timestamp.
    """

    priority: int = field(compare=True)
    event_type: EventType = field(compare=False)
    timestamp: datetime = field(compare=True, default_factory=datetime.now)
    data: Dict[str, Any] = field(compare=False, default_factory=dict)
    source: Optional[str] = field(compare=False, default=None)

    def __post_init__(self):
        """Validate event after initialization."""
        if not isinstance(self.event_type, EventType):
            raise TypeError(f"event_type must be EventType, got {type(self.event_type)}")
        if self.priority < 0 or self.priority > 10:
            raise ValueError(f"priority must be between 0 and 10, got {self.priority}")


class EventHandler(ABC):
    """
    Abstract base class for event handlers.

    All event handlers must implement the handle method and can optionally
    override the on_error method for custom error handling.
    """

    def __init__(self, name: Optional[str] = None):
        """
        Initialize event handler.

        Args:
            name: Optional name for the handler (defaults to class name)
        """
        self.name = name or self.__class__.__name__
        self.logger = logging.getLogger(f"{__name__}.{self.name}")

    @abstractmethod
    async def handle(self, event: Event) -> None:
        """
        Handle an event.

        Args:
            event: The event to handle

        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        pass

    async def on_error(self, event: Event, error: Exception) -> None:
        """
        Handle errors that occur during event processing.

        Default implementation logs the error. Override for custom behavior.

        Args:
            event: The event that caused the error
            error: The exception that occurred
        """
        self.logger.error(
            f"Error handling event {event.event_type} from {event.source}: {error}",
            exc_info=True
        )

    def can_handle(self, event_type: EventType) -> bool:
        """
        Check if this handler can handle a specific event type.

        Default implementation returns True for all event types.
        Override to filter specific event types.

        Args:
            event_type: The event type to check

        Returns:
            True if this handler can handle the event type
        """
        return True


class EventQueue:
    """
    Priority queue for events using heapq.

    Events with lower priority values are processed first.
    Events with the same priority are processed in FIFO order.
    """

    def __init__(self):
        """Initialize the priority queue."""
        self._queue: List[Event] = []
        self._counter = 0  # For stable sorting when priorities are equal
        self._lock = asyncio.Lock()

    async def put(self, event: Event) -> None:
        """
        Add an event to the queue.

        Args:
            event: The event to add
        """
        async with self._lock:
            # Use negative priority for max-heap behavior (higher priority first)
            # Use counter for stable FIFO ordering within same priority
            heapq.heappush(
                self._queue,
                (-event.priority, self._counter, event.timestamp, event)
            )
            self._counter += 1

    async def get(self) -> Event:
        """
        Get the highest priority event from the queue.

        Returns:
            The highest priority event

        Raises:
            IndexError: If the queue is empty
        """
        async with self._lock:
            if not self._queue:
                raise IndexError("Queue is empty")
            _, _, _, event = heapq.heappop(self._queue)
            return event

    async def peek(self) -> Optional[Event]:
        """
        Peek at the highest priority event without removing it.

        Returns:
            The highest priority event or None if queue is empty
        """
        async with self._lock:
            if not self._queue:
                return None
            return self._queue[0][3]

    def empty(self) -> bool:
        """
        Check if the queue is empty.

        Returns:
            True if the queue is empty
        """
        return len(self._queue) == 0

    def size(self) -> int:
        """
        Get the current size of the queue.

        Returns:
            Number of events in the queue
        """
        return len(self._queue)

    async def clear(self) -> None:
        """Clear all events from the queue."""
        async with self._lock:
            self._queue.clear()
            self._counter = 0


class EventBus:
    """
    Event bus implementing pub/sub pattern with priority-based processing.

    Handles event publishing, subscription management, and asynchronous
    event dispatching with error isolation.
    """

    def __init__(self, max_queue_size: int = 10000):
        """
        Initialize the event bus.

        Args:
            max_queue_size: Maximum number of events in the queue
        """
        self._subscribers: Dict[EventType, Set[EventHandler]] = {}
        self._global_handlers: Set[EventHandler] = set()
        self._queue = EventQueue()
        self._max_queue_size = max_queue_size
        self._running = False
        self._dispatcher_task: Optional[asyncio.Task] = None
        self._stats = {
            "published": 0,
            "processed": 0,
            "errors": 0,
            "dropped": 0
        }
        self.logger = logging.getLogger(f"{__name__}.EventBus")

    def subscribe(
        self,
        event_type: EventType,
        handler: EventHandler
    ) -> None:
        """
        Subscribe a handler to a specific event type.

        Args:
            event_type: The event type to subscribe to
            handler: The handler to register
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = set()
        self._subscribers[event_type].add(handler)
        self.logger.debug(f"Handler {handler.name} subscribed to {event_type}")

    def subscribe_all(self, handler: EventHandler) -> None:
        """
        Subscribe a handler to all event types.

        Args:
            handler: The handler to register for all events
        """
        self._global_handlers.add(handler)
        self.logger.debug(f"Handler {handler.name} subscribed to all events")

    def unsubscribe(
        self,
        event_type: EventType,
        handler: EventHandler
    ) -> None:
        """
        Unsubscribe a handler from a specific event type.

        Args:
            event_type: The event type to unsubscribe from
            handler: The handler to remove
        """
        if event_type in self._subscribers:
            self._subscribers[event_type].discard(handler)
            if not self._subscribers[event_type]:
                del self._subscribers[event_type]
            self.logger.debug(f"Handler {handler.name} unsubscribed from {event_type}")

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """
        Unsubscribe a handler from all event types.

        Args:
            handler: The handler to remove from all subscriptions
        """
        self._global_handlers.discard(handler)
        for event_type in list(self._subscribers.keys()):
            self.unsubscribe(event_type, handler)

    async def publish(self, event: Event) -> bool:
        """
        Publish an event to the bus.

        Args:
            event: The event to publish

        Returns:
            True if the event was queued, False if dropped due to full queue
        """
        if self._queue.size() >= self._max_queue_size:
            self.logger.warning(
                f"Event queue full ({self._max_queue_size}), dropping event {event.event_type}"
            )
            self._stats["dropped"] += 1
            return False

        await self._queue.put(event)
        self._stats["published"] += 1
        self.logger.debug(
            f"Published event {event.event_type} with priority {event.priority}"
        )
        return True

    async def start(self) -> None:
        """Start the event dispatcher."""
        if self._running:
            self.logger.warning("Event bus already running")
            return

        self._running = True
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())
        self.logger.info("Event bus started")

    async def stop(self) -> None:
        """Stop the event dispatcher and wait for completion."""
        if not self._running:
            return

        self._running = False
        if self._dispatcher_task:
            await self._dispatcher_task
        self.logger.info("Event bus stopped")

    async def _dispatch_loop(self) -> None:
        """
        Main event dispatcher loop.

        Continuously processes events from the queue and dispatches them
        to registered handlers with error isolation.
        """
        self.logger.info("Event dispatcher loop started")

        while self._running:
            try:
                # Wait for events with a timeout to allow clean shutdown
                if self._queue.empty():
                    await asyncio.sleep(0.01)
                    continue

                event = await self._queue.get()
                await self._dispatch_event(event)

            except asyncio.CancelledError:
                self.logger.info("Dispatcher loop cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in dispatcher loop: {e}", exc_info=True)
                await asyncio.sleep(0.1)  # Brief pause on error

        self.logger.info("Event dispatcher loop stopped")

    async def _dispatch_event(self, event: Event) -> None:
        """
        Dispatch an event to all registered handlers.

        Handlers are executed concurrently with error isolation.
        Each handler's errors are caught and logged without affecting other handlers.

        Args:
            event: The event to dispatch
        """
        # Collect all handlers for this event
        handlers = set()

        # Add specific handlers
        if event.event_type in self._subscribers:
            handlers.update(self._subscribers[event.event_type])

        # Add global handlers
        handlers.update(self._global_handlers)

        # Filter handlers that can handle this event type
        handlers = {h for h in handlers if h.can_handle(event.event_type)}

        if not handlers:
            self.logger.debug(f"No handlers for event {event.event_type}")
            return

        # Dispatch to all handlers concurrently with error isolation
        tasks = [
            self._safe_handle(handler, event)
            for handler in handlers
        ]

        await asyncio.gather(*tasks, return_exceptions=True)
        self._stats["processed"] += 1

    async def _safe_handle(self, handler: EventHandler, event: Event) -> None:
        """
        Safely execute a handler with error isolation.

        Args:
            handler: The handler to execute
            event: The event to handle
        """
        try:
            await handler.handle(event)
        except Exception as e:
            self._stats["errors"] += 1
            try:
                await handler.on_error(event, e)
            except Exception as error_handler_error:
                self.logger.error(
                    f"Error in error handler for {handler.name}: {error_handler_error}",
                    exc_info=True
                )

    def get_stats(self) -> Dict[str, int]:
        """
        Get event bus statistics.

        Returns:
            Dictionary with statistics (published, processed, errors, dropped)
        """
        return {
            **self._stats,
            "queue_size": self._queue.size(),
            "subscriber_count": sum(len(handlers) for handlers in self._subscribers.values()),
            "global_handler_count": len(self._global_handlers)
        }

    async def wait_empty(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the event queue to be empty.

        Args:
            timeout: Maximum time to wait in seconds (None for infinite)

        Returns:
            True if queue became empty, False if timeout occurred
        """
        start_time = asyncio.get_event_loop().time()

        while not self._queue.empty():
            if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                return False
            await asyncio.sleep(0.01)

        return True
