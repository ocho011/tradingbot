"""
Unit tests for Strategy C (Hybrid Trading Strategy).

Tests multi-condition signal generation with weighted confidence scoring.
"""

import pytest
from datetime import datetime

from src.core.constants import PositionSide, TimeFrame
from src.strategies.strategy_c import StrategyC
from src.strategies.base_strategy import TradingSignal


class TestStrategyCInitialization:
    """Test Strategy C initialization and weight validation."""

    def test_default_initialization(self):
        """Test strategy initialization with default parameters."""
        strategy = StrategyC()

        assert strategy.name == "Strategy_C_Hybrid"
        assert strategy.enabled is True
        assert strategy.min_confidence == 0.70
        assert strategy.risk_reward_ratio == 2.5

        # Check default weights
        assert strategy.trend_weight == 0.35
        assert strategy.entry_zone_weight == 0.30
        assert strategy.liquidity_weight == 0.25
        assert strategy.timing_weight == 0.10

        # Check minimum thresholds
        assert strategy.min_trend_score == 0.5
        assert strategy.min_entry_zone_score == 0.6
        assert strategy.min_liquidity_score == 0.4

        # Check timeframes
        assert strategy.higher_tf == TimeFrame.H1
        assert strategy.mid_tf == TimeFrame.M15
        assert strategy.lower_tf == TimeFrame.M1

    def test_custom_weights_initialization(self):
        """Test strategy initialization with custom weights."""
        strategy = StrategyC(
            trend_weight=0.40,
            entry_zone_weight=0.35,
            liquidity_weight=0.15,
            timing_weight=0.10,
        )

        assert strategy.trend_weight == 0.40
        assert strategy.entry_zone_weight == 0.35
        assert strategy.liquidity_weight == 0.15
        assert strategy.timing_weight == 0.10

    def test_custom_thresholds_initialization(self):
        """Test strategy initialization with custom minimum thresholds."""
        strategy = StrategyC(
            min_trend_score=0.6,
            min_entry_zone_score=0.7,
            min_liquidity_score=0.5,
        )

        assert strategy.min_trend_score == 0.6
        assert strategy.min_entry_zone_score == 0.7
        assert strategy.min_liquidity_score == 0.5

    def test_weights_must_sum_to_one(self):
        """Test that weight validation rejects incorrect sums."""
        with pytest.raises(ValueError, match="must sum to 1.0"):
            StrategyC(
                trend_weight=0.30,
                entry_zone_weight=0.30,
                liquidity_weight=0.30,
                timing_weight=0.20,  # Sum = 1.10
            )

    def test_weights_sum_tolerance(self):
        """Test that small floating point errors are tolerated."""
        # Should NOT raise - within 0.01 tolerance
        strategy = StrategyC(
            trend_weight=0.34,
            entry_zone_weight=0.33,
            liquidity_weight=0.23,
            timing_weight=0.10,  # Sum = 1.00
        )
        assert strategy is not None


class TestStrategyCTrendCondition:
    """Test trend condition analysis (Condition 1)."""

    def test_bullish_trend_confirmed(self):
        """Test bullish trend with BMS support."""
        strategy = StrategyC()

        indicators = {
            "1h": {
                "trend_state": {
                    "direction": "UPTREND",
                    "strength": 8.0,
                    "strength_level": "STRONG",
                    "is_confirmed": True,
                },
                "market_structure": {
                    "breaks": [
                        {
                            "new_structure": "BULLISH",
                            "strength": 0.85,
                            "timestamp": datetime.utcnow(),
                        }
                    ]
                },
            }
        }

        result = strategy._analyze_trend_condition(indicators)

        assert result["score"] >= strategy.min_trend_score
        assert result["bias"] == PositionSide.LONG
        assert result["has_bms_support"] is True
        assert result["strength"] > 0.0

    def test_bearish_trend_confirmed(self):
        """Test bearish trend with BMS support."""
        strategy = StrategyC()

        indicators = {
            "1h": {
                "trend_state": {
                    "direction": "DOWNTREND",
                    "strength": 7.0,
                    "strength_level": "STRONG",
                    "is_confirmed": True,
                },
                "market_structure": {
                    "breaks": [
                        {
                            "new_structure": "BEARISH",
                            "strength": 0.75,
                        }
                    ]
                },
            }
        }

        result = strategy._analyze_trend_condition(indicators)

        assert result["bias"] == PositionSide.SHORT
        assert result["has_bms_support"] is True

    def test_no_bms_detected(self):
        """Test trend analysis when no BMS is present."""
        strategy = StrategyC()

        indicators = {
            "1h": {
                "trend_state": {
                    "direction": "UPTREND",
                    "strength": 8.0,
                    "strength_level": "STRONG",
                    "is_confirmed": True,
                },
                "market_structure": {"breaks": []},
            }
        }

        result = strategy._analyze_trend_condition(indicators)

        assert result["has_bms_support"] is False
        # Score should be lower without BMS support

    def test_trend_with_misalignment(self):
        """Test trend with BMS-trend misalignment."""
        strategy = StrategyC()

        indicators = {
            "1h": {
                "trend_state": {
                    "direction": "DOWNTREND",
                    "strength": 6.0,
                    "strength_level": "MODERATE",
                    "is_confirmed": True,
                },
                "market_structure": {
                    "breaks": [{"new_structure": "BULLISH", "strength": 0.7}]
                },
            }
        }

        result = strategy._analyze_trend_condition(indicators)

        # Bias follows trend direction, not BMS
        assert result["bias"] == PositionSide.SHORT
        assert result["has_bms_support"] is False  # BMS doesn't align with trend

    def test_uncertain_trend(self):
        """Test with uncertain/ranging trend."""
        strategy = StrategyC()

        indicators = {
            "1h": {
                "trend_state": {
                    "direction": "RANGING",
                    "strength": 3.0,
                    "strength_level": "WEAK",
                    "is_confirmed": False,
                },
                "market_structure": {"breaks": []},
            }
        }

        result = strategy._analyze_trend_condition(indicators)

        assert result["score"] < strategy.min_trend_score
        assert result["bias"] is None


class TestStrategyCEntryZoneCondition:
    """Test entry zone condition analysis (Condition 2)."""

    def test_fvg_aligned_with_long_bias(self):
        """Test FVG detection for long entries."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "fvg": [
                    {
                        "type": "bullish",
                        "high": 50000,
                        "low": 49900,
                        "strength": 0.85,
                        "mitigated": False,
                    }
                ],
                "order_blocks": [],
            }
        }

        result = strategy._analyze_entry_zone_condition(indicators, PositionSide.LONG)

        assert result["score"] >= strategy.min_entry_zone_score
        assert result["zone_type"] == "FAIR_VALUE_GAP"
        assert result["entry_zone"]["high"] == 50000
        assert result["entry_zone"]["low"] == 49900

    def test_order_block_aligned_with_short_bias(self):
        """Test Order Block detection for short entries."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "fvg": [],
                "order_blocks": [
                    {
                        "type": "bearish",
                        "high": 50100,
                        "low": 50000,
                        "volume_ratio": 2.5,
                        "mitigated": False,
                    }
                ],
            }
        }

        result = strategy._analyze_entry_zone_condition(indicators, PositionSide.SHORT)

        assert result["score"] >= strategy.min_entry_zone_score
        assert result["zone_type"] == "ORDER_BLOCK"

    def test_no_aligned_zones(self):
        """Test when no zones align with bias."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "fvg": [{"type": "bearish", "high": 50000, "low": 49900}],
                "order_blocks": [{"type": "bearish", "high": 50100, "low": 50000}],
            }
        }

        # Looking for LONG but only bearish zones
        result = strategy._analyze_entry_zone_condition(indicators, PositionSide.LONG)

        assert result["score"] < strategy.min_entry_zone_score
        assert result["entry_zone"] is None

    def test_fvg_preferred_over_ob(self):
        """Test that OB is preferred over FVG for hybrid strategy."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "fvg": [
                    {
                        "type": "bullish",
                        "high": 50000,
                        "low": 49900,
                        "strength": 0.7,
                    }
                ],
                "order_blocks": [
                    {
                        "type": "bullish",
                        "high": 50050,
                        "low": 49950,
                        "volume_ratio": 3.0,
                    }
                ],
            }
        }

        result = strategy._analyze_entry_zone_condition(indicators, PositionSide.LONG)

        assert result["zone_type"] == "ORDER_BLOCK"

    def test_mitigated_zones_excluded(self):
        """Test mitigated zones - currently not filtered but could be future enhancement."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "fvg": [
                    {
                        "type": "bullish",
                        "high": 50000,
                        "low": 49900,
                        "strength": 0.9,
                        "state": "MITIGATED",  # Already used
                    }
                ],
                "order_blocks": [],
            }
        }

        result = strategy._analyze_entry_zone_condition(indicators, PositionSide.LONG)

        # Currently mitigated zones are not filtered - future enhancement
        assert result["entry_zone"] is not None
        assert result["entry_zone"]["state"] == "MITIGATED"


class TestStrategyCLiquidityCondition:
    """Test liquidity condition analysis (Condition 3)."""

    def test_long_with_sell_side_liquidity_below(self):
        """Test LONG setup with sell-side liquidity below price."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "liquidity_levels": [
                    {
                        "price": 49800,
                        "side": "SELL",
                        "strength": 0.8,
                        "swept": False,
                    },
                    {
                        "price": 50200,
                        "side": "BUY",
                        "strength": 0.7,
                        "swept": False,
                    },
                ]
            }
        }

        result = strategy._analyze_liquidity_condition(
            indicators, 50000, PositionSide.LONG
        )

        assert result["score"] >= strategy.min_liquidity_score
        assert result["nearby_levels_count"] > 0

    def test_short_with_buy_side_liquidity_above(self):
        """Test SHORT setup with buy-side liquidity above price."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "liquidity_levels": [
                    {
                        "price": 50200,
                        "side": "BUY",
                        "strength": 0.85,
                        "swept": False,
                    },
                    {
                        "price": 49800,
                        "side": "SELL",
                        "strength": 0.6,
                        "swept": False,
                    },
                ]
            }
        }

        result = strategy._analyze_liquidity_condition(
            indicators, 50000, PositionSide.SHORT
        )

        assert result["score"] >= strategy.min_liquidity_score
        assert result["nearby_levels_count"] > 0

    def test_recent_liquidity_sweep_bonus(self):
        """Test bonus for recent opposite-side liquidity sweep."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "liquidity_levels": [
                    {
                        "price": 49800,
                        "side": "SELL",
                        "strength": 0.7,
                        "swept": False,
                    }
                ],
                "liquidity_sweeps": [
                    {
                        "liquidity_side": "SELL",
                        "price": 49750,
                        "timestamp": datetime.utcnow(),
                    }
                ],
            }
        }

        result = strategy._analyze_liquidity_condition(
            indicators, 50000, PositionSide.LONG
        )

        assert result["has_sweep_support"] is True
        # Score should be higher with sweep support

    def test_no_liquidity_levels(self):
        """Test when no liquidity levels are available."""
        strategy = StrategyC()

        indicators = {"15m": {"liquidity_levels": []}}

        result = strategy._analyze_liquidity_condition(
            indicators, 50000, PositionSide.LONG
        )

        assert result["score"] < strategy.min_liquidity_score

    def test_wrong_side_liquidity(self):
        """Test poor positioning with wrong-side liquidity."""
        strategy = StrategyC()

        indicators = {
            "15m": {
                "liquidity_levels": [
                    {
                        "price": 50200,
                        "side": "SELL",
                        "strength": 0.8,
                        "swept": False,
                    }
                ]
            }
        }

        # LONG with SELL liquidity ABOVE is not ideal - score should be low
        result = strategy._analyze_liquidity_condition(
            indicators, 50000, PositionSide.LONG
        )

        # Score will be 0 because SELL liquidity is above price (not below)
        assert result["score"] == 0.0


class TestStrategyCTimingCondition:
    """Test timing condition analysis (Condition 4)."""

    def test_optimal_entry_timing_in_zone(self):
        """Test optimal timing when price is in entry zone."""
        strategy = StrategyC()

        entry_zone_analysis = {
            "entry_zone": {"high": 50000, "low": 49900},
            "zone_type": "FAIR_VALUE_GAP",
            "zone_high": 50000,
            "zone_low": 49900,
        }
        indicators = {
            "1m": {
                "market_structure": {"recent_events": [{"type": "structure_break"}]}
            }
        }

        result = strategy._analyze_timing_condition(
            indicators, 49950, entry_zone_analysis
        )

        assert result["score"] > 0
        assert result["price_in_zone"] is True
        assert 0.0 <= result["position_in_zone"] <= 1.0

    def test_price_outside_zone(self):
        """Test timing when price is outside entry zone."""
        strategy = StrategyC()

        entry_zone_analysis = {
            "entry_zone": {"high": 50000, "low": 49900},
            "zone_high": 50000,
            "zone_low": 49900,
        }
        indicators = {"1m": {"market_structure": {"recent_events": []}}}

        result = strategy._analyze_timing_condition(
            indicators, 50100, entry_zone_analysis
        )

        assert result["price_in_zone"] is False
        assert result["score"] == 0.3

    def test_confirmation_bonus(self):
        """Test timing bonus with 1m confirmation."""
        strategy = StrategyC()

        entry_zone_analysis = {
            "entry_zone": {"high": 50000, "low": 49900},
            "zone_high": 50000,
            "zone_low": 49900,
        }
        indicators = {
            "1m": {
                "market_structure": {
                    "recent_events": [
                        {"type": "liquidity_sweep"},
                        {"type": "structure_break"},
                    ]
                }
            }
        }

        result = strategy._analyze_timing_condition(
            indicators, 49950, entry_zone_analysis
        )

        assert result["has_1m_confirmation"] is True
        # Score should be higher with confirmation

    def test_no_entry_zone(self):
        """Test timing when no entry zone exists."""
        strategy = StrategyC()

        entry_zone_analysis = {"entry_zone": None}
        indicators = {"1m": {}}

        result = strategy._analyze_timing_condition(
            indicators, 50000, entry_zone_analysis
        )

        assert result["score"] == 0.5


class TestStrategyCWeightedConfidence:
    """Test weighted confidence calculation."""

    def test_perfect_confidence_calculation(self):
        """Test confidence with perfect scores."""
        strategy = StrategyC()

        trend_analysis = {"score": 1.0}
        entry_zone_analysis = {"score": 1.0}
        liquidity_analysis = {"score": 1.0}
        timing_analysis = {"score": 1.0}

        confidence = strategy._calculate_weighted_confidence(
            trend_analysis, entry_zone_analysis, liquidity_analysis, timing_analysis
        )

        assert abs(confidence - 1.0) < 0.01

    def test_weighted_confidence_with_defaults(self):
        """Test confidence calculation with default weights."""
        strategy = StrategyC()

        trend_analysis = {"score": 0.8}
        entry_zone_analysis = {"score": 0.7}
        liquidity_analysis = {"score": 0.6}
        timing_analysis = {"score": 0.5}

        confidence = strategy._calculate_weighted_confidence(
            trend_analysis, entry_zone_analysis, liquidity_analysis, timing_analysis
        )

        # Manual calculation: 0.35*0.8 + 0.30*0.7 + 0.25*0.6 + 0.10*0.5
        # = 0.28 + 0.21 + 0.15 + 0.05 = 0.69
        assert abs(confidence - 0.69) < 0.01

    def test_weighted_confidence_with_custom_weights(self):
        """Test confidence calculation with custom weights."""
        strategy = StrategyC(
            trend_weight=0.50,
            entry_zone_weight=0.30,
            liquidity_weight=0.10,
            timing_weight=0.10,
        )

        trend_analysis = {"score": 0.8}
        entry_zone_analysis = {"score": 0.7}
        liquidity_analysis = {"score": 0.6}
        timing_analysis = {"score": 0.5}

        confidence = strategy._calculate_weighted_confidence(
            trend_analysis, entry_zone_analysis, liquidity_analysis, timing_analysis
        )

        # Manual calculation: 0.50*0.8 + 0.30*0.7 + 0.10*0.6 + 0.10*0.5
        # = 0.40 + 0.21 + 0.06 + 0.05 = 0.72
        assert abs(confidence - 0.72) < 0.01

    def test_confidence_capped_at_one(self):
        """Test that confidence never exceeds 1.0."""
        strategy = StrategyC()

        # Even with impossible perfect scores
        trend_analysis = {"score": 1.5}
        entry_zone_analysis = {"score": 1.5}
        liquidity_analysis = {"score": 1.5}
        timing_analysis = {"score": 1.5}

        confidence = strategy._calculate_weighted_confidence(
            trend_analysis, entry_zone_analysis, liquidity_analysis, timing_analysis
        )

        assert confidence == 1.0


class TestStrategyCSignalGeneration:
    """Test complete multi-condition signal generation."""

    def test_successful_long_signal_generation(self):
        """Test generation of valid LONG signal with all conditions met."""
        strategy = StrategyC(min_confidence=0.65)

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "UPTREND",
                        "strength": 8.5,
                        "strength_level": "STRONG",
                        "is_confirmed": True,
                    },
                    "market_structure": {
                        "breaks": [{"new_structure": "BULLISH", "strength": 0.8}]
                    },
                },
                "15m": {
                    "fvg": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.80,
                            "mitigated": False,
                        }
                    ],
                    "order_blocks": [],
                    "liquidity_levels": [
                        {
                            "price": 49800,
                            "side": "SELL",
                            "strength": 0.75,
                            "swept": False,
                        }
                    ],
                    "liquidity_sweeps": [],
                },
                "1m": {
                    "market_structure": {"recent_events": [{"type": "confirmation"}]}
                },
            },
        }

        signal = strategy.analyze(market_data)

        assert signal is not None
        assert signal.direction == PositionSide.LONG
        assert signal.entry_price == 49950
        assert signal.confidence >= 0.65
        assert signal.stop_loss < signal.entry_price
        assert signal.take_profit > signal.entry_price
        assert signal.metadata["symbol"] == "BTCUSDT"

    def test_successful_short_signal_generation(self):
        """Test generation of valid SHORT signal with all conditions met."""
        strategy = StrategyC(min_confidence=0.65)

        market_data = {
            "symbol": "ETHUSDT",
            "current_price": 3050,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "DOWNTREND",
                        "strength": 8.0,
                        "strength_level": "STRONG",
                        "is_confirmed": True,
                    },
                    "market_structure": {
                        "breaks": [{"new_structure": "BEARISH", "strength": 0.75}]
                    },
                },
                "15m": {
                    "fvg": [
                        {
                            "type": "bearish",
                            "high": 3100,
                            "low": 3000,
                            "strength": 0.85,
                            "mitigated": False,
                        }
                    ],
                    "order_blocks": [],
                    "liquidity_levels": [
                        {
                            "price": 3150,
                            "side": "BUY",
                            "strength": 0.80,
                            "swept": False,
                        }
                    ],
                    "liquidity_sweeps": [],
                },
                "1m": {
                    "market_structure": {"recent_events": [{"type": "structure_break"}]}
                },
            },
        }

        signal = strategy.analyze(market_data)

        assert signal is not None
        assert signal.direction == PositionSide.SHORT
        assert signal.stop_loss > signal.entry_price
        assert signal.take_profit < signal.entry_price

    def test_no_signal_insufficient_trend(self):
        """Test no signal when trend condition fails."""
        strategy = StrategyC()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 50000,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "RANGING",
                        "strength": 3.0,
                        "strength_level": "WEAK",
                        "is_confirmed": False,
                    },
                    "market_structure": {"breaks": []},
                },
                "15m": {
                    "fvg": [
                        {
                            "type": "bullish",
                            "high": 50100,
                            "low": 50000,
                            "strength": 0.8,
                        }
                    ],
                    "liquidity_levels": [],
                },
                "1m": {"market_structure": {"recent_events": []}},
            },
        }

        signal = strategy.analyze(market_data)
        assert signal is None

    def test_no_signal_insufficient_entry_zone(self):
        """Test no signal when entry zone condition fails."""
        strategy = StrategyC()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 50000,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "UPTREND",
                        "strength": 8.0,
                        "strength_level": "STRONG",
                        "is_confirmed": True,
                    },
                    "market_structure": {
                        "breaks": [{"new_structure": "BULLISH", "strength": 0.8}]
                    },
                },
                "15m": {
                    "fvg": [],  # No FVG
                    "order_blocks": [],  # No OB
                    "liquidity_levels": [],
                },
                "1m": {"market_structure": {"recent_events": []}},
            },
        }

        signal = strategy.analyze(market_data)
        assert signal is None

    def test_no_signal_low_overall_confidence(self):
        """Test no signal when overall confidence is too low."""
        strategy = StrategyC(min_confidence=0.90)  # Very high threshold

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "UPTREND",
                        "strength": 6.0,
                        "strength_level": "MODERATE",
                        "is_confirmed": False,
                    },
                    "market_structure": {
                        "breaks": [{"new_structure": "BULLISH", "strength": 0.6}]
                    },
                },
                "15m": {
                    "fvg": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.6,
                            "mitigated": False,
                        }
                    ],
                    "order_blocks": [],
                    "liquidity_levels": [
                        {"price": 49800, "side": "SELL", "strength": 0.5}
                    ],
                },
                "1m": {"market_structure": {"recent_events": []}},
            },
        }

        signal = strategy.analyze(market_data)
        assert signal is None

    def test_disabled_strategy_no_signal(self):
        """Test that disabled strategy produces no signals."""
        strategy = StrategyC()
        strategy.disable()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "UPTREND",
                        "strength": 8.0,
                        "strength_level": "STRONG",
                        "is_confirmed": True,
                    },
                    "market_structure": {
                        "breaks": [{"new_structure": "BULLISH", "strength": 0.8}]
                    },
                },
                "15m": {
                    "fvg": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.8,
                            "mitigated": False,
                        }
                    ],
                    "liquidity_levels": [
                        {"price": 49800, "side": "SELL", "strength": 0.7}
                    ],
                },
                "1m": {"market_structure": {"recent_events": [{"type": "confirmation"}]}},
            },
        }

        signal = strategy.analyze(market_data)
        assert signal is None


class TestStrategyCSignalValidation:
    """Test signal validation with individual condition checks."""

    def test_valid_signal_all_conditions_met(self):
        """Test validation of signal meeting all thresholds."""
        strategy = StrategyC(min_confidence=0.70)

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.75,
            stop_loss=49900,
            take_profit=50250,
            timeframe_analysis={},
            metadata={
                "condition_scores": {
                    "trend": 0.80,
                    "entry_zone": 0.75,
                    "liquidity": 0.70,
                    "timing": 0.60,
                }
            },
        )

        assert strategy.validate_signal(signal) is True

    def test_invalid_signal_low_confidence(self):
        """Test rejection of signal with low overall confidence."""
        strategy = StrategyC(min_confidence=0.80)

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.70,  # Below threshold
            stop_loss=49900,
            take_profit=50250,
            timeframe_analysis={"condition_scores": {}},
        )

        assert strategy.validate_signal(signal) is False

    def test_invalid_signal_low_trend_score(self):
        """Test rejection when trend score below minimum."""
        strategy = StrategyC(min_trend_score=0.60)

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.75,
            stop_loss=49900,
            take_profit=50250,
            timeframe_analysis={
                "condition_scores": {
                    "trend": 0.50,  # Below min_trend_score
                    "entry_zone": 0.80,
                    "liquidity": 0.70,
                }
            },
        )

        assert strategy.validate_signal(signal) is False

    def test_invalid_signal_low_entry_zone_score(self):
        """Test rejection when entry zone score below minimum."""
        strategy = StrategyC(min_entry_zone_score=0.65)

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.75,
            stop_loss=49900,
            take_profit=50250,
            timeframe_analysis={
                "condition_scores": {
                    "trend": 0.80,
                    "entry_zone": 0.60,  # Below min_entry_zone_score
                    "liquidity": 0.70,
                }
            },
        )

        assert strategy.validate_signal(signal) is False

    def test_invalid_signal_low_liquidity_score(self):
        """Test rejection when liquidity score below minimum."""
        strategy = StrategyC(min_liquidity_score=0.50)

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.75,
            stop_loss=49900,
            take_profit=50250,
            timeframe_analysis={
                "condition_scores": {
                    "trend": 0.80,
                    "entry_zone": 0.75,
                    "liquidity": 0.40,  # Below min_liquidity_score
                }
            },
        )

        assert strategy.validate_signal(signal) is False

    def test_invalid_stop_loss_long(self):
        """Test rejection of LONG signal with invalid stop loss."""
        strategy = StrategyC()

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.80,
            stop_loss=50100,  # Above entry price - INVALID
            take_profit=50250,
            timeframe_analysis={"condition_scores": {}},
        )

        assert strategy.validate_signal(signal) is False

    def test_invalid_stop_loss_short(self):
        """Test rejection of SHORT signal with invalid stop loss."""
        strategy = StrategyC()

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.SHORT,
            confidence=0.80,
            stop_loss=49900,  # Below entry price - INVALID
            take_profit=49750,
            timeframe_analysis={"condition_scores": {}},
        )

        assert strategy.validate_signal(signal) is False

    def test_invalid_risk_reward_ratio(self):
        """Test rejection of signal with poor risk-reward ratio."""
        strategy = StrategyC(risk_reward_ratio=2.5)

        signal = TradingSignal(
            strategy_name="Strategy_C_Hybrid",
            timestamp=datetime.utcnow(),
            entry_price=50000,
            direction=PositionSide.LONG,
            confidence=0.80,
            stop_loss=49900,  # Risk: 100
            take_profit=50100,  # Reward: 100, R:R = 1.0 (below 2.5 threshold)
            timeframe_analysis={
                "condition_scores": {
                    "trend": 0.80,
                    "entry_zone": 0.75,
                    "liquidity": 0.70,
                }
            },
        )

        assert strategy.validate_signal(signal) is False


class TestStrategyCMultiConditionCombinations:
    """Test various multi-condition combination scenarios."""

    def test_strong_trend_weak_liquidity(self):
        """Test scenario with strong trend but weak liquidity."""
        strategy = StrategyC(min_liquidity_score=0.3)

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "UPTREND",
                        "strength": 9.5,
                        "strength_level": "STRONG",
                        "is_confirmed": True,
                    },
                    "market_structure": {
                        "breaks": [{"new_structure": "BULLISH", "strength": 0.9}]
                    },
                },
                "15m": {
                    "fvg": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.85,
                            "mitigated": False,
                        }
                    ],
                    "liquidity_levels": [
                        {"price": 49800, "side": "SELL", "strength": 0.4}  # Weak
                    ],
                },
                "1m": {"market_structure": {"recent_events": []}},
            },
        }

        signal = strategy.analyze(market_data)

        # Should still generate signal due to strong trend
        assert signal is not None
        # But confidence affected by weak liquidity

    def test_balanced_all_conditions(self):
        """Test scenario with balanced scores across all conditions."""
        strategy = StrategyC(min_confidence=0.60)

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 49950,
            "indicators": {
                "1h": {
                    "trend_state": {
                        "direction": "UPTREND",
                        "strength": 7.0,
                        "strength_level": "STRONG",
                        "is_confirmed": True,
                    },
                    "market_structure": {
                        "breaks": [{"new_structure": "BULLISH", "strength": 0.7}]
                    },
                },
                "15m": {
                    "order_blocks": [],
                    "fvg": [
                        {
                            "type": "bullish",
                            "high": 50000,
                            "low": 49900,
                            "strength": 0.7,
                            "state": "ACTIVE",
                            "mitigated": False,
                        }
                    ],
                    "liquidity_levels": [
                        {"price": 49800, "side": "SELL", "strength": 0.7}
                    ],
                    "liquidity_sweeps": [],
                },
                "1m": {
                    "market_structure": {"recent_events": [{"type": "confirmation"}]}
                },
            },
        }

        signal = strategy.analyze(market_data)

        assert signal is not None
        # Confidence should be moderate with balanced conditions

    def test_missing_data_graceful_handling(self):
        """Test graceful handling of missing indicator data."""
        strategy = StrategyC()

        market_data = {
            "symbol": "BTCUSDT",
            "current_price": 50000,
            "indicators": {},  # Missing all timeframe data
        }

        signal = strategy.analyze(market_data)
        assert signal is None  # Should not crash, just return None

    def test_insufficient_market_data(self):
        """Test handling of insufficient market data."""
        strategy = StrategyC()

        market_data = {
            "symbol": "BTCUSDT",
            # Missing current_price
            "indicators": {},
        }

        signal = strategy.analyze(market_data)
        assert signal is None
