"""
Tests for multi-timeframe market structure analysis system.

Tests the integration of liquidity zones, sweeps, BMS, and trend recognition
across multiple timeframes with consistency verification and conflict resolution.
"""

import pytest
from datetime import datetime, timedelta
from typing import List

from src.models.candle import Candle
from src.core.constants import TimeFrame
from src.indicators.multi_timeframe_engine import (
    MarketStructure,
    ConsistencyLevel,
    StructureBias,
    TimeframeMarketStructure,
    MultiTimeframeMarketStructure,
    MultiTimeframeMarketStructureAnalyzer,
)
from src.indicators.trend_recognition import TrendDirection, TrendState
from src.indicators.liquidity_zone import LiquidityLevel
from src.indicators.liquidity_sweep import LiquiditySweep


# --- Test Fixtures ---

@pytest.fixture
def bullish_h1_candles() -> List[Candle]:
    """Generate 1-hour bullish trending candles with clear swing points."""
    candles = []
    base_time = int(datetime(2024, 1, 1, 0, 0).timestamp() * 1000)
    base_price = 50000.0

    for i in range(100):
        # Create realistic price action with clear swings
        # Every 5-7 candles, create a pullback for swing point formation
        if i % 6 == 0 and i > 0:
            # Pullback candle (bearish) - creates swing high
            open_price = base_price + (i * 50)
            close = open_price - 200  # Bearish pullback
        else:
            # Bullish candle - overall uptrend
            open_price = base_price + (i * 50)
            close = open_price + 150  # Strong bullish move

        # Ensure close within [low, high] and add wicks for swing detection
        high = max(open_price, close) + 100
        low = min(open_price, close) - 80

        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.H1,
            timestamp=base_time + (i * 3600000),  # 1 hour intervals
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=1000000.0 + i * 10000,
            is_closed=True
        ))

    return candles


@pytest.fixture
def bearish_h1_candles() -> List[Candle]:
    """Generate 1-hour bearish trending candles with clear swing points."""
    candles = []
    base_time = int(datetime(2024, 1, 1, 0, 0).timestamp() * 1000)
    base_price = 55000.0

    for i in range(100):
        # Create realistic price action with clear swings
        # Every 6 candles, create a bounce for swing point formation
        if i % 6 == 0 and i > 0:
            # Bounce candle (bullish) - creates swing low
            open_price = base_price - (i * 50)
            close = open_price + 200  # Bullish bounce
        else:
            # Bearish candle - overall downtrend
            open_price = base_price - (i * 50)
            close = open_price - 150  # Strong bearish move

        # Ensure close within [low, high] and add wicks for swing detection
        high = max(open_price, close) + 80
        low = min(open_price, close) - 100

        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.H1,
            timestamp=base_time + (i * 3600000),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=1000000.0 + i * 10000,
            is_closed=True
        ))

    return candles


@pytest.fixture
def ranging_h1_candles() -> List[Candle]:
    """Generate 1-hour ranging candles."""
    candles = []
    base_time = int(datetime(2024, 1, 1, 0, 0).timestamp() * 1000)
    base_price = 50000.0

    for i in range(100):
        # Ranging between 49800 and 50200 with clear swings
        oscillation = (i % 12) - 6  # Creates wave pattern -6 to +6
        open_price = base_price + (oscillation * 60)

        # Alternate bullish/bearish candles for swings
        if i % 2 == 0:
            close = open_price + 80  # Bullish
        else:
            close = open_price - 80  # Bearish

        # Ensure close within [low, high] and add wicks
        high = max(open_price, close) + 60
        low = min(open_price, close) - 60

        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.H1,
            timestamp=base_time + (i * 3600000),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=1000000.0,
            is_closed=True
        ))

    return candles


@pytest.fixture
def bullish_m15_candles() -> List[Candle]:
    """Generate 15-minute bullish trending candles."""
    candles = []
    base_time = int(datetime(2024, 1, 1, 0, 0).timestamp() * 1000)
    base_price = 50000.0

    for i in range(400):  # 100 hours = 400 15-min candles
        # Create swings every 6 candles
        if i % 6 == 0 and i > 0:
            open_price = base_price + (i * 12)
            close = open_price - 40  # Pullback
        else:
            open_price = base_price + (i * 12)
            close = open_price + 30  # Bullish

        high = max(open_price, close) + 20
        low = min(open_price, close) - 15

        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M15,
            timestamp=base_time + (i * 900000),  # 15 min intervals
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=250000.0 + i * 200,
            is_closed=True
        ))

    return candles


@pytest.fixture
def bullish_m1_candles() -> List[Candle]:
    """Generate 1-minute bullish trending candles."""
    candles = []
    base_time = int(datetime(2024, 1, 1, 0, 0).timestamp() * 1000)
    base_price = 50000.0

    for i in range(1000):  # Last ~16 hours of 1-min candles
        # Create swings every 6 candles
        if i % 6 == 0 and i > 0:
            open_price = base_price + (i * 0.8)
            close = open_price - 5  # Pullback
        else:
            open_price = base_price + (i * 0.8)
            close = open_price + 4  # Bullish

        high = max(open_price, close) + 3
        low = min(open_price, close) - 2

        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            timestamp=base_time + (i * 60000),  # 1 min intervals
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=10000.0 + i * 10,
            is_closed=True
        ))

    return candles


@pytest.fixture
def analyzer() -> MultiTimeframeMarketStructureAnalyzer:
    """Create market structure analyzer instance."""
    return MultiTimeframeMarketStructureAnalyzer()


# --- Single Timeframe Analysis Tests ---

class TestTimeframeAnalysis:
    """Test analysis of individual timeframes."""

    def test_bullish_h1_analysis(self, analyzer, bullish_h1_candles):
        """Test that bullish H1 candles are correctly analyzed."""
        result = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.H1)

        assert result.timeframe == TimeFrame.H1
        assert result.timestamp > 0

        # Should have liquidity levels (at minimum)
        total_liquidity = len(result.buy_side_levels) + len(result.sell_side_levels)
        assert total_liquidity > 0, "Should detect at least some liquidity levels"

        # Should have swing points
        total_swings = len(result.swing_highs) + len(result.swing_lows)
        assert total_swings > 0, "Should detect at least some swing points"

        # Market structure should be determined
        assert result.market_structure is not None

    def test_bearish_h1_analysis(self, analyzer, bearish_h1_candles):
        """Test that bearish H1 candles are correctly analyzed."""
        result = analyzer.analyze_timeframe(bearish_h1_candles, TimeFrame.H1)

        assert result.timeframe == TimeFrame.H1

        # Should have some liquidity and swing points
        total_liquidity = len(result.buy_side_levels) + len(result.sell_side_levels)
        total_swings = len(result.swing_highs) + len(result.swing_lows)

        assert total_liquidity > 0, "Should detect liquidity levels"
        assert total_swings > 0, "Should detect swing points"
        assert result.market_structure is not None

    def test_ranging_h1_analysis(self, analyzer, ranging_h1_candles):
        """Test that ranging H1 candles are correctly identified."""
        result = analyzer.analyze_timeframe(ranging_h1_candles, TimeFrame.H1)

        assert result.timeframe == TimeFrame.H1

        # Should detect ranging/sideways
        assert result.market_structure == MarketStructure.RANGING
        assert result.structure_strength < 6.0  # Weaker structure in ranging

    def test_insufficient_candles(self, analyzer):
        """Test handling of insufficient candle data."""
        few_candles = [
            Candle(
                symbol="BTCUSDT",
                timeframe=TimeFrame.H1,
                timestamp=int(datetime.now().timestamp() * 1000),
                open=50000, high=50100, low=49900, close=50050,
                volume=1000, is_closed=True
            )
            for _ in range(5)
        ]

        result = analyzer.analyze_timeframe(few_candles, TimeFrame.H1)

        # Should return structure but with minimal data
        assert result.timeframe == TimeFrame.H1
        assert result.timestamp > 0


# --- Multi-Timeframe Integration Tests ---

class TestMultiTimeframeIntegration:
    """Test integration across multiple timeframes."""

    def test_perfect_bullish_alignment(self, analyzer, bullish_h1_candles,
                                      bullish_m15_candles, bullish_m1_candles):
        """Test perfect alignment when all timeframes are bullish."""
        result = analyzer.analyze_multi_timeframe(
            bullish_h1_candles,
            bullish_m15_candles,
            bullish_m1_candles
        )

        assert result.symbol == "BTCUSDT"
        assert result.timestamp > 0

        # All structures should exist
        assert result.h1_structure is not None
        assert result.m15_structure is not None
        assert result.m1_structure is not None

        # Should show high consistency
        assert result.consistency_level in [ConsistencyLevel.PERFECT, ConsistencyLevel.HIGH]

        # Should have bullish bias
        assert result.overall_bias in [StructureBias.BULLISH, StructureBias.STRONGLY_BULLISH]
        assert result.bias_strength > 6.0

        # H1 should be primary
        assert result.primary_timeframe == TimeFrame.H1

        # Should have recommendations
        assert len(result.recommendations) > 0

    def test_conflicting_timeframes(self, analyzer, bullish_h1_candles,
                                   bearish_h1_candles, ranging_h1_candles):
        """Test conflict detection when timeframes disagree."""
        # Use bullish H1, ranging M15, bearish M1 to create conflicts
        result = analyzer.analyze_multi_timeframe(
            bullish_h1_candles,
            ranging_h1_candles,  # Use as M15
            bearish_h1_candles   # Use as M1
        )

        # Should detect conflicts
        assert result.consistency_level in [ConsistencyLevel.LOW, ConsistencyLevel.CONFLICT]
        assert len(result.conflicts) > 0

        # H1 should still dominate (bullish)
        assert result.overall_bias in [StructureBias.BULLISH, StructureBias.STRONGLY_BULLISH]
        assert result.primary_timeframe == TimeFrame.H1

    def test_h1_priority_override(self, analyzer, bearish_h1_candles,
                                 bullish_m15_candles, bullish_m1_candles):
        """Test that H1 timeframe has priority in conflicts."""
        # H1 bearish, but M15 and M1 bullish
        result = analyzer.analyze_multi_timeframe(
            bearish_h1_candles,
            bullish_m15_candles,
            bullish_m1_candles
        )

        # H1 should win despite lower timeframes
        assert result.overall_bias in [StructureBias.BEARISH, StructureBias.STRONGLY_BEARISH]
        assert result.primary_timeframe == TimeFrame.H1

        # Should have conflicts noted
        assert len(result.conflicts) > 0


# --- Consistency Verification Tests ---

class TestConsistencyVerification:
    """Test timeframe consistency verification logic."""

    def test_perfect_consistency(self, analyzer, bullish_h1_candles):
        """Test perfect consistency when all timeframes agree."""
        # Use same bullish pattern for all timeframes
        h1_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.H1)
        m15_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.M15)
        m1_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.M1)

        consistency = analyzer._verify_consistency(h1_struct, m15_struct, m1_struct)

        # Should be perfect or high consistency
        assert consistency in [ConsistencyLevel.PERFECT, ConsistencyLevel.HIGH]

    def test_conflict_detection(self, analyzer, bullish_h1_candles, bearish_h1_candles):
        """Test conflict detection when timeframes disagree."""
        h1_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.H1)
        m15_struct = analyzer.analyze_timeframe(bearish_h1_candles, TimeFrame.M15)
        m1_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.M1)

        consistency = analyzer._verify_consistency(h1_struct, m15_struct, m1_struct)

        # Should detect conflicts
        assert consistency in [ConsistencyLevel.LOW, ConsistencyLevel.CONFLICT, ConsistencyLevel.MODERATE]


# --- Conflict Resolution Tests ---

class TestConflictResolution:
    """Test conflict resolution with higher timeframe priority."""

    def test_h1_dominance(self, analyzer, bullish_h1_candles, bearish_h1_candles):
        """Test that H1 dominates in conflict situations."""
        h1_bullish = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.H1)
        m15_bearish = analyzer.analyze_timeframe(bearish_h1_candles, TimeFrame.M15)
        m1_bearish = analyzer.analyze_timeframe(bearish_h1_candles, TimeFrame.M1)

        bias, strength, primary_tf, conflicts = analyzer._resolve_conflicts(
            h1_bullish, m15_bearish, m1_bearish
        )

        # H1 should win
        assert bias in [StructureBias.BULLISH, StructureBias.STRONGLY_BULLISH]
        assert primary_tf == TimeFrame.H1
        assert len(conflicts) > 0  # Should note the conflicts


# --- Recommendation Generation Tests ---

class TestRecommendations:
    """Test trading recommendation generation."""

    def test_strong_trend_recommendations(self, analyzer, bullish_h1_candles):
        """Test recommendations for strong trending market."""
        h1_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.H1)
        m15_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.M15)
        m1_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.M1)

        recommendations = analyzer._generate_recommendations(
            h1_struct, m15_struct, m1_struct,
            StructureBias.STRONGLY_BULLISH,
            ConsistencyLevel.PERFECT
        )

        assert len(recommendations) > 0
        # Should recommend long entries
        assert any("long" in rec.lower() or "bullish" in rec.lower() for rec in recommendations)

    def test_conflict_warning_recommendations(self, analyzer, bullish_h1_candles, bearish_h1_candles):
        """Test warnings when timeframes conflict."""
        h1_struct = analyzer.analyze_timeframe(bullish_h1_candles, TimeFrame.H1)
        m15_struct = analyzer.analyze_timeframe(bearish_h1_candles, TimeFrame.M15)
        m1_struct = analyzer.analyze_timeframe(bearish_h1_candles, TimeFrame.M1)

        recommendations = analyzer._generate_recommendations(
            h1_struct, m15_struct, m1_struct,
            StructureBias.NEUTRAL,
            ConsistencyLevel.CONFLICT
        )

        assert len(recommendations) > 0
        # Should warn about conflicts
        assert any("conflict" in rec.lower() or "avoid" in rec.lower() for rec in recommendations)


# --- Data Structure Tests ---

class TestDataStructures:
    """Test data structure functionality."""

    def test_timeframe_market_structure(self):
        """Test TimeframeMarketStructure data class."""
        structure = TimeframeMarketStructure(
            timeframe=TimeFrame.H1,
            timestamp=int(datetime.now().timestamp() * 1000),
            market_structure=MarketStructure.BULLISH,
            structure_strength=7.5
        )

        assert structure.timeframe == TimeFrame.H1
        assert structure.market_structure == MarketStructure.BULLISH
        assert structure.structure_strength == 7.5

    def test_multi_timeframe_structure(self):
        """Test MultiTimeframeMarketStructure data class."""
        structure = MultiTimeframeMarketStructure(
            symbol="BTCUSDT",
            timestamp=int(datetime.now().timestamp() * 1000),
            consistency_level=ConsistencyLevel.HIGH,
            overall_bias=StructureBias.BULLISH,
            bias_strength=8.0
        )

        assert structure.symbol == "BTCUSDT"
        assert structure.consistency_level == ConsistencyLevel.HIGH
        assert structure.overall_bias == StructureBias.BULLISH
        assert structure.bias_strength == 8.0

    def test_alignment_score_calculation(self):
        """Test alignment score calculation."""
        structure = MultiTimeframeMarketStructure(
            symbol="BTCUSDT",
            timestamp=int(datetime.now().timestamp() * 1000)
        )

        # Test with no timeframe data
        score = structure.get_timeframe_alignment_score()
        assert score == 0.0  # No data

    def test_strong_trend_detection(self):
        """Test strong trend detection logic."""
        structure = MultiTimeframeMarketStructure(
            symbol="BTCUSDT",
            timestamp=int(datetime.now().timestamp() * 1000),
            consistency_level=ConsistencyLevel.PERFECT,
            overall_bias=StructureBias.STRONGLY_BULLISH,
            bias_strength=8.5
        )

        assert structure.is_strong_trend() is True
        assert structure.is_ranging_market() is False

    def test_ranging_market_detection(self):
        """Test ranging market detection logic."""
        structure = MultiTimeframeMarketStructure(
            symbol="BTCUSDT",
            timestamp=int(datetime.now().timestamp() * 1000),
            consistency_level=ConsistencyLevel.CONFLICT,
            overall_bias=StructureBias.NEUTRAL,
            bias_strength=3.0
        )

        assert structure.is_ranging_market() is True
        assert structure.is_strong_trend() is False

    def test_entry_timeframe_recommendation(self):
        """Test entry timeframe recommendation logic."""
        # Strong trend case
        structure_strong = MultiTimeframeMarketStructure(
            symbol="BTCUSDT",
            timestamp=int(datetime.now().timestamp() * 1000),
            consistency_level=ConsistencyLevel.PERFECT,
            overall_bias=StructureBias.STRONGLY_BULLISH,
            bias_strength=9.0
        )

        assert structure_strong.get_entry_timeframe_recommendation() == TimeFrame.M15

        # Ranging case
        structure_ranging = MultiTimeframeMarketStructure(
            symbol="BTCUSDT",
            timestamp=int(datetime.now().timestamp() * 1000),
            consistency_level=ConsistencyLevel.CONFLICT,
            overall_bias=StructureBias.NEUTRAL,
            bias_strength=2.0
        )

        assert structure_ranging.get_entry_timeframe_recommendation() is None


# --- Integration with Existing Engine Tests ---

class TestEngineIntegration:
    """Test integration with existing MultiTimeframeIndicatorEngine."""

    def test_compatibility_with_existing_engine(self, analyzer):
        """Test that new analyzer works with existing engine data."""
        # This ensures the new analyzer doesn't break existing functionality
        assert analyzer.liquidity_zone_detector is not None
        assert analyzer.liquidity_sweep_detector is not None
        assert analyzer.trend_recognition_engine is not None
        assert analyzer.bms_detector is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
