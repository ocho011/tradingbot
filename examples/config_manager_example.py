"""
Example: Using StrategyConfigManager with Strategy Engine

This example demonstrates how to:
1. Initialize the configuration manager
2. Integrate with StrategyIntegrationLayer
3. Update configurations at runtime
4. Save/load configurations
5. Monitor performance
"""

import logging
from pathlib import Path
from decimal import Decimal

from src.services.strategy import (
    StrategyIntegrationLayer,
    StrategyConfigManager,
    FilterConfig,
)
from src.models.strategy_config import (
    StrategyConfig,
    StrategyParameters,
    FilterConfiguration,
    PriorityConfiguration,
    StrategyType,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_basic_usage():
    """Example 1: Basic configuration manager usage"""
    logger.info("=== Example 1: Basic Configuration Manager Usage ===")

    # Initialize config manager with default configuration
    config_file = Path("data/strategy_config.json")
    manager = StrategyConfigManager(
        config_file=config_file,
        auto_save=True  # Auto-save after successful updates
    )

    # Get initial status
    status = manager.get_strategy_status()
    logger.info(f"Initial status: {status['global_enabled']}")
    logger.info(f"Enabled strategies: {[k for k, v in status['strategies'].items() if v['enabled']]}")

    # Enable/disable strategies
    manager.enable_strategy(StrategyType.STRATEGY_A.value)
    manager.disable_strategy(StrategyType.STRATEGY_B.value)

    # Update strategy parameters
    manager.update_strategy_params(
        StrategyType.STRATEGY_A.value,
        {
            'confidence_threshold': 80.0,
            'min_risk_reward': 3.0,
        }
    )

    # Update filter configuration
    manager.update_filter_config(
        time_window_minutes=10,
        price_threshold_pct=2.0,
    )

    # Update priority configuration
    manager.update_priority_config(
        confidence_weight=0.5,
        strategy_type_weight=0.3,
        market_condition_weight=0.1,
        risk_reward_weight=0.1,
    )

    # Get metrics
    metrics = manager.get_performance_metrics()
    logger.info(f"Configuration updates: {metrics['config_updates']}")
    logger.info(f"Success rate: {metrics['success_rate_pct']:.1f}%")


def example_integration_with_strategy_layer():
    """Example 2: Integration with StrategyIntegrationLayer"""
    logger.info("=== Example 2: Integration with Strategy Engine ===")

    # Create config manager
    manager = StrategyConfigManager()

    # Get current filter config
    filter_config = manager.config.filter_config

    # Create strategy integration layer with config-driven settings
    integration_layer = StrategyIntegrationLayer(
        filter_config=FilterConfig(
            time_window_minutes=filter_config.time_window_minutes,
            price_threshold_pct=float(filter_config.price_threshold_pct),
            max_signals_per_window=filter_config.max_signals_per_window,
        ),
        enable_strategy_a=manager.config.strategies[StrategyType.STRATEGY_A.value].enabled,
        enable_strategy_b=manager.config.strategies[StrategyType.STRATEGY_B.value].enabled,
        enable_strategy_c=manager.config.strategies[StrategyType.STRATEGY_C.value].enabled,
    )

    # Register callback to sync integration layer with config changes
    def sync_integration_layer(change_type, subject, details):
        """Sync integration layer when config changes"""
        if change_type == 'strategy_enabled':
            integration_layer.enable_strategy(subject)
            logger.info(f"Synced: Enabled {subject} in integration layer")
        elif change_type == 'strategy_disabled':
            integration_layer.disable_strategy(subject)
            logger.info(f"Synced: Disabled {subject} in integration layer")
        elif change_type == 'filter_config_updated':
            new_config = details['new']
            integration_layer.update_filter_config(
                time_window_minutes=new_config['time_window_minutes'],
                price_threshold_pct=new_config['price_threshold_pct'],
            )
            logger.info(f"Synced: Updated filter config in integration layer")

    manager.register_change_callback(sync_integration_layer)

    # Now config changes automatically sync to integration layer
    manager.update_strategy_params(
        StrategyType.STRATEGY_A.value,
        {'confidence_threshold': 85.0}
    )

    manager.update_filter_config(time_window_minutes=15)

    # Check integration layer status
    layer_status = integration_layer.get_strategy_status()
    logger.info(f"Integration layer status: {layer_status}")


def example_configuration_persistence():
    """Example 3: Configuration save/load"""
    logger.info("=== Example 3: Configuration Persistence ===")

    config_file = Path("data/my_strategy_config.json")

    # Create and configure
    manager = StrategyConfigManager(config_file=config_file)

    manager.update_strategy_params(
        StrategyType.STRATEGY_A.value,
        {
            'confidence_threshold': 90.0,
            'min_risk_reward': 3.5,
        }
    )

    manager.update_priority_config(
        confidence_weight=0.6,
        strategy_type_weight=0.2,
        market_condition_weight=0.1,
        risk_reward_weight=0.1,
    )

    # Save configuration
    manager.save_config()
    logger.info(f"Configuration saved to {config_file}")

    # Load in new manager instance
    new_manager = StrategyConfigManager(config_file=config_file)
    new_manager.load_config()

    # Verify loaded config
    assert new_manager.config.strategies[StrategyType.STRATEGY_A.value].confidence_threshold == 90.0
    assert new_manager.config.priority_config.confidence_weight == 0.6

    logger.info("Configuration successfully loaded and verified")


def example_global_control():
    """Example 4: Global enable/disable control"""
    logger.info("=== Example 4: Global Control ===")

    manager = StrategyConfigManager()

    # Get enabled strategies
    enabled = manager.config.get_enabled_strategies()
    logger.info(f"Currently enabled strategies: {enabled}")

    # Disable all strategies globally (emergency stop)
    manager.disable_global()
    logger.info("Global disable activated - all strategies stopped")

    # Individual strategies are still marked as enabled, but not effective
    enabled = manager.config.get_enabled_strategies()
    logger.info(f"Enabled strategies (with global disabled): {enabled}")  # Empty list

    # Re-enable globally
    manager.enable_global()
    enabled = manager.config.get_enabled_strategies()
    logger.info(f"Enabled strategies (after global re-enable): {enabled}")


def example_performance_monitoring():
    """Example 5: Performance monitoring"""
    logger.info("=== Example 5: Performance Monitoring ===")

    manager = StrategyConfigManager()

    # Perform various operations
    manager.update_strategy_params(
        StrategyType.STRATEGY_A.value,
        {'confidence_threshold': 75.0}
    )

    manager.update_filter_config(time_window_minutes=8)

    try:
        # This will fail validation
        manager.update_strategy_params(
            StrategyType.STRATEGY_A.value,
            {'confidence_threshold': 150.0}  # Invalid
        )
    except Exception:
        pass

    # Get metrics
    metrics = manager.get_performance_metrics()
    logger.info(f"Total updates: {metrics['config_updates']}")
    logger.info(f"Successful: {metrics['successful_updates']}")
    logger.info(f"Failed: {metrics['failed_updates']}")
    logger.info(f"Rollbacks: {metrics['rollbacks']}")
    logger.info(f"Success rate: {metrics['success_rate_pct']:.1f}%")


def example_custom_configuration():
    """Example 6: Custom configuration creation"""
    logger.info("=== Example 6: Custom Configuration ===")

    # Create custom configuration
    custom_config = StrategyConfig(
        strategies={
            StrategyType.STRATEGY_A.value: StrategyParameters(
                confidence_threshold=85.0,
                min_risk_reward=3.0,
                max_position_size=1.0,
                enabled=True,
            ),
            StrategyType.STRATEGY_B.value: StrategyParameters(
                confidence_threshold=75.0,
                min_risk_reward=2.5,
                max_position_size=1.5,
                enabled=False,  # Start disabled
            ),
            StrategyType.STRATEGY_C.value: StrategyParameters(
                confidence_threshold=80.0,
                min_risk_reward=2.8,
                max_position_size=1.2,
                enabled=True,
            ),
        },
        filter_config=FilterConfiguration(
            time_window_minutes=10,
            price_threshold_pct=1.5,
            max_signals_per_window=5,
        ),
        priority_config=PriorityConfiguration(
            confidence_weight=0.5,
            strategy_type_weight=0.25,
            market_condition_weight=0.15,
            risk_reward_weight=0.1,
        ),
        global_enabled=True,
    )

    # Validate custom config
    custom_config.validate()
    logger.info("Custom configuration validated successfully")

    # Use with manager
    manager = StrategyConfigManager(config=custom_config)
    logger.info(f"Manager initialized with custom config: {manager}")


if __name__ == "__main__":
    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    # Run examples
    example_basic_usage()
    print("\n")

    example_integration_with_strategy_layer()
    print("\n")

    example_configuration_persistence()
    print("\n")

    example_global_control()
    print("\n")

    example_performance_monitoring()
    print("\n")

    example_custom_configuration()
    print("\n")

    logger.info("=== All examples completed successfully ===")
