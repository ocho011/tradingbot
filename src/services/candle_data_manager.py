"""
Multi-symbol and multi-timeframe candle data management system.

This module provides the CandleDataManager class that orchestrates
real-time candle processing across multiple trading pairs and timeframes,
with dynamic configuration, resource monitoring, and state management.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, List, Optional, Set

import psutil

from src.core.constants import EventType, TimeFrame
from src.core.events import Event, EventBus
from src.models.candle import Candle
from src.services.candle_storage import CandleStorage
from src.services.exchange.realtime_processor import RealtimeCandleProcessor

logger = logging.getLogger(__name__)


@dataclass
class SymbolConfig:
    """Configuration for a trading symbol."""

    symbol: str
    timeframes: Set[TimeFrame] = field(default_factory=set)
    enabled: bool = True
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "timeframes": [
                tf.value
                for tf in sorted(
                    self.timeframes, key=lambda x: Candle.get_timeframe_milliseconds(x)
                )
            ],
            "enabled": self.enabled,
            "added_at": self.added_at.isoformat(),
        }


@dataclass
class SystemMetrics:
    """System resource usage metrics."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_mb: float = 0.0
    process_memory_mb: float = 0.0
    candle_storage_mb: float = 0.0
    total_candles: int = 0
    active_symbols: int = 0
    active_timeframes: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_percent": round(self.memory_percent, 2),
            "memory_mb": round(self.memory_mb, 2),
            "process_memory_mb": round(self.process_memory_mb, 2),
            "candle_storage_mb": round(self.candle_storage_mb, 2),
            "total_candles": self.total_candles,
            "active_symbols": self.active_symbols,
            "active_timeframes": self.active_timeframes,
            "timestamp": self.timestamp.isoformat(),
        }


class CandleDataManager:
    """
    Orchestrates multi-symbol and multi-timeframe candle data management.

    Features:
    - Manages multiple trading pairs (e.g., BTCUSDT, ETHUSDT)
    - Supports multiple timeframes per symbol (e.g., 1m, 15m, 1h)
    - Dynamic symbol/timeframe addition and removal
    - Centralized storage coordination via CandleStorage
    - System resource monitoring and optimization
    - Memory usage tracking and garbage collection
    - Real-time state monitoring dashboard
    - Thread-safe operations

    Example:
        >>> manager = CandleDataManager(event_bus, max_candles_per_storage=500)
        >>> await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
        >>> await manager.add_symbol('ETHUSDT', [TimeFrame.M1, TimeFrame.H1])
        >>> stats = manager.get_dashboard_state()
        >>> print(f"Managing {stats['total_symbols']} symbols")
    """

    def __init__(
        self,
        event_bus: EventBus,
        max_candles_per_storage: int = 500,
        enable_monitoring: bool = True,
        monitoring_interval: int = 60,
    ):
        """
        Initialize the candle data manager.

        Args:
            event_bus: Event bus for publishing/subscribing to events
            max_candles_per_storage: Maximum candles per symbol-timeframe storage
            enable_monitoring: Enable system resource monitoring
            monitoring_interval: Monitoring interval in seconds
        """
        self.event_bus = event_bus
        self._max_candles = max_candles_per_storage
        self._enable_monitoring = enable_monitoring
        self._monitoring_interval = monitoring_interval

        # Centralized storage for all symbols and timeframes
        self._storage = CandleStorage(max_candles=max_candles_per_storage)

        # Real-time processor (shared across all symbols/timeframes)
        self._processor = RealtimeCandleProcessor(event_bus=event_bus, storage=self._storage)

        # Symbol configurations
        self._symbols: Dict[str, SymbolConfig] = {}
        self._lock = RLock()

        # Monitoring state
        self._monitoring_task: Optional[asyncio.Task] = None
        self._latest_metrics: Optional[SystemMetrics] = None
        self._process = psutil.Process()

        # Statistics
        self._start_time = datetime.now(timezone.utc)

        logger.info(
            f"CandleDataManager initialized "
            f"(max_candles={max_candles_per_storage}, "
            f"monitoring={'enabled' if enable_monitoring else 'disabled'})"
        )

    async def start(self) -> None:
        """Start the candle data manager."""
        logger.info("Starting CandleDataManager...")

        # Register event handler (subscribe is not async)
        self.event_bus.subscribe(EventType.CANDLE_RECEIVED, self._processor)

        # Start monitoring if enabled
        if self._enable_monitoring:
            self._monitoring_task = asyncio.create_task(self._monitor_resources())

        logger.info("CandleDataManager started successfully")

    async def stop(self) -> None:
        """Stop the candle data manager."""
        logger.info("Stopping CandleDataManager...")

        # Stop monitoring
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        # Unregister event handler (unsubscribe is not async)
        self.event_bus.unsubscribe(EventType.CANDLE_RECEIVED, self._processor)

        logger.info("CandleDataManager stopped")

    async def add_symbol(
        self, symbol: str, timeframes: List[TimeFrame], replace: bool = False
    ) -> None:
        """
        Add a new symbol with specified timeframes to manage.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            timeframes: List of timeframes to track for this symbol
            replace: If True, replace existing configuration; if False, merge

        Raises:
            ValueError: If symbol or timeframes are invalid

        Example:
            >>> await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15])
            >>> await manager.add_symbol('ETHUSDT', [TimeFrame.M1, TimeFrame.H1])
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")

        if not timeframes:
            raise ValueError("Must specify at least one timeframe")

        symbol_upper = symbol.upper()

        with self._lock:
            if symbol_upper in self._symbols:
                if replace:
                    # Replace entire configuration
                    self._symbols[symbol_upper] = SymbolConfig(
                        symbol=symbol_upper, timeframes=set(timeframes)
                    )
                    logger.info(
                        f"Replaced symbol configuration: {symbol_upper} with {len(timeframes)} timeframes"
                    )
                else:
                    # Merge with existing timeframes
                    existing = self._symbols[symbol_upper]
                    new_timeframes = set(timeframes) - existing.timeframes
                    existing.timeframes.update(timeframes)

                    if new_timeframes:
                        logger.info(
                            f"Added {len(new_timeframes)} new timeframes to {symbol_upper}: "
                            f"{[tf.value for tf in new_timeframes]}"
                        )
            else:
                # New symbol
                self._symbols[symbol_upper] = SymbolConfig(
                    symbol=symbol_upper, timeframes=set(timeframes)
                )
                logger.info(
                    f"Added new symbol: {symbol_upper} with timeframes: "
                    f"{[tf.value for tf in timeframes]}"
                )

        # Publish event for symbol addition
        await self.event_bus.publish(
            Event(
                event_type=EventType.SYSTEM_START,  # Reusing existing event type
                priority=5,
                data={
                    "action": "symbol_added",
                    "symbol": symbol_upper,
                    "timeframes": [tf.value for tf in timeframes],
                },
                source="CandleDataManager",
            )
        )

    async def remove_symbol(
        self, symbol: str, timeframes: Optional[List[TimeFrame]] = None, clear_data: bool = False
    ) -> bool:
        """
        Remove a symbol or specific timeframes from management.

        Args:
            symbol: Trading pair symbol
            timeframes: Specific timeframes to remove (None = remove all)
            clear_data: If True, also clear stored candle data

        Returns:
            True if symbol/timeframes were removed, False if not found

        Example:
            >>> # Remove specific timeframes
            >>> await manager.remove_symbol('BTCUSDT', [TimeFrame.M1])
            >>>
            >>> # Remove entire symbol
            >>> await manager.remove_symbol('BTCUSDT', clear_data=True)
        """
        symbol_upper = symbol.upper()

        with self._lock:
            if symbol_upper not in self._symbols:
                logger.warning(f"Symbol not found: {symbol_upper}")
                return False

            config = self._symbols[symbol_upper]

            if timeframes is None:
                # Remove entire symbol
                del self._symbols[symbol_upper]

                if clear_data:
                    cleared = self._storage.clear(symbol=symbol_upper)
                    logger.info(f"Removed symbol {symbol_upper} and cleared {cleared} candles")
                else:
                    logger.info(f"Removed symbol {symbol_upper} (data retained)")

                return True
            else:
                # Remove specific timeframes
                removed_tfs = config.timeframes.intersection(set(timeframes))
                config.timeframes.difference_update(timeframes)

                if clear_data:
                    cleared_total = 0
                    for tf in removed_tfs:
                        cleared = self._storage.clear(symbol=symbol_upper, timeframe=tf)
                        cleared_total += cleared

                    logger.info(
                        f"Removed {len(removed_tfs)} timeframes from {symbol_upper}, "
                        f"cleared {cleared_total} candles"
                    )
                else:
                    logger.info(
                        f"Removed {len(removed_tfs)} timeframes from {symbol_upper} "
                        f"(data retained)"
                    )

                # Remove symbol config if no timeframes left
                if not config.timeframes:
                    del self._symbols[symbol_upper]
                    logger.info(f"Removed {symbol_upper} config (no timeframes remaining)")

                return len(removed_tfs) > 0

    def get_symbols(self) -> List[str]:
        """
        Get list of all managed symbols.

        Returns:
            List of symbol strings
        """
        with self._lock:
            return sorted(self._symbols.keys())

    def get_timeframes(self, symbol: str) -> List[TimeFrame]:
        """
        Get timeframes for a specific symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            List of TimeFrame enums, sorted by duration
        """
        symbol_upper = symbol.upper()

        with self._lock:
            if symbol_upper not in self._symbols:
                return []

            timeframes = self._symbols[symbol_upper].timeframes
            return sorted(timeframes, key=lambda tf: Candle.get_timeframe_milliseconds(tf))

    def get_symbol_config(self, symbol: str) -> Optional[dict]:
        """
        Get configuration for a specific symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Symbol configuration dictionary or None if not found
        """
        symbol_upper = symbol.upper()

        with self._lock:
            if symbol_upper not in self._symbols:
                return None

            return self._symbols[symbol_upper].to_dict()

    def get_candles(
        self, symbol: str, timeframe: TimeFrame, limit: Optional[int] = None
    ) -> List[Candle]:
        """
        Get candles for a specific symbol and timeframe.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            limit: Maximum number of candles to return

        Returns:
            List of candles in chronological order
        """
        return self._storage.get_candles(symbol, timeframe, limit=limit)

    def get_latest_candle(self, symbol: str, timeframe: TimeFrame) -> Optional[Candle]:
        """
        Get the most recent candle for symbol-timeframe.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe

        Returns:
            Latest candle or None
        """
        return self._storage.get_latest_candle(symbol, timeframe)

    async def _monitor_resources(self) -> None:
        """Background task to monitor system resources."""
        logger.info(f"Resource monitoring started (interval: {self._monitoring_interval}s)")

        try:
            while True:
                try:
                    # Collect system metrics
                    metrics = self._collect_metrics()
                    self._latest_metrics = metrics

                    # Log warnings if resources are high
                    if metrics.memory_percent > 80:
                        logger.warning(
                            f"High memory usage: {metrics.memory_percent:.1f}% "
                            f"({metrics.memory_mb:.1f} MB)"
                        )

                    if metrics.cpu_percent > 80:
                        logger.warning(f"High CPU usage: {metrics.cpu_percent:.1f}%")

                    # Log storage stats periodically
                    if metrics.total_candles > 0:
                        logger.debug(
                            f"Storage: {metrics.total_candles} candles, "
                            f"{metrics.candle_storage_mb:.1f} MB, "
                            f"{metrics.active_symbols} symbols, "
                            f"{metrics.active_timeframes} timeframes"
                        )

                except Exception as e:
                    logger.error(f"Error collecting metrics: {e}", exc_info=True)

                await asyncio.sleep(self._monitoring_interval)

        except asyncio.CancelledError:
            logger.info("Resource monitoring stopped")
            raise

    def _collect_metrics(self) -> SystemMetrics:
        """
        Collect current system resource metrics.

        Returns:
            SystemMetrics with current resource usage
        """
        # System-wide metrics
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()

        # Process-specific metrics
        process_memory = self._process.memory_info()

        # Storage metrics
        storage_stats = self._storage.get_stats()

        # Active symbols/timeframes
        with self._lock:
            active_symbols = len(self._symbols)
            active_timeframes = sum(len(config.timeframes) for config in self._symbols.values())

        return SystemMetrics(
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_mb=memory.used / (1024 * 1024),
            process_memory_mb=process_memory.rss / (1024 * 1024),
            candle_storage_mb=storage_stats.memory_mb,
            total_candles=storage_stats.total_candles,
            active_symbols=active_symbols,
            active_timeframes=active_timeframes,
        )

    def get_dashboard_state(self) -> dict:
        """
        Get comprehensive dashboard state for monitoring.

        Returns:
            Dictionary with complete system state information

        Example:
            >>> state = manager.get_dashboard_state()
            >>> print(f"Total symbols: {state['total_symbols']}")
            >>> print(f"Memory usage: {state['metrics']['memory_mb']} MB")
        """
        with self._lock:
            # Symbol information
            symbols_info = {symbol: config.to_dict() for symbol, config in self._symbols.items()}

            # Storage statistics
            storage_stats = self._storage.get_stats()

            # Processor statistics
            processor_stats = self._processor.get_statistics()

            # System metrics
            metrics = self._latest_metrics.to_dict() if self._latest_metrics else None

            # Uptime
            uptime_seconds = (datetime.now(timezone.utc) - self._start_time).total_seconds()

            return {
                "total_symbols": len(self._symbols),
                "symbols": symbols_info,
                "storage": storage_stats.to_dict(),
                "processor": processor_stats,
                "metrics": metrics,
                "uptime_seconds": round(uptime_seconds, 1),
                "started_at": self._start_time.isoformat(),
                "monitoring_enabled": self._enable_monitoring,
            }

    def get_memory_usage_summary(self) -> dict:
        """
        Get detailed memory usage breakdown.

        Returns:
            Dictionary with memory usage by symbol and timeframe
        """
        with self._lock:
            summary = {}

            for symbol in self._symbols.keys():
                symbol_memory = 0
                timeframe_breakdown = {}

                for timeframe in self.get_timeframes(symbol):
                    candle_count = self._storage.get_candle_count(symbol, timeframe)
                    # Estimate: ~200 bytes per candle (approximate)
                    estimated_bytes = candle_count * 200

                    timeframe_breakdown[timeframe.value] = {
                        "candles": candle_count,
                        "estimated_mb": round(estimated_bytes / (1024 * 1024), 3),
                    }
                    symbol_memory += estimated_bytes

                summary[symbol] = {
                    "total_mb": round(symbol_memory / (1024 * 1024), 3),
                    "timeframes": timeframe_breakdown,
                }

            return summary

    async def optimize_memory(self, aggressive: bool = False) -> dict:
        """
        Perform memory optimization and garbage collection.

        Args:
            aggressive: If True, perform more aggressive cleanup

        Returns:
            Dictionary with optimization results
        """
        import gc

        logger.info(f"Starting memory optimization (aggressive={aggressive})")

        # Collect metrics before
        before_metrics = self._collect_metrics()

        # Force garbage collection
        collected = gc.collect()

        if aggressive:
            # More aggressive GC
            gc.collect(generation=2)

        # Collect metrics after
        after_metrics = self._collect_metrics()

        memory_freed_mb = before_metrics.process_memory_mb - after_metrics.process_memory_mb

        result = {
            "gc_objects_collected": collected,
            "memory_freed_mb": round(memory_freed_mb, 2),
            "before_memory_mb": round(before_metrics.process_memory_mb, 2),
            "after_memory_mb": round(after_metrics.process_memory_mb, 2),
            "aggressive": aggressive,
        }

        logger.info(
            f"Memory optimization completed: freed {memory_freed_mb:.2f} MB, "
            f"collected {collected} objects"
        )

        return result

    def __repr__(self) -> str:
        """String representation."""
        with self._lock:
            return (
                f"CandleDataManager(symbols={len(self._symbols)}, "
                f"max_candles={self._max_candles}, "
                f"monitoring={'enabled' if self._enable_monitoring else 'disabled'})"
            )

    def __str__(self) -> str:
        """Human-readable representation."""
        storage_stats = self._storage.get_stats()
        with self._lock:
            return (
                f"CandleDataManager: {len(self._symbols)} symbols, "
                f"{storage_stats.total_candles} candles, "
                f"{storage_stats.memory_mb} MB"
            )
