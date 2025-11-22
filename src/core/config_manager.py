"""
Dynamic Configuration Management System.

Provides hot-reload, environment switching, and change tracking for all system configurations.
Integrates with EventBus for configuration change notifications and coordinates settings
across all services (Binance, Trading, Database, Logging, API, ICT, Strategies).
"""

import asyncio
import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional

import yaml
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.core.config import (
    Settings,
)
from src.core.constants import EventType
from src.core.events import Event, EventBus

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Configuration-related errors"""


class ConfigFileWatcher(FileSystemEventHandler):
    """
    Watches configuration files for changes and triggers hot-reload.
    """

    def __init__(self, config_manager: "ConfigurationManager"):
        self.config_manager = config_manager
        self.last_reload = {}
        self.debounce_seconds = 1.0  # Prevent rapid reloads

    def on_modified(self, event: FileModifiedEvent):
        """Handle file modification events"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Check if it's a config file
        if file_path.suffix not in [".yaml", ".yml", ".json"]:
            return

        # Debounce rapid changes
        now = datetime.utcnow().timestamp()
        last_time = self.last_reload.get(str(file_path), 0)

        if now - last_time < self.debounce_seconds:
            return

        self.last_reload[str(file_path)] = now

        logger.info(f"Configuration file modified: {file_path}")
        try:
            self.config_manager.reload_from_file(file_path)
        except Exception as e:
            logger.error(f"Failed to reload configuration from {file_path}: {e}")


class ConfigurationHistory:
    """
    Tracks configuration changes with rollback capability.
    """

    def __init__(self, max_history: int = 20):
        self.max_history = max_history
        self.history: List[Dict[str, Any]] = []
        self._lock = RLock()

    def save_snapshot(self, config: Dict[str, Any], reason: str = "update") -> None:
        """Save configuration snapshot"""
        with self._lock:
            snapshot = {
                "timestamp": datetime.utcnow().isoformat(),
                "reason": reason,
                "config": copy.deepcopy(config),
            }
            self.history.append(snapshot)

            # Limit history size
            if len(self.history) > self.max_history:
                self.history.pop(0)

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Get most recent snapshot"""
        with self._lock:
            return self.history[-1] if self.history else None

    def rollback(self, steps: int = 1) -> Optional[Dict[str, Any]]:
        """Rollback to previous configuration"""
        with self._lock:
            if len(self.history) <= steps:
                return None

            # Get the snapshot to restore
            snapshot_to_restore = self.history[-steps]

            # Remove 'steps' most recent snapshots
            for _ in range(min(steps, len(self.history))):
                self.history.pop()

            return snapshot_to_restore

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent configuration history"""
        with self._lock:
            return self.history[-limit:]


class ConfigurationManager:
    """
    Global configuration manager with hot-reload and environment switching.

    Features:
    - Hot-reload configuration from YAML/JSON files
    - Environment switching (testnet ↔ mainnet)
    - Configuration change history and rollback
    - Event-driven notifications via EventBus
    - Thread-safe configuration updates
    - Validation before applying changes
    - Configuration file watching for auto-reload
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config_dir: Optional[Path] = None,
        enable_file_watching: bool = True,
        auto_save: bool = True,
    ):
        """
        Initialize configuration manager.

        Args:
            event_bus: EventBus for configuration change notifications
            config_dir: Directory containing configuration files
            enable_file_watching: Enable automatic file watching and reload
            auto_save: Automatically save after successful updates
        """
        self.event_bus = event_bus
        self.config_dir = config_dir or Path("config")
        self.enable_file_watching = enable_file_watching
        self.auto_save = auto_save

        # Thread safety
        self._lock = RLock()

        # Current settings
        self.settings = Settings()

        # Configuration history
        self.history = ConfigurationHistory(max_history=20)

        # Change callbacks
        self._change_callbacks: List[Callable[[str, Any, Any], None]] = []

        # File watcher
        self._observer: Optional[Observer] = None

        # Metrics
        self.metrics = {
            "reloads": 0,
            "successful_reloads": 0,
            "failed_reloads": 0,
            "rollbacks": 0,
            "env_switches": 0,
            "config_updates": 0,
        }

        # Initialize
        self._initialize()

    def _initialize(self) -> None:
        """Initialize configuration manager"""
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Save initial snapshot
        self.history.save_snapshot(self._get_current_config(), reason="init")

        # Start file watching if enabled
        if self.enable_file_watching:
            self._start_file_watching()

        logger.info(
            f"ConfigurationManager initialized (config_dir={self.config_dir}, file_watching={self.enable_file_watching})"
        )

    def _start_file_watching(self) -> None:
        """Start watching configuration files for changes"""
        try:
            self._observer = Observer()
            event_handler = ConfigFileWatcher(self)
            self._observer.schedule(event_handler, str(self.config_dir), recursive=True)
            self._observer.start()
            logger.info(f"Started watching configuration directory: {self.config_dir}")
        except Exception as e:
            logger.error(f"Failed to start file watching: {e}")
            self._observer = None

    def _stop_file_watching(self) -> None:
        """Stop watching configuration files"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped configuration file watching")

    def _get_current_config(self) -> Dict[str, Any]:
        """Get current configuration as dictionary"""
        return {
            "binance": {
                "testnet": self.settings.binance.testnet,
                "api_key": (
                    self.settings.binance.active_api_key[:8] + "..."
                    if self.settings.binance.active_api_key
                    else None
                ),
            },
            "trading": {
                "mode": self.settings.trading.mode,
                "default_leverage": self.settings.trading.default_leverage,
                "max_position_size_usdt": self.settings.trading.max_position_size_usdt,
                "risk_per_trade_percent": self.settings.trading.risk_per_trade_percent,
            },
            "database": {
                "path": self.settings.database.path,
            },
            "logging": {
                "level": self.settings.logging.level,
                "file_path": self.settings.logging.file_path,
            },
            "api": {
                "host": self.settings.api.host,
                "port": self.settings.api.port,
                "reload": self.settings.api.reload,
            },
            "ict": {
                "fvg_min_size_percent": self.settings.ict.fvg_min_size_percent,
                "ob_lookback_periods": self.settings.ict.ob_lookback_periods,
                "liquidity_sweep_threshold": self.settings.ict.liquidity_sweep_threshold,
            },
            "strategy": {
                "enable_strategy_1": self.settings.strategy.enable_strategy_1,
                "enable_strategy_2": self.settings.strategy.enable_strategy_2,
                "enable_strategy_3": self.settings.strategy.enable_strategy_3,
            },
            "market": {
                "active_symbols": self.settings.market.active_symbols,
                "primary_timeframe": self.settings.market.primary_timeframe,
                "higher_timeframe": self.settings.market.higher_timeframe,
                "lower_timeframe": self.settings.market.lower_timeframe,
            },
        }

    def reload_from_file(self, filepath: Path) -> bool:
        """
        Reload configuration from file.

        Args:
            filepath: Path to configuration file (YAML or JSON)

        Returns:
            True if successful

        Raises:
            ConfigurationError: If reload fails
        """
        with self._lock:
            try:
                self.metrics["reloads"] += 1

                # Save current config for rollback
                self.history.save_snapshot(
                    self._get_current_config(), reason=f"reload:{filepath.name}"
                )

                # Load configuration file
                if filepath.suffix in [".yaml", ".yml"]:
                    with open(filepath, "r") as f:
                        config_data = yaml.safe_load(f)
                elif filepath.suffix == ".json":
                    with open(filepath, "r") as f:
                        config_data = json.load(f)
                else:
                    raise ConfigurationError(f"Unsupported file format: {filepath.suffix}")

                # Apply configuration
                self._apply_config(config_data)

                # Emit event
                self._emit_config_changed("file_reload", filepath.name, config_data)

                self.metrics["successful_reloads"] += 1
                logger.info(f"Configuration reloaded from {filepath}")
                return True

            except Exception as e:
                self.metrics["failed_reloads"] += 1
                logger.error(f"Failed to reload configuration from {filepath}: {e}")
                raise ConfigurationError(f"Configuration reload failed: {e}")

    def _apply_config(self, config_data: Dict[str, Any]) -> None:
        """
        Apply configuration data to settings.

        Args:
            config_data: Configuration dictionary

        Raises:
            ConfigurationError: If validation fails
        """
        # Validate structure
        if not isinstance(config_data, dict):
            raise ConfigurationError("Configuration must be a dictionary")

        # Apply each section
        for section, data in config_data.items():
            if section == "binance" and hasattr(self.settings, "binance"):
                self._apply_binance_config(data)
            elif section == "trading" and hasattr(self.settings, "trading"):
                self._apply_trading_config(data)
            elif section == "database" and hasattr(self.settings, "database"):
                self._apply_database_config(data)
            elif section == "logging" and hasattr(self.settings, "logging"):
                self._apply_logging_config(data)
            elif section == "api" and hasattr(self.settings, "api"):
                self._apply_api_config(data)
            elif section == "ict" and hasattr(self.settings, "ict"):
                self._apply_ict_config(data)
            elif section == "strategy" and hasattr(self.settings, "strategy"):
                self._apply_strategy_config(data)
            elif section == "market" and hasattr(self.settings, "market"):
                self._apply_market_config(data)  
            else:
                logger.warning(f"Unknown configuration section: {section}")

    def _apply_binance_config(self, data: Dict[str, Any]) -> None:
        """Apply Binance configuration"""
        for key, value in data.items():
            if hasattr(self.settings.binance, key):
                setattr(self.settings.binance, key, value)

    def _apply_trading_config(self, data: Dict[str, Any]) -> None:
        """Apply trading configuration"""
        for key, value in data.items():
            if hasattr(self.settings.trading, key):
                setattr(self.settings.trading, key, value)

    def _apply_database_config(self, data: Dict[str, Any]) -> None:
        """Apply database configuration"""
        for key, value in data.items():
            if hasattr(self.settings.database, key):
                setattr(self.settings.database, key, value)

    def _apply_logging_config(self, data: Dict[str, Any]) -> None:
        """Apply logging configuration"""
        for key, value in data.items():
            if hasattr(self.settings.logging, key):
                setattr(self.settings.logging, key, value)

    def _apply_api_config(self, data: Dict[str, Any]) -> None:
        """Apply API configuration"""
        for key, value in data.items():
            if hasattr(self.settings.api, key):
                setattr(self.settings.api, key, value)

    def _apply_ict_config(self, data: Dict[str, Any]) -> None:
        """Apply ICT configuration"""
        for key, value in data.items():
            if hasattr(self.settings.ict, key):
                setattr(self.settings.ict, key, value)

    def _apply_strategy_config(self, data: Dict[str, Any]) -> None:
        """Apply strategy configuration"""
        for key, value in data.items():
            if hasattr(self.settings.strategy, key):
                setattr(self.settings.strategy, key, value)

    def _apply_market_config(self, data: Dict[str, Any]) -> None:
        """Apply market configuration"""
        for key, value in data.items():
            if hasattr(self.settings.market, key):
                setattr(self.settings.market, key, value)

    def switch_environment(self, to_testnet: bool) -> bool:
        """
        Switch between testnet and mainnet environments.

        Args:
            to_testnet: True to switch to testnet, False for mainnet

        Returns:
            True if successful

        Raises:
            ConfigurationError: If switch fails or credentials missing
        """
        with self._lock:
            try:
                # Save current config
                self.history.save_snapshot(
                    self._get_current_config(),
                    reason=f"env_switch:{'testnet' if to_testnet else 'mainnet'}",
                )

                old_env = self.settings.binance.testnet

                # Switch environment
                self.settings.binance.testnet = to_testnet

                # Validate credentials for new environment
                self.settings.binance.validate_credentials()

                # Emit event
                env_name = "testnet" if to_testnet else "mainnet"
                self._emit_config_changed(
                    "environment_switch",
                    env_name,
                    {
                        "from": "testnet" if old_env else "mainnet",
                        "to": env_name,
                    },
                )

                self.metrics["env_switches"] += 1
                logger.info(f"Environment switched to {env_name}")
                return True

            except Exception as e:
                logger.error(f"Environment switch failed: {e}")
                # Rollback
                self.rollback()
                raise ConfigurationError(f"Environment switch failed: {e}")

    def update_config(
        self,
        section: str,
        updates: Dict[str, Any],
        validate: bool = True,
    ) -> bool:
        """
        Update configuration section at runtime.

        Args:
            section: Configuration section (binance, trading, etc.)
            updates: Parameter updates
            validate: Validate before applying

        Returns:
            True if successful

        Raises:
            ConfigurationError: If validation fails
        """
        with self._lock:
            try:
                # Save current config
                self.history.save_snapshot(self._get_current_config(), reason=f"update:{section}")

                # Apply updates based on section
                if section == "binance":
                    self._apply_binance_config(updates)
                    if validate:
                        self.settings.binance.validate_credentials()
                elif section == "trading":
                    self._apply_trading_config(updates)
                elif section == "database":
                    self._apply_database_config(updates)
                elif section == "logging":
                    self._apply_logging_config(updates)
                elif section == "api":
                    self._apply_api_config(updates)
                elif section == "ict":
                    self._apply_ict_config(updates)
                elif section == "strategy":
                    self._apply_strategy_config(updates)
                elif section == "market":
                    self._apply_market_config(updates)
                else:
                    raise ConfigurationError(f"Unknown configuration section: {section}")

                # Emit event
                self._emit_config_changed("config_update", section, updates)

                # Auto-save
                if self.auto_save:
                    self.save_config()

                self.metrics["config_updates"] += 1
                logger.info(f"Configuration updated: {section} = {updates}")
                return True

            except Exception as e:
                logger.error(f"Configuration update failed: {e}")
                self.rollback()
                raise ConfigurationError(f"Configuration update failed: {e}")

    def update_config_batch(
        self,
        updates_by_section: Dict[str, Dict[str, Any]],
        validate: bool = True,
    ) -> bool:
        """
        Update multiple configuration sections atomically.

        Args:
            updates_by_section: Dictionary of {section: updates}
            validate: Validate before applying

        Returns:
            True if successful
        """
        with self._lock:
            try:
                # Save current config ONCE
                self.history.save_snapshot(self._get_current_config(), reason="update:batch")

                # Apply all updates
                for section, updates in updates_by_section.items():
                    if section == "binance":
                        self._apply_binance_config(updates)
                        if validate:
                            self.settings.binance.validate_credentials()
                    elif section == "trading":
                        self._apply_trading_config(updates)
                    elif section == "database":
                        self._apply_database_config(updates)
                    elif section == "logging":
                        self._apply_logging_config(updates)
                    elif section == "api":
                        self._apply_api_config(updates)
                    elif section == "ict":
                        self._apply_ict_config(updates)
                    elif section == "strategy":
                        self._apply_strategy_config(updates)
                    elif section == "market":
                        self._apply_market_config(updates)
                    else:
                        logger.warning(f"Unknown configuration section: {section}")

                # Emit event
                self._emit_config_changed("config_update_batch", "all", updates_by_section)

                # Auto-save
                if self.auto_save:
                    self.save_config()

                self.metrics["config_updates"] += 1
                logger.info(f"Batch configuration updated: {list(updates_by_section.keys())}")
                return True

            except Exception as e:
                logger.error(f"Batch configuration update failed: {e}")
                self.rollback()
                raise ConfigurationError(f"Batch configuration update failed: {e}")

    def rollback(self, steps: int = 1) -> bool:
        """
        Rollback to previous configuration.

        Args:
            steps: Number of steps to rollback

        Returns:
            True if successful
        """
        with self._lock:
            try:
                logger.info(f"Attempting rollback. Current history size: {len(self.history.history)}")
                
                previous_config = self.history.rollback(steps)
                if not previous_config:
                    logger.warning("No configuration history available for rollback")
                    return False

                logger.info(f"Restoring configuration from snapshot. Timestamp: {previous_config.get('timestamp')}, Reason: {previous_config.get('reason')}")
                # logger.debug(f"Restored config data: {previous_config.get('config')}")

                # Apply previous config
                self._apply_config(previous_config["config"])

                # Save rolled back config to file
                if self.auto_save:
                    self.save_config()

                # Emit event
                self._emit_config_changed("rollback", "all", {"steps": steps})

                self.metrics["rollbacks"] += 1
                logger.info(f"Configuration rolled back {steps} step(s)")
                return True

            except Exception as e:
                logger.error(f"Configuration rollback failed: {e}")
                return False

    def save_config(self, filepath: Optional[Path] = None) -> bool:
        """
        Save current configuration to file.

        Args:
            filepath: Target file path (uses default if None)

        Returns:
            True if successful
        """
        target_path = filepath or self.config_dir / "current_config.yaml"

        try:
            # Ensure directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Get current config
            config_data = self._get_current_config()

            # Write to file
            with open(target_path, "w") as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

            logger.info(f"Configuration saved to {target_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get current configuration status"""
        with self._lock:
            return {
                "environment": "testnet" if self.settings.binance.testnet else "mainnet",
                "trading_mode": self.settings.trading.mode,
                "config_dir": str(self.config_dir),
                "file_watching_enabled": self.enable_file_watching,
                "auto_save_enabled": self.auto_save,
                "history_size": len(self.history.history),
                "callbacks_registered": len(self._change_callbacks),
                "metrics": self.metrics,
                "current_config": self._get_current_config(),
            }

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get configuration change history"""
        return self.history.get_history(limit)

    def register_change_callback(
        self,
        callback: Callable[[str, Any, Any], None],
    ) -> None:
        """
        Register callback for configuration changes.

        Args:
            callback: Function(change_type, subject, details) to call
        """
        self._change_callbacks.append(callback)
        logger.info(f"Registered configuration change callback: {callback.__name__}")

    def _emit_config_changed(
        self,
        change_type: str,
        subject: str,
        details: Any,
    ) -> None:
        """Emit configuration changed event"""
        # Call registered callbacks
        for callback in self._change_callbacks:
            try:
                callback(change_type, subject, details)
            except Exception as e:
                logger.error(f"Error in change callback {callback.__name__}: {e}")

        # Emit EventBus event if available
        if self.event_bus:
            try:
                event = Event(
                    event_type=EventType.CONFIG_UPDATED,
                    data={
                        "change_type": change_type,
                        "subject": subject,
                        "details": details,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    priority=5,  # Medium priority
                )
                # Try to emit event asynchronously if event loop is running
                try:
                    asyncio.get_running_loop()
                    asyncio.create_task(self.event_bus.emit(event))
                except RuntimeError:
                    # No running event loop - skip async emission in sync context
                    pass
            except Exception as e:
                logger.error(f"Failed to emit CONFIG_UPDATED event: {e}")

    def shutdown(self) -> None:
        """Shutdown configuration manager"""
        logger.info("Shutting down ConfigurationManager")

        # Stop file watching
        self._stop_file_watching()

        # Save final state
        if self.auto_save:
            self.save_config()

        logger.info("ConfigurationManager shutdown complete")

    def __repr__(self) -> str:
        env = "testnet" if self.settings.binance.testnet else "mainnet"
        return (
            f"ConfigurationManager("
            f"env={env}, "
            f"watching={self.enable_file_watching}, "
            f"history={len(self.history.history)}"
            f")"
        )
