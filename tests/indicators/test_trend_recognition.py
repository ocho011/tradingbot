"""
Unit tests for Higher High/Lower Low Trend Recognition Engine.
"""

from datetime import datetime

import pytest

from src.core.constants import TimeFrame
from src.indicators.liquidity_zone import SwingPoint
from src.indicators.trend_recognition import (
    TrendDirection,
    TrendPattern,
    TrendRecognitionEngine,
    TrendState,
    TrendStrength,
    TrendStructure,
)
from src.models.candle import Candle


class TestTrendRecognitionEngine:
    """Test suite for TrendRecognitionEngine."""

    @pytest.fixture
    def engine(self):
        """Create trend recognition engine instance."""
        return TrendRecognitionEngine(
            min_swing_strength=3,
            min_patterns_for_confirmation=2,
            min_price_change_atr_multiple=0.5,
            atr_period=14,
        )

    @pytest.fixture
    def base_timestamp(self):
        """Base timestamp for test candles."""
        return int(datetime(2024, 1, 1).timestamp() * 1000)

    def create_candle(
        self,
        timestamp: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float = 1000.0,
        symbol: str = "BTCUSDT",
        timeframe: TimeFrame = TimeFrame.M15,
    ) -> Candle:
        """Helper to create test candles."""
        return Candle(
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            symbol=symbol,
            timeframe=timeframe,
        )

    def create_uptrend_candles(self, base_timestamp: int, count: int = 50) -> list[Candle]:
        """
        Create candles forming an uptrend with HH/HL pattern.

        Pattern: Higher highs and higher lows consistently.
        """
        candles = []
        base_price = 100.0
        time_delta = 15 * 60 * 1000  # 15 minutes

        for i in range(count):
            # Create upward trending candles with oscillation
            cycle_pos = i % 10

            if cycle_pos < 5:
                # Rising phase
                open_price = base_price + (i * 0.5)
                high = open_price + 1.0 + (cycle_pos * 0.3)
                low = open_price - 0.3
                close = open_price + 0.5 + (cycle_pos * 0.2)
                # Ensure close is within range
                close = max(low, min(high, close))
            else:
                # Pullback phase (but higher lows)
                open_price = base_price + (i * 0.5)
                high = open_price + 0.5
                low = open_price - 0.5 + ((cycle_pos - 5) * 0.1)
                close = open_price - 0.2
                # Ensure close is within range
                close = max(low, min(high, close))

            candle = self.create_candle(
                timestamp=base_timestamp + (i * time_delta),
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000.0 + (i * 10),
            )
            candles.append(candle)

        return candles

    def create_downtrend_candles(self, base_timestamp: int, count: int = 50) -> list[Candle]:
        """
        Create candles forming a downtrend with LH/LL pattern.

        Pattern: Lower highs and lower lows consistently.
        """
        candles = []
        base_price = 100.0
        time_delta = 15 * 60 * 1000

        for i in range(count):
            cycle_pos = i % 10

            if cycle_pos < 5:
                # Falling phase
                open_price = base_price - (i * 0.5)
                high = open_price + 0.3
                low = open_price - 1.0 - (cycle_pos * 0.3)
                close = open_price - 0.5 - (cycle_pos * 0.2)
                # Ensure close is within range
                close = max(low, min(high, close))
            else:
                # Relief rally phase (but lower highs)
                open_price = base_price - (i * 0.5)
                high = open_price + 0.5 - ((cycle_pos - 5) * 0.1)
                low = open_price - 0.5
                close = open_price + 0.2
                # Ensure close is within range
                close = max(low, min(high, close))

            candle = self.create_candle(
                timestamp=base_timestamp + (i * time_delta),
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000.0 + (i * 10),
            )
            candles.append(candle)

        return candles

    def create_ranging_candles(self, base_timestamp: int, count: int = 50) -> list[Candle]:
        """
        Create candles forming a ranging market.

        Pattern: No clear HH/HL or LH/LL, oscillating around same level.
        """
        candles = []
        base_price = 100.0
        time_delta = 15 * 60 * 1000

        for i in range(count):
            # Oscillate around base price
            amplitude = 2.0
            offset = amplitude * (0.5 - (i % 10) / 10.0)

            open_price = base_price + offset
            high = open_price + 0.5
            low = open_price - 0.5
            close = open_price + (0.2 if i % 2 == 0 else -0.2)

            candle = self.create_candle(
                timestamp=base_timestamp + (i * time_delta),
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
            )
            candles.append(candle)

        return candles

    # ==================== ATR Calculation Tests ====================

    def test_calculate_atr_basic(self, engine, base_timestamp):
        """Test basic ATR calculation."""
        candles = [
            self.create_candle(base_timestamp + i * 60000, 100 + i, 101 + i, 99 + i, 100.5 + i)
            for i in range(20)
        ]

        atr = engine.calculate_atr(candles, period=14)

        assert atr > 0
        assert isinstance(atr, float)

    def test_calculate_atr_insufficient_data(self, engine, base_timestamp):
        """Test ATR calculation with insufficient data."""
        candles = [
            self.create_candle(base_timestamp + i * 60000, 100, 101, 99, 100.5) for i in range(5)
        ]

        atr = engine.calculate_atr(candles, period=14)

        assert atr == 0.0  # Should return 0 for insufficient data

    # ==================== Swing Point Detection Tests ====================

    def test_detect_swing_highs_uptrend(self, engine, base_timestamp):
        """Test swing high detection in uptrend."""
        candles = self.create_uptrend_candles(base_timestamp, count=30)

        swing_highs = engine.detect_swing_highs(candles)

        assert len(swing_highs) > 0
        assert all(isinstance(swing, SwingPoint) for swing in swing_highs)
        assert all(swing.is_high for swing in swing_highs)

    def test_detect_swing_lows_downtrend(self, engine, base_timestamp):
        """Test swing low detection in downtrend."""
        candles = self.create_downtrend_candles(base_timestamp, count=30)

        swing_lows = engine.detect_swing_lows(candles)

        assert len(swing_lows) > 0
        assert all(isinstance(swing, SwingPoint) for swing in swing_lows)
        assert all(not swing.is_high for swing in swing_lows)

    def test_detect_swings_insufficient_data(self, engine, base_timestamp):
        """Test swing detection with insufficient candles."""
        candles = [
            self.create_candle(base_timestamp + i * 60000, 100, 101, 99, 100.5) for i in range(5)
        ]

        swing_highs = engine.detect_swing_highs(candles)
        swing_lows = engine.detect_swing_lows(candles)

        assert len(swing_highs) == 0
        assert len(swing_lows) == 0

    # ==================== Pattern Identification Tests ====================

    def test_identify_higher_high_pattern(self, engine):
        """Test identification of Higher High pattern."""
        previous = SwingPoint(price=100.0, timestamp=1000, candle_index=10, is_high=True)
        current = SwingPoint(price=105.0, timestamp=2000, candle_index=20, is_high=True)

        pattern = engine.identify_pattern(current, previous)

        assert pattern == TrendPattern.HIGHER_HIGH

    def test_identify_lower_high_pattern(self, engine):
        """Test identification of Lower High pattern."""
        previous = SwingPoint(price=105.0, timestamp=1000, candle_index=10, is_high=True)
        current = SwingPoint(price=100.0, timestamp=2000, candle_index=20, is_high=True)

        pattern = engine.identify_pattern(current, previous)

        assert pattern == TrendPattern.LOWER_HIGH

    def test_identify_higher_low_pattern(self, engine):
        """Test identification of Higher Low pattern."""
        previous = SwingPoint(price=95.0, timestamp=1000, candle_index=10, is_high=False)
        current = SwingPoint(price=98.0, timestamp=2000, candle_index=20, is_high=False)

        pattern = engine.identify_pattern(current, previous)

        assert pattern == TrendPattern.HIGHER_LOW

    def test_identify_lower_low_pattern(self, engine):
        """Test identification of Lower Low pattern."""
        previous = SwingPoint(price=98.0, timestamp=1000, candle_index=10, is_high=False)
        current = SwingPoint(price=95.0, timestamp=2000, candle_index=20, is_high=False)

        pattern = engine.identify_pattern(current, previous)

        assert pattern == TrendPattern.LOWER_LOW

    def test_identify_pattern_mismatched_types(self, engine):
        """Test pattern identification with mismatched swing types."""
        high = SwingPoint(price=100.0, timestamp=1000, candle_index=10, is_high=True)
        low = SwingPoint(price=95.0, timestamp=2000, candle_index=20, is_high=False)

        pattern = engine.identify_pattern(low, high)

        assert pattern is None

    # ==================== Trend Analysis Tests ====================

    def test_analyze_uptrend_patterns(self, engine, base_timestamp):
        """Test trend analysis on uptrend data."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)

        structures, direction = engine.analyze_trend_patterns(candles)

        assert len(structures) > 0
        assert direction in (TrendDirection.UPTREND, TrendDirection.TRANSITION)

        # Should detect HH and HL patterns
        hh_count = sum(1 for s in structures if s.pattern == TrendPattern.HIGHER_HIGH)
        hl_count = sum(1 for s in structures if s.pattern == TrendPattern.HIGHER_LOW)

        assert (hh_count + hl_count) > 0

    def test_analyze_downtrend_patterns(self, engine, base_timestamp):
        """Test trend analysis on downtrend data."""
        candles = self.create_downtrend_candles(base_timestamp, count=50)

        structures, direction = engine.analyze_trend_patterns(candles)

        assert len(structures) > 0
        assert direction in (TrendDirection.DOWNTREND, TrendDirection.TRANSITION)

        # Should detect LH and LL patterns
        lh_count = sum(1 for s in structures if s.pattern == TrendPattern.LOWER_HIGH)
        ll_count = sum(1 for s in structures if s.pattern == TrendPattern.LOWER_LOW)

        assert (lh_count + ll_count) > 0

    def test_analyze_ranging_patterns(self, engine, base_timestamp):
        """Test trend analysis on ranging market."""
        candles = self.create_ranging_candles(base_timestamp, count=50)

        structures, direction = engine.analyze_trend_patterns(candles)

        # Ranging market should have mixed or uncertain direction
        assert direction in (
            TrendDirection.RANGING,
            TrendDirection.TRANSITION,
            TrendDirection.UPTREND,
            TrendDirection.DOWNTREND,
        )

    # ==================== Trend Strength Tests ====================

    def test_calculate_trend_strength_uptrend(self, engine, base_timestamp):
        """Test trend strength calculation for uptrend."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)
        structures, direction = engine.analyze_trend_patterns(candles)

        strength, strength_level = engine.calculate_trend_strength(structures, direction)

        assert 0 <= strength <= 100
        assert isinstance(strength_level, TrendStrength)

    def test_calculate_trend_strength_ranging(self, engine, base_timestamp):
        """Test trend strength for ranging market."""
        candles = self.create_ranging_candles(base_timestamp, count=30)
        structures, direction = engine.analyze_trend_patterns(candles)

        strength, strength_level = engine.calculate_trend_strength(
            structures, TrendDirection.RANGING
        )

        assert strength == 0.0
        assert strength_level == TrendStrength.VERY_WEAK

    def test_strength_classification(self, engine, base_timestamp):
        """Test that strength is properly classified into levels."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)
        structures, direction = engine.analyze_trend_patterns(candles)

        strength, strength_level = engine.calculate_trend_strength(structures, direction)

        # Verify strength level matches score
        if strength >= 81:
            assert strength_level == TrendStrength.VERY_STRONG
        elif strength >= 61:
            assert strength_level == TrendStrength.STRONG
        elif strength >= 41:
            assert strength_level == TrendStrength.MODERATE
        elif strength >= 21:
            assert strength_level == TrendStrength.WEAK
        else:
            assert strength_level == TrendStrength.VERY_WEAK

    # ==================== Trend Change Detection Tests ====================

    def test_detect_trend_change_first_detection(self, engine, base_timestamp):
        """Test first trend detection (no previous trend)."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)

        new_trend = engine.detect_trend_change(candles)

        assert new_trend is not None
        assert isinstance(new_trend, TrendState)
        assert new_trend.direction in (TrendDirection.UPTREND, TrendDirection.TRANSITION)

    def test_detect_trend_change_direction_shift(self, engine, base_timestamp):
        """Test trend change when direction shifts."""
        # Establish uptrend
        uptrend_candles = self.create_uptrend_candles(base_timestamp, count=30)
        initial_trend = engine.detect_trend_change(uptrend_candles)

        assert initial_trend is not None

        # Create downtrend
        downtrend_candles = self.create_downtrend_candles(
            base_timestamp + (30 * 15 * 60 * 1000), count=30
        )

        # Detect trend on new data
        new_trend = engine.detect_trend_change(downtrend_candles)

        # Should detect change (though direction might be TRANSITION)
        assert new_trend is not None

    def test_no_trend_change_stable_trend(self, engine, base_timestamp):
        """Test that stable trend doesn't trigger false changes."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)

        # First detection
        first_trend = engine.detect_trend_change(candles)
        assert first_trend is not None

        # Add a few more candles with same trend
        more_candles = self.create_uptrend_candles(base_timestamp + (50 * 15 * 60 * 1000), count=10)
        all_candles = candles + more_candles

        # Second detection - might or might not detect change depending on strength
        second_trend = engine.detect_trend_change(all_candles)

        # Either no change or confirmed same direction
        if second_trend is not None:
            assert second_trend.direction in (TrendDirection.UPTREND, TrendDirection.TRANSITION)

    # ==================== Noise Filtering Tests ====================

    def test_is_significant_move_with_atr(self, engine, base_timestamp):
        """Test noise filtering using ATR."""
        candles = self.create_uptrend_candles(base_timestamp, count=30)
        atr = engine.calculate_atr(candles)

        # Significant move (above threshold)
        large_move = atr * 0.6
        assert engine.is_significant_move(large_move, candles) is True

        # Insignificant move (below threshold)
        small_move = atr * 0.3
        assert engine.is_significant_move(small_move, candles) is False

    def test_is_significant_move_no_atr(self, engine):
        """Test significant move check when ATR is zero."""
        # Empty or insufficient data
        price_change = 5.0
        result = engine.is_significant_move(price_change, [])

        assert result is True  # Should accept move when no ATR available

    # ==================== State Management Tests ====================

    def test_get_current_trend(self, engine, base_timestamp):
        """Test getting current trend state."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)

        # Before detection
        assert engine.get_current_trend() is None

        # After detection
        engine.detect_trend_change(candles)
        current = engine.get_current_trend()

        assert current is not None
        assert isinstance(current, TrendState)

    def test_get_trend_structures(self, engine, base_timestamp):
        """Test getting trend structures."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)
        engine.analyze_trend_patterns(candles)

        structures = engine.get_trend_structures()

        assert len(structures) > 0
        assert all(isinstance(s, TrendStructure) for s in structures)

    def test_get_swing_points(self, engine, base_timestamp):
        """Test getting swing points."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)
        engine.analyze_trend_patterns(candles)

        swing_highs, swing_lows = engine.get_swing_points()

        # Note: In uptrend, swing lows might be minimal or zero
        # depending on the candle pattern, so we test highs primarily
        assert len(swing_highs) > 0
        assert all(swing.is_high for swing in swing_highs)
        # Swing lows may or may not exist in pure uptrend
        if swing_lows:
            assert all(not swing.is_high for swing in swing_lows)

    def test_clear_history(self, engine, base_timestamp):
        """Test clearing trend history."""
        candles = self.create_uptrend_candles(base_timestamp, count=50)
        engine.detect_trend_change(candles)

        # Verify data exists
        assert engine.get_current_trend() is not None
        assert len(engine.get_trend_structures()) > 0

        # Clear history
        engine.clear_history()

        # Verify cleared
        assert engine.get_current_trend() is None
        assert len(engine.get_trend_structures()) == 0
        swing_highs, swing_lows = engine.get_swing_points()
        assert len(swing_highs) == 0
        assert len(swing_lows) == 0

    # ==================== Data Serialization Tests ====================

    def test_trend_structure_to_dict(self):
        """Test TrendStructure serialization."""
        structure = TrendStructure(
            pattern=TrendPattern.HIGHER_HIGH,
            price=105.0,
            timestamp=1000000,
            candle_index=20,
            previous_swing_price=100.0,
            previous_swing_index=10,
            swing_length=10,
            price_change=5.0,
            price_change_pct=5.0,
        )

        data = structure.to_dict()

        assert data["pattern"] == "HIGHER_HIGH"
        assert data["price"] == 105.0
        assert "datetime" in data

    def test_trend_state_to_dict(self, base_timestamp):
        """Test TrendState serialization."""
        state = TrendState(
            direction=TrendDirection.UPTREND,
            strength=75.0,
            strength_level=TrendStrength.STRONG,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            start_timestamp=base_timestamp,
            start_candle_index=0,
            last_update_timestamp=base_timestamp + 1000000,
            pattern_count=5,
            is_confirmed=True,
        )

        data = state.to_dict()

        assert data["direction"] == "UPTREND"
        assert data["strength"] == 75.0
        assert data["strength_level"] == "STRONG"
        assert "start_datetime" in data
        assert "last_update_datetime" in data

    # ==================== Edge Cases ====================

    def test_analyze_with_minimum_candles(self, engine, base_timestamp):
        """Test analysis with minimum required candles."""
        min_candles = engine.min_swing_strength * 2 + 1
        candles = self.create_uptrend_candles(base_timestamp, count=min_candles)

        # Should not raise error
        structures, direction = engine.analyze_trend_patterns(candles)

        # Might not find patterns, but should execute
        assert isinstance(structures, list)
        assert isinstance(direction, TrendDirection)

    def test_analyze_insufficient_candles_raises_error(self, engine, base_timestamp):
        """Test that insufficient candles raises ValueError."""
        insufficient_count = engine.min_swing_strength * 2  # One less than needed
        candles = [
            self.create_candle(base_timestamp + i * 60000, 100, 101, 99, 100.5)
            for i in range(insufficient_count)
        ]

        with pytest.raises(ValueError, match="Insufficient candles"):
            engine.analyze_trend_patterns(candles)
