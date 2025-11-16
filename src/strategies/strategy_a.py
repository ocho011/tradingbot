"""
Strategy A: Conservative Trading Strategy.

Multi-timeframe approach:
1. 1h timeframe: Confirm Break of Market Structure (BMS)
2. 15m timeframe: Detect Fair Value Gap (FVG) or Order Block (OB) aligned with BMS
3. 1m timeframe: Precise entry timing when price enters FVG/OB zone
"""

import logging
from datetime import datetime
from typing import Optional

from src.core.constants import PositionSide, TimeFrame
from src.strategies.base_strategy import BaseStrategy, TradingSignal

logger = logging.getLogger(__name__)


class StrategyA(BaseStrategy):
    """
    Conservative trading strategy using multi-timeframe ICT concepts.

    Strategy Logic:
    - Higher timeframe (1h) confirms overall market structure bias
    - Mid timeframe (15m) identifies quality entry zones (FVG/OB)
    - Lower timeframe (1m) provides precise entry timing
    - Requires strong multi-timeframe alignment for high confidence
    """

    def __init__(
        self,
        min_confidence: float = 0.7,
        risk_reward_ratio: float = 2.0,
    ):
        """
        Initialize Strategy A.

        Args:
            min_confidence: Minimum confidence threshold for signal generation (0.0-1.0)
            risk_reward_ratio: Target risk-reward ratio
        """
        super().__init__(name="Strategy_A_Conservative")
        self.min_confidence = min_confidence
        self.risk_reward_ratio = risk_reward_ratio

        # Timeframes for analysis
        self.higher_tf = TimeFrame.H1
        self.mid_tf = TimeFrame.M15
        self.lower_tf = TimeFrame.M1

        logger.info(
            f"Strategy A initialized: min_confidence={min_confidence}, "
            f"risk_reward={risk_reward_ratio}"
        )

    def analyze(self, market_data: dict) -> Optional[TradingSignal]:
        """
        Analyze multi-timeframe market data for Strategy A signals.

        Args:
            market_data: Dictionary containing:
                - indicators: Multi-timeframe indicator data
                - current_price: Current market price
                - symbol: Trading symbol

        Returns:
            TradingSignal if all conditions met, None otherwise
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

            # Step 1: Analyze higher timeframe (1h) for BMS
            h1_analysis = self._analyze_higher_timeframe(indicators)
            if not h1_analysis["bms_confirmed"]:
                logger.debug("No BMS confirmed on 1h timeframe")
                return None

            # Step 2: Analyze mid timeframe (15m) for FVG/OB
            m15_analysis = self._analyze_mid_timeframe(indicators, h1_analysis["bias"])
            if not m15_analysis["entry_zone_found"]:
                logger.debug("No valid entry zone on 15m timeframe")
                return None

            # Step 3: Analyze lower timeframe (1m) for entry timing
            m1_analysis = self._analyze_lower_timeframe(
                indicators, current_price, m15_analysis["entry_zone"]
            )
            if not m1_analysis["entry_ready"]:
                logger.debug("Entry timing not optimal on 1m timeframe")
                return None

            # Step 4: Calculate confidence score
            confidence = self._calculate_confidence(h1_analysis, m15_analysis, m1_analysis)

            if confidence < self.min_confidence:
                logger.debug(f"Confidence {confidence:.2f} below threshold {self.min_confidence}")
                return None

            # Step 5: Generate trading signal
            signal = self._generate_signal(
                symbol=symbol,
                current_price=current_price,
                direction=h1_analysis["bias"],
                entry_zone=m15_analysis["entry_zone"],
                confidence=confidence,
                timeframe_analysis={
                    "1h": h1_analysis,
                    "15m": m15_analysis,
                    "1m": m1_analysis,
                },
            )

            logger.info(
                f"Strategy A signal generated: {signal.direction.value} at "
                f"{signal.entry_price:.2f}, confidence={signal.confidence:.2f}"
            )

            return signal

        except Exception as e:
            logger.error(f"Error in Strategy A analysis: {e}", exc_info=True)
            return None

    def _analyze_higher_timeframe(self, indicators: dict) -> dict:
        """
        Analyze 1h timeframe for Break of Market Structure.

        Args:
            indicators: Multi-timeframe indicator data

        Returns:
            Dictionary with BMS analysis results
        """
        h1_data = indicators.get(self.higher_tf.value, {})
        market_structure = h1_data.get("market_structure", {})

        # Check for recent market structure break
        bms_breaks = market_structure.get("breaks", [])
        recent_bms = bms_breaks[-1] if bms_breaks else None

        if not recent_bms:
            return {"bms_confirmed": False, "bias": None}

        # Determine bias from BMS direction
        bias_value = recent_bms.get("new_structure")
        if bias_value == "BULLISH":
            bias = PositionSide.LONG
        elif bias_value == "BEARISH":
            bias = PositionSide.SHORT
        else:
            return {"bms_confirmed": False, "bias": None}

        # Verify trend alignment
        trend_data = h1_data.get("trend", {})
        trend_aligned = trend_data.get("current_trend", "UNCERTAIN") == bias_value

        return {
            "bms_confirmed": True,
            "bias": bias,
            "bms_data": recent_bms,
            "trend_aligned": trend_aligned,
            "strength": recent_bms.get("strength", 0.5),
        }

    def _analyze_mid_timeframe(self, indicators: dict, bias: PositionSide) -> dict:
        """
        Analyze 15m timeframe for FVG or Order Block entry zones.

        Args:
            indicators: Multi-timeframe indicator data
            bias: Market bias from higher timeframe (LONG/SHORT)

        Returns:
            Dictionary with entry zone analysis
        """
        m15_data = indicators.get(self.mid_tf.value, {})

        # Look for FVG aligned with bias
        fvg_zones = self._find_aligned_fvg(m15_data.get("fvg", []), bias)

        # Look for Order Blocks aligned with bias
        ob_zones = self._find_aligned_order_blocks(m15_data.get("order_blocks", []), bias)

        # Prefer FVG, fallback to OB
        if fvg_zones:
            entry_zone = fvg_zones[0]
            zone_type = "FVG"
            zone_quality = entry_zone.get("strength", 0.7)
        elif ob_zones:
            entry_zone = ob_zones[0]
            zone_type = "OB"
            zone_quality = entry_zone.get("volume_ratio", 1.5) / 2.0  # Normalize to 0-1
        else:
            return {"entry_zone_found": False, "entry_zone": None}

        return {
            "entry_zone_found": True,
            "entry_zone": entry_zone,
            "zone_type": zone_type,
            "zone_quality": min(zone_quality, 1.0),
        }

    def _analyze_lower_timeframe(
        self, indicators: dict, current_price: float, entry_zone: dict
    ) -> dict:
        """
        Analyze 1m timeframe for precise entry timing.

        Args:
            indicators: Multi-timeframe indicator data
            current_price: Current market price
            entry_zone: Entry zone from 15m analysis

        Returns:
            Dictionary with entry timing analysis
        """
        if not entry_zone:
            return {"entry_ready": False}

        # Check if price is within entry zone
        zone_high = entry_zone.get("high", 0)
        zone_low = entry_zone.get("low", 0)

        if not (zone_low <= current_price <= zone_high):
            return {"entry_ready": False, "reason": "Price outside entry zone"}

        # Analyze 1m structure for confirmation
        m1_data = indicators.get(self.lower_tf.value, {})
        market_structure = m1_data.get("market_structure", {})

        # Check for liquidity sweep or structure break supporting entry
        recent_events = market_structure.get("recent_events", [])
        has_confirmation = len(recent_events) > 0

        # Calculate entry position within zone (better if near optimal edge)
        zone_range = zone_high - zone_low
        if zone_range > 0:
            position_in_zone = (current_price - zone_low) / zone_range
        else:
            position_in_zone = 0.5

        return {
            "entry_ready": True,
            "has_1m_confirmation": has_confirmation,
            "position_in_zone": position_in_zone,
            "current_price": current_price,
        }

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

        # Sort by strength/quality
        aligned.sort(key=lambda x: x.get("strength", 0), reverse=True)
        return aligned

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

    def _calculate_confidence(
        self, h1_analysis: dict, m15_analysis: dict, m1_analysis: dict
    ) -> float:
        """
        Calculate overall signal confidence based on multi-timeframe alignment.

        Args:
            h1_analysis: Higher timeframe analysis results
            m15_analysis: Mid timeframe analysis results
            m1_analysis: Lower timeframe analysis results

        Returns:
            Confidence score between 0.0 and 1.0
        """
        # Base confidence from BMS strength
        base_confidence = h1_analysis.get("strength", 0.5)

        # Trend alignment bonus
        trend_bonus = 0.15 if h1_analysis.get("trend_aligned", False) else 0.0

        # Entry zone quality
        zone_quality = m15_analysis.get("zone_quality", 0.5) * 0.3

        # Lower timeframe confirmation
        m1_confirmation = 0.1 if m1_analysis.get("has_1m_confirmation", False) else 0.0

        # Position within zone bonus (prefer entries at zone edges)
        position = m1_analysis.get("position_in_zone", 0.5)
        position_bonus = 0.05 * (1.0 - abs(position - 0.5) * 2)  # Max bonus at edges

        total_confidence = (
            base_confidence + trend_bonus + zone_quality + m1_confirmation + position_bonus
        )

        return min(total_confidence, 1.0)

    def _generate_signal(
        self,
        symbol: str,
        current_price: float,
        direction: PositionSide,
        entry_zone: dict,
        confidence: float,
        timeframe_analysis: dict,
    ) -> TradingSignal:
        """Generate trading signal with risk management levels."""
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
            timeframe_analysis=timeframe_analysis,
            metadata={
                "symbol": symbol,
                "entry_zone": entry_zone,
                "risk_reward_ratio": self.risk_reward_ratio,
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
            logger.warning(f"Signal confidence {signal.confidence} below threshold")
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
            logger.warning(f"Risk-reward ratio {actual_rr:.2f} below target")
            return False

        logger.info("Signal validation passed")
        return True
