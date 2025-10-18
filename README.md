# Trading Bot - ICT Strategy Automated Trading System

Cryptocurrency automated trading bot implementing ICT (Inner Circle Trader) strategies with real-time market data processing and risk management.

## 🎯 Features

### Core Functionality
- **Real-time Market Data**: WebSocket-based live candle data from Binance
- **ICT Indicators**: Implementation of Order Blocks, Fair Value Gaps, Liquidity Sweeps
- **Automated Strategies**: 3 ICT-based trading strategies with customizable parameters
- **Risk Management**: Position sizing, stop-loss, take-profit automation
- **Event-Driven Architecture**: Asynchronous event system for scalable processing

### Technical Highlights
- **Async/Await**: Non-blocking I/O for efficient resource usage
- **FastAPI**: RESTful API for monitoring and control
- **SQLite**: Persistent storage for candles, trades, and analytics
- **Discord Integration**: Real-time notifications and alerts
- **Paper Trading**: Safe testing environment before live deployment

## 📋 Prerequisites

- Python 3.9 or higher
- Binance API account (testnet or live)
- Discord webhook (optional, for notifications)

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/ocho011/tradingbot.git
cd tradingbot
```

### 2. Create and activate virtual environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -e ".[dev]"
```

### 4. Configure environment variables
```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

## ⚙️ Configuration

Edit `.env` file with your settings:

```bash
# Binance API
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key
BINANCE_TESTNET=true  # Use testnet for testing

# Trading Configuration
TRADING_MODE=paper  # paper or live
DEFAULT_LEVERAGE=10
MAX_POSITION_SIZE_USDT=1000
RISK_PER_TRADE_PERCENT=1.0

# Discord Notifications (optional)
DISCORD_WEBHOOK_URL=your_webhook_url
```

## 🏃 Usage

### Start the trading bot
```bash
python -m src.main
```

### Run tests
```bash
pytest tests/
```

### Run with coverage
```bash
pytest --cov=src tests/
```

### Code formatting
```bash
black src/ tests/
isort src/ tests/
```

### Type checking
```bash
mypy src/
```

## 📁 Project Structure

```
tradingbot/
├── src/                    # Source code
│   ├── core/              # Core functionality
│   ├── api/               # Binance API integration
│   ├── indicators/        # ICT indicators
│   ├── strategies/        # Trading strategies
│   ├── database/          # Data persistence
│   └── utils/             # Utility functions
├── tests/                 # Test suite
│   ├── unit/             # Unit tests
│   └── integration/      # Integration tests
├── config/               # Configuration files
├── logs/                 # Log files
├── data/                 # Database files
├── pyproject.toml       # Project configuration
└── README.md            # This file
```

## 🎓 ICT Strategies Implemented

### Strategy 1: Order Block + FVG Entry
- Identifies bullish/bearish order blocks
- Waits for FVG formation in direction of trend
- Enters on retracement to order block with FVG confluence

### Strategy 2: Liquidity Sweep Reversal
- Detects liquidity sweep above/below key levels
- Confirms market structure shift
- Enters on first pullback after sweep

### Strategy 3: Market Structure Break + OB
- Identifies market structure breaks
- Waits for formation of order block
- Enters on retest of broken structure with OB support

## ⚠️ Risk Disclaimer

**IMPORTANT**: This bot is for educational purposes. Cryptocurrency trading involves substantial risk of loss. Never trade with money you cannot afford to lose. Always test strategies thoroughly in paper trading mode before considering live deployment.

- Past performance does not guarantee future results
- The bot's performance can vary significantly based on market conditions
- Always monitor the bot's activity and set appropriate risk limits
- Use stop-losses and never risk more than you can afford to lose

## 📊 Performance Tracking

The bot tracks:
- Win rate and profit factor
- Maximum drawdown
- Risk-adjusted returns (Sharpe ratio)
- Individual trade history
- Daily/weekly/monthly P&L

Access metrics via:
- FastAPI dashboard: `http://localhost:8000/docs`
- SQLite database: `data/tradingbot.db`
- Discord notifications

## 🔧 Development

### Running in development mode
```bash
# Enable auto-reload
API_RELOAD=true python -m src.main
```

### Adding new indicators
1. Create indicator class in `src/indicators/`
2. Implement calculate method
3. Add event emission on detection
4. Register in indicator engine

### Adding new strategies
1. Create strategy class in `src/strategies/`
2. Implement signal generation logic
3. Subscribe to relevant events
4. Register in strategy manager

## 📝 TODO

- [ ] Implement backtesting engine
- [ ] Add more ICT patterns (Breaker Blocks, Mitigation Blocks)
- [ ] Multi-timeframe analysis
- [ ] Machine learning for parameter optimization
- [ ] Web dashboard for monitoring
- [ ] Mobile app integration

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- ICT concepts from Michael J. Huddleston (The Inner Circle Trader)
- Binance API documentation and community
- CCXT library for exchange integration
- FastAPI framework for API development

## 📧 Contact

- GitHub: [@ocho011](https://github.com/ocho011)
- Project Link: [https://github.com/ocho011/tradingbot](https://github.com/ocho011/tradingbot)

---

**Made with ❤️ by osangwon**
