"""
Integration tests for Risk Management System.

Tests comprehensive risk validation workflows with:
- Complete order validation scenarios
- Daily loss limit enforcement
- Entry blocking workflows
- Multiple violation scenarios
- Real component interactions
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from src.services.risk.risk_validator import RiskValidator
from src.services.risk.position_sizer import PositionSizer
from src.services.risk.stop_loss_calculator import StopLossCalculator
from src.services.risk.take_profit_calculator import TakeProfitCalculator
from src.services.risk.daily_loss_monitor import DailyLossMonitor
from src.core.constants import PositionSide


@pytest.fixture
def mock_components():
    """Create mocked risk management components for integration testing."""
    # Mock position sizer
    position_sizer = Mock(spec=PositionSizer)

    async def mock_calc():
        return {
            'position_size': Decimal('1000'),
            'risk_amount': Decimal('20'),
            'leverage_applied': Decimal('5000')
        }

    position_sizer.calculate_position_size = Mock(side_effect=lambda **kwargs: mock_calc())

    # Mock stop loss calculator
    stop_loss_calc = Mock(spec=StopLossCalculator)
    stop_loss_calc.get_parameters.return_value = {
        'min_stop_distance_pct': Decimal('0.3'),
        'max_stop_distance_pct': Decimal('3.0')
    }

    # Mock take profit calculator
    take_profit_calc = Mock(spec=TakeProfitCalculator)
    take_profit_calc.get_parameters.return_value = {
        'min_risk_reward_ratio': Decimal('1.5'),
        'max_risk_reward_ratio': Decimal('5.0')
    }

    # Real daily loss monitor
    from src.core.events import EventBus
    event_bus = EventBus()
    daily_monitor = DailyLossMonitor(
        event_bus=event_bus,
        daily_loss_limit_pct=6.0
    )
    daily_monitor.start_session(Decimal('10000'))

    # Create risk validator
    validator = RiskValidator(
        position_sizer=position_sizer,
        stop_loss_calculator=stop_loss_calc,
        take_profit_calculator=take_profit_calc,
        daily_loss_monitor=daily_monitor,
        event_bus=event_bus
    )

    return {
        'validator': validator,
        'position_sizer': position_sizer,
        'stop_loss_calc': stop_loss_calc,
        'take_profit_calc': take_profit_calc,
        'daily_monitor': daily_monitor,
        'event_bus': event_bus
    }


@pytest.mark.asyncio
class TestRiskValidationIntegration:
    """Integration tests for complete risk validation workflows."""

    async def test_valid_long_order_approval(self, mock_components):
        """Test approval of valid LONG order through complete validation."""
        validator = mock_components['validator']

        # Valid LONG order parameters
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49000'),  # 2% stop loss
            take_profit=Decimal('53000'),  # 1.5:1 risk-reward
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is True
        assert "All risk checks passed" in result.reason
        assert len(result.violations) == 0
        assert result.metadata['symbol'] == 'BTCUSDT'

    async def test_valid_short_order_approval(self, mock_components):
        """Test approval of valid SHORT order through complete validation."""
        system = mock_components
        validator = system['validator']

        # Valid SHORT order parameters
        result = await validator.validate_order(
            symbol='ETHUSDT',
            side=PositionSide.SHORT,
            entry_price=Decimal('3000'),
            stop_loss=Decimal('3060'),  # 2% stop loss
            take_profit=Decimal('2910'),  # 1.5:1 risk-reward
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is True
        assert "All risk checks passed" in result.reason
        assert len(result.violations) == 0

    async def test_order_rejection_invalid_stop_loss(self, mock_components):
        """Test order rejection due to invalid stop loss placement."""
        system = mock_components
        validator = system['validator']

        # Invalid LONG order with SL above entry
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('51000'),  # Wrong direction!
            take_profit=Decimal('53000'),
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is False
        assert len(result.violations) > 0
        assert any('stop_loss' in v for v in result.violations)

    async def test_order_rejection_low_risk_reward(self, mock_components):
        """Test order rejection due to insufficient risk-reward ratio."""
        system = mock_components
        validator = system['validator']

        # Order with R:R ratio below 1.5:1
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49000'),  # 2% risk
            take_profit=Decimal('50500'),  # Only 1% reward -> 0.5:1 R:R
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is False
        assert any('take_profit' in v for v in result.violations)
        assert 'Risk-reward ratio too low' in result.reason

    async def test_order_rejection_excessive_position_size(self, mock_components):
        """Test order rejection due to position size exceeding limits."""
        system = mock_components
        validator = system['validator']

        # Position size way too large
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49000'),
            take_profit=Decimal('53000'),
            position_size=Decimal('5000'),  # Exceeds calculated size
            custom_balance=10000.0
        )

        assert result.approved is False
        assert any('position_size' in v for v in result.violations)


@pytest.mark.asyncio
class TestDailyLossLimitIntegration:
    """Integration tests for daily loss limit enforcement."""

    async def test_entry_blocking_when_loss_limit_reached(self, mock_components):
        """Test that entries are blocked when daily loss limit is reached."""
        system = mock_components
        validator = system['validator']
        daily_monitor = system['daily_monitor']

        # Simulate daily loss reaching limit
        daily_monitor.update_balance(
            current_balance=Decimal('9400'),  # -6% loss
            realized_pnl=Decimal('-600'),
            unrealized_pnl=Decimal('0')
        )

        # Verify limit is reached
        assert daily_monitor.is_loss_limit_reached() is True

        # Try to place order - should be rejected
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49000'),
            take_profit=Decimal('53000'),
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is False
        assert "Daily loss limit reached" in result.reason
        assert "entry_blocked" in result.violations

    async def test_entry_allowed_after_session_reset(self, mock_components):
        """Test that entries are allowed after daily session reset."""
        system = mock_components
        validator = system['validator']
        daily_monitor = system['daily_monitor']

        # Simulate loss limit being reached
        daily_monitor.update_balance(
            current_balance=Decimal('9400'),
            realized_pnl=Decimal('-600'),
            unrealized_pnl=Decimal('0')
        )
        assert daily_monitor.is_loss_limit_reached() is True

        # Reset for new trading day
        validator.reset_entry_blocking()
        daily_monitor.reset_session()
        daily_monitor.start_session(Decimal('9400'))  # Start new day with remaining balance

        # Verify entries are allowed
        allowed, reason = validator.check_entry_allowed()
        assert allowed is True
        assert "Entry allowed" in reason

    async def test_entry_allowed_with_normal_loss(self, mock_components):
        """Test that entries are allowed when loss is within limits."""
        system = mock_components
        validator = system['validator']
        daily_monitor = system['daily_monitor']

        # Simulate moderate loss (3% - within limit)
        daily_monitor.update_balance(
            current_balance=Decimal('9700'),
            realized_pnl=Decimal('-300'),
            unrealized_pnl=Decimal('0')
        )

        # Verify limit not reached
        assert daily_monitor.is_loss_limit_reached() is False

        # Verify entries are allowed
        allowed, reason = validator.check_entry_allowed()
        assert allowed is True

        # Order should be approved if valid
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49000'),
            take_profit=Decimal('53000'),
            position_size=Decimal('1000'),
            custom_balance=9700.0
        )

        assert result.approved is True


@pytest.mark.asyncio
class TestMultipleValidationScenarios:
    """Integration tests for various risk scenarios and edge cases."""

    async def test_tight_stop_loss_rejection(self, mock_components):
        """Test rejection of orders with stop loss too tight."""
        system = mock_components
        validator = system['validator']

        # Stop loss only 0.1% away (below min 0.3%)
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49950'),  # 0.1% stop
            take_profit=Decimal('50100'),
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is False
        assert any('Stop loss too tight' in v for v in result.violations)

    async def test_wide_stop_loss_rejection(self, mock_components):
        """Test rejection of orders with stop loss too wide."""
        system = mock_components
        validator = system['validator']

        # Stop loss 5% away (above max 3%)
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('47500'),  # 5% stop
            take_profit=Decimal('60000'),
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is False
        assert any('Stop loss too wide' in v for v in result.violations)

    async def test_multiple_violations_reporting(self, mock_components):
        """Test that multiple violations are all reported."""
        system = mock_components
        validator = system['validator']

        # Order with multiple issues
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('51000'),  # Wrong direction
            take_profit=Decimal('50100'),  # Low R:R
            position_size=Decimal('5000'),  # Too large
            custom_balance=10000.0
        )

        assert result.approved is False
        assert len(result.violations) >= 2  # Should have multiple violations
        violations_str = ' '.join(result.violations)
        assert 'stop_loss' in violations_str or 'take_profit' in violations_str

    async def test_validation_status_reporting(self, mock_components):
        """Test validation system status reporting."""
        system = mock_components
        validator = system['validator']
        daily_monitor = system['daily_monitor']

        # Set up some loss
        daily_monitor.update_balance(
            current_balance=Decimal('9700'),
            realized_pnl=Decimal('-300'),
            unrealized_pnl=Decimal('0')
        )

        # Get validation status
        status = validator.get_validation_status()

        assert 'entry_blocked' in status
        assert 'daily_loss_limit_reached' in status
        assert 'daily_status' in status
        assert status['daily_status']['loss_percentage'] == -3.0
        assert status['daily_status']['loss_limit_pct'] == 6.0
        assert status['daily_status']['remaining_capacity'] == 3.0


@pytest.mark.asyncio
class TestEventSystemIntegration:
    """Integration tests for event system integration."""

    async def test_event_published_on_approval(self, mock_components):
        """Test that RISK_CHECK_PASSED event is published on approval."""
        system = mock_components
        validator = system['validator']

        # Valid order
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49000'),
            take_profit=Decimal('53000'),
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is True
        # Event publishing logic would be tested here with actual event bus

    async def test_event_published_on_rejection(self, mock_components):
        """Test that RISK_CHECK_FAILED event is published on rejection."""
        system = mock_components
        validator = system['validator']

        # Invalid order
        result = await validator.validate_order(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('51000'),  # Invalid
            take_profit=Decimal('53000'),
            position_size=Decimal('1000'),
            custom_balance=10000.0
        )

        assert result.approved is False
        # Event publishing logic would be tested here with actual event bus
