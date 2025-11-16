"""
Tests for Signal Filtering System

Comprehensive test suite for duplicate signal detection and filtering.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.services.strategy.signal import Signal, SignalDirection
from src.services.strategy.signal_filter import FilterConfig, SignalFilter


class TestFilterConfig:
    """Test FilterConfig class"""

    def test_default_config(self):
        """Test default configuration values"""
        config = FilterConfig()

        assert config.time_window_minutes == 5
        assert config.price_threshold_pct == 1.0
        assert config.enabled is True
        assert config.filter_cross_strategy is True
        assert config.check_position_conflicts is True

    def test_custom_config(self):
        """Test custom configuration values"""
        config = FilterConfig(
            time_window_minutes=10,
            price_threshold_pct=2.0,
            enabled=False,
            filter_cross_strategy=False,
            check_position_conflicts=False,
        )

        assert config.time_window_minutes == 10
        assert config.price_threshold_pct == 2.0
        assert config.enabled is False
        assert config.filter_cross_strategy is False
        assert config.check_position_conflicts is False

    def test_time_window_property(self):
        """Test time_window property returns timedelta"""
        config = FilterConfig(time_window_minutes=10)
        assert config.time_window == timedelta(minutes=10)

    def test_price_threshold_decimal(self):
        """Test price_threshold_decimal conversion"""
        config = FilterConfig(price_threshold_pct=2.5)
        assert config.price_threshold_decimal == Decimal("0.025")

    def test_to_dict(self):
        """Test configuration serialization"""
        config = FilterConfig(time_window_minutes=10, price_threshold_pct=2.0)
        config_dict = config.to_dict()

        assert config_dict["time_window_minutes"] == 10
        assert config_dict["price_threshold_pct"] == 2.0
        assert config_dict["enabled"] is True


class TestSignalFilter:
    """Test SignalFilter class"""

    @pytest.fixture
    def filter_instance(self):
        """Create a SignalFilter instance for testing"""
        return SignalFilter()

    @pytest.fixture
    def sample_signal(self):
        """Create a sample signal for testing"""
        return Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )

    def test_initialization(self, filter_instance):
        """Test filter initialization"""
        assert filter_instance.config is not None
        assert filter_instance.recent_signals == []
        assert filter_instance.filtered_count == 0
        assert filter_instance.total_processed == 0

    def test_add_signal_first_time(self, filter_instance, sample_signal):
        """Test adding first signal (should be accepted)"""
        result = filter_instance.add_signal(sample_signal)

        assert result is True
        assert len(filter_instance.recent_signals) == 1
        assert filter_instance.total_processed == 1
        assert filter_instance.filtered_count == 0

    def test_time_window_filtering(self, filter_instance):
        """Test signals within 5min window should be filtered"""
        # Create first signal
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
            timestamp=datetime.utcnow(),
        )
        filter_instance.add_signal(signal1)

        # Create second signal 3 minutes later (within window)
        signal2 = Signal(
            entry_price=Decimal("50100.00"),  # Within 1% price threshold
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49100.00"),
            take_profit=Decimal("52100.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
            timestamp=datetime.utcnow() + timedelta(minutes=3),
        )

        result = filter_instance.add_signal(signal2)

        assert result is False  # Should be filtered
        assert filter_instance.filtered_count == 1
        assert len(filter_instance.recent_signals) == 1  # Only first signal in cache

    def test_time_window_boundary(self, filter_instance):
        """Test signals exactly at window boundary"""
        # Create first signal
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
            timestamp=datetime.utcnow(),
        )
        filter_instance.add_signal(signal1)

        # Create signal 6 minutes later (outside 5-min window)
        signal2 = Signal(
            entry_price=Decimal("50100.00"),
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49100.00"),
            take_profit=Decimal("52100.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
            timestamp=datetime.utcnow() + timedelta(minutes=6),
        )

        result = filter_instance.add_signal(signal2)

        assert result is True  # Should be accepted (outside window)
        assert filter_instance.filtered_count == 0

    def test_price_range_filtering(self, filter_instance):
        """Test signals with <1% price difference should be filtered"""
        # Create first signal at $50,000
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )
        filter_instance.add_signal(signal1)

        # Create signal at $50,400 (0.8% difference - within 1% threshold)
        signal2 = Signal(
            entry_price=Decimal("50400.00"),
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49400.00"),
            take_profit=Decimal("52400.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
        )

        result = filter_instance.add_signal(signal2)

        assert result is False  # Should be filtered (within 1% threshold)
        assert filter_instance.filtered_count == 1

    def test_price_range_boundary(self, filter_instance):
        """Test signals with >1% price difference should not be filtered"""
        # Create first signal at $50,000
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )
        filter_instance.add_signal(signal1)

        # Create signal at $50,600 (1.2% difference - outside threshold)
        signal2 = Signal(
            entry_price=Decimal("50600.00"),
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49600.00"),
            take_profit=Decimal("52600.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
        )

        result = filter_instance.add_signal(signal2)

        assert result is True  # Should be accepted (outside 1% threshold)
        assert filter_instance.filtered_count == 0

    def test_opposite_direction_allowed(self, filter_instance):
        """Test opposite direction signals should NOT be filtered"""
        # Create LONG signal
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )
        filter_instance.add_signal(signal1)

        # Create SHORT signal at similar price
        signal2 = Signal(
            entry_price=Decimal("50100.00"),
            direction=SignalDirection.SHORT,
            confidence=80.0,
            stop_loss=Decimal("51100.00"),
            take_profit=Decimal("48100.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
        )

        result = filter_instance.add_signal(signal2)

        assert result is True  # Should be accepted (opposite direction)
        assert filter_instance.filtered_count == 0

    def test_different_symbol_allowed(self, filter_instance):
        """Test different symbols should NOT be filtered"""
        # Create signal for BTCUSDT
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )
        filter_instance.add_signal(signal1)

        # Create signal for ETHUSDT
        signal2 = Signal(
            entry_price=Decimal("3000.00"),
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("2950.00"),
            take_profit=Decimal("3100.00"),
            symbol="ETHUSDT",
            strategy_name="Strategy_A_Conservative",
        )

        result = filter_instance.add_signal(signal2)

        assert result is True  # Should be accepted (different symbol)
        assert filter_instance.filtered_count == 0

    def test_cross_strategy_filtering_enabled(self):
        """Test cross-strategy filtering when enabled (default)"""
        config = FilterConfig(filter_cross_strategy=True)
        filter_instance = SignalFilter(config=config)

        # Strategy A signal
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )
        filter_instance.add_signal(signal1)

        # Strategy B signal (different strategy, but similar conditions)
        signal2 = Signal(
            entry_price=Decimal("50100.00"),
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49100.00"),
            take_profit=Decimal("52100.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
        )

        result = filter_instance.add_signal(signal2)

        assert result is False  # Should be filtered (cross-strategy enabled)
        assert filter_instance.filtered_count == 1

    def test_cross_strategy_filtering_disabled(self):
        """Test cross-strategy filtering when disabled"""
        config = FilterConfig(filter_cross_strategy=False)
        filter_instance = SignalFilter(config=config)

        # Strategy A signal
        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )
        filter_instance.add_signal(signal1)

        # Strategy B signal (different strategy)
        signal2 = Signal(
            entry_price=Decimal("50100.00"),
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49100.00"),
            take_profit=Decimal("52100.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
        )

        result = filter_instance.add_signal(signal2)

        assert result is True  # Should be accepted (cross-strategy disabled)
        assert filter_instance.filtered_count == 0

    def test_position_conflict_detection(self):
        """Test position conflict detection"""
        active_positions = [
            {
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry_price": Decimal("49500.00"),
            }
        ]

        config = FilterConfig(check_position_conflicts=True)
        filter_instance = SignalFilter(config=config, active_positions=active_positions)

        # Create LONG signal (conflicts with active LONG position)
        signal = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )

        result = filter_instance.add_signal(signal)

        assert result is False  # Should be filtered (position conflict)
        assert filter_instance.filtered_count == 1

    def test_filtering_disabled(self):
        """Test all signals accepted when filtering is disabled"""
        config = FilterConfig(enabled=False)
        filter_instance = SignalFilter(config=config)

        # Add multiple identical signals
        for i in range(5):
            signal = Signal(
                entry_price=Decimal("50000.00"),
                direction=SignalDirection.LONG,
                confidence=75.0,
                stop_loss=Decimal("49000.00"),
                take_profit=Decimal("52000.00"),
                symbol="BTCUSDT",
                strategy_name="Strategy_A_Conservative",
            )
            result = filter_instance.add_signal(signal)
            assert result is True  # All should be accepted

        assert filter_instance.filtered_count == 0
        assert filter_instance.total_processed == 5

    def test_configurable_thresholds(self):
        """Test adjustable time window and price threshold"""
        # Set wider thresholds (10 min window, 2% price threshold)
        config = FilterConfig(
            time_window_minutes=10,
            price_threshold_pct=2.0,
        )
        filter_instance = SignalFilter(config=config)

        signal1 = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
            timestamp=datetime.utcnow(),
        )
        filter_instance.add_signal(signal1)

        # Signal 8 minutes later with 1.5% price difference
        # Would be filtered with default config (5min, 1%)
        # Should be accepted with current config (10min, 2%)
        signal2 = Signal(
            entry_price=Decimal("50750.00"),  # 1.5% difference
            direction=SignalDirection.LONG,
            confidence=80.0,
            stop_loss=Decimal("49750.00"),
            take_profit=Decimal("52750.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
            timestamp=datetime.utcnow() + timedelta(minutes=8),
        )

        result = filter_instance.add_signal(signal2)

        # With wider thresholds, this would still be filtered
        # (within 10min window and within 2% price threshold)
        assert result is False

    def test_update_config_runtime(self, filter_instance):
        """Test runtime configuration updates"""
        filter_instance.update_config(time_window_minutes=10, price_threshold_pct=2.0)

        assert filter_instance.config.time_window_minutes == 10
        assert filter_instance.config.price_threshold_pct == 2.0

    def test_statistics(self, filter_instance, sample_signal):
        """Test filtering statistics"""
        # Add 3 signals (1 accepted, 2 duplicates filtered)
        filter_instance.add_signal(sample_signal)

        duplicate_signal = Signal(
            entry_price=Decimal("50100.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49100.00"),
            take_profit=Decimal("52100.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_B_Aggressive",
        )

        filter_instance.add_signal(duplicate_signal)
        filter_instance.add_signal(duplicate_signal)

        stats = filter_instance.get_statistics()

        assert stats["total_processed"] == 3
        assert stats["filtered_count"] == 2
        assert stats["accepted_count"] == 1
        assert stats["filter_rate_pct"] == pytest.approx(66.67, rel=0.1)

    def test_cache_cleanup(self, filter_instance):
        """Test old signals are removed from cache"""
        # Create old signal (7 minutes ago)
        old_signal = Signal(
            entry_price=Decimal("50000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("52000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
            timestamp=datetime.utcnow() - timedelta(minutes=7),
        )
        filter_instance.recent_signals.append(old_signal)

        # Add new signal (triggers cleanup)
        new_signal = Signal(
            entry_price=Decimal("51000.00"),
            direction=SignalDirection.LONG,
            confidence=75.0,
            stop_loss=Decimal("50000.00"),
            take_profit=Decimal("53000.00"),
            symbol="BTCUSDT",
            strategy_name="Strategy_A_Conservative",
        )
        filter_instance.add_signal(new_signal)

        # Old signal should be removed (outside 5-min window)
        assert len(filter_instance.recent_signals) == 1
        assert filter_instance.recent_signals[0] == new_signal

    def test_clear_cache(self, filter_instance, sample_signal):
        """Test cache clearing"""
        filter_instance.add_signal(sample_signal)
        assert len(filter_instance.recent_signals) == 1

        filter_instance.clear_cache()
        assert len(filter_instance.recent_signals) == 0

    def test_reset_statistics(self, filter_instance, sample_signal):
        """Test statistics reset"""
        filter_instance.add_signal(sample_signal)

        assert filter_instance.total_processed > 0

        filter_instance.reset_statistics()

        assert filter_instance.total_processed == 0
        assert filter_instance.filtered_count == 0
