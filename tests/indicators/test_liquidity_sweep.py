"""
Unit tests for Liquidity Sweep detection.
"""

import pytest
from datetime import datetime, timedelta

from src.indicators.liquidity_sweep import (
    LiquiditySweepDetector,
    LiquiditySweep,
    SweepDirection,
    SweepState,
    SweepCandidate
)
from src.indicators.liquidity_zone import (
    LiquidityLevel,
    LiquidityType,
    LiquidityState
)
from src.models.candle import Candle
from src.core.constants import TimeFrame


class TestLiquiditySweep:
    """Test LiquiditySweep data class."""

    def test_sweep_creation(self):
        """Test creating a liquidity sweep."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=1000000,
            origin_candle_index=10,
            symbol="EURUSD",
            timeframe=TimeFrame.M1,
            strength=50.0
        )

        sweep = LiquiditySweep(
            liquidity_level=level,
            direction=SweepDirection.BEARISH,
            breach_timestamp=1001000,
            breach_candle_index=15,
            breach_distance=2.5,
            reversal_strength=65.0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1,
            is_valid=True
        )

        assert sweep.liquidity_level == level
        assert sweep.direction == SweepDirection.BEARISH
        assert sweep.breach_candle_index == 15
        assert sweep.breach_distance == 2.5
        assert sweep.reversal_strength == 65.0
        assert sweep.is_valid is True

    def test_sweep_to_dict(self):
        """Test converting sweep to dictionary."""
        level = LiquidityLevel(
            type=LiquidityType.SELL_SIDE,
            price=1.0900,
            origin_timestamp=1000000,
            origin_candle_index=10,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        sweep = LiquiditySweep(
            liquidity_level=level,
            direction=SweepDirection.BULLISH,
            breach_timestamp=1001000,
            breach_candle_index=15,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        sweep_dict = sweep.to_dict()

        assert sweep_dict['direction'] == 'BULLISH'
        assert sweep_dict['breach_candle_index'] == 15
        assert sweep_dict['symbol'] == 'EURUSD'
        assert 'liquidity_level' in sweep_dict
        assert sweep_dict['liquidity_level']['price'] == 1.0900


class TestSweepCandidate:
    """Test SweepCandidate data class."""

    def test_candidate_creation(self):
        """Test creating a sweep candidate."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=1000000,
            origin_candle_index=10,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        candidate = SweepCandidate(
            level=level,
            direction=SweepDirection.BEARISH,
            breach_candle_index=15,
            breach_timestamp=1001000,
            breach_price=1.1005
        )

        assert candidate.level == level
        assert candidate.direction == SweepDirection.BEARISH
        assert candidate.breach_candle_index == 15
        assert candidate.breach_price == 1.1005
        assert candidate.state == SweepState.BREACHED


class TestLiquiditySweepDetector:
    """Test LiquiditySweepDetector class."""

    @pytest.fixture
    def detector(self):
        """Create a sweep detector for testing."""
        return LiquiditySweepDetector(
            min_breach_distance_pips=1.0,
            max_breach_distance_pips=20.0,
            reversal_confirmation_pips=3.0,
            max_candles_for_reversal=5,
            min_reversal_strength=30.0,
            pip_size=0.0001
        )

    @pytest.fixture
    def base_timestamp(self):
        """Base timestamp for test candles."""
        return int(datetime(2024, 1, 1, 0, 0).timestamp() * 1000)

    def create_candle(
        self,
        timestamp: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float = 100.0
    ) -> Candle:
        """Helper to create test candles."""
        return Candle(
            symbol="EURUSD",
            timeframe=TimeFrame.M1,
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume
        )

    def test_detector_initialization(self, detector):
        """Test detector initialization."""
        assert detector.min_breach_distance_pips == 1.0
        assert detector.max_breach_distance_pips == 20.0
        assert detector.reversal_confirmation_pips == 3.0
        assert detector.max_candles_for_reversal == 5
        assert detector.pip_size == 0.0001

    def test_buy_side_sweep_detection(self, detector, base_timestamp):
        """Test detection of buy-side liquidity sweep (bearish)."""
        # Create buy-side liquidity level at 1.1000
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1,
            strength=50.0
        )

        # Create candle sequence: approach → breach → close above → reverse below
        candles = [
            # Index 0: Level formation
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            # Index 1: Approach
            self.create_candle(base_timestamp + 60000, 1.0995, 1.0998, 1.0992, 1.0997),
            # Index 2: Breach (high goes to 1.1005)
            self.create_candle(base_timestamp + 120000, 1.0997, 1.1005, 1.0995, 1.1003),
            # Index 3: Reversal starts
            self.create_candle(base_timestamp + 180000, 1.1003, 1.1004, 1.0996, 1.0997),
            # Index 4: Reversal confirmed (close below 1.0997)
            self.create_candle(base_timestamp + 240000, 1.0997, 1.0998, 1.0990, 1.0992),
        ]

        # Run detection
        sweeps = detector.detect_sweeps(candles, [level], start_index=1)

        # Should detect one bearish sweep
        assert len(sweeps) == 1
        sweep = sweeps[0]

        assert sweep.direction == SweepDirection.BEARISH
        assert sweep.liquidity_level == level
        assert sweep.breach_candle_index == 2
        assert sweep.is_valid is True
        assert sweep.breach_distance > 1.0  # At least 1 pip beyond

    def test_sell_side_sweep_detection(self, detector, base_timestamp):
        """Test detection of sell-side liquidity sweep (bullish)."""
        # Create sell-side liquidity level at 1.0900
        level = LiquidityLevel(
            type=LiquidityType.SELL_SIDE,
            price=1.0900,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1,
            strength=50.0
        )

        # Create candle sequence: approach → breach → close below → reverse above
        candles = [
            # Index 0: Level formation
            self.create_candle(base_timestamp, 1.0905, 1.0910, 1.0900, 1.0905),
            # Index 1: Approach
            self.create_candle(base_timestamp + 60000, 1.0905, 1.0908, 1.0902, 1.0903),
            # Index 2: Breach (low goes to 1.0895)
            self.create_candle(base_timestamp + 120000, 1.0903, 1.0905, 1.0895, 1.0897),
            # Index 3: Reversal starts
            self.create_candle(base_timestamp + 180000, 1.0897, 1.0904, 1.0896, 1.0902),
            # Index 4: Reversal confirmed (close above 1.0903)
            self.create_candle(base_timestamp + 240000, 1.0902, 1.0908, 1.0901, 1.0905),
        ]

        # Run detection
        sweeps = detector.detect_sweeps(candles, [level], start_index=1)

        # Should detect one bullish sweep
        assert len(sweeps) == 1
        sweep = sweeps[0]

        assert sweep.direction == SweepDirection.BULLISH
        assert sweep.liquidity_level == level
        assert sweep.breach_candle_index == 2
        assert sweep.is_valid is True

    def test_no_sweep_on_small_breach(self, detector, base_timestamp):
        """Test that small breaches below minimum threshold are ignored."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        # Create candles with tiny breach (0.5 pips, below 1 pip minimum)
        candles = [
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            self.create_candle(base_timestamp + 60000, 1.0995, 1.10005, 1.0992, 1.0997),  # 0.5 pip breach
        ]

        sweeps = detector.detect_sweeps(candles, [level], start_index=1)

        # Should not detect sweep due to small breach
        assert len(sweeps) == 0

    def test_no_sweep_on_extreme_breach(self, detector, base_timestamp):
        """Test that extreme breaches above maximum threshold are filtered."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        # Create candles with huge breach (25 pips, above 20 pip maximum)
        candles = [
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            self.create_candle(base_timestamp + 60000, 1.0995, 1.1025, 1.0992, 1.1020),  # 25 pip breach
        ]

        sweeps = detector.detect_sweeps(candles, [level], start_index=1)

        # Should not detect sweep due to extreme breach
        assert len(sweeps) == 0

    def test_no_sweep_without_reversal(self, detector, base_timestamp):
        """Test that breach without reversal is not confirmed as sweep."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        # Create candles: breach but continue upward (no reversal)
        candles = [
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            self.create_candle(base_timestamp + 60000, 1.0995, 1.1005, 1.0992, 1.1003),  # Breach
            self.create_candle(base_timestamp + 120000, 1.1003, 1.1010, 1.1000, 1.1008),  # Continue up
            self.create_candle(base_timestamp + 180000, 1.1008, 1.1015, 1.1005, 1.1012),  # Still up
        ]

        sweeps = detector.detect_sweeps(candles, [level], start_index=1)

        # Should not detect sweep without reversal
        assert len(sweeps) == 0

    def test_sweep_timeout(self, detector, base_timestamp):
        """Test that candidates timeout if reversal takes too long."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        # Create candles: breach + close but reversal after max_candles_for_reversal
        candles = [
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            # Breach and close
            self.create_candle(base_timestamp + 60000, 1.0995, 1.1005, 1.0992, 1.1003),
            # Wait too long (> 5 candles)
            self.create_candle(base_timestamp + 120000, 1.1003, 1.1004, 1.1000, 1.1002),
            self.create_candle(base_timestamp + 180000, 1.1002, 1.1003, 1.0999, 1.1001),
            self.create_candle(base_timestamp + 240000, 1.1001, 1.1002, 1.0998, 1.1000),
            self.create_candle(base_timestamp + 300000, 1.1000, 1.1001, 1.0997, 1.0999),
            self.create_candle(base_timestamp + 360000, 1.0999, 1.1000, 1.0996, 1.0998),
            self.create_candle(base_timestamp + 420000, 1.0998, 1.0999, 1.0995, 1.0997),
            # Finally reverses but too late
            self.create_candle(base_timestamp + 480000, 1.0997, 1.0998, 1.0990, 1.0992),
        ]

        sweeps = detector.detect_sweeps(candles, [level], start_index=1)

        # Should timeout and not detect sweep
        assert len(sweeps) == 0

    def test_multiple_levels_sweep_detection(self, detector, base_timestamp):
        """Test detecting sweeps across multiple liquidity levels."""
        # Create multiple levels
        buy_side_level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        sell_side_level = LiquidityLevel(
            type=LiquidityType.SELL_SIDE,
            price=1.0900,
            origin_timestamp=base_timestamp + 60000,
            origin_candle_index=1,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        candles = [
            # Index 0: Buy-side level formation
            self.create_candle(base_timestamp, 1.0950, 1.1000, 1.0945, 1.0950),
            # Index 1: Sell-side level formation
            self.create_candle(base_timestamp + 60000, 1.0950, 1.0955, 1.0900, 1.0920),
            # Index 2: Range
            self.create_candle(base_timestamp + 120000, 1.0920, 1.0970, 1.0915, 1.0950),
            # Index 3: Buy-side sweep
            self.create_candle(base_timestamp + 180000, 1.0950, 1.1005, 1.0948, 1.1002),
            # Index 4: Reversal from buy-side
            self.create_candle(base_timestamp + 240000, 1.1002, 1.1003, 1.0990, 1.0993),
            # Index 5: Move down
            self.create_candle(base_timestamp + 300000, 1.0993, 1.0995, 1.0920, 1.0930),
            # Index 6: Sell-side sweep
            self.create_candle(base_timestamp + 360000, 1.0930, 1.0932, 1.0895, 1.0897),
            # Index 7: Reversal from sell-side
            self.create_candle(base_timestamp + 420000, 1.0897, 1.0910, 1.0896, 1.0905),
        ]

        levels = [buy_side_level, sell_side_level]
        sweeps = detector.detect_sweeps(candles, levels, start_index=2)

        # Should detect both sweeps
        assert len(sweeps) == 2

        bearish_sweeps = [s for s in sweeps if s.direction == SweepDirection.BEARISH]
        bullish_sweeps = [s for s in sweeps if s.direction == SweepDirection.BULLISH]

        assert len(bearish_sweeps) == 1
        assert len(bullish_sweeps) == 1

    def test_get_completed_sweeps_filtering(self, detector, base_timestamp):
        """Test filtering completed sweeps."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        candles = [
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            self.create_candle(base_timestamp + 60000, 1.0995, 1.1005, 1.0992, 1.1003),
            self.create_candle(base_timestamp + 120000, 1.1003, 1.1004, 1.0990, 1.0992),
        ]

        detector.detect_sweeps(candles, [level], start_index=1)

        # Get all completed sweeps
        all_sweeps = detector.get_completed_sweeps()
        assert len(all_sweeps) >= 1

        # Filter by direction
        bearish_sweeps = detector.get_completed_sweeps(direction=SweepDirection.BEARISH)
        assert all(s.direction == SweepDirection.BEARISH for s in bearish_sweeps)

    def test_clear_history(self, detector, base_timestamp):
        """Test clearing sweep history."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        candles = [
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            self.create_candle(base_timestamp + 60000, 1.0995, 1.1005, 1.0992, 1.1003),
            self.create_candle(base_timestamp + 120000, 1.1003, 1.1004, 1.0990, 1.0992),
        ]

        detector.detect_sweeps(candles, [level], start_index=1)

        # Should have history
        assert len(detector.get_completed_sweeps()) > 0

        # Clear history
        detector.clear_history()

        # Should be empty
        assert len(detector.get_completed_sweeps()) == 0
        assert len(detector.get_active_candidates()) == 0

    def test_level_state_updated_after_sweep(self, detector, base_timestamp):
        """Test that liquidity level state is updated after sweep."""
        level = LiquidityLevel(
            type=LiquidityType.BUY_SIDE,
            price=1.1000,
            origin_timestamp=base_timestamp,
            origin_candle_index=0,
            symbol="EURUSD",
            timeframe=TimeFrame.M1
        )

        # Initially active
        assert level.state == LiquidityState.ACTIVE

        candles = [
            self.create_candle(base_timestamp, 1.0995, 1.1000, 1.0990, 1.0995),
            self.create_candle(base_timestamp + 60000, 1.0995, 1.1005, 1.0992, 1.1003),
            self.create_candle(base_timestamp + 120000, 1.1003, 1.1004, 1.0990, 1.0992),
        ]

        detector.detect_sweeps(candles, [level], start_index=1)

        # Should be marked as swept
        assert level.state == LiquidityState.SWEPT
        assert level.swept_timestamp is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
