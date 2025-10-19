"""
Historical candle data loader for Binance exchange.

Handles batch loading of historical OHLCV data with rate limiting,
data validation, and integration with CandleStorage.
"""

import asyncio
import logging
import time
from typing import List, Optional, Dict, Any, Set
from datetime import datetime, timezone

from src.core.constants import TimeFrame
from src.models.candle import Candle
from src.services.candle_storage import CandleStorage
from src.services.exchange.binance_manager import BinanceManager, BinanceConnectionError


logger = logging.getLogger(__name__)


class HistoricalDataLoader:
    """
    Loads historical candle data from Binance with intelligent batching and rate limiting.

    Features:
    - Batch loading of up to 1000 candles per request (Binance limit)
    - Automatic rate limiting with exponential backoff
    - Data integrity validation (time ordering, gap detection)
    - Integration with CandleStorage for persistence
    - Efficient loading of multiple symbols/timeframes in parallel

    Example:
        >>> loader = HistoricalDataLoader(binance_manager, candle_storage)
        >>> await loader.load_historical_data('BTCUSDT', TimeFrame.M15, limit=500)
        >>> # Or load multiple symbols at once
        >>> await loader.load_multiple_symbols(
        ...     symbols=['BTCUSDT', 'ETHUSDT'],
        ...     timeframes=[TimeFrame.M15, TimeFrame.H1],
        ...     limit=500
        ... )
    """

    # Binance API limits
    MAX_CANDLES_PER_REQUEST = 1000
    DEFAULT_CANDLES_TO_LOAD = 500

    # Rate limiting configuration
    RATE_LIMIT_REQUESTS_PER_MINUTE = 1200  # Binance weight limit
    RATE_LIMIT_WINDOW_SECONDS = 60
    REQUEST_WEIGHT = 5  # Weight per klines request

    # Backoff configuration
    BACKOFF_BASE_DELAY = 1.0  # Initial delay in seconds
    BACKOFF_MAX_DELAY = 30.0  # Maximum delay in seconds
    BACKOFF_MULTIPLIER = 2.0
    MAX_RETRIES = 5

    def __init__(
        self,
        binance_manager: BinanceManager,
        candle_storage: CandleStorage,
        enable_rate_limiting: bool = True
    ):
        """
        Initialize historical data loader.

        Args:
            binance_manager: Initialized BinanceManager instance
            candle_storage: CandleStorage instance for persistence
            enable_rate_limiting: Enable automatic rate limiting (default: True)
        """
        self.binance_manager = binance_manager
        self.candle_storage = candle_storage
        self.enable_rate_limiting = enable_rate_limiting

        # Rate limiting tracking
        self._request_times: List[float] = []
        self._rate_limit_lock = asyncio.Lock()

        # Statistics
        self._total_candles_loaded = 0
        self._total_requests = 0
        self._rate_limit_delays = 0

        logger.info(
            f"HistoricalDataLoader initialized (rate_limiting={'enabled' if enable_rate_limiting else 'disabled'})"
        )

    async def _wait_for_rate_limit(self) -> None:
        """
        Wait if necessary to comply with rate limits.

        Uses a sliding window approach to track request rate and delays
        if the limit would be exceeded.
        """
        if not self.enable_rate_limiting:
            return

        async with self._rate_limit_lock:
            current_time = time.time()

            # Remove requests outside the time window
            cutoff_time = current_time - self.RATE_LIMIT_WINDOW_SECONDS
            self._request_times = [t for t in self._request_times if t > cutoff_time]

            # Calculate current request weight
            current_weight = len(self._request_times) * self.REQUEST_WEIGHT
            max_weight = self.RATE_LIMIT_REQUESTS_PER_MINUTE

            # Check if we need to wait
            if current_weight >= max_weight:
                # Calculate wait time (wait until oldest request expires)
                if self._request_times:
                    oldest_request = self._request_times[0]
                    wait_time = self.RATE_LIMIT_WINDOW_SECONDS - (current_time - oldest_request)

                    if wait_time > 0:
                        self._rate_limit_delays += 1
                        logger.warning(
                            f"Rate limit approached ({current_weight}/{max_weight} weight). "
                            f"Waiting {wait_time:.1f}s..."
                        )
                        await asyncio.sleep(wait_time)
                        current_time = time.time()

            # Record this request
            self._request_times.append(current_time)

    async def _fetch_ohlcv_with_retry(
        self,
        symbol: str,
        timeframe: TimeFrame,
        since: Optional[int] = None,
        limit: int = MAX_CANDLES_PER_REQUEST
    ) -> List[List]:
        """
        Fetch OHLCV data with exponential backoff retry logic.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            since: Start timestamp in milliseconds
            limit: Maximum candles to fetch

        Returns:
            List of OHLCV arrays

        Raises:
            BinanceConnectionError: If all retry attempts fail
        """
        delay = self.BACKOFF_BASE_DELAY
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                # Wait for rate limit
                await self._wait_for_rate_limit()

                # Fetch data
                logger.debug(
                    f"Fetching OHLCV: {symbol} {timeframe.value} "
                    f"(since={since}, limit={limit}, attempt={attempt + 1})"
                )

                ohlcv = await self.binance_manager.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe.value,
                    since=since,
                    limit=limit
                )

                self._total_requests += 1
                return ohlcv

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Failed to fetch OHLCV for {symbol} {timeframe.value} "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )

                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff
                    logger.info(f"Retrying after {delay}s...")
                    await asyncio.sleep(delay)
                    delay = min(delay * self.BACKOFF_MULTIPLIER, self.BACKOFF_MAX_DELAY)

        # All retries failed
        error_msg = (
            f"Failed to fetch OHLCV after {self.MAX_RETRIES} attempts: "
            f"{symbol} {timeframe.value} - {last_error}"
        )
        logger.error(error_msg)
        raise BinanceConnectionError(error_msg) from last_error

    def _validate_candles(self, candles: List[Candle]) -> Dict[str, Any]:
        """
        Validate loaded candles for data integrity.

        Checks:
        - Time ordering (candles are in chronological order)
        - Gap detection (missing candles in sequence)
        - Duplicate detection

        Args:
            candles: List of candles to validate

        Returns:
            Dictionary with validation results:
            - 'valid': Boolean indicating if data is valid
            - 'issues': List of detected issues
            - 'gaps': List of gap timestamps
            - 'duplicates': List of duplicate timestamps
        """
        if not candles:
            return {
                'valid': True,
                'issues': [],
                'gaps': [],
                'duplicates': []
            }

        issues = []
        gaps = []
        duplicates = []

        # Get timeframe interval
        timeframe = candles[0].timeframe
        interval_ms = Candle.get_timeframe_milliseconds(timeframe)

        # Check time ordering and gaps
        timestamps_seen = set()

        for i, candle in enumerate(candles):
            # Check for duplicates
            if candle.timestamp in timestamps_seen:
                duplicates.append(candle.timestamp)
                issues.append(f"Duplicate candle at {candle.get_datetime_iso()}")
            else:
                timestamps_seen.add(candle.timestamp)

            # Check ordering and gaps (skip first candle)
            if i > 0:
                prev_candle = candles[i - 1]

                # Check time ordering
                if candle.timestamp <= prev_candle.timestamp:
                    issues.append(
                        f"Time ordering violation at index {i}: "
                        f"{prev_candle.get_datetime_iso()} -> {candle.get_datetime_iso()}"
                    )

                # Check for gaps
                expected_timestamp = prev_candle.timestamp + interval_ms
                if candle.timestamp > expected_timestamp:
                    gap_size = (candle.timestamp - expected_timestamp) // interval_ms
                    gaps.append({
                        'start': prev_candle.timestamp,
                        'end': candle.timestamp,
                        'missing_candles': gap_size
                    })
                    issues.append(
                        f"Gap detected: {gap_size} missing candles between "
                        f"{prev_candle.get_datetime_iso()} and {candle.get_datetime_iso()}"
                    )

        valid = len(issues) == 0

        if not valid:
            logger.warning(
                f"Data validation found {len(issues)} issues for "
                f"{candles[0].symbol} {timeframe.value}"
            )

        return {
            'valid': valid,
            'issues': issues,
            'gaps': gaps,
            'duplicates': duplicates
        }

    async def load_historical_data(
        self,
        symbol: str,
        timeframe: TimeFrame,
        limit: int = DEFAULT_CANDLES_TO_LOAD,
        validate: bool = True,
        store: bool = True
    ) -> List[Candle]:
        """
        Load historical candle data for a symbol-timeframe pair.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            timeframe: Candle timeframe
            limit: Number of candles to load (default: 500, max: 1000)
            validate: Validate data integrity (default: True)
            store: Store candles in CandleStorage (default: True)

        Returns:
            List of Candle objects in chronological order

        Raises:
            ValueError: If limit is invalid
            BinanceConnectionError: If data loading fails
        """
        if limit <= 0 or limit > self.MAX_CANDLES_PER_REQUEST:
            raise ValueError(
                f"limit must be between 1 and {self.MAX_CANDLES_PER_REQUEST}, got {limit}"
            )

        logger.info(f"Loading {limit} historical candles for {symbol} {timeframe.value}...")
        start_time = time.time()

        try:
            # Fetch OHLCV data
            ohlcv_data = await self._fetch_ohlcv_with_retry(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not ohlcv_data:
                logger.warning(f"No data returned for {symbol} {timeframe.value}")
                return []

            # Convert to Candle objects
            candles = []
            for ohlcv in ohlcv_data:
                try:
                    candle = Candle.from_ccxt_ohlcv(
                        symbol=symbol,
                        timeframe=timeframe,
                        ohlcv=ohlcv,
                        is_closed=True  # Historical candles are always closed
                    )
                    candles.append(candle)
                except Exception as e:
                    logger.error(f"Failed to parse candle data: {e}", exc_info=True)
                    continue

            logger.info(
                f"Loaded {len(candles)} candles for {symbol} {timeframe.value} "
                f"(requested: {limit})"
            )

            # Validate data integrity
            if validate and candles:
                validation_result = self._validate_candles(candles)

                if not validation_result['valid']:
                    logger.warning(
                        f"Data validation issues for {symbol} {timeframe.value}:\n"
                        + "\n".join(validation_result['issues'][:5])  # Show first 5 issues
                    )
                else:
                    logger.debug(f"Data validation passed for {symbol} {timeframe.value}")

            # Store in CandleStorage
            if store and candles:
                for candle in candles:
                    self.candle_storage.add_candle(candle)

                logger.info(
                    f"Stored {len(candles)} candles in storage for {symbol} {timeframe.value}"
                )

            self._total_candles_loaded += len(candles)
            elapsed = time.time() - start_time

            logger.info(
                f"✓ Historical data load complete: {symbol} {timeframe.value} "
                f"({len(candles)} candles in {elapsed:.2f}s)"
            )

            return candles

        except Exception as e:
            logger.error(
                f"Failed to load historical data for {symbol} {timeframe.value}: {e}",
                exc_info=True
            )
            raise

    async def load_multiple_symbols(
        self,
        symbols: List[str],
        timeframes: List[TimeFrame],
        limit: int = DEFAULT_CANDLES_TO_LOAD,
        validate: bool = True,
        store: bool = True,
        parallel: bool = True
    ) -> Dict[str, Dict[TimeFrame, List[Candle]]]:
        """
        Load historical data for multiple symbol-timeframe combinations.

        Args:
            symbols: List of trading pair symbols
            timeframes: List of timeframes to load
            limit: Number of candles per symbol-timeframe
            validate: Validate data integrity
            store: Store candles in CandleStorage
            parallel: Load data in parallel (default: True)

        Returns:
            Nested dictionary: {symbol: {timeframe: [candles]}}

        Example:
            >>> result = await loader.load_multiple_symbols(
            ...     symbols=['BTCUSDT', 'ETHUSDT'],
            ...     timeframes=[TimeFrame.M15, TimeFrame.H1],
            ...     limit=500
            ... )
            >>> btc_m15_candles = result['BTCUSDT'][TimeFrame.M15]
        """
        logger.info(
            f"Loading historical data for {len(symbols)} symbols × "
            f"{len(timeframes)} timeframes = {len(symbols) * len(timeframes)} combinations"
        )

        start_time = time.time()
        results: Dict[str, Dict[TimeFrame, List[Candle]]] = {}

        # Create tasks for all symbol-timeframe combinations
        tasks = []
        symbol_timeframe_pairs = []

        for symbol in symbols:
            results[symbol] = {}
            for timeframe in timeframes:
                task = self.load_historical_data(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                    validate=validate,
                    store=store
                )
                tasks.append(task)
                symbol_timeframe_pairs.append((symbol, timeframe))

        # Execute tasks
        if parallel:
            # Run in parallel with rate limiting
            logger.info("Loading data in parallel...")
            candle_lists = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # Run sequentially
            logger.info("Loading data sequentially...")
            candle_lists = []
            for task in tasks:
                try:
                    candles = await task
                    candle_lists.append(candles)
                except Exception as e:
                    candle_lists.append(e)

        # Organize results
        for (symbol, timeframe), candles in zip(symbol_timeframe_pairs, candle_lists):
            if isinstance(candles, Exception):
                logger.error(
                    f"Failed to load {symbol} {timeframe.value}: {candles}"
                )
                results[symbol][timeframe] = []
            else:
                results[symbol][timeframe] = candles

        # Summary
        total_candles = sum(
            len(candles)
            for symbol_data in results.values()
            for candles in symbol_data.values()
        )
        elapsed = time.time() - start_time

        logger.info(
            f"✓ Loaded {total_candles} total candles across "
            f"{len(symbols)} symbols × {len(timeframes)} timeframes "
            f"in {elapsed:.2f}s"
        )

        return results

    def get_stats(self) -> Dict[str, Any]:
        """
        Get loader statistics.

        Returns:
            Dictionary with loading statistics
        """
        return {
            'total_candles_loaded': self._total_candles_loaded,
            'total_requests': self._total_requests,
            'rate_limit_delays': self._rate_limit_delays,
            'rate_limiting_enabled': self.enable_rate_limiting
        }

    def reset_stats(self) -> None:
        """Reset loading statistics."""
        self._total_candles_loaded = 0
        self._total_requests = 0
        self._rate_limit_delays = 0
        logger.debug("Loader statistics reset")
