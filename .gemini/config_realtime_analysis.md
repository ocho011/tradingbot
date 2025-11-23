# 설정 실시간 반영 분석 결과

## 📊 UI 설정 항목별 실시간 반영 여부

### ✅ 실시간 반영되는 항목 (동적 구독 구현됨)
1. **거래쌍 (Active Trading Pairs)**
   - ✅ 체크박스 선택 → Save 클릭
   - ✅ 자동으로 `/api/symbols/add` 호출
   - ✅ 1000개 과거 캔들 로드
   - ✅ WebSocket 실시간 구독 시작
   - ✅ 시스템 재시작 불필요

### ❌ 실시간 반영되지 않는 항목 (재시작 필요)

#### 1. **거래 설정 (Trading Settings)**
   - ❌ Leverage (레버리지)
   - ❌ Max Position Size (최대 포지션 크기)
   - ❌ Risk Per Trade (거래당 리스크)
   
   **현재 동작:**
   - ConfigurationManager에 저장만 됨
   - 실제 거래 로직에서 사용하는 값은 초기화 시점의 값
   - 변경 사항이 실시간 반영 안 됨

#### 2. **타임프레임 설정 (Timeframes)**
   - ❌ Primary Timeframe
   - ❌ Higher Timeframe
   - ❌ Lower Timeframe
   
   **현재 동작:**
   - 설정 파일에만 저장
   - 전략 실행 시 초기 설정값 사용
   - 변경하려면 재시작 필요

#### 3. **전략 활성화 (Strategy Control)**
   - ❌ Strategy 1 Enable/Disable
   - ❌ Strategy 2 Enable/Disable
   - ❌ Strategy 3 Enable/Disable
   
   **현재 동작:**
   - 설정 파일에만 저장
   - StrategyLayer 초기화 시점의 설정 사용
   - 실시간 활성화/비활성화 불가

#### 4. **ICT 지표 설정 (ICT Indicators)**
   - ❌ FVG Min Size
   - ❌ OB Lookback Periods
   - ❌ Liquidity Sweep Threshold
   
   **현재 동작:**
   - 설정 파일에만 저장
   - 지표 계산 엔진 초기화 시점의 값 사용
   - 변경하려면 재시작 필요

#### 5. **환경 전환 (Environment Switch)**
   - ❌ Testnet ↔ Mainnet
   
   **현재 동작:**
   - ConfigurationManager에서 설정 변경
   - BinanceManager는 초기화 시점의 환경 사용
   - 재시작 필요 (API 키, 엔드포인트 변경)

---

## 🔍 근본 원인

### 1. **CONFIG_UPDATED 이벤트 미구독**
```python
# ConfigurationManager에서 이벤트 발행
event = Event(
    event_type=EventType.CONFIG_UPDATED,
    data={
        "change_type": change_type,
        "subject": subject,
        "details": details,
    },
    priority=5,
)
await self.event_bus.emit(event)
```

**문제:** 이 이벤트를 구독하는 핸들러가 없음!

### 2. **컴포넌트별 초기화 시점 설정 사용**

#### BinanceManager
```python
def __init__(self, config: BinanceConfig, ...):
    self.config = config  # 초기화 시점의 config 저장
    # 이후 config 변경되어도 self.config는 그대로
```

#### StrategyLayer
```python
def __init__(self, config: StrategyConfig, ...):
    self.config = config  # 초기화 시점의 config
    # 전략 활성화 여부도 초기화 시점 기준
```

#### RiskManager
```python
def __init__(self, config: TradingConfig, ...):
    self.max_position_size = config.max_position_size_usdt
    self.leverage = config.default_leverage
    # 초기화 시점의 값으로 고정
```

---

## 💡 해결 방안

### 옵션 1: CONFIG_UPDATED 핸들러 추가 (권장)
각 컴포넌트가 CONFIG_UPDATED 이벤트를 구독하고 설정 업데이트

```python
class ConfigUpdateHandler(EventHandler):
    async def handle(self, event: Event):
        subject = event.data.get("subject")
        details = event.data.get("details")
        
        if subject == "trading":
            # RiskManager 설정 업데이트
            risk_manager.update_config(details)
        elif subject == "strategy":
            # StrategyLayer 설정 업데이트
            strategy_layer.update_config(details)
        # ...
```

### 옵션 2: 컴포넌트에서 ConfigurationManager 참조
설정이 필요할 때마다 ConfigurationManager에서 최신 값 조회

```python
class RiskManager:
    def __init__(self, config_manager: ConfigurationManager):
        self.config_manager = config_manager
    
    def validate_position_size(self, size: float):
        # 항상 최신 설정 사용
        max_size = self.config_manager.settings.trading.max_position_size_usdt
        return size <= max_size
```

### 옵션 3: 재시작 필요 명시
UI에서 "재시작 필요" 경고 표시

---

## 📝 결론

**현재 상태:**
- ✅ **거래쌍만** 동적 구독 구현됨
- ❌ **나머지 모든 설정**은 재시작 필요

**권장 사항:**
1. 중요도가 높은 설정부터 실시간 반영 구현
   - 우선순위: 전략 활성화 > 거래 설정 > ICT 지표
2. 환경 전환은 재시작 필수 (API 엔드포인트 변경)
3. UI에 "변경사항 적용을 위해 재시작 필요" 안내 추가
