"""
Unit tests for Strategy B (Aggressive Trading Strategy).
"""

from datetime import datetime

from src.core.constants import PositionSide, TimeFrame
from src.strategies.base_strategy import TradingSignal
from src.strategies.strategy_b import StrategyB


class TestStrategyBInitialization:
    """Test Strategy B initialization and configuration."""

    def test_default_initialization(self):
        """Test strategy initialization with default parameters."""
        strategy = StrategyB()

        assert strategy.name == "Strategy_B_Aggressive"
        assert strategy.enabled is True
        assert strategy.min_confidence == 0.65
        assert strategy.risk_reward_ratio == 3.0
        assert strategy.max_sweep_candles_ago == 3
        assert strategy.min_fvg_strength == 0.6
        assert strategy.volatility_adjustment_enabled is True
        assert strategy.primary_tf == TimeFrame.M15

    def test_custom_initialization(self):
        """Test strategy initialization with custom parameters."""
        strategy = StrategyB(
            min_confidence=0.75,
            risk_reward_ratio=4.0,
            max_sweep_candles_ago=5,
            min_fvg_strength=0.7,
            volatility_adjustment_enabled=False,
        )

        assert strategy.min_confidence == 0.75
        assert strategy.risk_reward_ratio == 4.0
        assert strategy.max_sweep_candles_ago == 5
        assert strategy.min_fvg_strength == 0.7
        assert strategy.volatility_adjustment_enabled is False

    def test_enable_disable(self):
        """Test enabling and disabling the strategy."""
        strategy = StrategyB()

        assert strategy.enabled is True

        strategy.disable()
        assert strategy.enabled is False

        strategy.enable()
        assert strategy.enabled is True


class TestStrategyBLiquiditySweepAnalysis:
    """Test liquidity sweep detection and analysis."""

    def test_sweep_detected_bullish(self):
        """Test detection of sell-side liquidity sweep (bullish reaction)."""
        strategy = StrategyB()

        indicators = {
            "15m": {
                "liquidity_sweeps": [
                    {
                        "liquidity_side": "SELL",
                        "strength": 0.8,
                        "price": 49800,
                        "candles_ago": 2,
                    }
                ]
            }
        }

        result = strategy._analyze_liquidity_sweep(indicators)

        assert result["sweep_detected"] is True
        assert result["sweep_direction"] == PositionSide.LONG
        assert result["sweep_strength"] == 0.8
        assert result["candles_ago"] == 2

    def test_sweep_detected_bearish(self):
        """Test detection of buy-side liquidity sweep (bearish reaction)."""
        strategy = StrategyB()

        indicators = {
            "15m": {
                "liquidity_sweeps": [
                    {
                        "liquidity_side": "BUY",
                        "strength": 0.75,
                        "price": 50200,
                        "candles_ago": 1,
                    }
                ]
            }
        }

        result = strategy._analyze_liquidity_sweep(indicators)

        assert result["sweep_detected"] is True
        assert result["sweep_direction"] == PositionSide.SHORT
        assert result["sweep_strength"] == 0.75

    def test_no_sweep_detected(self):
        """Test when no liquidity sweep is detected."""
        strategy = StrategyB()

        indicators = {"15m": {"liquidity_sweeps": []}}

        result = strategy._analyze_liquidity_sweep(indicators)

        assert result["sweep_detected"] is False
        assert result["sweep_direction"] is None

    def test_sweep_too_old(self):
        """Test when liquidity sweep is too old (beyond recency window)."""
        strategy = StrategyB(max_sweep_candles_ago=3)

        indicators = {
            "15m": {
                "liquidity_sweeps": [
                    {
                        "liquidity_side": "SELL",
                        "strength": 0.8,
                        "price": 49800,
                        "candles_ago": 5,  # Too old
                    }
                ]
            }
        }

        result = strategy._analyze_liquidity_sweep(indicators)

        assert result["sweep_detected"] is False

    def test_multiple_sweeps_selects_recent(self):
        """Test that most recent sweep is selected."""
        strategy = StrategyB()

        indicators = {
            "15m": {
                "liquidity_sweeps": [
                    {
                        "liquidity_side": "SELL",
                        "strength": 0.7,
                        "price": 49800,
                        "candles_ago": 3,
                    },
                    {
                        "liquidity_side": "BUY",
                        "strength": 0.9,
                        "price": 50200,
                        "candles_ago": 1,  # Most recent
                    },
                ]
            }
        }

        result = strategy._analyze_liquidity_sweep(indicators)

        assert result["sweep_detected"] is True
        assert result["sweep_direction"] == PositionSide.SHORT
        assert result["sweep_strength"] == 0.9


class TestStrategyBFVGAnalysis:
    """Test Fair Value Gap detection and analysis."""

    def test_fvg_detected_bullish(self):
        """Test detection of bullish FVG aligned with sweep."""
        strategy = StrategyB(min_fvg_strength=0.6)

        indicators = {
            "15m": {
                "fair_value_gaps": [
                    {
                        "type": "bullish",
                        "high": 50000,
                        "low": 49900,
                        "strength": 0.8,
                        "state": "ACTIVE",
                    }
                ]
            }
        }

        result = strategy._analyze_fair_value_gap(indicators, PositionSide.LONG)

        assert result["fvg_detected"] is True
        assert result["fvg_strength"] == 0.8
        assert result["fvg_type"] == "bullish"

    def test_fvg_detected_bearish(self):
        """Test detection of bearish FVG aligned with sweep."""
        strategy = StrategyB(min_fvg_strength=0.6)

        indicators = {
            "15m": {
                "fair_value_gaps": [
                    {
                        "type": "bearish",
                        "high": 50100,
                        "low": 50000,
                        "strength": 0.75,
                        "state": "ACTIVE",
                    }
                ]
            }
        }

        result = strategy._analyze_fair_value_gap(indicators, PositionSide.SHORT)

        assert result["fvg_detected"] is True
        assert result["fvg_strength"] == 0.75

    def test_no_fvg_detected(self):
        """Test when no FVG is detected."""
        strategy = StrategyB()

        indicators = {"15m": {"fair_value_gaps": []}}

        result = strategy._analyze_fair_value_gap(indicators, PositionSide.LONG)

        assert result["fvg_detected"] is False

    def test_fvg_misaligned_direction(self):
        """Test when FVG direction doesn't match expected direction."""
        strategy = StrategyB()

        indicators = {
            "15m": {
                "fair_value_gaps": [
                    {
                        "type": "bearish",
                        "high": 50100,
                        "low": 50000,
                        "strength": 0.8,
                        "state": "ACTIVE",
                    }
                ]
            }
        }

        # Looking for LONG but only bearish FVG available
        result = strategy._analyze_fair_value_gap(indicators, PositionSide.LONG)

        assert result["fvg_detected"] is False

    def test_fvg_below_strength_threshold(self):
        """Test when FVG strength is below minimum threshold."""
        strategy = StrategyB(min_fvg_strength=0.7)

        indicators = {
            "15m": {
                "fair_value_gaps": [
                    {
                        "type": "bullish",
                        "high": 50000,
                        "low": 49900,
                        "strength": 0.5,  # Below threshold
                        "state": "ACTIVE",
                    }
                ]
            }
        }

        result = strategy._analyze_fair_value_gap(indicators, PositionSide.LONG)

        assert result["fvg_detected"] is False

    def test_fvg_not_active(self):
        """Test when FVG is not in ACTIVE state."""
        strategy = StrategyB()

        indicators = {
            "15m": {
                "fair_value_gaps": [
                    {
                        "type": "bullish",
                        "high": 50000,
                        "low": 49900,
                        "strength": 0.8,
                        "state": "FILLED",  # Not active
                    }
                ]
            }
        }

        result = strategy._analyze_fair_value_gap(indicators, PositionSide.LONG)

        assert result["fvg_detected"] is False

    def test_multiple_fvgs_selects_strongest(self):
        """Test that strongest FVG is selected."""
        strategy = StrategyB()

        indicators = {
            "15m": {
                "fair_value_gaps": [
                    {
                        "type": "bullish",
                        "high": 50000,
                        "low": 49900,
                        "strength": 0.7,
                        "state": "ACTIVE",
                    },
                    {
                        "type": "bullish",
                        "high": 49950,
                        "low": 49850,
                        "strength": 0.9,  # Strongest
                        "state": "ACTIVE",
                    },
                ]
            }
        }

        result = strategy._analyze_fair_value_gap(indicators, PositionSide.LONG)

        assert result["fvg_detected"] is True
        assert result["fvg_strength"] == 0.9


class TestStrategyBSweepFVGAlignment:
    """Test alignment verification between liquidity sweep and FVG."""

    def test_aligned_long_setup(self):
        """Test properly aligned LONG setup (sweep below, FVG above)."""
        strategy = StrategyB()

        sweep_analysis = {
            "sweep_direction": PositionSide.LONG,
            "sweep_price": 49800,
            "sweep_strength": 0.8,
            "candles_ago": 2,
        }

        fvg_analysis = {
            "fvg_high": 50000,
            "fvg_low": 49900,
            "fvg_strength": 0.8,
            "fvg_data": {"candles_ago": 3},
        }

        result = strategy._verify_sweep_fvg_alignment(
            sweep_analysis, fvg_analysis, current_price=49950
        )

        assert result["aligned"] is True
        assert result["spatial_alignment"] is True
        assert result["timing_alignment"] is True

    def test_aligned_short_setup(self):
        """Test properly aligned SHORT setup (sweep above, FVG below)."""
        strategy = StrategyB()

        sweep_analysis = {
            "sweep_direction": PositionSide.SHORT,
            "sweep_price": 50200,
            "sweep_strength": 0.75,
            "candles_ago": 1,
        }

        fvg_analysis = {
            "fvg_high": 50100,
            "fvg_low": 50000,
            "fvg_strength": 0.7,
            "fvg_data": {"candles_ago": 2},
        }

        result = strategy._verify_sweep_fvg_alignment(
            sweep_analysis, fvg_analysis, current_price=50050
        )

        assert result["aligned"] is True
        assert result["spatial_alignment"] is True

    def test_spatial_misalignment_long(self):
        """Test spatial misalignment for LONG (sweep above FVG)."""
        strategy = StrategyB()

        sweep_analysis = {
            "sweep_direction": PositionSide.LONG,
            "sweep_price": 50100,  # Above FVG (wrong)
            "sweep_strength": 0.8,
            "candles_ago": 2,
        }

        fvg_analysis = {
            "fvg_high": 50000,
            "fvg_low": 49900,
            "fvg_strength": 0.8,
            "fvg_data": {"candles_ago": 3},
        }

        result = strategy._verify_sweep_fvg_alignment(
            sweep_analysis, fvg_analysis, current_price=49950
        )

        assert result["aligned"] is False
        assert result["spatial_alignment"] is False

    def test_timing_misalignment(self):
        """Test timing misalignment (FVG too old)."""
        strategy = StrategyB(max_sweep_candles_ago=3)

        sweep_analysis = {
            "sweep_direction": PositionSide.LONG,
            "sweep_price": 49800,
            "sweep_strength": 0.8,
            "candles_ago": 2,
        }

        fvg_analysis = {
            "fvg_high": 50000,
            "fvg_low": 49900,
            "fvg_strength": 0.8,
            "fvg_data": {"candles_ago": 10},  # Too old
        }

        result = strategy._verify_sweep_fvg_alignment(
            sweep_analysis, fvg_analysis, current_price=49950
        )

        assert result["aligned"] is False
        assert result["timing_alignment"] is False

    def test_price_in_fvg_zone(self):
        """Test when price is within FVG zone."""
        strategy = StrategyB()

        sweep_analysis = {
            "sweep_direction": PositionSide.LONG,
            "sweep_price": 49800,
            "sweep_strength": 0.8,
            "candles_ago": 2,
        }

        fvg_analysis = {
            "fvg_high": 50000,
            "fvg_low": 49900,
            "fvg_strength": 0.8,
            "fvg_data": {"candles_ago": 3},
        }

        result = strategy._verify_sweep_fvg_alignment(
            sweep_analysis, fvg_analysis, current_price=49950  # In zone
        )

        assert result["price_in_fvg"] is True


class TestStrategyBConfidenceCalculation:
    """Test confidence score calculation."""

    def test_high_confidence_without_volatility(self):
        """Test high confidence calculation without volatility adjustment."""
        strategy = StrategyB(volatility_adjustment_enabled=False)

        sweep_analysis = {"sweep_strength": 0.8, "candles_ago": 1}
        fvg_analysis = {"fvg_strength": 0.9, "fvg_data": {"candles_ago": 2}}
        alignment_check = {
            "spatial_alignment": True,
            "price_in_fvg": True,
            "timing_alignment": True,
        }

        confidence = strategy._calculate_confidence(
            sweep_analysis, fvg_analysis, alignment_check, {}
        )

        assert confidence >= 0.8
        assert confidence <= 1.0

    def test_moderate_confidence(self):
        """Test moderate confidence calculation."""
        strategy = StrategyB(volatility_adjustment_enabled=False)

        sweep_analysis = {"sweep_strength": 0.6, "candles_ago": 3}
        fvg_analysis = {"fvg_strength": 0.65, "fvg_data": {"candles_ago": 4}}
        alignment_check = {
            "spatial_alignment": True,
            "price_in_fvg": False,
            "timing_alignment": True,
        }

        confidence = strategy._calculate_confidence(
            sweep_analysis, fvg_analysis, alignment_check, {}
        )

        # Expected: 0.6 + 0.195 (fvg) + 0.1 (spatial) + 0.0 (recency) = 0.895
        assert 0.85 <= confidence <= 0.95

    def test_volatility_boost_high(self):
        """Test confidence boost with high volatility."""
        strategy = StrategyB(volatility_adjustment_enabled=True)

        sweep_analysis = {"sweep_strength": 0.7, "candles_ago": 2}
        fvg_analysis = {"fvg_strength": 0.75, "fvg_data": {"candles_ago": 3}}
        alignment_check = {
            "spatial_alignment": True,
            "price_in_fvg": True,
            "timing_alignment": True,
        }
        volatility_data = {"level": "HIGH", "percentile": 75}

        confidence = strategy._calculate_confidence(
            sweep_analysis, fvg_analysis, alignment_check, volatility_data
        )

        # Should be boosted by 1.2x
        assert confidence >= 0.8

    def test_volatility_reduction_low(self):
        """Test confidence reduction with low volatility."""
        strategy = StrategyB(volatility_adjustment_enabled=True)

        sweep_analysis = {"sweep_strength": 0.8, "candles_ago": 1}
        fvg_analysis = {"fvg_strength": 0.8, "fvg_data": {"candles_ago": 2}}
        alignment_check = {
            "spatial_alignment": True,
            "price_in_fvg": True,
            "timing_alignment": True,
        }
        volatility_data = {"level": "LOW", "percentile": 25}

        confidence = strategy._calculate_confidence(
            sweep_analysis, fvg_analysis, alignment_check, volatility_data
        )

        # Base is high enough that even with 0.85x reduction, it gets capped at 1.0
        assert confidence == 1.0

    def test_confidence_capped_at_one(self):
        """Test that confidence is capped at 1.0."""
        strategy = StrategyB(volatility_adjustment_enabled=True)

        sweep_analysis = {"sweep_strength": 1.0, "candles_ago": 0}
        fvg_analysis = {"fvg_strength": 1.0, "fvg_data": {"candles_ago": 1}}
        alignment_check = {
            "spatial_alignment": True,
            "price_in_fvg": True,
            "timing_alignment": True,
        }
        volatility_data = {"level": "VERY_HIGH", "percentile": 90}

        confidence = strategy._calculate_confidence(
            sweep_analysis, fvg_analysis, alignment_check, volatility_data
        )

        assert confidence == 1.0


class TestStrategyBSignalGeneration:
    """Test complete signal generation."""

    def test_successful_long_signal(self):
        """Test generation of valid LONG signal."""
        strategy = StrategyB(min_confidence=0.65)

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "15m": {
                    "liquidity_sweeps": [
                        {
                            "liquidity_side": "SELL",
                            "strength": 0.8,
                            "price": 49800,
                            "candles_ago": 2,
                        }
                    ],
                    "fair_value_gaps": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.85,
                            "state": "ACTIVE",
                            "candles_ago": 3,
                        }
                    ],
                }
            },
            "volatility": {"level": "HIGH", "percentile": 75},
        }

        signal = strategy.analyze(market_data)

        assert signal is not None
        assert signal.direction == PositionSide.LONG
        assert signal.entry_price == 49950
        assert signal.confidence >= 0.65
        assert signal.stop_loss < signal.entry_price
        assert signal.take_profit > signal.entry_price
        assert signal.metadata["symbol"] == "BTCUSDT"
        assert signal.metadata["strategy_type"] == "aggressive"

    def test_successful_short_signal(self):
        """Test generation of valid SHORT signal."""
        strategy = StrategyB(min_confidence=0.65)

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 50050,
            "indicators": {
                "15m": {
                    "liquidity_sweeps": [
                        {
                            "liquidity_side": "BUY",
                            "strength": 0.75,
                            "price": 50200,
                            "candles_ago": 1,
                        }
                    ],
                    "fair_value_gaps": [
                        {
                            "type": "bearish",
                            "high": 50100,
                            "low": 50000,
                            "strength": 0.8,
                            "state": "ACTIVE",
                            "candles_ago": 2,
                        }
                    ],
                }
            },
            "volatility": {"level": "NORMAL", "percentile": 50},
        }

        signal = strategy.analyze(market_data)

        assert signal is not None
        assert signal.direction == PositionSide.SHORT
        assert signal.stop_loss > signal.entry_price
        assert signal.take_profit < signal.entry_price

    def test_no_signal_no_sweep(self):
        """Test that no signal is generated without liquidity sweep."""
        strategy = StrategyB()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "15m": {
                    "liquidity_sweeps": [],  # No sweep
                    "fair_value_gaps": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.85,
                            "state": "ACTIVE",
                        }
                    ],
                }
            },
        }

        signal = strategy.analyze(market_data)

        assert signal is None

    def test_no_signal_no_fvg(self):
        """Test that no signal is generated without FVG."""
        strategy = StrategyB()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "15m": {
                    "liquidity_sweeps": [
                        {
                            "liquidity_side": "SELL",
                            "strength": 0.8,
                            "price": 49800,
                            "candles_ago": 2,
                        }
                    ],
                    "fair_value_gaps": [],  # No FVG
                }
            },
        }

        signal = strategy.analyze(market_data)

        assert signal is None

    def test_no_signal_misaligned(self):
        """Test that no signal is generated when sweep and FVG are misaligned."""
        strategy = StrategyB()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "15m": {
                    "liquidity_sweeps": [
                        {
                            "liquidity_side": "SELL",
                            "strength": 0.8,
                            "price": 50100,  # Above FVG (wrong)
                            "candles_ago": 2,
                        }
                    ],
                    "fair_value_gaps": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.85,
                            "state": "ACTIVE",
                            "candles_ago": 3,
                        }
                    ],
                }
            },
        }

        signal = strategy.analyze(market_data)

        assert signal is None

    def test_disabled_strategy_no_signal(self):
        """Test that disabled strategy produces no signals."""
        strategy = StrategyB()
        strategy.disable()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "15m": {
                    "liquidity_sweeps": [
                        {
                            "liquidity_side": "SELL",
                            "strength": 0.8,
                            "price": 49800,
                            "candles_ago": 2,
                        }
                    ],
                    "fair_value_gaps": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.85,
                            "state": "ACTIVE",
                            "candles_ago": 3,
                        }
                    ],
                }
            },
        }

        signal = strategy.analyze(market_data)

        assert signal is None


class TestStrategyBSignalValidation:
    """Test signal validation logic."""

    def test_valid_long_signal(self):
        """Test validation of valid LONG signal."""
        strategy = StrategyB(min_confidence=0.65, risk_reward_ratio=3.0)

        signal = TradingSignal(
            strategy_name="Strategy_B_Aggressive",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.8,
            stop_loss=49900,
            take_profit=50300,  # 3:1 R:R
            timeframe_analysis={},
            metadata={"sweep_strength": 0.8, "fvg_strength": 0.85},
        )

        assert strategy.validate_signal(signal) is True

    def test_valid_short_signal(self):
        """Test validation of valid SHORT signal."""
        strategy = StrategyB(min_confidence=0.65, risk_reward_ratio=3.0)

        signal = TradingSignal(
            strategy_name="Strategy_B_Aggressive",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.SHORT,
            confidence=0.75,
            stop_loss=50100,
            take_profit=49700,  # 3:1 R:R
            timeframe_analysis={},
            metadata={"sweep_strength": 0.75, "fvg_strength": 0.8},
        )

        assert strategy.validate_signal(signal) is True

    def test_invalid_confidence(self):
        """Test rejection of signal with low confidence."""
        strategy = StrategyB(min_confidence=0.8)

        signal = TradingSignal(
            strategy_name="Strategy_B_Aggressive",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.6,  # Below threshold
            stop_loss=49900,
            take_profit=50300,
            timeframe_analysis={},
            metadata={"sweep_strength": 0.6, "fvg_strength": 0.7},
        )

        assert strategy.validate_signal(signal) is False

    def test_invalid_risk_reward_ratio(self):
        """Test rejection of signal with poor risk-reward ratio."""
        strategy = StrategyB(risk_reward_ratio=3.0)

        signal = TradingSignal(
            strategy_name="Strategy_B_Aggressive",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.8,
            stop_loss=49900,  # Risk: 100
            take_profit=50150,  # Reward: 150 (R:R = 1.5, too low)
            timeframe_analysis={},
            metadata={"sweep_strength": 0.8, "fvg_strength": 0.85},
        )

        assert strategy.validate_signal(signal) is False

    def test_missing_metadata(self):
        """Test rejection of signal with missing metadata."""
        strategy = StrategyB()

        signal = TradingSignal(
            strategy_name="Strategy_B_Aggressive",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.8,
            stop_loss=49900,
            take_profit=50300,
            timeframe_analysis={},
            metadata={},  # Missing sweep/FVG strength
        )

        assert strategy.validate_signal(signal) is False


class TestStrategyBVolatilityMultiplier:
    """Test volatility multiplier calculation."""

    def test_high_volatility_boost(self):
        """Test confidence boost with high volatility."""
        strategy = StrategyB()

        volatility_data = {"level": "HIGH", "percentile": 75}
        multiplier = strategy._calculate_volatility_multiplier(volatility_data)

        assert multiplier == 1.2

    def test_very_high_volatility_boost(self):
        """Test maximum confidence boost with very high volatility."""
        strategy = StrategyB()

        volatility_data = {"level": "VERY_HIGH", "percentile": 90}
        multiplier = strategy._calculate_volatility_multiplier(volatility_data)

        assert multiplier == 1.3

    def test_normal_volatility_neutral(self):
        """Test neutral multiplier with normal volatility."""
        strategy = StrategyB()

        volatility_data = {"level": "NORMAL", "percentile": 50}
        multiplier = strategy._calculate_volatility_multiplier(volatility_data)

        assert multiplier == 1.0

    def test_low_volatility_reduction(self):
        """Test confidence reduction with low volatility."""
        strategy = StrategyB()

        volatility_data = {"level": "LOW", "percentile": 25}
        multiplier = strategy._calculate_volatility_multiplier(volatility_data)

        assert multiplier == 0.85

    def test_very_low_volatility_reduction(self):
        """Test maximum confidence reduction with very low volatility."""
        strategy = StrategyB()

        volatility_data = {"level": "VERY_LOW", "percentile": 10}
        multiplier = strategy._calculate_volatility_multiplier(volatility_data)

        assert multiplier == 0.7
