"""
Main entry point for the trading bot.
Usage: python -m src
"""

import sys
import asyncio
from src.core.config import settings


async def main() -> None:
    """Main entry point for the trading bot."""
    print("=" * 60)
    print("🚀 Trading Bot - ICT Strategy Automated Trading System")
    print("=" * 60)
    print()
    print(f"📊 Trading Mode: {settings.trading.mode.upper()}")
    print(f"🔧 Using Binance {'Testnet' if settings.binance.testnet else 'Live'}")
    print(f"📝 Log Level: {settings.logging.level}")
    print(f"💾 Database: {settings.database.path}")
    print()
    print("⚠️  Trading bot implementation is in progress...")
    print("    This is the basic project setup.")
    print()
    print("=" * 60)


def run() -> None:
    """Run the trading bot."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Trading bot stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()
