"""
Tests for Strategy Configuration Manager.

Tests cover:
- Configuration initialization and validation
- Strategy enable/disable operations
- Runtime parameter updates
- Configuration persistence (save/load)
- Rollback mechanisms
- Thread safety
- Performance monitoring
"""

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

from src.models.strategy_config import (
    FilterConfiguration,
    PriorityConfiguration,
    StrategyConfig,
    StrategyParameters,
    StrategyType,
)
from src.services.strategy.config_manager import (
    ConfigurationError,
    StrategyConfigManager,
)


class TestStrategyConfigManager:
    """Test suite for StrategyConfigManager"""

    @pytest.fixture
    def temp_config_file(self):
        """Create temporary config file for testing"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = Path(f.name)
        yield temp_path
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()

    @pytest.fixture
    def config_manager(self, temp_config_file):
        """Create config manager with default configuration"""
        return StrategyConfigManager(
            config_file=temp_config_file, auto_save=False  # Disable auto-save for most tests
        )

    @pytest.fixture
    def custom_config(self):
        """Create custom configuration for testing"""
        return StrategyConfig(
            strategies={
                StrategyType.STRATEGY_A.value: StrategyParameters(
                    confidence_threshold=80.0,
                    min_risk_reward=3.0,
                    enabled=True,
                ),
                StrategyType.STRATEGY_B.value: StrategyParameters(
                    confidence_threshold=70.0,
                    min_risk_reward=2.5,
                    enabled=False,
                ),
            },
            global_enabled=True,
        )

    def test_initialization_default_config(self):
        """Test initialization with default configuration"""
        manager = StrategyConfigManager()

        assert manager.config is not None
        assert len(manager.config.strategies) == 3
        assert manager.config.global_enabled is True
        assert manager.metrics["config_updates"] == 0

    def test_initialization_custom_config(self, custom_config, temp_config_file):
        """Test initialization with custom configuration"""
        manager = StrategyConfigManager(
            config=custom_config,
            config_file=temp_config_file,
        )

        assert len(manager.config.strategies) == 2
        assert manager.config.strategies[StrategyType.STRATEGY_A.value].confidence_threshold == 80.0
        assert manager.config.strategies[StrategyType.STRATEGY_B.value].enabled is False

    def test_enable_strategy_success(self, config_manager):
        """Test successful strategy enable"""
        strategy_name = StrategyType.STRATEGY_A.value

        # Disable first
        config_manager.config.disable_strategy(strategy_name)
        assert config_manager.config.strategies[strategy_name].enabled is False

        # Enable
        result = config_manager.enable_strategy(strategy_name)

        assert result is True
        assert config_manager.config.strategies[strategy_name].enabled is True
        assert config_manager.metrics["successful_updates"] == 1

    def test_enable_strategy_unknown_strategy(self, config_manager):
        """Test enabling unknown strategy raises error"""
        with pytest.raises(ConfigurationError):
            config_manager.enable_strategy("Unknown_Strategy")

    def test_disable_strategy_success(self, config_manager):
        """Test successful strategy disable"""
        strategy_name = StrategyType.STRATEGY_A.value

        # Ensure enabled first
        config_manager.config.enable_strategy(strategy_name)
        assert config_manager.config.strategies[strategy_name].enabled is True

        # Disable
        result = config_manager.disable_strategy(strategy_name)

        assert result is True
        assert config_manager.config.strategies[strategy_name].enabled is False
        assert config_manager.metrics["successful_updates"] == 1

    def test_update_strategy_params_success(self, config_manager):
        """Test successful parameter update"""
        strategy_name = StrategyType.STRATEGY_A.value
        updates = {
            "confidence_threshold": 85.0,
            "min_risk_reward": 3.5,
        }

        result = config_manager.update_strategy_params(strategy_name, updates)

        assert result is True
        assert config_manager.config.strategies[strategy_name].confidence_threshold == 85.0
        assert config_manager.config.strategies[strategy_name].min_risk_reward == 3.5
        assert config_manager.metrics["successful_updates"] == 1

    def test_update_strategy_params_invalid_value(self, config_manager):
        """Test parameter update with invalid value"""
        strategy_name = StrategyType.STRATEGY_A.value
        updates = {
            "confidence_threshold": 150.0,  # Invalid: > 100
        }

        with pytest.raises(ConfigurationError):
            config_manager.update_strategy_params(strategy_name, updates)

        # Verify rollback occurred
        assert config_manager.config.strategies[strategy_name].confidence_threshold != 150.0
        assert config_manager.metrics["failed_updates"] == 1
        assert config_manager.metrics["rollbacks"] == 1

    def test_update_filter_config_success(self, config_manager):
        """Test successful filter configuration update"""
        updates = {
            "time_window_minutes": 10,
            "price_threshold_pct": 2.0,
        }

        result = config_manager.update_filter_config(**updates)

        assert result is True
        assert config_manager.config.filter_config.time_window_minutes == 10
        assert config_manager.config.filter_config.price_threshold_pct == 2.0
        assert config_manager.metrics["successful_updates"] == 1

    def test_update_filter_config_invalid_param(self, config_manager):
        """Test filter config update with invalid parameter"""
        with pytest.raises(ConfigurationError):
            config_manager.update_filter_config(unknown_param=123)

        assert config_manager.metrics["failed_updates"] == 1

    def test_update_priority_config_success(self, config_manager):
        """Test successful priority configuration update"""
        # Update all weights to maintain sum = 1.0
        updates = {
            "confidence_weight": 0.5,
            "strategy_type_weight": 0.3,
            "market_condition_weight": 0.1,
            "risk_reward_weight": 0.1,
        }

        result = config_manager.update_priority_config(**updates)

        assert result is True
        assert config_manager.config.priority_config.confidence_weight == 0.5
        assert config_manager.config.priority_config.strategy_type_weight == 0.3
        assert config_manager.metrics["successful_updates"] == 1

    def test_update_priority_config_invalid_weights(self, config_manager):
        """Test priority config with invalid weight sum"""
        updates = {
            "confidence_weight": 0.9,  # Total weights will be > 1
            "strategy_type_weight": 0.9,
        }

        with pytest.raises(ConfigurationError):
            config_manager.update_priority_config(**updates)

        assert config_manager.metrics["failed_updates"] == 1
        assert config_manager.metrics["rollbacks"] == 1

    def test_global_enable_disable(self, config_manager):
        """Test global enable/disable functionality"""
        # Test disable
        result = config_manager.disable_global()
        assert result is True
        assert config_manager.config.global_enabled is False

        # Test enable
        result = config_manager.enable_global()
        assert result is True
        assert config_manager.config.global_enabled is True

    def test_save_config_success(self, config_manager, temp_config_file):
        """Test successful configuration save"""
        # Make some changes
        config_manager.enable_strategy(StrategyType.STRATEGY_A.value)
        config_manager.update_strategy_params(
            StrategyType.STRATEGY_A.value, {"confidence_threshold": 90.0}
        )

        # Save
        result = config_manager.save_config()

        assert result is True
        assert temp_config_file.exists()
        assert config_manager.metrics["saves"] == 1

        # Verify file content
        with open(temp_config_file, "r") as f:
            saved_data = json.load(f)

        assert saved_data["strategies"][StrategyType.STRATEGY_A.value]["enabled"] is True
        assert (
            saved_data["strategies"][StrategyType.STRATEGY_A.value]["confidence_threshold"] == 90.0
        )

    def test_save_config_no_filepath(self):
        """Test save without filepath raises error"""
        manager = StrategyConfigManager(config_file=None)

        with pytest.raises(ConfigurationError):
            manager.save_config()

    def test_load_config_success(self, config_manager, temp_config_file):
        """Test successful configuration load"""
        # Create and save a config
        config_manager.update_strategy_params(
            StrategyType.STRATEGY_A.value, {"confidence_threshold": 95.0}
        )
        config_manager.save_config()

        # Create new manager and load
        new_manager = StrategyConfigManager(config_file=temp_config_file)
        result = new_manager.load_config()

        assert result is True
        assert (
            new_manager.config.strategies[StrategyType.STRATEGY_A.value].confidence_threshold
            == 95.0
        )
        assert new_manager.metrics["loads"] == 1

    def test_load_config_file_not_found(self, config_manager):
        """Test load from non-existent file raises error"""
        non_existent = Path("/tmp/non_existent_config_12345.json")

        with pytest.raises(ConfigurationError):
            config_manager.load_config(non_existent)

    def test_load_config_invalid_json(self, config_manager, temp_config_file):
        """Test load from invalid JSON raises error"""
        # Write invalid JSON
        with open(temp_config_file, "w") as f:
            f.write("{ invalid json }")

        with pytest.raises(ConfigurationError):
            config_manager.load_config()

        # Verify rollback occurred
        assert config_manager.metrics["rollbacks"] == 1

    def test_get_strategy_status(self, config_manager):
        """Test getting strategy status"""
        status = config_manager.get_strategy_status()

        assert "global_enabled" in status
        assert "strategies" in status
        assert "filter_config" in status
        assert "priority_config" in status
        assert len(status["strategies"]) == 3

        # Check strategy details
        strategy_a = status["strategies"][StrategyType.STRATEGY_A.value]
        assert "enabled" in strategy_a
        assert "effective_enabled" in strategy_a
        assert "confidence_threshold" in strategy_a

    def test_get_performance_metrics(self, config_manager):
        """Test getting performance metrics"""
        # Perform some operations
        config_manager.enable_strategy(StrategyType.STRATEGY_A.value)
        config_manager.update_filter_config(time_window_minutes=10)

        metrics = config_manager.get_performance_metrics()

        assert metrics["config_updates"] == 2
        assert metrics["successful_updates"] == 2
        assert metrics["failed_updates"] == 0
        assert "success_rate_pct" in metrics
        assert metrics["success_rate_pct"] == 100.0

    def test_change_callback_registration(self, config_manager):
        """Test registering and calling change callbacks"""
        callback_invocations = []

        def test_callback(change_type, subject, details):
            callback_invocations.append(
                {
                    "change_type": change_type,
                    "subject": subject,
                    "details": details,
                }
            )

        # Register callback
        config_manager.register_change_callback(test_callback)

        # Make a change
        config_manager.enable_strategy(StrategyType.STRATEGY_A.value)

        # Verify callback was called
        assert len(callback_invocations) == 1
        assert callback_invocations[0]["change_type"] == "strategy_enabled"
        assert callback_invocations[0]["subject"] == StrategyType.STRATEGY_A.value

    def test_auto_save_on_update(self, temp_config_file):
        """Test auto-save functionality"""
        manager = StrategyConfigManager(config_file=temp_config_file, auto_save=True)

        # Make a change
        manager.update_strategy_params(
            StrategyType.STRATEGY_A.value, {"confidence_threshold": 88.0}
        )

        # Verify file was saved
        assert temp_config_file.exists()
        assert manager.metrics["saves"] == 1

    def test_thread_safety(self, config_manager):
        """Test thread-safe configuration updates"""
        num_threads = 10
        updates_per_thread = 5
        threads = []
        errors = []

        def update_config(strategy_idx):
            try:
                for _ in range(updates_per_thread):
                    strategy_name = StrategyType.STRATEGY_A.value
                    config_manager.update_strategy_params(
                        strategy_name, {"confidence_threshold": 70.0 + strategy_idx}
                    )
                    time.sleep(0.001)  # Small delay
            except Exception as e:
                errors.append(e)

        # Create and start threads
        for i in range(num_threads):
            t = threading.Thread(target=update_config, args=(i,))
            threads.append(t)
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Verify no errors occurred
        assert len(errors) == 0
        assert config_manager.metrics["successful_updates"] == num_threads * updates_per_thread

    def test_config_history_rollback(self, config_manager):
        """Test configuration history and rollback"""
        strategy_name = StrategyType.STRATEGY_A.value

        # Save initial state
        config_manager.config.strategies[strategy_name].confidence_threshold

        # Make some updates
        config_manager.update_strategy_params(strategy_name, {"confidence_threshold": 80.0})
        config_manager.update_strategy_params(strategy_name, {"confidence_threshold": 85.0})

        # Force an invalid update to trigger rollback
        try:
            config_manager.update_strategy_params(strategy_name, {"confidence_threshold": 150.0})
        except ConfigurationError:
            pass

        # Verify rollback occurred (should be at 85.0, not 150.0)
        assert config_manager.config.strategies[strategy_name].confidence_threshold == 85.0
        assert config_manager.metrics["rollbacks"] == 1

    def test_max_history_limit(self, config_manager):
        """Test configuration history size limit"""
        strategy_name = StrategyType.STRATEGY_A.value

        # Make more updates than max_history (default 10)
        for i in range(15):
            config_manager.update_strategy_params(strategy_name, {"confidence_threshold": 70.0 + i})

        # Verify history is limited
        assert len(config_manager._config_history) <= config_manager._max_history

    def test_repr(self, config_manager):
        """Test string representation"""
        repr_str = repr(config_manager)

        assert "StrategyConfigManager" in repr_str
        assert "enabled=" in repr_str
        assert "global_enabled=" in repr_str
        assert "updates=" in repr_str


class TestStrategyConfig:
    """Test suite for StrategyConfig model"""

    def test_default_initialization(self):
        """Test default configuration initialization"""
        config = StrategyConfig()

        assert len(config.strategies) == 3
        assert config.global_enabled is True
        assert config.version == "1.0.0"
        assert isinstance(config.filter_config, FilterConfiguration)
        assert isinstance(config.priority_config, PriorityConfiguration)

    def test_to_dict_from_dict_roundtrip(self):
        """Test serialization roundtrip"""
        config = StrategyConfig()

        # Convert to dict and back
        config_dict = config.to_dict()
        restored_config = StrategyConfig.from_dict(config_dict)

        # Verify equality
        assert config.global_enabled == restored_config.global_enabled
        assert config.version == restored_config.version
        assert len(config.strategies) == len(restored_config.strategies)

    def test_to_json_from_json_roundtrip(self):
        """Test JSON serialization roundtrip"""
        config = StrategyConfig()

        # Convert to JSON and back
        json_str = config.to_json()
        restored_config = StrategyConfig.from_json(json_str)

        # Verify equality
        assert config.global_enabled == restored_config.global_enabled
        assert len(config.strategies) == len(restored_config.strategies)

    def test_validation_success(self):
        """Test successful configuration validation"""
        config = StrategyConfig()
        result = config.validate()
        assert result is True

    def test_validation_failure_invalid_strategy_param(self):
        """Test validation fails with invalid strategy parameter"""
        config = StrategyConfig()
        config.strategies[StrategyType.STRATEGY_A.value].confidence_threshold = 150.0

        with pytest.raises(ValueError, match="confidence_threshold must be 0-100"):
            config.validate()

    def test_get_enabled_strategies(self):
        """Test getting list of enabled strategies"""
        config = StrategyConfig()

        # All should be enabled by default
        enabled = config.get_enabled_strategies()
        assert len(enabled) == 3

        # Disable one
        config.disable_strategy(StrategyType.STRATEGY_A.value)
        enabled = config.get_enabled_strategies()
        assert len(enabled) == 2
        assert StrategyType.STRATEGY_A.value not in enabled

        # Disable globally
        config.global_enabled = False
        enabled = config.get_enabled_strategies()
        assert len(enabled) == 0
