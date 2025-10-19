"""
Unit tests for Fair Value Gap detection and analysis.
"""

import pytest
from typing import List

from src.indicators.fair_value_gap import (
    FairValueGap,
    FVGType,
    FVGState,
    FVGDetector
)
from src.models.candle import Candle
from src.core.constants import TimeFrame


class TestFairValueGap:
    """Test FairValueGap data class."""

    def test_fvg_creation(self):
        """Test creating a valid Fair Value Gap."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        assert fvg.type == FVGType.BULLISH
        assert fvg.high == 50000.0
        assert fvg.low == 49800.0
        assert fvg.size_pips == 20.0
        assert fvg.size_percentage == 0.4
        assert fvg.state == FVGState.ACTIVE
        assert fvg.filled_percentage == 0.0

    def test_fvg_validation_high_low(self):
        """Test that high must be greater than low."""
        with pytest.raises(ValueError, match="High .* must be greater than low"):
            FairValueGap(
                type=FVGType.BULLISH,
                high=49000.0,
                low=50000.0,  # Invalid: low > high
                origin_timestamp=1704067200000,
                origin_candle_index=5,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                size_pips=10.0,
                size_percentage=0.2,
                volume=1000000.0
            )

    def test_fvg_validation_size_pips(self):
        """Test size_pips must be non-negative."""
        with pytest.raises(ValueError, match="Size pips must be non-negative"):
            FairValueGap(
                type=FVGType.BULLISH,
                high=50000.0,
                low=49800.0,
                origin_timestamp=1704067200000,
                origin_candle_index=5,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                size_pips=-10.0,  # Invalid: negative
                size_percentage=0.2,
                volume=1000000.0
            )

    def test_fvg_validation_filled_percentage(self):
        """Test filled_percentage must be between 0 and 100."""
        with pytest.raises(ValueError, match="Filled percentage must be between 0 and 100"):
            FairValueGap(
                type=FVGType.BULLISH,
                high=50000.0,
                low=49800.0,
                origin_timestamp=1704067200000,
                origin_candle_index=5,
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                size_pips=20.0,
                size_percentage=0.4,
                volume=1000000.0,
                filled_percentage=150.0  # Invalid: > 100
            )

    def test_fvg_range_and_midpoint(self):
        """Test calculating FVG range and midpoint."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        assert fvg.get_range() == 200.0
        assert fvg.get_midpoint() == 49900.0

    def test_fvg_contains_price(self):
        """Test checking if price is within FVG."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        assert fvg.contains_price(49900.0)
        assert fvg.contains_price(49800.0)  # Lower boundary
        assert fvg.contains_price(50000.0)  # Upper boundary
        assert not fvg.contains_price(49700.0)
        assert not fvg.contains_price(50100.0)

    def test_fvg_price_position(self):
        """Test checking price position relative to FVG."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        assert fvg.is_price_above(50100.0)
        assert not fvg.is_price_above(49900.0)
        assert fvg.is_price_below(49700.0)
        assert not fvg.is_price_below(49900.0)

    def test_fvg_update_fill_status_bullish(self):
        """Test updating fill status for bullish FVG."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        # Test partial fill (50% from bottom)
        fill_time = 1704067500000
        fvg.update_fill_status(49900.0, fill_time)

        assert fvg.state == FVGState.PARTIAL
        assert fvg.filled_percentage == pytest.approx(50.0, rel=0.01)
        assert fvg.first_fill_timestamp == fill_time

        # Test complete fill
        fvg.update_fill_status(50000.0, fill_time + 1000)
        assert fvg.state == FVGState.FILLED
        assert fvg.filled_percentage == 100.0

    def test_fvg_update_fill_status_bearish(self):
        """Test updating fill status for bearish FVG."""
        fvg = FairValueGap(
            type=FVGType.BEARISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        # Test partial fill (50% from top)
        fill_time = 1704067500000
        fvg.update_fill_status(49900.0, fill_time)

        assert fvg.state == FVGState.PARTIAL
        assert fvg.filled_percentage == pytest.approx(50.0, rel=0.01)
        assert fvg.first_fill_timestamp == fill_time

    def test_fvg_mark_expired(self):
        """Test marking FVG as expired."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        fvg.mark_expired()
        assert fvg.state == FVGState.EXPIRED

    def test_fvg_to_dict(self):
        """Test converting FVG to dictionary."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        fvg_dict = fvg.to_dict()

        assert fvg_dict['type'] == 'BULLISH'
        assert fvg_dict['high'] == 50000.0
        assert fvg_dict['low'] == 49800.0
        assert fvg_dict['size_pips'] == 20.0
        assert fvg_dict['size_percentage'] == 0.4
        assert fvg_dict['range'] == 200.0
        assert fvg_dict['midpoint'] == 49900.0


class TestFVGDetector:
    """Test FVGDetector class."""

    def create_test_candles(self) -> List[Candle]:
        """Create test candle data for FVG detection."""
        base_time = 1704067200000
        candles = []

        # Create 10 test candles
        prices = [
            (49000, 49500, 48900, 49200),  # 0
            (49200, 49400, 49100, 49300),  # 1
            (49300, 49600, 49250, 49500),  # 2
            (49500, 49800, 49450, 49700),  # 3
            (49700, 50500, 49650, 50400),  # 4 - Strong upward move
            (50400, 50600, 50300, 50500),  # 5
        ]

        for i, (o, h, l, c) in enumerate(prices):
            candles.append(Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.M15,
                timestamp=base_time + (i * 900000),  # 15 minutes apart
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=1000000.0,
                is_closed=True
            ))

        return candles

    def create_bullish_fvg_candles(self) -> List[Candle]:
        """Create candles with a clear bullish FVG pattern."""
        base_time = 1704067200000

        # Bullish FVG: candle[0].high < candle[2].low
        candles = [
            Candle("BTCUSDT", TimeFrame.M15, base_time, 49000, 49500, 48900, 49200, 1000000, True),  # 0: high=49500
            Candle("BTCUSDT", TimeFrame.M15, base_time + 900000, 49200, 50200, 49100, 50000, 1500000, True),  # 1: gap creator
            Candle("BTCUSDT", TimeFrame.M15, base_time + 1800000, 50000, 50300, 49900, 50200, 1200000, True),  # 2: low=49900
        ]
        # Gap exists between 49500 (candle 0 high) and 49900 (candle 2 low) = 400 pips gap

        return candles

    def create_bearish_fvg_candles(self) -> List[Candle]:
        """Create candles with a clear bearish FVG pattern."""
        base_time = 1704067200000

        # Bearish FVG: candle[0].low > candle[2].high
        candles = [
            Candle("BTCUSDT", TimeFrame.M15, base_time, 50000, 50500, 49900, 50200, 1000000, True),  # 0: low=49900
            Candle("BTCUSDT", TimeFrame.M15, base_time + 900000, 50200, 50300, 49200, 49400, 1500000, True),  # 1: gap creator
            Candle("BTCUSDT", TimeFrame.M15, base_time + 1800000, 49400, 49500, 49200, 49300, 1200000, True),  # 2: high=49500
        ]
        # Gap exists between 49500 (candle 2 high) and 49900 (candle 0 low) = 400 pips gap

        return candles

    def test_detector_initialization(self):
        """Test FVG detector initialization."""
        detector = FVGDetector(
            min_gap_size_pips=5.0,
            min_gap_size_percentage=0.1,
            use_pip_threshold=True,
            pip_size=0.0001
        )

        assert detector.min_gap_size_pips == 5.0
        assert detector.min_gap_size_percentage == 0.1
        assert detector.use_pip_threshold is True
        assert detector.pip_size == 0.0001

    def test_calculate_gap_size(self):
        """Test gap size calculation."""
        detector = FVGDetector(pip_size=1.0)  # 1 pip = 1.0 for simplicity

        size_pips, size_percentage = detector.calculate_gap_size(
            gap_high=50000.0,
            gap_low=49800.0,
            reference_price=50000.0
        )

        assert size_pips == 200.0  # (50000 - 49800) / 1.0
        assert size_percentage == pytest.approx(0.4, rel=0.01)  # (200 / 50000) * 100

    def test_meets_threshold_pips(self):
        """Test threshold checking with pip-based filtering."""
        detector = FVGDetector(min_gap_size_pips=10.0, use_pip_threshold=True)

        assert detector.meets_threshold(15.0, 0.1)  # 15 pips >= 10 pips
        assert not detector.meets_threshold(5.0, 0.5)  # 5 pips < 10 pips

    def test_meets_threshold_percentage(self):
        """Test threshold checking with percentage-based filtering."""
        detector = FVGDetector(
            min_gap_size_percentage=0.2,
            use_pip_threshold=False
        )

        assert detector.meets_threshold(5.0, 0.3)  # 0.3% >= 0.2%
        assert not detector.meets_threshold(20.0, 0.1)  # 0.1% < 0.2%

    def test_detect_bullish_fvg(self):
        """Test detecting bullish Fair Value Gap."""
        candles = self.create_bullish_fvg_candles()
        detector = FVGDetector(min_gap_size_pips=0.0, pip_size=1.0)

        fvg = detector.detect_bullish_fvg(candles, 0)

        assert fvg is not None
        assert fvg.type == FVGType.BULLISH
        assert fvg.low == 49500.0  # candle[0].high
        assert fvg.high == 49900.0  # candle[2].low
        assert fvg.origin_candle_index == 1
        assert fvg.size_pips == 400.0
        assert fvg.state == FVGState.ACTIVE

    def test_detect_bearish_fvg(self):
        """Test detecting bearish Fair Value Gap."""
        candles = self.create_bearish_fvg_candles()
        detector = FVGDetector(min_gap_size_pips=0.0, pip_size=1.0)

        fvg = detector.detect_bearish_fvg(candles, 0)

        assert fvg is not None
        assert fvg.type == FVGType.BEARISH
        assert fvg.low == 49500.0  # candle[2].high
        assert fvg.high == 49900.0  # candle[0].low
        assert fvg.origin_candle_index == 1
        assert fvg.size_pips == 400.0
        assert fvg.state == FVGState.ACTIVE

    def test_detect_fvg_with_threshold_filtering(self):
        """Test FVG detection with threshold filtering."""
        candles = self.create_bullish_fvg_candles()

        # With high threshold - should filter out
        detector_high = FVGDetector(min_gap_size_pips=500.0, pip_size=1.0)
        fvg_filtered = detector_high.detect_bullish_fvg(candles, 0)
        assert fvg_filtered is None

        # With low threshold - should detect
        detector_low = FVGDetector(min_gap_size_pips=100.0, pip_size=1.0)
        fvg_detected = detector_low.detect_bullish_fvg(candles, 0)
        assert fvg_detected is not None

    def test_detect_no_fvg_pattern(self):
        """Test that no FVG is detected when pattern doesn't exist."""
        base_time = 1704067200000

        # No gap - continuous price movement
        candles = [
            Candle("BTCUSDT", TimeFrame.M15, base_time, 49000, 49500, 48900, 49200, 1000000, True),
            Candle("BTCUSDT", TimeFrame.M15, base_time + 900000, 49200, 49600, 49100, 49400, 1000000, True),
            Candle("BTCUSDT", TimeFrame.M15, base_time + 1800000, 49400, 49700, 49300, 49600, 1000000, True),
        ]

        detector = FVGDetector(min_gap_size_pips=0.0, pip_size=1.0)

        bullish_fvg = detector.detect_bullish_fvg(candles, 0)
        bearish_fvg = detector.detect_bearish_fvg(candles, 0)

        assert bullish_fvg is None
        assert bearish_fvg is None

    def test_detect_fair_value_gaps(self):
        """Test detecting all FVGs in candle data."""
        # Create mixed data with both bullish and bearish FVGs
        base_time = 1704067200000
        candles = []

        # Add bullish FVG pattern
        candles.extend([
            Candle("BTCUSDT", TimeFrame.M15, base_time, 49000, 49500, 48900, 49200, 1000000, True),
            Candle("BTCUSDT", TimeFrame.M15, base_time + 900000, 49200, 50200, 49100, 50000, 1500000, True),
            Candle("BTCUSDT", TimeFrame.M15, base_time + 1800000, 50000, 50300, 49900, 50200, 1200000, True),
        ])

        # Add bearish FVG pattern
        candles.extend([
            Candle("BTCUSDT", TimeFrame.M15, base_time + 2700000, 50200, 50500, 50100, 50300, 1000000, True),
            Candle("BTCUSDT", TimeFrame.M15, base_time + 3600000, 50300, 50400, 49200, 49400, 1500000, True),
            Candle("BTCUSDT", TimeFrame.M15, base_time + 4500000, 49400, 49500, 49200, 49300, 1200000, True),
        ])

        detector = FVGDetector(min_gap_size_pips=0.0, pip_size=1.0)
        fvgs = detector.detect_fair_value_gaps(candles)

        assert len(fvgs) == 2
        assert fvgs[0].type == FVGType.BULLISH
        assert fvgs[1].type == FVGType.BEARISH

    def test_detect_insufficient_candles(self):
        """Test that detector raises error with insufficient candles."""
        candles = [
            Candle("BTCUSDT", TimeFrame.M15, 1704067200000, 49000, 49500, 48900, 49200, 1000000, True)
        ]

        detector = FVGDetector()

        with pytest.raises(ValueError, match="Insufficient candles for FVG detection"):
            detector.detect_fair_value_gaps(candles)

    def test_update_fvg_states(self):
        """Test updating FVG states based on current price action."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        # Create candle that enters the gap
        current_candles = [
            Candle(
                "BTCUSDT", TimeFrame.M15, 1704068000000,
                49850, 49950, 49800, 49900,
                1000000, True
            )
        ]

        detector = FVGDetector()
        detector.update_fvg_states([fvg], current_candles)

        assert fvg.state == FVGState.PARTIAL
        assert fvg.filled_percentage > 0

    def test_update_fvg_states_complete_fill(self):
        """Test FVG being marked as filled when price breaks through."""
        fvg = FairValueGap(
            type=FVGType.BULLISH,
            high=50000.0,
            low=49800.0,
            origin_timestamp=1704067200000,
            origin_candle_index=5,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            size_pips=20.0,
            size_percentage=0.4,
            volume=1000000.0
        )

        # Create candle that completely breaks through the gap
        current_candles = [
            Candle(
                "BTCUSDT", TimeFrame.M15, 1704068000000,
                49700, 49750, 49600, 49700,  # Low below gap
                1000000, True
            )
        ]

        detector = FVGDetector()
        detector.update_fvg_states([fvg], current_candles)

        assert fvg.state == FVGState.FILLED
        assert fvg.filled_percentage == 100.0
