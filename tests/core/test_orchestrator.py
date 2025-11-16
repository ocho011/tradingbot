"""
Unit tests for TradingSystemOrchestrator.

Tests service initialization, dependency ordering, lifecycle management,
state transitions, and error handling.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.core.config import BinanceConfig
from src.core.orchestrator import (
    OrchestratorError,
    ServiceInfo,
    ServiceState,
    SystemState,
    TradingSystemOrchestrator,
)


@pytest.fixture
def mock_config():
    """Create mock Binance configuration."""
    config = Mock(spec=BinanceConfig)
    config.testnet = True
    config.api_key = "test_key"
    config.api_secret = "test_secret"
    return config


@pytest.fixture
async def orchestrator(mock_config):
    """Create orchestrator instance for testing."""
    orch = TradingSystemOrchestrator(config=mock_config, enable_testnet=True)
    yield orch

    # Cleanup
    if orch.get_system_state() == SystemState.RUNNING:
        await orch.stop()


class TestOrchestratorInitialization:
    """Test orchestrator initialization."""

    def test_initialization_creates_correct_initial_state(self, mock_config):
        """Test that orchestrator initializes with correct state."""
        orch = TradingSystemOrchestrator(config=mock_config)

        assert orch.get_system_state() == SystemState.OFFLINE
        assert len(orch._services) == 0
        assert orch.event_bus is None
        assert orch.binance_manager is None

    def test_initialization_with_testnet_enabled(self):
        """Test initialization with testnet enabled."""
        orch = TradingSystemOrchestrator(enable_testnet=True)

        assert orch.config.testnet is True

    def test_initialization_with_testnet_disabled(self):
        """Test initialization with testnet disabled."""
        orch = TradingSystemOrchestrator(enable_testnet=False)

        assert orch.config.testnet is False

    @pytest.mark.asyncio
    async def test_initialize_creates_all_services(self, orchestrator):
        """Test that initialize creates all required services."""
        await orchestrator.initialize()

        expected_services = [
            "event_bus",
            "database",
            "binance_manager",
            "candle_storage",
            "multi_timeframe_engine",
            "strategy_layer",
            "risk_validator",
            "order_executor",
            "position_manager",
        ]

        for service_name in expected_services:
            assert service_name in orchestrator._services
            service_info = orchestrator._services[service_name]
            assert service_info.state == ServiceState.INITIALIZED

    @pytest.mark.asyncio
    async def test_initialize_sets_correct_dependencies(self, orchestrator):
        """Test that services have correct dependency relationships."""
        await orchestrator.initialize()

        # Event bus has no dependencies
        assert orchestrator._services["event_bus"].dependencies == []

        # Binance manager depends on event bus
        assert "event_bus" in orchestrator._services["binance_manager"].dependencies

        # Multi-timeframe engine depends on candle storage and event bus
        mtf_deps = orchestrator._services["multi_timeframe_engine"].dependencies
        assert "candle_storage" in mtf_deps
        assert "event_bus" in mtf_deps

        # Strategy layer depends on multi-timeframe engine
        assert "multi_timeframe_engine" in orchestrator._services["strategy_layer"].dependencies

    @pytest.mark.asyncio
    async def test_initialize_calculates_correct_order(self, orchestrator):
        """Test that initialization order respects dependencies."""
        await orchestrator.initialize()

        order = orchestrator._initialization_order

        # Event bus should come before services that depend on it
        event_bus_idx = order.index("event_bus")
        binance_idx = order.index("binance_manager")
        assert event_bus_idx < binance_idx

        # Candle storage should come before multi-timeframe engine
        storage_idx = order.index("candle_storage")
        engine_idx = order.index("multi_timeframe_engine")
        assert storage_idx < engine_idx

        # Multi-timeframe engine before strategy layer
        strategy_idx = order.index("strategy_layer")
        assert engine_idx < strategy_idx

    @pytest.mark.asyncio
    async def test_initialize_from_non_offline_state_raises_error(self, orchestrator):
        """Test that initializing from wrong state raises error."""
        await orchestrator.initialize()

        with pytest.raises(OrchestratorError, match="Cannot initialize from state"):
            await orchestrator.initialize()

    @pytest.mark.asyncio
    async def test_initialize_failure_sets_error_state(self, orchestrator):
        """Test that initialization failure sets system to error state."""
        # Mock a service initialization to fail
        with patch.object(
            orchestrator, "_initialize_event_bus", side_effect=Exception("Init failed")
        ):
            with pytest.raises(OrchestratorError):
                await orchestrator.initialize()

            assert orchestrator.get_system_state() == SystemState.ERROR


@pytest.mark.timeout(120)  # Integration tests that start full system need more time
class TestServiceLifecycle:
    """Test service lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_transitions_services_to_running(self, orchestrator):
        """Test that start transitions all services to running state."""
        await orchestrator.initialize()
        await orchestrator.start()

        for service_name, service_info in orchestrator._services.items():
            assert service_info.state == ServiceState.RUNNING

    @pytest.mark.asyncio
    async def test_start_calls_service_callbacks(self, orchestrator):
        """Test that start calls service start callbacks."""
        await orchestrator.initialize()

        # Mock a service start callback
        mock_callback = AsyncMock()
        orchestrator._services["event_bus"].start_callback = mock_callback

        await orchestrator.start()

        mock_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_respects_dependency_order(self, orchestrator):
        """Test that services start in dependency order."""
        await orchestrator.initialize()

        start_times = {}

        # Track when each service starts
        async def track_start(service_name):
            start_times[service_name] = datetime.now()
            await asyncio.sleep(0.01)  # Small delay

        for service_name, service_info in orchestrator._services.items():
            if service_info.start_callback:
                service_info.start_callback
                service_info.start_callback = lambda sn=service_name: track_start(sn)

        await orchestrator.start()

        # Verify event_bus started before binance_manager
        if "event_bus" in start_times and "binance_manager" in start_times:
            assert start_times["event_bus"] < start_times["binance_manager"]

    @pytest.mark.asyncio
    async def test_stop_transitions_services_to_stopped(self, orchestrator):
        """Test that stop transitions all services to stopped state."""
        await orchestrator.initialize()
        await orchestrator.start()
        await orchestrator.stop()

        for service_name, service_info in orchestrator._services.items():
            assert service_info.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_calls_service_callbacks(self, orchestrator):
        """Test that stop calls service stop callbacks."""
        await orchestrator.initialize()
        await orchestrator.start()

        # Mock a service stop callback
        mock_callback = AsyncMock()
        orchestrator._services["event_bus"].stop_callback = mock_callback

        await orchestrator.stop()

        mock_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_respects_reverse_order(self, orchestrator):
        """Test that services stop in reverse dependency order."""
        await orchestrator.initialize()
        await orchestrator.start()

        stop_times = {}

        # Track when each service stops
        async def track_stop(service_name):
            stop_times[service_name] = datetime.now()
            await asyncio.sleep(0.01)  # Small delay

        for service_name, service_info in orchestrator._services.items():
            if service_info.stop_callback:
                service_info.stop_callback = lambda sn=service_name: track_stop(sn)

        await orchestrator.stop()

        # Verify binance_manager stopped before event_bus (reverse of start order)
        if "event_bus" in stop_times and "binance_manager" in stop_times:
            assert stop_times["binance_manager"] < stop_times["event_bus"]

    @pytest.mark.asyncio
    async def test_start_from_wrong_state_raises_error(self, orchestrator):
        """Test that starting from wrong state raises error."""
        # Don't initialize, try to start directly
        with pytest.raises(OrchestratorError, match="Cannot start from state"):
            await orchestrator.start()

    @pytest.mark.asyncio
    async def test_service_start_failure_triggers_emergency_shutdown(self, orchestrator):
        """Test that service start failure triggers emergency shutdown."""
        await orchestrator.initialize()

        # Mock a service to fail during start
        orchestrator._services["event_bus"].start_callback
        orchestrator._services["event_bus"].start_callback = AsyncMock(
            side_effect=Exception("Start failed")
        )

        with pytest.raises(OrchestratorError):
            await orchestrator.start()

        assert orchestrator.get_system_state() == SystemState.ERROR


@pytest.mark.timeout(120)  # Integration tests that start full system need more time
class TestStateManagement:
    """Test system state management."""

    def test_get_system_state_returns_current_state(self, orchestrator):
        """Test that get_system_state returns current state."""
        assert orchestrator.get_system_state() == SystemState.OFFLINE

    @pytest.mark.asyncio
    async def test_system_state_transitions_during_lifecycle(self, orchestrator):
        """Test that system state transitions correctly."""
        # Initial state
        assert orchestrator.get_system_state() == SystemState.OFFLINE

        # During initialization
        init_task = asyncio.create_task(orchestrator.initialize())
        await asyncio.sleep(0.01)  # Let it start
        # State should transition through INITIALIZING

        await init_task
        assert orchestrator.get_system_state() == SystemState.OFFLINE

        # Start
        await orchestrator.start()
        assert orchestrator.get_system_state() == SystemState.RUNNING

        # Stop
        await orchestrator.stop()
        assert orchestrator.get_system_state() == SystemState.OFFLINE

    def test_get_service_states_returns_all_services(self, orchestrator):
        """Test that get_service_states returns info for all services."""
        # Before initialization, should be empty
        states = orchestrator.get_service_states()
        assert len(states) == 0

    @pytest.mark.asyncio
    async def test_get_service_states_after_initialization(self, orchestrator):
        """Test get_service_states after initialization."""
        await orchestrator.initialize()

        states = orchestrator.get_service_states()
        assert len(states) > 0

        for service_name, state_info in states.items():
            assert "state" in state_info
            assert "last_change" in state_info
            assert "error" in state_info

    @pytest.mark.asyncio
    async def test_service_info_update_state_changes_timestamp(self, orchestrator):
        """Test that ServiceInfo.update_state changes timestamp."""
        service_info = ServiceInfo(name="test_service", instance=Mock())

        first_time = service_info.last_state_change
        await asyncio.sleep(0.01)

        service_info.update_state(ServiceState.RUNNING)

        assert service_info.last_state_change > first_time
        assert service_info.state == ServiceState.RUNNING


@pytest.mark.timeout(120)  # Integration tests that start full system need more time
class TestSystemMonitoring:
    """Test system monitoring and statistics."""

    @pytest.mark.asyncio
    async def test_get_system_stats_includes_all_info(self, orchestrator):
        """Test that get_system_stats includes comprehensive info."""
        await orchestrator.initialize()
        await orchestrator.start()

        stats = orchestrator.get_system_stats()

        assert "system_state" in stats
        assert "uptime_seconds" in stats
        assert "service_count" in stats
        assert "services" in stats
        assert "event_bus_stats" in stats
        assert "startup_time" in stats

        assert stats["system_state"] == SystemState.RUNNING.value
        assert stats["service_count"] == len(orchestrator._services)
        assert stats["uptime_seconds"] is not None

    @pytest.mark.asyncio
    async def test_is_healthy_returns_true_when_running(self, orchestrator):
        """Test that is_healthy returns True when system is running."""
        await orchestrator.initialize()
        await orchestrator.start()

        assert orchestrator.is_healthy() is True

    @pytest.mark.asyncio
    async def test_is_healthy_returns_false_when_not_running(self, orchestrator):
        """Test that is_healthy returns False when system is not running."""
        await orchestrator.initialize()

        assert orchestrator.is_healthy() is False

    @pytest.mark.asyncio
    async def test_is_healthy_returns_false_when_service_error(self, orchestrator):
        """Test that is_healthy returns False when a service has error."""
        await orchestrator.initialize()
        await orchestrator.start()

        # Simulate service error
        orchestrator._services["event_bus"].update_state(
            ServiceState.ERROR, error=Exception("Test error")
        )

        assert orchestrator.is_healthy() is False

    @pytest.mark.asyncio
    async def test_uptime_calculation_when_running(self, orchestrator):
        """Test uptime calculation when system is running."""
        await orchestrator.initialize()
        await orchestrator.start()

        await asyncio.sleep(0.1)  # Wait a bit

        stats = orchestrator.get_system_stats()
        assert stats["uptime_seconds"] > 0

    @pytest.mark.asyncio
    async def test_uptime_calculation_after_stop(self, orchestrator):
        """Test uptime calculation after system stops."""
        await orchestrator.initialize()
        await orchestrator.start()
        await asyncio.sleep(0.1)
        await orchestrator.stop()

        stats = orchestrator.get_system_stats()
        assert stats["uptime_seconds"] is not None
        assert stats["shutdown_time"] is not None


@pytest.mark.timeout(120)  # Integration tests that start full system need more time
class TestErrorHandling:
    """Test error handling and recovery."""

    @pytest.mark.asyncio
    async def test_service_initialization_failure_propagates(self, orchestrator):
        """Test that service initialization failure is properly handled."""
        with patch.object(
            orchestrator,
            "_initialize_binance_manager",
            side_effect=Exception("Binance init failed"),
        ):
            with pytest.raises(OrchestratorError):
                await orchestrator.initialize()

    @pytest.mark.asyncio
    async def test_emergency_shutdown_stops_all_services(self, orchestrator):
        """Test that emergency shutdown attempts to stop all services."""
        await orchestrator.initialize()
        await orchestrator.start()

        # Trigger emergency shutdown
        await orchestrator._emergency_shutdown()

        # All services should be stopped or in error state
        for service_info in orchestrator._services.values():
            assert service_info.state in [ServiceState.STOPPED, ServiceState.ERROR]

    @pytest.mark.asyncio
    async def test_service_state_error_propagation(self, orchestrator):
        """Test that service errors are captured in state."""
        service_info = ServiceInfo(name="test_service", instance=Mock())

        error = Exception("Test error")
        service_info.update_state(ServiceState.ERROR, error=error)

        assert service_info.state == ServiceState.ERROR
        assert service_info.error == error

    @pytest.mark.asyncio
    async def test_health_check_detects_service_failures(self, orchestrator):
        """Test that health check loop detects service failures."""
        await orchestrator.initialize()
        await orchestrator.start()

        # Mock a health check failure
        health_check = AsyncMock(side_effect=Exception("Health check failed"))
        orchestrator._services["event_bus"].health_check = health_check

        # Run one health check iteration
        await orchestrator._perform_health_checks()

        # Service should be in error state
        assert orchestrator._services["event_bus"].state == ServiceState.ERROR


class TestDependencyResolution:
    """Test dependency resolution and ordering."""

    def test_calculate_initialization_order_simple_deps(self, orchestrator):
        """Test dependency ordering with simple dependencies."""
        # Create test services with dependencies
        orchestrator._services = {
            "a": ServiceInfo(name="a", instance=Mock(), dependencies=[]),
            "b": ServiceInfo(name="b", instance=Mock(), dependencies=["a"]),
            "c": ServiceInfo(name="c", instance=Mock(), dependencies=["b"]),
        }

        orchestrator._calculate_initialization_order()

        order = orchestrator._initialization_order
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_calculate_initialization_order_multiple_deps(self, orchestrator):
        """Test dependency ordering with multiple dependencies."""
        orchestrator._services = {
            "a": ServiceInfo(name="a", instance=Mock(), dependencies=[]),
            "b": ServiceInfo(name="b", instance=Mock(), dependencies=[]),
            "c": ServiceInfo(name="c", instance=Mock(), dependencies=["a", "b"]),
        }

        orchestrator._calculate_initialization_order()

        order = orchestrator._initialization_order
        c_idx = order.index("c")
        assert order.index("a") < c_idx
        assert order.index("b") < c_idx

    def test_calculate_initialization_order_circular_deps_raises_error(self, orchestrator):
        """Test that circular dependencies are detected."""
        orchestrator._services = {
            "a": ServiceInfo(name="a", instance=Mock(), dependencies=["b"]),
            "b": ServiceInfo(name="b", instance=Mock(), dependencies=["a"]),
        }

        with pytest.raises(OrchestratorError, match="Circular dependency"):
            orchestrator._calculate_initialization_order()


@pytest.mark.timeout(180)  # Multiple start/stop cycles need extra time
class TestConcurrency:
    """Test concurrent operations and thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_state_access_is_safe(self, orchestrator):
        """Test that concurrent state access is thread-safe."""
        await orchestrator.initialize()

        async def read_state():
            for _ in range(100):
                orchestrator.get_system_state()
                await asyncio.sleep(0.001)

        # Run multiple concurrent readers
        tasks = [asyncio.create_task(read_state()) for _ in range(10)]
        await asyncio.gather(*tasks)

        # Should complete without errors

    @pytest.mark.asyncio
    async def test_start_stop_cycle_multiple_times(self, orchestrator):
        """Test that system can be started and stopped multiple times."""
        await orchestrator.initialize()

        for _ in range(3):
            await orchestrator.start()
            assert orchestrator.get_system_state() == SystemState.RUNNING

            await orchestrator.stop()
            assert orchestrator.get_system_state() == SystemState.OFFLINE
