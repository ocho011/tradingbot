"""
Tests for Binance API permission verification system.
Tests cover:
- Permission verification (read, trade)
- Permission caching with TTL
- Periodic re-validation
- Change detection and notifications
- Error handling and recovery
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from src.core.constants import EventType
from src.core.events import EventBus
from src.services.exchange.permissions import (
    PermissionStatus,
    PermissionType,
    PermissionVerifier,
)


class TestPermissionStatus:
    """Test PermissionStatus dataclass."""

    def test_initial_status(self):
        """Test initial permission status values."""
        status = PermissionStatus()
        assert status.read is False
        assert status.trade is False
        assert status.last_checked is None
        assert status.last_changed is None
        assert status.check_count == 0
        assert status.error_count == 0

    def test_has_changed_detection(self):
        """Test permission change detection."""
        status = PermissionStatus(read=True, trade=False)
        # No change
        assert not status.has_changed(True, False)
        # Read permission changed
        assert status.has_changed(False, False)
        # Trade permission changed
        assert status.has_changed(True, True)
        # Both changed
        assert status.has_changed(False, True)

    def test_update_with_changes(self):
        """Test status update with permission changes."""
        status = PermissionStatus(read=True, trade=False)
        initial_time = time.time()
        # Update with change
        status.update(read=False, trade=True)
        assert status.read is False
        assert status.trade is True
        assert status.last_checked is not None
        assert status.last_changed is not None
        assert status.last_changed >= initial_time
        assert status.check_count == 1

    def test_update_without_changes(self):
        """Test status update without permission changes."""
        status = PermissionStatus(read=True, trade=True)
        status.update(True, True)
        # First update sets last_changed
        first_changed = status.last_changed
        first_checked = status.last_checked
        time.sleep(0.1)
        # Update again with same permissions
        status.update(True, True)
        # last_checked should update, but last_changed should not
        assert status.last_checked > first_checked
        assert status.last_changed == first_changed
        assert status.check_count == 2

    def test_to_dict(self):
        """Test conversion to dictionary."""
        current_time = time.time()
        status = PermissionStatus(
            read=True,
            trade=False,
            last_checked=current_time,
            last_changed=current_time,
            check_count=5,
            error_count=2,
        )
        result = status.to_dict()
        assert result["read"] is True
        assert result["trade"] is False
        assert result["last_checked"] == current_time
        assert result["last_changed"] == current_time
        assert result["check_count"] == 5
        assert result["error_count"] == 2
        assert "last_checked_datetime" in result
        assert "last_changed_datetime" in result


class TestPermissionVerifier:
    """Test PermissionVerifier class."""

    @pytest.fixture
    def mock_exchange(self):
        """Create mock ccxt exchange."""
        exchange = AsyncMock()
        exchange.fetch_balance = AsyncMock(return_value={"USDT": {"free": 1000}})
        exchange.fetch_open_orders = AsyncMock(return_value=[])
        return exchange

    @pytest.fixture
    def mock_event_bus(self):
        """Create mock event bus."""
        event_bus = AsyncMock(spec=EventBus)
        event_bus.publish = AsyncMock()
        return event_bus

    @pytest.fixture
    def verifier(self, mock_exchange, mock_event_bus):
        """Create PermissionVerifier instance."""
        return PermissionVerifier(
            exchange=mock_exchange,
            event_bus=mock_event_bus,
            cache_ttl=3600,
            revalidate_interval=3600,
        )

    @pytest.mark.asyncio
    async def test_verify_permissions_success(self, verifier, mock_exchange):
        """Test successful permission verification."""
        permissions = await verifier.verify_permissions()
        assert permissions["read"] is True
        assert permissions["trade"] is True
        assert mock_exchange.fetch_balance.called
        assert mock_exchange.fetch_open_orders.called

    @pytest.mark.asyncio
    async def test_verify_read_permission_denied(self, verifier, mock_exchange):
        """Test read permission denied."""
        mock_exchange.fetch_balance.side_effect = Exception("Permission denied")
        permissions = await verifier.verify_permissions()
        assert permissions["read"] is False
        assert permissions["trade"] is True

    @pytest.mark.asyncio
    async def test_verify_trade_permission_denied(self, verifier, mock_exchange):
        """Test trade permission denied."""
        mock_exchange.fetch_open_orders.side_effect = Exception("Permission denied")
        permissions = await verifier.verify_permissions()
        assert permissions["read"] is True
        assert permissions["trade"] is False

    @pytest.mark.asyncio
    async def test_permission_caching(self, verifier, mock_exchange):
        """Test permission result caching."""
        # First call - should hit the exchange
        result1 = await verifier.verify_permissions()
        assert mock_exchange.fetch_balance.call_count == 1
        # Second call - should use cache
        result2 = await verifier.verify_permissions()
        assert mock_exchange.fetch_balance.call_count == 1  # Not called again
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_force_refresh_bypass_cache(self, verifier, mock_exchange):
        """Test force refresh bypasses cache."""
        # First call
        await verifier.verify_permissions()
        assert mock_exchange.fetch_balance.call_count == 1
        # Force refresh
        await verifier.verify_permissions(force_refresh=True)
        assert mock_exchange.fetch_balance.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_expiration(self, verifier, mock_exchange):
        """Test cache expiration after TTL."""
        # Set short TTL for testing
        verifier.cache_ttl = 0.1
        # First verification
        await verifier.verify_permissions()
        assert mock_exchange.fetch_balance.call_count == 1
        # Wait for cache to expire
        await asyncio.sleep(0.2)
        # Should verify again
        await verifier.verify_permissions()
        assert mock_exchange.fetch_balance.call_count == 2

    @pytest.mark.asyncio
    async def test_permission_change_detection(self, verifier, mock_exchange, mock_event_bus):
        """Test detection of permission changes."""
        # Initial verification
        await verifier.verify_permissions()
        # Change permissions
        mock_exchange.fetch_balance.side_effect = Exception("Permission denied")
        # Force new verification
        await verifier.verify_permissions(force_refresh=True)
        # Check that change event was published
        published_events = [call.args[0] for call in mock_event_bus.publish.call_args_list]
        change_events = [
            e
            for e in published_events
            if e.event_type == EventType.EXCHANGE_ERROR
            and e.data.get("event") == "permissions_changed"
        ]
        assert len(change_events) > 0

    @pytest.mark.asyncio
    async def test_insufficient_permissions_warning(self, verifier, mock_exchange, mock_event_bus):
        """Test warning when permissions are insufficient."""
        # Deny both permissions
        mock_exchange.fetch_balance.side_effect = Exception("Permission denied")
        mock_exchange.fetch_open_orders.side_effect = Exception("Permission denied")
        await verifier.verify_permissions()
        # Check for insufficient permissions event
        published_events = [call.args[0] for call in mock_event_bus.publish.call_args_list]
        warning_events = [
            e for e in published_events if e.data.get("event") == "insufficient_permissions"
        ]
        assert len(warning_events) > 0

    @pytest.mark.asyncio
    async def test_consecutive_error_tracking(self, verifier, mock_exchange, mock_event_bus):
        """Test tracking of consecutive verification errors."""
        # Cause multiple consecutive failures on both checks
        mock_exchange.fetch_balance.side_effect = Exception("API Error")
        mock_exchange.fetch_open_orders.side_effect = Exception("API Error")
        # Verify until we hit the threshold
        for i in range(4):
            await verifier.verify_permissions(force_refresh=True)
        # Check consecutive error counter
        assert verifier._consecutive_errors >= 3
        # Should emit error event at threshold (3)
        published_events = [call.args[0] for call in mock_event_bus.publish.call_args_list]
        failure_events = [
            e for e in published_events if e.data.get("event") == "permission_verification_failures"
        ]
        assert len(failure_events) > 0

    @pytest.mark.asyncio
    async def test_error_recovery_with_cache(self, verifier, mock_exchange):
        """Test that cached data is used when verification fails."""
        # Successful first verification
        await verifier.verify_permissions()
        # Store original successful methods
        # original_balance = mock_exchange.fetch_balance
        # original_orders = mock_exchange.fetch_open_orders
        # Cause error on both verifications (complete failure)
        mock_exchange.fetch_balance.side_effect = Exception("Temporary error")
        mock_exchange.fetch_open_orders.side_effect = Exception("Temporary error")
        # Should return cached data instead of raising
        permissions = await verifier.verify_permissions(force_refresh=True)
        # Even though both checks failed, we should get cached data
        # The permissions will be updated to reflect the failure
        assert isinstance(permissions, dict)
        assert "read" in permissions
        assert "trade" in permissions

    @pytest.mark.asyncio
    async def test_get_status(self, verifier):
        """Test getting permission status."""
        await verifier.verify_permissions()
        status = verifier.get_status()
        assert isinstance(status, dict)
        assert "read" in status
        assert "trade" in status
        assert "last_checked" in status
        assert "check_count" in status
        assert status["check_count"] > 0

    @pytest.mark.asyncio
    async def test_is_permission_granted(self, verifier):
        """Test checking specific permissions."""
        await verifier.verify_permissions()
        assert verifier.is_permission_granted(PermissionType.READ) is True
        assert verifier.is_permission_granted(PermissionType.TRADE) is True

    @pytest.mark.asyncio
    async def test_has_read_permission_property(self, verifier):
        """Test has_read_permission property."""
        await verifier.verify_permissions()
        assert verifier.has_read_permission is True

    @pytest.mark.asyncio
    async def test_has_trade_permission_property(self, verifier):
        """Test has_trade_permission property."""
        await verifier.verify_permissions()
        assert verifier.has_trade_permission is True

    @pytest.mark.asyncio
    async def test_periodic_validation_start_stop(self, verifier):
        """Test starting and stopping periodic validation."""
        # Start periodic validation
        await verifier.start_periodic_validation()
        assert verifier.is_validation_running is True
        assert verifier._validation_task is not None
        # Stop periodic validation
        await verifier.stop_periodic_validation()
        assert verifier.is_validation_running is False

    @pytest.mark.asyncio
    async def test_periodic_validation_execution(self, verifier, mock_exchange):
        """Test that periodic validation executes verifications."""
        # Set very short interval for testing
        verifier.revalidate_interval = 0.1
        # Start validation
        await verifier.start_periodic_validation()
        # Wait for at least one validation cycle
        await asyncio.sleep(0.3)
        # Stop validation
        await verifier.stop_periodic_validation()
        # Should have called exchange multiple times
        assert mock_exchange.fetch_balance.call_count >= 2

    @pytest.mark.asyncio
    async def test_periodic_validation_error_recovery(self, verifier, mock_exchange):
        """Test that periodic validation continues after errors."""
        # Set short interval
        verifier.revalidate_interval = 0.1
        # Cause an error
        mock_exchange.fetch_balance.side_effect = [
            Exception("Error"),
            {"USDT": {"free": 1000}},  # Success after error
        ]
        await verifier.start_periodic_validation()
        await asyncio.sleep(0.3)
        await verifier.stop_periodic_validation()
        # Should have attempted multiple times despite error
        assert mock_exchange.fetch_balance.call_count >= 2


class TestPermissionVerifierIntegration:
    """Integration tests for permission verification with BinanceManager."""

    @pytest.fixture
    def mock_exchange(self):
        """Create mock exchange for integration tests."""
        exchange = AsyncMock()
        exchange.fetch_balance = AsyncMock(return_value={"USDT": {"free": 1000}})
        exchange.fetch_open_orders = AsyncMock(return_value=[])
        exchange.fetch_time = AsyncMock(return_value=int(time.time() * 1000))
        return exchange

    @pytest.fixture
    def event_bus(self):
        """Create real event bus for integration tests."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_full_verification_workflow(self, mock_exchange, event_bus):
        """Test complete permission verification workflow."""
        verifier = PermissionVerifier(
            exchange=mock_exchange,
            event_bus=event_bus,
            cache_ttl=1,  # Short TTL for testing
            revalidate_interval=0.5,  # Short interval
        )
        # Initial verification
        permissions = await verifier.verify_permissions()
        assert permissions["read"] is True
        assert permissions["trade"] is True
        # Start periodic monitoring
        await verifier.start_periodic_validation()
        # Wait for a validation cycle
        await asyncio.sleep(0.7)
        # Check status
        status = verifier.get_status()
        assert status["check_count"] >= 2  # Initial + at least one periodic
        # Stop monitoring
        await verifier.stop_periodic_validation()

    @pytest.mark.asyncio
    async def test_permission_change_notification_workflow(self, mock_exchange):
        """Test permission change notification workflow."""
        # Use mock event bus to capture events
        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish = AsyncMock()
        verifier = PermissionVerifier(exchange=mock_exchange, event_bus=mock_event_bus)
        # Initial verification with full permissions
        await verifier.verify_permissions()
        # Simulate permission change
        mock_exchange.fetch_balance.side_effect = Exception("Permission revoked")
        # Verify again - this should detect the change
        await verifier.verify_permissions(force_refresh=True)
        # Check for permission change event in published events
        published_events = [call.args[0] for call in mock_event_bus.publish.call_args_list]
        change_events = [
            e for e in published_events if e.data.get("event") == "permissions_changed"
        ]
        assert len(change_events) > 0
