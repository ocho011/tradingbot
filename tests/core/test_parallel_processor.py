"""
Tests for Parallel Processing Coordination System.

Tests Task 11.3 implementation:
- Concurrent execution with semaphore control
- Error isolation
- Result aggregation
- Performance metrics
- Priority-based execution
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from src.core.parallel_processor import (
    ParallelProcessor,
    ParallelExecutionResult,
    DataPipelineParallelProcessor
)


@pytest.fixture
def parallel_processor():
    """Create a ParallelProcessor for testing."""
    return ParallelProcessor(
        max_concurrent=5,
        timeout_seconds=2.0,
        enable_metrics=True
    )


@pytest.fixture
def data_pipeline_processor():
    """Create a DataPipelineParallelProcessor for testing."""
    return DataPipelineParallelProcessor(
        max_concurrent_candles=10,
        max_concurrent_indicators=5,
        max_concurrent_signals=3
    )


class TestParallelProcessor:
    """Test ParallelProcessor core functionality."""

    def test_initialization(self, parallel_processor):
        """Test processor initialization."""
        assert parallel_processor.max_concurrent == 5
        assert parallel_processor.timeout_seconds == 2.0
        assert parallel_processor.enable_metrics is True
        assert parallel_processor._total_executions == 0
        assert parallel_processor._total_successes == 0
        assert parallel_processor._total_errors == 0

    @pytest.mark.asyncio
    async def test_process_batch_success(self, parallel_processor):
        """Test successful batch processing."""
        items = list(range(10))

        async def process_item(item):
            await asyncio.sleep(0.01)
            return item * 2

        result = await parallel_processor.process_batch(
            items,
            process_item,
            operation_name="test_operation"
        )

        assert result.success_count == 10
        assert result.error_count == 0
        assert len(result.results) == 10
        assert len(result.errors) == 0
        assert set(result.results) == {i * 2 for i in range(10)}
        assert result.execution_time_seconds > 0

    @pytest.mark.asyncio
    async def test_process_batch_with_errors(self, parallel_processor):
        """Test batch processing with some errors."""
        items = list(range(10))

        async def process_item(item):
            await asyncio.sleep(0.01)
            if item % 3 == 0:
                raise ValueError(f"Error for item {item}")
            return item * 2

        result = await parallel_processor.process_batch(
            items,
            process_item,
            operation_name="test_with_errors"
        )

        # Items 0, 3, 6, 9 should fail (4 errors)
        assert result.error_count == 4
        assert result.success_count == 6
        assert len(result.errors) == 4
        assert len(result.results) == 6

        # Verify all errors are ValueError
        for error in result.errors:
            assert isinstance(error, ValueError)

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, parallel_processor):
        """Test that concurrency limit is enforced."""
        concurrent_count = {"current": 0, "max": 0}

        async def track_concurrency(item):
            concurrent_count["current"] += 1
            concurrent_count["max"] = max(
                concurrent_count["max"],
                concurrent_count["current"]
            )
            await asyncio.sleep(0.05)
            concurrent_count["current"] -= 1
            return item

        items = list(range(20))
        await parallel_processor.process_batch(items, track_concurrency)

        # Max concurrent should not exceed semaphore limit
        assert concurrent_count["max"] <= parallel_processor.max_concurrent

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test timeout handling for slow operations."""
        processor = ParallelProcessor(
            max_concurrent=5,
            timeout_seconds=0.1
        )

        async def slow_operation(item):
            await asyncio.sleep(0.5)  # Exceeds timeout
            return item

        items = list(range(5))
        result = await processor.process_batch(items, slow_operation)

        # All operations should timeout
        assert result.error_count == 5
        assert result.success_count == 0

        # Verify all errors are TimeoutError
        for error in result.errors:
            assert isinstance(error, asyncio.TimeoutError)

    @pytest.mark.asyncio
    async def test_gather_with_error_handling(self, parallel_processor):
        """Test gather_with_error_handling method."""
        async def success_coro(value):
            await asyncio.sleep(0.01)
            return value

        async def fail_coro():
            await asyncio.sleep(0.01)
            raise RuntimeError("Test error")

        coroutines = [
            success_coro(1),
            success_coro(2),
            fail_coro(),
            success_coro(3),
            fail_coro()
        ]

        result = await parallel_processor.gather_with_error_handling(
            coroutines,
            operation_name="gather_test"
        )

        assert result.success_count == 3
        assert result.error_count == 2
        assert set(result.results) == {1, 2, 3}
        assert len(result.errors) == 2

    @pytest.mark.asyncio
    async def test_process_with_priority(self, parallel_processor):
        """Test priority-based processing."""
        execution_order = []

        async def track_execution(item):
            execution_order.append(item)
            await asyncio.sleep(0.01)
            return item

        high_priority = [track_execution(f"high_{i}") for i in range(3)]
        low_priority = [track_execution(f"low_{i}") for i in range(3)]

        high_result, low_result = await parallel_processor.process_with_priority(
            high_priority,
            low_priority
        )

        # High priority should complete first
        assert high_result.success_count == 3
        assert low_result.success_count == 3

        # Verify high priority executed before low priority
        high_items = [item for item in execution_order if item.startswith("high")]
        low_items = [item for item in execution_order if item.startswith("low")]

        # All high priority should be before low priority
        last_high_index = max(execution_order.index(item) for item in high_items)
        first_low_index = min(execution_order.index(item) for item in low_items)

        assert last_high_index < first_low_index


class TestMetrics:
    """Test metrics collection functionality."""

    @pytest.mark.asyncio
    async def test_metrics_enabled(self, parallel_processor):
        """Test that metrics are collected when enabled."""
        items = list(range(5))

        async def process(item):
            await asyncio.sleep(0.01)
            return item

        await parallel_processor.process_batch(
            items,
            process,
            operation_name="metrics_test"
        )

        metrics = parallel_processor.get_metrics()

        assert metrics["total_executions"] == 5
        assert metrics["total_successes"] == 5
        assert metrics["total_errors"] == 0
        assert metrics["success_rate_percent"] == 100.0
        assert metrics["avg_execution_time_seconds"] > 0
        assert "metrics_test" in metrics["operations"]

    @pytest.mark.asyncio
    async def test_metrics_disabled(self):
        """Test that metrics are not collected when disabled."""
        processor = ParallelProcessor(
            max_concurrent=5,
            enable_metrics=False
        )

        items = list(range(5))

        async def process(item):
            await asyncio.sleep(0.01)
            return item

        await processor.process_batch(items, process)

        metrics = processor.get_metrics()

        # Metrics should still be available but may not be detailed
        assert "total_executions" in metrics
        assert "total_successes" in metrics

    @pytest.mark.asyncio
    async def test_operation_specific_metrics(self, parallel_processor):
        """Test metrics tracking per operation."""
        items = list(range(3))

        async def process(item):
            await asyncio.sleep(0.01)
            return item

        # Execute same operation multiple times
        for _ in range(3):
            await parallel_processor.process_batch(
                items,
                process,
                operation_name="repeated_op"
            )

        metrics = parallel_processor.get_metrics()
        op_metrics = metrics["operations"]["repeated_op"]

        assert op_metrics["count"] == 3
        assert op_metrics["avg_time_seconds"] > 0
        assert op_metrics["min_time_seconds"] > 0
        assert op_metrics["max_time_seconds"] > 0

    @pytest.mark.asyncio
    async def test_reset_metrics(self, parallel_processor):
        """Test metrics reset functionality."""
        items = list(range(5))

        async def process(item):
            await asyncio.sleep(0.01)
            return item

        await parallel_processor.process_batch(items, process)

        # Reset metrics
        parallel_processor.reset_metrics()

        metrics = parallel_processor.get_metrics()
        assert metrics["total_executions"] == 0
        assert metrics["total_successes"] == 0
        assert metrics["total_errors"] == 0


class TestDataPipelineProcessor:
    """Test DataPipelineParallelProcessor functionality."""

    def test_initialization(self, data_pipeline_processor):
        """Test data pipeline processor initialization."""
        assert data_pipeline_processor.candle_processor.max_concurrent == 10
        assert data_pipeline_processor.indicator_processor.max_concurrent == 5
        assert data_pipeline_processor.signal_processor.max_concurrent == 3

    @pytest.mark.asyncio
    async def test_process_candles_parallel(self, data_pipeline_processor):
        """Test parallel candle processing."""
        candles = [{"id": i, "price": 100 + i} for i in range(15)]

        async def process_candle(candle):
            await asyncio.sleep(0.01)
            return {"id": candle["id"], "processed": True}

        result = await data_pipeline_processor.process_candles_parallel(
            candles,
            process_candle
        )

        assert result.success_count == 15
        assert result.error_count == 0
        assert len(result.results) == 15

    @pytest.mark.asyncio
    async def test_calculate_indicators_parallel(self, data_pipeline_processor):
        """Test parallel indicator calculation."""
        async def calculate_rsi():
            await asyncio.sleep(0.02)
            return {"indicator": "RSI", "value": 65.5}

        async def calculate_macd():
            await asyncio.sleep(0.02)
            return {"indicator": "MACD", "value": 1.2}

        async def calculate_bollinger():
            await asyncio.sleep(0.02)
            return {"indicator": "Bollinger", "upper": 105, "lower": 95}

        indicator_tasks = [
            calculate_rsi(),
            calculate_macd(),
            calculate_bollinger()
        ]

        result = await data_pipeline_processor.calculate_indicators_parallel(
            indicator_tasks
        )

        assert result.success_count == 3
        assert result.error_count == 0
        assert len(result.results) == 3

    @pytest.mark.asyncio
    async def test_evaluate_signals_parallel(self, data_pipeline_processor):
        """Test parallel signal evaluation."""
        async def evaluate_trend_signal():
            await asyncio.sleep(0.01)
            return {"signal": "trend", "action": "BUY"}

        async def evaluate_momentum_signal():
            await asyncio.sleep(0.01)
            return {"signal": "momentum", "action": "HOLD"}

        signal_tasks = [
            evaluate_trend_signal(),
            evaluate_momentum_signal()
        ]

        result = await data_pipeline_processor.evaluate_signals_parallel(
            signal_tasks
        )

        assert result.success_count == 2
        assert result.error_count == 0
        assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_get_all_metrics(self, data_pipeline_processor):
        """Test getting metrics from all processors."""
        # Run some operations
        candles = [{"id": i} for i in range(5)]

        async def process_candle(candle):
            await asyncio.sleep(0.01)
            return candle

        await data_pipeline_processor.process_candles_parallel(
            candles,
            process_candle
        )

        all_metrics = data_pipeline_processor.get_all_metrics()

        assert "candle_processing" in all_metrics
        assert "indicator_calculation" in all_metrics
        assert "signal_evaluation" in all_metrics

        # Candle processing should have metrics
        candle_metrics = all_metrics["candle_processing"]
        assert candle_metrics["total_executions"] == 5
        assert candle_metrics["total_successes"] == 5


class TestErrorIsolation:
    """Test that errors in one task don't affect others."""

    @pytest.mark.asyncio
    async def test_error_isolation_in_batch(self, parallel_processor):
        """Test that one failure doesn't stop other tasks."""
        items = list(range(10))
        success_count = {"value": 0}

        async def process_with_occasional_failure(item):
            await asyncio.sleep(0.01)
            if item == 5:
                raise RuntimeError("Simulated failure")
            success_count["value"] += 1
            return item * 2

        result = await parallel_processor.process_batch(
            items,
            process_with_occasional_failure
        )

        # 9 successful, 1 failure
        assert result.success_count == 9
        assert result.error_count == 1
        assert success_count["value"] == 9

    @pytest.mark.asyncio
    async def test_multiple_errors_isolated(self, parallel_processor):
        """Test multiple errors are isolated from each other."""
        items = list(range(20))

        async def process_with_random_failures(item):
            await asyncio.sleep(0.01)
            if item % 4 == 0:
                raise ValueError(f"Error at {item}")
            return item

        result = await parallel_processor.process_batch(
            items,
            process_with_random_failures
        )

        # Items 0, 4, 8, 12, 16 should fail (5 errors)
        assert result.error_count == 5
        assert result.success_count == 15


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_batch(self, parallel_processor):
        """Test processing empty batch."""
        async def process(item):
            return item

        result = await parallel_processor.process_batch([], process)

        assert result.success_count == 0
        assert result.error_count == 0
        assert len(result.results) == 0
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_single_item_batch(self, parallel_processor):
        """Test processing single item."""
        async def process(item):
            await asyncio.sleep(0.01)
            return item * 2

        result = await parallel_processor.process_batch([5], process)

        assert result.success_count == 1
        assert result.error_count == 0
        assert result.results == [10]

    @pytest.mark.asyncio
    async def test_all_operations_fail(self, parallel_processor):
        """Test when all operations fail."""
        items = list(range(5))

        async def always_fail(item):
            await asyncio.sleep(0.01)
            raise RuntimeError("Always fails")

        result = await parallel_processor.process_batch(items, always_fail)

        assert result.success_count == 0
        assert result.error_count == 5
        assert len(result.results) == 0
        assert len(result.errors) == 5

    @pytest.mark.asyncio
    async def test_none_timeout(self):
        """Test processor with no timeout."""
        processor = ParallelProcessor(
            max_concurrent=3,
            timeout_seconds=None
        )

        async def slow_operation(item):
            await asyncio.sleep(0.1)
            return item

        items = [1, 2, 3]
        result = await processor.process_batch(items, slow_operation)

        # Should succeed without timeout
        assert result.success_count == 3
        assert result.error_count == 0
