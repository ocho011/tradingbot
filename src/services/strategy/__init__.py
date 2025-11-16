"""
Trading Strategy Services

This module provides the core trading signal generation and management system.
"""

from src.services.strategy.config_manager import ConfigurationError, StrategyConfigManager
from src.services.strategy.events import (
    SignalEventPublisher,
    SignalEventType,
    get_event_publisher,
    publish_signal_generated,
    publish_signal_rejected,
    publish_signal_validated,
)
from src.services.strategy.generator import (
    SignalGenerator,
    StrategyAGenerator,
    StrategyBGenerator,
    StrategyCGenerator,
)
from src.services.strategy.integration_layer import StrategyIntegrationLayer
from src.services.strategy.signal import Signal, SignalDirection
from src.services.strategy.signal_filter import FilterConfig, SignalFilter
from src.services.strategy.tracker import SignalTracker, get_signal_tracker
from src.services.strategy.validators import SignalValidator, ValidationResult

__all__ = [
    # Core signal classes
    "Signal",
    "SignalDirection",
    # Generators
    "SignalGenerator",
    "StrategyAGenerator",
    "StrategyBGenerator",
    "StrategyCGenerator",
    # Validation
    "SignalValidator",
    "ValidationResult",
    # Events
    "SignalEventPublisher",
    "SignalEventType",
    "get_event_publisher",
    "publish_signal_generated",
    "publish_signal_validated",
    "publish_signal_rejected",
    # Tracking
    "SignalTracker",
    "get_signal_tracker",
    # Filtering
    "SignalFilter",
    "FilterConfig",
    # Integration
    "StrategyIntegrationLayer",
    # Configuration
    "StrategyConfigManager",
    "ConfigurationError",
]
