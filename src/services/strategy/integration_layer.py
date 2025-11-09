"""
Strategy Integration Layer

Coordinates multiple trading strategies, manages signal generation,
applies filtering, and publishes validated signals through the event system.
"""

from typing import List, Optional, Dict, Any
from decimal import Decimal
import logging
import pandas as pd

from src.core.events import EventBus, Event, EventType
from src.services.candle_storage import CandleStorage
from src.services.strategy.signal import Signal
from src.services.strategy.generator import (
    SignalGenerator,
    StrategyAGenerator,
    StrategyBGenerator,
    StrategyCGenerator,
)
from src.services.strategy.signal_filter import SignalFilter, FilterConfig
from src.services.strategy.events import (
    SignalEventType,
    publish_signal_generated,
    publish_signal_validated,
    publish_signal_rejected,
    get_event_publisher,
)

logger = logging.getLogger(__name__)


class StrategyIntegrationLayer:
    """
    Integration layer for coordinating multiple trading strategies.

    Responsibilities:
    - Manage multiple strategy generators (A, B, C)
    - Generate signals from active strategies
    - Apply duplicate filtering
    - Publish validated signals via event system
    - Track strategy performance metrics
    """

    def __init__(
        self,
        filter_config: Optional[FilterConfig] = None,
        enable_strategy_a: bool = True,
        enable_strategy_b: bool = True,
        enable_strategy_c: bool = True,
        event_bus: Optional[EventBus] = None,
        candle_storage: Optional[CandleStorage] = None,
    ):
        """
        Initialize strategy integration layer.

        Args:
            filter_config: Signal filter configuration
            enable_strategy_a: Enable Strategy A (Conservative)
            enable_strategy_b: Enable Strategy B (Aggressive)
            enable_strategy_c: Enable Strategy C (Hybrid)
            event_bus: Main event bus for publishing SIGNAL_GENERATED events
            candle_storage: Candle storage for retrieving historical candles
        """
        # Store dependencies
        self.event_bus = event_bus
        self.candle_storage = candle_storage

        # Initialize signal filter
        self.signal_filter = SignalFilter(config=filter_config)

        # Initialize strategy generators
        self.strategies: Dict[str, SignalGenerator] = {}
        self.strategy_enabled: Dict[str, bool] = {}

        if enable_strategy_a:
            self.strategies['Strategy_A'] = StrategyAGenerator()
            self.strategy_enabled['Strategy_A'] = True

        if enable_strategy_b:
            self.strategies['Strategy_B'] = StrategyBGenerator()
            self.strategy_enabled['Strategy_B'] = True

        if enable_strategy_c:
            self.strategies['Strategy_C'] = StrategyCGenerator()
            self.strategy_enabled['Strategy_C'] = True

        # Performance metrics
        self.metrics = {
            'signals_generated': 0,
            'signals_filtered': 0,
            'signals_published': 0,
            'strategy_signals': {name: 0 for name in self.strategies.keys()},
        }

        # Event publisher
        self.event_publisher = get_event_publisher()

        logger.info(
            f"StrategyIntegrationLayer initialized with {len(self.strategies)} strategies: "
            f"{list(self.strategies.keys())}"
        )

    def generate_signals(
        self,
        symbol: str,
        current_price: Decimal,
        candles: pd.DataFrame,
        **kwargs
    ) -> List[Signal]:
        """
        Generate signals from all active strategies.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            current_price: Current market price
            candles: Historical candle data (OHLCV)
            **kwargs: Additional strategy-specific parameters

        Returns:
            List of validated signals (after filtering)
        """
        validated_signals = []

        # Generate signals from each active strategy
        for strategy_name, generator in self.strategies.items():
            if not self.strategy_enabled.get(strategy_name, False):
                logger.debug(f"Strategy {strategy_name} is disabled, skipping")
                continue

            try:
                signal = generator.generate_signal(
                    symbol=symbol,
                    current_price=current_price,
                    candles=candles,
                    **kwargs
                )

                if signal is None:
                    logger.debug(f"No signal from {strategy_name}")
                    continue

                # Signal generated
                self.metrics['signals_generated'] += 1
                self.metrics['strategy_signals'][strategy_name] += 1

                # Publish signal_generated event
                publish_signal_generated(
                    signal,
                    metadata={
                        'strategy': strategy_name,
                        'symbol': symbol,
                    }
                )

                # Apply filtering
                is_accepted = self.signal_filter.add_signal(signal)

                if not is_accepted:
                    # Signal was filtered (duplicate)
                    self.metrics['signals_filtered'] += 1
                    publish_signal_rejected(
                        signal,
                        metadata={
                            'reason': 'duplicate_filtered',
                            'strategy': strategy_name,
                        }
                    )
                    logger.info(
                        f"Signal from {strategy_name} filtered as duplicate: {signal}"
                    )
                else:
                    # Signal passed filtering
                    self.metrics['signals_published'] += 1
                    validated_signals.append(signal)

                    publish_signal_validated(
                        signal,
                        metadata={
                            'strategy': strategy_name,
                            'filter_passed': True,
                        }
                    )
                    logger.info(
                        f"Signal from {strategy_name} validated and published: {signal}"
                    )

            except Exception as e:
                logger.error(
                    f"Error generating signal from {strategy_name}: {e}",
                    exc_info=True
                )
                continue

        logger.info(
            f"Generated {len(validated_signals)} validated signals from "
            f"{len(self.strategies)} strategies for {symbol}"
        )

        return validated_signals

    async def evaluate_strategies(
        self,
        symbol: str,
        timeframe: str,
        indicators: Dict[str, Any],
    ) -> List[Signal]:
        """
        Evaluate all active strategies based on updated indicators.

        This is the async entry point called by the orchestrator when INDICATORS_UPDATED
        events are received. It retrieves candles, generates signals, and publishes them
        to the main EventBus.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe string (e.g., '1m', '5m')
            indicators: Dictionary of indicator data from the event

        Returns:
            List of validated Signal objects
        """
        if not self.candle_storage:
            logger.error("CandleStorage not configured, cannot evaluate strategies")
            return []

        try:
            # Retrieve candles for this symbol/timeframe from storage
            from src.models.timeframe import TimeFrame
            tf = TimeFrame(timeframe)
            candles_df = self.candle_storage.get_candles(symbol, tf, limit=100)

            if candles_df.empty:
                logger.warning(f"No candles available for {symbol} {timeframe}")
                return []

            # Get current price from latest candle
            current_price = Decimal(str(candles_df.iloc[-1]['close']))

            # Generate signals using existing method
            signals = self.generate_signals(
                symbol=symbol,
                current_price=current_price,
                candles=candles_df,
                indicators=indicators
            )

            # Publish SIGNAL_GENERATED events to main EventBus if configured
            if self.event_bus and signals:
                for signal in signals:
                    event = Event(
                        priority=6,
                        event_type=EventType.SIGNAL_GENERATED,
                        data={
                            'signal': signal.to_dict(),
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'strategy': signal.strategy_name if hasattr(signal, 'strategy_name') else 'unknown'
                        },
                        source='StrategyIntegrationLayer'
                    )
                    await self.event_bus.publish(event)
                    logger.debug(f"Published SIGNAL_GENERATED event for {symbol} {timeframe}")

            return signals

        except Exception as e:
            logger.error(f"Error evaluating strategies for {symbol} {timeframe}: {e}", exc_info=True)
            return []

    def enable_strategy(self, strategy_name: str):
        """
        Enable a specific strategy.

        Args:
            strategy_name: Name of strategy to enable (e.g., 'Strategy_A')
        """
        if strategy_name not in self.strategies:
            logger.warning(f"Unknown strategy: {strategy_name}")
            return

        self.strategy_enabled[strategy_name] = True
        logger.info(f"Strategy {strategy_name} enabled")

    def disable_strategy(self, strategy_name: str):
        """
        Disable a specific strategy.

        Args:
            strategy_name: Name of strategy to disable (e.g., 'Strategy_A')
        """
        if strategy_name not in self.strategies:
            logger.warning(f"Unknown strategy: {strategy_name}")
            return

        self.strategy_enabled[strategy_name] = False
        logger.info(f"Strategy {strategy_name} disabled")

    def update_filter_config(self, **kwargs):
        """
        Update signal filter configuration at runtime.

        Args:
            **kwargs: Filter configuration parameters

        Example:
            integration_layer.update_filter_config(
                time_window_minutes=10,
                price_threshold_pct=2.0
            )
        """
        self.signal_filter.update_config(**kwargs)
        logger.info(f"Updated filter config: {kwargs}")

    def update_active_positions(self, positions: List[Dict[str, Any]]):
        """
        Update active positions for position conflict detection.

        Args:
            positions: List of active position dictionaries
        """
        self.signal_filter.update_active_positions(positions)

    def get_strategy_status(self) -> Dict[str, Any]:
        """
        Get status of all strategies.

        Returns:
            Dictionary with strategy status and configuration
        """
        return {
            'strategies': {
                name: {
                    'enabled': self.strategy_enabled.get(name, False),
                    'signals_generated': self.metrics['strategy_signals'].get(name, 0),
                }
                for name in self.strategies.keys()
            },
            'filter_config': self.signal_filter.config.to_dict(),
        }

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics.

        Returns:
            Dictionary with performance statistics
        """
        filter_stats = self.signal_filter.get_statistics()

        return {
            'signals_generated': self.metrics['signals_generated'],
            'signals_filtered': self.metrics['signals_filtered'],
            'signals_published': self.metrics['signals_published'],
            'strategy_signals': self.metrics['strategy_signals'],
            'filter_statistics': filter_stats,
        }

    def reset_metrics(self):
        """Reset all performance metrics"""
        self.metrics = {
            'signals_generated': 0,
            'signals_filtered': 0,
            'signals_published': 0,
            'strategy_signals': {name: 0 for name in self.strategies.keys()},
        }
        self.signal_filter.reset_statistics()
        logger.info("Integration layer metrics reset")

    def __repr__(self) -> str:
        active_strategies = sum(1 for enabled in self.strategy_enabled.values() if enabled)
        return (
            f"StrategyIntegrationLayer(strategies={active_strategies}/{len(self.strategies)}, "
            f"signals_published={self.metrics['signals_published']}, "
            f"filter_rate={self.signal_filter.get_statistics()['filter_rate_pct']:.1f}%)"
        )
