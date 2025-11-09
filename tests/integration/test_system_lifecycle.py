"""
Integration tests for complete system lifecycle.

Tests the main entry point (__main__.py) including:
- Environment validation
- Logging configuration
- System initialization
- Service startup
- Graceful shutdown
- Signal handling
"""

import logging
import os
import signal
from unittest.mock import Mock, patch, AsyncMock

import pytest

from src.__main__ import (
    validate_environment,
    setup_logging,
    setup_signal_handlers,
    initialize_system,
    start_system,
    shutdown_system,
    EnvironmentValidationError,
)


# ============================================================================
# Environment Validation Tests
# ============================================================================

class TestEnvironmentValidation:
    """Test environment validation logic."""

    def test_validate_environment_success(self, monkeypatch):
        """Test successful environment validation."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_api_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret_key")
        monkeypatch.setenv("TESTNET", "true")

        # Should not raise
        validate_environment()

    def test_validate_environment_missing_api_key(self, monkeypatch):
        """Test validation failure when API key is missing."""
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")

        with pytest.raises(EnvironmentValidationError) as exc_info:
            validate_environment()

        assert "BINANCE_API_KEY" in str(exc_info.value)

    def test_validate_environment_missing_secret_key(self, monkeypatch):
        """Test validation failure when secret key is missing."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_api")
        monkeypatch.delenv("BINANCE_SECRET_KEY", raising=False)

        with pytest.raises(EnvironmentValidationError) as exc_info:
            validate_environment()

        assert "BINANCE_SECRET_KEY" in str(exc_info.value)

    def test_validate_environment_invalid_testnet_value(self, monkeypatch):
        """Test validation failure with invalid TESTNET value."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_api")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.setenv("TESTNET", "invalid_value")

        with pytest.raises(EnvironmentValidationError) as exc_info:
            validate_environment()

        assert "TESTNET" in str(exc_info.value)

    def test_validate_environment_creates_db_directory(self, monkeypatch, tmp_path):
        """Test that database directory is created if it doesn't exist."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_api")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")

        db_path = tmp_path / "data" / "trading.db"

        with patch("src.__main__.settings") as mock_settings:
            mock_settings.database.path = str(db_path)
            mock_settings.logging.level = "INFO"

            validate_environment()

            assert db_path.parent.exists()


# ============================================================================
# Logging Configuration Tests
# ============================================================================

class TestLoggingSetup:
    """Test logging configuration."""

    def test_setup_logging_creates_log_directory(self, tmp_path, monkeypatch):
        """Test that logs directory is created."""
        monkeypatch.chdir(tmp_path)

        with patch("src.__main__.settings") as mock_settings:
            mock_settings.logging.level = "INFO"

            setup_logging()

            log_dir = tmp_path / "logs"
            assert log_dir.exists()

    def test_setup_logging_creates_log_file(self, tmp_path, monkeypatch):
        """Test that log file is created."""
        monkeypatch.chdir(tmp_path)

        with patch("src.__main__.settings") as mock_settings:
            mock_settings.logging.level = "INFO"

            setup_logging()

            log_dir = tmp_path / "logs"
            log_files = list(log_dir.glob("trading_bot_*.log"))
            assert len(log_files) > 0

    def test_setup_logging_configures_log_level(self, tmp_path, monkeypatch):
        """Test that log level is configured correctly."""
        monkeypatch.chdir(tmp_path)

        with patch("src.__main__.settings") as mock_settings:
            mock_settings.logging.level = "DEBUG"

            setup_logging()

            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

    def test_setup_logging_adds_handlers(self, tmp_path, monkeypatch):
        """Test that console and file handlers are added."""
        monkeypatch.chdir(tmp_path)

        with patch("src.__main__.settings") as mock_settings:
            mock_settings.logging.level = "INFO"

            setup_logging()

            root_logger = logging.getLogger()
            # Should have console and file handlers
            assert len(root_logger.handlers) >= 2


# ============================================================================
# Signal Handler Tests
# ============================================================================

class TestSignalHandlers:
    """Test signal handler configuration."""

    def test_setup_signal_handlers_registers_sigterm(self):
        """Test that SIGTERM handler is registered."""
        original_handler = signal.getsignal(signal.SIGTERM)

        try:
            setup_signal_handlers()

            current_handler = signal.getsignal(signal.SIGTERM)
            assert current_handler != original_handler

        finally:
            # Restore original handler
            signal.signal(signal.SIGTERM, original_handler)

    def test_setup_signal_handlers_registers_sigint(self):
        """Test that SIGINT handler is registered."""
        original_handler = signal.getsignal(signal.SIGINT)

        try:
            setup_signal_handlers()

            current_handler = signal.getsignal(signal.SIGINT)
            assert current_handler != original_handler

        finally:
            # Restore original handler
            signal.signal(signal.SIGINT, original_handler)


# ============================================================================
# System Lifecycle Tests
# ============================================================================

@pytest.mark.asyncio
class TestSystemLifecycle:
    """Test system initialization, startup, and shutdown."""

    async def test_initialize_system_creates_components(self):
        """Test that system initialization creates all required components."""
        with patch("src.__main__.settings") as mock_settings:
            mock_settings.trading.mode = "paper"
            mock_settings.binance.testnet = True
            mock_settings.database.path = "test.db"
            mock_settings.logging.level = "INFO"

            # Mock the orchestrator initialization
            with patch("src.__main__.TradingSystemOrchestrator") as mock_orch_class:
                mock_orch = AsyncMock()
                mock_orch.event_bus = Mock()
                mock_orch._services = {"service1": Mock(), "service2": Mock()}
                mock_orch_class.return_value = mock_orch

                with patch("src.__main__.ConfigurationManager") as mock_cfg_class:
                    mock_cfg = Mock()
                    mock_cfg_class.return_value = mock_cfg

                    with patch("src.__main__.MetricsCollector"):
                        with patch("src.__main__.MonitoringSystem"):
                            orch, cfg, metrics, monitoring, evt_bus = await initialize_system()

                            # Verify components were created
                            assert orch is not None
                            assert cfg is not None
                            assert metrics is not None
                            assert monitoring is not None
                            assert evt_bus is not None

                            # Verify orchestrator was initialized
                            mock_orch.initialize.assert_called_once()

    async def test_start_system_starts_orchestrator(self):
        """Test that start_system calls orchestrator.start()."""
        mock_orch = AsyncMock()

        await start_system(mock_orch)

        mock_orch.start.assert_called_once()

    async def test_shutdown_system_stops_orchestrator(self):
        """Test that shutdown_system stops orchestrator."""
        mock_orch = AsyncMock()
        mock_cfg = Mock()

        await shutdown_system(mock_orch, mock_cfg)

        mock_orch.stop.assert_called_once()
        mock_cfg.save.assert_called_once()

    async def test_shutdown_system_handles_errors_gracefully(self):
        """Test that shutdown handles errors without crashing."""
        mock_orch = AsyncMock()
        mock_orch.stop.side_effect = Exception("Test error")
        mock_cfg = Mock()

        # Should not raise exception
        await shutdown_system(mock_orch, mock_cfg)

        # Config should still be saved even if orchestrator fails
        mock_cfg.save.assert_called_once()


# ============================================================================
# Integration Test: Complete Lifecycle
# ============================================================================

@pytest.mark.asyncio
class TestCompleteSystemLifecycle:
    """
    Integration test for the complete system lifecycle.

    This test simulates the full startup → run → shutdown sequence.
    """

    async def test_complete_lifecycle(self, monkeypatch, tmp_path):
        """Test complete system lifecycle from start to shutdown."""
        # Setup environment
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.setenv("TESTNET", "true")
        monkeypatch.chdir(tmp_path)

        # Track lifecycle stages
        lifecycle_stages = []

        # Mock all major components
        with patch("src.__main__.settings") as mock_settings:
            mock_settings.trading.mode = "paper"
            mock_settings.binance.testnet = True
            mock_settings.database.path = str(tmp_path / "test.db")
            mock_settings.logging.level = "INFO"

            with patch("src.__main__.TradingSystemOrchestrator") as mock_orch_class:
                mock_orch = AsyncMock()
                mock_orch.event_bus = Mock()
                mock_orch._services = {"svc": Mock()}

                async def mock_initialize():
                    lifecycle_stages.append("initialize")

                async def mock_start():
                    lifecycle_stages.append("start")

                async def mock_stop():
                    lifecycle_stages.append("stop")

                mock_orch.initialize = mock_initialize
                mock_orch.start = mock_start
                mock_orch.stop = mock_stop
                mock_orch_class.return_value = mock_orch

                with patch("src.__main__.ConfigurationManager") as mock_cfg_class:
                    mock_cfg = Mock()
                    mock_cfg_class.return_value = mock_cfg

                    with patch("src.__main__.MetricsCollector"):
                        with patch("src.__main__.MonitoringSystem"):
                            # Execute lifecycle
                            # 1. Initialize
                            orch, cfg_mgr, _, _, _ = await initialize_system()
                            assert "initialize" in lifecycle_stages

                            # 2. Start
                            await start_system(orch)
                            assert "start" in lifecycle_stages

                            # 3. Shutdown
                            await shutdown_system(orch, cfg_mgr)
                            assert "stop" in lifecycle_stages

                            # Verify complete sequence
                            assert lifecycle_stages == ["initialize", "start", "stop"]

                            # Verify config was saved
                            mock_cfg.save.assert_called_once()

    async def test_lifecycle_with_initialization_failure(self, monkeypatch, tmp_path):
        """Test that initialization failure is handled properly."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.chdir(tmp_path)

        with patch("src.__main__.settings") as mock_settings:
            mock_settings.trading.mode = "paper"
            mock_settings.binance.testnet = True
            mock_settings.database.path = str(tmp_path / "test.db")
            mock_settings.logging.level = "INFO"

            with patch("src.__main__.TradingSystemOrchestrator") as mock_orch_class:
                mock_orch = AsyncMock()
                mock_orch.initialize.side_effect = Exception("Initialization failed")
                mock_orch_class.return_value = mock_orch

                with patch("src.__main__.ConfigurationManager"):
                    # Should raise exception
                    with pytest.raises(Exception) as exc_info:
                        await initialize_system()

                    assert "Initialization failed" in str(exc_info.value)


# ============================================================================
# Test Utilities
# ============================================================================

@pytest.fixture
def clean_environment(monkeypatch):
    """Clean environment for testing."""
    # Clear all environment variables that might interfere
    for key in list(os.environ.keys()):
        if key.startswith("BINANCE_") or key in ["TESTNET", "LOG_LEVEL"]:
            monkeypatch.delenv(key, raising=False)

    yield

    # Cleanup is automatic with monkeypatch
