"""
Background Task and Parallel Processing System.

This module provides a comprehensive task management system for asyncio-based
background tasks with features including:
- Task lifecycle management (start, stop, restart)
- Health monitoring and automatic recovery
- Exponential backoff retry logic
- Parallel task coordination
- Resource usage tracking

Task 11.3 implementation.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional, Set

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """State of a background task."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    RECOVERING = "recovering"


class TaskPriority(Enum):
    """Priority levels for background tasks."""

    CRITICAL = 1  # Must always run (e.g., health checks)
    HIGH = 2  # Important business logic (e.g., data processing)
    MEDIUM = 3  # Standard operations (e.g., metrics collection)
    LOW = 4  # Nice-to-have (e.g., cleanup tasks)


@dataclass
class TaskMetrics:
    """Metrics for a background task."""

    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    last_error: Optional[Exception] = None
    last_error_time: Optional[datetime] = None
    total_runtime_seconds: float = 0.0
    avg_iteration_time_seconds: float = 0.0

    def record_run(self, duration_seconds: float) -> None:
        """Record a successful task iteration."""
        self.last_run_time = datetime.now()
        self.run_count += 1
        self.total_runtime_seconds += duration_seconds
        self.avg_iteration_time_seconds = self.total_runtime_seconds / self.run_count

    def record_error(self, error: Exception) -> None:
        """Record a task error."""
        self.error_count += 1
        self.last_error = error
        self.last_error_time = datetime.now()

    def get_uptime_seconds(self) -> Optional[float]:
        """Get total uptime in seconds."""
        if not self.start_time:
            return None
        end_time = self.stop_time or datetime.now()
        return (end_time - self.start_time).total_seconds()


@dataclass
class TaskConfig:
    """Configuration for a background task."""

    name: str
    coroutine_func: Callable[[], Coroutine]
    priority: TaskPriority = TaskPriority.MEDIUM
    auto_restart: bool = True
    max_restart_attempts: int = 5
    restart_delay_seconds: float = 1.0
    max_restart_delay_seconds: float = 60.0
    health_check_interval_seconds: float = 30.0
    timeout_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ManagedTask:
    """A managed background task with state and metrics."""

    config: TaskConfig
    task: Optional[asyncio.Task] = None
    state: TaskState = TaskState.CREATED
    metrics: TaskMetrics = field(default_factory=TaskMetrics)
    restart_attempts: int = 0
    current_restart_delay: float = 0.0

    def is_running(self) -> bool:
        """Check if task is currently running."""
        return self.state == TaskState.RUNNING and self.task is not None and not self.task.done()

    def is_healthy(self) -> bool:
        """Check if task is in a healthy state."""
        return self.state in [TaskState.RUNNING, TaskState.PAUSED]

    def needs_recovery(self) -> bool:
        """Check if task needs recovery."""
        return self.state in [TaskState.FAILED, TaskState.RECOVERING]

    def calculate_next_restart_delay(self) -> float:
        """Calculate next restart delay using exponential backoff."""
        if self.current_restart_delay == 0.0:
            self.current_restart_delay = self.config.restart_delay_seconds
        else:
            self.current_restart_delay = min(
                self.current_restart_delay * 2, self.config.max_restart_delay_seconds
            )
        return self.current_restart_delay

    def reset_restart_delay(self) -> None:
        """Reset restart delay after successful run."""
        self.current_restart_delay = 0.0
        self.restart_attempts = 0


class BackgroundTaskManager:
    """
    Comprehensive background task management system.

    Features:
    - Asyncio task lifecycle management
    - Automatic recovery with exponential backoff
    - Health monitoring and reporting
    - Parallel task coordination
    - Resource usage tracking
    - Priority-based task scheduling

    Usage:
        manager = BackgroundTaskManager()

        # Add tasks
        await manager.add_task(TaskConfig(
            name="data_processor",
            coroutine_func=process_data,
            priority=TaskPriority.HIGH
        ))

        # Start all tasks
        await manager.start_all()

        # Monitor health
        health = manager.get_health_status()

        # Stop all tasks
        await manager.stop_all()
    """

    def __init__(
        self,
        enable_health_monitoring: bool = True,
        health_check_interval: float = 30.0,
        enable_auto_recovery: bool = True,
    ):
        """
        Initialize background task manager.

        Args:
            enable_health_monitoring: Enable periodic health checks
            health_check_interval: Health check interval in seconds
            enable_auto_recovery: Enable automatic task recovery
        """
        self._tasks: Dict[str, ManagedTask] = {}
        self._task_groups: Dict[str, Set[str]] = defaultdict(set)

        # Manager state
        self._running = False
        self._health_monitor_task: Optional[asyncio.Task] = None
        self._recovery_tasks: Dict[str, asyncio.Task] = {}

        # Configuration
        self._enable_health_monitoring = enable_health_monitoring
        self._health_check_interval = health_check_interval
        self._enable_auto_recovery = enable_auto_recovery

        logger.info(
            "BackgroundTaskManager initialized "
            f"(health_monitoring={enable_health_monitoring}, "
            f"auto_recovery={enable_auto_recovery})"
        )

    @property
    def is_running(self) -> bool:
        """Check if task manager is running."""
        return self._running

    async def add_task(
        self, config: TaskConfig, group: Optional[str] = None, start_immediately: bool = False
    ) -> None:
        """
        Add a new background task.

        Args:
            config: Task configuration
            group: Optional group name for task organization
            start_immediately: Start task immediately after adding

        Raises:
            ValueError: If task with same name already exists
        """
        if config.name in self._tasks:
            raise ValueError(f"Task '{config.name}' already exists")

        managed_task = ManagedTask(config=config)
        self._tasks[config.name] = managed_task

        if group:
            self._task_groups[group].add(config.name)

        logger.info(
            f"Added task '{config.name}' " f"(priority={config.priority.name}, group={group})"
        )

        if start_immediately:
            await self.start_task(config.name)

    async def start_task(self, task_name: str) -> None:
        """
        Start a specific task.

        Args:
            task_name: Name of task to start

        Raises:
            KeyError: If task not found
            RuntimeError: If task is already running
        """
        managed_task = self._get_task(task_name)

        if managed_task.is_running():
            raise RuntimeError(f"Task '{task_name}' is already running")

        # Create and start task
        managed_task.task = asyncio.create_task(self._run_task_with_monitoring(managed_task))
        managed_task.state = TaskState.RUNNING
        managed_task.metrics.start_time = datetime.now()

        logger.info(f"Started task '{task_name}'")

    async def stop_task(self, task_name: str, timeout: Optional[float] = 5.0) -> None:
        """
        Stop a specific task.

        Args:
            task_name: Name of task to stop
            timeout: Maximum time to wait for graceful shutdown

        Raises:
            KeyError: If task not found
        """
        managed_task = self._get_task(task_name)

        if not managed_task.task:
            logger.warning(f"Task '{task_name}' has no running task")
            return

        # Cancel task
        managed_task.task.cancel()

        try:
            await asyncio.wait_for(managed_task.task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Task '{task_name}' did not stop within {timeout}s timeout")
        except asyncio.CancelledError:
            pass

        managed_task.state = TaskState.STOPPED
        managed_task.metrics.stop_time = datetime.now()

        logger.info(f"Stopped task '{task_name}'")

    async def restart_task(self, task_name: str) -> None:
        """
        Restart a specific task.

        Args:
            task_name: Name of task to restart
        """
        managed_task = self._get_task(task_name)

        logger.info(f"Restarting task '{task_name}'...")

        if managed_task.is_running():
            await self.stop_task(task_name)

        await self.start_task(task_name)

        # Note: restart counters are reset on successful task completion, not on restart

    async def start_all(self, group: Optional[str] = None) -> None:
        """
        Start all tasks or tasks in a specific group.

        Args:
            group: Optional group name to start
        """
        task_names = self._task_groups[group] if group else self._tasks.keys()

        for task_name in task_names:
            managed_task = self._tasks[task_name]
            if not managed_task.is_running():
                await self.start_task(task_name)

        self._running = True

        # Start health monitoring
        if self._enable_health_monitoring and not self._health_monitor_task:
            self._health_monitor_task = asyncio.create_task(self._health_monitor_loop())

        logger.info(f"Started {len(task_names)} tasks" + (f" in group '{group}'" if group else ""))

    async def stop_all(self, group: Optional[str] = None, timeout: Optional[float] = 10.0) -> None:
        """
        Stop all tasks or tasks in a specific group.

        Args:
            group: Optional group name to stop
            timeout: Maximum time to wait for each task
        """
        task_names = self._task_groups[group] if group else self._tasks.keys()

        # Stop tasks
        for task_name in task_names:
            try:
                await self.stop_task(task_name, timeout=timeout)
            except Exception as e:
                logger.error(f"Error stopping task '{task_name}': {e}")

        # Stop health monitoring if no tasks running
        if not group and self._health_monitor_task:
            self._health_monitor_task.cancel()
            try:
                await self._health_monitor_task
            except asyncio.CancelledError:
                pass
            self._health_monitor_task = None

        self._running = False

        logger.info(f"Stopped {len(task_names)} tasks" + (f" in group '{group}'" if group else ""))

    async def _run_task_with_monitoring(self, managed_task: ManagedTask) -> None:
        """
        Run task with monitoring and error handling.

        Args:
            managed_task: Managed task to run
        """
        task_name = managed_task.config.name

        try:
            # Apply timeout if configured
            if managed_task.config.timeout_seconds:
                iteration_start = datetime.now()
                await asyncio.wait_for(
                    managed_task.config.coroutine_func(),
                    timeout=managed_task.config.timeout_seconds,
                )
                iteration_duration = (datetime.now() - iteration_start).total_seconds()
                managed_task.metrics.record_run(iteration_duration)
                # Reset restart counters on successful completion
                managed_task.reset_restart_delay()
            else:
                iteration_start = datetime.now()
                await managed_task.config.coroutine_func()
                iteration_duration = (datetime.now() - iteration_start).total_seconds()
                managed_task.metrics.record_run(iteration_duration)
                # Reset restart counters on successful completion
                managed_task.reset_restart_delay()

            logger.debug(
                f"Task '{task_name}' completed iteration " f"(duration={iteration_duration:.2f}s)"
            )

        except asyncio.CancelledError:
            logger.info(f"Task '{task_name}' cancelled")
            raise

        except asyncio.TimeoutError:
            logger.error(
                f"Task '{task_name}' timed out after " f"{managed_task.config.timeout_seconds}s"
            )
            managed_task.metrics.record_error(
                TimeoutError(f"Task timeout after {managed_task.config.timeout_seconds}s")
            )
            managed_task.state = TaskState.FAILED

            # Trigger recovery if enabled
            if self._enable_auto_recovery and managed_task.config.auto_restart:
                await self._schedule_recovery(managed_task)

        except Exception as e:
            logger.error(f"Task '{task_name}' failed: {e}", exc_info=True)
            managed_task.metrics.record_error(e)
            managed_task.state = TaskState.FAILED

            # Trigger recovery if enabled
            if self._enable_auto_recovery and managed_task.config.auto_restart:
                await self._schedule_recovery(managed_task)

    async def _schedule_recovery(self, managed_task: ManagedTask) -> None:
        """
        Schedule task recovery with exponential backoff.

        Args:
            managed_task: Task to recover
        """
        task_name = managed_task.config.name

        # Check if max restart attempts reached
        if managed_task.restart_attempts >= managed_task.config.max_restart_attempts:
            logger.error(
                f"Task '{task_name}' reached max restart attempts "
                f"({managed_task.config.max_restart_attempts})"
            )
            return

        managed_task.state = TaskState.RECOVERING
        managed_task.restart_attempts += 1

        # Calculate delay with exponential backoff
        delay = managed_task.calculate_next_restart_delay()

        logger.info(
            f"Scheduling recovery for task '{task_name}' "
            f"(attempt {managed_task.restart_attempts}/"
            f"{managed_task.config.max_restart_attempts}, "
            f"delay={delay:.1f}s)"
        )

        # Create recovery task
        recovery_task = asyncio.create_task(self._recover_task(managed_task, delay))
        self._recovery_tasks[task_name] = recovery_task

    async def _recover_task(self, managed_task: ManagedTask, delay: float) -> None:
        """
        Recover a failed task after delay.

        Args:
            managed_task: Task to recover
            delay: Delay before recovery in seconds
        """
        task_name = managed_task.config.name

        try:
            await asyncio.sleep(delay)

            logger.info(f"Attempting to recover task '{task_name}'...")
            await self.restart_task(task_name)

            logger.info(f"Successfully recovered task '{task_name}'")

        except Exception as e:
            logger.error(f"Failed to recover task '{task_name}': {e}")
            managed_task.state = TaskState.FAILED

        finally:
            # Clean up recovery task
            if task_name in self._recovery_tasks:
                del self._recovery_tasks[task_name]

    async def _health_monitor_loop(self) -> None:
        """Background loop for health monitoring."""
        logger.info("Health monitor started")

        try:
            while self._running:
                await asyncio.sleep(self._health_check_interval)
                await self._perform_health_checks()

        except asyncio.CancelledError:
            logger.info("Health monitor cancelled")

        except Exception as e:
            logger.error(f"Health monitor error: {e}", exc_info=True)

    async def _perform_health_checks(self) -> None:
        """Perform health checks on all tasks."""
        for task_name, managed_task in self._tasks.items():
            if not managed_task.is_healthy():
                logger.warning(
                    f"Unhealthy task detected: '{task_name}' " f"(state={managed_task.state.value})"
                )

                # Attempt recovery if not already recovering
                if (
                    self._enable_auto_recovery
                    and managed_task.config.auto_restart
                    and not managed_task.state == TaskState.RECOVERING
                    and task_name not in self._recovery_tasks
                ):
                    await self._schedule_recovery(managed_task)

    def _get_task(self, task_name: str) -> ManagedTask:
        """Get managed task by name."""
        if task_name not in self._tasks:
            raise KeyError(f"Task '{task_name}' not found")
        return self._tasks[task_name]

    def get_task_status(self, task_name: str) -> Dict[str, Any]:
        """
        Get status of a specific task.

        Args:
            task_name: Name of task

        Returns:
            Dictionary with task status information
        """
        managed_task = self._get_task(task_name)

        return {
            "name": task_name,
            "state": managed_task.state.value,
            "priority": managed_task.config.priority.name,
            "is_running": managed_task.is_running(),
            "is_healthy": managed_task.is_healthy(),
            "restart_attempts": managed_task.restart_attempts,
            "max_restart_attempts": managed_task.config.max_restart_attempts,
            "metrics": {
                "run_count": managed_task.metrics.run_count,
                "error_count": managed_task.metrics.error_count,
                "uptime_seconds": managed_task.metrics.get_uptime_seconds(),
                "avg_iteration_time": managed_task.metrics.avg_iteration_time_seconds,
                "last_run_time": (
                    managed_task.metrics.last_run_time.isoformat()
                    if managed_task.metrics.last_run_time
                    else None
                ),
                "last_error": (
                    str(managed_task.metrics.last_error)
                    if managed_task.metrics.last_error
                    else None
                ),
                "last_error_time": (
                    managed_task.metrics.last_error_time.isoformat()
                    if managed_task.metrics.last_error_time
                    else None
                ),
            },
            "metadata": managed_task.config.metadata,
        }

    def get_all_status(self) -> Dict[str, Any]:
        """
        Get status of all tasks.

        Returns:
            Dictionary with comprehensive status information
        """
        return {
            "manager_running": self._running,
            "total_tasks": len(self._tasks),
            "running_tasks": sum(1 for t in self._tasks.values() if t.is_running()),
            "healthy_tasks": sum(1 for t in self._tasks.values() if t.is_healthy()),
            "failed_tasks": sum(1 for t in self._tasks.values() if t.state == TaskState.FAILED),
            "recovering_tasks": sum(
                1 for t in self._tasks.values() if t.state == TaskState.RECOVERING
            ),
            "tasks": {name: self.get_task_status(name) for name in self._tasks.keys()},
            "groups": {group: list(task_names) for group, task_names in self._task_groups.items()},
        }

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get overall health status.

        Returns:
            Health status dictionary with 'tasks' and 'summary' fields
        """
        all_healthy = all(task.is_healthy() for task in self._tasks.values())

        failed_tasks = [
            name for name, task in self._tasks.items() if task.state == TaskState.FAILED
        ]

        recovering_tasks = [
            name for name, task in self._tasks.items() if task.state == TaskState.RECOVERING
        ]

        # Build task list with details
        tasks_list = []
        for name, task in self._tasks.items():
            tasks_list.append(
                {
                    "name": name,
                    "state": task.state.value,
                    "healthy": task.is_healthy(),
                    "priority": task.config.priority.value,
                    "restart_attempts": task.restart_attempts,
                    "run_count": task.metrics.run_count,
                    "error_count": task.metrics.error_count,
                }
            )

        return {
            "tasks": tasks_list,
            "summary": {
                "healthy": all_healthy and self._running,
                "manager_running": self._running,
                "total_tasks": len(self._tasks),
                "healthy_tasks": sum(1 for t in self._tasks.values() if t.is_healthy()),
                "failed_tasks": failed_tasks,
                "recovering_tasks": recovering_tasks,
                "health_monitoring_enabled": self._enable_health_monitoring,
                "auto_recovery_enabled": self._enable_auto_recovery,
            },
        }
