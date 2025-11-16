"""
Strategy B: Aggressive Trading Strategy.

15-minute timeframe approach:
1. Detect Liquidity Sweep (LS) on 15m timeframe
2. Simultaneously detect Fair Value Gap (FVG) on 15m timeframe
3. Immediate entry when both conditions align
4. Higher risk-reward ratio targeting fast moves
"""

import logging
from datetime import datetime
from typing import List, Optional

from src.core.constants import PositionSide, TimeFrame
from src.strategies.base_strategy import BaseStrategy, TradingSignal

logger = logging.getLogger(__name__)


class StrategyB(BaseStrategy):
    """
    Aggressive trading strategy using 15m Liquidity Sweep + FVG detection.

    Strategy Logic:
    - 15m timeframe as primary analysis window
    - Simultaneous detection of Liquidity Sweep and FVG
    - Immediate entry on alignment (no waiting for confirmations)
    - Higher risk-reward ratio (3:1 or higher)
    - Market volatility-adjusted signal strength

    Key Characteristics:
    - Fast execution (no multi-timeframe confirmation needed)
    - Higher profit potential but also higher risk
    - Requires strong liquidity sweep + fresh FVG alignment
    - Volatility-based confidence adjustment
    """

    def __init__(
        self,
        min_confidence: float = 0.65,
        risk_reward_ratio: float = 3.0,
        max_sweep_candles_ago: int = 3,
        min_fvg_strength: float = 0.6,
        volatility_adjustment_enabled: bool = True,
    ):
        """
        Initialize Strategy B.

        Args:
            min_confidence: Minimum confidence threshold for signal generation (0.0-1.0)
            risk_reward_ratio: Target risk-reward ratio (aggressive: 3:1 or higher)
            max_sweep_candles_ago: Maximum candles since liquidity sweep (recency requirement)
            min_fvg_strength: Minimum FVG strength score for consideration
            volatility_adjustment_enabled: Enable dynamic volatility-based confidence adjustment
        """
        super().__init__(name="Strategy_B_Aggressive")
        self.min_confidence = min_confidence
        self.risk_reward_ratio = risk_reward_ratio
        self.max_sweep_candles_ago = max_sweep_candles_ago
        self.min_fvg_strength = min_fvg_strength
        self.volatility_adjustment_enabled = volatility_adjustment_enabled

        # Primary timeframe for analysis
        self.primary_tf = TimeFrame.M15

        logger.info(
            f"Strategy B initialized: min_confidence={min_confidence}, "
            f"risk_reward={risk_reward_ratio}, max_sweep_age={max_sweep_candles_ago}, "
            f"min_fvg_strength={min_fvg_strength}"
        )

    def analyze(self, market_data: dict) -> Optional[TradingSignal]:
        """
        Analyze 15m market data for Strategy B signals.

        Args:
            market_data: Dictionary containing:
                - indicators: Multi-timeframe indicator data
                - current_price: Current market price
                - symbol: Trading symbol
                - volatility: Optional volatility metrics

        Returns:
            TradingSignal if conditions met (LS + FVG alignment), None otherwise
        """
        if not self.enabled:
            return None

        try:
            indicators = market_data.get("indicators", {})
            current_price = market_data.get("current_price")
            symbol = market_data.get("symbol", "UNKNOWN")
            volatility_data = market_data.get("volatility", {})

            if not current_price or not indicators:
                logger.debug("Insufficient market data for analysis")
                return None

            # Step 1: Analyze 15m timeframe for Liquidity Sweep
            m15_sweep_analysis = self._analyze_liquidity_sweep(indicators)
            if not m15_sweep_analysis["sweep_detected"]:
                logger.debug("No recent liquidity sweep detected on 15m")
                return None

            # Step 2: Analyze 15m timeframe for Fair Value Gap
            m15_fvg_analysis = self._analyze_fair_value_gap(
                indicators, m15_sweep_analysis["sweep_direction"]
            )
            if not m15_fvg_analysis["fvg_detected"]:
                logger.debug("No aligned FVG detected on 15m")
                return None

            # Step 3: Verify alignment between Liquidity Sweep and FVG
            alignment_check = self._verify_sweep_fvg_alignment(
                m15_sweep_analysis, m15_fvg_analysis, current_price
            )
            if not alignment_check["aligned"]:
                logger.debug(f"Liquidity Sweep and FVG not aligned: {alignment_check['reason']}")
                return None

            # Step 4: Calculate confidence with volatility adjustment
            confidence = self._calculate_confidence(
                m15_sweep_analysis,
                m15_fvg_analysis,
                alignment_check,
                volatility_data,
            )

            if confidence < self.min_confidence:
                logger.debug(f"Confidence {confidence:.2f} below threshold {self.min_confidence}")
                return None

            # Step 5: Generate aggressive trading signal
            signal = self._generate_signal(
                symbol=symbol,
                current_price=current_price,
                direction=m15_sweep_analysis["sweep_direction"],
                fvg_zone=m15_fvg_analysis["fvg_data"],
                sweep_data=m15_sweep_analysis,
                confidence=confidence,
                volatility_data=volatility_data,
            )

            logger.info(
                f"Strategy B signal generated: {signal.direction.value} at "
                f"{signal.entry_price:.2f}, confidence={signal.confidence:.2f}, "
                f"R:R={self.risk_reward_ratio}:1"
            )

            return signal

        except Exception as e:
            logger.error(f"Error in Strategy B analysis: {e}", exc_info=True)
            return None

    def _analyze_liquidity_sweep(self, indicators: dict) -> dict:
        """
        Analyze 15m timeframe for recent Liquidity Sweep events.

        Args:
            indicators: Multi-timeframe indicator data

        Returns:
            Dictionary with liquidity sweep analysis
        """
        m15_data = indicators.get(self.primary_tf.value, {})
        liquidity_sweeps = m15_data.get("liquidity_sweeps", [])

        if not liquidity_sweeps:
            return {"sweep_detected": False, "sweep_direction": None}

        # Find most recent sweep within recency window
        recent_sweeps = [
            sweep
            for sweep in liquidity_sweeps
            if sweep.get("candles_ago", 999) <= self.max_sweep_candles_ago
        ]

        if not recent_sweeps:
            return {"sweep_detected": False, "sweep_direction": None}

        # Get most recent sweep
        latest_sweep = recent_sweeps[-1]

        # Determine sweep direction and trading bias
        swept_liquidity_side = latest_sweep.get("liquidity_side", "")

        # Liquidity sweep interpretation:
        # - If SELL-side liquidity swept → expect bullish reaction (LONG bias)
        # - If BUY-side liquidity swept → expect bearish reaction (SHORT bias)
        if swept_liquidity_side == "SELL":
            sweep_direction = PositionSide.LONG
        elif swept_liquidity_side == "BUY":
            sweep_direction = PositionSide.SHORT
        else:
            return {"sweep_detected": False, "sweep_direction": None}

        # Extract sweep strength/quality metrics
        sweep_strength = latest_sweep.get("strength", 0.5)
        sweep_price = latest_sweep.get("price", 0.0)
        candles_ago = latest_sweep.get("candles_ago", 0)

        return {
            "sweep_detected": True,
            "sweep_direction": sweep_direction,
            "sweep_data": latest_sweep,
            "sweep_strength": sweep_strength,
            "sweep_price": sweep_price,
            "candles_ago": candles_ago,
        }

    def _analyze_fair_value_gap(self, indicators: dict, expected_direction: PositionSide) -> dict:
        """
        Analyze 15m timeframe for Fair Value Gap aligned with sweep direction.

        Args:
            indicators: Multi-timeframe indicator data
            expected_direction: Expected FVG direction based on liquidity sweep

        Returns:
            Dictionary with FVG analysis
        """
        m15_data = indicators.get(self.primary_tf.value, {})
        fvg_zones = m15_data.get("fair_value_gaps", [])

        if not fvg_zones:
            return {"fvg_detected": False, "fvg_data": None}

        # Filter FVGs by direction alignment
        aligned_fvgs = self._find_aligned_fvg(fvg_zones, expected_direction)

        if not aligned_fvgs:
            return {"fvg_detected": False, "fvg_data": None}

        # Select highest quality FVG
        best_fvg = aligned_fvgs[0]

        # Check FVG strength threshold
        fvg_strength = best_fvg.get("strength", 0.0)
        if fvg_strength < self.min_fvg_strength:
            return {
                "fvg_detected": False,
                "fvg_data": None,
                "reason": f"FVG strength {fvg_strength:.2f} below minimum {self.min_fvg_strength}",
            }

        # Check if FVG is still unfilled (active)
        fvg_state = best_fvg.get("state", "UNKNOWN")
        if fvg_state != "ACTIVE":
            return {
                "fvg_detected": False,
                "fvg_data": None,
                "reason": f"FVG not active (state: {fvg_state})",
            }

        return {
            "fvg_detected": True,
            "fvg_data": best_fvg,
            "fvg_strength": fvg_strength,
            "fvg_type": best_fvg.get("type", ""),
            "fvg_high": best_fvg.get("high", 0.0),
            "fvg_low": best_fvg.get("low", 0.0),
        }

    def _find_aligned_fvg(self, fvg_list: List[dict], bias: PositionSide) -> List[dict]:
        """
        Find FVG zones aligned with trading bias.

        Args:
            fvg_list: List of FVG dictionaries
            bias: Trading bias (LONG/SHORT)

        Returns:
            Sorted list of aligned FVGs (by strength, descending)
        """
        if not fvg_list:
            return []

        aligned = []
        for fvg in fvg_list:
            fvg_type = fvg.get("type", "").lower()

            # Match FVG type with bias
            if bias == PositionSide.LONG and fvg_type == "bullish":
                aligned.append(fvg)
            elif bias == PositionSide.SHORT and fvg_type == "bearish":
                aligned.append(fvg)

        # Sort by strength (higher is better)
        aligned.sort(key=lambda x: x.get("strength", 0), reverse=True)
        return aligned

    def _verify_sweep_fvg_alignment(
        self, sweep_analysis: dict, fvg_analysis: dict, current_price: float
    ) -> dict:
        """
        Verify that Liquidity Sweep and FVG are properly aligned for entry.

        Args:
            sweep_analysis: Liquidity sweep analysis results
            fvg_analysis: FVG analysis results
            current_price: Current market price

        Returns:
            Dictionary with alignment verification results
        """
        sweep_direction = sweep_analysis["sweep_direction"]
        fvg_high = fvg_analysis["fvg_high"]
        fvg_low = fvg_analysis["fvg_low"]
        sweep_price = sweep_analysis["sweep_price"]

        # Check 1: Price must be approaching or within FVG
        price_in_fvg = fvg_low <= current_price <= fvg_high

        # Check 2: Sweep and FVG should be spatially related
        # For LONG: Sweep should be below FVG (swept lows, then gap up)
        # For SHORT: Sweep should be above FVG (swept highs, then gap down)
        if sweep_direction == PositionSide.LONG:
            spatial_alignment = sweep_price <= fvg_low
        else:
            spatial_alignment = sweep_price >= fvg_high

        # Check 3: Timing - both should be recent (sweep already checked)
        fvg_candles_ago = fvg_analysis["fvg_data"].get("candles_ago", 999)
        timing_alignment = fvg_candles_ago <= self.max_sweep_candles_ago * 2

        # Overall alignment
        is_aligned = spatial_alignment and timing_alignment

        # Provide detailed reason if not aligned
        if not is_aligned:
            reasons = []
            if not spatial_alignment:
                reasons.append("spatial mismatch")
            if not timing_alignment:
                reasons.append(f"FVG too old ({fvg_candles_ago} candles ago)")
            reason = "; ".join(reasons)
        else:
            reason = "aligned"

        return {
            "aligned": is_aligned,
            "price_in_fvg": price_in_fvg,
            "spatial_alignment": spatial_alignment,
            "timing_alignment": timing_alignment,
            "reason": reason,
        }

    def _calculate_confidence(
        self,
        sweep_analysis: dict,
        fvg_analysis: dict,
        alignment_check: dict,
        volatility_data: dict,
    ) -> float:
        """
        Calculate signal confidence with volatility adjustment.

        Args:
            sweep_analysis: Liquidity sweep analysis
            fvg_analysis: FVG analysis
            alignment_check: Sweep-FVG alignment verification
            volatility_data: Market volatility metrics

        Returns:
            Confidence score between 0.0 and 1.0
        """
        # Base confidence from sweep strength
        base_confidence = sweep_analysis.get("sweep_strength", 0.5)

        # FVG quality contribution
        fvg_quality = fvg_analysis.get("fvg_strength", 0.5) * 0.3

        # Spatial alignment bonus
        spatial_bonus = 0.1 if alignment_check.get("spatial_alignment", False) else 0.0

        # Price position bonus (in FVG zone is ideal)
        price_position_bonus = 0.05 if alignment_check.get("price_in_fvg", False) else 0.0

        # Recency bonus (more recent = better)
        candles_ago = sweep_analysis.get("candles_ago", self.max_sweep_candles_ago)
        recency_bonus = 0.05 * (1.0 - candles_ago / self.max_sweep_candles_ago)

        # Calculate base confidence
        confidence = (
            base_confidence + fvg_quality + spatial_bonus + price_position_bonus + recency_bonus
        )

        # Apply volatility adjustment if enabled
        if self.volatility_adjustment_enabled and volatility_data:
            volatility_multiplier = self._calculate_volatility_multiplier(volatility_data)
            confidence *= volatility_multiplier

            logger.debug(f"Volatility adjustment applied: multiplier={volatility_multiplier:.2f}")

        return min(confidence, 1.0)

    def _calculate_volatility_multiplier(self, volatility_data: dict) -> float:
        """
        Calculate confidence multiplier based on market volatility.

        High volatility = higher confidence (aggressive strategy thrives in movement)
        Low volatility = lower confidence (aggressive strategy needs volatility)

        Args:
            volatility_data: Dictionary with volatility metrics

        Returns:
            Multiplier between 0.7 and 1.3
        """
        # Get volatility indicator (e.g., ATR ratio, volatility percentile)
        volatility_level = volatility_data.get("level", "NORMAL")
        volatility_percentile = volatility_data.get("percentile", 50)

        # Map volatility to multiplier (check extreme levels first)
        if volatility_level == "VERY_HIGH" or volatility_percentile > 85:
            # Very high volatility = maximum confidence
            return 1.3
        elif volatility_level == "HIGH" or volatility_percentile > 70:
            # High volatility favors aggressive strategy
            return 1.2
        elif volatility_level == "VERY_LOW" or volatility_percentile < 15:
            # Very low volatility = minimal confidence
            return 0.7
        elif volatility_level == "LOW" or volatility_percentile < 30:
            # Low volatility = reduced confidence
            return 0.85
        else:
            # Normal volatility = neutral multiplier
            return 1.0

    def _generate_signal(
        self,
        symbol: str,
        current_price: float,
        direction: PositionSide,
        fvg_zone: dict,
        sweep_data: dict,
        confidence: float,
        volatility_data: dict,
    ) -> TradingSignal:
        """
        Generate aggressive trading signal with tight risk management.

        Args:
            symbol: Trading symbol
            current_price: Current market price
            direction: Trade direction
            fvg_zone: FVG zone data
            sweep_data: Liquidity sweep data
            confidence: Calculated confidence score
            volatility_data: Market volatility data

        Returns:
            TradingSignal with aggressive risk-reward parameters
        """
        # Use FVG boundaries for tight stop loss
        if direction == PositionSide.LONG:
            # For long, stop just below FVG low
            reference_level = fvg_zone.get("low", current_price * 0.995)
        else:
            # For short, stop just above FVG high
            reference_level = fvg_zone.get("high", current_price * 1.005)

        stop_loss = self.calculate_stop_loss(current_price, direction, reference_level)

        # Calculate aggressive take profit (3:1 or higher R:R)
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
                "15m": {
                    "liquidity_sweep": sweep_data,
                    "fvg_zone": fvg_zone,
                    "volatility": volatility_data,
                }
            },
            metadata={
                "symbol": symbol,
                "strategy_type": "aggressive",
                "risk_reward_ratio": self.risk_reward_ratio,
                "sweep_strength": sweep_data.get("sweep_strength", 0.0),
                "fvg_strength": fvg_zone.get("strength", 0.0),
                "volatility_adjusted": self.volatility_adjustment_enabled,
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

        # Validate risk-reward ratio (aggressive strategy needs higher R:R)
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        actual_rr = reward / risk if risk > 0 else 0

        # Require at least 80% of target R:R for aggressive strategy
        if actual_rr < self.risk_reward_ratio * 0.8:
            logger.warning(
                f"Risk-reward ratio {actual_rr:.2f} below target {self.risk_reward_ratio:.2f}"
            )
            return False

        # Validate that sweep and FVG data are present in metadata
        metadata = signal.metadata or {}
        if not metadata.get("sweep_strength") or not metadata.get("fvg_strength"):
            logger.error("Missing sweep or FVG strength in signal metadata")
            return False

        logger.info("Strategy B signal validation passed")
        return True
