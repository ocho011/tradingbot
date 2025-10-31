"""
Trading System Orchestrator - Main service coordination and lifecycle management.

This module implements the core orchestration layer that manages all trading system
components, their dependencies, initialization sequences, and lifecycle coordination.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from threading import Lock

from src.core.events import EventBus, Event, EventHandler
from src.core.constants import EventType
from src.core.config import BinanceConfig
from src.services.exchange.binance_manager import BinanceManager
from src.services.candle_storage import CandleStorage
from src.indicators.multi_timeframe_engine import MultiTimeframeIndicatorEngine
from src.services.strategy.integration_layer import StrategyIntegrationLayer
from src.services.risk.risk_validator import RiskValidator
from src.services.risk.position_sizer import PositionSizer
from src.services.risk.stop_loss_calculator import StopLossCalculator
from src.services.risk.take_profit_calculator import TakeProfitCalculator
from src.services.risk.daily_loss_monitor import DailyLossMonitor
from src.services.exchange.order_executor import OrderExecutor
from src.services.position.position_manager import PositionManager
from src.database import engine as db_engine

logger = logging.getLogger(__name__)


class ServiceState(str, Enum):
    """Service lifecycle states."""

    UNINITIALIZED = "uninitialized"  # Service not yet initialized
    INITIALIZING = "initializing"     # Currently initializing
    INITIALIZED = "initialized"       # Initialized but not started
    STARTING = "starting"             # Currently starting
    RUNNING = "running"               # Fully operational
    STOPPING = "stopping"             # Currently stopping
    STOPPED = "stopped"               # Cleanly stopped
    ERROR = "error"                   # Error state


class SystemState(str, Enum):
    """Overall system states."""

    OFFLINE = "offline"               # System offline
    INITIALIZING = "initializing"     # Initializing services
    STARTING = "starting"             # Starting services
    RUNNING = "running"               # System operational
    STOPPING = "stopping"             # Stopping services
    ERROR = "error"                   # System error
    MAINTENANCE = "maintenance"       # Maintenance mode


@dataclass
class ServiceInfo:
    """
    Information about a managed service.

    Attributes:
        name: Service identifier name
        instance: Service instance object
        state: Current service state
        dependencies: List of service names this depends on
        start_callback: Optional async callback to start service
        stop_callback: Optional async callback to stop service
        health_check: Optional async callback for health checking
        error: Last error if in ERROR state
        last_state_change: Timestamp of last state transition
    """

    name: str
    instance: Any
    state: ServiceState = ServiceState.UNINITIALIZED
    dependencies: List[str] = field(default_factory=list)
    start_callback: Optional[Callable] = None
    stop_callback: Optional[Callable] = None
    health_check: Optional[Callable] = None
    error: Optional[Exception] = None
    last_state_change: datetime = field(default_factory=datetime.now)

    def update_state(self, new_state: ServiceState, error: Optional[Exception] = None) -> None:
        """Update service state and timestamp."""
        self.state = new_state
        self.error = error
        self.last_state_change = datetime.now()


class OrchestratorError(Exception):
    """Raised when orchestrator operations fail."""
    pass


class TradingSystemOrchestrator:
    """
    Main orchestrator for the trading system.

    Manages initialization, startup, shutdown, and lifecycle of all trading system
    components with proper dependency ordering and error handling.

    Features:
    - Dependency injection and service registry
    - Ordered service initialization based on dependencies
    - Graceful startup and shutdown sequences
    - State synchronization across components
    - Error propagation and recovery
    - Health monitoring and status reporting

    Architecture:
    - EventBus: Central event coordination
    - BinanceManager: Exchange connectivity
    - CandleStorage: Market data storage
    - MultiTimeframeEngine: Indicator calculations
    - StrategyIntegrationLayer: Signal generation
    - RiskValidator: Risk management
    - OrderExecutor: Order execution
    - PositionManager: Position tracking
    """

    def __init__(
        self,
        config: Optional[BinanceConfig] = None,
        enable_testnet: bool = True,
        max_event_queue_size: int = 10000
    ):
        """
        Initialize trading system orchestrator.

        Args:
            config: Binance configuration (uses default if None)
            enable_testnet: Whether to use testnet environment
            max_event_queue_size: Maximum event queue size
        """
        self.config = config or BinanceConfig()
        self.config.testnet = enable_testnet

        # System state
        self._state = SystemState.OFFLINE
        self._state_lock = Lock()
        self._startup_time: Optional[datetime] = None
        self._shutdown_time: Optional[datetime] = None

        # Service registry
        self._services: Dict[str, ServiceInfo] = {}
        self._initialization_order: List[str] = []

        # Core components (initialized in _initialize_services)
        self.event_bus: Optional[EventBus] = None
        self.db_engine = db_engine  # Module reference for database operations
        self.binance_manager: Optional[BinanceManager] = None
        self.candle_storage: Optional[CandleStorage] = None
        self.multi_timeframe_engine: Optional[MultiTimeframeIndicatorEngine] = None
        self.strategy_layer: Optional[StrategyIntegrationLayer] = None
        self.risk_validator: Optional[RiskValidator] = None
        self.order_executor: Optional[OrderExecutor] = None
        self.position_manager: Optional[PositionManager] = None

        # Background tasks
        self._background_tasks: List[asyncio.Task] = []
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval = 30  # seconds

        logger.info(
            f"TradingSystemOrchestrator initialized "
            f"(testnet={'enabled' if enable_testnet else 'disabled'})"
        )

    async def initialize(self) -> None:
        """
        Initialize all system components with dependency ordering.

        Creates and initializes all services in the correct dependency order:
        1. EventBus (no dependencies)
        2. Database (no dependencies)
        3. BinanceManager (depends on EventBus)
        4. CandleStorage (no dependencies)
        5. MultiTimeframeEngine (depends on CandleStorage, EventBus)
        6. StrategyIntegrationLayer (depends on MultiTimeframeEngine)
        7. Risk components (depends on Database)
        8. OrderExecutor (depends on BinanceManager, EventBus)
        9. PositionManager (depends on Database, EventBus)

        Raises:
            OrchestratorError: If initialization fails
        """
        with self._state_lock:
            if self._state != SystemState.OFFLINE:
                raise OrchestratorError(
                    f"Cannot initialize from state {self._state}"
                )
            # Check if services are already initialized
            if self._services:
                raise OrchestratorError(
                    f"Cannot initialize from state INITIALIZED"
                )
            self._state = SystemState.INITIALIZING

        try:
            logger.info("Initializing trading system components...")

            # Initialize services in dependency order
            await self._initialize_event_bus()
            await self._initialize_database()
            await self._initialize_binance_manager()
            await self._initialize_candle_storage()
            await self._initialize_multi_timeframe_engine()
            await self._initialize_strategy_layer()
            await self._initialize_risk_components()
            await self._initialize_order_executor()
            await self._initialize_position_manager()

            # Calculate initialization order based on dependencies
            self._calculate_initialization_order()

            with self._state_lock:
                self._state = SystemState.OFFLINE  # Initialized and ready to start

            logger.info(
                f"Successfully initialized {len(self._services)} services: "
                f"{list(self._services.keys())}"
            )

        except Exception as e:
            with self._state_lock:
                self._state = SystemState.ERROR
            logger.error(f"Initialization failed: {e}", exc_info=True)
            raise OrchestratorError(f"Initialization failed: {e}") from e

    async def _initialize_event_bus(self) -> None:
        """Initialize event bus (no dependencies)."""
        logger.info("Initializing EventBus...")
        self.event_bus = EventBus(max_queue_size=10000)

        self._services["event_bus"] = ServiceInfo(
            name="event_bus",
            instance=self.event_bus,
            state=ServiceState.INITIALIZED,
            dependencies=[],
            start_callback=self.event_bus.start,
            stop_callback=self.event_bus.stop
        )
        logger.info("EventBus initialized")

    async def _initialize_database(self) -> None:
        """Initialize database engine (no dependencies)."""
        logger.info("Initializing Database...")
        # Initialize database tables
        await db_engine.init_db()

        self._services["database"] = ServiceInfo(
            name="database",
            instance=db_engine,
            state=ServiceState.INITIALIZED,
            dependencies=[]
        )
        logger.info("Database initialized")

    async def _initialize_binance_manager(self) -> None:
        """Initialize Binance manager (depends on EventBus)."""
        logger.info("Initializing BinanceManager...")
        self.binance_manager = BinanceManager(
            config=self.config,
            event_bus=self.event_bus
        )
        await self.binance_manager.initialize()

        self._services["binance_manager"] = ServiceInfo(
            name="binance_manager",
            instance=self.binance_manager,
            state=ServiceState.INITIALIZED,
            dependencies=["event_bus"],
            start_callback=self._start_binance_manager,
            stop_callback=self._stop_binance_manager
        )
        logger.info("BinanceManager initialized")

    async def _initialize_candle_storage(self) -> None:
        """Initialize candle storage (no dependencies)."""
        logger.info("Initializing CandleStorage...")
        self.candle_storage = CandleStorage(max_candles=500)

        self._services["candle_storage"] = ServiceInfo(
            name="candle_storage",
            instance=self.candle_storage,
            state=ServiceState.INITIALIZED,
            dependencies=[]
        )
        logger.info("CandleStorage initialized")

    async def _initialize_multi_timeframe_engine(self) -> None:
        """Initialize multi-timeframe engine (depends on CandleStorage, EventBus)."""
        logger.info("Initializing MultiTimeframeIndicatorEngine...")
        self.multi_timeframe_engine = MultiTimeframeIndicatorEngine(
            event_bus=self.event_bus
        )

        self._services["multi_timeframe_engine"] = ServiceInfo(
            name="multi_timeframe_engine",
            instance=self.multi_timeframe_engine,
            state=ServiceState.INITIALIZED,
            dependencies=["candle_storage", "event_bus"]
        )
        logger.info("MultiTimeframeIndicatorEngine initialized")

    async def _initialize_strategy_layer(self) -> None:
        """Initialize strategy integration layer (depends on MultiTimeframeEngine)."""
        logger.info("Initializing StrategyIntegrationLayer...")
        self.strategy_layer = StrategyIntegrationLayer(
            enable_strategy_a=True,
            enable_strategy_b=True,
            enable_strategy_c=True
        )

        self._services["strategy_layer"] = ServiceInfo(
            name="strategy_layer",
            instance=self.strategy_layer,
            state=ServiceState.INITIALIZED,
            dependencies=["multi_timeframe_engine"]
        )
        logger.info("StrategyIntegrationLayer initialized")

    async def _initialize_risk_components(self) -> None:
        """Initialize risk management components (depends on BinanceManager, Database)."""
        logger.info("Initializing Risk components...")

        # Initialize sub-components (order matters due to dependencies)
        position_sizer = PositionSizer(
            binance_manager=self.binance_manager,
            risk_percentage=2.0,
            leverage=5
        )
        stop_loss_calculator = StopLossCalculator(
            position_sizer=position_sizer
        )
        take_profit_calculator = TakeProfitCalculator()
        daily_loss_monitor = DailyLossMonitor(
            event_bus=self.event_bus,
            daily_loss_limit_pct=5.0
        )

        # Initialize risk validator
        self.risk_validator = RiskValidator(
            position_sizer=position_sizer,
            stop_loss_calculator=stop_loss_calculator,
            take_profit_calculator=take_profit_calculator,
            daily_loss_monitor=daily_loss_monitor,
            event_bus=self.event_bus
        )

        self._services["risk_validator"] = ServiceInfo(
            name="risk_validator",
            instance=self.risk_validator,
            state=ServiceState.INITIALIZED,
            dependencies=["binance_manager", "database", "event_bus"]
        )
        logger.info("Risk components initialized")

    async def _initialize_order_executor(self) -> None:
        """Initialize order executor (depends on BinanceManager, EventBus)."""
        logger.info("Initializing OrderExecutor...")
        self.order_executor = OrderExecutor(
            exchange=self.binance_manager.exchange,
            event_bus=self.event_bus
        )

        self._services["order_executor"] = ServiceInfo(
            name="order_executor",
            instance=self.order_executor,
            state=ServiceState.INITIALIZED,
            dependencies=["binance_manager", "event_bus"]
        )
        logger.info("OrderExecutor initialized")

    async def _initialize_position_manager(self) -> None:
        """Initialize position manager (depends on Database, EventBus)."""
        logger.info("Initializing PositionManager...")
        # Get a database session for position manager
        async with db_engine.get_session() as session:
            self.position_manager = PositionManager(
                db_session=session,
                event_bus=self.event_bus
            )

        self._services["position_manager"] = ServiceInfo(
            name="position_manager",
            instance=self.position_manager,
            state=ServiceState.INITIALIZED,
            dependencies=["database", "event_bus"]
        )
        logger.info("PositionManager initialized")

    def _calculate_initialization_order(self) -> None:
        """
        Calculate service initialization order based on dependencies.

        Uses topological sort to determine correct startup sequence.
        """
        # Topological sort using Kahn's algorithm
        in_degree = {name: 0 for name in self._services}

        # Calculate in-degrees
        for service_info in self._services.values():
            for dep in service_info.dependencies:
                in_degree[service_info.name] += 1

        # Queue services with no dependencies
        queue = [name for name, degree in in_degree.items() if degree == 0]
        order = []

        while queue:
            current = queue.pop(0)
            order.append(current)

            # Reduce in-degree for dependent services
            for service_info in self._services.values():
                if current in service_info.dependencies:
                    in_degree[service_info.name] -= 1
                    if in_degree[service_info.name] == 0:
                        queue.append(service_info.name)

        if len(order) != len(self._services):
            raise OrchestratorError("Circular dependency detected in services")

        self._initialization_order = order
        logger.info(f"Service initialization order: {order}")

    async def start(self) -> None:
        """
        Start all system services in dependency order.

        Raises:
            OrchestratorError: If startup fails
        """
        with self._state_lock:
            if self._state not in [SystemState.OFFLINE]:
                raise OrchestratorError(
                    f"Cannot start from state {self._state}"
                )
            # Ensure services are initialized before starting
            if not self._services:
                raise OrchestratorError(
                    f"Cannot start from state {self._state} - services not initialized. Call initialize() first."
                )
            self._state = SystemState.STARTING

        try:
            logger.info("Starting trading system...")
            self._startup_time = datetime.now()

            # Start services in dependency order
            for service_name in self._initialization_order:
                await self._start_service(service_name)

            # Start health monitoring
            self._health_check_task = asyncio.create_task(
                self._health_check_loop()
            )

            with self._state_lock:
                self._state = SystemState.RUNNING

            logger.info(
                f"Trading system started successfully "
                f"({len(self._services)} services running)"
            )

        except Exception as e:
            with self._state_lock:
                self._state = SystemState.ERROR
            logger.error(f"Startup failed: {e}", exc_info=True)

            # Attempt cleanup
            await self._emergency_shutdown()
            raise OrchestratorError(f"Startup failed: {e}") from e

    async def _start_service(self, service_name: str) -> None:
        """
        Start a specific service.

        Args:
            service_name: Name of service to start

        Raises:
            OrchestratorError: If service startup fails
        """
        service_info = self._services[service_name]

        # Check dependencies are running
        for dep in service_info.dependencies:
            dep_info = self._services[dep]
            if dep_info.state != ServiceState.RUNNING:
                raise OrchestratorError(
                    f"Cannot start {service_name}: dependency {dep} not running"
                )

        try:
            logger.info(f"Starting service: {service_name}")
            service_info.update_state(ServiceState.STARTING)

            # Call start callback if provided
            if service_info.start_callback:
                await service_info.start_callback()

            service_info.update_state(ServiceState.RUNNING)
            logger.info(f"Service started: {service_name}")

        except Exception as e:
            service_info.update_state(ServiceState.ERROR, error=e)
            logger.error(f"Failed to start {service_name}: {e}", exc_info=True)
            raise OrchestratorError(f"Failed to start {service_name}") from e

    async def stop(self) -> None:
        """
        Stop all system services in reverse dependency order.

        Performs graceful shutdown of all components.
        """
        with self._state_lock:
            if self._state not in [SystemState.RUNNING, SystemState.ERROR]:
                logger.warning(f"Stop called from state {self._state}")
                return
            self._state = SystemState.STOPPING

        try:
            logger.info("Stopping trading system...")
            self._shutdown_time = datetime.now()

            # Stop health monitoring
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass

            # Stop services in reverse order
            for service_name in reversed(self._initialization_order):
                await self._stop_service(service_name)

            # Cancel all background tasks
            for task in self._background_tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            with self._state_lock:
                self._state = SystemState.OFFLINE

            uptime = (
                self._shutdown_time - self._startup_time
                if self._startup_time else None
            )
            logger.info(
                f"Trading system stopped successfully "
                f"(uptime: {uptime})"
            )

        except Exception as e:
            with self._state_lock:
                self._state = SystemState.ERROR
            logger.error(f"Shutdown error: {e}", exc_info=True)

    async def _stop_service(self, service_name: str) -> None:
        """
        Stop a specific service.

        Args:
            service_name: Name of service to stop
        """
        service_info = self._services[service_name]

        if service_info.state != ServiceState.RUNNING:
            return

        try:
            logger.info(f"Stopping service: {service_name}")
            service_info.update_state(ServiceState.STOPPING)

            # Call stop callback if provided
            if service_info.stop_callback:
                await service_info.stop_callback()

            service_info.update_state(ServiceState.STOPPED)
            logger.info(f"Service stopped: {service_name}")

        except Exception as e:
            service_info.update_state(ServiceState.ERROR, error=e)
            logger.error(f"Error stopping {service_name}: {e}", exc_info=True)

    async def _emergency_shutdown(self) -> None:
        """Emergency shutdown - attempt to stop all services."""
        logger.warning("Executing emergency shutdown...")

        for service_name in reversed(self._initialization_order):
            try:
                await self._stop_service(service_name)
            except Exception as e:
                logger.error(
                    f"Error during emergency shutdown of {service_name}: {e}"
                )

    async def _health_check_loop(self) -> None:
        """Background task for periodic health checking."""
        logger.info("Health check loop started")

        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._perform_health_checks()

            except asyncio.CancelledError:
                logger.info("Health check loop cancelled")
                break
            except Exception as e:
                logger.error(f"Health check error: {e}", exc_info=True)

    async def _perform_health_checks(self) -> None:
        """Perform health checks on all services."""
        for service_name, service_info in self._services.items():
            if service_info.state != ServiceState.RUNNING:
                continue

            if service_info.health_check:
                try:
                    await service_info.health_check()
                except Exception as e:
                    logger.error(
                        f"Health check failed for {service_name}: {e}"
                    )
                    service_info.update_state(ServiceState.ERROR, error=e)

    # Service-specific start/stop callbacks

    async def _start_binance_manager(self) -> None:
        """Start Binance manager with connection test."""
        if not self.binance_manager._connected:
            await self.binance_manager.test_connection()

    async def _stop_binance_manager(self) -> None:
        """Stop Binance manager and close connections."""
        await self.binance_manager.close()

    # Status and monitoring methods

    def get_system_state(self) -> SystemState:
        """Get current system state."""
        with self._state_lock:
            return self._state

    def get_service_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Get states of all services.

        Returns:
            Dictionary mapping service names to their state info
        """
        return {
            name: {
                "state": info.state.value,
                "last_change": info.last_state_change.isoformat(),
                "error": str(info.error) if info.error else None
            }
            for name, info in self._services.items()
        }

    def get_system_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive system statistics.

        Returns:
            Dictionary with system-wide statistics
        """
        uptime = None
        if self._startup_time:
            if self._shutdown_time:
                uptime = (self._shutdown_time - self._startup_time).total_seconds()
            elif self._state == SystemState.RUNNING:
                uptime = (datetime.now() - self._startup_time).total_seconds()

        return {
            "system_state": self._state.value,
            "uptime_seconds": uptime,
            "service_count": len(self._services),
            "services": self.get_service_states(),
            "event_bus_stats": (
                self.event_bus.get_stats() if self.event_bus else None
            ),
            "startup_time": (
                self._startup_time.isoformat() if self._startup_time else None
            ),
            "shutdown_time": (
                self._shutdown_time.isoformat() if self._shutdown_time else None
            )
        }

    def is_healthy(self) -> bool:
        """
        Check if system is healthy.

        Returns:
            True if system is running and all services are healthy
        """
        if self._state != SystemState.RUNNING:
            return False

        # Check all services are running
        for service_info in self._services.values():
            if service_info.state not in [ServiceState.RUNNING, ServiceState.INITIALIZED]:
                return False

        return True
