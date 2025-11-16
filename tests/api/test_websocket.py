"""
Tests for WebSocket Manager and Real-time Communication.

Comprehensive tests for WebSocket functionality including connection management,
subscription system, message broadcasting, and heartbeat mechanism.
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocket

from src.api.websocket import (
    MessageType,
    SubscriptionTopic,
    WebSocketConnection,
    WebSocketManager,
    WebSocketMessage,
)
from src.core.constants import EventType
from src.core.events import Event, EventBus

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def event_bus():
    """Create and start an event bus instance for testing."""
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
async def ws_manager(event_bus):
    """Create and start a WebSocket manager for testing."""
    manager = WebSocketManager(event_bus=event_bus, heartbeat_interval=1.0)
    await manager.start()
    yield manager
    await manager.stop()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket for testing."""
    websocket = AsyncMock(spec=WebSocket)
    websocket.accept = AsyncMock()
    websocket.send_json = AsyncMock()
    websocket.receive_text = AsyncMock()
    websocket.close = AsyncMock()
    return websocket


# ============================================================================
# WebSocketConnection Tests
# ============================================================================


class TestWebSocketConnection:
    """Tests for WebSocketConnection class."""

    @pytest.mark.asyncio
    async def test_send_message(self, mock_websocket):
        """Test sending message to client."""
        connection = WebSocketConnection(mock_websocket, "test-id")

        message = WebSocketMessage(
            type=MessageType.CANDLE_UPDATE, data={"symbol": "BTCUSDT", "price": 50000}
        )

        result = await connection.send_message(message)

        assert result is True
        assert connection.message_count == 1
        mock_websocket.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_failure(self, mock_websocket):
        """Test handling of failed message send."""
        connection = WebSocketConnection(mock_websocket, "test-id")
        mock_websocket.send_json.side_effect = Exception("Connection lost")

        message = WebSocketMessage(type=MessageType.PONG, data={})
        result = await connection.send_message(message)

        assert result is False
        assert connection.message_count == 0

    @pytest.mark.asyncio
    async def test_send_error(self, mock_websocket):
        """Test sending error message."""
        connection = WebSocketConnection(mock_websocket, "test-id")

        await connection.send_error("Test error", "Error details")

        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == MessageType.ERROR.value
        assert call_args["data"]["error"] == "Test error"
        assert call_args["data"]["detail"] == "Error details"

    def test_is_subscribed(self, mock_websocket):
        """Test subscription checking."""
        connection = WebSocketConnection(mock_websocket, "test-id")

        # Not subscribed initially
        assert not connection.is_subscribed(SubscriptionTopic.CANDLES)

        # Subscribe to specific topic
        connection.subscriptions.add(SubscriptionTopic.CANDLES)
        assert connection.is_subscribed(SubscriptionTopic.CANDLES)
        assert not connection.is_subscribed(SubscriptionTopic.SIGNALS)

        # Subscribe to all
        connection.subscriptions.add(SubscriptionTopic.ALL)
        assert connection.is_subscribed(SubscriptionTopic.SIGNALS)

    def test_matches_filters(self, mock_websocket):
        """Test filter matching."""
        connection = WebSocketConnection(mock_websocket, "test-id")

        # No filters - matches everything
        assert connection.matches_filters({"symbol": "BTCUSDT"})

        # With filters
        connection.filters = {"symbol": "BTCUSDT"}
        assert connection.matches_filters({"symbol": "BTCUSDT", "price": 50000})
        assert not connection.matches_filters({"symbol": "ETHUSDT"})
        assert not connection.matches_filters({"price": 50000})

    def test_get_info(self, mock_websocket):
        """Test getting connection information."""
        connection = WebSocketConnection(mock_websocket, "test-id")
        connection.subscriptions.add(SubscriptionTopic.CANDLES)
        connection.filters = {"symbol": "BTCUSDT"}
        connection.message_count = 10

        info = connection.get_info()

        assert info["connection_id"] == "test-id"
        assert SubscriptionTopic.CANDLES.value in info["subscriptions"]
        assert info["filters"] == {"symbol": "BTCUSDT"}
        assert info["message_count"] == 10
        assert "uptime_seconds" in info


# ============================================================================
# WebSocketManager Tests
# ============================================================================


class TestWebSocketManager:
    """Tests for WebSocketManager class."""

    @pytest.mark.asyncio
    async def test_start_stop(self, event_bus):
        """Test starting and stopping WebSocket manager."""
        manager = WebSocketManager(event_bus)

        assert not manager._running

        await manager.start()
        assert manager._running
        assert manager.event_handler is not None
        assert manager.heartbeat_task is not None

        await manager.stop()
        assert not manager._running
        assert len(manager.connections) == 0

    @pytest.mark.asyncio
    async def test_connect(self, ws_manager, mock_websocket):
        """Test WebSocket connection."""
        connection_id = await ws_manager.connect(mock_websocket)

        assert connection_id in ws_manager.connections
        assert ws_manager.stats["total_connections"] == 1
        assert ws_manager.stats["active_connections"] == 1
        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, ws_manager, mock_websocket):
        """Test WebSocket disconnection."""
        connection_id = await ws_manager.connect(mock_websocket)
        await ws_manager.disconnect(connection_id)

        assert connection_id not in ws_manager.connections
        assert ws_manager.stats["active_connections"] == 0

    @pytest.mark.asyncio
    async def test_handle_subscribe_message(self, ws_manager, mock_websocket):
        """Test handling subscribe message."""
        connection_id = await ws_manager.connect(mock_websocket)

        message = json.dumps(
            {
                "type": "subscribe",
                "topics": ["candles", "signals"],
                "filters": {"symbol": "BTCUSDT"},
            }
        )

        await ws_manager.handle_message(connection_id, message)

        connection = ws_manager.connections[connection_id]
        assert SubscriptionTopic.CANDLES in connection.subscriptions
        assert SubscriptionTopic.SIGNALS in connection.subscriptions
        assert connection.filters == {"symbol": "BTCUSDT"}

    @pytest.mark.asyncio
    async def test_handle_unsubscribe_message(self, ws_manager, mock_websocket):
        """Test handling unsubscribe message."""
        connection_id = await ws_manager.connect(mock_websocket)
        connection = ws_manager.connections[connection_id]
        connection.subscriptions.add(SubscriptionTopic.CANDLES)
        connection.subscriptions.add(SubscriptionTopic.SIGNALS)

        message = json.dumps({"type": "unsubscribe", "topics": ["candles"]})

        await ws_manager.handle_message(connection_id, message)

        assert SubscriptionTopic.CANDLES not in connection.subscriptions
        assert SubscriptionTopic.SIGNALS in connection.subscriptions

    @pytest.mark.asyncio
    async def test_handle_ping_message(self, ws_manager, mock_websocket):
        """Test handling ping message."""
        connection_id = await ws_manager.connect(mock_websocket)

        message = json.dumps({"type": "ping"})
        await ws_manager.handle_message(connection_id, message)

        # Should have sent pong response
        assert mock_websocket.send_json.call_count >= 2  # Welcome + pong

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self, ws_manager, mock_websocket):
        """Test handling invalid JSON message."""
        connection_id = await ws_manager.connect(mock_websocket)

        await ws_manager.handle_message(connection_id, "invalid json{")

        # Should send error message
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == MessageType.ERROR.value

    @pytest.mark.asyncio
    async def test_broadcast(self, ws_manager, mock_websocket):
        """Test broadcasting message to subscribers."""
        # Connect two clients
        mock_ws1 = AsyncMock(spec=WebSocket)
        mock_ws1.accept = AsyncMock()
        mock_ws1.send_json = AsyncMock()

        mock_ws2 = AsyncMock(spec=WebSocket)
        mock_ws2.accept = AsyncMock()
        mock_ws2.send_json = AsyncMock()

        conn_id1 = await ws_manager.connect(mock_ws1)
        conn_id2 = await ws_manager.connect(mock_ws2)

        # Subscribe conn1 to candles, conn2 to signals
        ws_manager.connections[conn_id1].subscriptions.add(SubscriptionTopic.CANDLES)
        ws_manager.connections[conn_id2].subscriptions.add(SubscriptionTopic.SIGNALS)

        # Broadcast candle update
        sent_count = await ws_manager.broadcast(
            message_type=MessageType.CANDLE_UPDATE,
            data={"symbol": "BTCUSDT", "price": 50000},
            topic=SubscriptionTopic.CANDLES,
        )

        # Only conn1 should receive it
        assert sent_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_with_filters(self, ws_manager):
        """Test broadcasting with filter matching."""
        # Create two connections with different filters
        mock_ws1 = AsyncMock(spec=WebSocket)
        mock_ws1.accept = AsyncMock()
        mock_ws1.send_json = AsyncMock()

        mock_ws2 = AsyncMock(spec=WebSocket)
        mock_ws2.accept = AsyncMock()
        mock_ws2.send_json = AsyncMock()

        conn_id1 = await ws_manager.connect(mock_ws1)
        conn_id2 = await ws_manager.connect(mock_ws2)

        # Both subscribe to candles but with different symbol filters
        ws_manager.connections[conn_id1].subscriptions.add(SubscriptionTopic.CANDLES)
        ws_manager.connections[conn_id1].filters = {"symbol": "BTCUSDT"}

        ws_manager.connections[conn_id2].subscriptions.add(SubscriptionTopic.CANDLES)
        ws_manager.connections[conn_id2].filters = {"symbol": "ETHUSDT"}

        # Broadcast BTC candle
        sent_count = await ws_manager.broadcast(
            message_type=MessageType.CANDLE_UPDATE,
            data={"symbol": "BTCUSDT", "price": 50000},
            topic=SubscriptionTopic.CANDLES,
        )

        # Only conn1 should receive it
        assert sent_count == 1

    @pytest.mark.asyncio
    async def test_heartbeat_timeout(self, event_bus):
        """Test heartbeat timeout disconnection."""
        # Use very short heartbeat interval for testing
        manager = WebSocketManager(event_bus, heartbeat_interval=0.1)
        await manager.start()

        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()
        mock_ws.close = AsyncMock()

        conn_id = await manager.connect(mock_ws)

        # Set last pong to old timestamp
        manager.connections[conn_id].last_pong = datetime.fromtimestamp(0)

        # Wait for heartbeat check
        await asyncio.sleep(0.3)

        # Connection should be removed
        assert conn_id not in manager.connections
        mock_ws.close.assert_called_once()

        await manager.stop()

    def test_get_stats(self, ws_manager):
        """Test getting WebSocket statistics."""
        stats = ws_manager.get_stats()

        assert "total_connections" in stats
        assert "active_connections" in stats
        assert "messages_sent" in stats
        assert "messages_failed" in stats
        assert "connections" in stats


# ============================================================================
# WebSocketEventHandler Tests
# ============================================================================


class TestWebSocketEventHandler:
    """Tests for WebSocketEventHandler class."""

    @pytest.mark.asyncio
    async def test_event_broadcasting(self, ws_manager):
        """Test event broadcasting to WebSocket clients."""
        # Create and subscribe a client
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()

        conn_id = await ws_manager.connect(mock_ws)
        ws_manager.connections[conn_id].subscriptions.add(SubscriptionTopic.CANDLES)

        # Publish candle event to event bus
        event = Event(
            priority=5,
            event_type=EventType.CANDLE_RECEIVED,
            data={"symbol": "BTCUSDT", "price": 50000},
            source="test",
        )

        await ws_manager.event_bus.publish(event)

        # Wait for event queue to be empty (processed)
        await ws_manager.event_bus.wait_empty(timeout=1.0)
        await asyncio.sleep(0.05)  # Small delay for async message sending

        # Client should have received the event
        assert mock_ws.send_json.call_count >= 2  # Welcome + candle update

    @pytest.mark.asyncio
    async def test_signal_event_broadcasting(self, ws_manager):
        """Test signal event broadcasting."""
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()

        conn_id = await ws_manager.connect(mock_ws)
        ws_manager.connections[conn_id].subscriptions.add(SubscriptionTopic.SIGNALS)

        # Publish signal event
        event = Event(
            priority=8,
            event_type=EventType.SIGNAL_GENERATED,
            data={"symbol": "BTCUSDT", "side": "BUY", "confidence": 0.85},
            source="strategy",
        )

        await ws_manager.event_bus.publish(event)

        # Wait for event queue to be empty (processed)
        await ws_manager.event_bus.wait_empty(timeout=1.0)
        await asyncio.sleep(0.05)  # Small delay for async message sending

        # Verify signal was broadcast
        assert mock_ws.send_json.call_count >= 2

    @pytest.mark.asyncio
    async def test_order_event_broadcasting(self, ws_manager):
        """Test order event broadcasting."""
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()

        conn_id = await ws_manager.connect(mock_ws)
        ws_manager.connections[conn_id].subscriptions.add(SubscriptionTopic.ORDERS)

        # Publish order event
        event = Event(
            priority=9,
            event_type=EventType.ORDER_FILLED,
            data={"order_id": "123456", "symbol": "BTCUSDT", "filled_qty": 0.1},
            source="exchange",
        )

        await ws_manager.event_bus.publish(event)

        # Wait for event queue to be empty (processed)
        await ws_manager.event_bus.wait_empty(timeout=1.0)
        await asyncio.sleep(0.05)  # Small delay for async message sending

        assert mock_ws.send_json.call_count >= 2

    @pytest.mark.asyncio
    async def test_unhandled_event_type(self, ws_manager):
        """Test that unhandled event types are not broadcast."""
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()

        conn_id = await ws_manager.connect(mock_ws)
        ws_manager.connections[conn_id].subscriptions.add(SubscriptionTopic.ALL)

        initial_call_count = mock_ws.send_json.call_count

        # Create an event type not in the mapping
        # (This would be a custom event type not meant for WebSocket)
        event = Event(
            priority=5,
            event_type=EventType.ORDERBOOK_UPDATE,  # Not in WebSocket mapping
            data={"test": "data"},
            source="test",
        )

        await ws_manager.event_bus.publish(event)
        await asyncio.sleep(0.1)

        # No additional messages should be sent
        assert mock_ws.send_json.call_count == initial_call_count


# ============================================================================
# Integration Tests
# ============================================================================


class TestWebSocketIntegration:
    """Integration tests for complete WebSocket system."""

    @pytest.mark.asyncio
    async def test_full_connection_lifecycle(self, ws_manager):
        """Test complete connection lifecycle."""
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()
        mock_ws.close = AsyncMock()

        # Connect
        conn_id = await ws_manager.connect(mock_ws)
        assert conn_id in ws_manager.connections

        # Subscribe
        subscribe_msg = json.dumps(
            {
                "type": "subscribe",
                "topics": ["candles", "signals"],
                "filters": {"symbol": "BTCUSDT"},
            }
        )
        await ws_manager.handle_message(conn_id, subscribe_msg)

        # Ping
        ping_msg = json.dumps({"type": "ping"})
        await ws_manager.handle_message(conn_id, ping_msg)

        # Publish events
        await ws_manager.event_bus.publish(
            Event(
                priority=5,
                event_type=EventType.CANDLE_RECEIVED,
                data={"symbol": "BTCUSDT", "price": 50000},
                source="test",
            )
        )

        await asyncio.sleep(0.1)

        # Unsubscribe
        unsubscribe_msg = json.dumps({"type": "unsubscribe", "topics": ["candles"]})
        await ws_manager.handle_message(conn_id, unsubscribe_msg)

        # Disconnect
        await ws_manager.disconnect(conn_id)
        assert conn_id not in ws_manager.connections

    @pytest.mark.asyncio
    async def test_multiple_clients_with_different_subscriptions(self, ws_manager):
        """Test multiple clients with different subscriptions."""
        # Create three clients
        clients = []
        for i in range(3):
            mock_ws = AsyncMock(spec=WebSocket)
            mock_ws.accept = AsyncMock()
            mock_ws.send_json = AsyncMock()
            conn_id = await ws_manager.connect(mock_ws)
            clients.append((conn_id, mock_ws))

        # Subscribe to different topics
        ws_manager.connections[clients[0][0]].subscriptions.add(SubscriptionTopic.CANDLES)
        ws_manager.connections[clients[1][0]].subscriptions.add(SubscriptionTopic.SIGNALS)
        ws_manager.connections[clients[2][0]].subscriptions.add(SubscriptionTopic.ALL)

        # Broadcast to each topic
        await ws_manager.broadcast(
            MessageType.CANDLE_UPDATE, {"symbol": "BTCUSDT"}, SubscriptionTopic.CANDLES
        )

        await ws_manager.broadcast(MessageType.SIGNAL, {"side": "BUY"}, SubscriptionTopic.SIGNALS)

        # Client 0 should get candle only
        # Client 1 should get signal only
        # Client 2 should get both (subscribed to ALL)
        # Note: Each also got welcome message on connect
        assert clients[0][1].send_json.call_count >= 2  # welcome + candle
        assert clients[1][1].send_json.call_count >= 2  # welcome + signal
        assert clients[2][1].send_json.call_count >= 3  # welcome + candle + signal
