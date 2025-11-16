"""
Strategy configuration data models.

This module defines configuration structures for managing trading strategies,
including strategy-specific parameters, filter settings, and priority configurations.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict


class StrategyType(str, Enum):
    """Strategy type enumeration"""

    STRATEGY_A = "Strategy_A"  # Conservative
    STRATEGY_B = "Strategy_B"  # Aggressive
    STRATEGY_C = "Strategy_C"  # Hybrid


@dataclass
class StrategyParameters:
    """
    Strategy-specific configuration parameters.

    Attributes:
        confidence_threshold: Minimum confidence level (0-100)
        min_risk_reward: Minimum acceptable risk-reward ratio
        max_position_size: Maximum position size as % of capital
        time_window_minutes: Time window for duplicate detection
        price_threshold_pct: Price threshold for duplicate detection
        enabled: Whether strategy is active
        custom_params: Additional strategy-specific parameters
    """

    confidence_threshold: float = 70.0
    min_risk_reward: float = 2.0
    max_position_size: float = 2.0  # % of capital
    time_window_minutes: int = 5
    price_threshold_pct: float = 1.0
    enabled: bool = True
    custom_params: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> bool:
        """Validate parameter values"""
        if not (0 <= self.confidence_threshold <= 100):
            raise ValueError(f"confidence_threshold must be 0-100, got {self.confidence_threshold}")
        if self.min_risk_reward < 0:
            raise ValueError(f"min_risk_reward must be positive, got {self.min_risk_reward}")
        if not (0 < self.max_position_size <= 100):
            raise ValueError(f"max_position_size must be 0-100%, got {self.max_position_size}")
        if self.time_window_minutes < 0:
            raise ValueError(
                f"time_window_minutes must be positive, got {self.time_window_minutes}"
            )
        if self.price_threshold_pct < 0:
            raise ValueError(
                f"price_threshold_pct must be positive, got {self.price_threshold_pct}"
            )
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyParameters":
        """Create from dictionary"""
        return cls(**data)


@dataclass
class FilterConfiguration:
    """
    Signal filter configuration.

    Attributes:
        time_window_minutes: Time window for duplicate detection
        price_threshold_pct: Price threshold percentage for duplicate detection
        max_signals_per_window: Maximum signals allowed in time window
        enable_position_conflict_check: Check for position conflicts
        enabled: Whether filtering is active
    """

    time_window_minutes: int = 5
    price_threshold_pct: float = 1.0
    max_signals_per_window: int = 3
    enable_position_conflict_check: bool = True
    enabled: bool = True

    def validate(self) -> bool:
        """Validate filter configuration"""
        if self.time_window_minutes < 0:
            raise ValueError(
                f"time_window_minutes must be positive, got {self.time_window_minutes}"
            )
        if self.price_threshold_pct < 0:
            raise ValueError(
                f"price_threshold_pct must be positive, got {self.price_threshold_pct}"
            )
        if self.max_signals_per_window < 1:
            raise ValueError(
                f"max_signals_per_window must be >= 1, got {self.max_signals_per_window}"
            )
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FilterConfiguration":
        """Create from dictionary"""
        return cls(**data)


@dataclass
class PriorityConfiguration:
    """
    Signal priority configuration.

    Attributes:
        confidence_weight: Weight for confidence score (0-1)
        strategy_type_weight: Weight for strategy type (0-1)
        market_condition_weight: Weight for market conditions (0-1)
        risk_reward_weight: Weight for risk-reward ratio (0-1)
        strategy_multipliers: Multipliers per strategy type
        min_confidence_threshold: Minimum confidence for selection
        min_risk_reward_ratio: Minimum R:R for selection
        max_concurrent_signals: Maximum signals in queue
    """

    confidence_weight: float = 0.4
    strategy_type_weight: float = 0.2
    market_condition_weight: float = 0.2
    risk_reward_weight: float = 0.2
    strategy_multipliers: Dict[str, float] = field(
        default_factory=lambda: {
            "Strategy_A": 1.0,
            "Strategy_B": 1.2,
            "Strategy_C": 1.1,
        }
    )
    min_confidence_threshold: float = 60.0
    min_risk_reward_ratio: float = 1.5
    max_concurrent_signals: int = 10

    def validate(self) -> bool:
        """Validate priority configuration"""
        # Check weights sum to ~1.0
        total_weight = (
            self.confidence_weight
            + self.strategy_type_weight
            + self.market_condition_weight
            + self.risk_reward_weight
        )
        if not (0.95 <= total_weight <= 1.05):
            raise ValueError(f"Weights must sum to ~1.0, got {total_weight}")

        # Check individual weights
        for weight_name in [
            "confidence_weight",
            "strategy_type_weight",
            "market_condition_weight",
            "risk_reward_weight",
        ]:
            weight = getattr(self, weight_name)
            if not (0 <= weight <= 1):
                raise ValueError(f"{weight_name} must be 0-1, got {weight}")

        # Check thresholds
        if not (0 <= self.min_confidence_threshold <= 100):
            raise ValueError(
                f"min_confidence_threshold must be 0-100, got {self.min_confidence_threshold}"
            )
        if self.min_risk_reward_ratio < 0:
            raise ValueError(
                f"min_risk_reward_ratio must be positive, got {self.min_risk_reward_ratio}"
            )
        if self.max_concurrent_signals < 1:
            raise ValueError(
                f"max_concurrent_signals must be >= 1, got {self.max_concurrent_signals}"
            )

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PriorityConfiguration":
        """Create from dictionary"""
        return cls(**data)


@dataclass
class StrategyConfig:
    """
    Complete strategy system configuration.

    Combines all configuration aspects for the trading strategy system.

    Attributes:
        strategies: Configuration per strategy type
        filter_config: Signal filtering configuration
        priority_config: Signal priority configuration
        global_enabled: Master enable/disable switch
        version: Configuration version
        created_at: Configuration creation timestamp
        updated_at: Last update timestamp
        metadata: Additional metadata
    """

    strategies: Dict[str, StrategyParameters] = field(
        default_factory=lambda: {
            StrategyType.STRATEGY_A.value: StrategyParameters(
                confidence_threshold=75.0,
                min_risk_reward=2.5,
                max_position_size=1.5,
            ),
            StrategyType.STRATEGY_B.value: StrategyParameters(
                confidence_threshold=65.0,
                min_risk_reward=2.0,
                max_position_size=2.0,
            ),
            StrategyType.STRATEGY_C.value: StrategyParameters(
                confidence_threshold=70.0,
                min_risk_reward=2.2,
                max_position_size=1.8,
            ),
        }
    )
    filter_config: FilterConfiguration = field(default_factory=FilterConfiguration)
    priority_config: PriorityConfiguration = field(default_factory=PriorityConfiguration)
    global_enabled: bool = True
    version: str = "1.0.0"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> bool:
        """Validate entire configuration"""
        # Validate each strategy config
        for strategy_name, params in self.strategies.items():
            try:
                params.validate()
            except ValueError as e:
                raise ValueError(f"Invalid config for {strategy_name}: {e}")

        # Validate filter config
        self.filter_config.validate()

        # Validate priority config
        self.priority_config.validate()

        return True

    def enable_strategy(self, strategy_name: str) -> bool:
        """Enable a specific strategy"""
        if strategy_name not in self.strategies:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        self.strategies[strategy_name].enabled = True
        self.updated_at = datetime.utcnow()
        return True

    def disable_strategy(self, strategy_name: str) -> bool:
        """Disable a specific strategy"""
        if strategy_name not in self.strategies:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        self.strategies[strategy_name].enabled = False
        self.updated_at = datetime.utcnow()
        return True

    def update_strategy_params(self, strategy_name: str, **kwargs) -> bool:
        """Update strategy parameters"""
        if strategy_name not in self.strategies:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        params = self.strategies[strategy_name]
        for key, value in kwargs.items():
            if hasattr(params, key):
                setattr(params, key, value)
            elif key in params.custom_params:
                params.custom_params[key] = value
            else:
                raise ValueError(f"Unknown parameter: {key}")

        # Validate after update
        params.validate()
        self.updated_at = datetime.utcnow()
        return True

    def get_enabled_strategies(self) -> list[str]:
        """Get list of enabled strategy names"""
        return [
            name
            for name, params in self.strategies.items()
            if params.enabled and self.global_enabled
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "strategies": {name: params.to_dict() for name, params in self.strategies.items()},
            "filter_config": self.filter_config.to_dict(),
            "priority_config": self.priority_config.to_dict(),
            "global_enabled": self.global_enabled,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyConfig":
        """Create from dictionary"""
        # Parse strategies
        strategies = {
            name: StrategyParameters.from_dict(params)
            for name, params in data.get("strategies", {}).items()
        }

        # Parse filter config
        filter_config = FilterConfiguration.from_dict(data.get("filter_config", {}))

        # Parse priority config
        priority_config = PriorityConfiguration.from_dict(data.get("priority_config", {}))

        # Parse timestamps
        created_at = (
            datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.utcnow()
        )
        updated_at = (
            datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.utcnow()
        )

        return cls(
            strategies=strategies,
            filter_config=filter_config,
            priority_config=priority_config,
            global_enabled=data.get("global_enabled", True),
            version=data.get("version", "1.0.0"),
            created_at=created_at,
            updated_at=updated_at,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "StrategyConfig":
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        enabled_count = len(self.get_enabled_strategies())
        return (
            f"StrategyConfig(version={self.version}, "
            f"enabled={enabled_count}/{len(self.strategies)}, "
            f"global_enabled={self.global_enabled})"
        )
