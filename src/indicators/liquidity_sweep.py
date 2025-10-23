"""
Liquidity Sweep pattern detection for ICT trading methodology.

This module implements detection of Liquidity Sweep patterns where price:
1. Breaches a liquidity level (swing high/low)
2. Closes beyond the level
3. Reverses back in the opposite direction

Liquidity sweeps are key trading signals in ICT methodology, often indicating
institutional activity and potential high-probability reversal points.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import logging

from src.models.candle import Candle
from src.core.constants import TimeFrame, EventType
from src.core.events import Event, EventBus
from src.indicators.liquidity_zone import LiquidityLevel, LiquidityType, LiquidityState


logger = logging.getLogger(__name__)


class SweepDirection(str, Enum):
    """Direction of the liquidity sweep."""
    BULLISH = "BULLISH"  # Sweep of sell-side liquidity (downward sweep)
    BEARISH = "BEARISH"  # Sweep of buy-side liquidity (upward sweep)


class SweepState(str, Enum):
    """State tracking for potential sweep detection."""
    NO_BREACH = "NO_BREACH"          # No breach detected
    BREACHED = "BREACHED"            # Level breached but not confirmed
    CLOSE_CONFIRMED = "CLOSE_CONFIRMED"  # Candle closed beyond level
    SWEEP_COMPLETED = "SWEEP_COMPLETED"  # Full sweep pattern confirmed


@dataclass
class LiquiditySweep:
    """
    Represents a detected Liquidity Sweep pattern.

    Attributes:
        liquidity_level: The liquidity level that was swept
        direction: Direction of the sweep (bullish/bearish)
        breach_timestamp: When the level was initially breached
        breach_candle_index: Index of the breaching candle
        close_timestamp: When the candle closed beyond the level
        reversal_timestamp: When the reversal was confirmed
        reversal_candle_index: Index of the reversal candle
        breach_distance: How far price breached beyond the level (pips)
        reversal_strength: Strength of the reversal move (0-100)
        symbol: Trading symbol
        timeframe: Timeframe where detected
        is_valid: Whether this is a confirmed valid sweep
    """

    liquidity_level: LiquidityLevel
    direction: SweepDirection
    breach_timestamp: int
    breach_candle_index: int
    close_timestamp: Optional[int] = None
    reversal_timestamp: Optional[int] = None
    reversal_candle_index: Optional[int] = None
    breach_distance: float = 0.0
    reversal_strength: float = 0.0
    symbol: str = ""
    timeframe: TimeFrame = TimeFrame.M1
    is_valid: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert sweep to dictionary format."""
        return {
            'liquidity_level': self.liquidity_level.to_dict(),
            'direction': self.direction.value,
            'breach_timestamp': self.breach_timestamp,
            'breach_datetime': datetime.fromtimestamp(self.breach_timestamp / 1000).isoformat(),
            'breach_candle_index': self.breach_candle_index,
            'close_timestamp': self.close_timestamp,
            'close_datetime': (
                datetime.fromtimestamp(self.close_timestamp / 1000).isoformat()
                if self.close_timestamp else None
            ),
            'reversal_timestamp': self.reversal_timestamp,
            'reversal_datetime': (
                datetime.fromtimestamp(self.reversal_timestamp / 1000).isoformat()
                if self.reversal_timestamp else None
            ),
            'reversal_candle_index': self.reversal_candle_index,
            'breach_distance': self.breach_distance,
            'reversal_strength': self.reversal_strength,
            'symbol': self.symbol,
            'timeframe': self.timeframe.value,
            'is_valid': self.is_valid
        }

    def __repr__(self) -> str:
        """String representation of liquidity sweep."""
        return (
            f"LiquiditySweep(direction={self.direction.value}, "
            f"level={self.liquidity_level.price:.2f}, "
            f"breach_distance={self.breach_distance:.1f}pips, "
            f"reversal_strength={self.reversal_strength:.1f}, "
            f"valid={self.is_valid})"
        )


@dataclass
class SweepCandidate:
    """
    Tracks a potential sweep in progress.

    Used internally to monitor breaches until they are confirmed or invalidated.
    """

    level: LiquidityLevel
    direction: SweepDirection
    breach_candle_index: int
    breach_timestamp: int
    breach_price: float
    state: SweepState = SweepState.BREACHED
    close_candle_index: Optional[int] = None
    close_timestamp: Optional[int] = None


class LiquiditySweepDetector:
    """
    Detects Liquidity Sweep patterns in real-time.

    The detector monitors price action relative to liquidity levels and identifies
    the three-phase sweep pattern: breach → close confirmation → reversal.
    """

    def __init__(
        self,
        min_breach_distance_pips: float = 1.0,
        max_breach_distance_pips: float = 20.0,
        reversal_confirmation_pips: float = 3.0,
        max_candles_for_reversal: int = 5,
        min_reversal_strength: float = 30.0,
        pip_size: float = 0.0001,
        event_bus: Optional[EventBus] = None
    ):
        """
        Initialize Liquidity Sweep detector.

        Args:
            min_breach_distance_pips: Minimum pips beyond level to count as breach
            max_breach_distance_pips: Maximum pips for valid sweep (filters extreme moves)
            reversal_confirmation_pips: Pips back across level to confirm reversal
            max_candles_for_reversal: Maximum candles to wait for reversal confirmation
            min_reversal_strength: Minimum strength score for valid reversal
            pip_size: Size of one pip (0.0001 for most forex, 0.01 for JPY)
            event_bus: Optional EventBus for publishing sweep events
        """
        self.min_breach_distance_pips = min_breach_distance_pips
        self.max_breach_distance_pips = max_breach_distance_pips
        self.reversal_confirmation_pips = reversal_confirmation_pips
        self.max_candles_for_reversal = max_candles_for_reversal
        self.min_reversal_strength = min_reversal_strength
        self.pip_size = pip_size
        self.event_bus = event_bus

        self._candidates: List[SweepCandidate] = []
        self._completed_sweeps: List[LiquiditySweep] = []

        self.logger = logging.getLogger(f"{__name__}.LiquiditySweepDetector")

    def detect_sweeps(
        self,
        candles: List[Candle],
        liquidity_levels: List[LiquidityLevel],
        start_index: int = 0
    ) -> List[LiquiditySweep]:
        """
        Detect liquidity sweep patterns in candle data.

        Args:
            candles: List of candles to analyze
            liquidity_levels: Active liquidity levels to monitor
            start_index: Starting candle index for detection

        Returns:
            List of detected and confirmed liquidity sweeps
        """
        if not candles or not liquidity_levels:
            return []

        self.logger.info(
            f"Detecting sweeps in {len(candles)} candles with {len(liquidity_levels)} levels "
            f"(start_index={start_index})"
        )

        sweeps_detected = []

        # Filter active levels only
        active_levels = [
            level for level in liquidity_levels
            if level.state in (LiquidityState.ACTIVE, LiquidityState.PARTIAL)
        ]

        for i in range(start_index, len(candles)):
            candle = candles[i]

            # Check for new breaches
            for level in active_levels:
                # Skip if level was formed after this candle
                if level.origin_candle_index >= i:
                    continue

                # Check if we already have a candidate for this level
                if any(c.level == level for c in self._candidates):
                    continue

                # Detect breach
                candidate = self._check_breach(candle, level, i)
                if candidate:
                    self._candidates.append(candidate)
                    self.logger.debug(
                        f"New sweep candidate: {level.type.value} level at {level.price:.5f} "
                        f"breached at index {i}"
                    )

            # Update existing candidates
            self._update_candidates(candle, i, candles)

            # Check for completed sweeps
            completed = self._check_completions()
            sweeps_detected.extend(completed)

        # Clean up stale candidates
        self._cleanup_candidates(len(candles) - 1)

        self.logger.info(f"Detected {len(sweeps_detected)} liquidity sweeps")
        return sweeps_detected

    def _check_breach(
        self,
        candle: Candle,
        level: LiquidityLevel,
        candle_index: int
    ) -> Optional[SweepCandidate]:
        """
        Check if a candle breaches a liquidity level.

        Args:
            candle: The candle to check
            level: The liquidity level to check against
            candle_index: Index of the candle

        Returns:
            SweepCandidate if breach detected, None otherwise
        """
        if level.type == LiquidityType.BUY_SIDE:
            # Buy-side liquidity above swing highs - check upward breach
            if candle.high > level.price:
                breach_distance_pips = (candle.high - level.price) / self.pip_size

                # Filter extreme moves
                if breach_distance_pips < self.min_breach_distance_pips:
                    return None
                if breach_distance_pips > self.max_breach_distance_pips:
                    self.logger.debug(
                        f"Breach too far: {breach_distance_pips:.1f} pips (max {self.max_breach_distance_pips})"
                    )
                    return None

                return SweepCandidate(
                    level=level,
                    direction=SweepDirection.BEARISH,  # Upward sweep is bearish signal
                    breach_candle_index=candle_index,
                    breach_timestamp=candle.timestamp,
                    breach_price=candle.high,
                    state=SweepState.BREACHED
                )

        else:  # SELL_SIDE
            # Sell-side liquidity below swing lows - check downward breach
            if candle.low < level.price:
                breach_distance_pips = (level.price - candle.low) / self.pip_size

                # Filter extreme moves
                if breach_distance_pips < self.min_breach_distance_pips:
                    return None
                if breach_distance_pips > self.max_breach_distance_pips:
                    self.logger.debug(
                        f"Breach too far: {breach_distance_pips:.1f} pips (max {self.max_breach_distance_pips})"
                    )
                    return None

                return SweepCandidate(
                    level=level,
                    direction=SweepDirection.BULLISH,  # Downward sweep is bullish signal
                    breach_candle_index=candle_index,
                    breach_timestamp=candle.timestamp,
                    breach_price=candle.low,
                    state=SweepState.BREACHED
                )

        return None

    def _update_candidates(
        self,
        candle: Candle,
        candle_index: int,
        all_candles: List[Candle]
    ) -> None:
        """
        Update state of existing sweep candidates.

        Args:
            candle: Current candle
            candle_index: Index of current candle
            all_candles: Full list of candles for context
        """
        for candidate in self._candidates:
            if candidate.state == SweepState.BREACHED:
                # Check for close confirmation
                if self._check_close_confirmation(candle, candidate):
                    candidate.state = SweepState.CLOSE_CONFIRMED
                    candidate.close_candle_index = candle_index
                    candidate.close_timestamp = candle.timestamp
                    self.logger.debug(
                        f"Close confirmed for {candidate.level.type.value} sweep at index {candle_index}"
                    )

            elif candidate.state == SweepState.CLOSE_CONFIRMED:
                # Check for reversal
                candles_since_close = candle_index - (candidate.close_candle_index or 0)

                if candles_since_close > self.max_candles_for_reversal:
                    # Timeout - invalidate candidate
                    self.logger.debug(
                        f"Sweep candidate timeout after {candles_since_close} candles"
                    )
                    continue

                if self._check_reversal(candle, candidate, all_candles):
                    candidate.state = SweepState.SWEEP_COMPLETED
                    self.logger.info(
                        f"Sweep completed: {candidate.direction.value} at {candidate.level.price:.5f}"
                    )

    def _check_close_confirmation(
        self,
        candle: Candle,
        candidate: SweepCandidate
    ) -> bool:
        """
        Check if candle close confirms the breach.

        Args:
            candle: The candle to check
            candidate: The sweep candidate

        Returns:
            True if close confirms breach
        """
        level_price = candidate.level.price

        if candidate.direction == SweepDirection.BEARISH:
            # For bearish sweep (buy-side breach), close should be above level
            return candle.close > level_price
        else:
            # For bullish sweep (sell-side breach), close should be below level
            return candle.close < level_price

    def _check_reversal(
        self,
        candle: Candle,
        candidate: SweepCandidate,
        all_candles: List[Candle]
    ) -> bool:
        """
        Check if price has reversed after the sweep.

        Args:
            candle: Current candle
            candidate: The sweep candidate
            all_candles: Full list of candles for strength calculation

        Returns:
            True if reversal is confirmed
        """
        level_price = candidate.level.price
        reversal_threshold = self.reversal_confirmation_pips * self.pip_size

        if candidate.direction == SweepDirection.BEARISH:
            # For bearish sweep, reversal is downward (price back below level)
            if candle.close < (level_price - reversal_threshold):
                # Calculate reversal strength
                strength = self._calculate_reversal_strength(
                    candidate,
                    candle,
                    all_candles
                )
                return strength >= self.min_reversal_strength

        else:  # BULLISH
            # For bullish sweep, reversal is upward (price back above level)
            if candle.close > (level_price + reversal_threshold):
                # Calculate reversal strength
                strength = self._calculate_reversal_strength(
                    candidate,
                    candle,
                    all_candles
                )
                return strength >= self.min_reversal_strength

        return False

    def _calculate_reversal_strength(
        self,
        candidate: SweepCandidate,
        reversal_candle: Candle,
        all_candles: List[Candle]
    ) -> float:
        """
        Calculate strength of the reversal move.

        Strength based on:
        - Distance of reversal move
        - Speed of reversal (fewer candles = stronger)
        - Volume during reversal
        - Breach distance (smaller breach = cleaner sweep)

        Args:
            candidate: The sweep candidate
            reversal_candle: The candle confirming reversal
            all_candles: Full list of candles

        Returns:
            Strength score (0-100)
        """
        # Distance factor (0-30 points)
        level_price = candidate.level.price
        if candidate.direction == SweepDirection.BEARISH:
            reversal_distance = level_price - reversal_candle.close
        else:
            reversal_distance = reversal_candle.close - level_price

        reversal_distance_pips = abs(reversal_distance) / self.pip_size
        distance_score = min(30, reversal_distance_pips * 2)

        # Speed factor (0-30 points) - faster reversal is stronger
        candles_to_reverse = (
            (candidate.close_candle_index or 0) -
            candidate.breach_candle_index + 1
        )
        speed_score = max(0, 30 - (candles_to_reverse * 5))

        # Volume factor (0-25 points)
        avg_volume = sum(c.volume for c in all_candles) / len(all_candles) if all_candles else 1.0
        volume_ratio = reversal_candle.volume / avg_volume if avg_volume > 0 else 1.0
        volume_score = min(25, volume_ratio * 12.5)

        # Breach cleanliness (0-15 points) - smaller breach is cleaner
        breach_distance_pips = abs(candidate.breach_price - level_price) / self.pip_size
        breach_ratio = breach_distance_pips / self.max_breach_distance_pips
        breach_score = max(0, 15 * (1 - breach_ratio))

        total_score = distance_score + speed_score + volume_score + breach_score
        return min(100, max(0, total_score))

    def _check_completions(self) -> List[LiquiditySweep]:
        """
        Check for completed sweeps and create LiquiditySweep objects.

        Returns:
            List of completed sweeps
        """
        completed = []
        remaining_candidates = []

        for candidate in self._candidates:
            if candidate.state == SweepState.SWEEP_COMPLETED:
                # Create the completed sweep
                breach_distance_pips = abs(
                    candidate.breach_price - candidate.level.price
                ) / self.pip_size

                sweep = LiquiditySweep(
                    liquidity_level=candidate.level,
                    direction=candidate.direction,
                    breach_timestamp=candidate.breach_timestamp,
                    breach_candle_index=candidate.breach_candle_index,
                    close_timestamp=candidate.close_timestamp,
                    reversal_timestamp=candidate.close_timestamp,  # Will be updated by last candle check
                    reversal_candle_index=candidate.close_candle_index,
                    breach_distance=breach_distance_pips,
                    reversal_strength=0.0,  # Will be calculated
                    symbol=candidate.level.symbol,
                    timeframe=candidate.level.timeframe,
                    is_valid=True
                )

                # Mark the liquidity level as swept
                candidate.level.mark_swept(candidate.close_timestamp or candidate.breach_timestamp)

                completed.append(sweep)
                self._completed_sweeps.append(sweep)

                # Publish event if EventBus available
                if self.event_bus:
                    self._publish_sweep_event(sweep)

            else:
                # Keep candidates that are still pending
                remaining_candidates.append(candidate)

        self._candidates = remaining_candidates
        return completed

    def _cleanup_candidates(self, current_index: int) -> None:
        """
        Remove stale candidates that timed out.

        Args:
            current_index: Current candle index
        """
        active_candidates = []

        for candidate in self._candidates:
            candles_since_breach = current_index - candidate.breach_candle_index

            if candidate.state == SweepState.BREACHED:
                # Give some time for close confirmation
                if candles_since_breach <= 2:
                    active_candidates.append(candidate)

            elif candidate.state == SweepState.CLOSE_CONFIRMED:
                candles_since_close = current_index - (candidate.close_candle_index or 0)
                if candles_since_close <= self.max_candles_for_reversal:
                    active_candidates.append(candidate)

        removed_count = len(self._candidates) - len(active_candidates)
        if removed_count > 0:
            self.logger.debug(f"Cleaned up {removed_count} stale sweep candidates")

        self._candidates = active_candidates

    def _publish_sweep_event(self, sweep: LiquiditySweep) -> None:
        """
        Publish sweep detection event to EventBus.

        Args:
            sweep: The completed liquidity sweep
        """
        if not self.event_bus:
            return

        event = Event(
            priority=7,  # High priority for trading signals
            event_type=EventType.LIQUIDITY_SWEEP_DETECTED,
            timestamp=datetime.now(),
            data=sweep.to_dict(),
            source="LiquiditySweepDetector"
        )

        # Publish asynchronously (fire and forget)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.event_bus.publish(event))
            else:
                asyncio.run(self.event_bus.publish(event))
        except Exception as e:
            self.logger.error(f"Failed to publish sweep event: {e}")

    def get_completed_sweeps(
        self,
        direction: Optional[SweepDirection] = None,
        min_strength: Optional[float] = None
    ) -> List[LiquiditySweep]:
        """
        Get completed sweeps with optional filtering.

        Args:
            direction: Filter by sweep direction
            min_strength: Minimum reversal strength

        Returns:
            List of completed sweeps matching filters
        """
        sweeps = self._completed_sweeps

        if direction:
            sweeps = [s for s in sweeps if s.direction == direction]

        if min_strength is not None:
            sweeps = [s for s in sweeps if s.reversal_strength >= min_strength]

        return sweeps

    def get_active_candidates(self) -> List[SweepCandidate]:
        """
        Get list of active sweep candidates (for monitoring).

        Returns:
            List of candidates currently being tracked
        """
        return self._candidates.copy()

    def clear_history(self) -> None:
        """Clear completed sweeps and candidates history."""
        self._completed_sweeps.clear()
        self._candidates.clear()
        self.logger.debug("Cleared sweep detection history")
