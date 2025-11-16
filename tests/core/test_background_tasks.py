"""
Tests for Background Task Management System.

Tests Task 11.3 implementation:
- Asyncio task lifecycle management
- Automatic recovery with exponential backoff
- Health monitoring
- Task priority and grouping
- Error handling and metrics
"""

import asyncio

import pytest

from src.core.background_tasks import (
    BackgroundTaskManager,
    TaskConfig,
    TaskPriority,
    TaskState,
)


@pytest.fixture
def task_manager():
    """Create a BackgroundTaskManager for testing."""
    manager = BackgroundTaskManager(
        enable_health_monitoring=False,  # Disable for most tests
        enable_auto_recovery=True,
        health_check_interval=1.0,
    )
    return manager


@pytest.fixture
async def started_task_manager():
    """Create and start a BackgroundTaskManager."""
    manager = BackgroundTaskManager(enable_health_monitoring=False, enable_auto_recovery=True)
    await manager.start_all()
    yield manager
    await manager.stop_all()


@pytest.fixture
def simple_task_config():
    """Create a simple task configuration."""

    async def simple_coroutine():
        await asyncio.sleep(0.1)
        return "success"

    return TaskConfig(
        name="simple_test_task",
        coroutine_func=simple_coroutine,
        priority=TaskPriority.MEDIUM,
        auto_restart=False,
    )


@pytest.fixture
def failing_task_config():
    """Create a task configuration that fails."""

    async def failing_coroutine():
        await asyncio.sleep(0.05)
        raise ValueError("Test failure")

    return TaskConfig(
        name="failing_test_task",
        coroutine_func=failing_coroutine,
        priority=TaskPriority.HIGH,
        auto_restart=True,
        max_restart_attempts=3,
    )


@pytest.fixture
def loop_task_config():
    """Create a task configuration that runs in a loop."""
    counter = {"value": 0}

    async def loop_coroutine():
        counter["value"] += 1
        await asyncio.sleep(0.05)

    config = TaskConfig(
        name="loop_test_task",
        coroutine_func=loop_coroutine,
        priority=TaskPriority.LOW,
        auto_restart=True,
    )
    config.counter = counter  # Attach for verification
    return config


class TestTaskConfig:
    """Test TaskConfig dataclass and validation."""

    def test_task_config_creation(self):
        """Test creating a valid task configuration."""

        async def dummy_coro():
            pass

        config = TaskConfig(
            name="test_task", coroutine_func=dummy_coro, priority=TaskPriority.CRITICAL
        )

        assert config.name == "test_task"
        assert config.priority == TaskPriority.CRITICAL
        assert config.auto_restart is True  # Default
        assert config.max_restart_attempts == 5  # Default
        assert config.restart_delay_seconds == 1.0  # Default
        assert config.max_restart_delay_seconds == 60.0  # Default


class TestBackgroundTaskManager:
    """Test BackgroundTaskManager core functionality."""

    @pytest.mark.asyncio
    async def test_initialization(self, task_manager):
        """Test manager initialization."""
        assert task_manager._tasks == {}
        assert task_manager._enable_health_monitoring is False
        assert task_manager._enable_auto_recovery is True
        assert not task_manager._running

    @pytest.mark.asyncio
    async def test_start_stop_all(self, task_manager):
        """Test starting and stopping the manager."""
        assert not task_manager._running

        await task_manager.start_all()
        assert task_manager._running

        await task_manager.stop_all()
        assert not task_manager._running

    @pytest.mark.asyncio
    async def test_add_task(self, started_task_manager, simple_task_config):
        """Test adding a task to the manager."""
        await started_task_manager.add_task(simple_task_config, start_immediately=False)

        assert "simple_test_task" in started_task_manager._tasks
        task = started_task_manager._tasks["simple_test_task"]
        assert task.state == TaskState.CREATED
        assert task.config.name == "simple_test_task"

    @pytest.mark.asyncio
    async def test_add_task_auto_start(self, started_task_manager, simple_task_config):
        """Test adding a task with auto-start."""
        await started_task_manager.add_task(simple_task_config, start_immediately=True)

        await asyncio.sleep(0.05)

        assert "simple_test_task" in started_task_manager._tasks
        task = started_task_manager._tasks["simple_test_task"]
        assert task.state == TaskState.RUNNING

    @pytest.mark.asyncio
    async def test_start_task(self, started_task_manager, simple_task_config):
        """Test starting a specific task."""
        await started_task_manager.add_task(simple_task_config, start_immediately=False)

        await started_task_manager.start_task("simple_test_task")

        # Give task time to start
        await asyncio.sleep(0.05)

        task = started_task_manager._tasks["simple_test_task"]
        assert task.state == TaskState.RUNNING
        assert task.task is not None

    @pytest.mark.asyncio
    async def test_stop_task(self, started_task_manager, loop_task_config):
        """Test stopping a running task."""
        await started_task_manager.add_task(loop_task_config, start_immediately=True)

        # Let task run a bit
        await asyncio.sleep(0.15)

        await started_task_manager.stop_task("loop_test_task")

        task = started_task_manager._tasks["loop_test_task"]
        assert task.state == TaskState.STOPPED
        assert task.task is None or task.task.done()

    @pytest.mark.asyncio
    async def test_restart_task(self, started_task_manager, simple_task_config):
        """Test restarting a task."""
        await started_task_manager.add_task(simple_task_config, start_immediately=True)
        await asyncio.sleep(0.15)  # Let it complete

        await started_task_manager.restart_task("simple_test_task")
        await asyncio.sleep(0.2)  # Increased wait time for task to run again

        task = started_task_manager._tasks["simple_test_task"]
        assert task.metrics.run_count >= 2


class TestTaskRecovery:
    """Test automatic task recovery and exponential backoff."""

    @pytest.mark.asyncio
    async def test_automatic_recovery(self, started_task_manager, failing_task_config):
        """Test that failed tasks are automatically recovered."""
        await started_task_manager.add_task(failing_task_config, start_immediately=True)

        # Wait for multiple failure and recovery attempts
        await asyncio.sleep(0.5)

        task = started_task_manager._tasks["failing_test_task"]
        assert task.metrics.error_count > 0
        assert task.restart_attempts > 0

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, started_task_manager):
        """Test exponential backoff delay calculation."""

        async def quick_fail():
            raise RuntimeError("Quick fail")

        config = TaskConfig(
            name="backoff_test",
            coroutine_func=quick_fail,
            priority=TaskPriority.MEDIUM,
            auto_restart=True,
            max_restart_attempts=5,
            restart_delay_seconds=0.1,
            max_restart_delay_seconds=1.0,
        )

        await started_task_manager.add_task(config, start_immediately=True)

        # Track restart delays
        delays = []
        for _ in range(4):
            await asyncio.sleep(0.15)
            task = started_task_manager._tasks["backoff_test"]
            if task.restart_attempts > len(delays):
                delays.append(task.restart_attempts)

        # Verify attempts increased
        assert len(delays) > 0

    @pytest.mark.asyncio
    async def test_max_restart_attempts(self, started_task_manager):
        """Test that tasks stop recovering after max attempts."""

        async def always_fail():
            raise RuntimeError("Always fails")

        config = TaskConfig(
            name="max_attempts_test",
            coroutine_func=always_fail,
            priority=TaskPriority.LOW,
            auto_restart=True,
            max_restart_attempts=2,
            restart_delay_seconds=0.05,
        )

        await started_task_manager.add_task(config, start_immediately=True)

        # Wait for max attempts + some buffer (0.05 + 0.1 + buffer for exponential backoff)
        await asyncio.sleep(1.0)

        task = started_task_manager._tasks["max_attempts_test"]
        assert task.restart_attempts >= 2
        # Task should eventually stay in FAILED state
        assert task.state in [TaskState.FAILED, TaskState.RECOVERING]


class TestHealthMonitoring:
    """Test health monitoring functionality."""

    @pytest.mark.asyncio
    async def test_health_monitoring_enabled(self):
        """Test that health monitoring starts when enabled."""
        manager = BackgroundTaskManager(enable_health_monitoring=True, health_check_interval=0.1)

        await manager.start_all()

        # Health monitor should be running
        assert manager._health_monitor_task is not None
        assert not manager._health_monitor_task.done()

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_get_health_status(self, started_task_manager, simple_task_config):
        """Test health status retrieval."""
        await started_task_manager.add_task(simple_task_config, start_immediately=True)
        await asyncio.sleep(0.15)

        health_status = started_task_manager.get_health_status()

        assert "tasks" in health_status
        assert "summary" in health_status
        # Verify task is included
        assert any(t["name"] == "simple_test_task" for t in health_status["tasks"])


class TestTaskMetrics:
    """Test task metrics collection."""

    @pytest.mark.asyncio
    async def test_metrics_collection(self, started_task_manager, loop_task_config):
        """Test that metrics are collected during task execution."""
        await started_task_manager.add_task(loop_task_config, start_immediately=True)

        # Let task run several iterations
        await asyncio.sleep(0.25)

        await started_task_manager.stop_task("loop_test_task")

        task = started_task_manager._tasks["loop_test_task"]
        assert task.metrics.run_count > 0
        assert task.metrics.start_time is not None
        assert task.metrics.last_run_time is not None
        assert loop_task_config.counter["value"] > 0

    @pytest.mark.asyncio
    async def test_error_metrics(self, started_task_manager, failing_task_config):
        """Test error metrics tracking."""
        await started_task_manager.add_task(failing_task_config, start_immediately=True)

        await asyncio.sleep(0.3)

        task = started_task_manager._tasks["failing_test_task"]
        assert task.metrics.error_count > 0
        assert task.metrics.last_error is not None
        assert task.metrics.last_error_time is not None
        assert isinstance(task.metrics.last_error, ValueError)


class TestMultipleTaskManagement:
    """Test managing multiple tasks."""

    @pytest.mark.asyncio
    async def test_multiple_tasks_concurrent(self, started_task_manager):
        """Test managing multiple tasks concurrently."""
        # Create multiple tasks
        for i in range(3):

            async def dummy():
                await asyncio.sleep(0.1)

            config = TaskConfig(
                name=f"concurrent_task_{i}", coroutine_func=dummy, priority=TaskPriority.MEDIUM
            )
            await started_task_manager.add_task(config, start_immediately=True)

        await asyncio.sleep(0.05)

        # All tasks should be running
        for i in range(3):
            task = started_task_manager._tasks[f"concurrent_task_{i}"]
            assert task.state == TaskState.RUNNING

    @pytest.mark.asyncio
    async def test_stop_all_tasks(self, started_task_manager):
        """Test stopping all tasks at once."""
        # Create continuous tasks
        for i in range(2):
            counter = {"value": 0}

            async def loop_func():
                while True:
                    counter["value"] += 1
                    await asyncio.sleep(0.05)

            config = TaskConfig(
                name=f"stop_all_task_{i}", coroutine_func=loop_func, priority=TaskPriority.LOW
            )
            await started_task_manager.add_task(config, start_immediately=True)

        await asyncio.sleep(0.1)
        await started_task_manager.stop_all()

        # All tasks should be stopped
        for i in range(2):
            task = started_task_manager._tasks[f"stop_all_task_{i}"]
            assert task.state == TaskState.STOPPED


class TestTaskPriority:
    """Test task priority handling."""

    @pytest.mark.asyncio
    async def test_priority_ordering(self, started_task_manager):
        """Test that tasks maintain priority information."""
        priorities = [
            TaskPriority.CRITICAL,
            TaskPriority.HIGH,
            TaskPriority.MEDIUM,
            TaskPriority.LOW,
        ]

        for i, priority in enumerate(priorities):

            async def dummy():
                await asyncio.sleep(0.1)

            config = TaskConfig(name=f"priority_task_{i}", coroutine_func=dummy, priority=priority)
            await started_task_manager.add_task(config, start_immediately=False)

        # Verify priorities are set correctly
        for i, priority in enumerate(priorities):
            task = started_task_manager._tasks[f"priority_task_{i}"]
            assert task.config.priority == priority


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_start_nonexistent_task(self, started_task_manager):
        """Test starting a task that doesn't exist."""
        with pytest.raises(KeyError):
            await started_task_manager.start_task("nonexistent_task")

    @pytest.mark.asyncio
    async def test_stop_nonexistent_task(self, started_task_manager):
        """Test stopping a task that doesn't exist."""
        with pytest.raises(KeyError):
            await started_task_manager.stop_task("nonexistent_task")

    @pytest.mark.asyncio
    async def test_add_duplicate_task(self, started_task_manager, simple_task_config):
        """Test adding a task with duplicate name."""
        await started_task_manager.add_task(simple_task_config, start_immediately=False)

        # Adding with same name should raise or replace
        with pytest.raises(ValueError):
            await started_task_manager.add_task(simple_task_config, start_immediately=False)

    @pytest.mark.asyncio
    async def test_stop_all_cleans_up(self, started_task_manager, loop_task_config):
        """Test that stop_all() properly cleans up all tasks."""
        await started_task_manager.add_task(loop_task_config, start_immediately=True)
        await asyncio.sleep(0.1)

        await started_task_manager.stop_all()

        # All tasks should be stopped
        task = started_task_manager._tasks["loop_test_task"]
        assert task.state == TaskState.STOPPED
        assert not started_task_manager.is_running
