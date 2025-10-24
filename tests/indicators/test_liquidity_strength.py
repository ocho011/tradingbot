"""
Unit tests for Liquidity Strength calculation and Market State tracking.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock

from src.indicators.liquidity_strength import (
    LiquidityStrengthCalculator,
    MarketStateTracker,
    LiquidityStrengthMetrics,
    LiquidityStrengthLevel,
    MarketStateData,
    MarketState
)
from src.indicators.liquidity_zone import LiquidityLevel, LiquidityType, LiquidityState, SwingPoint
from src.indicators.trend_recognition import TrendState, TrendDirection, TrendStrength
from src.indicators.market_structure_break import BreakOfMarketStructure, BMSType, BMSState
from src.models.candle import Candle
from src.core.constants import TimeFrame
from src.core.events import EventBus


@pytest.fixture
def sample_candles():
    """Create sample candles for testing."""
    candles = []
    base_time = 1609459200000  # 2021-01-01 00:00:00

    for i in range(100):
        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=base_time + (i * 900000),  # 15 min intervals
            open=50000 + i * 10,
            high=50100 + i * 10,
            low=49900 + i * 10,
            close=50050 + i * 10,
            volume=1000 + i
        ))

    return candles


@pytest.fixture
def sample_liquidity_level():
    """Create a sample liquidity level for testing."""
    return LiquidityLevel(
        type=LiquidityType.SELL_SIDE,
        price=50000.0,
        origin_timestamp=1609459200000,
        origin_candle_index=10,
        symbol="BTCUSDT",
        timeframe=TimeFrame.M15,
        touch_count=3,
        strength=6.5,
        volume_profile=5000.0,
        state=LiquidityState.ACTIVE
    )


class TestLiquidityStrengthCalculator:
    """Test cases for LiquidityStrengthCalculator."""

    def test_calculator_initialization(self):
        """Test calculator initialization with default weights."""
        calculator = LiquidityStrengthCalculator()

        assert calculator.base_weight > 0
        assert calculator.touch_weight > 0
        assert calculator.volume_weight > 0
        assert calculator.recency_weight > 0

        # Weights should sum to approximately 1.0
        total_weight = (
            calculator.base_weight +
            calculator.touch_weight +
            calculator.volume_weight +
            calculator.recency_weight
        )
        assert abs(total_weight - 1.0) < 0.01

    def test_calculator_custom_weights(self):
        """Test calculator initialization with custom weights."""
        calculator = LiquidityStrengthCalculator(
            base_weight=0.3,
            touch_weight=0.3,
            volume_weight=0.2,
            recency_weight=0.2
        )

        assert calculator.base_weight == 0.3
        assert calculator.touch_weight == 0.3
        assert calculator.volume_weight == 0.2
        assert calculator.recency_weight == 0.2

    def test_calculate_strength(self, sample_liquidity_level, sample_candles):
        """Test comprehensive strength calculation."""
        calculator = LiquidityStrengthCalculator()
        current_index = 50  # Middle of the candle list

        metrics = calculator.calculate_strength(
            sample_liquidity_level,
            sample_candles,
            current_index
        )

        # Verify metrics structure
        assert isinstance(metrics, LiquidityStrengthMetrics)
        assert metrics.level == sample_liquidity_level
        assert 0 <= metrics.base_strength <= 100
        assert 0 <= metrics.touch_strength <= 100
        assert 0 <= metrics.volume_strength <= 100
        assert 0 <= metrics.recency_strength <= 100
        assert 0 <= metrics.total_strength <= 100
        assert isinstance(metrics.strength_level, LiquidityStrengthLevel)
        assert metrics.last_calculated == sample_candles[current_index].timestamp

    def test_calculate_strength_old_level(self, sample_liquidity_level, sample_candles):
        """Test strength calculation for an old level (should have lower recency)."""
        calculator = LiquidityStrengthCalculator()

        # Test at the end of candles (level is old)
        current_index = 99

        metrics = calculator.calculate_strength(
            sample_liquidity_level,
            sample_candles,
            current_index
        )

        # Old level should have lower recency strength
        assert metrics.recency_strength < 60

    def test_calculate_strength_recent_level(self, sample_candles):
        """Test strength calculation for a recent level."""
        calculator = LiquidityStrengthCalculator()

        # Create a recent level
        recent_level = LiquidityLevel(
            type=LiquidityType.SELL_SIDE,
            price=51000.0,
            origin_timestamp=sample_candles[95].timestamp,
            origin_candle_index=95,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            touch_count=2,
            strength=7.0,
            volume_profile=6000.0,
            state=LiquidityState.ACTIVE
        )

        current_index = 99

        metrics = calculator.calculate_strength(
            recent_level,
            sample_candles,
            current_index
        )

        # Recent level should have high recency strength
        assert metrics.recency_strength > 70

    def test_calculate_all_strengths(self, sample_candles):
        """Test calculating strength for multiple levels."""
        calculator = LiquidityStrengthCalculator()

        # Create multiple levels
        levels = []
        for i in range(3):
            level = LiquidityLevel(
                type=LiquidityType.SELL_SIDE,
                price=50000.0 + i * 100,
                origin_timestamp=sample_candles[10 + i * 10].timestamp,
                origin_candle_index=10 + i * 10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                touch_count=2 + i,
                strength=6.0 + i,
                volume_profile=5000.0 + i * 1000,
                state=LiquidityState.ACTIVE
            )
            levels.append(level)

        current_index = 50

        metrics_list = calculator.calculate_all_strengths(
            levels,
            sample_candles,
            current_index
        )

        # Should get metrics for all active levels
        assert len(metrics_list) == 3

        # Each should be valid
        for metrics in metrics_list:
            assert isinstance(metrics, LiquidityStrengthMetrics)
            assert 0 <= metrics.total_strength <= 100

    def test_calculate_all_strengths_skips_filled_levels(self, sample_candles):
        """Test that filled/swept levels are skipped in batch calculation."""
        calculator = LiquidityStrengthCalculator()

        # Create levels with different states
        active_level = LiquidityLevel(
            type=LiquidityType.SELL_SIDE,
            price=50000.0,
            origin_timestamp=sample_candles[10].timestamp,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            touch_count=2,
            strength=6.0,
            volume_profile=5000.0,
            state=LiquidityState.ACTIVE
        )

        swept_level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=50100.0,
            origin_timestamp=sample_candles[20].timestamp,
            origin_candle_index=20,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            touch_count=3,
            strength=7.0,
            volume_profile=6000.0,
            state=LiquidityState.SWEPT,
            swept_timestamp=sample_candles[30].timestamp
        )

        levels = [active_level, swept_level]
        current_index = 50

        metrics_list = calculator.calculate_all_strengths(
            levels,
            sample_candles,
            current_index
        )

        # Only active level should be included
        assert len(metrics_list) == 1
        assert metrics_list[0].level == active_level


class TestMarketStateTracker:
    """Test cases for MarketStateTracker."""

    def test_tracker_initialization(self):
        """Test tracker initialization."""
        event_bus = Mock(spec=EventBus)
        tracker = MarketStateTracker(event_bus=event_bus)

        assert tracker.event_bus == event_bus
        assert tracker.min_bms_for_confirmation > 0
        assert tracker.min_trend_strength > 0
        assert tracker.min_confidence_for_state > 0
        assert tracker.get_current_state() is None
        assert tracker.get_state_history() == []

    def test_update_state_bullish_trend(self, sample_candles):
        """Test state update with bullish trend."""
        event_bus = Mock(spec=EventBus)
        tracker = MarketStateTracker(event_bus=event_bus)

        # Create bullish trend state
        trend_state = TrendState(
            direction=TrendDirection.UPTREND,
            strength=75.0,
            strength_level=TrendStrength.STRONG,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            start_timestamp=sample_candles[0].timestamp,
            start_candle_index=0,
            last_update_timestamp=sample_candles[-1].timestamp,
            pattern_count=5,
            is_confirmed=True
        )

        # Create bullish BMS
        bms_list = [
            BreakOfMarketStructure(
                bms_type=BMSType.BULLISH,
                broken_level=SwingPoint(
                    price=50400.0,
                    timestamp=sample_candles[49].timestamp,
                    candle_index=49,
                    is_high=True
                ),
                break_timestamp=sample_candles[50].timestamp,
                break_candle_index=50,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                confidence_score=80.0,
                state=BMSState.CONFIRMED
            )
        ]

        buy_side_levels = []
        sell_side_levels = []

        # First update should create new state
        state_data = tracker.update_state(
            sample_candles,
            trend_state,
            bms_list,
            buy_side_levels,
            sell_side_levels
        )

        assert state_data is not None
        assert isinstance(state_data, MarketStateData)
        assert state_data.state in [MarketState.BULLISH, MarketState.TRANSITIONING]
        assert state_data.symbol == "BTCUSDT"
        assert state_data.timeframe == TimeFrame.M15
        assert state_data.trend_direction == TrendDirection.UPTREND
        assert state_data.trend_strength == 75.0

    def test_update_state_ranging_market(self, sample_candles):
        """Test state update with ranging market."""
        event_bus = Mock(spec=EventBus)
        tracker = MarketStateTracker(
            event_bus=event_bus,
            min_confidence_for_state=20.0  # Lower threshold for ranging market
        )

        # Create ranging trend state
        trend_state = TrendState(
            direction=TrendDirection.RANGING,
            strength=30.0,
            strength_level=TrendStrength.WEAK,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            start_timestamp=sample_candles[0].timestamp,
            start_candle_index=0,
            last_update_timestamp=sample_candles[-1].timestamp,
            pattern_count=1,
            is_confirmed=True
        )

        bms_list = []
        buy_side_levels = []
        sell_side_levels = []

        state_data = tracker.update_state(
            sample_candles,
            trend_state,
            bms_list,
            buy_side_levels,
            sell_side_levels
        )

        assert state_data is not None
        assert state_data.state == MarketState.RANGING
        assert state_data.trend_direction == TrendDirection.RANGING

    def test_update_state_no_change_returns_none(self, sample_candles):
        """Test that update returns None when state doesn't change."""
        event_bus = Mock(spec=EventBus)
        tracker = MarketStateTracker(event_bus=event_bus)

        # Create initial state
        trend_state = TrendState(
            direction=TrendDirection.UPTREND,
            strength=75.0,
            strength_level=TrendStrength.STRONG,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            start_timestamp=sample_candles[0].timestamp,
            start_candle_index=0,
            last_update_timestamp=sample_candles[-1].timestamp,
            pattern_count=5,
            is_confirmed=True
        )

        bms_list = [
            BreakOfMarketStructure(
                bms_type=BMSType.BULLISH,
                broken_level=SwingPoint(
                    price=50400.0,
                    timestamp=sample_candles[49].timestamp,
                    candle_index=49,
                    is_high=True
                ),
                break_timestamp=sample_candles[50].timestamp,
                break_candle_index=50,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                confidence_score=80.0,
                state=BMSState.CONFIRMED
            )
        ]

        buy_side_levels = []
        sell_side_levels = []

        # First update creates state
        first_update = tracker.update_state(
            sample_candles,
            trend_state,
            bms_list,
            buy_side_levels,
            sell_side_levels
        )
        assert first_update is not None

        # Second update with same conditions should return None (no change)
        second_update = tracker.update_state(
            sample_candles,
            trend_state,
            bms_list,
            buy_side_levels,
            sell_side_levels
        )
        assert second_update is None

    def test_get_current_state(self, sample_candles):
        """Test getting current state."""
        event_bus = Mock(spec=EventBus)
        tracker = MarketStateTracker(
            event_bus=event_bus,
            min_confidence_for_state=20.0  # Lower threshold for ranging market
        )

        # Initially no state
        assert tracker.get_current_state() is None

        # Create and update state
        trend_state = TrendState(
            direction=TrendDirection.RANGING,
            strength=30.0,
            strength_level=TrendStrength.WEAK,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            start_timestamp=sample_candles[0].timestamp,
            start_candle_index=0,
            last_update_timestamp=sample_candles[-1].timestamp,
            pattern_count=1,
            is_confirmed=True
        )

        tracker.update_state(
            sample_candles,
            trend_state,
            [],
            [],
            []
        )

        # Now should have a state
        current_state = tracker.get_current_state()
        assert current_state is not None
        assert isinstance(current_state, MarketStateData)

    def test_get_state_history(self, sample_candles):
        """Test getting state history."""
        event_bus = Mock(spec=EventBus)
        tracker = MarketStateTracker(
            event_bus=event_bus,
            min_confidence_for_state=20.0  # Lower threshold for ranging market
        )

        # Initially empty
        assert tracker.get_state_history() == []

        # Create state
        ranging_trend = TrendState(
            direction=TrendDirection.RANGING,
            strength=30.0,
            strength_level=TrendStrength.WEAK,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            start_timestamp=sample_candles[0].timestamp,
            start_candle_index=0,
            last_update_timestamp=sample_candles[25].timestamp,
            pattern_count=1,
            is_confirmed=True
        )

        # First state change
        tracker.update_state(sample_candles[:50], ranging_trend, [], [], [])

        history = tracker.get_state_history()
        assert len(history) == 1
        assert history[0].state == MarketState.RANGING

    def test_clear_history(self, sample_candles):
        """Test clearing state history."""
        event_bus = Mock(spec=EventBus)
        tracker = MarketStateTracker(
            event_bus=event_bus,
            min_confidence_for_state=20.0  # Lower threshold for ranging market
        )

        # Create a state
        trend_state = TrendState(
            direction=TrendDirection.RANGING,
            strength=30.0,
            strength_level=TrendStrength.WEAK,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            start_timestamp=sample_candles[0].timestamp,
            start_candle_index=0,
            last_update_timestamp=sample_candles[-1].timestamp,
            pattern_count=1,
            is_confirmed=True
        )

        tracker.update_state(sample_candles, trend_state, [], [], [])

        # Verify history exists
        assert len(tracker.get_state_history()) > 0

        # Clear and verify
        tracker.clear_history()
        assert tracker.get_state_history() == []
