"""
Indicator Expiration Management System.

This module provides comprehensive expiration logic for ICT indicators across
multiple timeframes. It manages both time-based and price-based expiration
criteria to automatically clean up invalid or outdated indicators.

Key Features:
- Time-based expiration (age-based cleanup)
- Price-based expiration (level breakthrough detection)
- Configurable expiration rules per indicator type
- Multi-timeframe aware expiration logic
- Automatic indicator state management
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional, Callable
import logging

from src.indicators.order_block import OrderBlock, OrderBlockState, OrderBlockType
from src.indicators.fair_value_gap import FairValueGap, FVGState, FVGType
from src.indicators.breaker_block import BreakerBlock, BreakerBlockType
from src.models.candle import Candle
from src.core.constants import TimeFrame


logger = logging.getLogger(__name__)


class ExpirationType(str, Enum):
    """Type of expiration check."""
    TIME_BASED = "time_based"        # Expire after certain time/candles
    PRICE_BASED = "price_based"      # Expire when price breaks through
    BOTH = "both"                    # Require both conditions


@dataclass
class ExpirationConfig:
    """
    Configuration for indicator expiration rules.

    Attributes:
        max_age_candles: Maximum age in number of candles before expiration
        max_age_ms: Maximum age in milliseconds before expiration
        price_breach_percentage: % price must breach beyond level for expiration
        require_close_beyond: If True, candle must close beyond level for expiration
        expiration_type: Which expiration criteria to use
    """
    max_age_candles: Optional[int] = None
    max_age_ms: Optional[int] = None
    price_breach_percentage: float = 100.0  # 100% = complete breakthrough
    require_close_beyond: bool = True
    expiration_type: ExpirationType = ExpirationType.TIME_BASED

    def __post_init__(self):
        """Validate configuration."""
        if self.expiration_type == ExpirationType.TIME_BASED:
            if self.max_age_candles is None and self.max_age_ms is None:
                raise ValueError(
                    "TIME_BASED expiration requires max_age_candles or max_age_ms"
                )

        if self.price_breach_percentage < 0 or self.price_breach_percentage > 200:
            raise ValueError(
                f"price_breach_percentage must be 0-200%, got {self.price_breach_percentage}"
            )


@dataclass
class ExpirationRules:
    """
    Expiration rules for different indicator types.

    Default configurations provide sensible ICT trading methodology defaults:
    - Order Blocks: Valid for ~50-100 candles or until broken
    - Fair Value Gaps: Valid for ~30-50 candles or until filled
    - Breaker Blocks: Valid for ~100-200 candles (longer than OB)
    """
    order_block: ExpirationConfig = field(default_factory=lambda: ExpirationConfig(
        max_age_candles=100,
        price_breach_percentage=150.0,  # Needs significant breach
        require_close_beyond=True,
        expiration_type=ExpirationType.BOTH
    ))

    fair_value_gap: ExpirationConfig = field(default_factory=lambda: ExpirationConfig(
        max_age_candles=50,
        price_breach_percentage=100.0,  # Full breakthrough
        require_close_beyond=False,     # FVG expires on touch
        expiration_type=ExpirationType.BOTH
    ))

    breaker_block: ExpirationConfig = field(default_factory=lambda: ExpirationConfig(
        max_age_candles=200,            # Longer validity than OB
        price_breach_percentage=150.0,
        require_close_beyond=True,
        expiration_type=ExpirationType.BOTH
    ))


class IndicatorExpirationManager:
    """
    Manages expiration of ICT indicators across multiple timeframes.

    Handles both time-based expiration (indicators that are too old) and
    price-based expiration (indicators that have been invalidated by price action).
    """

    def __init__(
        self,
        expiration_rules: Optional[ExpirationRules] = None,
        auto_remove_expired: bool = True
    ):
        """
        Initialize expiration manager.

        Args:
            expiration_rules: Custom expiration rules, or None for defaults
            auto_remove_expired: If True, automatically remove expired indicators
        """
        self.expiration_rules = expiration_rules or ExpirationRules()
        self.auto_remove_expired = auto_remove_expired
        self.logger = logging.getLogger(f"{__name__}.IndicatorExpirationManager")

        # Statistics tracking
        self.expiration_stats: Dict[str, int] = {
            'order_blocks_expired': 0,
            'fair_value_gaps_expired': 0,
            'breaker_blocks_expired': 0,
            'time_based_expirations': 0,
            'price_based_expirations': 0
        }

    def check_order_block_expiration(
        self,
        order_block: OrderBlock,
        current_candle: Candle,
        candles_since_origin: int
    ) -> bool:
        """
        Check if an Order Block should expire.

        Args:
            order_block: Order Block to check
            current_candle: Current market candle
            candles_since_origin: Number of candles since OB origin

        Returns:
            True if Order Block should expire
        """
        config = self.expiration_rules.order_block

        # Skip if already expired or broken
        if order_block.state in [OrderBlockState.EXPIRED, OrderBlockState.BROKEN]:
            return False

        time_expired = self._check_time_expiration(
            config,
            order_block.origin_timestamp,
            current_candle.timestamp,
            candles_since_origin
        )

        price_expired = self._check_price_expiration_ob(
            config,
            order_block,
            current_candle
        )

        # Determine expiration based on type
        should_expire = False
        if config.expiration_type == ExpirationType.TIME_BASED:
            should_expire = time_expired
        elif config.expiration_type == ExpirationType.PRICE_BASED:
            should_expire = price_expired
        else:  # BOTH
            should_expire = time_expired or price_expired

        if should_expire:
            self._log_expiration("OrderBlock", order_block, time_expired, price_expired)

        return should_expire

    def check_fvg_expiration(
        self,
        fvg: FairValueGap,
        current_candle: Candle,
        candles_since_origin: int
    ) -> bool:
        """
        Check if a Fair Value Gap should expire.

        Args:
            fvg: Fair Value Gap to check
            current_candle: Current market candle
            candles_since_origin: Number of candles since FVG origin

        Returns:
            True if FVG should expire
        """
        config = self.expiration_rules.fair_value_gap

        # Skip if already expired or filled
        if fvg.state in [FVGState.EXPIRED, FVGState.FILLED]:
            return False

        time_expired = self._check_time_expiration(
            config,
            fvg.origin_timestamp,
            current_candle.timestamp,
            candles_since_origin
        )

        price_expired = self._check_price_expiration_fvg(
            config,
            fvg,
            current_candle
        )

        # Determine expiration
        should_expire = False
        if config.expiration_type == ExpirationType.TIME_BASED:
            should_expire = time_expired
        elif config.expiration_type == ExpirationType.PRICE_BASED:
            should_expire = price_expired
        else:  # BOTH
            should_expire = time_expired or price_expired

        if should_expire:
            self._log_expiration("FairValueGap", fvg, time_expired, price_expired)

        return should_expire

    def check_breaker_block_expiration(
        self,
        breaker_block: BreakerBlock,
        current_candle: Candle,
        candles_since_transition: int
    ) -> bool:
        """
        Check if a Breaker Block should expire.

        Args:
            breaker_block: Breaker Block to check
            current_candle: Current market candle
            candles_since_transition: Number of candles since BB transition

        Returns:
            True if Breaker Block should expire
        """
        config = self.expiration_rules.breaker_block

        # Skip if already expired
        if breaker_block.state == "EXPIRED":
            return False

        time_expired = self._check_time_expiration(
            config,
            breaker_block.transition_timestamp,
            current_candle.timestamp,
            candles_since_transition
        )

        price_expired = self._check_price_expiration_bb(
            config,
            breaker_block,
            current_candle
        )

        # Determine expiration
        should_expire = False
        if config.expiration_type == ExpirationType.TIME_BASED:
            should_expire = time_expired
        elif config.expiration_type == ExpirationType.PRICE_BASED:
            should_expire = price_expired
        else:  # BOTH
            should_expire = time_expired or price_expired

        if should_expire:
            self._log_expiration("BreakerBlock", breaker_block, time_expired, price_expired)

        return should_expire

    def expire_order_blocks(
        self,
        order_blocks: List[OrderBlock],
        current_candle: Candle,
        candle_history_length: int
    ) -> List[OrderBlock]:
        """
        Check and expire Order Blocks, optionally removing them.

        Args:
            order_blocks: List of Order Blocks to check
            current_candle: Current market candle
            candle_history_length: Total number of candles in history

        Returns:
            List of active Order Blocks (expired ones removed if auto_remove_expired)
        """
        active_obs = []

        for ob in order_blocks:
            candles_since = candle_history_length - ob.origin_candle_index

            if self.check_order_block_expiration(ob, current_candle, candles_since):
                ob.mark_expired()
                self.expiration_stats['order_blocks_expired'] += 1

                if not self.auto_remove_expired:
                    active_obs.append(ob)
            else:
                active_obs.append(ob)

        return active_obs

    def expire_fair_value_gaps(
        self,
        fvgs: List[FairValueGap],
        current_candle: Candle,
        candle_history_length: int
    ) -> List[FairValueGap]:
        """
        Check and expire Fair Value Gaps, optionally removing them.

        Args:
            fvgs: List of FVGs to check
            current_candle: Current market candle
            candle_history_length: Total number of candles in history

        Returns:
            List of active FVGs (expired ones removed if auto_remove_expired)
        """
        active_fvgs = []

        for fvg in fvgs:
            candles_since = candle_history_length - fvg.origin_candle_index

            if self.check_fvg_expiration(fvg, current_candle, candles_since):
                fvg.mark_expired()
                self.expiration_stats['fair_value_gaps_expired'] += 1

                if not self.auto_remove_expired:
                    active_fvgs.append(fvg)
            else:
                active_fvgs.append(fvg)

        return active_fvgs

    def expire_breaker_blocks(
        self,
        breaker_blocks: List[BreakerBlock],
        current_candle: Candle,
        candle_history_length: int
    ) -> List[BreakerBlock]:
        """
        Check and expire Breaker Blocks, optionally removing them.

        Args:
            breaker_blocks: List of Breaker Blocks to check
            current_candle: Current market candle
            candle_history_length: Total number of candles in history

        Returns:
            List of active Breaker Blocks (expired ones removed if auto_remove_expired)
        """
        active_bbs = []

        for bb in breaker_blocks:
            candles_since = candle_history_length - bb.transition_candle_index

            if self.check_breaker_block_expiration(bb, current_candle, candles_since):
                bb.mark_expired()
                self.expiration_stats['breaker_blocks_expired'] += 1

                if not self.auto_remove_expired:
                    active_bbs.append(bb)
            else:
                active_bbs.append(bb)

        return active_bbs

    def _check_time_expiration(
        self,
        config: ExpirationConfig,
        origin_timestamp: int,
        current_timestamp: int,
        candles_since_origin: int
    ) -> bool:
        """Check if indicator has expired based on time."""
        # Check candle-based expiration
        if config.max_age_candles is not None:
            if candles_since_origin >= config.max_age_candles:
                self.expiration_stats['time_based_expirations'] += 1
                return True

        # Check millisecond-based expiration
        if config.max_age_ms is not None:
            age_ms = current_timestamp - origin_timestamp
            if age_ms >= config.max_age_ms:
                self.expiration_stats['time_based_expirations'] += 1
                return True

        return False

    def _check_price_expiration_ob(
        self,
        config: ExpirationConfig,
        order_block: OrderBlock,
        current_candle: Candle
    ) -> bool:
        """Check if Order Block has been invalidated by price action."""
        ob_range = order_block.get_range()
        if ob_range == 0:
            return False

        if order_block.type == OrderBlockType.BULLISH:
            # Bullish OB (support) expires if price breaks significantly below
            breach_price = current_candle.low
            breach_level = order_block.low

            if breach_price >= breach_level:
                return False

            breach_distance = breach_level - breach_price
            breach_pct = (breach_distance / ob_range) * 100

            # Check close requirement
            if config.require_close_beyond:
                if current_candle.close >= breach_level:
                    return False

        else:  # BEARISH
            # Bearish OB (resistance) expires if price breaks significantly above
            breach_price = current_candle.high
            breach_level = order_block.high

            if breach_price <= breach_level:
                return False

            breach_distance = breach_price - breach_level
            breach_pct = (breach_distance / ob_range) * 100

            # Check close requirement
            if config.require_close_beyond:
                if current_candle.close <= breach_level:
                    return False

        if breach_pct >= config.price_breach_percentage:
            self.expiration_stats['price_based_expirations'] += 1
            return True

        return False

    def _check_price_expiration_fvg(
        self,
        config: ExpirationConfig,
        fvg: FairValueGap,
        current_candle: Candle
    ) -> bool:
        """Check if FVG has been invalidated by price action."""
        gap_range = fvg.get_range()
        if gap_range == 0:
            return False

        if fvg.type == FVGType.BULLISH:
            # Bullish FVG expires if price breaks significantly below
            breach_price = current_candle.low
            breach_level = fvg.low

            if breach_price >= breach_level:
                return False

            breach_distance = breach_level - breach_price

        else:  # BEARISH
            # Bearish FVG expires if price breaks significantly above
            breach_price = current_candle.high
            breach_level = fvg.high

            if breach_price <= breach_level:
                return False

            breach_distance = breach_price - breach_level

        breach_pct = (breach_distance / gap_range) * 100

        # Check close requirement
        if config.require_close_beyond:
            if fvg.type == FVGType.BULLISH:
                if current_candle.close >= fvg.low:
                    return False
            else:
                if current_candle.close <= fvg.high:
                    return False

        if breach_pct >= config.price_breach_percentage:
            self.expiration_stats['price_based_expirations'] += 1
            return True

        return False

    def _check_price_expiration_bb(
        self,
        config: ExpirationConfig,
        breaker_block: BreakerBlock,
        current_candle: Candle
    ) -> bool:
        """Check if Breaker Block has been invalidated by price action."""
        bb_range = breaker_block.get_range()
        if bb_range == 0:
            return False

        if breaker_block.type == BreakerBlockType.BULLISH:
            # Bullish BB (support) expires if price breaks significantly below
            breach_price = current_candle.low
            breach_level = breaker_block.low

            if breach_price >= breach_level:
                return False

            breach_distance = breach_level - breach_price

        else:  # BEARISH
            # Bearish BB (resistance) expires if price breaks significantly above
            breach_price = current_candle.high
            breach_level = breaker_block.high

            if breach_price <= breach_level:
                return False

            breach_distance = breach_price - breach_level

        breach_pct = (breach_distance / bb_range) * 100

        # Check close requirement
        if config.require_close_beyond:
            if breaker_block.type == BreakerBlockType.BULLISH:
                if current_candle.close >= breaker_block.low:
                    return False
            else:
                if current_candle.close <= breaker_block.high:
                    return False

        if breach_pct >= config.price_breach_percentage:
            self.expiration_stats['price_based_expirations'] += 1
            return True

        return False

    def _log_expiration(
        self,
        indicator_type: str,
        indicator: Any,
        time_expired: bool,
        price_expired: bool
    ) -> None:
        """Log indicator expiration details."""
        reasons = []
        if time_expired:
            reasons.append("time")
        if price_expired:
            reasons.append("price")

        reason_str = " & ".join(reasons)

        self.logger.debug(
            f"{indicator_type} expired ({reason_str}): {indicator}"
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Get expiration statistics."""
        return {
            **self.expiration_stats,
            'total_expired': sum(self.expiration_stats.values()),
            'auto_remove_enabled': self.auto_remove_expired
        }

    def reset_statistics(self) -> None:
        """Reset expiration statistics."""
        for key in self.expiration_stats:
            self.expiration_stats[key] = 0
