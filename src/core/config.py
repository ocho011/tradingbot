"""
Configuration management using Pydantic Settings.
Loads environment variables and provides typed configuration access.
"""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BinanceConfig(BaseSettings):
    """Binance API configuration with separate mainnet/testnet credentials."""

    # Testnet credentials
    testnet_api_key: Optional[str] = Field(None, description="Binance testnet API key")
    testnet_secret_key: Optional[str] = Field(None, description="Binance testnet secret key")

    # Mainnet credentials
    mainnet_api_key: Optional[str] = Field(None, description="Binance mainnet API key")
    mainnet_secret_key: Optional[str] = Field(None, description="Binance mainnet secret key")

    # Legacy fallback (for backward compatibility)
    api_key: Optional[str] = Field(None, description="Legacy API key (fallback)")
    secret_key: Optional[str] = Field(None, description="Legacy secret key (fallback)")

    testnet: bool = Field(True, description="Use Binance testnet")

    model_config = SettingsConfigDict(env_prefix="BINANCE_", env_file=".env", extra="ignore")

    @property
    def active_api_key(self) -> str:
        """Get active API key based on testnet setting."""
        if self.testnet:
            return self.testnet_api_key or self.api_key or ""
        return self.mainnet_api_key or self.api_key or ""

    @property
    def active_secret_key(self) -> str:
        """Get active secret key based on testnet setting."""
        if self.testnet:
            return self.testnet_secret_key or self.secret_key or ""
        return self.mainnet_secret_key or self.secret_key or ""

    def validate_credentials(self) -> None:
        """
        Validate that required credentials are present for the selected environment.

        Raises:
            ValueError: If credentials are missing for the active environment
        """
        env_name = "testnet" if self.testnet else "mainnet"
        if not self.active_api_key or not self.active_secret_key:
            raise ValueError(
                f"Binance {env_name} API credentials not configured. "
                f"Please set BINANCE_{env_name.upper()}_API_KEY and "
                f"BINANCE_{env_name.upper()}_SECRET_KEY in your .env file."
            )


class DiscordConfig(BaseSettings):
    """Discord webhook configuration."""

    webhook_url: Optional[str] = Field(None, description="Discord webhook URL for notifications")

    model_config = SettingsConfigDict(env_prefix="DISCORD_", env_file=".env", extra="ignore")


class TradingConfig(BaseSettings):
    """Trading configuration."""

    mode: str = Field("paper", description="Trading mode: paper or live")
    default_leverage: int = Field(10, description="Default leverage for positions")
    max_position_size_usdt: float = Field(
        1000.0, description="Maximum position size in USDT"
    )
    risk_per_trade_percent: float = Field(
        1.0, description="Risk per trade as percentage of capital"
    )

    model_config = SettingsConfigDict(env_prefix="TRADING_", env_file=".env", extra="ignore")


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    path: str = Field("data/tradingbot.db", description="SQLite database file path")

    model_config = SettingsConfigDict(env_prefix="DATABASE_", env_file=".env", extra="ignore")


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = Field("INFO", description="Logging level")
    file_path: str = Field("logs/tradingbot.log", description="Log file path")
    max_size_mb: int = Field(10, description="Maximum log file size in MB")
    backup_count: int = Field(5, description="Number of backup log files to keep")

    model_config = SettingsConfigDict(env_prefix="LOG_", env_file=".env", extra="ignore")


class APIConfig(BaseSettings):
    """FastAPI server configuration."""

    host: str = Field("0.0.0.0", description="API server host")
    port: int = Field(8000, description="API server port")
    reload: bool = Field(False, description="Enable auto-reload for development")

    model_config = SettingsConfigDict(env_prefix="API_", env_file=".env", extra="ignore")


class ICTConfig(BaseSettings):
    """ICT indicator configuration."""

    fvg_min_size_percent: float = Field(
        0.1, description="Minimum FVG size as percentage of price"
    )
    ob_lookback_periods: int = Field(100, description="Lookback periods for Order Blocks")
    liquidity_sweep_threshold: float = Field(
        0.5, description="Threshold for liquidity sweep detection"
    )

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")


class StrategyConfig(BaseSettings):
    """Strategy enable/disable configuration."""

    enable_strategy_1: bool = Field(True, description="Enable Strategy 1")
    enable_strategy_2: bool = Field(True, description="Enable Strategy 2")
    enable_strategy_3: bool = Field(True, description="Enable Strategy 3")

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")


class Settings:
    """Main settings class that aggregates all configuration sections."""

    def __init__(self):
        self.binance = BinanceConfig()
        self.discord = DiscordConfig()
        self.trading = TradingConfig()
        self.database = DatabaseConfig()
        self.logging = LoggingConfig()
        self.api = APIConfig()
        self.ict = ICTConfig()
        self.strategy = StrategyConfig()

    def __repr__(self) -> str:
        return (
            f"Settings(\n"
            f"  binance=BinanceConfig(testnet={self.binance.testnet}),\n"
            f"  trading=TradingConfig(mode={self.trading.mode}),\n"
            f"  database=DatabaseConfig(path={self.database.path}),\n"
            f"  logging=LoggingConfig(level={self.logging.level})\n"
            f")"
        )


# Global settings instance
settings = Settings()
