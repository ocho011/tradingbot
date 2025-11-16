"""
Unit tests for Breaker Block detection and role transition logic.
"""

from typing import List

import pytest

from src.core.constants import TimeFrame
from src.indicators.breaker_block import BreakerBlock, BreakerBlockDetector, BreakerBlockType
from src.indicators.order_block import OrderBlock, OrderBlockState, OrderBlockType
from src.models.candle import Candle


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


class TestBreakerBlock:
    """Test BreakerBlock data class."""

    def test_breaker_block_creation(self):
        """Test creating a valid breaker block."""
        bb = BreakerBlock(
            type=BreakerBlockType.BEARISH,
            original_type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            transition_timestamp=1704067500000,
            transition_candle_index=15,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.5,
            volume=1500000.0,
            original_ob_volume=1000000.0,
            original_test_count=3,
            breach_percentage=2.5,
        )

        assert bb.type == BreakerBlockType.BEARISH
        assert bb.original_type == OrderBlockType.BULLISH
        assert bb.high == 50000.0
        assert bb.low == 49500.0
        assert bb.strength == 75.5
        assert bb.state == "ACTIVE"
        assert bb.test_count == 0
        assert bb.breach_percentage == 2.5
        assert bb.original_test_count == 3

    def test_breaker_block_validation_high_low(self):
        """Test that high must be greater than low."""
        with pytest.raises(ValueError, match="High .* must be greater than low"):
            BreakerBlock(
                type=BreakerBlockType.BEARISH,
                original_type=OrderBlockType.BULLISH,
                high=49000.0,
                low=50000.0,  # Invalid
                origin_timestamp=1704067200000,
                transition_timestamp=1704067500000,
                transition_candle_index=15,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=75.0,
                volume=1500000.0,
                original_ob_volume=1000000.0,
            )

    def test_breaker_block_validation_strength(self):
        """Test strength must be between 0 and 100."""
        with pytest.raises(ValueError, match="Strength must be between 0 and 100"):
            BreakerBlock(
                type=BreakerBlockType.BEARISH,
                original_type=OrderBlockType.BULLISH,
                high=50000.0,
                low=49500.0,
                origin_timestamp=1704067200000,
                transition_timestamp=1704067500000,
                transition_candle_index=15,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=150.0,  # Invalid
                volume=1500000.0,
                original_ob_volume=1000000.0,
            )

    def test_breaker_block_validation_breach_percentage(self):
        """Test breach percentage must be non-negative."""
        with pytest.raises(ValueError, match="Breach percentage must be non-negative"):
            BreakerBlock(
                type=BreakerBlockType.BEARISH,
                original_type=OrderBlockType.BULLISH,
                high=50000.0,
                low=49500.0,
                origin_timestamp=1704067200000,
                transition_timestamp=1704067500000,
                transition_candle_index=15,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                strength=75.0,
                volume=1500000.0,
                original_ob_volume=1000000.0,
                breach_percentage=-1.0,  # Invalid
            )

    def test_breaker_block_role_description(self):
        """Test role description for role transitions."""
        # Bullish BB (former bearish OB - resistance → support)
        bb_bullish = BreakerBlock(
            type=BreakerBlockType.BULLISH,
            original_type=OrderBlockType.BEARISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            transition_timestamp=1704067500000,
            transition_candle_index=15,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1500000.0,
            original_ob_volume=1000000.0,
        )

        assert "resistance" in bb_bullish.get_role_description().lower()
        assert "support" in bb_bullish.get_role_description().lower()

        # Bearish BB (former bullish OB - support → resistance)
        bb_bearish = BreakerBlock(
            type=BreakerBlockType.BEARISH,
            original_type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            transition_timestamp=1704067500000,
            transition_candle_index=15,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1500000.0,
            original_ob_volume=1000000.0,
        )

        assert "support" in bb_bearish.get_role_description().lower()
        assert "resistance" in bb_bearish.get_role_description().lower()

    def test_breaker_block_range_and_midpoint(self):
        """Test calculating breaker block range and midpoint."""
        bb = BreakerBlock(
            type=BreakerBlockType.BEARISH,
            original_type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            transition_timestamp=1704067500000,
            transition_candle_index=15,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1500000.0,
            original_ob_volume=1000000.0,
        )

        assert bb.get_range() == 500.0
        assert bb.get_midpoint() == 49750.0

    def test_breaker_block_contains_price(self):
        """Test checking if price is within breaker block."""
        bb = BreakerBlock(
            type=BreakerBlockType.BEARISH,
            original_type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            transition_timestamp=1704067500000,
            transition_candle_index=15,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1500000.0,
            original_ob_volume=1000000.0,
        )

        assert bb.contains_price(49750.0)
        assert bb.contains_price(49500.0)
        assert bb.contains_price(50000.0)
        assert not bb.contains_price(49400.0)
        assert not bb.contains_price(50100.0)

    def test_breaker_block_mark_tested(self):
        """Test marking breaker block as tested."""
        bb = BreakerBlock(
            type=BreakerBlockType.BEARISH,
            original_type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            transition_timestamp=1704067500000,
            transition_candle_index=15,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1500000.0,
            original_ob_volume=1000000.0,
        )

        test_time = 1704067800000
        bb.mark_tested(test_time)

        assert bb.state == "TESTED"
        assert bb.last_tested_timestamp == test_time
        assert bb.test_count == 1

    def test_breaker_block_to_dict(self):
        """Test converting breaker block to dictionary."""
        bb = BreakerBlock(
            type=BreakerBlockType.BEARISH,
            original_type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1704067200000,
            transition_timestamp=1704067500000,
            transition_candle_index=15,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            strength=75.0,
            volume=1500000.0,
            original_ob_volume=1000000.0,
            breach_percentage=2.5,
        )

        bb_dict = bb.to_dict()

        assert bb_dict["type"] == "BEARISH"
        assert bb_dict["original_type"] == "BULLISH"
        assert bb_dict["high"] == 50000.0
        assert bb_dict["low"] == 49500.0
        assert bb_dict["strength"] == 75.0
        assert bb_dict["breach_percentage"] == 2.5
        assert bb_dict["range"] == 500.0
        assert bb_dict["midpoint"] == 49750.0
        assert "role_transition" in bb_dict


class TestBreakerBlockDetector:
    """Test BreakerBlockDetector functionality."""

    def create_bullish_ob_with_breach(self) -> tuple[List[Candle], OrderBlock]:
        """
        Create test data: bullish OB (support) that gets breached downward.

        Returns:
            Tuple of (candles, order_block)
        """
        base_time = 1704067200000
        interval = 60000

        # Create candles with a bullish OB that gets breached
        candles = [
            # Initial candles
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time, 50000, 50100, 49900, 50000, 100000
            ),
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time + interval, 50000, 50050, 49950, 50000, 100000
            ),
            # Bullish OB formed here (support at 49500-49700)
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 2,
                49700,
                49750,
                49500,
                49550,
                150000,
            ),
            # Price moves up (confirming OB)
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 3,
                49550,
                49900,
                49500,
                49850,
                120000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 4,
                49850,
                50100,
                49800,
                50050,
                110000,
            ),
            # Price comes back to test OB
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 5,
                50050,
                50100,
                49600,
                49650,
                100000,
            ),
            # BREACH: Strong move down through the OB support
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 6,
                49650,
                49700,
                49200,
                49250,
                200000,
            ),
            # Continuation down
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 7,
                49250,
                49300,
                48900,
                49000,
                180000,
            ),
        ]

        # Create the bullish Order Block
        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=49700.0,
            low=49500.0,
            origin_timestamp=base_time + interval * 2,
            origin_candle_index=2,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=70.0,
            volume=150000.0,
            state=OrderBlockState.ACTIVE,
        )

        return candles, ob

    def create_bearish_ob_with_breach(self) -> tuple[List[Candle], OrderBlock]:
        """
        Create test data: bearish OB (resistance) that gets breached upward.

        Returns:
            Tuple of (candles, order_block)
        """
        base_time = 1704067200000
        interval = 60000

        candles = [
            # Initial candles
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time, 49000, 49100, 48950, 49000, 100000
            ),
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time + interval, 49000, 49050, 48950, 49000, 100000
            ),
            # Bearish OB formed here (resistance at 49300-49500)
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 2,
                49300,
                49500,
                49250,
                49450,
                150000,
            ),
            # Price moves down (confirming OB)
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 3,
                49450,
                49500,
                49100,
                49150,
                120000,
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 4,
                49150,
                49200,
                48900,
                48950,
                110000,
            ),
            # Price comes back to test OB
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 5,
                48950,
                49400,
                48900,
                49350,
                100000,
            ),
            # BREACH: Strong move up through the OB resistance
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 6,
                49350,
                49800,
                49300,
                49750,
                200000,
            ),
            # Continuation up
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 7,
                49750,
                50100,
                49700,
                50000,
                180000,
            ),
        ]

        # Create the bearish Order Block
        ob = OrderBlock(
            type=OrderBlockType.BEARISH,
            high=49500.0,
            low=49300.0,
            origin_timestamp=base_time + interval * 2,
            origin_candle_index=2,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=70.0,
            volume=150000.0,
            state=OrderBlockState.ACTIVE,
        )

        return candles, ob

    def test_detector_initialization(self):
        """Test detector initialization with parameters."""
        detector = BreakerBlockDetector(
            breach_threshold_percentage=1.0,
            min_breach_candle_body_ratio=0.5,
            require_close_beyond=True,
        )

        assert detector.breach_threshold_percentage == 1.0
        assert detector.min_breach_candle_body_ratio == 0.5
        assert detector.require_close_beyond is True

    def test_calculate_breach_percentage_bullish_ob(self):
        """Test calculating breach percentage for bullish OB."""
        detector = BreakerBlockDetector()

        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,  # Range = 500
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=70.0,
            volume=100000.0,
        )

        # No breach (price above low)
        assert detector.calculate_breach_percentage(ob, 49600.0) == 0.0

        # 50 point breach below 49500 = 10% of 500 range
        assert detector.calculate_breach_percentage(ob, 49450.0) == 10.0

        # 100 point breach = 20%
        assert detector.calculate_breach_percentage(ob, 49400.0) == 20.0

    def test_calculate_breach_percentage_bearish_ob(self):
        """Test calculating breach percentage for bearish OB."""
        detector = BreakerBlockDetector()

        ob = OrderBlock(
            type=OrderBlockType.BEARISH,
            high=50000.0,
            low=49500.0,  # Range = 500
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=70.0,
            volume=100000.0,
        )

        # No breach (price below high)
        assert detector.calculate_breach_percentage(ob, 49900.0) == 0.0

        # 50 point breach above 50000 = 10% of 500 range
        assert detector.calculate_breach_percentage(ob, 50050.0) == 10.0

        # 100 point breach = 20%
        assert detector.calculate_breach_percentage(ob, 50100.0) == 20.0

    def test_is_order_block_breached_bullish(self):
        """Test breach detection for bullish OB."""
        detector = BreakerBlockDetector(
            breach_threshold_percentage=2.0,  # Need 2% breach
            min_breach_candle_body_ratio=0.4,
            require_close_beyond=True,
        )

        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,  # Range = 500, 2% = 10 points
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=70.0,
            volume=100000.0,
        )

        base_time = 1704067500000

        # Not breached - price stays above low
        candle_no_breach = create_test_candle(
            "BTCUSDT", TimeFrame.M1, base_time, 49600, 49700, 49520, 49650, 100000
        )
        assert not detector.is_order_block_breached(ob, candle_no_breach)

        # Breached but insufficient percentage (only 1%)
        candle_small_breach = create_test_candle(
            "BTCUSDT", TimeFrame.M1, base_time, 49500, 49550, 49480, 49495, 100000
        )
        assert not detector.is_order_block_breached(ob, candle_small_breach)

        # Good breach (3% = 15 points below low) with strong body
        candle_breach = create_test_candle(
            "BTCUSDT", TimeFrame.M1, base_time, 49500, 49520, 49400, 49420, 100000
        )
        assert detector.is_order_block_breached(ob, candle_breach)

    def test_is_order_block_breached_bearish(self):
        """Test breach detection for bearish OB."""
        detector = BreakerBlockDetector(
            breach_threshold_percentage=2.0,
            min_breach_candle_body_ratio=0.4,
            require_close_beyond=True,
        )

        ob = OrderBlock(
            type=OrderBlockType.BEARISH,
            high=50000.0,
            low=49500.0,  # Range = 500, 2% = 10 points
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=70.0,
            volume=100000.0,
        )

        base_time = 1704067500000

        # Not breached - price stays below high
        candle_no_breach = create_test_candle(
            "BTCUSDT", TimeFrame.M1, base_time, 49800, 49900, 49750, 49850, 100000
        )
        assert not detector.is_order_block_breached(ob, candle_no_breach)

        # Good breach (3% = 15 points above high) with strong body
        candle_breach = create_test_candle(
            "BTCUSDT", TimeFrame.M1, base_time, 49950, 50150, 49900, 50100, 100000
        )
        assert detector.is_order_block_breached(ob, candle_breach)

    def test_convert_to_breaker_block_bullish_to_bearish(self):
        """Test converting bullish OB to bearish BB (support → resistance)."""
        detector = BreakerBlockDetector()
        candles, ob = self.create_bullish_ob_with_breach()

        breach_candle = candles[6]  # The candle that breaks the OB
        bb = detector.convert_to_breaker_block(ob, breach_candle, 6)

        assert bb.type == BreakerBlockType.BEARISH  # Role reversed
        assert bb.original_type == OrderBlockType.BULLISH
        assert bb.high == ob.high
        assert bb.low == ob.low
        assert bb.transition_timestamp == breach_candle.timestamp
        assert bb.breach_percentage > 0
        assert bb.state == "ACTIVE"

    def test_convert_to_breaker_block_bearish_to_bullish(self):
        """Test converting bearish OB to bullish BB (resistance → support)."""
        detector = BreakerBlockDetector()
        candles, ob = self.create_bearish_ob_with_breach()

        breach_candle = candles[6]
        bb = detector.convert_to_breaker_block(ob, breach_candle, 6)

        assert bb.type == BreakerBlockType.BULLISH  # Role reversed
        assert bb.original_type == OrderBlockType.BEARISH
        assert bb.high == ob.high
        assert bb.low == ob.low
        assert bb.transition_timestamp == breach_candle.timestamp
        assert bb.breach_percentage > 0
        assert bb.state == "ACTIVE"

    def test_detect_breaker_blocks_from_bullish_ob(self):
        """Test detecting breaker block from breached bullish OB."""
        candles, ob = self.create_bullish_ob_with_breach()
        detector = BreakerBlockDetector(breach_threshold_percentage=1.0)

        breaker_blocks = detector.detect_breaker_blocks([ob], candles)

        assert len(breaker_blocks) > 0
        bb = breaker_blocks[0]

        assert bb.type == BreakerBlockType.BEARISH
        assert bb.original_type == OrderBlockType.BULLISH
        assert bb.symbol == "BTCUSDT"
        assert bb.timeframe == TimeFrame.M1
        assert ob.state == OrderBlockState.BROKEN

    def test_detect_breaker_blocks_from_bearish_ob(self):
        """Test detecting breaker block from breached bearish OB."""
        candles, ob = self.create_bearish_ob_with_breach()
        detector = BreakerBlockDetector(breach_threshold_percentage=1.0)

        breaker_blocks = detector.detect_breaker_blocks([ob], candles)

        assert len(breaker_blocks) > 0
        bb = breaker_blocks[0]

        assert bb.type == BreakerBlockType.BULLISH
        assert bb.original_type == OrderBlockType.BEARISH
        assert bb.symbol == "BTCUSDT"
        assert bb.timeframe == TimeFrame.M1
        assert ob.state == OrderBlockState.BROKEN

    def test_detect_breaker_blocks_no_breach(self):
        """Test that no breaker blocks are detected without breach."""
        base_time = 1704067200000
        interval = 60000

        # Create candles where OB is respected (not breached)
        candles = [
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + i * interval,
                49500 + (i * 10),
                49600 + (i * 10),
                49400 + (i * 10),
                49550 + (i * 10),
                100000,
            )
            for i in range(10)
        ]

        ob = OrderBlock(
            type=OrderBlockType.BULLISH,
            high=49700.0,
            low=49500.0,
            origin_timestamp=base_time,
            origin_candle_index=0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=70.0,
            volume=100000.0,
            state=OrderBlockState.ACTIVE,
        )

        detector = BreakerBlockDetector(breach_threshold_percentage=2.0)
        breaker_blocks = detector.detect_breaker_blocks([ob], candles, start_index=1)

        assert len(breaker_blocks) == 0
        assert ob.state == OrderBlockState.ACTIVE

    def test_update_breaker_block_states(self):
        """Test updating breaker block states when price tests them."""
        candles, ob = self.create_bullish_ob_with_breach()
        detector = BreakerBlockDetector(breach_threshold_percentage=1.0)

        # First detect the breaker block
        breaker_blocks = detector.detect_breaker_blocks([ob], candles)
        assert len(breaker_blocks) > 0

        bb = breaker_blocks[0]
        assert bb.state == "ACTIVE"
        assert bb.test_count == 0

        # Add more candles that test the breaker block (now acting as resistance)
        base_time = candles[-1].timestamp
        interval = 60000

        test_candles = candles + [
            # Price comes back to test the new resistance
            create_test_candle(
                "BTCUSDT", TimeFrame.M1, base_time + interval, 49300, 49600, 49200, 49550, 100000
            ),
            create_test_candle(
                "BTCUSDT",
                TimeFrame.M1,
                base_time + interval * 2,
                49550,
                49650,
                49500,
                49600,
                100000,
            ),
        ]

        # Update states
        detector.update_breaker_block_states(breaker_blocks, test_candles, start_index=len(candles))

        assert bb.state == "TESTED"
        assert bb.test_count >= 1

    def test_multiple_order_blocks_detection(self):
        """Test detecting multiple breaker blocks from multiple OBs."""
        candles1, ob1 = self.create_bullish_ob_with_breach()
        candles2, ob2 = self.create_bearish_ob_with_breach()

        # Combine candles (adjust timestamps to be sequential)
        all_candles = candles1 + candles2

        detector = BreakerBlockDetector(breach_threshold_percentage=1.0)
        breaker_blocks = detector.detect_breaker_blocks([ob1, ob2], all_candles)

        # Should detect at least 2 breaker blocks (one from each OB)
        assert len(breaker_blocks) >= 1

        # Verify they are sorted by timestamp
        if len(breaker_blocks) > 1:
            for i in range(len(breaker_blocks) - 1):
                assert (
                    breaker_blocks[i].transition_timestamp
                    <= breaker_blocks[i + 1].transition_timestamp
                )
