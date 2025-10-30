"""
Unit tests for DailyLossMonitor.

Tests cover:
- Session initialization and starting balance tracking
- Real-time P&L calculation and loss percentage tracking
- 6% loss threshold detection and event emission
- Session reset logic with timezone awareness
- Thread-safe balance updates
- Edge cases and error handling
"""

import pytest
from decimal import Decimal
from datetime import time
from unittest.mock import Mock, AsyncMock, patch

from src.services.risk.daily_loss_monitor import (
    DailyLossMonitor,
    DailyLossLimitError
)
from src.core.constants import EventType


class TestDailyLossMonitorInitialization:
    """Test DailyLossMonitor initialization and validation."""

    def test_successful_initialization(self):
        """Test successful initialization with valid parameters."""
        event_bus = Mock()
        monitor = DailyLossMonitor(
            event_bus=event_bus,
            daily_loss_limit_pct=6.0,
            reset_time_utc=time(0, 0),
            precision=8
        )

        assert monitor.daily_loss_limit_pct == Decimal('6.0')
        assert monitor.reset_time_utc == time(0, 0)
        assert monitor.precision == 8
        assert monitor.current_session is None
        assert monitor.event_bus is event_bus

    def test_initialization_with_defaults(self):
        """Test initialization uses default values correctly."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        assert monitor.daily_loss_limit_pct == Decimal('6.0')
        assert monitor.reset_time_utc == time(0, 0)
        assert monitor.precision == 8

    def test_invalid_loss_limit(self):
        """Test initialization fails with non-positive loss limit."""
        event_bus = Mock()
        with pytest.raises(ValueError, match="daily_loss_limit_pct must be positive"):
            DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=0)

        with pytest.raises(ValueError, match="daily_loss_limit_pct must be positive"):
            DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=-5.0)


class TestSessionManagement:
    """Test session start, reset, and lifecycle management."""

    def test_start_session_success(self):
        """Test successful session start with valid balance."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        starting_balance = Decimal('10000.0')
        session = monitor.start_session(starting_balance)

        assert session is not None
        assert session.starting_balance == starting_balance
        assert session.current_balance == starting_balance
        assert session.realized_pnl == Decimal('0')
        assert session.unrealized_pnl == Decimal('0')
        assert session.total_pnl == Decimal('0')
        assert session.loss_percentage == Decimal('0')
        assert not session.limit_reached
        assert monitor.current_session == session

    def test_start_session_invalid_balance(self):
        """Test session start fails with invalid balance."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        with pytest.raises(ValueError, match="starting_balance must be positive"):
            monitor.start_session(Decimal('0'))

        with pytest.raises(ValueError, match="starting_balance must be positive"):
            monitor.start_session(Decimal('-1000'))

    def test_start_session_resets_limit_flag(self):
        """Test starting new session resets limit event flag."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        # Start first session and trigger limit
        monitor.start_session(Decimal('10000'))
        monitor._limit_event_emitted = True

        # Start new session - flag should reset
        monitor.start_session(Decimal('10000'))
        assert not monitor._limit_event_emitted

    def test_reset_session(self):
        """Test session reset clears current session."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        monitor.start_session(Decimal('10000'))
        assert monitor.current_session is not None

        monitor.reset_session()
        assert monitor.current_session is None
        assert not monitor._limit_event_emitted


class TestBalanceUpdateAndPnLCalculation:
    """Test balance updates and P&L calculations."""

    def test_update_balance_success(self):
        """Test successful balance update with P&L calculation."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        monitor.start_session(Decimal('10000'))

        # Update with loss
        current_balance = Decimal('9500')
        realized_pnl = Decimal('-400')
        unrealized_pnl = Decimal('-100')

        result = monitor.update_balance(current_balance, realized_pnl, unrealized_pnl)

        assert result['session'].current_balance == current_balance
        assert result['session'].realized_pnl == realized_pnl
        assert result['session'].unrealized_pnl == unrealized_pnl
        assert result['session'].total_pnl == Decimal('-500')
        assert result['session'].loss_percentage == Decimal('-5.0')
        assert not result['limit_reached']
        assert not result['event_emitted']

    def test_update_balance_with_profit(self):
        """Test balance update with positive P&L."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        monitor.start_session(Decimal('10000'))

        # Update with profit
        current_balance = Decimal('10500')
        realized_pnl = Decimal('400')
        unrealized_pnl = Decimal('100')

        result = monitor.update_balance(current_balance, realized_pnl, unrealized_pnl)

        assert result['session'].total_pnl == Decimal('500')
        assert result['session'].loss_percentage == Decimal('5.0')  # Positive percentage
        assert not result['limit_reached']

    def test_update_balance_no_active_session(self):
        """Test update fails when no active session."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        with pytest.raises(DailyLossLimitError, match="No active session"):
            monitor.update_balance(Decimal('9000'), Decimal('-1000'), Decimal('0'))


class TestLossLimitDetection:
    """Test loss limit threshold detection and event emission."""

    def test_loss_limit_exactly_at_threshold(self):
        """Test detection when loss exactly at 6% threshold."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=6.0)

        monitor.start_session(Decimal('10000'))

        # Exactly 6% loss
        current_balance = Decimal('9400')
        realized_pnl = Decimal('-600')
        unrealized_pnl = Decimal('0')

        with patch('asyncio.run') as mock_run, \
             patch('asyncio.get_event_loop') as mock_get_loop:
            mock_loop = Mock()
            mock_loop.is_running.return_value = False
            mock_get_loop.return_value = mock_loop

            result = monitor.update_balance(current_balance, realized_pnl, unrealized_pnl)

        assert result['limit_reached']
        assert result['event_emitted']
        assert result['session'].limit_reached
        assert monitor.is_loss_limit_reached()

    def test_loss_limit_exceeded(self):
        """Test detection when loss exceeds 6% threshold."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=6.0)

        monitor.start_session(Decimal('10000'))

        # 7% loss
        current_balance = Decimal('9300')
        realized_pnl = Decimal('-500')
        unrealized_pnl = Decimal('-200')

        with patch('asyncio.run'), \
             patch('asyncio.get_event_loop') as mock_get_loop:
            mock_loop = Mock()
            mock_loop.is_running.return_value = False
            mock_get_loop.return_value = mock_loop

            result = monitor.update_balance(current_balance, realized_pnl, unrealized_pnl)

        assert result['limit_reached']
        assert result['session'].loss_percentage == Decimal('-7.0')

    def test_loss_limit_event_emitted_once(self):
        """Test event is emitted only once when limit reached."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=6.0)

        monitor.start_session(Decimal('10000'))

        with patch('asyncio.run'), \
             patch('asyncio.get_event_loop') as mock_get_loop:
            mock_loop = Mock()
            mock_loop.is_running.return_value = False
            mock_get_loop.return_value = mock_loop

            # First update - crosses threshold
            result1 = monitor.update_balance(Decimal('9400'), Decimal('-600'), Decimal('0'))
            assert result1['event_emitted']

            # Second update - still over threshold
            result2 = monitor.update_balance(Decimal('9300'), Decimal('-700'), Decimal('0'))
            assert not result2['event_emitted']  # Should not emit again

    def test_loss_limit_not_reached(self):
        """Test no limit detection when loss below threshold."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=6.0)

        monitor.start_session(Decimal('10000'))

        # 5% loss - below threshold
        result = monitor.update_balance(Decimal('9500'), Decimal('-500'), Decimal('0'))

        assert not result['limit_reached']
        assert not result['event_emitted']
        assert not monitor.is_loss_limit_reached()


class TestEventEmission:
    """Test event creation and emission to EventBus."""

    def test_event_data_structure(self):
        """Test emitted event contains correct data structure."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=6.0)

        monitor.start_session(Decimal('10000'))

        with patch('asyncio.run') as mock_run, \
             patch('asyncio.get_event_loop') as mock_get_loop:
            mock_loop = Mock()
            mock_loop.is_running.return_value = False
            mock_get_loop.return_value = mock_loop

            # Trigger limit
            monitor.update_balance(Decimal('9400'), Decimal('-600'), Decimal('0'))

            # Verify asyncio.run was called
            assert mock_run.called
            call_args = mock_run.call_args
            # The first argument should be a coroutine from event_bus.publish()
            assert call_args is not None

    def test_event_priority(self):
        """Test emitted event has high priority (9) for risk management."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        monitor.start_session(Decimal('10000'))

        # We'll capture the event by mocking the Event class
        with patch('src.services.risk.daily_loss_monitor.Event') as mock_event_class, \
             patch('asyncio.run'):
            mock_event_instance = Mock()
            mock_event_class.return_value = mock_event_instance

            monitor.update_balance(Decimal('9400'), Decimal('-600'), Decimal('0'))

            # Verify Event was created with priority 9
            mock_event_class.assert_called_once()
            call_kwargs = mock_event_class.call_args.kwargs
            assert call_kwargs['priority'] == 9
            assert call_kwargs['event_type'] == EventType.RISK_LIMIT_EXCEEDED
            assert call_kwargs['source'] == 'DailyLossMonitor'


class TestSessionStatus:
    """Test current status retrieval and metrics."""

    def test_get_current_status_with_session(self):
        """Test status retrieval with active session."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=6.0)

        monitor.start_session(Decimal('10000'))
        monitor.update_balance(Decimal('9500'), Decimal('-500'), Decimal('0'))

        status = monitor.get_current_status()

        assert status is not None
        assert status['starting_balance'] == 10000.0
        assert status['current_balance'] == 9500.0
        assert status['realized_pnl'] == -500.0
        assert status['unrealized_pnl'] == 0.0
        assert status['total_pnl'] == -500.0
        assert status['loss_percentage'] == -5.0
        assert status['loss_limit'] == 6.0
        assert not status['limit_reached']
        assert status['distance_to_limit'] == 1.0  # 6 - 5 = 1% remaining

    def test_get_current_status_no_session(self):
        """Test status returns None when no active session."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        status = monitor.get_current_status()
        assert status is None

    def test_distance_to_limit_calculation(self):
        """Test distance to limit calculation in various scenarios."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=6.0)

        monitor.start_session(Decimal('10000'))

        # 2% loss - 4% remaining
        monitor.update_balance(Decimal('9800'), Decimal('-200'), Decimal('0'))
        status = monitor.get_current_status()
        assert status['distance_to_limit'] == 4.0

        # 5.5% loss - 0.5% remaining
        monitor.update_balance(Decimal('9450'), Decimal('-550'), Decimal('0'))
        status = monitor.get_current_status()
        assert abs(status['distance_to_limit'] - 0.5) < 0.01  # Allow small floating point error


class TestSessionReset:
    """Test session reset logic with timezone awareness."""

    @patch('src.services.risk.daily_loss_monitor.datetime')
    def test_should_reset_different_date(self, mock_datetime):
        """Test reset detection when on different date."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        # Set up current session with yesterday's date
        monitor.start_session(Decimal('10000'))
        monitor.current_session.date = '2025-01-01'

        # Mock current time to be next day after reset time
        mock_now = Mock()
        mock_now.strftime.return_value = '2025-01-02'
        mock_now.time.return_value = time(0, 1)  # 00:01 UTC
        mock_datetime.now.return_value = mock_now

        assert monitor.should_reset_session()

    @patch('src.services.risk.daily_loss_monitor.datetime')
    def test_should_not_reset_same_date(self, mock_datetime):
        """Test no reset when still on same date."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        monitor.start_session(Decimal('10000'))
        monitor.current_session.date = '2025-01-01'

        # Mock current time to be same day
        mock_now = Mock()
        mock_now.strftime.return_value = '2025-01-01'
        mock_now.time.return_value = time(12, 0)  # 12:00 UTC
        mock_datetime.now.return_value = mock_now

        assert not monitor.should_reset_session()

    def test_should_reset_no_session(self):
        """Test reset returns True when no session exists."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        assert monitor.should_reset_session()


class TestThreadSafety:
    """Test thread-safe balance updates."""

    def test_concurrent_balance_updates(self):
        """Test balance updates are thread-safe."""
        import threading

        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)
        monitor.start_session(Decimal('10000'))

        results = []
        errors = []

        def update_balance_thread(pnl_value):
            try:
                result = monitor.update_balance(
                    Decimal('9500'),
                    Decimal(str(pnl_value)),
                    Decimal('0')
                )
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Create multiple threads updating balance
        threads = []
        for i in range(10):
            thread = threading.Thread(target=update_balance_thread, args=(-50 * i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All updates should succeed without errors
        assert len(errors) == 0
        assert len(results) == 10


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_starting_balance_division(self):
        """Test handling of zero starting balance (should be prevented)."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        with pytest.raises(ValueError):
            monitor.start_session(Decimal('0'))

    def test_very_small_balance(self):
        """Test handling of very small balances."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        # Very small starting balance
        monitor.start_session(Decimal('0.00000001'))

        with patch('asyncio.run'):
            result = monitor.update_balance(
                Decimal('0.000000009'),
                Decimal('-0.000000001'),
                Decimal('0')
            )

        assert result['session'].loss_percentage == Decimal('-10.0')

    def test_very_large_balance(self):
        """Test handling of very large balances."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()
        monitor = DailyLossMonitor(event_bus=event_bus)

        # Very large starting balance
        large_balance = Decimal('1000000000.0')
        monitor.start_session(large_balance)

        loss = Decimal('60000000.0')  # 6% loss

        with patch('asyncio.run'):
            result = monitor.update_balance(
                large_balance - loss,
                -loss,
                Decimal('0')
            )

        assert result['limit_reached']

    def test_custom_loss_limit(self):
        """Test monitor with custom loss limit percentage."""
        event_bus = Mock()
        event_bus.publish = AsyncMock()

        # Set 3% loss limit
        monitor = DailyLossMonitor(event_bus=event_bus, daily_loss_limit_pct=3.0)
        monitor.start_session(Decimal('10000'))

        with patch('asyncio.run'):
            # 3% loss should trigger
            result = monitor.update_balance(Decimal('9700'), Decimal('-300'), Decimal('0'))
            assert result['limit_reached']

    def test_mixed_realized_unrealized_pnl(self):
        """Test with various combinations of realized and unrealized P&L."""
        event_bus = Mock()
        monitor = DailyLossMonitor(event_bus=event_bus)
        monitor.start_session(Decimal('10000'))

        # Realized profit, unrealized loss
        result = monitor.update_balance(
            Decimal('9900'),
            Decimal('200'),
            Decimal('-300')
        )
        assert result['session'].total_pnl == Decimal('-100')

        # Realized loss, unrealized profit
        result = monitor.update_balance(
            Decimal('10100'),
            Decimal('-300'),
            Decimal('400')
        )
        assert result['session'].total_pnl == Decimal('100')
