import sys
import json
import requests

try:
    response = requests.get('http://localhost:8000/config')
    data = response.json()
    config = data.get('configuration', {})
    meta = data.get('metadata', {})

    print('='*50)
    print('1. ENVIRONMENT (환경 설정)')
    print(f"- Environment Mode : {meta.get('environment', 'Unknown').upper()}")
    print(f"- Binance Testnet  : {config.get('binance', {}).get('testnet')}")
    print('='*50)

    print('2. MARKET SELECTION (시장 설정)')
    market = config.get('market', {})
    print(f"- Active Symbols   : {market.get('active_symbols')}")
    print(f"- Primary Timeframe: {market.get('primary_timeframe')}")
    print(f"- Higher Timeframe : {market.get('higher_timeframe')}")
    print(f"- Lower Timeframe  : {market.get('lower_timeframe')}")
    print('='*50)

    print('3. TRADING SETTINGS (트레이딩 설정)')
    trading = config.get('trading', {})
    print(f"- Trading Mode     : {trading.get('mode', 'live').upper()}")
    print(f"- Leverage         : {trading.get('default_leverage')}x")
    print(f"- Max Position     : ${trading.get('max_position_size_usdt')}")
    print(f"- Risk per Trade   : {trading.get('risk_per_trade_percent')}%")
    print('='*50)

    print('4. STRATEGY CONTROL (전략 제어)')
    strat = config.get('strategy', {})
    print(f"- Strategy 1 (Conservative): {'ON' if strat.get('enable_strategy_1') else 'OFF'}")
    print(f"- Strategy 2 (Aggressive)  : {'ON' if strat.get('enable_strategy_2') else 'OFF'}")
    print(f"- Strategy 3 (Hybrid)      : {'ON' if strat.get('enable_strategy_3') else 'OFF'}")
    print('='*50)

    print('5. ICT INDICATORS (지표 설정)')
    ict = config.get('ict', {})
    print(f"- FVG Min Size     : {ict.get('fvg_min_size_percent')}%")
    print(f"- OB Lookback      : {ict.get('ob_lookback_periods')} candles")
    print(f"- Liquidity Sweep  : {ict.get('liquidity_sweep_threshold')}")
    print('='*50)

except Exception as e:
    print(f"Error: {e}")
