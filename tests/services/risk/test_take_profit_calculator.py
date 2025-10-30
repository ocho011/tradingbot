"""
Unit tests for TakeProfitCalculator.

Tests cover:
- Liquidity level detection and target identification
- Risk-reward ratio calculation (minimum 1:1.5)
- Partial take-profit level calculation
- Trailing stop calculation
- Distance validation
- Multiple strategy modes (AUTO, LIQUIDITY_SWEEP, FIXED_RR, SCALED)
- Edge cases and error handling
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock
from datetime import datetime

from src.services.risk.take_profit_calculator import (
    TakeProfitCalculator,
    TakeProfitCalculationError,
    TakeProfitStrategy,
    PartialTakeProfit
)
from src.indicators.liquidity_zone import LiquidityLevel, LiquidityType, LiquidityState
from src.core.constants import PositionSide, TimeFrame


class TestTakeProfitCalculatorInitialization:
    """Test TakeProfitCalculator initialization and validation."""

    def test_successful_initialization(self):
        """Test successful initialization with valid parameters."""
        calculator = TakeProfitCalculator(
            min_risk_reward_ratio=1.5,
            partial_tp_percentages=[(1.5, 50), (2.5, 50)],
            min_distance_pct=0.5,
            max_distance_pct=10.0,
            precision=8
        )

        assert calculator.min_risk_reward_ratio == Decimal('1.5')
        assert len(calculator.partial_tp_percentages) == 2
        assert calculator.min_distance_pct == Decimal('0.5')
        assert calculator.max_distance_pct == Decimal('10.0')
        assert calculator.precision == 8

    def test_initialization_with_defaults(self):
        """Test initialization uses default values correctly."""
        calculator = TakeProfitCalculator()

        assert calculator.min_risk_reward_ratio == Decimal('1.5')
        assert len(calculator.partial_tp_percentages) == 4  # Default 4 levels
        assert calculator.min_distance_pct == Decimal('0.5')
        assert calculator.max_distance_pct == Decimal('10.0')
        assert calculator.precision == 8

    def test_invalid_min_rr_ratio(self):
        """Test initialization fails with RR ratio < 1.0."""
        with pytest.raises(ValueError, match="min_risk_reward_ratio must be >= 1.0"):
            TakeProfitCalculator(min_risk_reward_ratio=0.5)

    def test_invalid_distance_range(self):
        """Test initialization fails with invalid distance range."""
        with pytest.raises(ValueError, match="Invalid distance range"):
            TakeProfitCalculator(
                min_distance_pct=10.0,
                max_distance_pct=5.0
            )

    def test_invalid_precision(self):
        """Test initialization fails with negative precision."""
        with pytest.raises(ValueError, match="precision must be non-negative"):
            TakeProfitCalculator(precision=-1)

    def test_partial_tp_percentages_not_summing_to_100(self):
        """Test initialization fails when partial TP percentages don't sum to 100%."""
        with pytest.raises(ValueError, match="must sum to 100%"):
            TakeProfitCalculator(
                partial_tp_percentages=[(1.5, 30), (2.0, 40)]  # Only 70%
            )


class TestLiquidityLevelDetection:
    """Test liquidity level detection for take profit targets."""

    def test_find_long_target_liquidity_levels(self):
        """Test finding buy-side liquidity above entry for LONG positions."""
        calculator = TakeProfitCalculator()
        entry_price = 50000.0

        # Create liquidity levels
        liquidity_levels = [
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=51000.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=100,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.8,
                volume_profile=1000000.0,
                state=LiquidityState.ACTIVE
            ),
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=52000.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=101,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.9,
                volume_profile=1500000.0,
                state=LiquidityState.ACTIVE
            ),
            LiquidityLevel(
                type=LiquidityType.SELL_SIDE,
                price=49000.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=99,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.7,
                volume_profile=800000.0,
                state=LiquidityState.ACTIVE
            )
        ]

        result = calculator._find_target_liquidity_levels(
            liquidity_levels,
            entry_price,
            PositionSide.LONG,
            count=2
        )

        # Should only find buy-side liquidity above entry
        assert len(result) == 2
        assert all(level.type == LiquidityType.BUY_SIDE for level in result)
        assert all(level.price > entry_price for level in result)

    def test_find_short_target_liquidity_levels(self):
        """Test finding sell-side liquidity below entry for SHORT positions."""
        calculator = TakeProfitCalculator()
        entry_price = 50000.0

        liquidity_levels = [
            LiquidityLevel(
                type=LiquidityType.SELL_SIDE,
                price=49000.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=99,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.8,
                volume_profile=1000000.0,
                state=LiquidityState.ACTIVE
            ),
            LiquidityLevel(
                type=LiquidityType.SELL_SIDE,
                price=48000.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=98,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.9,
                volume_profile=1500000.0,
                state=LiquidityState.ACTIVE
            ),
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=51000.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=100,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.7,
                volume_profile=800000.0,
                state=LiquidityState.ACTIVE
            )
        ]

        result = calculator._find_target_liquidity_levels(
            liquidity_levels,
            entry_price,
            PositionSide.SHORT,
            count=2
        )

        # Should only find sell-side liquidity below entry
        assert len(result) == 2
        assert all(level.type == LiquidityType.SELL_SIDE for level in result)
        assert all(level.price < entry_price for level in result)

    def test_no_relevant_liquidity_levels(self):
        """Test behavior when no relevant liquidity levels exist."""
        calculator = TakeProfitCalculator()
        entry_price = 50000.0

        # All levels are below entry for LONG (need levels above)
        liquidity_levels = [
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=49000.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=99,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.8,
                volume_profile=1000000.0,
                state=LiquidityState.ACTIVE
            )
        ]

        result = calculator._find_target_liquidity_levels(
            liquidity_levels,
            entry_price,
            PositionSide.LONG,
            count=2
        )

        assert len(result) == 0


class TestRiskRewardCalculation:
    """Test risk-reward ratio calculation."""

    def test_calculate_risk_distance(self):
        """Test risk distance calculation."""
        calculator = TakeProfitCalculator()

        entry_price = 50000.0
        stop_loss_price = 49500.0

        risk_distance = calculator._calculate_risk_distance(entry_price, stop_loss_price)

        assert risk_distance == Decimal('500.0')

    def test_calculate_tp_price_from_rr_long(self):
        """Test TP price calculation for LONG position."""
        calculator = TakeProfitCalculator()

        entry_price = 50000.0
        stop_loss_price = 49500.0  # 500 risk
        rr_ratio = 2.0

        tp_price = calculator._calculate_tp_price_from_rr(
            entry_price,
            stop_loss_price,
            rr_ratio,
            PositionSide.LONG
        )

        # Expected: entry + (risk * RR) = 50000 + (500 * 2) = 51000
        assert tp_price == pytest.approx(51000.0, rel=1e-6)

    def test_calculate_tp_price_from_rr_short(self):
        """Test TP price calculation for SHORT position."""
        calculator = TakeProfitCalculator()

        entry_price = 50000.0
        stop_loss_price = 50500.0  # 500 risk
        rr_ratio = 2.0

        tp_price = calculator._calculate_tp_price_from_rr(
            entry_price,
            stop_loss_price,
            rr_ratio,
            PositionSide.SHORT
        )

        # Expected: entry - (risk * RR) = 50000 - (500 * 2) = 49000
        assert tp_price == pytest.approx(49000.0, rel=1e-6)


class TestPartialTakeProfitCalculation:
    """Test partial take-profit level calculation."""

    def test_calculate_partial_take_profits_long(self):
        """Test calculating partial TP levels for LONG position."""
        calculator = TakeProfitCalculator(
            partial_tp_percentages=[(1.5, 50), (2.5, 50)]
        )

        entry_price = 50000.0
        stop_loss_price = 49500.0  # 500 risk

        partial_tps = calculator.calculate_partial_take_profits(
            entry_price,
            stop_loss_price,
            PositionSide.LONG
        )

        assert len(partial_tps) == 2

        # First TP: 1.5 RR = 50000 + (500 * 1.5) = 50750
        assert partial_tps[0].price == pytest.approx(50750.0, rel=1e-6)
        assert partial_tps[0].percentage == 50.0
        assert partial_tps[0].risk_reward_ratio == 1.5

        # Second TP: 2.5 RR = 50000 + (500 * 2.5) = 51250
        assert partial_tps[1].price == pytest.approx(51250.0, rel=1e-6)
        assert partial_tps[1].percentage == 50.0
        assert partial_tps[1].risk_reward_ratio == 2.5

    def test_calculate_partial_take_profits_short(self):
        """Test calculating partial TP levels for SHORT position."""
        calculator = TakeProfitCalculator(
            partial_tp_percentages=[(1.5, 50), (2.5, 50)]
        )

        entry_price = 50000.0
        stop_loss_price = 50500.0  # 500 risk

        partial_tps = calculator.calculate_partial_take_profits(
            entry_price,
            stop_loss_price,
            PositionSide.SHORT
        )

        assert len(partial_tps) == 2

        # First TP: 1.5 RR = 50000 - (500 * 1.5) = 49250
        assert partial_tps[0].price == pytest.approx(49250.0, rel=1e-6)
        assert partial_tps[0].percentage == 50.0

        # Second TP: 2.5 RR = 50000 - (500 * 2.5) = 48750
        assert partial_tps[1].price == pytest.approx(48750.0, rel=1e-6)
        assert partial_tps[1].percentage == 50.0

    def test_partial_tp_with_liquidity_alignment(self):
        """Test partial TP alignment with liquidity levels."""
        calculator = TakeProfitCalculator(
            partial_tp_percentages=[(1.5, 50), (2.5, 50)]
        )

        entry_price = 50000.0
        stop_loss_price = 49500.0  # 500 risk

        # Create liquidity level near first TP (50750 expected)
        liquidity_levels = [
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=50800.0,  # Close to 50750 (within 1% of entry)
                origin_timestamp=datetime.now(),
                origin_candle_index=100,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.9,
                volume_profile=1500000.0,
                state=LiquidityState.ACTIVE
            )
        ]

        partial_tps = calculator.calculate_partial_take_profits(
            entry_price,
            stop_loss_price,
            PositionSide.LONG,
            liquidity_levels
        )

        # First TP should align with liquidity level
        assert partial_tps[0].liquidity_level is not None
        assert partial_tps[0].price == 50800.0


class TestTakeProfitCalculation:
    """Test complete take profit calculation."""

    def test_calculate_take_profit_long(self):
        """Test complete TP calculation for LONG position."""
        calculator = TakeProfitCalculator(
            min_risk_reward_ratio=1.5,
            partial_tp_percentages=[(1.5, 50), (2.5, 50)]
        )

        entry_price = 50000.0
        stop_loss_price = 49500.0  # 500 risk

        result = calculator.calculate_take_profit(
            entry_price,
            stop_loss_price,
            PositionSide.LONG
        )

        assert result['valid'] is True
        assert result['min_risk_reward_ratio'] == 1.5
        assert result['actual_risk_reward_ratio'] >= 1.5
        assert result['final_target'] == pytest.approx(51250.0, rel=1e-6)
        assert len(result['partial_take_profits']) == 2
        assert result['trailing_stop_enabled'] is True
        assert result['trailing_activation_price'] is not None

    def test_calculate_take_profit_short(self):
        """Test complete TP calculation for SHORT position."""
        calculator = TakeProfitCalculator(
            min_risk_reward_ratio=1.5,
            partial_tp_percentages=[(1.5, 50), (2.5, 50)]
        )

        entry_price = 50000.0
        stop_loss_price = 50500.0  # 500 risk

        result = calculator.calculate_take_profit(
            entry_price,
            stop_loss_price,
            PositionSide.SHORT
        )

        assert result['valid'] is True
        assert result['actual_risk_reward_ratio'] >= 1.5
        assert result['final_target'] == pytest.approx(48750.0, rel=1e-6)
        assert len(result['partial_take_profits']) == 2

    def test_calculate_take_profit_with_liquidity_levels(self):
        """Test TP calculation with liquidity level integration."""
        calculator = TakeProfitCalculator(
            partial_tp_percentages=[(1.5, 50), (2.5, 50)]
        )

        entry_price = 50000.0
        stop_loss_price = 49500.0

        liquidity_levels = [
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=51300.0,
                origin_timestamp=datetime.now(),
                origin_candle_index=100,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=1,
                strength=0.9,
                volume_profile=1500000.0,
                state=LiquidityState.ACTIVE
            )
        ]

        result = calculator.calculate_take_profit(
            entry_price,
            stop_loss_price,
            PositionSide.LONG,
            liquidity_levels
        )

        assert result['valid'] is True
        # Some TPs might be aligned with liquidity
        assert len(result['partial_take_profits']) == 2


class TestTrailingStopCalculation:
    """Test trailing stop calculation."""

    def test_calculate_trailing_stop_long(self):
        """Test trailing stop for LONG position."""
        calculator = TakeProfitCalculator()

        current_price = 51000.0
        entry_price = 50000.0
        highest_price = 51500.0
        lowest_price = 49000.0  # Not used for LONG

        trailing_stop = calculator.calculate_trailing_stop(
            current_price,
            entry_price,
            highest_price,
            lowest_price,
            PositionSide.LONG,
            trailing_pct=1.0
        )

        # Expected: highest - (highest * 1%) = 51500 - 515 = 50985
        assert trailing_stop == pytest.approx(50985.0, rel=1e-6)

    def test_calculate_trailing_stop_short(self):
        """Test trailing stop for SHORT position."""
        calculator = TakeProfitCalculator()

        current_price = 49000.0
        entry_price = 50000.0
        highest_price = 51000.0  # Not used for SHORT
        lowest_price = 48500.0

        trailing_stop = calculator.calculate_trailing_stop(
            current_price,
            entry_price,
            highest_price,
            lowest_price,
            PositionSide.SHORT,
            trailing_pct=1.0
        )

        # Expected: lowest + (lowest * 1%) = 48500 + 485 = 48985
        assert trailing_stop == pytest.approx(48985.0, rel=1e-6)

    def test_trailing_stop_doesnt_go_below_entry_long(self):
        """Test trailing stop doesn't go below entry for LONG."""
        calculator = TakeProfitCalculator()

        current_price = 50200.0
        entry_price = 50000.0
        highest_price = 50300.0  # Only 300 profit
        lowest_price = 49000.0

        trailing_stop = calculator.calculate_trailing_stop(
            current_price,
            entry_price,
            highest_price,
            lowest_price,
            PositionSide.LONG,
            trailing_pct=1.0
        )

        # Calculated: 50300 - 503 = 49797, but should be at entry minimum
        assert trailing_stop == entry_price

    def test_trailing_stop_doesnt_go_above_entry_short(self):
        """Test trailing stop doesn't go above entry for SHORT."""
        calculator = TakeProfitCalculator()

        current_price = 49800.0
        entry_price = 50000.0
        highest_price = 51000.0
        lowest_price = 49700.0  # Only 300 profit

        trailing_stop = calculator.calculate_trailing_stop(
            current_price,
            entry_price,
            highest_price,
            lowest_price,
            PositionSide.SHORT,
            trailing_pct=1.0
        )

        # Calculated: 49700 + 497 = 50197, but should be at entry maximum
        assert trailing_stop == entry_price


class TestDistanceValidation:
    """Test distance validation."""

    def test_validate_tp_distance_valid(self):
        """Test TP distance validation passes for valid distance."""
        calculator = TakeProfitCalculator(
            min_distance_pct=0.5,
            max_distance_pct=10.0
        )

        entry_price = 50000.0
        tp_price = 51000.0  # 2% distance

        is_valid = calculator._validate_tp_distance(
            entry_price,
            tp_price,
            PositionSide.LONG
        )

        assert is_valid is True

    def test_validate_tp_distance_too_close(self):
        """Test TP distance validation fails for too close TP."""
        calculator = TakeProfitCalculator(
            min_distance_pct=1.0,
            max_distance_pct=10.0
        )

        entry_price = 50000.0
        tp_price = 50100.0  # 0.2% distance (too close)

        is_valid = calculator._validate_tp_distance(
            entry_price,
            tp_price,
            PositionSide.LONG
        )

        assert is_valid is False

    def test_validate_tp_distance_too_far(self):
        """Test TP distance validation fails for too far TP."""
        calculator = TakeProfitCalculator(
            min_distance_pct=0.5,
            max_distance_pct=5.0
        )

        entry_price = 50000.0
        tp_price = 54000.0  # 8% distance (too far)

        is_valid = calculator._validate_tp_distance(
            entry_price,
            tp_price,
            PositionSide.LONG
        )

        assert is_valid is False


class TestParameterManagement:
    """Test parameter getter and setter methods."""

    def test_get_parameters(self):
        """Test getting current parameters."""
        calculator = TakeProfitCalculator(
            min_risk_reward_ratio=2.0,
            partial_tp_percentages=[(1.5, 50), (2.5, 50)]
        )

        params = calculator.get_parameters()

        assert params['min_risk_reward_ratio'] == 2.0
        assert len(params['partial_tp_percentages']) == 2
        assert params['min_distance_pct'] == 0.5
        assert params['max_distance_pct'] == 10.0
        assert params['precision'] == 8

    def test_update_min_rr_ratio(self):
        """Test updating minimum RR ratio."""
        calculator = TakeProfitCalculator(min_risk_reward_ratio=1.5)

        calculator.update_parameters(min_risk_reward_ratio=2.0)

        assert calculator.min_risk_reward_ratio == Decimal('2.0')

    def test_update_partial_tp_percentages(self):
        """Test updating partial TP percentages."""
        calculator = TakeProfitCalculator()

        new_percentages = [(2.0, 100)]
        calculator.update_parameters(partial_tp_percentages=new_percentages)

        assert len(calculator.partial_tp_percentages) == 1
        assert calculator.partial_tp_percentages[0] == (Decimal('2.0'), Decimal('100'))

    def test_update_distance_parameters(self):
        """Test updating distance parameters."""
        calculator = TakeProfitCalculator()

        calculator.update_parameters(
            min_distance_pct=1.0,
            max_distance_pct=15.0
        )

        assert calculator.min_distance_pct == Decimal('1.0')
        assert calculator.max_distance_pct == Decimal('15.0')

    def test_update_invalid_rr_ratio(self):
        """Test updating with invalid RR ratio fails."""
        calculator = TakeProfitCalculator()

        with pytest.raises(ValueError, match="min_risk_reward_ratio must be >= 1.0"):
            calculator.update_parameters(min_risk_reward_ratio=0.5)

    def test_update_invalid_percentages_sum(self):
        """Test updating with invalid percentage sum fails."""
        calculator = TakeProfitCalculator()

        with pytest.raises(ValueError, match="must sum to 100%"):
            calculator.update_parameters(
                partial_tp_percentages=[(1.5, 30), (2.0, 40)]
            )


class TestEdgeCases:
    """Test edge cases and error scenarios."""

    def test_no_partial_tps_calculated(self):
        """Test error when no partial TPs can be calculated."""
        # Create calculator with valid percentages first
        calculator = TakeProfitCalculator(
            partial_tp_percentages=[(1.5, 100)]
        )
        # Then manually set to empty to simulate edge case
        calculator.partial_tp_percentages = []

        with pytest.raises(TakeProfitCalculationError):
            calculator.calculate_take_profit(
                entry_price=50000.0,
                stop_loss_price=49500.0,
                position_side=PositionSide.LONG
            )

    def test_rounding_precision(self):
        """Test price rounding to specified precision."""
        calculator = TakeProfitCalculator(precision=2)

        price = 50000.123456
        rounded = calculator._round_tp_price(price)

        assert rounded == 50000.12

    def test_partial_take_profit_to_dict(self):
        """Test PartialTakeProfit to_dict conversion."""
        liquidity_level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=51000.0,
            origin_timestamp=int(datetime.now().timestamp() * 1000),
            origin_candle_index=100,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            touch_count=1,
            strength=0.9,
            volume_profile=1500000.0,
            state=LiquidityState.ACTIVE
        )

        partial_tp = PartialTakeProfit(
            price=51000.0,
            percentage=25.0,
            liquidity_level=liquidity_level,
            risk_reward_ratio=1.5
        )

        result = partial_tp.to_dict()

        assert result['price'] == 51000.0
        assert result['percentage'] == 25.0
        assert result['liquidity_level'] is not None
        assert result['risk_reward_ratio'] == 1.5
