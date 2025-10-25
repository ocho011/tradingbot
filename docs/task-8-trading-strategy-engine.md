# Task 8: 매매 전략 엔진 구현 문서

## 개요

Task 8은 3가지 매매 전략(보수적, 공격적, 혼합)을 구현하고, 신호 생성, 중복 필터링, 우선순위 관리 시스템을 포함한 종합적인 매매 전략 엔진을 구축하는 작업입니다.

**상태**: ✅ 완료
**복잡도**: 9/10
**의존성**: Task 7 (SMC 패턴 분석 모듈)

---

## 1. 전략 A: 보수적 매매 로직 (Subtask 8.1)

### 개요
1시간 차트에서 Break of Market Structure(BMS) 확인 후, 15분 차트에서 Fair Value Gap(FVG) 또는 Order Block(OB)를 감지하고, 1분 차트에서 정확한 진입 타이밍을 포착하는 보수적 접근 방식입니다.

### 주요 구현 내용

```python
class StrategyA:
    """보수적 매매 전략 - 다중 타임프레임 확인"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.timeframes = ['1h', '15m', '1m']

    def analyze(self, market_data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        """
        3단계 확인 프로세스:
        1. 1시간 차트 - BMS 확인
        2. 15분 차트 - FVG/OB 감지
        3. 1분 차트 - 진입 타이밍 포착
        """
        # 1시간 BMS 확인
        if not self._check_hourly_bms(market_data['1h']):
            return None

        # 15분 FVG/OB 감지
        pattern = self._detect_15m_patterns(market_data['15m'])
        if not pattern:
            return None

        # 1분 진입 타이밍
        entry = self._find_entry_timing(market_data['1m'], pattern)
        if not entry:
            return None

        return self._generate_signal(entry, pattern)
```

### 신호 생성 조건
- **1시간 BMS**: 명확한 시장 구조 변화 감지
- **15분 FVG/OB**: 고확률 패턴 확인
- **1분 진입**: 리스크 최소화된 진입점
- **신뢰도**: 보수적 접근으로 높은 신뢰도 요구 (>80%)

### 구현 파일
- `src/services/strategy/strategy_a.py`
- `tests/services/strategy/test_strategy_a.py`

---

## 2. 전략 B: 공격적 매매 로직 (Subtask 8.2)

### 개요
15분 차트에서 Liquidity Sweep와 FVG가 동시에 감지되면 즉시 진입하는 공격적 접근 방식입니다.

### 주요 구현 내용

```python
class StrategyB:
    """공격적 매매 전략 - 신속한 진입"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.timeframe = '15m'

    def analyze(self, market_data: pd.DataFrame) -> Optional[Signal]:
        """
        동시 조건 확인:
        1. Liquidity Sweep 감지
        2. FVG 형성 확인
        3. 즉시 진입 신호 생성
        """
        # Liquidity Sweep 감지
        liquidity_sweep = self._detect_liquidity_sweep(market_data)
        if not liquidity_sweep:
            return None

        # FVG 동시 감지
        fvg = self._detect_fvg(market_data)
        if not fvg:
            return None

        # 즉시 진입 신호
        return self._generate_aggressive_signal(liquidity_sweep, fvg)
```

### 신호 생성 조건
- **Liquidity Sweep**: 유동성 사냥 패턴 확인
- **FVG**: Fair Value Gap 즉시 감지
- **위험-수익 비율**: 높은 RR (1:3 이상)
- **신뢰도**: 중간 수준 (>60%)으로 빠른 진입 우선

### 구현 파일
- `src/services/strategy/strategy_b.py`
- `tests/services/strategy/test_strategy_b.py`

---

## 3. 전략 C: 혼합 매매 로직 (Subtask 8.3)

### 개요
1시간 추세, 15분 OB/FVG, Liquidity 조건을 종합적으로 고려하는 균형잡힌 접근 방식입니다.

### 주요 구현 내용

```python
class StrategyC:
    """혼합 매매 전략 - 다중 조건 종합"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.weights = {
            'trend': 0.4,      # 추세 가중치
            'pattern': 0.35,   # 패턴 가중치
            'liquidity': 0.25  # 유동성 가중치
        }

    def analyze(self, market_data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        """
        가중치 기반 종합 분석:
        1. 1시간 추세 분석
        2. 15분 OB/FVG 확인
        3. Liquidity 레벨 체크
        4. 가중 신뢰도 계산
        """
        scores = {}

        # 1시간 추세 분석
        scores['trend'] = self._analyze_hourly_trend(market_data['1h'])

        # 15분 패턴 분석
        scores['pattern'] = self._analyze_15m_patterns(market_data['15m'])

        # Liquidity 분석
        scores['liquidity'] = self._analyze_liquidity(market_data['15m'])

        # 가중 신뢰도 계산
        confidence = self._calculate_weighted_confidence(scores)

        if confidence >= self.config.min_confidence:
            return self._generate_signal(market_data, scores, confidence)

        return None
```

### 신호 생성 조건
- **추세 분석**: 1시간 차트 방향성 (40% 가중치)
- **패턴 분석**: 15분 OB/FVG (35% 가중치)
- **Liquidity**: 유동성 레벨 (25% 가중치)
- **신뢰도**: 가중 평균 기반 (>70%)

### 구현 파일
- `src/services/strategy/strategy_c.py`
- `tests/services/strategy/test_strategy_c.py`

---

## 4. 매매 신호 통합 레이어 (Subtask 8.4)

### 개요
3가지 전략을 통합하고 신호를 조율하는 중앙 관리 시스템입니다.

### 주요 구현 내용

```python
class StrategyIntegrationLayer:
    """전략 통합 및 신호 조율 레이어"""

    def __init__(self):
        self.strategies = {
            'strategy_a': StrategyA(config_a),
            'strategy_b': StrategyB(config_b),
            'strategy_c': StrategyC(config_c)
        }
        self.active_strategies = set()

    async def generate_signals(self, market_data: Dict) -> List[Signal]:
        """모든 활성 전략에서 신호 생성"""
        signals = []

        for name, strategy in self.strategies.items():
            if name not in self.active_strategies:
                continue

            signal = await strategy.analyze(market_data)
            if signal:
                signal.strategy = name
                signals.append(signal)

        return signals

    def enable_strategy(self, strategy_name: str):
        """전략 활성화"""
        self.active_strategies.add(strategy_name)

    def disable_strategy(self, strategy_name: str):
        """전략 비활성화"""
        self.active_strategies.discard(strategy_name)
```

### Signal 데이터 모델

```python
@dataclass
class Signal:
    """매매 신호 데이터 클래스"""
    strategy: str              # 전략 이름
    symbol: str               # 거래 심볼
    direction: str            # 'long' or 'short'
    entry_price: Decimal      # 진입 가격
    stop_loss: Decimal        # 손절 가격
    take_profit: Decimal      # 익절 가격
    confidence: float         # 신뢰도 (0-1)
    timestamp: datetime       # 생성 시간
    timeframe: str           # 타임프레임
    pattern_type: str        # 패턴 유형
    risk_reward_ratio: float # 리스크-보상 비율
```

### 구현 파일
- `src/services/strategy/integration_layer.py`
- `src/models/signal.py`
- `tests/services/strategy/test_integration_layer.py`

---

## 5. 중복 신호 필터링 시스템 (Subtask 8.5)

### 개요
동일 시간대 또는 유사한 조건의 중복 신호를 자동으로 감지하고 필터링합니다.

### 주요 구현 내용

```python
class DuplicateSignalFilter:
    """중복 신호 필터링 시스템"""

    def __init__(self):
        self.time_window = timedelta(minutes=5)  # 5분 윈도우
        self.price_threshold = 0.01  # 1% 가격 차이
        self.recent_signals = deque(maxlen=100)

    def filter_duplicates(self, new_signal: Signal) -> bool:
        """
        중복 신호 검사:
        1. 시간 윈도우 체크 (5분 이내)
        2. 가격 범위 체크 (1% 이내)
        3. 전략 충돌 체크
        4. 포지션 충돌 체크
        """
        for existing_signal in self.recent_signals:
            if self._is_duplicate(new_signal, existing_signal):
                logger.info(
                    f"Duplicate signal filtered: {new_signal.strategy} "
                    f"at {new_signal.entry_price}"
                )
                return False

        self.recent_signals.append(new_signal)
        return True

    def _is_duplicate(self, signal1: Signal, signal2: Signal) -> bool:
        """중복 여부 판단"""
        # 시간 체크
        time_diff = abs((signal1.timestamp - signal2.timestamp).total_seconds())
        if time_diff > self.time_window.total_seconds():
            return False

        # 가격 체크
        price_diff = abs(signal1.entry_price - signal2.entry_price)
        if price_diff / signal1.entry_price > self.price_threshold:
            return False

        # 방향 체크
        if signal1.direction != signal2.direction:
            return False

        return True
```

### 필터링 규칙
- **시간 윈도우**: 5분 이내 신호는 중복으로 간주
- **가격 범위**: 1% 이내 가격은 동일한 것으로 간주
- **방향 일치**: 동일 방향(long/short) 신호만 중복 체크
- **전략 독립성**: 서로 다른 전략은 독립적으로 처리

### 구현 파일
- `src/services/strategy/duplicate_filter.py`
- `tests/services/strategy/test_duplicate_filter.py`

---

## 6. 신호 우선순위 관리 시스템 (Subtask 8.6)

### 개요
다중 신호 발생 시 우선순위를 기반으로 최적의 신호를 선택합니다.

### 주요 구현 내용

```python
class SignalPriorityManager:
    """신호 우선순위 관리 시스템"""

    def __init__(self):
        self.priority_weights = {
            'confidence': 0.5,      # 신뢰도 가중치
            'risk_reward': 0.3,     # RR 비율 가중치
            'strategy_rank': 0.2    # 전략 순위 가중치
        }
        self.strategy_ranks = {
            'strategy_a': 3,  # 가장 높은 순위
            'strategy_c': 2,
            'strategy_b': 1   # 가장 낮은 순위
        }

    def select_best_signal(self, signals: List[Signal]) -> Optional[Signal]:
        """
        우선순위 기반 최적 신호 선택:
        1. 우선순위 점수 계산
        2. 점수 기반 정렬
        3. 최고 점수 신호 반환
        """
        if not signals:
            return None

        scored_signals = []
        for signal in signals:
            score = self._calculate_priority_score(signal)
            scored_signals.append((score, signal))

        # 점수 기반 정렬 (내림차순)
        scored_signals.sort(key=lambda x: x[0], reverse=True)

        best_score, best_signal = scored_signals[0]
        logger.info(
            f"Selected signal: {best_signal.strategy} "
            f"with priority score {best_score:.2f}"
        )

        return best_signal

    def _calculate_priority_score(self, signal: Signal) -> float:
        """우선순위 점수 계산"""
        # 신뢰도 점수
        confidence_score = signal.confidence * self.priority_weights['confidence']

        # RR 비율 점수 (정규화)
        rr_normalized = min(signal.risk_reward_ratio / 5.0, 1.0)
        rr_score = rr_normalized * self.priority_weights['risk_reward']

        # 전략 순위 점수
        strategy_rank = self.strategy_ranks.get(signal.strategy, 0)
        rank_normalized = strategy_rank / 3.0
        rank_score = rank_normalized * self.priority_weights['strategy_rank']

        return confidence_score + rr_score + rank_score
```

### 우선순위 계산 요소
- **신뢰도** (50%): 신호의 신뢰 수준
- **RR 비율** (30%): 리스크-보상 비율
- **전략 순위** (20%): 전략 타입별 고정 순위
  - Strategy A (보수적): 순위 3
  - Strategy C (혼합): 순위 2
  - Strategy B (공격적): 순위 1

### 구현 파일
- `src/services/strategy/priority_manager.py`
- `tests/services/strategy/test_priority_manager.py`

---

## 7. 전략 설정 관리 시스템 (Subtask 8.7)

### 개요
각 전략의 활성화/비활성화 및 파라미터를 런타임에 제어합니다.

### 주요 구현 내용

```python
class StrategyConfigManager:
    """전략 설정 관리 시스템"""

    def __init__(self, config_path: str = "config/strategies.yaml"):
        self.config_path = config_path
        self.configs: Dict[str, StrategyConfig] = {}
        self.load_configs()

    def load_configs(self):
        """설정 파일 로드"""
        with open(self.config_path, 'r') as f:
            data = yaml.safe_load(f)

        for strategy_name, config_data in data['strategies'].items():
            self.configs[strategy_name] = StrategyConfig(**config_data)

    def save_configs(self):
        """설정 파일 저장"""
        data = {
            'strategies': {
                name: asdict(config)
                for name, config in self.configs.items()
            }
        }

        with open(self.config_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)

    def update_strategy_config(
        self,
        strategy_name: str,
        **kwargs
    ) -> StrategyConfig:
        """전략 설정 업데이트"""
        if strategy_name not in self.configs:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        config = self.configs[strategy_name]

        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

        self.save_configs()
        return config

    def enable_strategy(self, strategy_name: str):
        """전략 활성화"""
        self.update_strategy_config(strategy_name, enabled=True)

    def disable_strategy(self, strategy_name: str):
        """전략 비활성화"""
        self.update_strategy_config(strategy_name, enabled=False)
```

### StrategyConfig 모델

```python
@dataclass
class StrategyConfig:
    """전략 설정 데이터 클래스"""
    enabled: bool = True
    min_confidence: float = 0.7
    time_window_minutes: int = 5
    max_positions: int = 3
    risk_per_trade: float = 0.02  # 2% 리스크
    min_risk_reward: float = 1.5

    # 전략 A 전용
    require_hourly_bms: bool = True
    require_15m_confirmation: bool = True

    # 전략 B 전용
    liquidity_sweep_threshold: float = 0.015  # 1.5%
    immediate_entry: bool = True

    # 전략 C 전용
    trend_weight: float = 0.4
    pattern_weight: float = 0.35
    liquidity_weight: float = 0.25
```

### 설정 파일 예시 (config/strategies.yaml)

```yaml
strategies:
  strategy_a:
    enabled: true
    min_confidence: 0.8
    time_window_minutes: 5
    max_positions: 2
    risk_per_trade: 0.02
    min_risk_reward: 2.0
    require_hourly_bms: true
    require_15m_confirmation: true

  strategy_b:
    enabled: true
    min_confidence: 0.6
    time_window_minutes: 3
    max_positions: 3
    risk_per_trade: 0.03
    min_risk_reward: 3.0
    liquidity_sweep_threshold: 0.015
    immediate_entry: true

  strategy_c:
    enabled: true
    min_confidence: 0.7
    time_window_minutes: 5
    max_positions: 2
    risk_per_trade: 0.02
    min_risk_reward: 1.5
    trend_weight: 0.4
    pattern_weight: 0.35
    liquidity_weight: 0.25
```

### 구현 파일
- `src/services/strategy/config_manager.py`
- `src/models/strategy_config.py`
- `tests/services/strategy/test_config_manager.py`
- `examples/config_manager_example.py`

---

## 8. 테스트 전략

### 단위 테스트

각 전략별 독립적인 테스트:

```python
# tests/services/strategy/test_strategy_a.py
def test_strategy_a_signal_generation():
    """전략 A 신호 생성 테스트"""
    strategy = StrategyA(config)
    market_data = load_test_data('strategy_a_scenario.json')

    signal = strategy.analyze(market_data)

    assert signal is not None
    assert signal.confidence >= 0.8
    assert signal.direction in ['long', 'short']

def test_strategy_a_no_signal_without_bms():
    """BMS 없을 때 신호 미생성 테스트"""
    strategy = StrategyA(config)
    market_data = load_test_data('no_bms_scenario.json')

    signal = strategy.analyze(market_data)

    assert signal is None
```

### 통합 테스트

```python
# tests/integration/test_strategy_integration.py
@pytest.mark.asyncio
async def test_multiple_strategy_integration():
    """다중 전략 통합 테스트"""
    integration_layer = StrategyIntegrationLayer()
    integration_layer.enable_strategy('strategy_a')
    integration_layer.enable_strategy('strategy_b')
    integration_layer.enable_strategy('strategy_c')

    market_data = load_test_data('multi_strategy_scenario.json')
    signals = await integration_layer.generate_signals(market_data)

    assert len(signals) > 0
    assert all(s.confidence > 0.6 for s in signals)
```

### 성능 테스트

```python
# tests/performance/test_strategy_performance.py
def test_signal_generation_performance():
    """신호 생성 성능 벤치마크"""
    strategy = StrategyC(config)
    market_data = generate_large_dataset(1000)

    start_time = time.time()
    for _ in range(100):
        strategy.analyze(market_data)
    elapsed = time.time() - start_time

    assert elapsed < 1.0  # 100회 실행이 1초 이내
```

---

## 9. 구현 파일 구조

```
src/
├── models/
│   ├── signal.py                    # Signal 데이터 모델
│   └── strategy_config.py           # StrategyConfig 모델
│
├── services/
│   └── strategy/
│       ├── __init__.py
│       ├── strategy_a.py            # 전략 A 구현
│       ├── strategy_b.py            # 전략 B 구현
│       ├── strategy_c.py            # 전략 C 구현
│       ├── integration_layer.py     # 통합 레이어
│       ├── duplicate_filter.py      # 중복 필터링
│       ├── priority_manager.py      # 우선순위 관리
│       └── config_manager.py        # 설정 관리
│
tests/
├── services/
│   └── strategy/
│       ├── test_strategy_a.py
│       ├── test_strategy_b.py
│       ├── test_strategy_c.py
│       ├── test_integration_layer.py
│       ├── test_duplicate_filter.py
│       ├── test_priority_manager.py
│       └── test_config_manager.py
│
├── integration/
│   └── test_strategy_integration.py
│
└── performance/
    └── test_strategy_performance.py

config/
└── strategies.yaml                  # 전략 설정 파일

examples/
└── config_manager_example.py        # 설정 관리 예제
```

---

## 10. 사용 예시

### 기본 사용

```python
from src.services.strategy import StrategyIntegrationLayer
from src.services.strategy import DuplicateSignalFilter
from src.services.strategy import SignalPriorityManager

# 초기화
integration_layer = StrategyIntegrationLayer()
duplicate_filter = DuplicateSignalFilter()
priority_manager = SignalPriorityManager()

# 전략 활성화
integration_layer.enable_strategy('strategy_a')
integration_layer.enable_strategy('strategy_c')

# 신호 생성
market_data = get_market_data()
signals = await integration_layer.generate_signals(market_data)

# 중복 필터링
filtered_signals = [
    signal for signal in signals
    if duplicate_filter.filter_duplicates(signal)
]

# 최적 신호 선택
best_signal = priority_manager.select_best_signal(filtered_signals)

if best_signal:
    print(f"Execute trade: {best_signal.direction} at {best_signal.entry_price}")
```

### 설정 관리

```python
from src.services.strategy import StrategyConfigManager

config_manager = StrategyConfigManager()

# 전략 비활성화
config_manager.disable_strategy('strategy_b')

# 전략 설정 업데이트
config_manager.update_strategy_config(
    'strategy_a',
    min_confidence=0.85,
    risk_per_trade=0.015
)

# 설정 조회
config = config_manager.get_config('strategy_c')
print(f"Min confidence: {config.min_confidence}")
```

---

## 11. 향후 개선 방향

### 단기 개선 사항
1. **백테스팅 시스템**: 과거 데이터 기반 전략 성능 검증
2. **실시간 모니터링**: 전략별 성능 대시보드
3. **자동 파라미터 최적화**: 머신러닝 기반 설정 튜닝

### 장기 개선 사항
1. **추가 전략 개발**: 더 다양한 매매 전략 추가
2. **포트폴리오 최적화**: 전략 간 자본 배분 최적화
3. **리스크 관리 고도화**: VAR, 드로다운 제한 등

---

## 12. 참고 자료

### 내부 문서
- Task 7: SMC 패턴 분석 모듈 문서
- Task 9: 포지션 관리 시스템 문서

### 외부 참고
- Smart Money Concepts (SMC) 이론
- ICT (Inner Circle Trader) 트레이딩 개념
- 다중 타임프레임 분석 방법론

---

**작성일**: 2025-10-25
**버전**: 1.0
**작성자**: Trading Bot Development Team
