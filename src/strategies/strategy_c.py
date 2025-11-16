"""
Strategy C: Hybrid Trading Strategy.

Multi-condition approach combining:
1. 1h timeframe: Trend direction confirmation
2. 15m timeframe: Order Block (OB) or Fair Value Gap (FVG) detection
3. Liquidity level alignment: Price near significant liquidity zones
4. Weighted confidence scoring for multi-condition validation
"""

import logging
from datetime import datetime
from typing import Optional

from src.core.constants import PositionSide, TimeFrame
from src.strategies.base_strategy import BaseStrategy, TradingSignal

logger = logging.getLogger(__name__)


class StrategyC(BaseStrategy):
    """
    Hybrid trading strategy using multi-timeframe and multi-condition analysis.

    Strategy Logic:
    - 1h timeframe provides overall trend bias
    - 15m timeframe identifies high-probability entry zones (OB/FVG)
    - Liquidity levels validate price positioning
    - Weighted scoring system combines all conditions for signal confidence
    - Only generates signals when weighted score exceeds threshold

    Key Characteristics:
    - Multi-condition validation reduces false signals
    - Flexible weighting system adapts to market conditions
    - Comprehensive risk management with multiple confirmation layers
    - Balanced approach between conservative (Strategy A) and aggressive (Strategy B)
    """

    def __init__(
        self,
        min_confidence: float = 0.70,
        risk_reward_ratio: float = 2.5,
        # Condition weights (must sum to 1.0)
        trend_weight: float = 0.35,
        entry_zone_weight: float = 0.30,
        liquidity_weight: float = 0.25,
        timing_weight: float = 0.10,
        # Minimum individual condition scores
        min_trend_score: float = 0.5,
        min_entry_zone_score: float = 0.6,
        min_liquidity_score: float = 0.4,
    ):
        """
        Initialize Strategy C.

        Args:
            min_confidence: Minimum weighted confidence threshold (0.0-1.0)
            risk_reward_ratio: Target risk-reward ratio
            trend_weight: Weight for 1h trend condition (0.0-1.0)
            entry_zone_weight: Weight for 15m entry zone condition (0.0-1.0)
            liquidity_weight: Weight for liquidity alignment condition (0.0-1.0)
            timing_weight: Weight for entry timing condition (0.0-1.0)
            min_trend_score: Minimum trend score to consider signal
            min_entry_zone_score: Minimum entry zone score to consider signal
            min_liquidity_score: Minimum liquidity score to consider signal
        """
        super().__init__(name="Strategy_C_Hybrid")
        self.min_confidence = min_confidence
        self.risk_reward_ratio = risk_reward_ratio

        # Validate weights sum to 1.0
        total_weight = trend_weight + entry_zone_weight + liquidity_weight + timing_weight
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Condition weights must sum to 1.0, got {total_weight:.2f}")

        self.trend_weight = trend_weight
        self.entry_zone_weight = entry_zone_weight
        self.liquidity_weight = liquidity_weight
        self.timing_weight = timing_weight

        self.min_trend_score = min_trend_score
        self.min_entry_zone_score = min_entry_zone_score
        self.min_liquidity_score = min_liquidity_score

        # Timeframes for analysis
        self.higher_tf = TimeFrame.H1
        self.mid_tf = TimeFrame.M15
        self.lower_tf = TimeFrame.M1

        logger.info(
            f"Strategy C initialized: min_confidence={min_confidence}, "
            f"risk_reward={risk_reward_ratio}, "
            f"weights=[trend={trend_weight}, entry_zone={entry_zone_weight}, "
            f"liquidity={liquidity_weight}, timing={timing_weight}]"
        )

    def analyze(self, market_data: dict) -> Optional[TradingSignal]:
        """
        Analyze multi-condition market data for Strategy C signals.

        Args:
            market_data: Dictionary containing:
                - indicators: Multi-timeframe indicator data
                - current_price: Current market price
                - symbol: Trading symbol

        Returns:
            TradingSignal if weighted conditions met, None otherwise
        """
        if not self.enabled:
            return None

        try:
            indicators = market_data.get("indicators", {})
            current_price = market_data.get("current_price")
            symbol = market_data.get("symbol", "UNKNOWN")

            if not current_price or not indicators:
                logger.debug("Insufficient market data for analysis")
                return None

            # Condition 1: Analyze 1h trend direction
            trend_analysis = self._analyze_trend_condition(indicators)
            if trend_analysis["score"] < self.min_trend_score:
                logger.debug(
                    f"Trend score {trend_analysis['score']:.2f} below minimum {self.min_trend_score}"
                )
                return None

            # Condition 2: Analyze 15m entry zone (OB/FVG)
            entry_zone_analysis = self._analyze_entry_zone_condition(
                indicators, trend_analysis["bias"]
            )
            if entry_zone_analysis["score"] < self.min_entry_zone_score:
                logger.debug(
                    f"Entry zone score {entry_zone_analysis['score']:.2f} below minimum {self.min_entry_zone_score}"
                )
                return None

            # Condition 3: Analyze liquidity level alignment
            liquidity_analysis = self._analyze_liquidity_condition(
                indicators, current_price, trend_analysis["bias"]
            )
            if liquidity_analysis["score"] < self.min_liquidity_score:
                logger.debug(
                    f"Liquidity score {liquidity_analysis['score']:.2f} below minimum {self.min_liquidity_score}"
                )
                return None

            # Condition 4: Analyze entry timing
            timing_analysis = self._analyze_timing_condition(
                indicators, current_price, entry_zone_analysis
            )

            # Calculate weighted confidence score
            confidence = self._calculate_weighted_confidence(
                trend_analysis,
                entry_zone_analysis,
                liquidity_analysis,
                timing_analysis,
            )

            if confidence < self.min_confidence:
                logger.debug(
                    f"Weighted confidence {confidence:.2f} below threshold {self.min_confidence}"
                )
                return None

            # Generate trading signal
            signal = self._generate_signal(
                symbol=symbol,
                current_price=current_price,
                direction=trend_analysis["bias"],
                entry_zone=entry_zone_analysis.get("entry_zone"),
                confidence=confidence,
                condition_analysis={
                    "trend": trend_analysis,
                    "entry_zone": entry_zone_analysis,
                    "liquidity": liquidity_analysis,
                    "timing": timing_analysis,
                },
            )

            logger.info(
                f"Strategy C signal generated: {signal.direction.value} at "
                f"{signal.entry_price:.2f}, confidence={signal.confidence:.2f}, "
                f"trend_score={trend_analysis['score']:.2f}, "
                f"entry_zone_score={entry_zone_analysis['score']:.2f}, "
                f"liquidity_score={liquidity_analysis['score']:.2f}, "
                f"timing_score={timing_analysis['score']:.2f}"
            )

            return signal

        except Exception as e:
            logger.error(f"Error in Strategy C analysis: {e}", exc_info=True)
            return None

    def _analyze_trend_condition(self, indicators: dict) -> dict:
        """
        Analyze 1h timeframe trend direction.

        Evaluates:
        - Current trend direction (uptrend/downtrend/ranging)
        - Trend strength (weak/moderate/strong)
        - Recent Break of Market Structure (BMS)

        Args:
            indicators: Multi-timeframe indicator data

        Returns:
            Dictionary with trend analysis and score
        """
        h1_data = indicators.get(self.higher_tf.value, {})

        # Get trend state
        trend_state = h1_data.get("trend_state")
        if not trend_state:
            return {"score": 0.0, "bias": None, "reason": "No trend state"}

        # Determine bias from trend direction
        trend_direction = trend_state.get("direction", "RANGING")
        if trend_direction == "UPTREND":
            bias = PositionSide.LONG
        elif trend_direction == "DOWNTREND":
            bias = PositionSide.SHORT
        else:
            return {
                "score": 0.0,
                "bias": None,
                "reason": f"Ranging market: {trend_direction}",
            }

        # Calculate trend score based on strength
        trend_strength = trend_state.get("strength", 0.0)
        strength_level = trend_state.get("strength_level", "WEAK")
        is_confirmed = trend_state.get("is_confirmed", False)

        # Base score from strength (0-10 scale normalized to 0-1)
        base_score = min(trend_strength / 10.0, 1.0)

        # Bonus for confirmed trend
        confirmation_bonus = 0.15 if is_confirmed else 0.0

        # Check for supporting BMS
        market_structure = h1_data.get("market_structure", {})
        bms_breaks = market_structure.get("breaks", [])
        recent_bms = bms_breaks[-1] if bms_breaks else None

        bms_bonus = 0.0
        if recent_bms:
            bms_direction = recent_bms.get("new_structure", "")
            # BMS should align with trend
            if (bias == PositionSide.LONG and bms_direction == "BULLISH") or (
                bias == PositionSide.SHORT and bms_direction == "BEARISH"
            ):
                bms_strength = recent_bms.get("strength", 0.5)
                bms_bonus = 0.1 * bms_strength

        total_score = min(base_score + confirmation_bonus + bms_bonus, 1.0)

        return {
            "score": total_score,
            "bias": bias,
            "trend_direction": trend_direction,
            "strength": trend_strength,
            "strength_level": strength_level,
            "is_confirmed": is_confirmed,
            "has_bms_support": bms_bonus > 0,
        }

    def _analyze_entry_zone_condition(self, indicators: dict, bias: PositionSide) -> dict:
        """
        Analyze 15m timeframe for entry zones (Order Blocks or Fair Value Gaps).

        Args:
            indicators: Multi-timeframe indicator data
            bias: Market bias from trend analysis

        Returns:
            Dictionary with entry zone analysis and score
        """
        if not bias:
            return {"score": 0.0, "entry_zone": None, "zone_type": None}

        m15_data = indicators.get(self.mid_tf.value, {})

        # Look for Order Blocks aligned with bias
        ob_zones = self._find_aligned_order_blocks(m15_data.get("order_blocks", []), bias)

        # Look for Fair Value Gaps aligned with bias
        fvg_zones = self._find_aligned_fvg(m15_data.get("fvg", []), bias)

        # Determine best entry zone (prefer OB over FVG for hybrid strategy)
        best_zone = None
        zone_type = None
        zone_score = 0.0

        if ob_zones:
            best_zone = ob_zones[0]
            zone_type = "ORDER_BLOCK"
            # OB scoring: volume ratio, recency, state
            volume_ratio = best_zone.get("volume_ratio", 1.0)
            state = best_zone.get("state", "UNKNOWN")

            base_score = min(volume_ratio / 3.0, 0.7)  # Normalize volume ratio
            state_bonus = 0.2 if state == "ACTIVE" else 0.0
            recency_bonus = 0.1  # OB is recent

            zone_score = min(base_score + state_bonus + recency_bonus, 1.0)

        elif fvg_zones:
            best_zone = fvg_zones[0]
            zone_type = "FAIR_VALUE_GAP"
            # FVG scoring: strength, state
            strength = best_zone.get("strength", 0.5)
            state = best_zone.get("state", "UNKNOWN")

            base_score = strength * 0.7
            state_bonus = 0.2 if state == "ACTIVE" else 0.0
            recency_bonus = 0.1

            zone_score = min(base_score + state_bonus + recency_bonus, 1.0)

        if not best_zone:
            return {
                "score": 0.0,
                "entry_zone": None,
                "zone_type": None,
                "reason": "No aligned entry zones found",
            }

        return {
            "score": zone_score,
            "entry_zone": best_zone,
            "zone_type": zone_type,
            "zone_high": best_zone.get("high", 0.0),
            "zone_low": best_zone.get("low", 0.0),
        }

    def _analyze_liquidity_condition(
        self, indicators: dict, current_price: float, bias: PositionSide
    ) -> dict:
        """
        Analyze liquidity level alignment and positioning.

        Args:
            indicators: Multi-timeframe indicator data
            current_price: Current market price
            bias: Market bias

        Returns:
            Dictionary with liquidity analysis and score
        """
        if not bias:
            return {"score": 0.0, "reason": "No bias"}

        # Check both H1 and M15 liquidity levels
        h1_data = indicators.get(self.higher_tf.value, {})
        m15_data = indicators.get(self.mid_tf.value, {})

        h1_liquidity = h1_data.get("liquidity_levels", [])
        m15_liquidity = m15_data.get("liquidity_levels", [])

        # Combine liquidity levels
        all_liquidity = h1_liquidity + m15_liquidity

        if not all_liquidity:
            return {
                "score": 0.3,  # Neutral score if no liquidity data
                "reason": "No liquidity levels detected",
            }

        # Find nearby liquidity levels (within 2% of current price)
        price_tolerance = current_price * 0.02
        nearby_levels = [
            lvl
            for lvl in all_liquidity
            if abs(lvl.get("price", 0) - current_price) <= price_tolerance
        ]

        if not nearby_levels:
            return {
                "score": 0.5,  # Neutral score if no nearby liquidity
                "reason": "No nearby liquidity levels",
            }

        # Analyze liquidity alignment with bias
        score = 0.0

        for level in nearby_levels:
            level_side = level.get("side", "")
            level_price = level.get("price", 0)

            # For LONG bias: we want price near SELL-side liquidity (below price)
            # For SHORT bias: we want price near BUY-side liquidity (above price)
            if bias == PositionSide.LONG:
                if level_side == "SELL" and level_price < current_price:
                    # Good liquidity positioning for long
                    distance_factor = 1.0 - (current_price - level_price) / price_tolerance
                    score = max(score, 0.6 + 0.4 * distance_factor)
            else:  # SHORT bias
                if level_side == "BUY" and level_price > current_price:
                    # Good liquidity positioning for short
                    distance_factor = 1.0 - (level_price - current_price) / price_tolerance
                    score = max(score, 0.6 + 0.4 * distance_factor)

        # Check for recent liquidity sweeps (could indicate reversal)
        m15_sweeps = m15_data.get("liquidity_sweeps", [])
        recent_sweeps = m15_sweeps[-3:] if m15_sweeps else []

        sweep_bonus = 0.0
        for sweep in recent_sweeps:
            swept_side = sweep.get("liquidity_side", "")
            # Sweep on opposite side supports the bias
            if bias == PositionSide.LONG and swept_side == "SELL":
                sweep_bonus = max(sweep_bonus, 0.15)
            elif bias == PositionSide.SHORT and swept_side == "BUY":
                sweep_bonus = max(sweep_bonus, 0.15)

        total_score = min(score + sweep_bonus, 1.0)

        return {
            "score": total_score,
            "nearby_levels_count": len(nearby_levels),
            "has_sweep_support": sweep_bonus > 0,
        }

    def _analyze_timing_condition(
        self, indicators: dict, current_price: float, entry_zone_analysis: dict
    ) -> dict:
        """
        Analyze entry timing using lower timeframe.

        Args:
            indicators: Multi-timeframe indicator data
            current_price: Current market price
            entry_zone_analysis: Entry zone analysis from 15m

        Returns:
            Dictionary with timing analysis and score
        """
        entry_zone = entry_zone_analysis.get("entry_zone")
        if not entry_zone:
            return {"score": 0.5, "reason": "No entry zone"}

        zone_high = entry_zone_analysis.get("zone_high", 0)
        zone_low = entry_zone_analysis.get("zone_low", 0)

        # Check if price is within entry zone
        price_in_zone = zone_low <= current_price <= zone_high

        if not price_in_zone:
            # Price outside zone, low timing score
            return {
                "score": 0.3,
                "price_in_zone": False,
                "reason": "Price outside entry zone",
            }

        # Price in zone, calculate position within zone
        zone_range = zone_high - zone_low
        if zone_range > 0:
            position_in_zone = (current_price - zone_low) / zone_range
        else:
            position_in_zone = 0.5

        # Prefer entries at favorable edges of zone
        # For bullish: prefer lower part of zone (closer to support)
        # For bearish: prefer upper part of zone (closer to resistance)
        # Position score: higher at edges (0.0 or 1.0), lower at center (0.5)
        edge_score = 1.0 - abs(position_in_zone - 0.5) * 2

        # Base timing score
        base_score = 0.6

        # Edge bonus
        edge_bonus = 0.3 * edge_score

        # Check 1m structure for additional confirmation
        m1_data = indicators.get(self.lower_tf.value, {})
        market_structure = m1_data.get("market_structure", {})
        recent_events = market_structure.get("recent_events", [])

        confirmation_bonus = 0.1 if recent_events else 0.0

        total_score = min(base_score + edge_bonus + confirmation_bonus, 1.0)

        return {
            "score": total_score,
            "price_in_zone": True,
            "position_in_zone": position_in_zone,
            "edge_score": edge_score,
            "has_1m_confirmation": len(recent_events) > 0,
        }

    def _find_aligned_order_blocks(self, ob_list: list, bias: PositionSide) -> list:
        """Find Order Blocks aligned with market bias."""
        if not ob_list:
            return []

        aligned = []
        for ob in ob_list:
            ob_type = ob.get("type", "")
            if bias == PositionSide.LONG and ob_type == "bullish":
                aligned.append(ob)
            elif bias == PositionSide.SHORT and ob_type == "bearish":
                aligned.append(ob)

        # Sort by volume ratio (higher is better)
        aligned.sort(key=lambda x: x.get("volume_ratio", 0), reverse=True)
        return aligned

    def _find_aligned_fvg(self, fvg_list: list, bias: PositionSide) -> list:
        """Find FVG zones aligned with market bias."""
        if not fvg_list:
            return []

        aligned = []
        for fvg in fvg_list:
            fvg_type = fvg.get("type", "")
            if bias == PositionSide.LONG and fvg_type == "bullish":
                aligned.append(fvg)
            elif bias == PositionSide.SHORT and fvg_type == "bearish":
                aligned.append(fvg)

        # Sort by strength
        aligned.sort(key=lambda x: x.get("strength", 0), reverse=True)
        return aligned

    def _calculate_weighted_confidence(
        self,
        trend_analysis: dict,
        entry_zone_analysis: dict,
        liquidity_analysis: dict,
        timing_analysis: dict,
    ) -> float:
        """
        Calculate overall weighted confidence score.

        Args:
            trend_analysis: Trend condition analysis
            entry_zone_analysis: Entry zone condition analysis
            liquidity_analysis: Liquidity condition analysis
            timing_analysis: Timing condition analysis

        Returns:
            Weighted confidence score between 0.0 and 1.0
        """
        # Extract individual scores
        trend_score = trend_analysis.get("score", 0.0)
        entry_zone_score = entry_zone_analysis.get("score", 0.0)
        liquidity_score = liquidity_analysis.get("score", 0.0)
        timing_score = timing_analysis.get("score", 0.0)

        # Apply weights
        weighted_confidence = (
            self.trend_weight * trend_score
            + self.entry_zone_weight * entry_zone_score
            + self.liquidity_weight * liquidity_score
            + self.timing_weight * timing_score
        )

        return min(weighted_confidence, 1.0)

    def _generate_signal(
        self,
        symbol: str,
        current_price: float,
        direction: PositionSide,
        entry_zone: dict,
        confidence: float,
        condition_analysis: dict,
    ) -> TradingSignal:
        """Generate trading signal with comprehensive metadata."""
        # Use entry zone boundaries for stop loss
        if direction == PositionSide.LONG:
            # For long, stop below zone low
            reference_level = entry_zone.get("low", current_price * 0.98)
        else:
            # For short, stop above zone high
            reference_level = entry_zone.get("high", current_price * 1.02)

        stop_loss = self.calculate_stop_loss(current_price, direction, reference_level)
        take_profit = self.calculate_take_profit(current_price, stop_loss, self.risk_reward_ratio)

        return TradingSignal(
            strategy_name=self.name,
            timestamp=datetime.utcnow(),
            entry_price=current_price,
            direction=direction,
            confidence=confidence,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timeframe_analysis={
                "1h_trend": condition_analysis["trend"],
                "15m_entry_zone": condition_analysis["entry_zone"],
                "liquidity": condition_analysis["liquidity"],
                "timing": condition_analysis["timing"],
            },
            metadata={
                "symbol": symbol,
                "strategy_type": "hybrid",
                "risk_reward_ratio": self.risk_reward_ratio,
                "condition_scores": {
                    "trend": condition_analysis["trend"]["score"],
                    "entry_zone": condition_analysis["entry_zone"]["score"],
                    "liquidity": condition_analysis["liquidity"]["score"],
                    "timing": condition_analysis["timing"]["score"],
                },
                "condition_weights": {
                    "trend": self.trend_weight,
                    "entry_zone": self.entry_zone_weight,
                    "liquidity": self.liquidity_weight,
                    "timing": self.timing_weight,
                },
                "weighted_confidence": confidence,
            },
        )

    def validate_signal(self, signal: TradingSignal) -> bool:
        """
        Validate signal before execution.

        Args:
            signal: Trading signal to validate

        Returns:
            True if signal passes validation, False otherwise
        """
        # Check confidence threshold
        if signal.confidence < self.min_confidence:
            logger.warning(
                f"Signal confidence {signal.confidence:.2f} below threshold {self.min_confidence}"
            )
            return False

        # Validate stop loss placement
        if signal.direction == PositionSide.LONG:
            if signal.stop_loss >= signal.entry_price:
                logger.error("Invalid stop loss for LONG position")
                return False
        else:
            if signal.stop_loss <= signal.entry_price:
                logger.error("Invalid stop loss for SHORT position")
                return False

        # Validate take profit placement
        if signal.direction == PositionSide.LONG:
            if signal.take_profit <= signal.entry_price:
                logger.error("Invalid take profit for LONG position")
                return False
        else:
            if signal.take_profit >= signal.entry_price:
                logger.error("Invalid take profit for SHORT position")
                return False

        # Validate risk-reward ratio
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        actual_rr = reward / risk if risk > 0 else 0

        if actual_rr < self.risk_reward_ratio * 0.8:  # 20% tolerance
            logger.warning(
                f"Risk-reward ratio {actual_rr:.2f} below target {self.risk_reward_ratio:.2f}"
            )
            return False

        # Validate metadata contains condition scores
        metadata = signal.metadata or {}
        condition_scores = metadata.get("condition_scores", {})

        if not condition_scores:
            logger.error("Missing condition scores in signal metadata")
            return False

        # Ensure all individual conditions met minimum thresholds
        if condition_scores.get("trend", 0) < self.min_trend_score:
            logger.warning("Trend score below minimum threshold")
            return False

        if condition_scores.get("entry_zone", 0) < self.min_entry_zone_score:
            logger.warning("Entry zone score below minimum threshold")
            return False

        if condition_scores.get("liquidity", 0) < self.min_liquidity_score:
            logger.warning("Liquidity score below minimum threshold")
            return False

        logger.info("Strategy C signal validation passed")
        return True
