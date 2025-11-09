"""
Parallel Processing Coordination for Trading System.

This module provides utilities for coordinating parallel processing of:
- Market data reception and parsing
- Indicator calculations across multiple timeframes
- Signal generation from multiple strategies
- Risk validation and order execution

Task 11.3 implementation.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar
from collections import defaultdict

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class ParallelExecutionResult:
    """Result from parallel execution."""
    success_count: int
    error_count: int
    results: List[Any]
    errors: List[Exception]
    execution_time_seconds: float


class ParallelProcessor:
    """
    Coordinate parallel processing of trading system operations.

    Features:
    - Concurrent execution with configurable limits
    - Error isolation (one failure doesn't stop others)
    - Result aggregation and error reporting
    - Performance monitoring
    - Backpressure management

    Usage:
        processor = ParallelProcessor(max_concurrent=10)

        # Process multiple items in parallel
        results = await processor.process_batch(
            items=['BTCUSDT', 'ETHUSDT', 'BNBUSDT'],
            processor_func=fetch_market_data
        )

        # Execute multiple coroutines in parallel
        results = await processor.gather_with_error_handling([
            process_candle(candle1),
            process_candle(candle2),
            process_candle(candle3)
        ])
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        timeout_seconds: Optional[float] = 30.0,
        enable_metrics: bool = True
    ):
        """
        Initialize parallel processor.

        Args:
            max_concurrent: Maximum concurrent operations
            timeout_seconds: Timeout for individual operations
            enable_metrics: Enable performance metrics collection
        """
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self.enable_metrics = enable_metrics

        # Metrics
        self._total_executions = 0
        self._total_successes = 0
        self._total_errors = 0
        self._total_execution_time = 0.0
        self._execution_times_by_operation: Dict[str, List[float]] = defaultdict(list)

        # Semaphore for concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent)

        logger.info(
            f"ParallelProcessor initialized (max_concurrent={max_concurrent})"
        )

    async def process_batch(
        self,
        items: List[T],
        processor_func: Callable[[T], Coroutine],
        operation_name: Optional[str] = None
    ) -> ParallelExecutionResult:
        """
        Process a batch of items in parallel.

        Args:
            items: List of items to process
            processor_func: Async function to process each item
            operation_name: Name for metrics tracking

        Returns:
            ParallelExecutionResult with aggregated results
        """
        start_time = datetime.now()

        # Create tasks for all items
        tasks = [
            self._process_with_semaphore(item, processor_func)
            for item in items
        ]

        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successes and errors
        successes = []
        errors = []

        for result in results:
            if isinstance(result, Exception):
                errors.append(result)
            else:
                successes.append(result)

        execution_time = (datetime.now() - start_time).total_seconds()

        # Update metrics
        if self.enable_metrics:
            self._total_executions += len(items)
            self._total_successes += len(successes)
            self._total_errors += len(errors)
            self._total_execution_time += execution_time

            if operation_name:
                self._execution_times_by_operation[operation_name].append(
                    execution_time
                )

        logger.info(
            f"Batch processing completed: {len(successes)} successes, "
            f"{len(errors)} errors in {execution_time:.2f}s"
        )

        return ParallelExecutionResult(
            success_count=len(successes),
            error_count=len(errors),
            results=successes,
            errors=errors,
            execution_time_seconds=execution_time
        )

    async def _process_with_semaphore(
        self,
        item: T,
        processor_func: Callable[[T], Coroutine]
    ) -> Any:
        """
        Process item with semaphore-based concurrency control.

        Args:
            item: Item to process
            processor_func: Processor function

        Returns:
            Processing result

        Raises:
            Exception: If processing fails
        """
        async with self._semaphore:
            if self.timeout_seconds:
                return await asyncio.wait_for(
                    processor_func(item),
                    timeout=self.timeout_seconds
                )
            else:
                return await processor_func(item)

    async def gather_with_error_handling(
        self,
        coroutines: List[Coroutine],
        operation_name: Optional[str] = None
    ) -> ParallelExecutionResult:
        """
        Execute multiple coroutines in parallel with error handling.

        Unlike asyncio.gather, this doesn't cancel other tasks if one fails.

        Args:
            coroutines: List of coroutines to execute
            operation_name: Name for metrics tracking

        Returns:
            ParallelExecutionResult with aggregated results
        """
        start_time = datetime.now()

        # Execute all coroutines
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # Separate successes and errors
        successes = []
        errors = []

        for result in results:
            if isinstance(result, Exception):
                errors.append(result)
                logger.error(f"Coroutine failed: {result}")
            else:
                successes.append(result)

        execution_time = (datetime.now() - start_time).total_seconds()

        # Update metrics
        if self.enable_metrics:
            self._total_executions += len(coroutines)
            self._total_successes += len(successes)
            self._total_errors += len(errors)
            self._total_execution_time += execution_time

            if operation_name:
                self._execution_times_by_operation[operation_name].append(
                    execution_time
                )

        logger.info(
            f"Parallel execution completed: {len(successes)} successes, "
            f"{len(errors)} errors in {execution_time:.2f}s"
        )

        return ParallelExecutionResult(
            success_count=len(successes),
            error_count=len(errors),
            results=successes,
            errors=errors,
            execution_time_seconds=execution_time
        )

    async def process_with_priority(
        self,
        high_priority_tasks: List[Coroutine],
        low_priority_tasks: List[Coroutine]
    ) -> tuple[ParallelExecutionResult, ParallelExecutionResult]:
        """
        Process tasks with priority levels.

        High priority tasks execute first, then low priority tasks.

        Args:
            high_priority_tasks: List of high priority coroutines
            low_priority_tasks: List of low priority coroutines

        Returns:
            Tuple of (high_priority_results, low_priority_results)
        """
        # Execute high priority first
        high_results = await self.gather_with_error_handling(
            high_priority_tasks,
            operation_name="high_priority"
        )

        # Then execute low priority
        low_results = await self.gather_with_error_handling(
            low_priority_tasks,
            operation_name="low_priority"
        )

        return high_results, low_results

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics.

        Returns:
            Dictionary with performance statistics
        """
        avg_execution_time = (
            self._total_execution_time / self._total_executions
            if self._total_executions > 0
            else 0.0
        )

        success_rate = (
            self._total_successes / self._total_executions * 100
            if self._total_executions > 0
            else 0.0
        )

        operation_stats = {}
        for op_name, times in self._execution_times_by_operation.items():
            operation_stats[op_name] = {
                "count": len(times),
                "avg_time_seconds": sum(times) / len(times),
                "min_time_seconds": min(times),
                "max_time_seconds": max(times)
            }

        return {
            "total_executions": self._total_executions,
            "total_successes": self._total_successes,
            "total_errors": self._total_errors,
            "success_rate_percent": success_rate,
            "avg_execution_time_seconds": avg_execution_time,
            "total_execution_time_seconds": self._total_execution_time,
            "max_concurrent": self.max_concurrent,
            "operations": operation_stats
        }

    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self._total_executions = 0
        self._total_successes = 0
        self._total_errors = 0
        self._total_execution_time = 0.0
        self._execution_times_by_operation.clear()
        logger.info("Metrics reset")


class DataPipelineParallelProcessor:
    """
    Specialized parallel processor for data pipeline operations.

    Coordinates parallel processing of:
    - Market data reception (multiple symbols, timeframes)
    - Indicator calculations (multiple indicators per timeframe)
    - Signal generation (multiple strategies)
    - Risk validation (multiple concurrent checks)
    """

    def __init__(
        self,
        max_concurrent_candles: int = 50,
        max_concurrent_indicators: int = 20,
        max_concurrent_signals: int = 10
    ):
        """
        Initialize data pipeline parallel processor.

        Args:
            max_concurrent_candles: Max concurrent candle processing
            max_concurrent_indicators: Max concurrent indicator calculations
            max_concurrent_signals: Max concurrent signal evaluations
        """
        self.candle_processor = ParallelProcessor(
            max_concurrent=max_concurrent_candles,
            timeout_seconds=5.0
        )
        self.indicator_processor = ParallelProcessor(
            max_concurrent=max_concurrent_indicators,
            timeout_seconds=10.0
        )
        self.signal_processor = ParallelProcessor(
            max_concurrent=max_concurrent_signals,
            timeout_seconds=15.0
        )

        logger.info(
            "DataPipelineParallelProcessor initialized "
            f"(candles={max_concurrent_candles}, "
            f"indicators={max_concurrent_indicators}, "
            f"signals={max_concurrent_signals})"
        )

    async def process_candles_parallel(
        self,
        candles: List[Any],
        processor_func: Callable[[Any], Coroutine]
    ) -> ParallelExecutionResult:
        """Process multiple candles in parallel."""
        return await self.candle_processor.process_batch(
            candles,
            processor_func,
            operation_name="candle_processing"
        )

    async def calculate_indicators_parallel(
        self,
        indicator_tasks: List[Coroutine]
    ) -> ParallelExecutionResult:
        """Calculate multiple indicators in parallel."""
        return await self.indicator_processor.gather_with_error_handling(
            indicator_tasks,
            operation_name="indicator_calculation"
        )

    async def evaluate_signals_parallel(
        self,
        signal_tasks: List[Coroutine]
    ) -> ParallelExecutionResult:
        """Evaluate multiple signals in parallel."""
        return await self.signal_processor.gather_with_error_handling(
            signal_tasks,
            operation_name="signal_evaluation"
        )

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics from all processors."""
        return {
            "candle_processing": self.candle_processor.get_metrics(),
            "indicator_calculation": self.indicator_processor.get_metrics(),
            "signal_evaluation": self.signal_processor.get_metrics()
        }
