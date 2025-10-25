"""
Signal Priority Management System

Manages signal priorities when multiple signals are generated simultaneously.
Scores signals based on confidence, strategy type, and market conditions,
then selects the optimal signal for execution.
"""

from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import heapq
import logging
from datetime import datetime

from src.services.strategy.signal import Signal, SignalDirection

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """Strategy type for priority weighting"""
    CONSERVATIVE = "CONSERVATIVE"  # Strategy A
    AGGRESSIVE = "AGGRESSIVE"      # Strategy B
    HYBRID = "HYBRID"              # Strategy C


class MarketCondition(Enum):
    """Market condition for priority adjustment"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    STABLE = "STABLE"


@dataclass
class PriorityConfig:
    """
    Configuration for priority scoring algorithm.

    Weights determine how much each factor contributes to the final priority score.
    """

    # Base weights for scoring factors (0-1 range, sum should be 1.0)
    confidence_weight: float = 0.4
    strategy_type_weight: float = 0.3
    market_condition_weight: float = 0.2
    risk_reward_weight: float = 0.1

    # Strategy type multipliers (applied to strategy_type_weight)
    strategy_multipliers: Dict[str, float] = field(default_factory=lambda: {
        'Strategy_A': 1.0,  # Conservative - baseline
        'Strategy_B': 1.2,  # Aggressive - slight preference
        'Strategy_C': 1.1,  # Hybrid - balanced preference
    })

    # Market condition multipliers (applied to market_condition_weight)
    market_condition_multipliers: Dict[MarketCondition, float] = field(default_factory=lambda: {
        MarketCondition.TRENDING_UP: 1.2,
        MarketCondition.TRENDING_DOWN: 1.1,
        MarketCondition.RANGING: 0.9,
        MarketCondition.VOLATILE: 0.8,
        MarketCondition.STABLE: 1.0,
    })

    # Minimum acceptable confidence for signal execution
    min_confidence_threshold: float = 50.0

    # Minimum acceptable risk-reward ratio
    min_risk_reward_ratio: float = 1.0

    def __post_init__(self):
        """Validate configuration"""
        total_weight = (
            self.confidence_weight +
            self.strategy_type_weight +
            self.market_condition_weight +
            self.risk_reward_weight
        )
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(
                f"Priority weights sum to {total_weight:.2f}, should be 1.0. "
                "Normalizing weights."
            )
            # Normalize weights
            self.confidence_weight /= total_weight
            self.strategy_type_weight /= total_weight
            self.market_condition_weight /= total_weight
            self.risk_reward_weight /= total_weight


@dataclass
class PrioritizedSignal:
    """
    Signal with priority score for queue ordering.

    Uses negative score for max-heap behavior (highest priority first).
    """
    score: float
    signal: Signal
    timestamp: datetime = field(default_factory=datetime.utcnow)
    market_condition: Optional[MarketCondition] = None
    scoring_details: Dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other):
        """Compare by score (negated for max-heap)"""
        return self.score > other.score  # Higher score = higher priority

    def __repr__(self) -> str:
        return (
            f"PrioritizedSignal(score={self.score:.2f}, "
            f"signal={self.signal.signal_id[:8]}..., "
            f"{self.signal.strategy_name})"
        )


class SignalPriorityManager:
    """
    Manages signal priorities and selection when multiple signals exist.

    Features:
    - Multi-criteria priority scoring (confidence, strategy, market, R:R)
    - Priority queue for efficient signal ordering
    - Optimal signal selection from concurrent signals
    - Signal execution and cancellation handling
    """

    def __init__(
        self,
        config: Optional[PriorityConfig] = None,
        max_concurrent_signals: int = 10,
    ):
        """
        Initialize priority manager.

        Args:
            config: Priority configuration (creates default if None)
            max_concurrent_signals: Maximum signals to keep in queue
        """
        self.config = config or PriorityConfig()
        self.max_concurrent_signals = max_concurrent_signals

        # Priority queue (min-heap, but we negate scores for max-heap behavior)
        self.signal_queue: List[PrioritizedSignal] = []

        # Metrics
        self.metrics = {
            'signals_scored': 0,
            'signals_selected': 0,
            'signals_cancelled': 0,
            'total_score': 0.0,
        }

        logger.info(
            f"SignalPriorityManager initialized with config: "
            f"confidence_weight={self.config.confidence_weight:.2f}, "
            f"strategy_weight={self.config.strategy_type_weight:.2f}"
        )

    def calculate_priority_score(
        self,
        signal: Signal,
        market_condition: Optional[MarketCondition] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate priority score for a signal.

        Score is computed as weighted sum of:
        1. Confidence score (0-100 normalized to 0-1)
        2. Strategy type multiplier
        3. Market condition alignment
        4. Risk-reward ratio quality

        Args:
            signal: Signal to score
            market_condition: Current market condition (optional)

        Returns:
            Tuple of (priority_score, scoring_details)
            - priority_score: Float between 0-100 (higher is better)
            - scoring_details: Dict with component scores
        """
        # Component 1: Confidence score (0-100 -> 0-1)
        confidence_score = signal.confidence / 100.0

        # Component 2: Strategy type score
        strategy_multiplier = self.config.strategy_multipliers.get(
            signal.strategy_name,
            1.0
        )
        strategy_score = strategy_multiplier

        # Component 3: Market condition score
        market_score = 1.0  # Default neutral
        if market_condition:
            market_multiplier = self.config.market_condition_multipliers.get(
                market_condition,
                1.0
            )
            market_score = market_multiplier

        # Component 4: Risk-reward ratio score
        # Normalize R:R ratio to 0-1 range (cap at 5:1 for normalization)
        rr_ratio = min(signal.risk_reward_ratio, 5.0)
        rr_score = rr_ratio / 5.0

        # Calculate weighted final score
        final_score = (
            self.config.confidence_weight * confidence_score +
            self.config.strategy_type_weight * strategy_score +
            self.config.market_condition_weight * market_score +
            self.config.risk_reward_weight * rr_score
        ) * 100  # Scale to 0-100

        # Track scoring details
        scoring_details = {
            'confidence_score': confidence_score,
            'confidence_contribution': self.config.confidence_weight * confidence_score * 100,
            'strategy_multiplier': strategy_multiplier,
            'strategy_contribution': self.config.strategy_type_weight * strategy_score * 100,
            'market_condition': market_condition.value if market_condition else None,
            'market_score': market_score,
            'market_contribution': self.config.market_condition_weight * market_score * 100,
            'risk_reward_ratio': signal.risk_reward_ratio,
            'rr_score': rr_score,
            'rr_contribution': self.config.risk_reward_weight * rr_score * 100,
            'final_score': final_score,
        }

        self.metrics['signals_scored'] += 1
        self.metrics['total_score'] += final_score

        logger.debug(
            f"Calculated priority score for {signal.signal_id[:8]}...: "
            f"{final_score:.2f} (conf={confidence_score:.2f}, "
            f"strategy={strategy_multiplier:.2f}, market={market_score:.2f}, "
            f"rr={rr_score:.2f})"
        )

        return final_score, scoring_details

    def add_signal(
        self,
        signal: Signal,
        market_condition: Optional[MarketCondition] = None,
    ) -> PrioritizedSignal:
        """
        Score and add signal to priority queue.

        Args:
            signal: Signal to add
            market_condition: Current market condition

        Returns:
            PrioritizedSignal with score and details
        """
        # Calculate priority score
        score, details = self.calculate_priority_score(signal, market_condition)

        # Create prioritized signal
        prioritized = PrioritizedSignal(
            score=score,
            signal=signal,
            market_condition=market_condition,
            scoring_details=details,
        )

        # Add to priority queue
        heapq.heappush(self.signal_queue, prioritized)

        # Enforce queue size limit
        if len(self.signal_queue) > self.max_concurrent_signals:
            # Since __lt__ is inverted for max-heap, heappop would remove highest priority
            # Instead, find and remove the actual lowest priority signal (min score)
            lowest_idx = min(range(len(self.signal_queue)),
                           key=lambda i: self.signal_queue[i].score)
            removed = self.signal_queue.pop(lowest_idx)
            # Rebuild heap after manual removal
            heapq.heapify(self.signal_queue)

            self.metrics['signals_cancelled'] += 1
            logger.info(
                f"Queue full, removed lowest priority signal: {removed.signal.signal_id[:8]}... "
                f"(score={removed.score:.2f})"
            )

        logger.info(
            f"Added signal to priority queue: {signal.signal_id[:8]}... "
            f"(score={score:.2f}, queue_size={len(self.signal_queue)})"
        )

        return prioritized

    def get_highest_priority_signal(
        self,
        remove: bool = True,
    ) -> Optional[PrioritizedSignal]:
        """
        Get the highest priority signal from queue.

        Args:
            remove: Whether to remove signal from queue (default: True)

        Returns:
            Highest priority PrioritizedSignal, or None if queue is empty
        """
        if not self.signal_queue:
            logger.debug("No signals in priority queue")
            return None

        if remove:
            prioritized = heapq.heappop(self.signal_queue)
            self.metrics['signals_selected'] += 1
            logger.info(
                f"Selected highest priority signal: {prioritized.signal.signal_id[:8]}... "
                f"(score={prioritized.score:.2f})"
            )
        else:
            # Peek without removing
            prioritized = self.signal_queue[0]
            logger.debug(
                f"Peeked highest priority signal: {prioritized.signal.signal_id[:8]}... "
                f"(score={prioritized.score:.2f})"
            )

        return prioritized

    def select_best_signal(
        self,
        signals: List[Signal],
        market_condition: Optional[MarketCondition] = None,
    ) -> Optional[Tuple[Signal, Dict[str, Any]]]:
        """
        Select the best signal from a list of concurrent signals.

        This is a convenience method for one-time selection without queue management.

        Args:
            signals: List of signals to choose from
            market_condition: Current market condition

        Returns:
            Tuple of (best_signal, selection_details) or None if no valid signals
        """
        if not signals:
            return None

        # Score all signals
        scored_signals = []
        for signal in signals:
            score, details = self.calculate_priority_score(signal, market_condition)

            # Apply minimum thresholds
            if signal.confidence < self.config.min_confidence_threshold:
                logger.debug(
                    f"Signal {signal.signal_id[:8]}... rejected: "
                    f"confidence {signal.confidence:.1f} < threshold {self.config.min_confidence_threshold}"
                )
                continue

            if signal.risk_reward_ratio < self.config.min_risk_reward_ratio:
                logger.debug(
                    f"Signal {signal.signal_id[:8]}... rejected: "
                    f"R:R {signal.risk_reward_ratio:.2f} < threshold {self.config.min_risk_reward_ratio}"
                )
                continue

            scored_signals.append((score, signal, details))

        if not scored_signals:
            logger.warning("No signals met minimum criteria for selection")
            return None

        # Sort by score (descending)
        scored_signals.sort(reverse=True, key=lambda x: x[0])

        # Get best signal
        best_score, best_signal, best_details = scored_signals[0]

        selection_details = {
            'selected_signal_id': best_signal.signal_id,
            'selected_score': best_score,
            'total_candidates': len(signals),
            'valid_candidates': len(scored_signals),
            'rejected_count': len(signals) - len(scored_signals),
            'scoring_details': best_details,
            'runner_ups': [
                {
                    'signal_id': sig.signal_id,
                    'strategy': sig.strategy_name,
                    'score': score,
                }
                for score, sig, _ in scored_signals[1:3]  # Top 2 runner-ups
            ] if len(scored_signals) > 1 else [],
        }

        logger.info(
            f"Selected best signal from {len(signals)} candidates: "
            f"{best_signal.signal_id[:8]}... (score={best_score:.2f}, "
            f"strategy={best_signal.strategy_name})"
        )

        return best_signal, selection_details

    def cancel_signals(self, signal_ids: List[str]) -> int:
        """
        Cancel specific signals by ID.

        Args:
            signal_ids: List of signal IDs to cancel

        Returns:
            Number of signals cancelled
        """
        cancelled_count = 0

        # Remove signals from queue
        new_queue = []
        for prioritized in self.signal_queue:
            if prioritized.signal.signal_id not in signal_ids:
                new_queue.append(prioritized)
            else:
                cancelled_count += 1
                logger.info(f"Cancelled signal: {prioritized.signal.signal_id[:8]}...")

        # Rebuild heap
        self.signal_queue = new_queue
        heapq.heapify(self.signal_queue)

        self.metrics['signals_cancelled'] += cancelled_count

        return cancelled_count

    def clear_queue(self):
        """Clear all signals from queue"""
        count = len(self.signal_queue)
        self.signal_queue.clear()
        self.metrics['signals_cancelled'] += count
        logger.info(f"Cleared priority queue ({count} signals removed)")

    def get_queue_snapshot(self) -> List[Dict[str, Any]]:
        """
        Get snapshot of current queue state.

        Returns:
            List of signal summaries ordered by priority (highest first)
        """
        # Sort queue by priority score (highest first)
        # Note: PrioritizedSignal.__lt__ is defined so higher scores compare as "less than"
        # for max-heap behavior, so we need to reverse the sort
        sorted_queue = sorted(self.signal_queue, key=lambda p: p.score, reverse=True)

        return [
            {
                'rank': idx + 1,
                'signal_id': p.signal.signal_id,
                'strategy': p.signal.strategy_name,
                'symbol': p.signal.symbol,
                'direction': p.signal.direction.value,
                'confidence': p.signal.confidence,
                'priority_score': p.score,
                'market_condition': p.market_condition.value if p.market_condition else None,
                'timestamp': p.timestamp.isoformat(),
            }
            for idx, p in enumerate(sorted_queue)
        ]

    def get_metrics(self) -> Dict[str, Any]:
        """Get priority manager metrics"""
        avg_score = (
            self.metrics['total_score'] / self.metrics['signals_scored']
            if self.metrics['signals_scored'] > 0 else 0.0
        )

        return {
            'signals_scored': self.metrics['signals_scored'],
            'signals_selected': self.metrics['signals_selected'],
            'signals_cancelled': self.metrics['signals_cancelled'],
            'average_score': avg_score,
            'queue_size': len(self.signal_queue),
            'queue_capacity': self.max_concurrent_signals,
        }

    def update_config(self, **kwargs):
        """
        Update priority configuration at runtime.

        Args:
            **kwargs: Configuration parameters to update
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"Updated priority config: {key}={value}")
            else:
                logger.warning(f"Unknown config parameter: {key}")

    def __repr__(self) -> str:
        return (
            f"SignalPriorityManager(queue={len(self.signal_queue)}/{self.max_concurrent_signals}, "
            f"scored={self.metrics['signals_scored']}, "
            f"selected={self.metrics['signals_selected']})"
        )
