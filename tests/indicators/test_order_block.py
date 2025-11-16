"""
Unit tests for Order Block detection and analysis.
"""

from typing import List

import pytest

from src.core.constants import TimeFrame
from src.indicators.order_block import (
    OrderBlock,
    OrderBlockDetector,
    OrderBlockState,
    OrderBlockType,
    SwingPoint,
)
from src.models.candle import Candle


class TestOrderBlock:
    """Test OrderBlock data class."""

    def test_order_block_creation(self):
        """Test creating a valid order block."""
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.5,
            volume=1000000.0,
        )

        assert ob.type == OrderBlockType.BULLISH
        assert ob.high == 50000.0
        assert ob.low == 49500.0
        assert ob.strength == 75.5
        assert ob.state == OrderBlockState.ACTIVE
        assert ob.test_count == 0

    def test_order_block_validation_high_low(self):
        """Test that high must be greater than low."""
        with pytest.raises(ValueError, match="High .* must be greater than low"):
            OrderBlock(
                type=OrderBlockType.BULLISH,
                high=49000.0,
                low=50000.0,  # Invalid: low > high
                origin_timestamp=1704067200000,
                origin_candle_index=10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=75.0,
                volume=1000000.0,
            )

    def test_order_block_validation_strength(self):
        """Test strength must be between 0 and 100."""
        with pytest.raises(ValueError, match="Strength must be between 0 and 100"):
            OrderBlock(
                type=OrderBlockType.BULLISH,
                high=50000.0,
                low=49500.0,
                origin_timestamp=1704067200000,
                origin_candle_index=10,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=150.0,  # Invalid: > 100
                volume=1000000.0,
            )

    def test_order_block_range(self):
        """Test calculating order block range."""
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1000000.0,
        )

        assert ob.get_range() == 500.0
        assert ob.get_midpoint() == 49750.0

    def test_order_block_contains_price(self):
        """Test checking if price is within order block."""
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1000000.0,
        )

        assert ob.contains_price(49750.0)
        assert ob.contains_price(49500.0)  # Lower boundary
        assert ob.contains_price(50000.0)  # Upper boundary
        assert not ob.contains_price(49400.0)
        assert not ob.contains_price(50100.0)

    def test_order_block_price_position(self):
        """Test checking price position relative to order block."""
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1000000.0,
        )

        assert ob.is_price_above(50100.0)
        assert not ob.is_price_above(49900.0)
        assert ob.is_price_below(49400.0)
        assert not ob.is_price_below(49900.0)

    def test_order_block_mark_tested(self):
        """Test marking order block as tested."""
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1000000.0,
        )

        test_time = 1704067500000
        ob.mark_tested(test_time)

        assert ob.state == OrderBlockState.TESTED
        assert ob.last_tested_timestamp == test_time
        assert ob.test_count == 1

        # Test multiple times
        ob.mark_tested(test_time + 1000)
        assert ob.test_count == 2

    def test_order_block_state_changes(self):
        """Test state transitions."""
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1000000.0,
        )

        assert ob.state == OrderBlockState.ACTIVE

        ob.mark_broken()
        assert ob.state == OrderBlockState.BROKEN

        ob.mark_expired()
        assert ob.state == OrderBlockState.EXPIRED

    def test_order_block_to_dict(self):
        """Test converting order block to dictionary."""
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            origin_candle_index=10,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1000000.0,
        )

        ob_dict = ob.to_dict()

        assert ob_dict["type"] == "BULLISH"
        assert ob_dict["high"] == 50000.0
        assert ob_dict["low"] == 49500.0
        assert ob_dict["strength"] == 75.0
        assert ob_dict["state"] == "ACTIVE"
        assert ob_dict["range"] == 500.0
        assert ob_dict["midpoint"] == 49750.0


class TestSwingPoint:
    """Test SwingPoint data class."""

    def test_swing_point_creation(self):
        """Test creating swing points."""
        swing_high = SwingPoint(
            price=50000.0, timestamp=1704067200000, candle_index=10, is_high=True, strength=3
        )

        assert swing_high.is_high
        assert swing_high.price == 50000.0
        assert swing_high.strength == 3

        swing_low = SwingPoint(
            price=49000.0, timestamp=1704067500000, candle_index=15, is_high=False, strength=2
        )

        assert not swing_low.is_high
        assert swing_low.price == 49000.0


def create_test_candle(
    symbol: str,
    timeframe: TimeFrame,
    timestamp: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    is_closed: bool = True,
) -> Candle:
    """Helper function to create test candles."""
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        is_closed=is_closed,
    )


class TestOrderBlockDetector:
    """Test OrderBlockDetector functionality."""

    def create_bullish_pattern_candles(self) -> List[Candle]:
        """
        Create a pattern with a bullish order block.

        Pattern: Downtrend → Swing Low → Strong move up
        """
        base_time = 1704067200000
        interval = 60000  # 1 minute

        candles = [
            # Downtrend leading to swing low
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time, 50000, 50100, 49900, 49950, 100000
            ),
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time + interval, 49950, 50000, 49800, 49850, 110000
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 2,
                49850,
                49900,
                49700,
                49750,
                120000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 3,
                49750,
                49800,
                49600,
                49650,
                130000,
            ),
            # Last bearish candle (potential OB) - high volume
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 4,
                49650,
                49700,
                49500,
                49550,
                200000,
            ),
            # Swing low
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time + interval * 5, 49550, 49600, 49450, 49500, 90000
            ),
            # Strong move up (confirming the order block)
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 6,
                49500,
                49900,
                49500,
                49850,
                150000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 7,
                49850,
                50200,
                49800,
                50100,
                160000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 8,
                50100,
                50400,
                50000,
                50300,
                140000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 9,
                50300,
                50500,
                50200,
                50400,
                130000,
            ),
        ]

        return candles

    def create_bearish_pattern_candles(self) -> List[Candle]:
        """
        Create a pattern with a bearish order block.

        Pattern: Uptrend → Swing High → Strong move down
        """
        base_time = 1704067200000
        interval = 60000  # 1 minute

        candles = [
            # Uptrend leading to swing high
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time, 49000, 49100, 48950, 49050, 100000
            ),
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time + interval, 49050, 49200, 49000, 49150, 110000
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 2,
                49150,
                49300,
                49100,
                49250,
                120000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 3,
                49250,
                49400,
                49200,
                49350,
                130000,
            ),
            # Last bullish candle (potential OB) - high volume
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 4,
                49350,
                49500,
                49300,
                49450,
                200000,
            ),
            # Swing high
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time + interval * 5, 49450, 49550, 49400, 49500, 90000
            ),
            # Strong move down (confirming the order block)
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 6,
                49500,
                49500,
                49100,
                49150,
                150000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 7,
                49150,
                49200,
                48800,
                48900,
                160000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 8,
                48900,
                49000,
                48600,
                48700,
                140000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 9,
                48700,
                48800,
                48500,
                48600,
                130000,
            ),
        ]

        return candles

    def test_detector_initialization(self):
        """Test detector initialization with parameters."""
        detector = OrderBlockDetector(
            min_swing_strength=3,
            min_candles_for_ob=5,
            max_candles_for_ob=7,
            volume_multiplier_threshold=1.5,
        )

        assert detector.min_swing_strength == 3
        assert detector.min_candles_for_ob == 5
        assert detector.max_candles_for_ob == 7
        assert detector.volume_multiplier_threshold == 1.5

    def test_detect_swing_highs(self):
        """Test swing high detection."""
        candles = self.create_bearish_pattern_candles()
        detector = OrderBlockDetector()

        swing_highs = detector.detect_swing_highs(candles, lookback=2)

        assert len(swing_highs) > 0
        # The swing high should be around index 5
        swing_high = next((s for s in swing_highs if s.candle_index == 5), None)
        assert swing_high is not None
        assert swing_high.is_high
        assert swing_high.price == 49550.0

    def test_detect_swing_lows(self):
        """Test swing low detection."""
        candles = self.create_bullish_pattern_candles()
        detector = OrderBlockDetector()

        swing_lows = detector.detect_swing_lows(candles, lookback=2)

        assert len(swing_lows) > 0
        # The swing low should be around index 5
        swing_low = next((s for s in swing_lows if s.candle_index == 5), None)
        assert swing_low is not None
        assert not swing_low.is_high
        assert swing_low.price == 49450.0

    def test_detect_bullish_order_blocks(self):
        """Test detecting bullish order blocks."""
        candles = self.create_bullish_pattern_candles()
        detector = OrderBlockDetector(min_swing_strength=2)

        order_blocks = detector.detect_order_blocks(candles)

        # Should detect at least one bullish order block
        bullish_obs = [ob for ob in order_blocks if ob.type == OrderBlockType.BULLISH]
        assert len(bullish_obs) > 0

        # Check the detected order block properties
        ob = bullish_obs[0]
        assert ob.type == OrderBlockType.BULLISH
        assert ob.symbol == "BTCUSDT"
        assert ob.timeframe == TimeFrame.M1
        assert ob.state == OrderBlockState.ACTIVE
        assert 0 <= ob.strength <= 100

    def test_detect_bearish_order_blocks(self):
        """Test detecting bearish order blocks."""
        candles = self.create_bearish_pattern_candles()
        detector = OrderBlockDetector(min_swing_strength=2)

        order_blocks = detector.detect_order_blocks(candles)

        # Should detect at least one bearish order block
        bearish_obs = [ob for ob in order_blocks if ob.type == OrderBlockType.BEARISH]
        assert len(bearish_obs) > 0

        # Check the detected order block properties
        ob = bearish_obs[0]
        assert ob.type == OrderBlockType.BEARISH
        assert ob.symbol == "BTCUSDT"
        assert ob.timeframe == TimeFrame.M1
        assert ob.state == OrderBlockState.ACTIVE
        assert 0 <= ob.strength <= 100

    def test_insufficient_candles_error(self):
        """Test that insufficient candles raises error."""
        detector = OrderBlockDetector(min_candles_for_ob=10)
        candles = self.create_bullish_pattern_candles()[:5]

        with pytest.raises(ValueError, match="Insufficient candles"):
            detector.detect_order_blocks(candles)

    def test_strength_calculation(self):
        """Test order block strength calculation."""
        candles = self.create_bullish_pattern_candles()
        detector = OrderBlockDetector()

        # Test with a high-volume candle
        high_vol_candle = candles[4]  # The OB candle with volume=200000
        strength = detector.calculate_order_block_strength(high_vol_candle, candles, 4)

        assert 0 <= strength <= 100
        # High volume should contribute to higher strength
        assert strength > 30  # Should have reasonable strength

    def test_empty_swing_points(self):
        """Test behavior with no swing points detected."""
        # Create a ranging market with no clear swings
        base_time = 1704067200000
        interval = 60000

        candles = [
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + i * interval,
                50000,
                50050,
                49950,
                50000,
                100000,
            )
            for i in range(10)
        ]

        detector = OrderBlockDetector(min_swing_strength=3)
        order_blocks = detector.detect_order_blocks(candles)

        # With no clear swings, should detect few or no order blocks
        assert isinstance(order_blocks, list)

    def test_order_blocks_sorted_by_time(self):
        """Test that detected order blocks are sorted by timestamp."""
        candles = self.create_bullish_pattern_candles() + self.create_bearish_pattern_candles()
        detector = OrderBlockDetector(min_swing_strength=2)

        order_blocks = detector.detect_order_blocks(candles)

        if len(order_blocks) > 1:
            for i in range(len(order_blocks) - 1):
                assert order_blocks[i].origin_timestamp <= order_blocks[i + 1].origin_timestamp
