"""
Unit tests for Liquidity Zone detection and analysis.
"""

import pytest
from datetime import datetime, timezone

from src.indicators.liquidity_zone import (
    LiquidityLevel,
    LiquidityType,
    LiquidityState,
    LiquidityZoneDetector,
    SwingPoint
)
from src.models.candle import Candle
from src.core.constants import TimeFrame


class TestLiquidityLevel:
    """Test cases for LiquidityLevel dataclass."""

    def test_create_buy_side_liquidity_level(self):
        """Test creating a buy-side liquidity level."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=50000.0,
            origin_timestamp=1609459200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            touch_count=2,
            strength=75.0,
            volume_profile=100000.0
        )

        assert level.type == LiquidityType.BUY_SIDE
        assert level.price == 50000.0
        assert level.touch_count == 2
        assert level.strength == 75.0
        assert level.state == LiquidityState.ACTIVE

    def test_create_sell_side_liquidity_level(self):
        """Test creating a sell-side liquidity level."""
        level = LiquidityLevel(
            type=LiquidityType.SELL_SIDE,
            price=49000.0,
            origin_timestamp=1609459200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=60.0
        )

        assert level.type == LiquidityType.SELL_SIDE
        assert level.price == 49000.0
        assert level.touch_count == 0

    def test_invalid_price(self):
        """Test that invalid price raises ValueError."""
        with pytest.raises(ValueError, match="Price must be positive"):
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=-100.0,
                origin_timestamp=1609459200000,
                origin_candle_index=10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15
            )

    def test_invalid_strength(self):
        """Test that invalid strength raises ValueError."""
        with pytest.raises(ValueError, match="Strength must be between 0 and 100"):
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=50000.0,
                origin_timestamp=1609459200000,
                origin_candle_index=10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=150.0
            )

    def test_is_price_near(self):
        """Test price proximity detection."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=50000.0,
            origin_timestamp=1609459200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15
        )

        # Within tolerance (2 pips default with pip_size=1.0 for BTC)
        assert level.is_price_near(50001.0, tolerance_pips=2.0, pip_size=1.0)
        assert level.is_price_near(49999.0, tolerance_pips=2.0, pip_size=1.0)

        # Outside tolerance
        assert not level.is_price_near(50010.0, tolerance_pips=2.0, pip_size=1.0)

    def test_mark_touched(self):
        """Test marking liquidity level as touched."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=50000.0,
            origin_timestamp=1609459200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15
        )

        assert level.touch_count == 0
        assert level.state == LiquidityState.ACTIVE

        level.mark_touched(1609459300000)

        assert level.touch_count == 1
        assert level.last_touch_timestamp == 1609459300000
        assert level.state == LiquidityState.PARTIAL

    def test_mark_swept(self):
        """Test marking liquidity level as swept."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=50000.0,
            origin_timestamp=1609459200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15
        )

        level.mark_swept(1609459400000)

        assert level.state == LiquidityState.SWEPT
        assert level.swept_timestamp == 1609459400000

    def test_to_dict(self):
        """Test converting liquidity level to dictionary."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=50000.0,
            origin_timestamp=1609459200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            touch_count=3,
            strength=80.0
        )

        data = level.to_dict()

        assert data['type'] == 'BUY_SIDE'
        assert data['price'] == 50000.0
        assert data['touch_count'] == 3
        assert data['strength'] == 80.0
        assert 'origin_datetime' in data


class TestSwingPoint:
    """Test cases for SwingPoint dataclass."""

    def test_create_swing_high(self):
        """Test creating a swing high point."""
        swing = SwingPoint(
            price=50000.0,
            timestamp=1609459200000,
            candle_index=10,
            is_high=True,
            strength=3,
            volume=1000.0
        )

        assert swing.is_high is True
        assert swing.price == 50000.0
        assert swing.strength == 3

    def test_create_swing_low(self):
        """Test creating a swing low point."""
        swing = SwingPoint(
            price=49000.0,
            timestamp=1609459200000,
            candle_index=5,
            is_high=False,
            strength=3,
            volume=1200.0
        )

        assert swing.is_high is False
        assert swing.price == 49000.0


class TestLiquidityZoneDetector:
    """Test cases for LiquidityZoneDetector."""

    def create_test_candles(self, count: int = 20, start_price: float = 50000.0) -> list[Candle]:
        """Helper to create test candles."""
        candles = []
        timestamp = 1609459200000

        for i in range(count):
            # Create varying prices for swing detection
            price_variation = (i % 5 - 2) * 100  # Creates swing patterns

            candles.append(Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=timestamp + i * 900000,  # 15 min intervals
                open=start_price + price_variation,
                high=start_price + price_variation + 50,
                low=start_price + price_variation - 50,
                close=start_price + price_variation + 25,
                volume=1000.0 + i * 10,
                is_closed=True
            ))

        return candles

    def create_swing_pattern_candles(self) -> list[Candle]:
        """Create candles with clear swing highs and lows."""
        prices = [
            # Swing low at index 3
            100.0, 99.0, 98.0, 95.0, 96.0, 97.0, 98.0,
            # Swing high at index 10
            99.0, 100.0, 102.0, 105.0, 103.0, 102.0, 101.0,
            # Swing low at index 17
            100.0, 99.0, 97.0, 94.0, 95.0, 96.0, 97.0
        ]

        candles = []
        timestamp = 1609459200000

        for i, price in enumerate(prices):
            candles.append(Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=timestamp + i * 900000,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1000.0,
                is_closed=True
            ))

        return candles

    def test_detector_initialization(self):
        """Test detector initialization with default parameters."""
        detector = LiquidityZoneDetector()

        assert detector.min_swing_strength == 3
        assert detector.proximity_tolerance_pips == 2.0
        assert detector.pip_size == 0.0001

    def test_detector_custom_parameters(self):
        """Test detector initialization with custom parameters."""
        detector = LiquidityZoneDetector(
            min_swing_strength=5,
            proximity_tolerance_pips=5.0,
            pip_size=0.01
        )

        assert detector.min_swing_strength == 5
        assert detector.proximity_tolerance_pips == 5.0
        assert detector.pip_size == 0.01

    def test_detect_swing_highs(self):
        """Test swing high detection."""
        detector = LiquidityZoneDetector(min_swing_strength=3)
        candles = self.create_swing_pattern_candles()

        swing_highs = detector.detect_swing_highs(candles)

        # Should detect the swing high around index 10
        assert len(swing_highs) > 0
        assert any(s.is_high for s in swing_highs)

        # The highest swing should be around index 10 (price 105)
        highest_swing = max(swing_highs, key=lambda s: s.price)
        assert highest_swing.candle_index == 10
        assert highest_swing.price == 106.0  # high price

    def test_detect_swing_lows(self):
        """Test swing low detection."""
        detector = LiquidityZoneDetector(min_swing_strength=3)
        candles = self.create_swing_pattern_candles()

        swing_lows = detector.detect_swing_lows(candles)

        # Should detect swing lows
        assert len(swing_lows) > 0
        assert all(not s.is_high for s in swing_lows)

        # Should have low around index 3 (price 95) and index 17 (price 94)
        lowest_swing = min(swing_lows, key=lambda s: s.price)
        assert lowest_swing.candle_index in [3, 17]

    def test_insufficient_candles_for_swing_detection(self):
        """Test that insufficient candles returns empty list with warning."""
        detector = LiquidityZoneDetector(min_swing_strength=5)
        candles = self.create_test_candles(count=5)

        swing_highs = detector.detect_swing_highs(candles)
        swing_lows = detector.detect_swing_lows(candles)

        assert len(swing_highs) == 0
        assert len(swing_lows) == 0

    def test_calculate_volume_profile(self):
        """Test volume profile calculation."""
        detector = LiquidityZoneDetector(volume_lookback=10)
        candles = self.create_test_candles(count=20)

        volume_profile = detector.calculate_volume_profile(candles, 10)

        assert volume_profile > 0
        # Should be average of candles around index 10
        expected_avg = sum(c.volume for c in candles[5:15]) / 10
        assert abs(volume_profile - expected_avg) < 1.0

    def test_calculate_liquidity_strength(self):
        """Test liquidity strength calculation."""
        detector = LiquidityZoneDetector()
        candles = self.create_test_candles(count=20)

        swing_point = SwingPoint(
            price=50000.0,
            timestamp=1609459200000,
            candle_index=10,
            is_high=True,
            strength=3,
            volume=2000.0
        )

        strength = detector.calculate_liquidity_strength(swing_point, candles, touch_count=2)

        assert 0 <= strength <= 100
        # With 2 touches, strength should be higher
        assert strength > 20

    def test_detect_liquidity_levels(self):
        """Test complete liquidity level detection."""
        detector = LiquidityZoneDetector(min_swing_strength=3)
        candles = self.create_swing_pattern_candles()

        buy_side, sell_side = detector.detect_liquidity_levels(candles)

        # Should detect both buy-side and sell-side levels
        assert len(buy_side) > 0
        assert len(sell_side) > 0

        # Buy-side levels should be at swing highs
        assert all(level.type == LiquidityType.BUY_SIDE for level in buy_side)

        # Sell-side levels should be at swing lows
        assert all(level.type == LiquidityType.SELL_SIDE for level in sell_side)

    def test_detect_liquidity_levels_insufficient_candles(self):
        """Test that insufficient candles raises ValueError."""
        detector = LiquidityZoneDetector(min_swing_strength=3)
        candles = self.create_test_candles(count=5)

        with pytest.raises(ValueError, match="Insufficient candles"):
            detector.detect_liquidity_levels(candles)

    def test_cluster_nearby_levels(self):
        """Test clustering of nearby liquidity levels."""
        detector = LiquidityZoneDetector(
            proximity_tolerance_pips=5.0,
            pip_size=1.0
        )

        # Create 3 nearby levels
        levels = [
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=50000.0,
                origin_timestamp=1609459200000,
                origin_candle_index=10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=70.0,
                touch_count=1
            ),
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=50003.0,
                origin_timestamp=1609459300000,
                origin_candle_index=11,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=65.0,
                touch_count=2
            ),
            LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=50100.0,  # Far away
                origin_timestamp=1609459400000,
                origin_candle_index=12,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=60.0
            )
        ]

        clustered = detector.cluster_nearby_levels(levels)

        # First two should be clustered, third separate
        assert len(clustered) == 2

        # Clustered level should have combined touches
        cluster = next(l for l in clustered if l.touch_count > 1)
        assert cluster.touch_count == 3

    def test_update_liquidity_states_buy_side_sweep(self):
        """Test updating buy-side liquidity state on sweep."""
        detector = LiquidityZoneDetector(min_swing_strength=3)
        candles = self.create_swing_pattern_candles()

        buy_side, sell_side = detector.detect_liquidity_levels(candles)

        # Create candle that sweeps buy-side liquidity
        if buy_side:
            highest_level = max(buy_side, key=lambda l: l.price)
            sweep_candle = Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1609459200000 + 20 * 900000,
                open=highest_level.price - 5.0,
                high=highest_level.price + 5.0,
                low=highest_level.price - 10.0,
                close=highest_level.price + 3.0,
                volume=1500.0,
                is_closed=True
            )

            test_candles = candles + [sweep_candle]
            detector.update_liquidity_states(buy_side, sell_side, test_candles, start_index=len(candles))

            assert highest_level.state == LiquidityState.SWEPT
            assert highest_level.swept_timestamp is not None

    def test_update_liquidity_states_sell_side_sweep(self):
        """Test updating sell-side liquidity state on sweep."""
        detector = LiquidityZoneDetector(min_swing_strength=3)
        candles = self.create_swing_pattern_candles()

        buy_side, sell_side = detector.detect_liquidity_levels(candles)

        # Create candle that sweeps sell-side liquidity
        if sell_side:
            lowest_level = min(sell_side, key=lambda l: l.price)
            sweep_candle = Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1609459200000 + 20 * 900000,
                open=lowest_level.price + 5.0,
                high=lowest_level.price + 10.0,
                low=lowest_level.price - 5.0,
                close=lowest_level.price - 3.0,
                volume=1500.0,
                is_closed=True
            )

            test_candles = candles + [sweep_candle]
            detector.update_liquidity_states(buy_side, sell_side, test_candles, start_index=len(candles))

            assert lowest_level.state == LiquidityState.SWEPT
            assert lowest_level.swept_timestamp is not None

    def test_update_liquidity_states_touch_without_sweep(self):
        """Test updating liquidity state on touch without full sweep."""
        detector = LiquidityZoneDetector(min_swing_strength=3)
        candles = self.create_swing_pattern_candles()

        buy_side, sell_side = detector.detect_liquidity_levels(candles)

        # Create candle that touches but doesn't sweep buy-side liquidity
        if buy_side:
            level = buy_side[0]
            touch_candle = Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=1609459200000 + 20 * 900000,
                open=level.price - 5.0,
                high=level.price + 1.0,
                low=level.price - 10.0,
                close=level.price - 2.0,  # Closes below level
                volume=1200.0,
                is_closed=True
            )

            test_candles = candles + [touch_candle]
            original_touches = level.touch_count

            detector.update_liquidity_states(buy_side, sell_side, test_candles, start_index=len(candles))

            # Should be touched but not swept
            assert level.touch_count > original_touches
            assert level.state == LiquidityState.PARTIAL
            assert level.last_touch_timestamp is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
