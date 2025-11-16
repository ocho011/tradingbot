"""
Unit tests for configuration module.
"""

from src.core.config import (
    BinanceConfig,
    DatabaseConfig,
    LoggingConfig,
    Settings,
    TradingConfig,
)


class TestSettings:
    """Test suite for Settings class."""

    def test_settings_initialization(self):
        """Test that Settings initializes all config sections."""
        settings = Settings()
        assert hasattr(settings, "binance")
        assert hasattr(settings, "trading")
        assert hasattr(settings, "database")
        assert hasattr(settings, "logging")
        assert hasattr(settings, "api")
        assert hasattr(settings, "ict")
        assert hasattr(settings, "strategy")

    def test_settings_repr(self):
        """Test Settings string representation."""
        settings = Settings()
        repr_str = repr(settings)
        assert "Settings(" in repr_str
        assert "binance=" in repr_str
        assert "trading=" in repr_str


class TestBinanceConfig:
    """Test suite for BinanceConfig."""

    def test_binance_config_has_required_fields(self):
        """Test that BinanceConfig has all required fields."""
        # This will use environment variables or defaults
        config = BinanceConfig(api_key="test_key", secret_key="test_secret", testnet=True)
        assert config.api_key == "test_key"
        assert config.secret_key == "test_secret"
        assert config.testnet is True


class TestTradingConfig:
    """Test suite for TradingConfig."""

    def test_trading_config_defaults(self):
        """Test TradingConfig default values."""
        config = TradingConfig()
        assert config.mode == "paper"
        assert config.default_leverage == 10
        assert config.max_position_size_usdt == 1000.0
        assert config.risk_per_trade_percent == 1.0


class TestDatabaseConfig:
    """Test suite for DatabaseConfig."""

    def test_database_config_default_path(self):
        """Test DatabaseConfig default path."""
        config = DatabaseConfig()
        assert config.path == "data/tradingbot.db"


class TestLoggingConfig:
    """Test suite for LoggingConfig."""

    def test_logging_config_defaults(self):
        """Test LoggingConfig default values."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.file_path == "logs/tradingbot.log"
        assert config.max_size_mb == 10
        assert config.backup_count == 5
