"""
WebSocket Manager for Real-time Communication.

Provides WebSocket server functionality for real-time data streaming,
signal notifications, and trade status updates with subscription management
and heartbeat mechanism.
"""

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.core.constants import EventType
from src.core.events import Event, EventBus, EventHandler

logger = logging.getLogger(__name__)


# ============================================================================
# Message Types and Models
# ============================================================================

class MessageType(str, Enum):
    """WebSocket message types."""

    # Client to Server
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"
    GET_SUBSCRIPTIONS = "get_subscriptions"

    # Server to Client
    PONG = "pong"
    CANDLE_UPDATE = "candle_update"
    SIGNAL = "signal"
    ORDER_UPDATE = "order_update"
    POSITION_UPDATE = "position_update"
    INDICATOR_UPDATE = "indicator_update"
    SYSTEM_STATUS = "system_status"
    ERROR = "error"
    SUBSCRIPTIONS = "subscriptions"


class SubscriptionTopic(str, Enum):
    """Available subscription topics."""

    CANDLES = "candles"  # Real-time candle updates
    SIGNALS = "signals"  # Trading signals
    ORDERS = "orders"  # Order updates
    POSITIONS = "positions"  # Position updates
    INDICATORS = "indicators"  # Indicator updates
    SYSTEM = "system"  # System status updates
    ALL = "all"  # All topics


class WebSocketMessage(BaseModel):
    """Base WebSocket message structure."""

    type: MessageType = Field(..., description="Message type")
    timestamp: datetime = Field(default_factory=datetime.now)
    data: Dict[str, Any] = Field(default_factory=dict)


class SubscribeMessage(BaseModel):
    """Subscribe request message."""

    type: MessageType = Field(MessageType.SUBSCRIBE)
    topics: List[SubscriptionTopic] = Field(..., description="Topics to subscribe to")
    filters: Optional[Dict[str, Any]] = Field(None, description="Optional filters (e.g., specific symbols)")


class UnsubscribeMessage(BaseModel):
    """Unsubscribe request message."""

    type: MessageType = Field(MessageType.UNSUBSCRIBE)
    topics: List[SubscriptionTopic] = Field(..., description="Topics to unsubscribe from")


# ============================================================================
# Connection Management
# ============================================================================

class WebSocketConnection:
    """
    Represents a single WebSocket client connection with subscription management.
    """

    def __init__(self, websocket: WebSocket, connection_id: str):
        """
        Initialize WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance
            connection_id: Unique connection identifier
        """
        self.websocket = websocket
        self.connection_id = connection_id
        self.subscriptions: Set[SubscriptionTopic] = set()
        self.filters: Dict[str, Any] = {}
        self.connected_at = datetime.now()
        self.last_ping = datetime.now()
        self.last_pong = datetime.now()
        self.message_count = 0

    async def send_message(self, message: WebSocketMessage) -> bool:
        """
        Send a message to the client.

        Args:
            message: Message to send

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            await self.websocket.send_json(message.model_dump())
            self.message_count += 1
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {self.connection_id}: {e}")
            return False

    async def send_error(self, error: str, detail: Optional[str] = None) -> None:
        """
        Send an error message to the client.

        Args:
            error: Error message
            detail: Optional error details
        """
        message = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": error, "detail": detail}
        )
        await self.send_message(message)

    def is_subscribed(self, topic: SubscriptionTopic) -> bool:
        """
        Check if connection is subscribed to a topic.

        Args:
            topic: Topic to check

        Returns:
            True if subscribed
        """
        return topic in self.subscriptions or SubscriptionTopic.ALL in self.subscriptions

    def matches_filters(self, data: Dict[str, Any]) -> bool:
        """
        Check if data matches connection's filters.

        Args:
            data: Data to check against filters

        Returns:
            True if data matches all filters or no filters set
        """
        if not self.filters:
            return True

        for key, value in self.filters.items():
            if key not in data or data[key] != value:
                return False

        return True

    def get_info(self) -> Dict[str, Any]:
        """
        Get connection information.

        Returns:
            Dictionary with connection details
        """
        return {
            "connection_id": self.connection_id,
            "subscriptions": [topic.value for topic in self.subscriptions],
            "filters": self.filters,
            "connected_at": self.connected_at.isoformat(),
            "uptime_seconds": (datetime.now() - self.connected_at).total_seconds(),
            "message_count": self.message_count,
            "last_ping": self.last_ping.isoformat(),
            "last_pong": self.last_pong.isoformat(),
        }


# ============================================================================
# WebSocket Manager
# ============================================================================

class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts events to subscribed clients.
    """

    def __init__(self, event_bus: EventBus, heartbeat_interval: float = 30.0):
        """
        Initialize WebSocket manager.

        Args:
            event_bus: Event bus for receiving system events
            heartbeat_interval: Interval for heartbeat checks in seconds
        """
        self.event_bus = event_bus
        self.heartbeat_interval = heartbeat_interval
        self.connections: Dict[str, WebSocketConnection] = {}
        self.event_handler: Optional[WebSocketEventHandler] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self.logger = logger

        # Statistics
        self.stats = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_sent": 0,
            "messages_failed": 0,
        }

    async def start(self) -> None:
        """Start the WebSocket manager and event handler."""
        if self._running:
            return

        self._running = True

        # Register event handler with event bus
        self.event_handler = WebSocketEventHandler(self)
        self.event_bus.subscribe_all(self.event_handler)

        # Start heartbeat task
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        self.logger.info("WebSocket manager started")

    async def stop(self) -> None:
        """Stop the WebSocket manager and disconnect all clients."""
        if not self._running:
            return

        self._running = False

        # Stop heartbeat
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

        # Disconnect all clients
        for connection in list(self.connections.values()):
            try:
                await connection.websocket.close()
            except Exception as e:
                self.logger.error(f"Error closing connection {connection.connection_id}: {e}")

        self.connections.clear()

        # Unregister event handler
        if self.event_handler:
            self.event_bus.unsubscribe_all(self.event_handler)

        self.logger.info("WebSocket manager stopped")

    async def connect(self, websocket: WebSocket) -> str:
        """
        Accept a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance

        Returns:
            Connection ID
        """
        connection_id = str(uuid4())
        await websocket.accept()

        connection = WebSocketConnection(websocket, connection_id)
        self.connections[connection_id] = connection

        self.stats["total_connections"] += 1
        self.stats["active_connections"] = len(self.connections)

        self.logger.info(f"WebSocket connected: {connection_id}")

        # Send welcome message
        await connection.send_message(WebSocketMessage(
            type=MessageType.SYSTEM_STATUS,
            data={
                "status": "connected",
                "connection_id": connection_id,
                "server_time": datetime.now().isoformat(),
            }
        ))

        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        """
        Disconnect a WebSocket client.

        Args:
            connection_id: Connection identifier
        """
        if connection_id in self.connections:
            del self.connections[connection_id]
            self.stats["active_connections"] = len(self.connections)
            self.logger.info(f"WebSocket disconnected: {connection_id}")

    async def handle_message(self, connection_id: str, message: str) -> None:
        """
        Handle incoming message from client.

        Args:
            connection_id: Connection identifier
            message: Raw message string
        """
        connection = self.connections.get(connection_id)
        if not connection:
            return

        try:
            data = json.loads(message)
            message_type = data.get("type")

            if message_type == MessageType.SUBSCRIBE.value:
                await self._handle_subscribe(connection, data)
            elif message_type == MessageType.UNSUBSCRIBE.value:
                await self._handle_unsubscribe(connection, data)
            elif message_type == MessageType.PING.value:
                await self._handle_ping(connection)
            elif message_type == MessageType.GET_SUBSCRIPTIONS.value:
                await self._handle_get_subscriptions(connection)
            else:
                await connection.send_error(f"Unknown message type: {message_type}")

        except json.JSONDecodeError as e:
            await connection.send_error("Invalid JSON", str(e))
        except Exception as e:
            self.logger.error(f"Error handling message from {connection_id}: {e}", exc_info=True)
            await connection.send_error("Internal error", str(e))

    async def _handle_subscribe(self, connection: WebSocketConnection, data: Dict[str, Any]) -> None:
        """Handle subscribe request."""
        try:
            topics = [SubscriptionTopic(topic) for topic in data.get("topics", [])]
            filters = data.get("filters", {})

            connection.subscriptions.update(topics)
            connection.filters.update(filters)

            await connection.send_message(WebSocketMessage(
                type=MessageType.SUBSCRIPTIONS,
                data={
                    "subscribed": [topic.value for topic in topics],
                    "all_subscriptions": [topic.value for topic in connection.subscriptions],
                    "filters": connection.filters,
                }
            ))

            self.logger.debug(f"Connection {connection.connection_id} subscribed to {topics}")

        except ValueError as e:
            await connection.send_error("Invalid topic", str(e))

    async def _handle_unsubscribe(self, connection: WebSocketConnection, data: Dict[str, Any]) -> None:
        """Handle unsubscribe request."""
        try:
            topics = [SubscriptionTopic(topic) for topic in data.get("topics", [])]

            for topic in topics:
                connection.subscriptions.discard(topic)

            await connection.send_message(WebSocketMessage(
                type=MessageType.SUBSCRIPTIONS,
                data={
                    "unsubscribed": [topic.value for topic in topics],
                    "all_subscriptions": [topic.value for topic in connection.subscriptions],
                }
            ))

            self.logger.debug(f"Connection {connection.connection_id} unsubscribed from {topics}")

        except ValueError as e:
            await connection.send_error("Invalid topic", str(e))

    async def _handle_ping(self, connection: WebSocketConnection) -> None:
        """Handle ping request."""
        connection.last_ping = datetime.now()
        await connection.send_message(WebSocketMessage(
            type=MessageType.PONG,
            data={"server_time": datetime.now().isoformat()}
        ))

    async def _handle_get_subscriptions(self, connection: WebSocketConnection) -> None:
        """Handle get subscriptions request."""
        await connection.send_message(WebSocketMessage(
            type=MessageType.SUBSCRIPTIONS,
            data={
                "subscriptions": [topic.value for topic in connection.subscriptions],
                "filters": connection.filters,
            }
        ))

    async def broadcast(
        self,
        message_type: MessageType,
        data: Dict[str, Any],
        topic: SubscriptionTopic,
    ) -> int:
        """
        Broadcast a message to all subscribed clients.

        Args:
            message_type: Type of message to broadcast
            data: Message data
            topic: Topic for filtering subscribers

        Returns:
            Number of clients the message was sent to
        """
        message = WebSocketMessage(type=message_type, data=data)
        sent_count = 0

        for connection in list(self.connections.values()):
            if connection.is_subscribed(topic) and connection.matches_filters(data):
                success = await connection.send_message(message)
                if success:
                    sent_count += 1
                    self.stats["messages_sent"] += 1
                else:
                    self.stats["messages_failed"] += 1

        return sent_count

    async def _heartbeat_loop(self) -> None:
        """
        Heartbeat loop to monitor connection health.

        Periodically checks for stale connections and sends ping messages.
        """
        self.logger.info("Heartbeat loop started")

        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                # Check for stale connections (no pong response in 2x heartbeat interval)
                timeout_threshold = datetime.now().timestamp() - (self.heartbeat_interval * 2)

                for connection_id, connection in list(self.connections.items()):
                    if connection.last_pong.timestamp() < timeout_threshold:
                        self.logger.warning(f"Connection {connection_id} timed out, disconnecting")
                        try:
                            await connection.websocket.close()
                        except Exception:
                            pass
                        await self.disconnect(connection_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in heartbeat loop: {e}", exc_info=True)

        self.logger.info("Heartbeat loop stopped")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get WebSocket manager statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            **self.stats,
            "connections": [conn.get_info() for conn in self.connections.values()],
        }


# ============================================================================
# Event Handler for Broadcasting
# ============================================================================

class WebSocketEventHandler(EventHandler):
    """
    Event handler that broadcasts system events to WebSocket clients.
    """

    def __init__(self, ws_manager: WebSocketManager):
        """
        Initialize WebSocket event handler.

        Args:
            ws_manager: WebSocket manager instance
        """
        super().__init__(name="WebSocketEventHandler")
        self.ws_manager = ws_manager

        # Mapping of event types to (message_type, topic)
        self.event_mapping = {
            # Candle events → CANDLES topic
            EventType.CANDLE_RECEIVED: (MessageType.CANDLE_UPDATE, SubscriptionTopic.CANDLES),
            EventType.CANDLE_CLOSED: (MessageType.CANDLE_UPDATE, SubscriptionTopic.CANDLES),

            # Indicator events → INDICATORS topic
            EventType.FVG_DETECTED: (MessageType.INDICATOR_UPDATE, SubscriptionTopic.INDICATORS),
            EventType.ORDER_BLOCK_DETECTED: (MessageType.INDICATOR_UPDATE, SubscriptionTopic.INDICATORS),
            EventType.LIQUIDITY_SWEEP_DETECTED: (MessageType.INDICATOR_UPDATE, SubscriptionTopic.INDICATORS),
            EventType.MARKET_STRUCTURE_CHANGE: (MessageType.INDICATOR_UPDATE, SubscriptionTopic.INDICATORS),
            EventType.INDICATORS_UPDATED: (MessageType.INDICATOR_UPDATE, SubscriptionTopic.INDICATORS),

            # Signal events → SIGNALS topic
            EventType.SIGNAL_GENERATED: (MessageType.SIGNAL, SubscriptionTopic.SIGNALS),

            # Order events → ORDERS topic
            EventType.ORDER_PLACED: (MessageType.ORDER_UPDATE, SubscriptionTopic.ORDERS),
            EventType.ORDER_FILLED: (MessageType.ORDER_UPDATE, SubscriptionTopic.ORDERS),
            EventType.ORDER_CANCELLED: (MessageType.ORDER_UPDATE, SubscriptionTopic.ORDERS),
            EventType.ORDER_FAILED: (MessageType.ORDER_UPDATE, SubscriptionTopic.ORDERS),

            # Position events → POSITIONS topic
            EventType.POSITION_OPENED: (MessageType.POSITION_UPDATE, SubscriptionTopic.POSITIONS),
            EventType.POSITION_CLOSED: (MessageType.POSITION_UPDATE, SubscriptionTopic.POSITIONS),
            EventType.POSITION_UPDATED: (MessageType.POSITION_UPDATE, SubscriptionTopic.POSITIONS),
        }

    async def handle(self, event: Event) -> None:
        """
        Handle event by broadcasting to WebSocket clients.

        Args:
            event: Event to broadcast
        """
        # Check if we should broadcast this event type
        if event.event_type not in self.event_mapping:
            return

        message_type, topic = self.event_mapping[event.event_type]

        # Prepare broadcast data
        broadcast_data = {
            "event_type": event.event_type.value,
            "source": event.source,
            "timestamp": event.timestamp.isoformat(),
            **event.data,
        }

        # Broadcast to subscribed clients
        sent_count = await self.ws_manager.broadcast(
            message_type=message_type,
            data=broadcast_data,
            topic=topic,
        )

        if sent_count > 0:
            self.logger.debug(f"Broadcasted {event.event_type} to {sent_count} clients")
