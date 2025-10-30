"""
Tests for the OrderTracker system.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

from src.services.exchange.order_tracker import (
    OrderTracker,
    OrderTrackingStatus,
    TrackedOrder,
)
from src.core.events import EventBus, Event
from src.core.constants import EventType


@pytest.fixture
def event_bus():
    """Create a mock event bus."""
    bus = Mock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def order_tracker(event_bus):
    """Create OrderTracker instance with event bus."""
    return OrderTracker(event_bus=event_bus, max_history_size=100)


@pytest.fixture
def sample_order_data():
    """Sample order data for testing."""
    return {
        "order_id": "12345",
        "symbol": "BTCUSDT",
        "order_type": "MARKET",
        "side": "BUY",
        "quantity": 0.001,
        "price": None,
        "stop_price": None,
        "client_order_id": "client_123"
    }


class TestTrackedOrder:
    """Tests for TrackedOrder class."""

    def test_tracked_order_creation(self):
        """Test TrackedOrder initialization."""
        order = TrackedOrder(
            order_id="12345",
            client_order_id="client_123",
            symbol="BTCUSDT",
            order_type="MARKET",
            side="BUY",
            quantity=0.001,
            price=None,
            stop_price=None
        )

        assert order.order_id == "12345"
        assert order.client_order_id == "client_123"
        assert order.symbol == "BTCUSDT"
        assert order.status == OrderTrackingStatus.PENDING
        assert order.filled_quantity == 0.0
        assert len(order.status_history) == 0

    def test_update_status(self):
        """Test status update and history tracking."""
        order = TrackedOrder(
            order_id="12345",
            client_order_id=None,
            symbol="BTCUSDT",
            order_type="LIMIT",
            side="BUY",
            quantity=0.001,
            price=50000.0,
            stop_price=None
        )

        # Update to PLACED
        order.update_status(OrderTrackingStatus.PLACED)
        assert order.status == OrderTrackingStatus.PLACED
        assert len(order.status_history) == 1
        assert order.status_history[0]["new_status"] == "PLACED"

        # Update to FILLED
        order.update_status(
            OrderTrackingStatus.FILLED,
            filled_qty=0.001,
            avg_price=50100.0
        )
        assert order.status == OrderTrackingStatus.FILLED
        assert order.filled_quantity == 0.001
        assert order.average_price == 50100.0
        assert len(order.status_history) == 2

    def test_is_final_state(self):
        """Test final state detection."""
        order = TrackedOrder(
            order_id="12345",
            client_order_id=None,
            symbol="BTCUSDT",
            order_type="MARKET",
            side="BUY",
            quantity=0.001,
            price=None,
            stop_price=None
        )

        # Non-final states
        assert not order.is_final_state()  # PENDING

        order.status = OrderTrackingStatus.PLACED
        assert not order.is_final_state()

        order.status = OrderTrackingStatus.PARTIALLY_FILLED
        assert not order.is_final_state()

        # Final states
        order.status = OrderTrackingStatus.FILLED
        assert order.is_final_state()

        order.status = OrderTrackingStatus.FAILED
        assert order.is_final_state()

        order.status = OrderTrackingStatus.CANCELLED
        assert order.is_final_state()

        order.status = OrderTrackingStatus.EXPIRED
        assert order.is_final_state()

    def test_to_dict(self):
        """Test dictionary conversion."""
        order = TrackedOrder(
            order_id="12345",
            client_order_id="client_123",
            symbol="BTCUSDT",
            order_type="LIMIT",
            side="SELL",
            quantity=0.002,
            price=55000.0,
            stop_price=None
        )

        order_dict = order.to_dict()

        assert order_dict["order_id"] == "12345"
        assert order_dict["client_order_id"] == "client_123"
        assert order_dict["symbol"] == "BTCUSDT"
        assert order_dict["order_type"] == "LIMIT"
        assert order_dict["side"] == "SELL"
        assert order_dict["quantity"] == 0.002
        assert order_dict["price"] == 55000.0
        assert order_dict["status"] == "PENDING"


class TestOrderTracker:
    """Tests for OrderTracker class."""

    @pytest.mark.asyncio
    async def test_initialization(self, event_bus):
        """Test OrderTracker initialization."""
        tracker = OrderTracker(event_bus=event_bus, max_history_size=50)

        assert tracker.event_bus == event_bus
        assert tracker.max_history_size == 50
        assert len(tracker._active_orders) == 0
        assert len(tracker._completed_orders) == 0
        assert tracker._stats["total_tracked"] == 0

    @pytest.mark.asyncio
    async def test_track_order(self, order_tracker, sample_order_data, event_bus):
        """Test tracking a new order."""
        tracked_order = await order_tracker.track_order(**sample_order_data)

        assert tracked_order.order_id == "12345"
        assert tracked_order.symbol == "BTCUSDT"
        assert tracked_order.status == OrderTrackingStatus.PENDING

        # Check order is in active orders
        assert "12345" in order_tracker._active_orders
        assert order_tracker._stats["total_tracked"] == 1
        assert order_tracker._stats["currently_active"] == 1

        # Check ORDER_PLACED event was published
        event_bus.publish.assert_called_once()
        published_event = event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.ORDER_PLACED
        assert published_event.data["order_id"] == "12345"

    @pytest.mark.asyncio
    async def test_track_duplicate_order(self, order_tracker, sample_order_data):
        """Test tracking the same order twice."""
        # Track order first time
        order1 = await order_tracker.track_order(**sample_order_data)

        # Track same order again
        order2 = await order_tracker.track_order(**sample_order_data)

        assert order1 is order2
        assert order_tracker._stats["total_tracked"] == 1

    @pytest.mark.asyncio
    async def test_update_order_status(self, order_tracker, sample_order_data, event_bus):
        """Test updating order status."""
        # Track order
        await order_tracker.track_order(**sample_order_data)

        # Update to PLACED
        updated_order = await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.PLACED
        )

        assert updated_order is not None
        assert updated_order.status == OrderTrackingStatus.PLACED

        # Update to FILLED
        updated_order = await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.FILLED,
            filled_quantity=0.001,
            average_price=50000.0
        )

        assert updated_order.status == OrderTrackingStatus.FILLED
        assert updated_order.filled_quantity == 0.001
        assert updated_order.average_price == 50000.0

        # Check ORDER_FILLED event was published
        calls = event_bus.publish.call_args_list
        assert any(
            call[0][0].event_type == EventType.ORDER_FILLED
            for call in calls
        )

    @pytest.mark.asyncio
    async def test_update_nonexistent_order(self, order_tracker):
        """Test updating an order that doesn't exist."""
        result = await order_tracker.update_order_status(
            order_id="nonexistent",
            new_status=OrderTrackingStatus.FILLED
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_finalize_order(self, order_tracker, sample_order_data):
        """Test order finalization when reaching final state."""
        # Track order
        await order_tracker.track_order(**sample_order_data)

        # Update to final state
        await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.FILLED,
            filled_quantity=0.001,
            average_price=50000.0
        )

        # Check order moved to history
        assert "12345" not in order_tracker._active_orders
        assert len(order_tracker._completed_orders) == 1
        assert order_tracker._stats["currently_active"] == 0
        assert order_tracker._stats["total_filled"] == 1

    @pytest.mark.asyncio
    async def test_cancelled_order_stats(self, order_tracker, sample_order_data):
        """Test cancelled order statistics."""
        await order_tracker.track_order(**sample_order_data)

        await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.CANCELLED
        )

        assert order_tracker._stats["total_cancelled"] == 1

    @pytest.mark.asyncio
    async def test_failed_order_stats(self, order_tracker, sample_order_data):
        """Test failed order statistics."""
        await order_tracker.track_order(**sample_order_data)

        await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.FAILED,
            error_message="Insufficient funds"
        )

        assert order_tracker._stats["total_failed"] == 1

    @pytest.mark.asyncio
    async def test_websocket_update(self, order_tracker, sample_order_data):
        """Test WebSocket order update."""
        # Track order
        await order_tracker.track_order(**sample_order_data)

        # Simulate WebSocket execution report
        ws_data = {
            "e": "executionReport",
            "i": "12345",  # order ID
            "c": "client_123",  # client order ID
            "X": "FILLED",  # order status
            "z": "0.001",  # cumulative filled quantity
            "Z": "50.0"  # cumulative quote asset transacted quantity
        }

        await order_tracker.update_from_websocket(ws_data)

        # Check order was updated
        order = order_tracker.get_order("12345")
        assert order is not None
        assert order.status == OrderTrackingStatus.FILLED
        assert order.filled_quantity == 0.001

    @pytest.mark.asyncio
    async def test_websocket_update_invalid_event(self, order_tracker):
        """Test WebSocket update with invalid event type."""
        ws_data = {
            "e": "someOtherEvent",
            "i": "12345"
        }

        # Should not raise exception
        await order_tracker.update_from_websocket(ws_data)

    @pytest.mark.asyncio
    async def test_websocket_update_missing_order_id(self, order_tracker):
        """Test WebSocket update with missing order ID."""
        ws_data = {
            "e": "executionReport",
            "X": "FILLED"
        }

        # Should not raise exception
        await order_tracker.update_from_websocket(ws_data)

    def test_get_order_active(self, order_tracker, sample_order_data):
        """Test getting an active order."""
        asyncio.run(order_tracker.track_order(**sample_order_data))

        order = order_tracker.get_order("12345")

        assert order is not None
        assert order.order_id == "12345"
        assert order.status == OrderTrackingStatus.PENDING

    def test_get_order_completed(self, order_tracker, sample_order_data):
        """Test getting a completed order."""
        asyncio.run(order_tracker.track_order(**sample_order_data))
        asyncio.run(order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.FILLED
        ))

        order = order_tracker.get_order("12345")

        assert order is not None
        assert order.order_id == "12345"
        assert order.status == OrderTrackingStatus.FILLED

    def test_get_order_not_found(self, order_tracker):
        """Test getting a non-existent order."""
        order = order_tracker.get_order("nonexistent")

        assert order is None

    def test_get_order_by_client_id(self, order_tracker, sample_order_data):
        """Test getting order by client ID."""
        asyncio.run(order_tracker.track_order(**sample_order_data))

        order = order_tracker.get_order_by_client_id("client_123")

        assert order is not None
        assert order.order_id == "12345"
        assert order.client_order_id == "client_123"

    def test_get_active_orders(self, order_tracker):
        """Test getting all active orders."""
        # Track multiple orders
        asyncio.run(order_tracker.track_order(
            order_id="1", symbol="BTCUSDT", order_type="MARKET",
            side="BUY", quantity=0.001
        ))
        asyncio.run(order_tracker.track_order(
            order_id="2", symbol="ETHUSDT", order_type="LIMIT",
            side="SELL", quantity=0.01, price=3000.0
        ))

        all_orders = order_tracker.get_active_orders()
        assert len(all_orders) == 2

        # Filter by symbol
        btc_orders = order_tracker.get_active_orders(symbol="BTCUSDT")
        assert len(btc_orders) == 1
        assert btc_orders[0].symbol == "BTCUSDT"

    def test_get_completed_orders(self, order_tracker):
        """Test getting completed orders."""
        # Track and complete multiple orders
        asyncio.run(order_tracker.track_order(
            order_id="1", symbol="BTCUSDT", order_type="MARKET",
            side="BUY", quantity=0.001
        ))
        asyncio.run(order_tracker.update_order_status(
            order_id="1", new_status=OrderTrackingStatus.FILLED
        ))

        asyncio.run(order_tracker.track_order(
            order_id="2", symbol="ETHUSDT", order_type="MARKET",
            side="BUY", quantity=0.01
        ))
        asyncio.run(order_tracker.update_order_status(
            order_id="2", new_status=OrderTrackingStatus.FILLED
        ))

        completed = order_tracker.get_completed_orders()
        assert len(completed) == 2

        # With limit
        limited = order_tracker.get_completed_orders(limit=1)
        assert len(limited) == 1

        # With symbol filter
        btc_completed = order_tracker.get_completed_orders(symbol="BTCUSDT")
        assert len(btc_completed) == 1

    def test_history_size_limit(self, order_tracker):
        """Test that history size is limited."""
        order_tracker.max_history_size = 3

        # Track and complete 5 orders
        for i in range(5):
            asyncio.run(order_tracker.track_order(
                order_id=str(i),
                symbol="BTCUSDT",
                order_type="MARKET",
                side="BUY",
                quantity=0.001
            ))
            asyncio.run(order_tracker.update_order_status(
                order_id=str(i),
                new_status=OrderTrackingStatus.FILLED
            ))

        # Only last 3 should be in history
        assert len(order_tracker._completed_orders) == 3
        assert order_tracker._completed_orders[0].order_id == "2"
        assert order_tracker._completed_orders[-1].order_id == "4"

    def test_get_stats(self, order_tracker):
        """Test getting tracker statistics."""
        # Track some orders
        asyncio.run(order_tracker.track_order(
            order_id="1", symbol="BTCUSDT", order_type="MARKET",
            side="BUY", quantity=0.001
        ))
        asyncio.run(order_tracker.update_order_status(
            order_id="1", new_status=OrderTrackingStatus.FILLED
        ))

        stats = order_tracker.get_stats()

        assert stats["total_tracked"] == 1
        assert stats["currently_active"] == 0
        assert stats["total_filled"] == 1
        assert stats["history_size"] == 1

    def test_clear_history(self, order_tracker):
        """Test clearing order history."""
        # Add some completed orders
        asyncio.run(order_tracker.track_order(
            order_id="1", symbol="BTCUSDT", order_type="MARKET",
            side="BUY", quantity=0.001
        ))
        asyncio.run(order_tracker.update_order_status(
            order_id="1", new_status=OrderTrackingStatus.FILLED
        ))

        assert len(order_tracker._completed_orders) == 1

        order_tracker.clear_history()

        assert len(order_tracker._completed_orders) == 0

    @pytest.mark.asyncio
    async def test_event_publishing_without_event_bus(self):
        """Test that tracker works without event bus."""
        tracker = OrderTracker(event_bus=None)

        # Should not raise exception
        await tracker.track_order(
            order_id="1",
            symbol="BTCUSDT",
            order_type="MARKET",
            side="BUY",
            quantity=0.001
        )

        await tracker.update_order_status(
            order_id="1",
            new_status=OrderTrackingStatus.FILLED
        )

    @pytest.mark.asyncio
    async def test_partially_filled_order(self, order_tracker, sample_order_data):
        """Test partially filled order handling."""
        await order_tracker.track_order(**sample_order_data)

        # Partial fill
        await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.PARTIALLY_FILLED,
            filled_quantity=0.0005,
            average_price=50000.0
        )

        order = order_tracker.get_order("12345")
        assert order.status == OrderTrackingStatus.PARTIALLY_FILLED
        assert order.filled_quantity == 0.0005
        # Should still be active (not final state)
        assert "12345" in order_tracker._active_orders

    @pytest.mark.asyncio
    async def test_multiple_status_transitions(self, order_tracker, sample_order_data, event_bus):
        """Test multiple status transitions and event publishing."""
        await order_tracker.track_order(**sample_order_data)

        # PENDING → PLACED
        await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.PLACED
        )

        # PLACED → PARTIALLY_FILLED
        await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.PARTIALLY_FILLED,
            filled_quantity=0.0005,
            average_price=50000.0
        )

        # PARTIALLY_FILLED → FILLED
        await order_tracker.update_order_status(
            order_id="12345",
            new_status=OrderTrackingStatus.FILLED,
            filled_quantity=0.001,
            average_price=50050.0
        )

        order = order_tracker.get_order("12345")
        assert len(order.status_history) == 3
        assert order.status == OrderTrackingStatus.FILLED

        # Check events were published
        assert event_bus.publish.call_count >= 2  # At least ORDER_PLACED and ORDER_FILLED
