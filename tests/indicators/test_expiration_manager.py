"""
Tests for Indicator Expiration Manager.

Tests time-based and price-based expiration logic for all indicator types.
"""

import pytest
from datetime import datetime, timedelta

from src.indicators.expiration_manager import (
    IndicatorExpirationManager,
    ExpirationConfig,
    ExpirationRules,
    ExpirationType
)
from src.indicators.order_block import (
    OrderBlock,
    OrderBlockType,
    OrderBlockState
)
from src.indicators.fair_value_gap import (
    FairValueGap,
    FVGType,
    FVGState
)
from src.indicators.breaker_block import (
    BreakerBlock,
    BreakerBlockType
)
from src.models.candle import Candle
from src.core.constants import TimeFrame


class TestExpirationConfig:
    """Test expiration configuration validation."""

    def test_time_based_requires_age_setting(self):
        """TIME_BASED expiration requires max_age_candles or max_age_ms."""
        with pytest.raises(ValueError, match="requires max_age_candles or max_age_ms"):
            ExpirationConfig(
                expiration_type=ExpirationType.TIME_BASED
            )

    def test_valid_time_based_config(self):
        """Valid TIME_BASED configuration with max_age_candles."""
        config = ExpirationConfig(
            max_age_candles=100,
            expiration_type=ExpirationType.TIME_BASED
        )
        assert config.max_age_candles == 100

    def test_price_breach_percentage_validation(self):
        """price_breach_percentage must be 0-200%."""
        with pytest.raises(ValueError, match="must be 0-200%"):
            ExpirationConfig(
                max_age_candles=100,
                price_breach_percentage=250.0
            )


class TestOrderBlockExpiration:
    """Test Order Block expiration logic."""

    def create_order_block(
        self,
        ob_type: OrderBlockType,
        high: float,
        low: float,
        timestamp: int,
        candle_index: int = 0
    ) -> OrderBlock:
        """Helper to create Order Block."""
        return OrderBlock(
            type=ob_type,
            high=high,
            low=low,
            origin_timestamp=timestamp,
            origin_candle_index=candle_index,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=75.0,
            volume=1000000.0,
            state=OrderBlockState.ACTIVE
        )

    def test_time_based_expiration_candles(self):
        """Order Block expires after max_age_candles."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                order_block=ExpirationConfig(
                    max_age_candles=50,
                    expiration_type=ExpirationType.TIME_BASED
                )
            )
        )

        ob = self.create_order_block(
            OrderBlockType.BULLISH,
            50000.0,
            49500.0,
            1000000,
            candle_index=0
        )

        current_candle = Candle(
            timestamp=1003000,
            open=51000.0,
            high=51500.0,
            low=50500.0,
            close=51000.0,
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )

        # 30 candles since origin - should not expire
        assert not manager.check_order_block_expiration(ob, current_candle, 30)

        # 60 candles since origin - should expire
        assert manager.check_order_block_expiration(ob, current_candle, 60)

    def test_time_based_expiration_milliseconds(self):
        """Order Block expires after max_age_ms."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                order_block=ExpirationConfig(
                    max_age_ms=3600000,  # 1 hour
                    expiration_type=ExpirationType.TIME_BASED
                )
            )
        )

        ob = self.create_order_block(
            OrderBlockType.BULLISH,
            50000.0,
            49500.0,
            1000000
        )

        # 30 minutes later - should not expire
        current_candle = Candle(
            timestamp=1000000 + 1800000,  # +30 minutes
            open=51000.0,
            high=51500.0,
            low=50500.0,
            close=51000.0,
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert not manager.check_order_block_expiration(ob, current_candle, 30)

        # 2 hours later - should expire
        current_candle.timestamp = 1000000 + 7200000  # +2 hours
        assert manager.check_order_block_expiration(ob, current_candle, 120)

    def test_price_based_expiration_bullish_ob(self):
        """Bullish OB expires when price breaks significantly below."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                order_block=ExpirationConfig(
                    price_breach_percentage=100.0,  # Need 100% breach (1x range)
                    require_close_beyond=True,
                    expiration_type=ExpirationType.PRICE_BASED
                )
            )
        )

        ob = self.create_order_block(
            OrderBlockType.BULLISH,
            50000.0,
            49500.0,  # Range = 500
            1000000
        )

        # Price touches low but doesn't close below - no expiration
        candle_touch = Candle(
            timestamp=1001000,
            open=49600.0,
            high=49700.0,
            low=49500.0,  # Touches OB low
            close=49600.0,  # Closes above
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert not manager.check_order_block_expiration(ob, candle_touch, 1)

        # Price breaks below by 50% but closes above - no expiration
        candle_break_no_close = Candle(
            timestamp=1002000,
            open=49400.0,
            high=49600.0,
            low=49250.0,  # 50% breach (250 points below)
            close=49550.0,  # Closes above low
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert not manager.check_order_block_expiration(ob, candle_break_no_close, 2)

        # Price breaks below by 100% and closes beyond - expiration
        candle_expire = Candle(
            timestamp=1003000,
            open=49400.0,
            high=49600.0,
            low=49000.0,  # 100% breach (500 points = 1x range)
            close=49100.0,  # Closes below low
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert manager.check_order_block_expiration(ob, candle_expire, 3)

    def test_price_based_expiration_bearish_ob(self):
        """Bearish OB expires when price breaks significantly above."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                order_block=ExpirationConfig(
                    price_breach_percentage=150.0,  # Need 150% breach
                    require_close_beyond=True,
                    expiration_type=ExpirationType.PRICE_BASED
                )
            )
        )

        ob = self.create_order_block(
            OrderBlockType.BEARISH,
            50000.0,
            49500.0,  # Range = 500
            1000000
        )

        # Price breaks above by 100% - should not expire (need 150%)
        candle_100pct = Candle(
            timestamp=1001000,
            open=50100.0,
            high=50500.0,  # 100% breach (500 points above high)
            low=50000.0,
            close=50400.0,  # Closes above
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert not manager.check_order_block_expiration(ob, candle_100pct, 1)

        # Price breaks above by 150% - should expire
        candle_150pct = Candle(
            timestamp=1002000,
            open=50200.0,
            high=50750.0,  # 150% breach (750 points above high)
            low=50100.0,
            close=50600.0,  # Closes above
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert manager.check_order_block_expiration(ob, candle_150pct, 2)

    def test_both_expiration_type(self):
        """BOTH expiration type expires on either time or price."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                order_block=ExpirationConfig(
                    max_age_candles=50,
                    price_breach_percentage=100.0,
                    require_close_beyond=True,
                    expiration_type=ExpirationType.BOTH
                )
            )
        )

        ob = self.create_order_block(
            OrderBlockType.BULLISH,
            50000.0,
            49500.0,
            1000000,
            candle_index=0
        )

        # Young OB, no price breach - no expiration
        candle_young = Candle(
            timestamp=1001000,
            open=50100.0,
            high=50200.0,
            low=50000.0,
            close=50100.0,
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert not manager.check_order_block_expiration(ob, candle_young, 10)

        # Young OB, significant price breach - should expire (price condition)
        candle_price_breach = Candle(
            timestamp=1002000,
            open=49300.0,
            high=49400.0,
            low=49000.0,  # 100% breach
            close=49100.0,  # Closes beyond
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert manager.check_order_block_expiration(ob, candle_price_breach, 15)

        # Reset to test time condition
        ob2 = self.create_order_block(
            OrderBlockType.BULLISH,
            50000.0,
            49500.0,
            1000000,
            candle_index=0
        )

        # Old OB, no price breach - should expire (time condition)
        assert manager.check_order_block_expiration(ob2, candle_young, 60)

    def test_expire_order_blocks_list_with_auto_remove(self):
        """expire_order_blocks removes expired OBs when auto_remove_expired=True."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                order_block=ExpirationConfig(
                    max_age_candles=50,
                    expiration_type=ExpirationType.TIME_BASED
                )
            ),
            auto_remove_expired=True
        )

        obs = [
            self.create_order_block(OrderBlockType.BULLISH, 50000.0, 49500.0, 1000000, 0),
            self.create_order_block(OrderBlockType.BULLISH, 51000.0, 50500.0, 1001000, 15),
            self.create_order_block(OrderBlockType.BEARISH, 52000.0, 51500.0, 1002000, 25),
        ]

        current_candle = Candle(
            timestamp=1005000,
            open=51000.0,
            high=51500.0,
            low=50500.0,
            close=51000.0,
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )

        # 60 candles total - first OB should expire (60 candles old ≥ 50)
        # Second OB: 60-15 = 45 candles old (< 50, should not expire)
        # Third OB: 60-25 = 35 candles old (< 50, should not expire)
        result = manager.expire_order_blocks(obs, current_candle, 60)

        assert len(result) == 2  # First OB removed
        assert result[0].origin_candle_index == 15
        assert result[1].origin_candle_index == 25
        assert manager.expiration_stats['order_blocks_expired'] == 1


class TestFairValueGapExpiration:
    """Test Fair Value Gap expiration logic."""

    def create_fvg(
        self,
        fvg_type: FVGType,
        high: float,
        low: float,
        timestamp: int,
        candle_index: int = 0
    ) -> FairValueGap:
        """Helper to create FVG."""
        return FairValueGap(
            type=fvg_type,
            high=high,
            low=low,
            origin_timestamp=timestamp,
            origin_candle_index=candle_index,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            size_pips=10.0,
            size_percentage=0.1,
            volume=1000000.0,
            state=FVGState.ACTIVE
        )

    def test_fvg_time_expiration(self):
        """FVG expires after max_age_candles."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                fair_value_gap=ExpirationConfig(
                    max_age_candles=30,
                    expiration_type=ExpirationType.TIME_BASED
                )
            )
        )

        fvg = self.create_fvg(
            FVGType.BULLISH,
            50100.0,
            50000.0,
            1000000,
            candle_index=0
        )

        current_candle = Candle(
            timestamp=1002000,
            open=51000.0,
            high=51500.0,
            low=50500.0,
            close=51000.0,
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )

        # 20 candles - should not expire
        assert not manager.check_fvg_expiration(fvg, current_candle, 20)

        # 40 candles - should expire
        assert manager.check_fvg_expiration(fvg, current_candle, 40)

    def test_fvg_price_expiration_no_close_requirement(self):
        """FVG with require_close_beyond=False expires on touch."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                fair_value_gap=ExpirationConfig(
                    price_breach_percentage=100.0,
                    require_close_beyond=False,  # Expires on touch
                    expiration_type=ExpirationType.PRICE_BASED
                )
            )
        )

        fvg = self.create_fvg(
            FVGType.BULLISH,
            50100.0,
            50000.0,  # Range = 100
            1000000
        )

        # Price breaks below by 100% - should expire even without close
        candle = Candle(
            timestamp=1001000,
            open=50000.0,
            high=50100.0,
            low=49900.0,  # 100% breach (100 points below)
            close=50050.0,  # Closes inside gap
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )
        assert manager.check_fvg_expiration(fvg, candle, 1)


class TestBreakerBlockExpiration:
    """Test Breaker Block expiration logic."""

    def create_breaker_block(
        self,
        bb_type: BreakerBlockType,
        high: float,
        low: float,
        transition_timestamp: int,
        candle_index: int = 0
    ) -> BreakerBlock:
        """Helper to create Breaker Block."""
        return BreakerBlock(
            type=bb_type,
            original_type=OrderBlockType.BULLISH if bb_type == BreakerBlockType.BEARISH else OrderBlockType.BEARISH,
            high=high,
            low=low,
            origin_timestamp=transition_timestamp - 1000,
            transition_timestamp=transition_timestamp,
            transition_candle_index=candle_index,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=75.0,
            volume=1000000.0,
            original_ob_volume=900000.0,
            state="ACTIVE"
        )

    def test_breaker_block_expiration(self):
        """Breaker Block expires after max_age_candles from transition."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                breaker_block=ExpirationConfig(
                    max_age_candles=100,
                    expiration_type=ExpirationType.TIME_BASED
                )
            )
        )

        bb = self.create_breaker_block(
            BreakerBlockType.BULLISH,
            50000.0,
            49500.0,
            1000000,
            candle_index=0
        )

        current_candle = Candle(
            timestamp=1005000,
            open=51000.0,
            high=51500.0,
            low=50500.0,
            close=51000.0,
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )

        # 80 candles since transition - should not expire
        assert not manager.check_breaker_block_expiration(bb, current_candle, 80)

        # 120 candles since transition - should expire
        assert manager.check_breaker_block_expiration(bb, current_candle, 120)


class TestExpirationStatistics:
    """Test expiration statistics tracking."""

    def test_statistics_tracking(self):
        """Statistics are correctly tracked and can be retrieved."""
        manager = IndicatorExpirationManager(
            expiration_rules=ExpirationRules(
                order_block=ExpirationConfig(
                    max_age_candles=10,
                    expiration_type=ExpirationType.TIME_BASED
                )
            )
        )

        obs = [OrderBlock(
            type=OrderBlockType.BULLISH,
            high=50000.0,
            low=49500.0,
            origin_timestamp=1000000,
            origin_candle_index=0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            strength=75.0,
            volume=1000000.0,
            state=OrderBlockState.ACTIVE
        )]

        current_candle = Candle(
            timestamp=1001000,
            open=51000.0,
            high=51500.0,
            low=50500.0,
            close=51000.0,
            volume=500000.0,
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1
        )

        # Trigger expiration via expire_order_blocks (which updates stats)
        result = manager.expire_order_blocks(obs, current_candle, 15)

        stats = manager.get_statistics()
        assert stats['order_blocks_expired'] == 1
        assert stats['time_based_expirations'] == 1
        assert stats['total_expired'] == 2  # Both time_based and order_blocks counters

        # Reset statistics
        manager.reset_statistics()
        stats = manager.get_statistics()
        assert stats['total_expired'] == 0
