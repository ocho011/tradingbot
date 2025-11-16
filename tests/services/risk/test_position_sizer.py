"""
Unit tests for PositionSizer class.

Tests cover:
- Position size calculation with various balance scenarios
- Risk amount calculation (2%)
- Leverage application (5x)
- Min/max validation
- Precision handling
- Error cases
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.exchange.binance_manager import BinanceConnectionError, BinanceManager
from src.services.risk.position_sizer import PositionSizer, PositionSizingError


@pytest.fixture
def mock_binance_manager():
    """Create a mock BinanceManager instance."""
    manager = MagicMock(spec=BinanceManager)
    manager.fetch_balance = AsyncMock()
    return manager


@pytest.fixture
def position_sizer(mock_binance_manager):
    """Create a PositionSizer instance with default parameters."""
    return PositionSizer(
        binance_manager=mock_binance_manager,
        risk_percentage=2.0,
        leverage=5,
        min_position_size=10.0,
        max_position_size=10000.0,
        precision=8,
    )


class TestPositionSizerInitialization:
    """Test PositionSizer initialization and parameter validation."""

    def test_init_with_valid_parameters(self, mock_binance_manager):
        """Test initialization with valid parameters."""
        sizer = PositionSizer(
            binance_manager=mock_binance_manager,
            risk_percentage=2.0,
            leverage=5,
            min_position_size=10.0,
            max_position_size=10000.0,
        )

        assert sizer.risk_percentage == Decimal("2.0")
        assert sizer.leverage == 5
        assert sizer.min_position_size == Decimal("10.0")
        assert sizer.max_position_size == Decimal("10000.0")
        assert sizer.precision == 8

    def test_init_with_invalid_binance_manager(self):
        """Test initialization with invalid BinanceManager."""
        with pytest.raises(ValueError, match="binance_manager must be a BinanceManager instance"):
            PositionSizer(binance_manager="not a manager")

    def test_init_with_invalid_risk_percentage(self, mock_binance_manager):
        """Test initialization with invalid risk percentage."""
        with pytest.raises(ValueError, match="risk_percentage must be between 0 and 100"):
            PositionSizer(mock_binance_manager, risk_percentage=-1)

        with pytest.raises(ValueError, match="risk_percentage must be between 0 and 100"):
            PositionSizer(mock_binance_manager, risk_percentage=0)

        with pytest.raises(ValueError, match="risk_percentage must be between 0 and 100"):
            PositionSizer(mock_binance_manager, risk_percentage=101)

    def test_init_with_invalid_leverage(self, mock_binance_manager):
        """Test initialization with invalid leverage."""
        with pytest.raises(ValueError, match="leverage must be positive"):
            PositionSizer(mock_binance_manager, leverage=0)

        with pytest.raises(ValueError, match="leverage must be positive"):
            PositionSizer(mock_binance_manager, leverage=-5)

    def test_init_with_invalid_min_position_size(self, mock_binance_manager):
        """Test initialization with invalid minimum position size."""
        with pytest.raises(ValueError, match="min_position_size must be positive"):
            PositionSizer(mock_binance_manager, min_position_size=0)

        with pytest.raises(ValueError, match="min_position_size must be positive"):
            PositionSizer(mock_binance_manager, min_position_size=-10)

    def test_init_with_invalid_max_position_size(self, mock_binance_manager):
        """Test initialization with invalid maximum position size."""
        with pytest.raises(
            ValueError, match="max_position_size must be greater than min_position_size"
        ):
            PositionSizer(mock_binance_manager, min_position_size=100.0, max_position_size=50.0)

    def test_init_with_invalid_precision(self, mock_binance_manager):
        """Test initialization with invalid precision."""
        with pytest.raises(ValueError, match="precision must be non-negative"):
            PositionSizer(mock_binance_manager, precision=-1)


class TestAccountBalanceRetrieval:
    """Test account balance retrieval functionality."""

    @pytest.mark.asyncio
    async def test_get_account_balance_success(self, position_sizer, mock_binance_manager):
        """Test successful balance retrieval."""
        mock_binance_manager.fetch_balance.return_value = {
            "free": {"USDT": 1000.0},
            "used": {"USDT": 0.0},
            "total": {"USDT": 1000.0},
        }

        balance = await position_sizer.get_account_balance("USDT")

        assert balance == Decimal("1000.0")
        mock_binance_manager.fetch_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_account_balance_no_currency(self, position_sizer, mock_binance_manager):
        """Test balance retrieval when currency not found."""
        mock_binance_manager.fetch_balance.return_value = {"free": {}, "used": {}, "total": {}}

        balance = await position_sizer.get_account_balance("USDT")

        assert balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_account_balance_connection_error(self, position_sizer, mock_binance_manager):
        """Test balance retrieval with connection error."""
        mock_binance_manager.fetch_balance.side_effect = BinanceConnectionError("Connection failed")

        with pytest.raises(PositionSizingError, match="Failed to fetch account balance"):
            await position_sizer.get_account_balance("USDT")


class TestRiskCalculations:
    """Test risk amount and leverage calculations."""

    def test_calculate_risk_amount(self, position_sizer):
        """Test 2% risk calculation."""
        balance = Decimal("1000.0")
        risk_amount = position_sizer.calculate_risk_amount(balance)

        assert risk_amount == Decimal("20.0")  # 2% of 1000

    def test_calculate_risk_amount_various_balances(self, position_sizer):
        """Test risk calculation with various balance amounts."""
        test_cases = [
            (Decimal("100.0"), Decimal("2.0")),  # 2% of 100
            (Decimal("500.0"), Decimal("10.0")),  # 2% of 500
            (Decimal("5000.0"), Decimal("100.0")),  # 2% of 5000
            (Decimal("10000.0"), Decimal("200.0")),  # 2% of 10000
        ]

        for balance, expected_risk in test_cases:
            risk_amount = position_sizer.calculate_risk_amount(balance)
            assert risk_amount == expected_risk

    def test_apply_leverage(self, position_sizer):
        """Test 5x leverage application."""
        risk_amount = Decimal("20.0")
        position_size = position_sizer.apply_leverage(risk_amount)

        assert position_size == Decimal("100.0")  # 20 * 5

    def test_apply_leverage_various_amounts(self, position_sizer):
        """Test leverage application with various amounts."""
        test_cases = [
            (Decimal("10.0"), Decimal("50.0")),  # 10 * 5
            (Decimal("50.0"), Decimal("250.0")),  # 50 * 5
            (Decimal("100.0"), Decimal("500.0")),  # 100 * 5
            (Decimal("200.0"), Decimal("1000.0")),  # 200 * 5
        ]

        for risk_amount, expected_position in test_cases:
            position_size = position_sizer.apply_leverage(risk_amount)
            assert position_size == expected_position


class TestPositionSizeValidation:
    """Test position size min/max validation."""

    def test_validate_position_size_within_range(self, position_sizer):
        """Test validation with position size within acceptable range."""
        position_size = Decimal("500.0")
        validated = position_sizer.validate_position_size(position_size)

        assert validated == Decimal("500.0")

    def test_validate_position_size_below_minimum(self, position_sizer):
        """Test validation with position size below minimum."""
        position_size = Decimal("5.0")  # Below min of 10

        with pytest.raises(PositionSizingError, match="below minimum"):
            position_sizer.validate_position_size(position_size)

    def test_validate_position_size_above_maximum(self, position_sizer):
        """Test validation with position size above maximum."""
        position_size = Decimal("15000.0")  # Above max of 10000
        validated = position_sizer.validate_position_size(position_size)

        assert validated == Decimal("10000.0")  # Capped to maximum

    def test_validate_position_size_at_boundaries(self, position_sizer):
        """Test validation at exact min/max boundaries."""
        # At minimum
        validated_min = position_sizer.validate_position_size(Decimal("10.0"))
        assert validated_min == Decimal("10.0")

        # At maximum
        validated_max = position_sizer.validate_position_size(Decimal("10000.0"))
        assert validated_max == Decimal("10000.0")


class TestPrecisionHandling:
    """Test position size rounding and precision."""

    def test_round_position_size_default_precision(self, position_sizer):
        """Test rounding with default precision (8 decimals)."""
        position_size = Decimal("123.123456789")
        rounded = position_sizer.round_position_size(position_size)

        assert rounded == Decimal("123.12345678")

    def test_round_position_size_various_precisions(self, mock_binance_manager):
        """Test rounding with various precision values."""
        test_cases = [
            (2, Decimal("123.456"), Decimal("123.45")),
            (3, Decimal("123.4567"), Decimal("123.456")),
            (4, Decimal("123.45678"), Decimal("123.4567")),
            (0, Decimal("123.456"), Decimal("123")),
        ]

        for precision, input_size, expected_output in test_cases:
            sizer = PositionSizer(mock_binance_manager, precision=precision)
            rounded = sizer.round_position_size(input_size)
            assert rounded == expected_output


class TestPositionSizeCalculation:
    """Test complete position size calculation workflow."""

    @pytest.mark.asyncio
    async def test_calculate_position_size_with_custom_balance(self, position_sizer):
        """Test calculation with custom balance (no API call)."""
        result = await position_sizer.calculate_position_size(custom_balance=1000.0)

        assert result["balance"] == 1000.0
        assert result["risk_amount"] == 20.0  # 2% of 1000
        assert result["position_size"] == 100.0  # 20 * 5x leverage
        assert result["leverage"] == 5
        assert result["risk_percentage"] == 2.0
        assert result["currency"] == "USDT"
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_calculate_position_size_with_api(self, position_sizer, mock_binance_manager):
        """Test calculation with actual balance API call."""
        mock_binance_manager.fetch_balance.return_value = {"free": {"USDT": 5000.0}}

        result = await position_sizer.calculate_position_size()

        assert result["balance"] == 5000.0
        assert result["risk_amount"] == 100.0  # 2% of 5000
        assert result["position_size"] == 500.0  # 100 * 5x leverage
        mock_binance_manager.fetch_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_calculate_position_size_various_balances(self, position_sizer):
        """Test position size calculation with various balance scenarios."""
        test_cases = [
            # (balance, expected_risk, expected_position)
            (100.0, 2.0, 10.0),  # Minimum viable
            (500.0, 10.0, 50.0),
            (1000.0, 20.0, 100.0),
            (5000.0, 100.0, 500.0),
            (10000.0, 200.0, 1000.0),
        ]

        for balance, expected_risk, expected_position in test_cases:
            result = await position_sizer.calculate_position_size(custom_balance=balance)

            assert result["balance"] == balance
            assert result["risk_amount"] == expected_risk
            assert result["position_size"] == expected_position

    @pytest.mark.asyncio
    async def test_calculate_position_size_with_insufficient_balance(self, position_sizer):
        """Test calculation with insufficient balance."""
        with pytest.raises(PositionSizingError, match="Insufficient.*balance"):
            await position_sizer.calculate_position_size(custom_balance=0)

    @pytest.mark.asyncio
    async def test_calculate_position_size_with_capping(self, position_sizer):
        """Test calculation where result is capped to maximum."""
        # Balance that would result in position > 10000
        result = await position_sizer.calculate_position_size(custom_balance=200000.0)

        # Should be capped to max_position_size
        assert result["position_size"] == 10000.0


class TestQuantityCalculation:
    """Test trading quantity calculation for symbols."""

    def test_calculate_quantity_for_symbol(self, position_sizer):
        """Test quantity calculation with standard parameters."""
        quantity = position_sizer.calculate_quantity_for_symbol(
            position_size_usdt=100.0, entry_price=50000.0, symbol_precision=3
        )

        assert quantity == 0.002  # 100 / 50000 = 0.002

    def test_calculate_quantity_various_scenarios(self, position_sizer):
        """Test quantity calculation with various scenarios."""
        test_cases = [
            # (position_size, entry_price, precision, expected_quantity)
            (100.0, 50000.0, 3, 0.002),  # BTC-like
            (100.0, 2000.0, 3, 0.050),  # ETH-like
            (100.0, 1.0, 2, 100.00),  # Stablecoin
            (1000.0, 0.5, 0, 2000.0),  # Low-price coin
        ]

        for position_size, entry_price, precision, expected in test_cases:
            quantity = position_sizer.calculate_quantity_for_symbol(
                position_size, entry_price, precision
            )
            assert quantity == expected

    def test_calculate_quantity_with_invalid_price(self, position_sizer):
        """Test quantity calculation with invalid entry price."""
        with pytest.raises(ValueError, match="entry_price must be positive"):
            position_sizer.calculate_quantity_for_symbol(100.0, 0)

        with pytest.raises(ValueError, match="entry_price must be positive"):
            position_sizer.calculate_quantity_for_symbol(100.0, -50000.0)

    def test_calculate_quantity_with_invalid_position_size(self, position_sizer):
        """Test quantity calculation with invalid position size."""
        with pytest.raises(ValueError, match="position_size_usdt must be positive"):
            position_sizer.calculate_quantity_for_symbol(0, 50000.0)

        with pytest.raises(ValueError, match="position_size_usdt must be positive"):
            position_sizer.calculate_quantity_for_symbol(-100.0, 50000.0)


class TestParameterUpdates:
    """Test dynamic parameter updates."""

    def test_update_risk_percentage(self, position_sizer):
        """Test updating risk percentage."""
        position_sizer.update_parameters(risk_percentage=3.0)

        assert position_sizer.risk_percentage == Decimal("3.0")

    def test_update_leverage(self, position_sizer):
        """Test updating leverage."""
        position_sizer.update_parameters(leverage=10)

        assert position_sizer.leverage == 10

    def test_update_min_position_size(self, position_sizer):
        """Test updating minimum position size."""
        position_sizer.update_parameters(min_position_size=20.0)

        assert position_sizer.min_position_size == Decimal("20.0")

    def test_update_max_position_size(self, position_sizer):
        """Test updating maximum position size."""
        position_sizer.update_parameters(max_position_size=20000.0)

        assert position_sizer.max_position_size == Decimal("20000.0")

    def test_update_multiple_parameters(self, position_sizer):
        """Test updating multiple parameters at once."""
        position_sizer.update_parameters(risk_percentage=3.0, leverage=10, min_position_size=20.0)

        assert position_sizer.risk_percentage == Decimal("3.0")
        assert position_sizer.leverage == 10
        assert position_sizer.min_position_size == Decimal("20.0")

    def test_update_with_invalid_parameters(self, position_sizer):
        """Test updating with invalid parameters."""
        with pytest.raises(ValueError):
            position_sizer.update_parameters(risk_percentage=-1)

        with pytest.raises(ValueError):
            position_sizer.update_parameters(leverage=0)

        with pytest.raises(ValueError):
            position_sizer.update_parameters(min_position_size=-10)


class TestGetParameters:
    """Test retrieving current parameters."""

    def test_get_parameters(self, position_sizer):
        """Test getting current parameters."""
        params = position_sizer.get_parameters()

        assert params["risk_percentage"] == 2.0
        assert params["leverage"] == 5
        assert params["min_position_size"] == 10.0
        assert params["max_position_size"] == 10000.0
        assert params["precision"] == 8

    def test_get_parameters_after_updates(self, position_sizer):
        """Test getting parameters after updates."""
        position_sizer.update_parameters(risk_percentage=3.0, leverage=10)

        params = position_sizer.get_parameters()

        assert params["risk_percentage"] == 3.0
        assert params["leverage"] == 10


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_very_small_balance(self, position_sizer):
        """Test with very small balance."""
        # Balance that results in position below minimum
        with pytest.raises(PositionSizingError, match="below minimum"):
            await position_sizer.calculate_position_size(custom_balance=50.0)
            # 50 * 0.02 * 5 = 5 USDT (below min of 10)

    @pytest.mark.asyncio
    async def test_very_large_balance(self, position_sizer):
        """Test with very large balance."""
        result = await position_sizer.calculate_position_size(custom_balance=1000000.0)

        # Should be capped to max_position_size
        assert result["position_size"] == 10000.0

    def test_precision_edge_cases(self, mock_binance_manager):
        """Test with extreme precision values."""
        # Very low precision
        sizer = PositionSizer(mock_binance_manager, precision=0)
        rounded = sizer.round_position_size(Decimal("123.456"))
        assert rounded == Decimal("123")

        # Very high precision
        sizer = PositionSizer(mock_binance_manager, precision=18)
        rounded = sizer.round_position_size(Decimal("123.123456789012345678"))
        assert rounded == Decimal("123.123456789012345678")


class TestIntegrationScenarios:
    """Test complete integration scenarios."""

    @pytest.mark.asyncio
    async def test_complete_trading_workflow(self, position_sizer, mock_binance_manager):
        """Test complete workflow from balance to trading quantity."""
        # Setup: Account has 10000 USDT
        mock_binance_manager.fetch_balance.return_value = {"free": {"USDT": 10000.0}}

        # Step 1: Calculate position size
        result = await position_sizer.calculate_position_size()

        assert result["balance"] == 10000.0
        assert result["risk_amount"] == 200.0  # 2% risk
        assert result["position_size"] == 1000.0  # 5x leverage

        # Step 2: Calculate trading quantity for BTC at 50000 USDT
        quantity = position_sizer.calculate_quantity_for_symbol(
            position_size_usdt=result["position_size"], entry_price=50000.0, symbol_precision=3
        )

        assert quantity == 0.020  # 1000 / 50000 = 0.02 BTC

    @pytest.mark.asyncio
    async def test_parameter_adjustment_workflow(self, position_sizer):
        """Test workflow with parameter adjustments."""
        # Initial calculation with default parameters
        result1 = await position_sizer.calculate_position_size(custom_balance=1000.0)
        assert result1["position_size"] == 100.0  # 2% * 5x

        # Increase risk to 3%
        position_sizer.update_parameters(risk_percentage=3.0)
        result2 = await position_sizer.calculate_position_size(custom_balance=1000.0)
        assert result2["position_size"] == 150.0  # 3% * 5x

        # Increase leverage to 10x
        position_sizer.update_parameters(leverage=10)
        result3 = await position_sizer.calculate_position_size(custom_balance=1000.0)
        assert result3["position_size"] == 300.0  # 3% * 10x
