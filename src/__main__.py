"""
Main entry point for the Trading Bot - ICT Strategy Automated Trading System.

This module orchestrates the complete system lifecycle including:
- Environment validation and configuration
- Logging initialization
- Service orchestration and dependency management
- Graceful shutdown handling
- API server integration

Usage:
    python -m src                    # Run with default settings
    TESTNET=false python -m src      # Run on mainnet
    LOG_LEVEL=DEBUG python -m src    # Debug logging
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.api.server import app as fastapi_app
from src.core.config import settings
from src.core.config_manager import ConfigurationManager
from src.core.events import EventBus
from src.core.metrics import MetricsCollector, MonitoringSystem
from src.core.orchestrator import TradingSystemOrchestrator

# Global instances for signal handling
orchestrator: Optional[TradingSystemOrchestrator] = None
config_manager: Optional[ConfigurationManager] = None
shutdown_event: Optional[asyncio.Event] = None

logger = logging.getLogger(__name__)


# ============================================================================
# Environment Validation
# ============================================================================


class EnvironmentValidationError(Exception):
    """Raised when environment validation fails."""



def validate_environment() -> None:
    """
    Validate required environment variables and system requirements.

    Raises:
        EnvironmentValidationError: If validation fails
    """
    required_vars = {
        "BINANCE_API_KEY": "Binance API key for trading",
        "BINANCE_SECRET_KEY": "Binance secret key for authentication",
    }

    missing_required = []

    for var, description in required_vars.items():
        if not os.getenv(var):
            missing_required.append(f"  - {var}: {description}")

    if missing_required:
        error_msg = (
            "❌ Missing required environment variables:\n"
            + "\n".join(missing_required)
            + "\n\nPlease set these variables in your .env file or environment."
        )
        raise EnvironmentValidationError(error_msg)

    # Validate optional variables
    testnet = os.getenv("TESTNET", "true").lower()
    if testnet not in ["true", "false", "1", "0", "yes", "no"]:
        raise EnvironmentValidationError(
            f"❌ Invalid TESTNET value: {testnet}. Must be true/false."
        )

    # Validate database path
    db_path = settings.database.path
    db_dir = Path(db_path).parent
    if not db_dir.exists():
        logger.info(f"Creating database directory: {db_dir}")
        db_dir.mkdir(parents=True, exist_ok=True)

    logger.info("✅ Environment validation passed")


# ============================================================================
# Logging Configuration
# ============================================================================


def setup_logging() -> None:
    """
    Configure comprehensive logging for the trading system.

    Sets up:
    - Console handler with color formatting
    - File handler for persistent logs
    - Appropriate log levels for different modules
    - Structured log format with timestamps
    """
    log_level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Log file with timestamp
    log_file = log_dir / f"trading_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler with formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler with detailed formatting
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setLevel(logging.DEBUG)  # Always DEBUG in file
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Set levels for noisy third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    logger.info(f"✅ Logging configured: Level={settings.logging.level}, File={log_file}")


# ============================================================================
# Signal Handlers
# ============================================================================


def setup_signal_handlers() -> None:
    """
    Configure signal handlers for graceful shutdown.

    Handles:
    - SIGTERM: Graceful shutdown from system
    - SIGINT: Ctrl+C from user
    """

    def signal_handler(sig, frame):
        """Handle shutdown signals."""
        sig_name = signal.Signals(sig).name
        logger.warning(f"⚠️  Received {sig_name} signal - initiating graceful shutdown")

        if shutdown_event:
            shutdown_event.set()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("✅ Signal handlers configured (SIGTERM, SIGINT)")


# ============================================================================
# System Lifecycle
# ============================================================================


async def initialize_system() -> tuple[
    TradingSystemOrchestrator,
    ConfigurationManager,
    MetricsCollector,
    MonitoringSystem,
    EventBus,
]:
    """
    Initialize all system components.

    Returns:
        Tuple of (orchestrator, config_manager, metrics, monitoring, event_bus)

    Raises:
        Exception: If initialization fails
    """
    logger.info("=" * 80)
    logger.info("🚀 Trading Bot - ICT Strategy Automated Trading System")
    logger.info("=" * 80)
    logger.info(f"📊 Trading Mode: {settings.trading.mode.upper()}")
    logger.info(f"🔧 Environment: {'Testnet' if settings.binance.testnet else 'LIVE TRADING ⚠️'}")
    logger.info(f"💾 Database: {settings.database.path}")
    logger.info("=" * 80)

    # Initialize configuration manager
    logger.info("📝 Initializing configuration manager...")
    cfg_manager = ConfigurationManager(config_file=None)  # Uses default config

    # Initialize orchestrator
    logger.info("🎛️  Initializing trading system orchestrator...")
    orch = TradingSystemOrchestrator(
        enable_testnet=settings.binance.testnet,
        config_manager=cfg_manager,
    )

    # Initialize orchestrator services
    logger.info("⚙️  Initializing all trading services...")
    await orch.initialize()
    logger.info(f"✅ Initialized {len(orch._services)} services")

    # Get references to core components
    evt_bus = orch.event_bus

    # Initialize monitoring
    logger.info("📊 Initializing metrics and monitoring...")
    metrics = MetricsCollector()
    monitoring = MonitoringSystem(
        event_bus=evt_bus,
        metrics_collector=metrics,
    )

    logger.info("✅ System initialization complete")
    return orch, cfg_manager, metrics, monitoring, evt_bus


async def start_system(
    orch: TradingSystemOrchestrator,
) -> None:
    """
    Start all system services.

    Args:
        orch: Initialized orchestrator

    Raises:
        Exception: If startup fails
    """
    logger.info("🚀 Starting trading system services...")

    await orch.start()

    logger.info("✅ All services started successfully")


async def shutdown_system(
    orch: TradingSystemOrchestrator,
    cfg_manager: ConfigurationManager,
) -> None:
    """
    Gracefully shutdown all system components.

    Args:
        orch: Trading system orchestrator
        cfg_manager: Configuration manager
    """
    logger.info("🛑 Initiating graceful shutdown...")

    # Stop orchestrator (stops all services in reverse order)
    if orch:
        try:
            logger.info("Stopping trading system services...")
            await orch.stop()
            logger.info("✅ Trading system stopped")
        except Exception as e:
            logger.error(f"Error stopping orchestrator: {e}", exc_info=True)

    # Save configuration state (always attempt even if orchestrator fails)
    if cfg_manager:
        try:
            logger.info("Saving configuration state...")
            cfg_manager.save()
            logger.info("✅ Configuration saved")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}", exc_info=True)

    logger.info("👋 Shutdown complete")


# ============================================================================
# API Server Integration
# ============================================================================


async def run_api_server(
    orch: TradingSystemOrchestrator,
    cfg_manager: ConfigurationManager,
    metrics: MetricsCollector,
    monitoring: MonitoringSystem,
    evt_bus: EventBus,
) -> None:
    """
    Run FastAPI server in the background.

    Args:
        orch: Trading system orchestrator
        cfg_manager: Configuration manager
        metrics: Metrics collector
        monitoring: Monitoring system
        evt_bus: Event bus
    """
    import uvicorn

    # Set global instances in API module
    import src.api.server as server_module
    from src.api.websocket import WebSocketManager

    server_module.orchestrator = orch
    server_module.config_manager = cfg_manager
    server_module.metrics_collector = metrics
    server_module.monitoring_system = monitoring
    server_module.event_bus = evt_bus
    server_module.ws_manager = WebSocketManager(event_bus=evt_bus)

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    logger.info(f"🌐 Starting API server on {host}:{port}")

    config = uvicorn.Config(
        app=fastapi_app,
        host=host,
        port=port,
        log_level=settings.logging.level.lower(),
        access_log=True,
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    except asyncio.CancelledError:
        logger.info("API server cancelled")
    except Exception as e:
        logger.error(f"API server error: {e}", exc_info=True)
        raise


# ============================================================================
# Main Entry Point
# ============================================================================


async def main() -> None:
    """
    Main entry point for the trading bot.

    Orchestrates:
    1. Environment validation
    2. Logging setup
    3. Signal handler registration
    4. System initialization
    5. Service startup
    6. API server launch
    7. Graceful shutdown on signal
    """
    global orchestrator, config_manager, shutdown_event

    try:
        # 1. Validate environment
        validate_environment()

        # 2. Setup logging
        setup_logging()

        # 3. Setup signal handlers
        setup_signal_handlers()
        shutdown_event = asyncio.Event()

        # 4. Initialize system
        orch, cfg_mgr, metrics, monitoring, evt_bus = await initialize_system()
        orchestrator = orch
        config_manager = cfg_mgr

        # 5. Start services
        await start_system(orch)

        # 6. Start API server in background
        api_task = asyncio.create_task(run_api_server(orch, cfg_mgr, metrics, monitoring, evt_bus))

        logger.info("=" * 80)
        logger.info("✅ Trading Bot is now running")
        logger.info("📡 API server available at http://0.0.0.0:8000")
        logger.info("📚 API documentation at http://0.0.0.0:8000/docs")
        logger.info("🔄 WebSocket endpoint at ws://0.0.0.0:8000/ws")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 80)

        # Wait for shutdown signal
        await shutdown_event.wait()

        # Cancel API server
        api_task.cancel()
        try:
            await api_task
        except asyncio.CancelledError:
            pass

        # 7. Graceful shutdown
        await shutdown_system(orch, cfg_mgr)

    except EnvironmentValidationError as e:
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        if orchestrator and config_manager:
            await shutdown_system(orchestrator, config_manager)

    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}", exc_info=True)
        if orchestrator and config_manager:
            await shutdown_system(orchestrator, config_manager)
        sys.exit(1)


def run() -> None:
    """
    Run the trading bot with proper async event loop handling.
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Trading bot stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    run()
