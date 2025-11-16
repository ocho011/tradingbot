"""
Thread-safe in-memory candle storage system using deque.

This module provides high-performance candle storage with automatic LRU eviction
and memory monitoring capabilities.
"""

import logging
import sys
from collections import deque
from dataclasses import dataclass
from threading import RLock
from typing import Deque, Dict, List, Optional, Tuple

from src.core.constants import TimeFrame
from src.models.candle import Candle

logger = logging.getLogger(__name__)


@dataclass
class StorageStats:
    """Statistics for candle storage monitoring."""

    total_candles: int = 0
    storage_count: int = 0  # Number of symbol-timeframe pairs
    memory_bytes: int = 0
    evictions: int = 0

    @property
    def memory_mb(self) -> float:
        """Get memory usage in megabytes."""
        return round(self.memory_bytes / (1024 * 1024), 2)

    def to_dict(self) -> dict:
        """Convert stats to dictionary."""
        return {
            "total_candles": self.total_candles,
            "storage_count": self.storage_count,
            "memory_bytes": self.memory_bytes,
            "memory_mb": self.memory_mb,
            "evictions": self.evictions,
        }


class CandleStorage:
    """
    Thread-safe in-memory storage for candle data.

    Features:
    - Separate storage per symbol-timeframe pair
    - Maximum 500 candles per storage (LRU eviction)
    - Thread-safe operations using RLock
    - Memory usage monitoring
    - O(1) append and eviction operations via deque

    Example:
        >>> storage = CandleStorage(max_candles=500)
        >>> candle = Candle(symbol='BTCUSDT', timeframe=TimeFrame.M1, ...)
        >>> storage.add_candle(candle)
        >>> candles = storage.get_candles('BTCUSDT', TimeFrame.M1, limit=100)
    """

    def __init__(self, max_candles: int = 500):
        """
        Initialize candle storage.

        Args:
            max_candles: Maximum candles to store per symbol-timeframe pair
        """
        if max_candles <= 0:
            raise ValueError(f"max_candles must be positive, got {max_candles}")

        self._max_candles = max_candles
        self._storage: Dict[Tuple[str, TimeFrame], Deque[Candle]] = {}
        self._lock = RLock()
        self._eviction_count = 0

        logger.info(f"CandleStorage initialized with max_candles={max_candles}")

    def _get_storage_key(self, symbol: str, timeframe: TimeFrame) -> Tuple[str, TimeFrame]:
        """
        Get storage key for symbol-timeframe pair.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe

        Returns:
            Tuple key for storage dictionary
        """
        return (symbol.upper(), timeframe)

    def add_candle(self, candle: Candle) -> None:
        """
        Add candle to storage with automatic LRU eviction.

        Thread-safe operation that adds a new candle and removes oldest
        candle if max capacity is reached.

        Args:
            candle: Candle instance to store

        Example:
            >>> storage.add_candle(candle)
        """
        key = self._get_storage_key(candle.symbol, candle.timeframe)

        with self._lock:
            # Create storage if doesn't exist
            if key not in self._storage:
                self._storage[key] = deque(maxlen=self._max_candles)
                logger.debug(f"Created new storage for {key}")

            storage = self._storage[key]

            # Check if we'll evict (storage is at max capacity)
            will_evict = len(storage) >= self._max_candles

            # Add candle (deque automatically evicts oldest if at maxlen)
            storage.append(candle)

            if will_evict:
                self._eviction_count += 1
                logger.debug(
                    f"Evicted oldest candle for {candle.symbol} {candle.timeframe.value} "
                    f"(total evictions: {self._eviction_count})"
                )

            logger.debug(
                f"Added candle for {candle.symbol} {candle.timeframe.value} "
                f"@ {candle.get_datetime_iso()} (storage size: {len(storage)})"
            )

    def get_candles(
        self,
        symbol: str,
        timeframe: TimeFrame,
        limit: Optional[int] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Candle]:
        """
        Get candles from storage with optional filtering.

        Thread-safe operation that retrieves candles in chronological order.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            limit: Maximum number of candles to return (most recent)
            start_time: Filter candles >= this timestamp (milliseconds)
            end_time: Filter candles <= this timestamp (milliseconds)

        Returns:
            List of candles in chronological order (oldest first)

        Example:
            >>> # Get last 100 candles
            >>> candles = storage.get_candles('BTCUSDT', TimeFrame.M1, limit=100)
            >>>
            >>> # Get candles in time range
            >>> candles = storage.get_candles(
            ...     'BTCUSDT', TimeFrame.M1,
            ...     start_time=1704067200000,
            ...     end_time=1704153600000
            ... )
        """
        key = self._get_storage_key(symbol, timeframe)

        with self._lock:
            if key not in self._storage:
                logger.debug(f"No storage found for {symbol} {timeframe.value}")
                return []

            storage = self._storage[key]
            candles = list(storage)  # Convert deque to list

            # Apply time filters
            if start_time is not None:
                candles = [c for c in candles if c.timestamp >= start_time]

            if end_time is not None:
                candles = [c for c in candles if c.timestamp <= end_time]

            # Apply limit (get most recent)
            if limit is not None:
                if limit <= 0:
                    candles = []
                else:
                    candles = candles[-limit:]

            logger.debug(
                f"Retrieved {len(candles)} candles for {symbol} {timeframe.value} "
                f"(filters: limit={limit}, start_time={start_time}, end_time={end_time})"
            )

            return candles

    def get_latest_candle(self, symbol: str, timeframe: TimeFrame) -> Optional[Candle]:
        """
        Get the most recent candle for symbol-timeframe pair.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe

        Returns:
            Most recent candle or None if storage is empty

        Example:
            >>> latest = storage.get_latest_candle('BTCUSDT', TimeFrame.M1)
        """
        key = self._get_storage_key(symbol, timeframe)

        with self._lock:
            if key not in self._storage or len(self._storage[key]) == 0:
                return None

            return self._storage[key][-1]  # Most recent candle

    def remove_candles(
        self, symbol: str, timeframe: TimeFrame, before_timestamp: Optional[int] = None
    ) -> int:
        """
        Remove candles from storage.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            before_timestamp: Remove candles older than this timestamp (milliseconds).
                            If None, removes all candles for the symbol-timeframe pair.

        Returns:
            Number of candles removed

        Example:
            >>> # Remove all candles older than timestamp
            >>> removed = storage.remove_candles('BTCUSDT', TimeFrame.M1, before_timestamp=1704067200000)
            >>>
            >>> # Remove all candles for symbol-timeframe
            >>> removed = storage.remove_candles('BTCUSDT', TimeFrame.M1)
        """
        key = self._get_storage_key(symbol, timeframe)

        with self._lock:
            if key not in self._storage:
                return 0

            storage = self._storage[key]

            if before_timestamp is None:
                # Remove all candles
                count = len(storage)
                del self._storage[key]
                logger.info(f"Removed all {count} candles for {symbol} {timeframe.value}")
                return count

            # Remove candles before timestamp
            original_count = len(storage)

            # Convert to list, filter, and create new deque
            remaining = [c for c in storage if c.timestamp >= before_timestamp]
            self._storage[key] = deque(remaining, maxlen=self._max_candles)

            removed_count = original_count - len(remaining)

            if removed_count > 0:
                logger.info(
                    f"Removed {removed_count} candles before {before_timestamp} "
                    f"for {symbol} {timeframe.value}"
                )

            # Clean up empty storage
            if len(self._storage[key]) == 0:
                del self._storage[key]

            return removed_count

    def clear(self, symbol: Optional[str] = None, timeframe: Optional[TimeFrame] = None) -> int:
        """
        Clear storage for specific symbol-timeframe or all storage.

        Args:
            symbol: If provided, clear only this symbol's data
            timeframe: If provided with symbol, clear only this timeframe

        Returns:
            Number of candles removed

        Example:
            >>> # Clear all storage
            >>> storage.clear()
            >>>
            >>> # Clear all timeframes for a symbol
            >>> storage.clear(symbol='BTCUSDT')
            >>>
            >>> # Clear specific symbol-timeframe
            >>> storage.clear(symbol='BTCUSDT', timeframe=TimeFrame.M1)
        """
        with self._lock:
            if symbol is None:
                # Clear everything
                total = sum(len(storage) for storage in self._storage.values())
                self._storage.clear()
                self._eviction_count = 0
                logger.info(f"Cleared all storage ({total} candles)")
                return total

            if timeframe is not None:
                # Clear specific symbol-timeframe
                return self.remove_candles(symbol, timeframe)

            # Clear all timeframes for symbol
            symbol_upper = symbol.upper()
            keys_to_remove = [key for key in self._storage.keys() if key[0] == symbol_upper]

            total = 0
            for key in keys_to_remove:
                total += len(self._storage[key])
                del self._storage[key]

            logger.info(f"Cleared {total} candles for symbol {symbol}")
            return total

    def get_storage_count(self, symbol: Optional[str] = None) -> int:
        """
        Get count of symbol-timeframe storage pairs.

        Args:
            symbol: If provided, count only for this symbol

        Returns:
            Number of storage pairs
        """
        with self._lock:
            if symbol is None:
                return len(self._storage)

            symbol_upper = symbol.upper()
            return sum(1 for key in self._storage.keys() if key[0] == symbol_upper)

    def get_candle_count(
        self, symbol: Optional[str] = None, timeframe: Optional[TimeFrame] = None
    ) -> int:
        """
        Get total count of stored candles.

        Args:
            symbol: If provided, count only for this symbol
            timeframe: If provided with symbol, count only for this timeframe

        Returns:
            Total number of candles
        """
        with self._lock:
            if symbol is None:
                return sum(len(storage) for storage in self._storage.values())

            if timeframe is not None:
                key = self._get_storage_key(symbol, timeframe)
                return len(self._storage.get(key, []))

            symbol_upper = symbol.upper()
            return sum(
                len(storage) for key, storage in self._storage.items() if key[0] == symbol_upper
            )

    def get_memory_usage(self) -> int:
        """
        Estimate memory usage in bytes.

        Returns:
            Approximate memory usage in bytes

        Note:
            This is an approximation using sys.getsizeof which may not
            account for all Python object overhead.
        """
        with self._lock:
            total_bytes = 0

            # Storage dictionary overhead
            total_bytes += sys.getsizeof(self._storage)

            # Each storage deque and its candles
            for key, storage in self._storage.items():
                total_bytes += sys.getsizeof(key)
                total_bytes += sys.getsizeof(storage)

                for candle in storage:
                    total_bytes += sys.getsizeof(candle)

            return total_bytes

    def get_stats(self) -> StorageStats:
        """
        Get comprehensive storage statistics.

        Returns:
            StorageStats with current storage metrics

        Example:
            >>> stats = storage.get_stats()
            >>> print(f"Total candles: {stats.total_candles}")
            >>> print(f"Memory usage: {stats.memory_mb} MB")
        """
        with self._lock:
            return StorageStats(
                total_candles=self.get_candle_count(),
                storage_count=self.get_storage_count(),
                memory_bytes=self.get_memory_usage(),
                evictions=self._eviction_count,
            )

    def get_symbols(self) -> List[str]:
        """
        Get list of all symbols currently stored.

        Returns:
            List of unique symbol strings
        """
        with self._lock:
            return sorted(set(key[0] for key in self._storage.keys()))

    def get_timeframes(self, symbol: str) -> List[TimeFrame]:
        """
        Get list of timeframes stored for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            List of TimeFrame enums
        """
        symbol_upper = symbol.upper()

        with self._lock:
            timeframes = [key[1] for key in self._storage.keys() if key[0] == symbol_upper]
            return sorted(timeframes, key=lambda tf: Candle.get_timeframe_milliseconds(tf))

    @property
    def max_candles(self) -> int:
        """Maximum candles per storage."""
        return self._max_candles

    def __repr__(self) -> str:
        """String representation of storage."""
        stats = self.get_stats()
        return (
            f"CandleStorage(max_candles={self._max_candles}, "
            f"storages={stats.storage_count}, "
            f"total_candles={stats.total_candles}, "
            f"memory_mb={stats.memory_mb})"
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        stats = self.get_stats()
        return (
            f"CandleStorage: {stats.total_candles} candles across {stats.storage_count} storages, "
            f"using {stats.memory_mb} MB"
        )
