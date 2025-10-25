"""
Unit tests for Signal Priority Management System
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from src.services.strategy.signal import Signal, SignalDirection
from src.services.strategy.priority_manager import (
    SignalPriorityManager,
    PriorityConfig,
    MarketCondition,
    StrategyType,
    PrioritizedSignal,
)


class TestPriorityConfig:
    """Test priority configuration"""

    def test_default_config(self):
        """Test default configuration values"""
        config = PriorityConfig()

        assert config.confidence_weight == 0.4
        assert config.strategy_type_weight == 0.3
        assert config.market_condition_weight == 0.2
        assert config.risk_reward_weight == 0.1

        # Weights should sum to 1.0
        total = (
            config.confidence_weight +
            config.strategy_type_weight +
            config.market_condition_weight +
            config.risk_reward_weight
        )
        assert abs(total - 1.0) < 0.01

    def test_custom_config(self):
        """Test custom configuration"""
        config = PriorityConfig(
            confidence_weight=0.5,
            strategy_type_weight=0.2,
            market_condition_weight=0.2,
            risk_reward_weight=0.1,
        )

        assert config.confidence_weight == 0.5
        assert config.strategy_type_weight == 0.2

    def test_strategy_multipliers(self):
        """Test strategy type multipliers"""
        config = PriorityConfig()

        assert 'Strategy_A' in config.strategy_multipliers
        assert 'Strategy_B' in config.strategy_multipliers
        assert 'Strategy_C' in config.strategy_multipliers

        # Strategy B (aggressive) should have highest multiplier
        assert config.strategy_multipliers['Strategy_B'] > config.strategy_multipliers['Strategy_A']

    def test_market_condition_multipliers(self):
        """Test market condition multipliers"""
        config = PriorityConfig()

        assert MarketCondition.TRENDING_UP in config.market_condition_multipliers
        assert MarketCondition.VOLATILE in config.market_condition_multipliers

        # Trending should have higher multiplier than volatile
        assert (
            config.market_condition_multipliers[MarketCondition.TRENDING_UP] >
            config.market_condition_multipliers[MarketCondition.VOLATILE]
        )


class TestSignalPriorityManager:
    """Test signal priority manager"""

    @pytest.fixture
    def manager(self):
        """Create priority manager instance"""
        return SignalPriorityManager()

    @pytest.fixture
    def sample_signal(self):
        """Create sample signal"""
        return Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

    def test_manager_initialization(self, manager):
        """Test manager initialization"""
        assert manager.config is not None
        assert manager.signal_queue == []
        assert manager.max_concurrent_signals == 10
        assert manager.metrics['signals_scored'] == 0

    def test_calculate_priority_score_basic(self, manager, sample_signal):
        """Test basic priority score calculation"""
        score, details = manager.calculate_priority_score(sample_signal)

        # Score should be in 0-100 range
        assert 0 <= score <= 100

        # Verify details structure
        assert 'confidence_score' in details
        assert 'strategy_multiplier' in details
        assert 'final_score' in details
        assert details['final_score'] == score

    def test_calculate_priority_score_with_market_condition(self, manager, sample_signal):
        """Test priority score with market condition"""
        score_trending, _ = manager.calculate_priority_score(
            sample_signal,
            market_condition=MarketCondition.TRENDING_UP
        )

        score_volatile, _ = manager.calculate_priority_score(
            sample_signal,
            market_condition=MarketCondition.VOLATILE
        )

        # Trending should score higher than volatile
        assert score_trending > score_volatile

    def test_confidence_impact_on_score(self, manager):
        """Test that confidence affects priority score"""
        high_conf_signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=90.0,  # High confidence
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        low_conf_signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=60.0,  # Low confidence
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        score_high, _ = manager.calculate_priority_score(high_conf_signal)
        score_low, _ = manager.calculate_priority_score(low_conf_signal)

        # Higher confidence should result in higher score
        assert score_high > score_low

    def test_strategy_type_impact_on_score(self, manager):
        """Test that strategy type affects priority score"""
        strategy_a_signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",  # Conservative
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        strategy_b_signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_B",  # Aggressive
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        score_a, _ = manager.calculate_priority_score(strategy_a_signal)
        score_b, _ = manager.calculate_priority_score(strategy_b_signal)

        # Strategy B (aggressive) should score higher
        assert score_b > score_a

    def test_risk_reward_impact_on_score(self, manager):
        """Test that risk-reward ratio affects priority score"""
        high_rr_signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("54000.00"),  # R:R = 4:1
        )

        low_rr_signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("51000.00"),  # R:R = 1:1
        )

        score_high_rr, _ = manager.calculate_priority_score(high_rr_signal)
        score_low_rr, _ = manager.calculate_priority_score(low_rr_signal)

        # Higher R:R should result in higher score
        assert score_high_rr > score_low_rr

    def test_add_signal_to_queue(self, manager, sample_signal):
        """Test adding signal to priority queue"""
        prioritized = manager.add_signal(sample_signal)

        assert isinstance(prioritized, PrioritizedSignal)
        assert prioritized.signal == sample_signal
        assert len(manager.signal_queue) == 1
        assert manager.metrics['signals_scored'] == 1

    def test_add_multiple_signals(self, manager):
        """Test adding multiple signals maintains priority order"""
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
            for conf in [60.0, 90.0, 75.0]
        ]

        for signal in signals:
            manager.add_signal(signal)

        assert len(manager.signal_queue) == 3

        # Get highest priority (should be 90% confidence)
        highest = manager.get_highest_priority_signal(remove=False)
        assert highest.signal.confidence == 90.0

    def test_queue_size_limit(self, manager):
        """Test queue size limit enforcement"""
        # Set low limit
        manager.max_concurrent_signals = 3

        # Add 5 signals
        for i in range(5):
            signal = Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=50.0 + i * 10,
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
            )
            manager.add_signal(signal)

        # Queue should be limited to 3
        assert len(manager.signal_queue) <= 3

    def test_get_highest_priority_signal(self, manager):
        """Test getting highest priority signal"""
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
            for conf in [60.0, 80.0, 70.0]
        ]

        for signal in signals:
            manager.add_signal(signal)

        # Get highest priority
        highest = manager.get_highest_priority_signal(remove=True)
        assert highest.signal.confidence == 80.0
        assert len(manager.signal_queue) == 2

    def test_get_highest_priority_empty_queue(self, manager):
        """Test getting signal from empty queue"""
        result = manager.get_highest_priority_signal()
        assert result is None

    def test_select_best_signal(self, manager):
        """Test selecting best signal from list"""
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
            for conf in [60.0, 85.0, 70.0]
        ]

        result = manager.select_best_signal(signals)
        assert result is not None

        best_signal, details = result
        assert best_signal.confidence == 85.0
        assert details['total_candidates'] == 3
        assert details['selected_signal_id'] == best_signal.signal_id

    def test_select_best_signal_with_thresholds(self, manager):
        """Test signal selection with minimum thresholds"""
        # Set high threshold
        manager.config.min_confidence_threshold = 80.0

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

        result = manager.select_best_signal(signals)
        assert result is not None

        best_signal, details = result
        # Only 85% confidence signal should pass threshold
        assert best_signal.confidence == 85.0
        assert details['rejected_count'] == 2

    def test_select_best_signal_empty_list(self, manager):
        """Test selecting from empty signal list"""
        result = manager.select_best_signal([])
        assert result is None

    def test_select_best_signal_all_rejected(self, manager):
        """Test when all signals are rejected by thresholds"""
        manager.config.min_confidence_threshold = 90.0

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
            for conf in [60.0, 70.0, 80.0]
        ]

        result = manager.select_best_signal(signals)
        # All signals below 90% threshold
        assert result is None

    def test_cancel_signals(self, manager, sample_signal):
        """Test cancelling specific signals"""
        # Add multiple signals
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
            manager.add_signal(signal)
            signals.append(signal)

        # Cancel first signal
        cancelled = manager.cancel_signals([signals[0].signal_id])
        assert cancelled == 1
        assert len(manager.signal_queue) == 2

    def test_clear_queue(self, manager):
        """Test clearing entire queue"""
        # Add signals
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
            manager.add_signal(signal)

        assert len(manager.signal_queue) == 3

        manager.clear_queue()
        assert len(manager.signal_queue) == 0

    def test_get_queue_snapshot(self, manager):
        """Test getting queue snapshot"""
        # Add signals with distinct confidences
        confidences = [60.0, 70.0, 80.0]
        for conf in confidences:
            signal = Signal(
                symbol="BTCUSDT",
                strategy_name="Strategy_A",
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=conf,
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
            )
            manager.add_signal(signal)

        snapshot = manager.get_queue_snapshot()

        assert len(snapshot) == 3
        assert all('rank' in item for item in snapshot)
        assert all('priority_score' in item for item in snapshot)

        # First item should have highest priority (80% confidence)
        assert snapshot[0]['rank'] == 1
        # Verify priorities are descending
        assert snapshot[0]['priority_score'] >= snapshot[1]['priority_score']
        assert snapshot[1]['priority_score'] >= snapshot[2]['priority_score']

    def test_get_metrics(self, manager):
        """Test getting metrics"""
        # Add and process signals
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
            manager.add_signal(signal)

        manager.get_highest_priority_signal()

        metrics = manager.get_metrics()

        assert metrics['signals_scored'] == 3
        assert metrics['signals_selected'] == 1
        assert metrics['queue_size'] == 2
        assert 'average_score' in metrics

    def test_update_config(self, manager):
        """Test updating configuration at runtime"""
        original_weight = manager.config.confidence_weight

        manager.update_config(confidence_weight=0.5)
        assert manager.config.confidence_weight == 0.5
        assert manager.config.confidence_weight != original_weight

    def test_concurrent_signals_same_symbol_different_confidence(self, manager):
        """Test priority with concurrent signals on same symbol"""
        signals = [
            Signal(
                symbol="BTCUSDT",
                strategy_name=f"Strategy_{chr(65 + i)}",  # A, B, C
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=60.0 + i * 15,
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
            )
            for i in range(3)
        ]

        result = manager.select_best_signal(signals, MarketCondition.TRENDING_UP)
        assert result is not None

        best_signal, details = result
        # Strategy C with highest confidence should win
        assert best_signal.strategy_name == "Strategy_C"
        assert best_signal.confidence == 90.0

    def test_market_condition_preference(self, manager):
        """Test market condition affects selection"""
        signal_a = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        # Score in trending market
        score_trending, _ = manager.calculate_priority_score(
            signal_a,
            MarketCondition.TRENDING_UP
        )

        # Score in ranging market
        score_ranging, _ = manager.calculate_priority_score(
            signal_a,
            MarketCondition.RANGING
        )

        # Trending should score higher
        assert score_trending > score_ranging


class TestPrioritizedSignal:
    """Test prioritized signal class"""

    def test_prioritized_signal_comparison(self):
        """Test priority comparison for heap ordering"""
        signal1 = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        signal2 = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_B",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        p1 = PrioritizedSignal(score=70.0, signal=signal1)
        p2 = PrioritizedSignal(score=80.0, signal=signal2)

        # Higher score should be "less than" for max-heap behavior
        assert p2 < p1

    def test_prioritized_signal_repr(self):
        """Test string representation"""
        signal = Signal(
            symbol="BTCUSDT",
            strategy_name="Strategy_A",
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
        )

        prioritized = PrioritizedSignal(score=75.5, signal=signal)
        repr_str = repr(prioritized)

        assert "PrioritizedSignal" in repr_str
        assert "75.5" in repr_str
        assert "Strategy_A" in repr_str
