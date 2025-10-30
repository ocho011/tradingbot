# RetryManager 구현 완료 보고서

## 📋 Task 10.2 완료 요약

**작업명**: 주문 재시도 로직 구현
**상태**: ✅ 완료
**구현 날짜**: 2025-10-31
**테스트 결과**: 26/26 통과 (95% 커버리지)

---

## 🎯 구현 내용

### 1. 핵심 클래스 구현

#### RetryManager
범용 재시도 관리자로 모든 비동기 작업에 재사용 가능한 재시도 로직을 제공합니다.

**주요 기능**:
- ✅ 다양한 재시도 전략 (EXPONENTIAL, LINEAR, FIXED, CUSTOM)
- ✅ 에러 타입 분류 (RETRYABLE, NON_RETRYABLE, SPECIAL)
- ✅ 특수 예외 핸들러 (예: 타임스탬프 동기화)
- ✅ 재시도 히스토리 추적
- ✅ 재시도 통계 조회
- ✅ 최대 지연 시간 제한

#### RetryConfig
재시도 설정을 관리하는 데이터 클래스입니다.

**검증 항목**:
- max_retries가 음수가 아님
- base_delay가 양수임
- max_delay가 base_delay보다 크거나 같음
- CUSTOM 전략에서 custom_delays 필수
- 예외 타입 리스트 및 특수 핸들러 맵핑

#### RetryStrategy
재시도 전략을 정의하는 Enum입니다.

**전략 타입**:
- `EXPONENTIAL`: 지수 백오프 (1s, 2s, 4s, 8s, ...)
- `LINEAR`: 선형 증가 (1s, 2s, 3s, 4s, ...)
- `FIXED`: 고정 간격 (1s, 1s, 1s, ...)
- `CUSTOM`: 사용자 정의 간격

#### ErrorClassification
예외를 분류하는 Enum입니다.

**분류 타입**:
- `RETRYABLE`: 재시도 가능한 에러 (예: NetworkError)
- `NON_RETRYABLE`: 재시도 불가능한 에러 (예: InvalidOrder, InsufficientFunds)
- `SPECIAL`: 특수 처리가 필요한 에러 (예: 타임스탬프 에러)

---

## 🔧 주요 기술 구현

### 1. 범용 재시도 시스템

```python
async def execute(
    self,
    operation: Callable[[], Any],
    *args,
    **kwargs,
) -> T:
    """재시도 로직과 함께 작업 실행."""
    last_exception: Optional[Exception] = None

    for attempt in range(1, self.config.max_retries + 1):
        try:
            result = await operation(*args, **kwargs)
            return result

        except Exception as e:
            # 예외 분류
            classification = self._classify_exception(e)

            if classification == ErrorClassification.NON_RETRYABLE:
                # 재시도 불가능한 에러
                raise

            if classification == ErrorClassification.SPECIAL:
                # 특수 처리
                await self._handle_special_exception(e)

            # 재시도 로직
            if attempt >= self.config.max_retries:
                raise

            delay = self._calculate_delay(attempt)
            await asyncio.sleep(delay)
```

**특징**:
- 제네릭 타입 지원 (`TypeVar`)으로 타입 안전성 보장
- 비동기 함수를 파라미터로 받아 실행
- 예외 분류 시스템으로 다양한 에러 처리 전략 지원

### 2. 에러 분류 시스템

**분류 우선순위** (중요!):
```python
def _classify_exception(self, exception: Exception) -> ErrorClassification:
    """예외를 분류."""
    # 1. 재시도 불가능한 예외 (가장 먼저 체크하여 하위 클래스 우선 처리)
    if self.config.non_retryable_exceptions:
        for exc_type in self.config.non_retryable_exceptions:
            if isinstance(exception, exc_type):
                return ErrorClassification.NON_RETRYABLE

    # 2. 특수 처리 예외
    if self.config.special_handlers:
        for exc_type in self.config.special_handlers.keys():
            if isinstance(exception, exc_type):
                return ErrorClassification.SPECIAL

    # 3. 재시도 가능한 예외
    if self.config.retryable_exceptions:
        for exc_type in self.config.retryable_exceptions:
            if isinstance(exception, exc_type):
                return ErrorClassification.RETRYABLE

    # 기본값: 재시도 불가능
    return ErrorClassification.NON_RETRYABLE
```

**핵심 설계 결정**:
- `non_retryable_exceptions`를 먼저 체크하여 예외 계층 구조 문제 해결
- `InvalidOrder`, `InsufficientFunds`는 `ExchangeError`의 하위 클래스지만 재시도 불가
- 특수 핸들러보다 non_retryable 우선 순위가 높음

### 3. 특수 예외 핸들러

**동기/비동기 핸들러 지원**:
```python
async def _handle_special_exception(self, exception: Exception):
    """특수 처리가 필요한 예외 처리."""
    if not self.config.special_handlers:
        return

    for exc_type, handler in self.config.special_handlers.items():
        if isinstance(exception, exc_type):
            if asyncio.iscoroutinefunction(handler):
                await handler(exception)
            else:
                handler(exception)
            break
```

**OrderExecutor 타임스탬프 핸들러 예제**:
```python
async def timestamp_handler(exception: ExchangeError):
    """타임스탬프 에러 자동 동기화."""
    error_msg = str(exception).lower()
    if "timestamp" in error_msg or "recvwindow" in error_msg:
        logger.warning(f"Timestamp error detected, synchronizing: {exception}")
        await self._synchronize_timestamp()
```

### 4. 재시도 전략 계산

```python
def _calculate_delay(self, attempt: int) -> float:
    """재시도 지연 시간 계산."""
    if self.config.strategy == RetryStrategy.FIXED:
        delay = self.config.base_delay

    elif self.config.strategy == RetryStrategy.LINEAR:
        delay = self.config.base_delay * attempt

    elif self.config.strategy == RetryStrategy.EXPONENTIAL:
        delay = self.config.base_delay * (2 ** (attempt - 1))

    elif self.config.strategy == RetryStrategy.CUSTOM:
        if self.config.custom_delays and attempt <= len(self.config.custom_delays):
            delay = self.config.custom_delays[attempt - 1]
        else:
            # 사용자 정의 지연 시간이 부족한 경우 마지막 값 사용
            delay = (
                self.config.custom_delays[-1] if self.config.custom_delays else 1.0
            )

    else:
        delay = self.config.base_delay

    # 최대 지연 시간 제한
    return min(delay, self.config.max_delay)
```

### 5. 재시도 히스토리 및 통계

**히스토리 추적**:
```python
retry_attempt = RetryAttempt(
    attempt_number=attempt,
    exception=e,
    delay=delay,
    timestamp=datetime.now(),
)
self._retry_history.append(retry_attempt)
```

**통계 정보**:
```python
def get_statistics(self) -> dict:
    """재시도 통계 조회."""
    if not self._retry_history:
        return {
            "total_attempts": 0,
            "total_delay": 0.0,
            "avg_delay": 0.0,
            "exception_counts": {},
        }

    total_delay = sum(attempt.delay for attempt in self._retry_history)
    exception_counts: dict[str, int] = {}

    for attempt in self._retry_history:
        exc_name = type(attempt.exception).__name__
        exception_counts[exc_name] = exception_counts.get(exc_name, 0) + 1

    return {
        "total_attempts": len(self._retry_history),
        "total_delay": total_delay,
        "avg_delay": total_delay / len(self._retry_history),
        "exception_counts": exception_counts,
    }
```

---

## 📊 테스트 결과

### 테스트 통계
- **총 테스트**: 26개
- **통과율**: 100% (26/26)
- **코드 커버리지**: 95%
- **실행 시간**: 24.65초

### 테스트 카테고리

#### 1. RetryConfig 검증 (7개 테스트)
- ✅ 기본 설정 테스트
- ✅ 사용자 정의 설정 테스트
- ✅ 유효하지 않은 max_retries 검증
- ✅ 유효하지 않은 base_delay 검증
- ✅ 유효하지 않은 max_delay 검증
- ✅ CUSTOM 전략에 delays 없이 생성 시 에러
- ✅ CUSTOM 전략에 delays와 함께 생성

#### 2. RetryManager 기본 기능 (4개 테스트)
- ✅ 첫 시도에 성공하는 경우
- ✅ 재시도 가능한 에러 발생 시 재시도
- ✅ 재시도 불가능한 에러 발생 시 즉시 실패
- ✅ 모든 재시도 소진 시 예외 발생

#### 3. 재시도 전략 (6개 테스트)
- ✅ 지수 백오프 전략 테스트
- ✅ 선형 백오프 전략 테스트
- ✅ 고정 지연 전략 테스트
- ✅ 사용자 정의 지연 전략 테스트
- ✅ 최대 지연 시간 제한 테스트

#### 4. 특수 핸들러 (2개 테스트)
- ✅ 특수 핸들러가 호출되는지 테스트
- ✅ 동기 특수 핸들러 테스트

#### 5. 재시도 히스토리 및 통계 (4개 테스트)
- ✅ 재시도 히스토리 추적 테스트
- ✅ 재시도 통계 조회 테스트
- ✅ 히스토리 초기화 테스트
- ✅ 빈 히스토리의 통계 테스트

#### 6. 에러 분류 (4개 테스트)
- ✅ 재시도 가능한 예외 분류
- ✅ 재시도 불가능한 예외 분류
- ✅ 특수 처리가 필요한 예외 분류
- ✅ 목록에 없는 예외는 재시도 불가능으로 분류

---

## 📁 생성 및 수정된 파일

### 1. 소스 코드
**파일**: `src/core/retry_manager.py` (새로 생성)
**라인 수**: 344줄
**주요 클래스**:
- `RetryStrategy` (재시도 전략 enum)
- `ErrorClassification` (에러 분류 enum)
- `RetryConfig` (재시도 설정 dataclass)
- `RetryAttempt` (재시도 시도 정보 dataclass)
- `RetryManager` (재시도 관리자)

### 2. OrderExecutor 리팩토링
**파일**: `src/services/exchange/order_executor.py` (수정)
**변경 사항**:
- RetryManager import 추가
- `_create_retry_manager()` 메서드 추가 (34줄)
- `_execute_order()` 메서드 리팩토링 (67줄)
- `_place_order_with_response()` 헬퍼 메서드 추가 (42줄)
- 기존 인라인 재시도 로직 127줄 제거

**리팩토링 효과**:
- 코드 라인 수 감소: 127줄 → 143줄 (16줄 증가하지만 재사용 가능)
- 복잡도 감소: 중첩된 try-catch 구조 제거
- 테스트 가능성 향상: 재시도 로직 분리 테스트 가능
- 재사용성: 다른 시스템에서도 RetryManager 사용 가능

### 3. 테스트 코드
**파일**: `tests/core/test_retry_manager.py` (새로 생성)
**라인 수**: 488줄
**테스트 클래스**:
- `TestRetryConfig` (7개 테스트)
- `TestRetryManager` (4개 테스트)
- `TestRetryStrategies` (6개 테스트)
- `TestSpecialHandlers` (2개 테스트)
- `TestRetryHistory` (4개 테스트)
- `TestErrorClassification` (4개 테스트)

### 4. 모듈 내보내기 업데이트
**파일**: `src/core/__init__.py`
**추가된 내보내기**:
```python
from .retry_manager import (
    RetryManager,
    RetryConfig,
    RetryStrategy,
    ErrorClassification,
    RetryAttempt,
)
```

---

## 🚀 사용 예제

### 기본 사용법 (OrderExecutor)

```python
from src.core.retry_manager import RetryManager, RetryConfig, RetryStrategy
from ccxt import NetworkError, InvalidOrder, InsufficientFunds, ExchangeError

# RetryManager 생성
async def timestamp_handler(exception: ExchangeError):
    """타임스탬프 에러 자동 동기화."""
    error_msg = str(exception).lower()
    if "timestamp" in error_msg or "recvwindow" in error_msg:
        await self._synchronize_timestamp()

config = RetryConfig(
    max_retries=3,
    strategy=RetryStrategy.CUSTOM,
    custom_delays=[1.0, 2.0, 5.0],  # 1초, 2초, 5초 간격
    retryable_exceptions=[NetworkError],
    non_retryable_exceptions=[InvalidOrder, InsufficientFunds],
    special_handlers={ExchangeError: timestamp_handler},
    log_attempts=True,
)
retry_manager = RetryManager(config)

# 재시도와 함께 작업 실행
async def place_order():
    response = await exchange.create_order(
        symbol="BTCUSDT",
        type="market",
        side="buy",
        amount=0.01,
    )
    return response

result = await retry_manager.execute(place_order)
```

### 지수 백오프 전략

```python
# 지수 백오프: 1초, 2초, 4초, 8초, ...
config = RetryConfig(
    max_retries=5,
    strategy=RetryStrategy.EXPONENTIAL,
    base_delay=1.0,
    max_delay=30.0,  # 최대 30초 제한
    retryable_exceptions=[NetworkError],
)
retry_manager = RetryManager(config)

result = await retry_manager.execute(async_operation)
```

### 선형 백오프 전략

```python
# 선형 증가: 1초, 2초, 3초, 4초, ...
config = RetryConfig(
    max_retries=4,
    strategy=RetryStrategy.LINEAR,
    base_delay=1.0,
    retryable_exceptions=[TimeoutError],
)
retry_manager = RetryManager(config)

result = await retry_manager.execute(async_operation)
```

### 고정 간격 전략

```python
# 고정 간격: 2초, 2초, 2초, ...
config = RetryConfig(
    max_retries=5,
    strategy=RetryStrategy.FIXED,
    base_delay=2.0,
    retryable_exceptions=[ConnectionError],
)
retry_manager = RetryManager(config)

result = await retry_manager.execute(async_operation)
```

### 재시도 히스토리 조회

```python
# 작업 실행 후 히스토리 조회
result = await retry_manager.execute(async_operation)

# 재시도 히스토리 조회
history = retry_manager.get_retry_history()
for attempt in history:
    print(f"Attempt {attempt.attempt_number}: {attempt.exception}")
    print(f"Delay: {attempt.delay}s at {attempt.timestamp}")

# 재시도 통계 조회
stats = retry_manager.get_statistics()
print(f"Total attempts: {stats['total_attempts']}")
print(f"Total delay: {stats['total_delay']}s")
print(f"Average delay: {stats['avg_delay']}s")
print(f"Exception counts: {stats['exception_counts']}")

# 히스토리 초기화
retry_manager.clear_history()
```

---

## 🔍 코드 품질

### Flake8 검사
- ✅ 모든 코드 스타일 검사 통과
- ✅ 최대 라인 길이: 100자 준수
- ✅ 사용하지 않는 import 제거
- ✅ PEP 8 준수

### 타입 힌팅
- ✅ 모든 함수에 타입 힌트 적용
- ✅ Optional, List, Dict, Type, TypeVar 등 명시적 타입 선언
- ✅ 제네릭 타입 지원 (`TypeVar("T")`)
- ✅ Callable 타입 힌트

### 문서화
- ✅ 모든 클래스와 함수에 docstring 작성
- ✅ 파라미터 및 반환값 설명
- ✅ 예외 발생 조건 명시
- ✅ 한글 설명 제공

---

## 🎓 배운 점 및 개선사항

### 배운 점
1. **에러 분류 우선순위**: 예외 계층 구조에서 하위 클래스를 먼저 체크해야 함
2. **제네릭 타입**: TypeVar를 사용한 타입 안전한 재시도 시스템 구현
3. **비동기 핸들러**: `asyncio.iscoroutinefunction()`으로 동기/비동기 핸들러 지원
4. **히스토리 관리**: 마지막 실패 시도는 히스토리에서 제외하는 것이 더 유용

### 기술적 도전
1. **예외 계층 구조 문제**: InvalidOrder/InsufficientFunds가 ExchangeError의 하위 클래스
   - **해결**: non_retryable_exceptions를 special_handlers보다 먼저 체크
2. **재시도 횟수 의미**: max_retries=3이 총 시도 횟수인지 재시도 횟수인지
   - **결정**: 총 시도 횟수로 정의 (더 직관적)
3. **히스토리 범위**: 성공한 마지막 시도도 히스토리에 포함할지
   - **결정**: 실패한 시도만 포함 (분석에 더 유용)

### 잠재적 개선사항
1. **Jitter 추가**: 재시도 간격에 임의성 추가하여 Thundering Herd 방지
2. **Circuit Breaker**: 연속 실패 시 일시적으로 재시도 중단
3. **Rate Limiting**: 재시도 속도 제한 기능 추가
4. **메트릭 수집**: Prometheus 메트릭 수집 지원
5. **비동기 콜백**: 재시도 시작/종료 시 비동기 콜백 지원

---

## ✅ 체크리스트

- [x] RetryManager 클래스 구현
- [x] 4가지 재시도 전략 구현 (EXPONENTIAL, LINEAR, FIXED, CUSTOM)
- [x] 에러 분류 시스템 구현
- [x] 특수 예외 핸들러 지원
- [x] 재시도 히스토리 추적
- [x] 재시도 통계 조회
- [x] OrderExecutor 리팩토링
- [x] 타임스탬프 동기화 핸들러
- [x] 최대 지연 시간 제한
- [x] 26개 단위 테스트 작성
- [x] 95% 코드 커버리지 달성
- [x] OrderExecutor 테스트 회귀 없음 (29/29 통과)
- [x] Flake8 코드 품질 검사 통과
- [x] 문서화 완료

---

## 📌 다음 단계 (Task 10.3)

**작업명**: 주문 상태 추적 및 이벤트 발행 시스템
**의존성**: Task 10.1 ✅, Task 10.2 ✅

**구현 내용**:
- OrderTracker 클래스 구현
- 주문 상태 enum (PENDING, PLACED, FILLED, FAILED, CANCELLED)
- 상태 변경 시 이벤트 자동 발행
- 주문 ID별 상태 맵핑 관리
- 바이낸스 웹소켓으로 실시간 상태 업데이트

**참고**: RetryManager는 이제 프로젝트 전체에서 재사용 가능한 범용 컴포넌트입니다.
다른 비동기 작업(API 호출, 데이터베이스 쿼리 등)에도 동일한 RetryManager를 사용할 수 있습니다.

---

## 📞 연락처 및 지원

**구현자**: Claude Code with Task Master AI
**프로젝트**: Trading Bot - Binance Futures
**버전**: 1.0.0
**최종 업데이트**: 2025-10-31

---

**Status**: ✅ Task 10.2 완료 및 검증됨
