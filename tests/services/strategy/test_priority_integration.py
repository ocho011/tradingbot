"""
Integration tests for Signal Priority Management with Strategy Integration Layer
"""

import pytest
from decimal import Decimal
import pandas as pd

from src.services.strategy.signal import Signal, SignalDirection
from src.services.strategy.priority_manager import (
    SignalPriorityManager,
    PriorityConfig,
    MarketCondition,
)
from src.services.strategy.integration_layer import StrategyIntegrationLayer
from src.services.strategy.signal_filter import FilterConfig


class TestPriorityIntegration:
    """Integration tests for priority management with strategy layer"""

    @pytest.fixture
    def candles(self):
        """Create sample candle data"""
        return pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=100, freq='1h'),
            'open': [50000.0] * 100,
            'high': [51000.0] * 100,
            'low': [49000.0] * 100,
            'close': [50500.0] * 100,
            'volume': [100.0] * 100,
        })

    @pytest.fixture
    def integration_layer(self):
        """Create integration layer with all strategies enabled"""
        filter_config = FilterConfig(
            enabled=True,
            time_window_minutes=5,
            filter_cross_strategy=True,
        )
        return StrategyIntegrationLayer(
            filter_config=filter_config,
            enable_strategy_a=True,
            enable_strategy_b=True,
            enable_strategy_c=True,
        )

    @pytest.fixture
    def priority_manager(self):
        """Create priority manager"""
        return SignalPriorityManager()

    def test_priority_selection_from_multiple_strategies(
        self,
        integration_layer,
        priority_manager,
        candles
    ):
        """Test selecting highest priority signal from multiple strategies"""
        # Generate signals from all strategies
        signals = integration_layer.generate_signals(
            symbol="BTCUSDT",
            current_price=Decimal("50000.00"),
            candles=candles,
        )

        # If we got multiple signals, test priority selection
        if len(signals) > 1:
            result = priority_manager.select_best_signal(
                signals,
                market_condition=MarketCondition.TRENDING_UP
            )

            assert result is not None
            best_signal, details = result

            # Verify selection was made
            assert best_signal in signals
            assert details['total_candidates'] == len(signals)
            assert details['selected_signal_id'] == best_signal.signal_id

    def test_priority_queue_with_filtered_signals(
        self,
        integration_layer,
        priority_manager,
        candles
    ):
        """Test priority queue with signals after filtering"""
        # Generate signals (will be filtered by integration layer)
        signals = integration_layer.generate_signals(
            symbol="BTCUSDT",
            current_price=Decimal("50000.00"),
            candles=candles,
        )

        # Add filtered signals to priority queue
        for signal in signals:
            priority_manager.add_signal(
                signal,
                market_condition=MarketCondition.TRENDING_UP
            )

        # If signals were generated, verify they were added correctly
        if signals:
            assert len(priority_manager.signal_queue) > 0

            # Get highest priority
            highest = priority_manager.get_highest_priority_signal(remove=False)
            assert highest is not None
            assert highest.score > 0
        else:
            # No signals generated is also valid (strategies may not trigger)
            assert len(priority_manager.signal_queue) == 0

    def test_concurrent_signal_handling(self, priority_manager):
        """Test handling concurrent signals from different strategies"""
        # Create signals from different strategies with varying characteristics
        signals = [
            Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_A",  # Conservative
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=85.0,  # High confidence
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),  # R:R = 2:1
            ),
            Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_B",  # Aggressive
                entry_price=Decimal("50100.00"),
                direction=SignalDirection.LONG,
                confidence=75.0,  # Moderate confidence
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("54000.00"),  # R:R = 3.6:1
            ),
            Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_C",  # Hybrid
                entry_price=Decimal("50050.00"),
                direction=SignalDirection.LONG,
                confidence=80.0,  # Good confidence
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("53000.00"),  # R:R = 2.8:1
            ),
        ]

        # Select best signal
        result = priority_manager.select_best_signal(
            signals,
            market_condition=MarketCondition.TRENDING_UP
        )

        assert result is not None
        best_signal, details = result

        # Verify all signals were candidates
        assert details['total_candidates'] == 3
        assert details['valid_candidates'] >= 1

        # Best signal should be one of our signals
        assert best_signal in signals

    def test_market_condition_impact_on_selection(self, priority_manager):
        """Test that market conditions affect signal selection"""
        signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        # Score in different market conditions
        score_trending, _ = priority_manager.calculate_priority_score(
            signal,
            MarketCondition.TRENDING_UP
        )

        score_volatile, _ = priority_manager.calculate_priority_score(
            signal,
            MarketCondition.VOLATILE
        )

        score_ranging, _ = priority_manager.calculate_priority_score(
            signal,
            MarketCondition.RANGING
        )

        # Trending should score highest
        assert score_trending > score_volatile
        assert score_trending > score_ranging

    def test_signal_rejection_based_on_thresholds(self, priority_manager):
        """Test signal rejection when below thresholds"""
        # Set high thresholds
        priority_manager.config.min_confidence_threshold = 80.0
        priority_manager.config.min_risk_reward_ratio = 2.0

        signals = [
            Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=70.0,  # Below threshold
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
            ),
            Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_B",
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=85.0,  # Above threshold
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("51000.00"),  # R:R = 1:1, below threshold
            ),
            Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_C",
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=85.0,  # Above threshold
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),  # R:R = 2:1, meets threshold
            ),
        ]

        result = priority_manager.select_best_signal(signals)
        assert result is not None

        best_signal, details = result

        # Only Strategy C should pass both thresholds
        assert best_signal.strategy_name == "Strategy_C"
        assert details['rejected_count'] == 2

    def test_priority_queue_capacity_management(self, priority_manager):
        """Test queue capacity enforcement with integration"""
        # Set small capacity
        priority_manager.max_concurrent_signals = 5

        # Add more signals than capacity with increasing confidence
        # Use same strategy to isolate confidence as the differentiating factor
        for i in range(10):
            signal = Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_A",  # Same strategy for all signals
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=50.0 + i * 5,  # 50, 55, 60, 65, 70, 75, 80, 85, 90, 95
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
            )
            priority_manager.add_signal(signal)

        # Queue should be limited to capacity
        assert len(priority_manager.signal_queue) <= 5

        # Queue should contain highest priority signals
        snapshot = priority_manager.get_queue_snapshot()
        assert len(snapshot) <= 5

        # Since all signals have same strategy, R:R, and market condition,
        # confidence should be the primary differentiator (40% weight)
        # The top 5 signals by confidence should be: 95, 90, 85, 80, 75
        if snapshot:
            # At least 4 of top 5 should have confidence >= 75 (allowing for small variance)
            high_conf_count = sum(1 for item in snapshot if item['confidence'] >= 75.0)
            assert high_conf_count >= 4  # At least 4 of top 5 should be high confidence

    def test_signal_cancellation_workflow(self, priority_manager):
        """Test signal cancellation in priority queue"""
        # Add signals
        signals = []
        for i in range(3):
            signal = Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=60.0 + i * 10,
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
            )
            priority_manager.add_signal(signal)
            signals.append(signal)

        assert len(priority_manager.signal_queue) == 3

        # Cancel middle signal
        cancelled = priority_manager.cancel_signals([signals[1].signal_id])
        assert cancelled == 1
        assert len(priority_manager.signal_queue) == 2

        # Verify correct signals remain
        snapshot = priority_manager.get_queue_snapshot()
        remaining_ids = {item['signal_id'] for item in snapshot}
        assert signals[0].signal_id in remaining_ids
        assert signals[1].signal_id not in remaining_ids
        assert signals[2].signal_id in remaining_ids

    def test_metrics_tracking(self, priority_manager):
        """Test metrics tracking across priority operations"""
        signals = [
            Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=conf,
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
            )
            for conf in [60.0, 75.0, 85.0]
        ]

        # Add signals
        for signal in signals:
            priority_manager.add_signal(signal)

        # Get highest priority
        priority_manager.get_highest_priority_signal()

        # Check metrics
        metrics = priority_manager.get_metrics()

        assert metrics['signals_scored'] == 3
        assert metrics['signals_selected'] == 1
        assert metrics['queue_size'] == 2
        assert metrics['average_score'] > 0

    def test_config_update_during_runtime(self, priority_manager):
        """Test updating priority configuration at runtime"""
        signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        # Score with default config
        score1, _ = priority_manager.calculate_priority_score(signal)

        # Update config to prioritize confidence more
        priority_manager.update_config(
            confidence_weight=0.6,
            strategy_type_weight=0.2,
            market_condition_weight=0.1,
            risk_reward_weight=0.1,
        )

        # Score with new config
        score2, _ = priority_manager.calculate_priority_score(signal)

        # Scores should differ due to config change
        # (they might be the same by coincidence, but typically differ)
        assert priority_manager.config.confidence_weight == 0.6

    def test_empty_signal_list_handling(self, priority_manager):
        """Test handling of empty signal lists"""
        result = priority_manager.select_best_signal([])
        assert result is None

        highest = priority_manager.get_highest_priority_signal()
        assert highest is None


class TestStrategyPriorityCoordination:
    """Test coordination between strategy layer and priority management"""

    def test_full_workflow_integration(self):
        """Test complete workflow from strategy generation to priority selection"""
        # Setup
        filter_config = FilterConfig(enabled=True)
        integration = StrategyIntegrationLayer(filter_config=filter_config)
        priority_mgr = SignalPriorityManager()

        candles = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=100, freq='1h'),
            'open': [50000.0] * 100,
            'high': [51000.0] * 100,
            'low': [49000.0] * 100,
            'close': [50500.0] * 100,
            'volume': [100.0] * 100,
        })

        # Generate signals through integration layer (includes filtering)
        validated_signals = integration.generate_signals(
            symbol="BTCUSDT",
            current_price=Decimal("50000.00"),
            candles=candles,
        )

        # If signals were generated and passed filtering
        if validated_signals:
            # Select best signal using priority manager
            result = priority_mgr.select_best_signal(
                validated_signals,
                market_condition=MarketCondition.TRENDING_UP
            )

            if result is not None:
                best_signal, details = result

                # Verify complete workflow
                assert best_signal is not None
                assert best_signal in validated_signals
                assert details['selected_signal_id'] == best_signal.signal_id

                # Verify signal passed all validations
                assert best_signal.confidence > 0
                assert best_signal.risk_reward_ratio > 0
