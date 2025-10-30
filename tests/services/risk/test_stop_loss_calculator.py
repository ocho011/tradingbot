"""
Unit tests for StopLossCalculator.

Tests cover:
- Structural level detection (Order Blocks, FVGs, Liquidity Zones)
- Tolerance application (0.1-0.3%)
- Stop distance validation (0.3-3.0%)
- Position size recalculation
- Multiple strategy modes (AUTO, ORDER_BLOCK, FAIR_VALUE_GAP, LIQUIDITY_ZONE)
- Edge cases and error handling
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from src.services.risk.stop_loss_calculator import (
    StopLossCalculator,
    StopLossCalculationError,
    StopLossStrategy
)
from src.services.risk.position_sizer import PositionSizer
from src.indicators.order_block import OrderBlock, OrderBlockType, OrderBlockState
from src.indicators.fair_value_gap import FairValueGap, FVGType, FVGState
from src.indicators.liquidity_zone import LiquidityLevel, LiquidityType, LiquidityState
from src.core.constants import PositionSide, TimeFrame


class TestStopLossCalculatorInitialization:
    """Test StopLossCalculator initialization and validation."""

    def test_successful_initialization(self):
        """Test successful initialization with valid parameters."""
        position_sizer = Mock(spec=PositionSizer)

        calculator = StopLossCalculator(
            position_sizer=position_sizer,
            min_tolerance_pct=0.1,
            max_tolerance_pct=0.3,
            default_tolerance_pct=0.2,
            min_stop_distance_pct=0.3,
            max_stop_distance_pct=3.0,
            precision=8
        )

        assert calculator.position_sizer == position_sizer
        assert calculator.min_tolerance_pct == Decimal('0.1')
        assert calculator.max_tolerance_pct == Decimal('0.3')
        assert calculator.default_tolerance_pct == Decimal('0.2')
        assert calculator.min_stop_distance_pct == Decimal('0.3')
        assert calculator.max_stop_distance_pct == Decimal('3.0')
        assert calculator.precision == 8

    def test_initialization_with_defaults(self):
        """Test initialization uses default values correctly."""
        position_sizer = Mock(spec=PositionSizer)
        calculator = StopLossCalculator(position_sizer=position_sizer)

        assert calculator.min_tolerance_pct == Decimal('0.1')
        assert calculator.max_tolerance_pct == Decimal('0.3')
        assert calculator.default_tolerance_pct == Decimal('0.2')
        assert calculator.min_stop_distance_pct == Decimal('0.3')
        assert calculator.max_stop_distance_pct == Decimal('3.0')
        assert calculator.precision == 8

    def test_invalid_position_sizer_type(self):
        """Test initialization fails with invalid position_sizer type."""
        with pytest.raises(ValueError, match="position_sizer must be a PositionSizer instance"):
            StopLossCalculator(position_sizer="invalid")

    def test_invalid_tolerance_range(self):
        """Test initialization fails with invalid tolerance range."""
        position_sizer = Mock(spec=PositionSizer)

        # min_tolerance >= max_tolerance
        with pytest.raises(ValueError, match="min_tolerance_pct must be less than max_tolerance_pct"):
            StopLossCalculator(
                position_sizer=position_sizer,
                min_tolerance_pct=0.3,
                max_tolerance_pct=0.1
            )

    def test_invalid_default_tolerance(self):
        """Test initialization fails with default_tolerance outside range."""
        position_sizer = Mock(spec=PositionSizer)

        with pytest.raises(ValueError, match="default_tolerance_pct must be between"):
            StopLossCalculator(
                position_sizer=position_sizer,
                min_tolerance_pct=0.1,
                max_tolerance_pct=0.3,
                default_tolerance_pct=0.5  # Outside range
            )

    def test_invalid_stop_distance_range(self):
        """Test initialization fails with invalid stop distance range."""
        position_sizer = Mock(spec=PositionSizer)

        with pytest.raises(ValueError, match="min_stop_distance_pct must be less than max_stop_distance_pct"):
            StopLossCalculator(
                position_sizer=position_sizer,
                min_stop_distance_pct=3.0,
                max_stop_distance_pct=0.3
            )

    def test_invalid_precision(self):
        """Test initialization fails with negative precision."""
        position_sizer = Mock(spec=PositionSizer)

        with pytest.raises(ValueError, match="precision must be non-negative"):
            StopLossCalculator(position_sizer=position_sizer, precision=-1)


class TestStructuralLevelDetection:
    """Test structural level detection methods."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator instance for testing."""
        position_sizer = Mock(spec=PositionSizer)
        return StopLossCalculator(position_sizer=position_sizer)

    @pytest.fixture
    def sample_order_blocks(self):
        """Create sample Order Blocks for testing."""
        return [
            OrderBlock(
                type=OrderBlockType.BULLISH,
                high=50100.0,
                low=50000.0,
                origin_timestamp=1000,
                origin_candle_index=10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=0.8,
                volume=1000000.0,
                state=OrderBlockState.ACTIVE
            ),
            OrderBlock(
                type=OrderBlockType.BEARISH,
                high=50500.0,
                low=50400.0,
                origin_timestamp=2000,
                origin_candle_index=20,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=0.7,
                volume=900000.0,
                state=OrderBlockState.ACTIVE
            ),
        ]

    @pytest.fixture
    def sample_fvgs(self):
        """Create sample Fair Value Gaps for testing."""
        return [
            FairValueGap(
                type=FVGType.BULLISH,
                high=49900.0,
                low=49800.0,
                origin_timestamp=1500,
                origin_candle_index=15,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                size_pips=100.0,
                size_percentage=0.2,
                volume=800000.0,
                state=FVGState.ACTIVE
            ),
            FairValueGap(
                type=FVGType.BEARISH,
                high=50600.0,
                low=50500.0,
                origin_timestamp=2500,
                origin_candle_index=25,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                size_pips=100.0,
                size_percentage=0.2,
                volume=850000.0,
                state=FVGState.ACTIVE
            ),
        ]

    @pytest.fixture
    def sample_liquidity_levels(self):
        """Create sample Liquidity Levels for testing."""
        return [
            LiquidityLevel(
                type=LiquidityType.SELL_SIDE,
                price=49700.0,
                strength=0.85,
                touch_count=3,
                state=LiquidityState.ACTIVE,
                first_detected_timestamp=1000,
                last_tested_timestamp=2000,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15
            ),
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=50700.0,
                strength=0.9,
                touch_count=4,
                state=LiquidityState.ACTIVE,
                first_detected_timestamp=1500,
                last_tested_timestamp=2500,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15
            ),
        ]

    def test_find_nearest_order_block_long_position(self, calculator, sample_order_blocks):
        """Test finding nearest Order Block for LONG position."""
        entry_price = 50200.0

        ob = calculator._find_nearest_order_block(
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            order_blocks=sample_order_blocks
        )

        assert ob is not None
        assert ob.type == OrderBlockType.BULLISH
        assert ob.high == 50100.0  # Below entry
        assert ob.state == OrderBlockState.ACTIVE

    def test_find_nearest_order_block_short_position(self, calculator, sample_order_blocks):
        """Test finding nearest Order Block for SHORT position."""
        entry_price = 50300.0

        ob = calculator._find_nearest_order_block(
            entry_price=entry_price,
            position_side=PositionSide.SHORT,
            order_blocks=sample_order_blocks
        )

        assert ob is not None
        assert ob.type == OrderBlockType.BEARISH
        assert ob.low == 50400.0  # Above entry
        assert ob.state == OrderBlockState.ACTIVE

    def test_find_nearest_order_block_none_available(self, calculator, sample_order_blocks):
        """Test finding Order Block when none are suitable."""
        entry_price = 49000.0  # Below all Order Blocks

        ob = calculator._find_nearest_order_block(
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            order_blocks=sample_order_blocks
        )

        assert ob is None

    def test_find_nearest_fvg_long_position(self, calculator, sample_fvgs):
        """Test finding nearest FVG for LONG position."""
        entry_price = 50200.0

        fvg = calculator._find_nearest_fvg(
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            fvgs=sample_fvgs
        )

        assert fvg is not None
        assert fvg.type == FVGType.BULLISH
        assert fvg.high == 49900.0  # Below entry
        assert fvg.state == FVGState.ACTIVE

    def test_find_nearest_fvg_short_position(self, calculator, sample_fvgs):
        """Test finding nearest FVG for SHORT position."""
        entry_price = 50300.0

        fvg = calculator._find_nearest_fvg(
            entry_price=entry_price,
            position_side=PositionSide.SHORT,
            fvgs=sample_fvgs
        )

        assert fvg is not None
        assert fvg.type == FVGType.BEARISH
        assert fvg.low == 50500.0  # Above entry
        assert fvg.state == FVGState.ACTIVE

    def test_find_nearest_liquidity_level_long_position(self, calculator, sample_liquidity_levels):
        """Test finding nearest liquidity level for LONG position."""
        entry_price = 50200.0

        level = calculator._find_nearest_liquidity_level(
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            liquidity_levels=sample_liquidity_levels
        )

        assert level is not None
        assert level.type == LiquidityType.SELL_SIDE
        assert level.price == 49700.0  # Below entry
        assert level.state == LiquidityState.ACTIVE

    def test_find_nearest_liquidity_level_short_position(self, calculator, sample_liquidity_levels):
        """Test finding nearest liquidity level for SHORT position."""
        entry_price = 50300.0

        level = calculator._find_nearest_liquidity_level(
            entry_price=entry_price,
            position_side=PositionSide.SHORT,
            liquidity_levels=sample_liquidity_levels
        )

        assert level is not None
        assert level.type == LiquidityType.BUY_SIDE
        assert level.price == 50700.0  # Above entry
        assert level.state == LiquidityState.ACTIVE


class TestToleranceApplication:
    """Test tolerance application logic."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator instance for testing."""
        position_sizer = Mock(spec=PositionSizer)
        return StopLossCalculator(
            position_sizer=position_sizer,
            min_tolerance_pct=0.1,
            max_tolerance_pct=0.3,
            default_tolerance_pct=0.2
        )

    def test_apply_tolerance_long_position_default(self, calculator):
        """Test applying default tolerance for LONG position."""
        structural_level = 50000.0
        entry_price = 50200.0

        stop_price = calculator._apply_tolerance(
            structural_level=structural_level,
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            tolerance_pct=None  # Use default
        )

        # For LONG, stop should be below structural level
        # 50000 - (0.2% of 50000) = 50000 - 100 = 49900
        assert stop_price == pytest.approx(49900.0, rel=1e-6)

    def test_apply_tolerance_short_position_default(self, calculator):
        """Test applying default tolerance for SHORT position."""
        structural_level = 50500.0
        entry_price = 50300.0

        stop_price = calculator._apply_tolerance(
            structural_level=structural_level,
            entry_price=entry_price,
            position_side=PositionSide.SHORT,
            tolerance_pct=None  # Use default
        )

        # For SHORT, stop should be above structural level
        # 50500 + (0.2% of 50500) = 50500 + 101 = 50601
        assert stop_price == pytest.approx(50601.0, rel=1e-6)

    def test_apply_tolerance_custom_value(self, calculator):
        """Test applying custom tolerance value."""
        structural_level = 50000.0
        entry_price = 50200.0

        stop_price = calculator._apply_tolerance(
            structural_level=structural_level,
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            tolerance_pct=0.15  # Custom 0.15%
        )

        # 50000 - (0.15% of 50000) = 50000 - 75 = 49925
        assert stop_price == pytest.approx(49925.0, rel=1e-6)

    def test_apply_tolerance_invalid_value(self, calculator):
        """Test applying tolerance with invalid value raises error."""
        structural_level = 50000.0
        entry_price = 50200.0

        with pytest.raises(StopLossCalculationError, match="Tolerance percentage must be between"):
            calculator._apply_tolerance(
                structural_level=structural_level,
                entry_price=entry_price,
                position_side=PositionSide.LONG,
                tolerance_pct=0.5  # Outside valid range
            )


class TestStopDistanceValidation:
    """Test stop distance validation logic."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator instance for testing."""
        position_sizer = Mock(spec=PositionSizer)
        return StopLossCalculator(
            position_sizer=position_sizer,
            min_stop_distance_pct=0.3,
            max_stop_distance_pct=3.0
        )

    def test_validate_stop_distance_within_range(self, calculator):
        """Test validation passes when stop distance is within range."""
        entry_price = 50000.0
        stop_price = 49500.0  # 1% distance

        calculator._validate_stop_distance(
            entry_price=entry_price,
            stop_price=stop_price,
            position_side=PositionSide.LONG
        )
        # Should not raise exception

    def test_validate_stop_distance_too_tight(self, calculator):
        """Test validation fails when stop distance is too tight."""
        entry_price = 50000.0
        stop_price = 49950.0  # 0.1% distance - too tight

        with pytest.raises(StopLossCalculationError, match="Stop loss distance too tight"):
            calculator._validate_stop_distance(
                entry_price=entry_price,
                stop_price=stop_price,
                position_side=PositionSide.LONG
            )

    def test_validate_stop_distance_too_wide(self, calculator):
        """Test validation fails when stop distance is too wide."""
        entry_price = 50000.0
        stop_price = 48000.0  # 4% distance - too wide

        with pytest.raises(StopLossCalculationError, match="Stop loss distance too wide"):
            calculator._validate_stop_distance(
                entry_price=entry_price,
                stop_price=stop_price,
                position_side=PositionSide.LONG
            )

    def test_validate_stop_distance_short_position(self, calculator):
        """Test validation for SHORT position."""
        entry_price = 50000.0
        stop_price = 50500.0  # 1% distance

        calculator._validate_stop_distance(
            entry_price=entry_price,
            stop_price=stop_price,
            position_side=PositionSide.SHORT
        )
        # Should not raise exception

    def test_validate_stop_wrong_direction_long(self, calculator):
        """Test validation fails when stop is on wrong side for LONG."""
        entry_price = 50000.0
        stop_price = 50500.0  # Above entry for LONG - wrong direction

        with pytest.raises(StopLossCalculationError, match="Stop loss on wrong side"):
            calculator._validate_stop_distance(
                entry_price=entry_price,
                stop_price=stop_price,
                position_side=PositionSide.LONG
            )

    def test_validate_stop_wrong_direction_short(self, calculator):
        """Test validation fails when stop is on wrong side for SHORT."""
        entry_price = 50000.0
        stop_price = 49500.0  # Below entry for SHORT - wrong direction

        with pytest.raises(StopLossCalculationError, match="Stop loss on wrong side"):
            calculator._validate_stop_distance(
                entry_price=entry_price,
                stop_price=stop_price,
                position_side=PositionSide.SHORT
            )


class TestPositionSizeRecalculation:
    """Test position size recalculation based on stop distance."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator instance with mocked position sizer."""
        position_sizer = Mock(spec=PositionSizer)
        position_sizer.calculate_position_size = AsyncMock(return_value={
            'balance': 10000.0,
            'risk_amount': 200.0,  # 2% of 10000
            'position_size': 1000.0,  # With 5x leverage
            'leverage': 5,
            'risk_percentage': 2.0
        })
        return StopLossCalculator(position_sizer=position_sizer)

    @pytest.mark.asyncio
    async def test_recalculate_position_size_long(self, calculator):
        """Test position size recalculation for LONG position."""
        entry_price = 50000.0
        stop_price = 49500.0  # 1% distance

        result = await calculator.calculate_position_size_for_stop(
            entry_price=entry_price,
            stop_price=stop_price,
            position_side=PositionSide.LONG
        )

        assert 'position_size_usdt' in result
        assert 'quantity' in result
        assert 'risk_amount' in result
        assert 'stop_distance_pct' in result
        assert result['stop_distance_pct'] == pytest.approx(1.0, rel=1e-6)

    @pytest.mark.asyncio
    async def test_recalculate_position_size_short(self, calculator):
        """Test position size recalculation for SHORT position."""
        entry_price = 50000.0
        stop_price = 50500.0  # 1% distance

        result = await calculator.calculate_position_size_for_stop(
            entry_price=entry_price,
            stop_price=stop_price,
            position_side=PositionSide.SHORT
        )

        assert 'position_size_usdt' in result
        assert 'quantity' in result
        assert result['stop_distance_pct'] == pytest.approx(1.0, rel=1e-6)


class TestStopLossCalculation:
    """Test complete stop loss calculation with different strategies."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator instance with mocked position sizer."""
        position_sizer = Mock(spec=PositionSizer)
        position_sizer.calculate_position_size = AsyncMock(return_value={
            'balance': 10000.0,
            'risk_amount': 200.0,
            'position_size': 1000.0,
            'leverage': 5,
            'risk_percentage': 2.0
        })
        return StopLossCalculator(position_sizer=position_sizer)

    @pytest.fixture
    def sample_order_blocks(self):
        """Create sample Order Blocks."""
        return [
            OrderBlock(
                type=OrderBlockType.BULLISH,
                high=49900.0,
                low=49800.0,
                origin_timestamp=1000,
                origin_candle_index=10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=0.8,
                volume=1000000.0,
                state=OrderBlockState.ACTIVE
            ),
        ]

    @pytest.fixture
    def sample_fvgs(self):
        """Create sample FVGs."""
        return [
            FairValueGap(
                type=FVGType.BULLISH,
                high=49700.0,
                low=49600.0,
                origin_timestamp=1500,
                origin_candle_index=15,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                size_pips=100.0,
                size_percentage=0.2,
                volume=800000.0,
                state=FVGState.ACTIVE
            ),
        ]

    @pytest.mark.asyncio
    async def test_calculate_stop_loss_order_block_strategy(
        self, calculator, sample_order_blocks
    ):
        """Test stop loss calculation using ORDER_BLOCK strategy."""
        entry_price = 50000.0

        result = await calculator.calculate_stop_loss(
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            order_blocks=sample_order_blocks,
            strategy=StopLossStrategy.ORDER_BLOCK
        )

        assert result['strategy_used'] == StopLossStrategy.ORDER_BLOCK.value
        assert 'stop_loss_price' in result
        assert 'structural_level' in result
        assert result['structural_level']['type'] == 'order_block'
        assert result['position_size_adjusted'] is not None

    @pytest.mark.asyncio
    async def test_calculate_stop_loss_fvg_strategy(self, calculator, sample_fvgs):
        """Test stop loss calculation using FAIR_VALUE_GAP strategy."""
        entry_price = 50000.0

        result = await calculator.calculate_stop_loss(
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            fvgs=sample_fvgs,
            strategy=StopLossStrategy.FAIR_VALUE_GAP
        )

        assert result['strategy_used'] == StopLossStrategy.FAIR_VALUE_GAP.value
        assert result['structural_level']['type'] == 'fair_value_gap'

    @pytest.mark.asyncio
    async def test_calculate_stop_loss_auto_strategy(
        self, calculator, sample_order_blocks, sample_fvgs
    ):
        """Test stop loss calculation using AUTO strategy."""
        entry_price = 50000.0

        result = await calculator.calculate_stop_loss(
            entry_price=entry_price,
            position_side=PositionSide.LONG,
            order_blocks=sample_order_blocks,
            fvgs=sample_fvgs,
            strategy=StopLossStrategy.AUTO
        )

        # AUTO should prioritize ORDER_BLOCK when available
        assert result['strategy_used'] == StopLossStrategy.ORDER_BLOCK.value
        assert 'stop_loss_price' in result

    @pytest.mark.asyncio
    async def test_calculate_stop_loss_no_structural_levels(self, calculator):
        """Test calculation fails when no structural levels are provided."""
        entry_price = 50000.0

        with pytest.raises(StopLossCalculationError, match="No structural levels provided"):
            await calculator.calculate_stop_loss(
                entry_price=entry_price,
                position_side=PositionSide.LONG,
                strategy=StopLossStrategy.ORDER_BLOCK
            )

    @pytest.mark.asyncio
    async def test_calculate_stop_loss_invalid_entry_price(self, calculator):
        """Test calculation fails with invalid entry price."""
        with pytest.raises(ValueError, match="entry_price must be positive"):
            await calculator.calculate_stop_loss(
                entry_price=-50000.0,
                position_side=PositionSide.LONG,
                order_blocks=[]
            )


class TestParameterManagement:
    """Test parameter update and retrieval methods."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator instance."""
        position_sizer = Mock(spec=PositionSizer)
        return StopLossCalculator(position_sizer=position_sizer)

    def test_get_parameters(self, calculator):
        """Test getting current parameters."""
        params = calculator.get_parameters()

        assert 'min_tolerance_pct' in params
        assert 'max_tolerance_pct' in params
        assert 'default_tolerance_pct' in params
        assert 'min_stop_distance_pct' in params
        assert 'max_stop_distance_pct' in params
        assert 'precision' in params

    def test_update_parameters_tolerance(self, calculator):
        """Test updating tolerance parameters."""
        calculator.update_parameters(
            min_tolerance_pct=0.15,
            max_tolerance_pct=0.35,
            default_tolerance_pct=0.25
        )

        assert calculator.min_tolerance_pct == Decimal('0.15')
        assert calculator.max_tolerance_pct == Decimal('0.35')
        assert calculator.default_tolerance_pct == Decimal('0.25')

    def test_update_parameters_stop_distance(self, calculator):
        """Test updating stop distance parameters."""
        calculator.update_parameters(
            min_stop_distance_pct=0.5,
            max_stop_distance_pct=5.0
        )

        assert calculator.min_stop_distance_pct == Decimal('0.5')
        assert calculator.max_stop_distance_pct == Decimal('5.0')

    def test_update_parameters_invalid_tolerance_range(self, calculator):
        """Test updating with invalid tolerance range fails."""
        with pytest.raises(ValueError, match="min_tolerance_pct must be less than max_tolerance_pct"):
            calculator.update_parameters(
                min_tolerance_pct=0.3,
                max_tolerance_pct=0.1
            )

    def test_update_parameters_invalid_default_tolerance(self, calculator):
        """Test updating with invalid default tolerance fails."""
        # First set valid range
        calculator.update_parameters(
            min_tolerance_pct=0.1,
            max_tolerance_pct=0.3
        )

        # Then try to set default outside range
        with pytest.raises(ValueError, match="default_tolerance_pct must be between"):
            calculator.update_parameters(default_tolerance_pct=0.5)
