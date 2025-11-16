"""
Strategy Configuration Manager.

Manages runtime configuration for trading strategies, including:
- Strategy enable/disable control
- Parameter adjustments
- Configuration persistence (save/load)
- Performance monitoring integration
- Thread-safe configuration updates
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, Optional

from src.models.strategy_config import (
    StrategyConfig,
)

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Configuration-related errors"""



class StrategyConfigManager:
    """
    Manages strategy configuration with thread-safe runtime updates.

    Features:
    - Enable/disable strategies individually or globally
    - Update strategy parameters at runtime
    - Configuration validation before applying
    - Persistence (save/load) to JSON files
    - Rollback mechanism for failed updates
    - Performance metrics tracking
    - Configuration change notifications via callbacks
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        config_file: Optional[Path] = None,
        auto_save: bool = True,
    ):
        """
        Initialize configuration manager.

        Args:
            config: Initial configuration (creates default if None)
            config_file: Path for configuration persistence
            auto_save: Automatically save after successful updates
        """
        self.config = config or StrategyConfig()
        self.config_file = config_file
        self.auto_save = auto_save

        # Thread safety
        self._lock = Lock()

        # Configuration history for rollback
        self._config_history: list[StrategyConfig] = []
        self._max_history = 10

        # Change callbacks
        self._change_callbacks: list[Callable[[str, Any, Any], None]] = []

        # Performance metrics
        self.metrics = {
            "config_updates": 0,
            "successful_updates": 0,
            "failed_updates": 0,
            "rollbacks": 0,
            "saves": 0,
            "loads": 0,
        }

        # Validate initial config
        try:
            self.config.validate()
            logger.info(f"StrategyConfigManager initialized: {self.config}")
        except Exception as e:
            logger.error(f"Invalid initial configuration: {e}")
            raise ConfigurationError(f"Invalid initial configuration: {e}")

    def enable_strategy(self, strategy_name: str) -> bool:
        """
        Enable a specific strategy.

        Args:
            strategy_name: Name of strategy (e.g., 'Strategy_A')

        Returns:
            True if successful

        Raises:
            ConfigurationError: If strategy doesn't exist or update fails
        """
        with self._lock:
            try:
                # Save current config for rollback
                self._save_to_history()

                # Update config
                old_value = self.config.strategies[strategy_name].enabled
                self.config.enable_strategy(strategy_name)

                # Validate
                self.config.validate()

                # Track metrics
                self.metrics["config_updates"] += 1
                self.metrics["successful_updates"] += 1

                # Notify callbacks
                self._notify_change("strategy_enabled", strategy_name, old_value)

                # Auto-save
                if self.auto_save and self.config_file:
                    self.save_config()

                logger.info(f"Strategy {strategy_name} enabled")
                return True

            except Exception as e:
                self.metrics["failed_updates"] += 1
                logger.error(f"Failed to enable strategy {strategy_name}: {e}")
                raise ConfigurationError(f"Failed to enable strategy: {e}")

    def disable_strategy(self, strategy_name: str) -> bool:
        """
        Disable a specific strategy.

        Args:
            strategy_name: Name of strategy (e.g., 'Strategy_A')

        Returns:
            True if successful

        Raises:
            ConfigurationError: If strategy doesn't exist or update fails
        """
        with self._lock:
            try:
                # Save current config for rollback
                self._save_to_history()

                # Update config
                old_value = self.config.strategies[strategy_name].enabled
                self.config.disable_strategy(strategy_name)

                # Validate
                self.config.validate()

                # Track metrics
                self.metrics["config_updates"] += 1
                self.metrics["successful_updates"] += 1

                # Notify callbacks
                self._notify_change("strategy_disabled", strategy_name, old_value)

                # Auto-save
                if self.auto_save and self.config_file:
                    self.save_config()

                logger.info(f"Strategy {strategy_name} disabled")
                return True

            except Exception as e:
                self.metrics["failed_updates"] += 1
                logger.error(f"Failed to disable strategy {strategy_name}: {e}")
                raise ConfigurationError(f"Failed to disable strategy: {e}")

    def update_strategy_params(
        self,
        strategy_name: str,
        params: Dict[str, Any],
        validate_first: bool = True,
    ) -> bool:
        """
        Update strategy parameters at runtime.

        Args:
            strategy_name: Strategy to update
            params: Parameter updates (e.g., {'confidence_threshold': 80.0})
            validate_first: Validate before applying (recommended)

        Returns:
            True if successful

        Raises:
            ConfigurationError: If validation fails or update fails
        """
        with self._lock:
            try:
                # Save current config for rollback
                self._save_to_history()

                # Get old values for notification
                old_params = self.config.strategies[strategy_name].to_dict()

                # Apply updates
                self.config.update_strategy_params(strategy_name, **params)

                # Validate if requested
                if validate_first:
                    self.config.validate()

                # Track metrics
                self.metrics["config_updates"] += 1
                self.metrics["successful_updates"] += 1

                # Notify callbacks
                self._notify_change(
                    "strategy_params_updated",
                    strategy_name,
                    {
                        "old": old_params,
                        "new": self.config.strategies[strategy_name].to_dict(),
                        "changed": params,
                    },
                )

                # Auto-save
                if self.auto_save and self.config_file:
                    self.save_config()

                logger.info(f"Updated params for {strategy_name}: {params}")
                return True

            except Exception as e:
                self.metrics["failed_updates"] += 1
                logger.error(f"Failed to update strategy params: {e}")
                # Rollback on failure
                self._rollback_from_history()
                raise ConfigurationError(f"Failed to update strategy params: {e}")

    def update_filter_config(self, **kwargs) -> bool:
        """
        Update signal filter configuration.

        Args:
            **kwargs: Filter configuration parameters

        Returns:
            True if successful

        Raises:
            ConfigurationError: If validation fails
        """
        with self._lock:
            try:
                # Save current config for rollback
                self._save_to_history()

                # Get old config
                old_config = self.config.filter_config.to_dict()

                # Apply updates
                for key, value in kwargs.items():
                    if hasattr(self.config.filter_config, key):
                        setattr(self.config.filter_config, key, value)
                    else:
                        raise ValueError(f"Unknown filter parameter: {key}")

                # Validate
                self.config.filter_config.validate()
                self.config.updated_at = datetime.utcnow()

                # Track metrics
                self.metrics["config_updates"] += 1
                self.metrics["successful_updates"] += 1

                # Notify callbacks
                self._notify_change(
                    "filter_config_updated",
                    "filter",
                    {
                        "old": old_config,
                        "new": self.config.filter_config.to_dict(),
                        "changed": kwargs,
                    },
                )

                # Auto-save
                if self.auto_save and self.config_file:
                    self.save_config()

                logger.info(f"Updated filter config: {kwargs}")
                return True

            except Exception as e:
                self.metrics["failed_updates"] += 1
                logger.error(f"Failed to update filter config: {e}")
                self._rollback_from_history()
                raise ConfigurationError(f"Failed to update filter config: {e}")

    def update_priority_config(self, **kwargs) -> bool:
        """
        Update signal priority configuration.

        Args:
            **kwargs: Priority configuration parameters

        Returns:
            True if successful

        Raises:
            ConfigurationError: If validation fails
        """
        with self._lock:
            try:
                # Save current config for rollback
                self._save_to_history()

                # Get old config
                old_config = self.config.priority_config.to_dict()

                # Apply updates
                for key, value in kwargs.items():
                    if hasattr(self.config.priority_config, key):
                        setattr(self.config.priority_config, key, value)
                    else:
                        raise ValueError(f"Unknown priority parameter: {key}")

                # Validate
                self.config.priority_config.validate()
                self.config.updated_at = datetime.utcnow()

                # Track metrics
                self.metrics["config_updates"] += 1
                self.metrics["successful_updates"] += 1

                # Notify callbacks
                self._notify_change(
                    "priority_config_updated",
                    "priority",
                    {
                        "old": old_config,
                        "new": self.config.priority_config.to_dict(),
                        "changed": kwargs,
                    },
                )

                # Auto-save
                if self.auto_save and self.config_file:
                    self.save_config()

                logger.info(f"Updated priority config: {kwargs}")
                return True

            except Exception as e:
                self.metrics["failed_updates"] += 1
                logger.error(f"Failed to update priority config: {e}")
                self._rollback_from_history()
                raise ConfigurationError(f"Failed to update priority config: {e}")

    def enable_global(self) -> bool:
        """Enable all strategies globally"""
        with self._lock:
            old_value = self.config.global_enabled
            self.config.global_enabled = True
            self.config.updated_at = datetime.utcnow()
            self._notify_change("global_enabled", "all", old_value)
            if self.auto_save and self.config_file:
                self.save_config()
            logger.info("Global strategy enable activated")
            return True

    def disable_global(self) -> bool:
        """Disable all strategies globally"""
        with self._lock:
            old_value = self.config.global_enabled
            self.config.global_enabled = False
            self.config.updated_at = datetime.utcnow()
            self._notify_change("global_disabled", "all", old_value)
            if self.auto_save and self.config_file:
                self.save_config()
            logger.warning("Global strategy disable activated - all strategies stopped")
            return True

    def save_config(self, filepath: Optional[Path] = None) -> bool:
        """
        Save configuration to JSON file.

        Args:
            filepath: Target file path (uses self.config_file if None)

        Returns:
            True if successful

        Raises:
            ConfigurationError: If save fails
        """
        target_path = filepath or self.config_file
        if not target_path:
            raise ConfigurationError("No config file path specified")

        try:
            # Ensure directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Write config
            with open(target_path, "w") as f:
                f.write(self.config.to_json(indent=2))

            self.metrics["saves"] += 1
            logger.info(f"Configuration saved to {target_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            raise ConfigurationError(f"Failed to save configuration: {e}")

    def load_config(self, filepath: Optional[Path] = None) -> bool:
        """
        Load configuration from JSON file.

        Args:
            filepath: Source file path (uses self.config_file if None)

        Returns:
            True if successful

        Raises:
            ConfigurationError: If load fails or validation fails
        """
        source_path = filepath or self.config_file
        if not source_path:
            raise ConfigurationError("No config file path specified")

        if not source_path.exists():
            raise ConfigurationError(f"Config file not found: {source_path}")

        with self._lock:
            try:
                # Save current config for rollback
                self._save_to_history()

                # Load from file
                with open(source_path, "r") as f:
                    config_data = json.load(f)

                # Parse and validate
                new_config = StrategyConfig.from_dict(config_data)
                new_config.validate()

                # Apply new config
                self.config = new_config

                self.metrics["loads"] += 1
                logger.info(f"Configuration loaded from {source_path}")
                return True

            except Exception as e:
                logger.error(f"Failed to load configuration: {e}")
                self._rollback_from_history()
                raise ConfigurationError(f"Failed to load configuration: {e}")

    def get_strategy_status(self) -> Dict[str, Any]:
        """
        Get current status of all strategies.

        Returns:
            Dictionary with strategy status and configuration
        """
        with self._lock:
            return {
                "global_enabled": self.config.global_enabled,
                "strategies": {
                    name: {
                        "enabled": params.enabled,
                        "effective_enabled": params.enabled and self.config.global_enabled,
                        "confidence_threshold": params.confidence_threshold,
                        "min_risk_reward": params.min_risk_reward,
                        "max_position_size": params.max_position_size,
                    }
                    for name, params in self.config.strategies.items()
                },
                "filter_config": self.config.filter_config.to_dict(),
                "priority_config": self.config.priority_config.to_dict(),
                "version": self.config.version,
                "updated_at": self.config.updated_at.isoformat(),
            }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get configuration manager performance metrics"""
        with self._lock:
            success_rate = (
                self.metrics["successful_updates"] / self.metrics["config_updates"] * 100
                if self.metrics["config_updates"] > 0
                else 0.0
            )

            return {
                **self.metrics,
                "success_rate_pct": success_rate,
                "config_history_size": len(self._config_history),
                "callbacks_registered": len(self._change_callbacks),
            }

    def register_change_callback(
        self,
        callback: Callable[[str, Any, Any], None],
    ) -> None:
        """
        Register callback for configuration changes.

        Args:
            callback: Function(change_type, subject, details) to call on changes
        """
        self._change_callbacks.append(callback)
        logger.info(f"Registered configuration change callback: {callback.__name__}")

    def _save_to_history(self) -> None:
        """Save current config to history for rollback"""
        # Deep copy current config
        config_copy = StrategyConfig.from_dict(self.config.to_dict())
        self._config_history.append(config_copy)

        # Limit history size
        if len(self._config_history) > self._max_history:
            self._config_history.pop(0)

    def _rollback_from_history(self) -> bool:
        """Rollback to previous configuration"""
        if not self._config_history:
            logger.warning("No configuration history available for rollback")
            return False

        self.config = self._config_history.pop()
        self.metrics["rollbacks"] += 1
        logger.info("Configuration rolled back to previous state")
        return True

    def _notify_change(
        self,
        change_type: str,
        subject: Any,
        details: Any,
    ) -> None:
        """Notify all registered callbacks of configuration change"""
        for callback in self._change_callbacks:
            try:
                callback(change_type, subject, details)
            except Exception as e:
                logger.error(f"Error in change callback {callback.__name__}: {e}")

    def __repr__(self) -> str:
        enabled_count = len(self.config.get_enabled_strategies())
        return (
            f"StrategyConfigManager("
            f"enabled={enabled_count}/{len(self.config.strategies)}, "
            f"global_enabled={self.config.global_enabled}, "
            f"updates={self.metrics['successful_updates']}"
            f")"
        )
