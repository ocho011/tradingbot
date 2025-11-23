# 캔들 수신 → 신호 처리 파이프라인 분석

## 📊 전체 데이터 흐름도

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         1. 캔들 데이터 수신                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    BinanceManager._watch_candles()
                    - exchange.watch_ohlcv() 호출
                    - WebSocket으로 실시간 캔들 수신
                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │ CANDLE_RECEIVED 이벤트    │
                    │ EventBus.publish()        │
                    └───────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│  2. CandleProcessingHandler     │   │  WebSocketEventHandler          │
│  (orchestrator.py)               │   │  (websocket.py)                 │
│                                  │   │                                 │
│  - CandleStorage.add_candle()   │   │  - WebSocket 클라이언트로       │
│  - MultiTimeframeEngine         │   │    브로드캐스트                 │
│    .add_candle()                 │   └─────────────────────────────────┘
└─────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    3. 지표 계산 (MultiTimeframeEngine)                   │
│                                                                          │
│  - OrderBlockDetector.detect()                                          │
│  - FVGDetector.detect()                                                 │
│  - BreakerBlockDetector.detect()                                        │
│  - LiquidityZoneDetector.detect()                                       │
│  - TrendRecognitionEngine.analyze()                                     │
└─────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────┐
        │ INDICATOR_UPDATED 이벤트  │
        │ EventBus.publish()        │
        └───────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                 4. IndicatorProcessingHandler                            │
│                 (orchestrator.py)                                        │
│                                                                          │
│  - StrategyIntegrationLayer.process_indicators()                        │
│    → Strategy_A, Strategy_B, Strategy_C 실행                            │
└─────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────┐
        │ SIGNAL_GENERATED 이벤트   │
        │ EventBus.publish()        │
        └───────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   5. SignalProcessingHandler                             │
│                   (orchestrator.py)                                      │
│                                                                          │
│  - RiskValidator.validate_signal()                                      │
│    → 포지션 사이즈 계산                                                 │
│    → 스탑로스/테이크프로핏 계산                                         │
│    → 리스크 검증                                                        │
└─────────────────────────────────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────────┐   ┌──────────────────┐
│ RISK_CHECK_PASSED│   │ RISK_CHECK_FAILED│
└──────────────────┘   └──────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    6. RiskValidationHandler                              │
│                    (orchestrator.py)                                     │
│                                                                          │
│  - OrderExecutor.execute_order()                                        │
│    → Binance API로 주문 전송                                            │
└─────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────┐
        │ ORDER_PLACED 이벤트       │
        │ EventBus.publish()        │
        └───────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    7. OrderExecutionHandler                              │
│                    (orchestrator.py)                                     │
│                                                                          │
│  - PositionManager.open_position()                                      │
│    → 포지션 추적 시작                                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## 🔍 핵심 컴포넌트 상세

### 1. BinanceManager (캔들 수신)
**파일**: `src/services/exchange/binance_manager.py`

```python
async def _watch_candles(self, symbol: str, timeframe: TimeFrame):
    while self._ws_running:
        # ccxt의 watch_ohlcv 사용 (WebSocket)
        ohlcv = await self.exchange.watch_ohlcv(symbol, timeframe.value)
        
        # 최신 캔들 추출
        latest_candle = ohlcv[-1]
        
        # 캔들 데이터 구성
        candle_data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": latest_candle[0],
            "open": latest_candle[1],
            "high": latest_candle[2],
            "low": latest_candle[3],
            "close": latest_candle[4],
            "volume": latest_candle[5],
        }
        
        # 이벤트 발행
        await self.event_bus.publish(
            Event(
                event_type=EventType.CANDLE_RECEIVED,
                priority=6,
                data={"candle": candle_data},
                source="BinanceManager"
            )
        )
```

**현재 문제**: `watch_ohlcv`가 데이터를 반환하지 않음

---

### 2. CandleProcessingHandler (캔들 저장 & 지표 계산 트리거)
**파일**: `src/core/orchestrator.py`

```python
class CandleProcessingHandler(EventHandler):
    async def handle(self, event: Event):
        if event.event_type != EventType.CANDLE_RECEIVED:
            return
        
        candle_data = event.data.get("candle")
        candle = Candle(**candle_data)
        
        # 1. 캔들 저장
        self.candle_storage.add_candle(candle)
        
        # 2. 지표 계산 (자동으로 INDICATOR_UPDATED 이벤트 발행)
        self.multi_timeframe_engine.add_candle(candle)
```

**구독**: `EventType.CANDLE_RECEIVED`
**발행**: 없음 (MultiTimeframeEngine이 INDICATOR_UPDATED 발행)

---

### 3. MultiTimeframeIndicatorEngine (지표 계산)
**파일**: `src/indicators/multi_timeframe_engine.py`

```python
def add_candle(self, candle: Candle):
    # 캔들 저장
    self._candles[symbol][timeframe].append(candle)
    
    # 지표 계산
    indicators = self._calculate_indicators(symbol, timeframe, candles)
    
    # 이벤트 발행
    self.event_bus.publish(
        Event(
            event_type=EventType.INDICATOR_UPDATED,
            data={
                "symbol": symbol,
                "timeframe": timeframe,
                "indicators": indicators
            }
        )
    )
```

**입력**: Candle 객체
**출력**: INDICATOR_UPDATED 이벤트
**계산 항목**:
- Order Blocks (OrderBlockDetector)
- Fair Value Gaps (FVGDetector)
- Breaker Blocks (BreakerBlockDetector)
- Liquidity Zones (LiquidityZoneDetector)
- Trend Recognition (TrendRecognitionEngine)

---

### 4. IndicatorProcessingHandler (전략 실행)
**파일**: `src/core/orchestrator.py`

```python
class IndicatorProcessingHandler(EventHandler):
    async def handle(self, event: Event):
        if event.event_type != EventType.INDICATOR_UPDATED:
            return
        
        # 전략 레이어에서 신호 생성
        signals = await self.strategy_layer.process_indicators(
            symbol=event.data["symbol"],
            timeframe=event.data["timeframe"],
            indicators=event.data["indicators"]
        )
        
        # 각 신호에 대해 SIGNAL_GENERATED 이벤트 발행
        for signal in signals:
            await self.event_bus.publish(
                Event(
                    event_type=EventType.SIGNAL_GENERATED,
                    data={"signal": signal}
                )
            )
```

**구독**: `EventType.INDICATOR_UPDATED`
**발행**: `EventType.SIGNAL_GENERATED`

---

### 5. SignalProcessingHandler (리스크 검증)
**파일**: `src/core/orchestrator.py`

```python
class SignalProcessingHandler(EventHandler):
    async def handle(self, event: Event):
        if event.event_type != EventType.SIGNAL_GENERATED:
            return
        
        signal = event.data["signal"]
        
        # 리스크 검증
        validation_result = await self.risk_validator.validate_signal(signal)
        
        if validation_result.approved:
            await self.event_bus.publish(
                Event(
                    event_type=EventType.RISK_CHECK_PASSED,
                    data={
                        "signal": signal,
                        "validation": validation_result
                    }
                )
            )
        else:
            await self.event_bus.publish(
                Event(
                    event_type=EventType.RISK_CHECK_FAILED,
                    data={
                        "signal": signal,
                        "reason": validation_result.rejection_reason
                    }
                )
            )
```

**구독**: `EventType.SIGNAL_GENERATED`
**발행**: `EventType.RISK_CHECK_PASSED` 또는 `EventType.RISK_CHECK_FAILED`

---

### 6. RiskValidationHandler (주문 실행)
**파일**: `src/core/orchestrator.py`

```python
class RiskValidationHandler(EventHandler):
    async def handle(self, event: Event):
        if event.event_type != EventType.RISK_CHECK_PASSED:
            return
        
        signal = event.data["signal"]
        validation = event.data["validation"]
        
        # 주문 실행
        order = await self.order_executor.execute_order(
            signal=signal,
            position_size=validation.position_size,
            stop_loss=validation.stop_loss,
            take_profit=validation.take_profit
        )
        
        await self.event_bus.publish(
            Event(
                event_type=EventType.ORDER_PLACED,
                data={"order": order}
            )
        )
```

**구독**: `EventType.RISK_CHECK_PASSED`
**발행**: `EventType.ORDER_PLACED`

---

### 7. OrderExecutionHandler (포지션 관리)
**파일**: `src/core/orchestrator.py`

```python
class OrderExecutionHandler(EventHandler):
    async def handle(self, event: Event):
        if event.event_type not in [EventType.ORDER_PLACED, EventType.ORDER_FILLED]:
            return
        
        order = event.data["order"]
        
        # 포지션 추적 시작
        await self.position_manager.open_position(order)
```

**구독**: `EventType.ORDER_PLACED`, `EventType.ORDER_FILLED`
**발행**: `EventType.POSITION_OPENED`

---

## 🔴 현재 문제점

### 문제 1: 캔들 데이터 수신 실패
**위치**: `BinanceManager._watch_candles()`
**증상**: 
- `watch_ohlcv()` 호출 후 데이터 없음
- "Published candle" 로그 없음
- CANDLE_RECEIVED 이벤트 발행 안됨

**원인 추정**:
1. ccxt의 `watch_ohlcv`가 Binance Futures에서 작동하지 않음
2. WebSocket 연결은 되었으나 데이터 스트림 구독 실패
3. 에러가 발생하지만 로깅되지 않음

### 문제 2: Swing Point 감지 실패
**위치**: 모든 지표 감지기
**증상**:
- "Found 0 swing highs and 0 swing lows"
- 1000개 캔들 분석하는데 0개 감지

**원인**:
- CandleStorage에 캔들이 저장되지 않음
- MultiTimeframeEngine이 빈 캔들 리스트로 지표 계산 시도

### 문제 3: 신호/주문 없음
**증상**:
- "Generated 0 validated signals from 3 strategies"
- 주문 실행 없음

**원인**:
- 지표가 없으므로 전략이 신호 생성 불가능

---

## 💡 해결 방안

### 방안 1: 디버그 로깅 활성화
**목적**: `watch_ohlcv`에서 정확히 무슨 일이 일어나는지 확인

```python
# BinanceManager._watch_candles()에 추가
async def _watch_candles(self, symbol: str, timeframe: TimeFrame):
    logger.info(f"Starting candle watcher for {symbol}:{timeframe.value}")
    
    try:
        while self._ws_running:
            logger.debug(f"Calling watch_ohlcv for {symbol} {timeframe.value}...")
            ohlcv = await self.exchange.watch_ohlcv(symbol, timeframe.value)
            logger.debug(f"Received {len(ohlcv) if ohlcv else 0} candles")
            
            if not ohlcv or len(ohlcv) == 0:
                logger.warning(f"No candles received for {symbol} {timeframe.value}")
                continue
            
            # ... 나머지 로직
```

### 방안 2: REST API 폴백 (초기 데이터 로드)
**목적**: WebSocket 문제와 무관하게 초기 캔들 데이터 확보

```python
async def _initialize_candle_history(self, symbol: str, timeframe: TimeFrame):
    """초기 캔들 히스토리를 REST API로 로드"""
    logger.info(f"Loading initial candle history for {symbol} {timeframe.value}")
    
    ohlcv = await self.exchange.fetch_ohlcv(
        symbol=symbol,
        timeframe=timeframe.value,
        limit=1000
    )
    
    for candle_data in ohlcv:
        candle = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": candle_data[0],
            "open": candle_data[1],
            "high": candle_data[2],
            "low": candle_data[3],
            "close": candle_data[4],
            "volume": candle_data[5],
        }
        
        await self.event_bus.publish(
            Event(
                event_type=EventType.CANDLE_RECEIVED,
                data={"candle": candle},
                source="BinanceManager.InitialLoad"
            )
        )
    
    logger.info(f"Loaded {len(ohlcv)} historical candles for {symbol} {timeframe.value}")
```

### 방안 3: Binance WebSocket 직접 구현
**목적**: ccxt 의존성 제거, 직접 제어

```python
import websockets
import json

async def _binance_websocket_stream(self, symbol: str, timeframe: TimeFrame):
    """Binance WebSocket 직접 연결"""
    # Binance Futures WebSocket URL
    ws_url = f"wss://fstream.binance.com/ws/{symbol.lower()}@kline_{timeframe.value}"
    
    async with websockets.connect(ws_url) as websocket:
        logger.info(f"Connected to Binance WebSocket: {ws_url}")
        
        while self._ws_running:
            message = await websocket.recv()
            data = json.loads(message)
            
            # Kline 데이터 추출
            kline = data['k']
            
            candle_data = {
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": kline['t'],
                "open": float(kline['o']),
                "high": float(kline['h']),
                "low": float(kline['l']),
                "close": float(kline['c']),
                "volume": float(kline['v']),
                "is_closed": kline['x']  # 캔들 마감 여부
            }
            
            await self.event_bus.publish(
                Event(
                    event_type=EventType.CANDLE_RECEIVED,
                    data={"candle": candle_data},
                    source="BinanceManager.WebSocket"
                )
            )
```

---

## 📋 다음 단계

1. **디버그 로깅 추가** (`BinanceManager._watch_candles`)
2. **초기 캔들 히스토리 로드** (REST API)
3. **WebSocket 에러 확인** (로그 분석)
4. **필요시 Binance WebSocket 직접 구현**

---

## 🎯 성공 기준

✅ "Published candle" 로그 출력
✅ CandleStorage에 캔들 저장 확인
✅ Swing Point 감지 (> 0)
✅ Order Block, FVG 등 지표 감지
✅ 전략에서 신호 생성
✅ 리스크 검증 통과
✅ 주문 실행

---

생성 시각: 2025-11-22 15:20:54 KST
