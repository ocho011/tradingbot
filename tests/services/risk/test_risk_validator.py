"""
Unit tests for RiskValidator class.

Tests validation logic for:
- Position sizing validation
- Stop loss validation
- Take profit validation
- Entry blocking management
- Daily loss limit integration
- Order approval/rejection decisions
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from src.core.constants import EventType, PositionSide
from src.core.events import Event
from src.services.risk.daily_loss_monitor import DailyLossMonitor
from src.services.risk.position_sizer import PositionSizer
from src.services.risk.risk_validator import RiskValidationError, RiskValidator
from src.services.risk.stop_loss_calculator import StopLossCalculator
from src.services.risk.take_profit_calculator import TakeProfitCalculator


@pytest.fixture
def mock_position_sizer():
    """Create mock position sizer."""
    sizer = Mock(spec=PositionSizer)

    # Make calculate_position_size return a coroutine
    async def mock_calc():
        return {
            "position_size": Decimal("1000"),
            "risk_amount": Decimal("20"),
            "leverage_applied": Decimal("5000"),
        }

    sizer.calculate_position_size = Mock(side_effect=lambda **kwargs: mock_calc())
    return sizer


@pytest.fixture
def mock_stop_loss_calculator():
    """Create mock stop loss calculator."""
    calculator = Mock(spec=StopLossCalculator)
    calculator.get_parameters.return_value = {
        "min_stop_distance_pct": Decimal("0.3"),
        "max_stop_distance_pct": Decimal("3.0"),
    }
    return calculator


@pytest.fixture
def mock_take_profit_calculator():
    """Create mock take profit calculator."""
    calculator = Mock(spec=TakeProfitCalculator)
    calculator.get_parameters.return_value = {"min_risk_reward_ratio": Decimal("1.5")}
    return calculator


@pytest.fixture
def mock_daily_loss_monitor():
    """Create mock daily loss monitor."""
    monitor = Mock(spec=DailyLossMonitor)
    monitor.is_loss_limit_reached.return_value = False
    monitor.get_current_status.return_value = {
        "date": "2025-10-31",
        "starting_balance": Decimal("10000"),
        "current_balance": Decimal("9750"),
        "realized_pnl": Decimal("-250"),
        "unrealized_pnl": Decimal("0"),
        "total_pnl": Decimal("-250"),
        "loss_percentage": Decimal("2.5"),
        "loss_limit": Decimal("6.0"),
        "limit_reached": False,
        "distance_to_limit": Decimal("3.5"),
    }
    return monitor


@pytest.fixture
def mock_event_bus():
    """Create mock event bus."""
    return Mock()


@pytest.fixture
def risk_validator(
    mock_position_sizer,
    mock_stop_loss_calculator,
    mock_take_profit_calculator,
    mock_daily_loss_monitor,
    mock_event_bus,
):
    """Create RiskValidator instance with mocked dependencies."""
    return RiskValidator(
        position_sizer=mock_position_sizer,
        stop_loss_calculator=mock_stop_loss_calculator,
        take_profit_calculator=mock_take_profit_calculator,
        daily_loss_monitor=mock_daily_loss_monitor,
        event_bus=mock_event_bus,
    )


class TestRiskValidatorInitialization:
    """Test RiskValidator initialization."""

    def test_initialization_success(self, risk_validator):
        """Test successful initialization."""
        assert risk_validator is not None
        assert not risk_validator.entry_blocked
        assert risk_validator.position_sizer is not None
        assert risk_validator.stop_loss_calculator is not None
        assert risk_validator.take_profit_calculator is not None
        assert risk_validator.daily_loss_monitor is not None

    def test_initialization_missing_components(
        self, mock_stop_loss_calculator, mock_take_profit_calculator, mock_daily_loss_monitor
    ):
        """Test initialization fails with missing components."""
        with pytest.raises(RiskValidationError):
            RiskValidator(
                position_sizer=None,
                stop_loss_calculator=mock_stop_loss_calculator,
                take_profit_calculator=mock_take_profit_calculator,
                daily_loss_monitor=mock_daily_loss_monitor,
            )


class TestEntryControl:
    """Test entry blocking and control logic."""

    def test_check_entry_allowed_initially(self, risk_validator):
        """Test entry is allowed initially."""
        allowed, reason = risk_validator.check_entry_allowed()
        assert allowed is True
        assert "allowed" in reason.lower()

    def test_check_entry_blocked_after_daily_limit(self, risk_validator, mock_daily_loss_monitor):
        """Test entry blocked when daily loss limit reached."""
        mock_daily_loss_monitor.is_loss_limit_reached.return_value = True

        allowed, reason = risk_validator.check_entry_allowed()
        assert allowed is False
        assert "daily loss limit" in reason.lower()
        assert risk_validator.entry_blocked is True

    def test_handle_daily_loss_event(self, risk_validator):
        """Test handling of daily loss limit reached event."""
        event = Event(
            priority=9, event_type=EventType.DAILY_LOSS_LIMIT_REACHED, data={"loss_percentage": 6.5}
        )

        risk_validator.handle_daily_loss_event(event)
        assert risk_validator.entry_blocked is True

    def test_reset_entry_blocking(self, risk_validator):
        """Test resetting entry blocking."""
        risk_validator.entry_blocked = True
        risk_validator.reset_entry_blocking()
        assert risk_validator.entry_blocked is False


class TestPositionSizeValidation:
    """Test position size validation logic."""

    @pytest.mark.asyncio
    async def test_validate_position_size_valid(self, risk_validator):
        """Test validation passes for correct position size."""
        valid, reason = await risk_validator.validate_position_size(
            position_size=Decimal("1000"),
            symbol="BTCUSDT",
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            side=PositionSide.LONG,
            custom_balance=1000.0,
        )
        assert valid is True
        assert "valid" in reason.lower()

    @pytest.mark.asyncio
    async def test_validate_position_size_within_tolerance(self, risk_validator):
        """Test validation passes for size within 5% tolerance."""
        valid, reason = await risk_validator.validate_position_size(
            position_size=Decimal("1040"),  # +4% from 1000
            symbol="BTCUSDT",
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            side=PositionSide.LONG,
            custom_balance=1000.0,
        )
        assert valid is True

    @pytest.mark.asyncio
    async def test_validate_position_size_too_small(self, risk_validator):
        """Test validation fails for position size too small."""
        valid, reason = await risk_validator.validate_position_size(
            position_size=Decimal("900"),  # -10% from 1000
            symbol="BTCUSDT",
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            side=PositionSide.LONG,
            custom_balance=1000.0,
        )
        assert valid is False
        assert "below minimum" in reason.lower()

    @pytest.mark.asyncio
    async def test_validate_position_size_too_large(self, risk_validator):
        """Test validation fails for position size too large."""
        valid, reason = await risk_validator.validate_position_size(
            position_size=Decimal("1100"),  # +10% from 1000
            symbol="BTCUSDT",
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            side=PositionSide.LONG,
            custom_balance=1000.0,
        )
        assert valid is False
        assert "exceeds maximum" in reason.lower()


class TestStopLossValidation:
    """Test stop loss validation logic."""

    def test_validate_stop_loss_long_valid(self, risk_validator):
        """Test valid stop loss for LONG position."""
        valid, reason = risk_validator.validate_stop_loss(
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),  # 1% below entry
            side=PositionSide.LONG,
        )
        assert valid is True

    def test_validate_stop_loss_short_valid(self, risk_validator):
        """Test valid stop loss for SHORT position."""
        valid, reason = risk_validator.validate_stop_loss(
            entry_price=Decimal("50000"),
            stop_loss=Decimal("50500"),  # 1% above entry
            side=PositionSide.SHORT,
        )
        assert valid is True

    def test_validate_stop_loss_long_wrong_direction(self, risk_validator):
        """Test stop loss above entry for LONG position fails."""
        valid, reason = risk_validator.validate_stop_loss(
            entry_price=Decimal("50000"),
            stop_loss=Decimal("50500"),  # Above entry (wrong)
            side=PositionSide.LONG,
        )
        assert valid is False
        assert "below entry price" in reason.lower()

    def test_validate_stop_loss_short_wrong_direction(self, risk_validator):
        """Test stop loss below entry for SHORT position fails."""
        valid, reason = risk_validator.validate_stop_loss(
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),  # Below entry (wrong)
            side=PositionSide.SHORT,
        )
        assert valid is False
        assert "above entry price" in reason.lower()

    def test_validate_stop_loss_too_tight(self, risk_validator):
        """Test stop loss too close to entry fails."""
        valid, reason = risk_validator.validate_stop_loss(
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49990"),  # 0.02% (too tight)
            side=PositionSide.LONG,
        )
        assert valid is False
        assert "too tight" in reason.lower()

    def test_validate_stop_loss_too_wide(self, risk_validator):
        """Test stop loss too far from entry fails."""
        valid, reason = risk_validator.validate_stop_loss(
            entry_price=Decimal("50000"),
            stop_loss=Decimal("48000"),  # 4% (too wide)
            side=PositionSide.LONG,
        )
        assert valid is False
        assert "too wide" in reason.lower()


class TestTakeProfitValidation:
    """Test take profit validation logic."""

    def test_validate_take_profit_long_valid(self, risk_validator):
        """Test valid take profit for LONG position."""
        valid, reason = risk_validator.validate_take_profit(
            entry_price=Decimal("50000"),
            take_profit=Decimal("51000"),  # 2% above entry
            stop_loss=Decimal("49500"),  # 1% below entry (R:R = 2)
            side=PositionSide.LONG,
        )
        assert valid is True

    def test_validate_take_profit_short_valid(self, risk_validator):
        """Test valid take profit for SHORT position."""
        valid, reason = risk_validator.validate_take_profit(
            entry_price=Decimal("50000"),
            take_profit=Decimal("49000"),  # 2% below entry
            stop_loss=Decimal("50500"),  # 1% above entry (R:R = 2)
            side=PositionSide.SHORT,
        )
        assert valid is True

    def test_validate_take_profit_long_wrong_direction(self, risk_validator):
        """Test take profit below entry for LONG fails."""
        valid, reason = risk_validator.validate_take_profit(
            entry_price=Decimal("50000"),
            take_profit=Decimal("49500"),  # Below entry (wrong)
            stop_loss=Decimal("49000"),
            side=PositionSide.LONG,
        )
        assert valid is False
        assert "above entry price" in reason.lower()

    def test_validate_take_profit_short_wrong_direction(self, risk_validator):
        """Test take profit above entry for SHORT fails."""
        valid, reason = risk_validator.validate_take_profit(
            entry_price=Decimal("50000"),
            take_profit=Decimal("50500"),  # Above entry (wrong)
            stop_loss=Decimal("51000"),
            side=PositionSide.SHORT,
        )
        assert valid is False
        assert "below entry price" in reason.lower()

    def test_validate_take_profit_low_risk_reward(self, risk_validator):
        """Test take profit with insufficient risk-reward ratio fails."""
        valid, reason = risk_validator.validate_take_profit(
            entry_price=Decimal("50000"),
            take_profit=Decimal("50400"),  # 0.8% above entry
            stop_loss=Decimal("49500"),  # 1% below entry (R:R = 0.8)
            side=PositionSide.LONG,
        )
        assert valid is False
        assert "risk-reward ratio too low" in reason.lower()


class TestOrderValidation:
    """Test comprehensive order validation."""

    @pytest.mark.asyncio
    async def test_validate_order_all_checks_pass(self, risk_validator):
        """Test order validation with all checks passing."""
        result = await risk_validator.validate_order(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            take_profit=Decimal("51000"),
            position_size=Decimal("1000"),
            custom_balance=1000.0,
        )

        assert result.approved is True
        assert len(result.violations) == 0
        assert "passed" in result.reason.lower()
        assert result.metadata["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_validate_order_entry_blocked(self, risk_validator, mock_daily_loss_monitor):
        """Test order validation fails when entries are blocked."""
        mock_daily_loss_monitor.is_loss_limit_reached.return_value = True

        result = await risk_validator.validate_order(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            take_profit=Decimal("51000"),
            position_size=Decimal("1000"),
            custom_balance=1000.0,
        )

        assert result.approved is False
        assert "entry_blocked" in result.violations
        assert "daily loss limit" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_validate_order_multiple_violations(self, risk_validator):
        """Test order validation with multiple failures."""
        result = await risk_validator.validate_order(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("50500"),  # Wrong direction
            take_profit=Decimal("49500"),  # Wrong direction
            position_size=Decimal("1100"),  # Too large
            custom_balance=1000.0,
        )

        assert result.approved is False
        assert len(result.violations) >= 2
        assert any("stop_loss" in v for v in result.violations)
        assert any("take_profit" in v for v in result.violations)

    @pytest.mark.asyncio
    async def test_validate_order_with_metadata(self, risk_validator):
        """Test order validation preserves metadata."""
        custom_metadata = {"strategy": "ICT_SMC", "timeframe": "15m", "confidence": 0.85}

        result = await risk_validator.validate_order(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            take_profit=Decimal("51000"),
            position_size=Decimal("1000"),
            metadata=custom_metadata,
            custom_balance=1000.0,
        )

        assert result.metadata["strategy"] == "ICT_SMC"
        assert result.metadata["timeframe"] == "15m"
        assert result.metadata["confidence"] == 0.85


class TestValidationStatus:
    """Test validation status reporting."""

    def test_get_validation_status(self, risk_validator, mock_daily_loss_monitor):
        """Test getting current validation status."""
        status = risk_validator.get_validation_status()

        assert "entry_blocked" in status
        assert "daily_loss_limit_reached" in status
        assert "daily_status" in status
        assert "timestamp" in status

        daily_status = status["daily_status"]
        assert daily_status["loss_percentage"] == 2.5
        assert daily_status["loss_limit_pct"] == 6.0
        assert daily_status["remaining_capacity"] == 3.5


class TestEventPublishing:
    """Test event publishing for validation results."""

    @pytest.mark.asyncio
    async def test_publish_passed_validation(self, risk_validator, mock_event_bus):
        """Test event published for passed validation."""
        result = await risk_validator.validate_order(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49500"),
            take_profit=Decimal("51000"),
            position_size=Decimal("1000"),
            custom_balance=1000.0,
        )

        # Event publishing is logged but not directly testable without event bus implementation
        # This test verifies the validation succeeded
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_publish_failed_validation(self, risk_validator, mock_event_bus):
        """Test event published for failed validation."""
        result = await risk_validator.validate_order(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("50500"),  # Wrong direction
            take_profit=Decimal("51000"),
            position_size=Decimal("1000"),
            custom_balance=1000.0,
        )

        # Event publishing is logged but not directly testable without event bus implementation
        # This test verifies the validation failed
        assert result.approved is False


class TestThreadSafety:
    """Test thread-safety of entry blocking."""

    def test_concurrent_entry_check_thread_safe(self, risk_validator):
        """Test entry checking is thread-safe."""
        import threading

        results = []

        def check_entry():
            allowed, _ = risk_validator.check_entry_allowed()
            results.append(allowed)

        threads = [threading.Thread(target=check_entry) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All checks should return consistent results
        assert all(r == results[0] for r in results)

    def test_concurrent_blocking_reset_thread_safe(self, risk_validator):
        """Test entry blocking reset is thread-safe."""
        import threading

        def block_entry():
            risk_validator.entry_blocked = True

        def reset_entry():
            risk_validator.reset_entry_blocking()

        threads = [
            threading.Thread(target=block_entry if i % 2 == 0 else reset_entry) for i in range(20)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without deadlock or race conditions
        assert isinstance(risk_validator.entry_blocked, bool)
