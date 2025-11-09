"""
Trading System Orchestrator - Main service coordination and lifecycle management.

This module implements the core orchestration layer that manages all trading system
components, their dependencies, initialization sequences, and lifecycle coordination.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
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


# Pipeline Event Handlers


class PipelineMetrics:
    """Metrics for pipeline performance monitoring."""

    def __init__(self):
        """Initialize pipeline metrics."""
        self.candles_received = 0
        self.candles_processed = 0
        self.indicators_calculated = 0
        self.signals_generated = 0
        self.orders_executed = 0
        self.errors = 0
        self.processing_times: Dict[str, List[float]] = {
            "candle_to_indicator": [],
            "indicator_to_signal": [],
            "signal_to_risk": [],
            "risk_to_order": [],
            "order_to_position": [],
        }
        self._lock = Lock()

    def record_candle(self) -> None:
        """Record candle received."""
        with self._lock:
            self.candles_received += 1

    def record_processed(self) -> None:
        """Record candle processed."""
        with self._lock:
            self.candles_processed += 1

    def record_indicator(self) -> None:
        """Record indicator calculation."""
        with self._lock:
            self.indicators_calculated += 1

    def record_signal(self) -> None:
        """Record signal generation."""
        with self._lock:
            self.signals_generated += 1

    def record_order(self) -> None:
        """Record order execution."""
        with self._lock:
            self.orders_executed += 1

    def record_error(self) -> None:
        """Record pipeline error."""
        with self._lock:
            self.errors += 1

    def record_processing_time(self, stage: str, duration: float) -> None:
        """
        Record processing time for a pipeline stage.

        Args:
            stage: Pipeline stage name
            duration: Processing duration in seconds
        """
        with self._lock:
            if stage in self.processing_times:
                self.processing_times[stage].append(duration)
                # Keep only last 100 measurements
                if len(self.processing_times[stage]) > 100:
                    self.processing_times[stage].pop(0)

    def get_avg_processing_time(self, stage: str) -> Optional[float]:
        """Get average processing time for a stage."""
        with self._lock:
            times = self.processing_times.get(stage, [])
            return sum(times) / len(times) if times else None

    def get_stats(self) -> Dict[str, Any]:
        """Get all pipeline statistics."""
        with self._lock:
            avg_times = {
                stage: self.get_avg_processing_time(stage)
                for stage in self.processing_times.keys()
            }
            return {
                "candles_received": self.candles_received,
                "candles_processed": self.candles_processed,
                "indicators_calculated": self.indicators_calculated,
                "signals_generated": self.signals_generated,
                "orders_executed": self.orders_executed,
                "errors": self.errors,
                "avg_processing_times_ms": {
                    stage: round(time * 1000, 2) if time else None
                    for stage, time in avg_times.items()
                },
                "processing_rate": (
                    self.candles_processed / max(self.candles_received, 1) * 100
                ) if self.candles_received > 0 else 0,
            }


class CandleProcessingHandler(EventHandler):
    """
    Handler for processing incoming candles through the pipeline.

    Receives CANDLE_RECEIVED events and coordinates storage and indicator calculation.
    """

    def __init__(
        self,
        candle_storage: CandleStorage,
        multi_timeframe_engine: MultiTimeframeIndicatorEngine,
        metrics: PipelineMetrics
    ):
        """
        Initialize candle processing handler.

        Args:
            candle_storage: Candle storage instance
            multi_timeframe_engine: Multi-timeframe indicator engine
            metrics: Pipeline metrics tracker
        """
        super().__init__(name="CandleProcessingHandler")
        self.candle_storage = candle_storage
        self.multi_timeframe_engine = multi_timeframe_engine
        self.metrics = metrics

    async def handle(self, event: Event) -> None:
        """Process candle received event."""
        if event.event_type != EventType.CANDLE_RECEIVED:
            return

        start_time = datetime.now()
        self.metrics.record_candle()

        try:
            # Extract candle data from event
            candle_data = event.data.get("candle")
            if not candle_data:
                self.logger.error("No candle data in CANDLE_RECEIVED event")
                self.metrics.record_error()
                return

            # Store candle
            from src.models.candle import Candle
            candle = Candle(**candle_data)
            self.candle_storage.add_candle(candle)

            # Calculate indicators for this candle
            self.multi_timeframe_engine.add_candle(candle)

            # Record metrics
            self.metrics.record_processed()
            duration = (datetime.now() - start_time).total_seconds()
            self.metrics.record_processing_time("candle_to_indicator", duration)

            self.logger.debug(
                f"Processed candle {candle.symbol} {candle.timeframe} "
                f"in {duration*1000:.2f}ms"
            )

        except Exception as e:
            self.logger.error(f"Error processing candle: {e}", exc_info=True)
            self.metrics.record_error()


class IndicatorToStrategyHandler(EventHandler):
    """
    Handler for forwarding indicator updates to strategy layer.

    Receives INDICATORS_UPDATED events and triggers strategy evaluation.
    """

    def __init__(
        self,
        strategy_layer: StrategyIntegrationLayer,
        metrics: PipelineMetrics
    ):
        """
        Initialize indicator to strategy handler.

        Args:
            strategy_layer: Strategy integration layer
            metrics: Pipeline metrics tracker
        """
        super().__init__(name="IndicatorToStrategyHandler")
        self.strategy_layer = strategy_layer
        self.metrics = metrics

    async def handle(self, event: Event) -> None:
        """Process indicators updated event."""
        if event.event_type != EventType.INDICATORS_UPDATED:
            return

        start_time = datetime.now()
        self.metrics.record_indicator()

        try:
            # Extract indicator data
            symbol = event.data.get("symbol")
            timeframe = event.data.get("timeframe")
            indicators = event.data.get("indicators", {})

            if not symbol or not timeframe:
                self.logger.error("Missing symbol or timeframe in INDICATORS_UPDATED event")
                return

            # Trigger strategy evaluation
            signals = await self.strategy_layer.evaluate_strategies(
                symbol=symbol,
                timeframe=timeframe,
                indicators=indicators
            )

            # Record metrics
            if signals:
                self.metrics.record_signal()

            duration = (datetime.now() - start_time).total_seconds()
            self.metrics.record_processing_time("indicator_to_signal", duration)

        except Exception as e:
            self.logger.error(f"Error in indicator to strategy: {e}", exc_info=True)
            self.metrics.record_error()


class SignalToRiskHandler(EventHandler):
    """
    Handler for processing trading signals through risk validation.

    Receives SIGNAL_GENERATED events and validates them against risk rules.
    """

    def __init__(
        self,
        risk_validator: RiskValidator,
        metrics: PipelineMetrics
    ):
        """
        Initialize signal to risk handler.

        Args:
            risk_validator: Risk validation service
            metrics: Pipeline metrics tracker
        """
        super().__init__(name="SignalToRiskHandler")
        self.risk_validator = risk_validator
        self.metrics = metrics

    async def handle(self, event: Event) -> None:
        """Process signal generated event."""
        if event.event_type != EventType.SIGNAL_GENERATED:
            return

        start_time = datetime.now()

        try:
            # Extract signal data
            signal_data = event.data.get("signal")
            if not signal_data:
                self.logger.error("No signal data in SIGNAL_GENERATED event")
                return

            # Validate signal against risk rules
            validation_result = await self.risk_validator.validate_signal(signal_data)

            duration = (datetime.now() - start_time).total_seconds()
            self.metrics.record_processing_time("signal_to_risk", duration)

            if not validation_result.is_valid:
                self.logger.info(
                    f"Signal rejected by risk validator: {validation_result.rejection_reason}"
                )

        except Exception as e:
            self.logger.error(f"Error in signal to risk validation: {e}", exc_info=True)
            self.metrics.record_error()


class RiskToOrderHandler(EventHandler):
    """
    Handler for executing orders after risk approval.

    Receives RISK_CHECK_PASSED events and executes validated orders.
    """

    def __init__(
        self,
        order_executor: OrderExecutor,
        metrics: PipelineMetrics
    ):
        """
        Initialize risk to order handler.

        Args:
            order_executor: Order execution service
            metrics: Pipeline metrics tracker
        """
        super().__init__(name="RiskToOrderHandler")
        self.order_executor = order_executor
        self.metrics = metrics

    async def handle(self, event: Event) -> None:
        """Process risk check passed event."""
        if event.event_type != EventType.RISK_CHECK_PASSED:
            return

        start_time = datetime.now()

        try:
            # Extract validated order data
            order_data = event.data.get("order")
            if not order_data:
                self.logger.error("No order data in RISK_CHECK_PASSED event")
                return

            # Execute order
            order_result = await self.order_executor.execute_order(order_data)

            # Record metrics
            self.metrics.record_order()
            duration = (datetime.now() - start_time).total_seconds()
            self.metrics.record_processing_time("risk_to_order", duration)

            self.logger.info(
                f"Order executed: {order_result.order_id} in {duration*1000:.2f}ms"
            )

        except Exception as e:
            self.logger.error(f"Error executing order: {e}", exc_info=True)
            self.metrics.record_error()


class OrderToPositionHandler(EventHandler):
    """
    Handler for updating positions after order execution.

    Receives ORDER_FILLED events and updates position tracking.
    """

    def __init__(
        self,
        position_manager: PositionManager,
        metrics: PipelineMetrics
    ):
        """
        Initialize order to position handler.

        Args:
            position_manager: Position management service
            metrics: Pipeline metrics tracker
        """
        super().__init__(name="OrderToPositionHandler")
        self.position_manager = position_manager
        self.metrics = metrics

    async def handle(self, event: Event) -> None:
        """Process order filled event."""
        if event.event_type not in [EventType.ORDER_FILLED, EventType.ORDER_PLACED]:
            return

        start_time = datetime.now()

        try:
            # Extract order data
            order_data = event.data.get("order")
            if not order_data:
                self.logger.error(f"No order data in {event.event_type} event")
                return

            # Update position tracking
            await self.position_manager.update_from_order(order_data)

            duration = (datetime.now() - start_time).total_seconds()
            self.metrics.record_processing_time("order_to_position", duration)

        except Exception as e:
            self.logger.error(f"Error updating position: {e}", exc_info=True)
            self.metrics.record_error()


class BackpressureMonitor:
    """
    Monitor and control pipeline backpressure.

    Tracks event queue sizes and processing rates to prevent overload.
    """

    def __init__(
        self,
        event_bus: EventBus,
        max_queue_threshold: float = 0.8,
        check_interval: int = 5
    ):
        """
        Initialize backpressure monitor.

        Args:
            event_bus: Event bus to monitor
            max_queue_threshold: Queue fullness threshold (0-1)
            check_interval: Check interval in seconds
        """
        self.event_bus = event_bus
        self.max_queue_threshold = max_queue_threshold
        self.check_interval = check_interval
        self.is_throttled = False
        self.throttle_count = 0
        self.logger = logging.getLogger(f"{__name__}.BackpressureMonitor")

    def check_backpressure(self) -> bool:
        """
        Check if system is experiencing backpressure.

        Returns:
            True if backpressure detected
        """
        stats = self.event_bus.get_stats()
        queue_size = stats.get("queue_size", 0)
        max_size = self.event_bus._max_queue_size

        queue_fullness = queue_size / max_size if max_size > 0 else 0

        if queue_fullness > self.max_queue_threshold:
            if not self.is_throttled:
                self.logger.warning(
                    f"Backpressure detected: queue {queue_fullness*100:.1f}% full "
                    f"({queue_size}/{max_size})"
                )
                self.is_throttled = True
                self.throttle_count += 1
            return True
        else:
            if self.is_throttled:
                self.logger.info("Backpressure relieved")
                self.is_throttled = False
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get backpressure statistics."""
        stats = self.event_bus.get_stats()
        queue_size = stats.get("queue_size", 0)
        max_size = self.event_bus._max_queue_size

        return {
            "is_throttled": self.is_throttled,
            "throttle_count": self.throttle_count,
            "queue_fullness": (queue_size / max_size * 100) if max_size > 0 else 0,
            "queue_size": queue_size,
            "max_queue_size": max_size,
        }


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

        # Pipeline components (initialized in _setup_pipeline_handlers)
        self._pipeline_metrics: Optional[PipelineMetrics] = None
        self._backpressure_monitor: Optional[BackpressureMonitor] = None
        self._pipeline_handlers: List[EventHandler] = []

        # Background tasks
        self._background_tasks: List[asyncio.Task] = []
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval = 30  # seconds
        self._backpressure_check_task: Optional[asyncio.Task] = None

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
        10. Pipeline Handlers (depends on all above components)

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
                    "Cannot initialize from state INITIALIZED"
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

            # Set up data pipeline handlers
            await self._setup_pipeline_handlers()

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
        """Initialize strategy integration layer (depends on MultiTimeframeEngine, EventBus, CandleStorage)."""
        logger.info("Initializing StrategyIntegrationLayer...")
        self.strategy_layer = StrategyIntegrationLayer(
            enable_strategy_a=True,
            enable_strategy_b=True,
            enable_strategy_c=True,
            event_bus=self.event_bus,
            candle_storage=self.candle_storage
        )

        self._services["strategy_layer"] = ServiceInfo(
            name="strategy_layer",
            instance=self.strategy_layer,
            state=ServiceState.INITIALIZED,
            dependencies=["multi_timeframe_engine", "event_bus", "candle_storage"]
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

    async def _setup_pipeline_handlers(self) -> None:
        """
        Set up data pipeline event handlers.

        Registers handlers for the complete data flow:
        BinanceManager → CandleStorage → MultiTimeframeEngine →
        StrategyIntegrationLayer → RiskValidator → OrderExecutor → PositionManager
        """
        logger.info("Setting up data pipeline handlers...")

        # Initialize pipeline metrics
        self._pipeline_metrics = PipelineMetrics()

        # Initialize backpressure monitor
        self._backpressure_monitor = BackpressureMonitor(
            event_bus=self.event_bus,
            max_queue_threshold=0.8,
            check_interval=5
        )

        # Create pipeline handlers
        candle_handler = CandleProcessingHandler(
            candle_storage=self.candle_storage,
            multi_timeframe_engine=self.multi_timeframe_engine,
            metrics=self._pipeline_metrics
        )

        indicator_handler = IndicatorToStrategyHandler(
            strategy_layer=self.strategy_layer,
            metrics=self._pipeline_metrics
        )

        signal_handler = SignalToRiskHandler(
            risk_validator=self.risk_validator,
            metrics=self._pipeline_metrics
        )

        risk_handler = RiskToOrderHandler(
            order_executor=self.order_executor,
            metrics=self._pipeline_metrics
        )

        order_handler = OrderToPositionHandler(
            position_manager=self.position_manager,
            metrics=self._pipeline_metrics
        )

        # Register handlers with event bus
        self.event_bus.subscribe(EventType.CANDLE_RECEIVED, candle_handler)
        self.event_bus.subscribe(EventType.INDICATORS_UPDATED, indicator_handler)
        self.event_bus.subscribe(EventType.SIGNAL_GENERATED, signal_handler)
        self.event_bus.subscribe(EventType.RISK_CHECK_PASSED, risk_handler)
        self.event_bus.subscribe(EventType.ORDER_FILLED, order_handler)
        self.event_bus.subscribe(EventType.ORDER_PLACED, order_handler)

        # Store handlers for cleanup
        self._pipeline_handlers = [
            candle_handler,
            indicator_handler,
            signal_handler,
            risk_handler,
            order_handler
        ]

        logger.info(
            f"Data pipeline configured with {len(self._pipeline_handlers)} handlers"
        )

    async def _start_backpressure_monitoring(self) -> None:
        """Start background task for backpressure monitoring."""
        logger.info("Starting backpressure monitoring...")
        self._backpressure_check_task = asyncio.create_task(
            self._backpressure_check_loop()
        )

    async def _backpressure_check_loop(self) -> None:
        """Background loop for checking pipeline backpressure."""
        while True:
            try:
                await asyncio.sleep(self._backpressure_monitor.check_interval)

                # Check backpressure
                has_backpressure = self._backpressure_monitor.check_backpressure()

                # Log backpressure stats periodically
                if has_backpressure:
                    stats = self._backpressure_monitor.get_stats()
                    logger.warning(f"Backpressure stats: {stats}")

            except asyncio.CancelledError:
                logger.info("Backpressure monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in backpressure monitoring: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause on error

    def get_pipeline_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive pipeline statistics.

        Returns:
            Dictionary with pipeline performance metrics
        """
        if not self._pipeline_metrics:
            return {}

        stats = self._pipeline_metrics.get_stats()

        # Add backpressure stats if available
        if self._backpressure_monitor:
            stats["backpressure"] = self._backpressure_monitor.get_stats()

        return stats

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

            # Start backpressure monitoring
            if self._backpressure_monitor:
                await self._start_backpressure_monitoring()

            with self._state_lock:
                self._state = SystemState.RUNNING

            logger.info(
                f"Trading system started successfully "
                f"({len(self._services)} services running, "
                f"pipeline monitoring active)"
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

            # Stop backpressure monitoring
            if self._backpressure_check_task:
                self._backpressure_check_task.cancel()
                try:
                    await self._backpressure_check_task
                except asyncio.CancelledError:
                    pass

            # Stop services in reverse order
            for service_name in reversed(self._initialization_order):
                await self._stop_service(service_name)

            # Unsubscribe pipeline handlers
            if self.event_bus and self._pipeline_handlers:
                for handler in self._pipeline_handlers:
                    self.event_bus.unsubscribe_all(handler)
                logger.info("Pipeline handlers unsubscribed")

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

            # Log final pipeline stats
            if self._pipeline_metrics:
                final_stats = self._pipeline_metrics.get_stats()
                logger.info(f"Final pipeline stats: {final_stats}")

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
            Dictionary with system-wide statistics including pipeline metrics
        """
        uptime = None
        if self._startup_time:
            if self._shutdown_time:
                uptime = (self._shutdown_time - self._startup_time).total_seconds()
            elif self._state == SystemState.RUNNING:
                uptime = (datetime.now() - self._startup_time).total_seconds()

        stats = {
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

        # Add pipeline statistics
        if self._pipeline_metrics or self._backpressure_monitor:
            stats["pipeline"] = self.get_pipeline_stats()

        return stats

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
