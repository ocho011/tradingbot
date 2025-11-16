"""
Retry management system for handling transient failures with exponential backoff.

이 모듈은 재시도 로직을 캡슐화하여 다양한 시스템에서 재사용할 수 있는
RetryManager 클래스를 제공합니다.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, List, Optional, Type, TypeVar

logger = logging.getLogger(__name__)


T = TypeVar("T")


class RetryStrategy(str, Enum):
    """재시도 전략."""

    EXPONENTIAL = "exponential"  # 지수 백오프 (1s, 2s, 4s, 8s, ...)
    LINEAR = "linear"  # 선형 증가 (1s, 2s, 3s, 4s, ...)
    FIXED = "fixed"  # 고정 간격 (1s, 1s, 1s, ...)
    CUSTOM = "custom"  # 사용자 정의 간격


class ErrorClassification(str, Enum):
    """에러 분류."""

    RETRYABLE = "retryable"  # 재시도 가능한 에러
    NON_RETRYABLE = "non_retryable"  # 재시도 불가능한 에러
    SPECIAL = "special"  # 특수 처리가 필요한 에러


@dataclass
class RetryConfig:
    """
    재시도 설정.

    Attributes:
        max_retries: 최대 재시도 횟수 (기본값: 3)
        strategy: 재시도 전략 (기본값: EXPONENTIAL)
        base_delay: 기본 지연 시간 (초, 기본값: 1.0)
        max_delay: 최대 지연 시간 (초, 기본값: 60.0)
        custom_delays: 사용자 정의 지연 시간 리스트 (CUSTOM 전략용)
        retryable_exceptions: 재시도 가능한 예외 타입 리스트
        non_retryable_exceptions: 재시도 불가능한 예외 타입 리스트
        special_handlers: 특수 처리가 필요한 예외와 핸들러 매핑
        log_attempts: 재시도 시도 로깅 여부 (기본값: True)
    """

    max_retries: int = 3
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    base_delay: float = 1.0
    max_delay: float = 60.0
    custom_delays: Optional[List[float]] = None
    retryable_exceptions: Optional[List[Type[Exception]]] = None
    non_retryable_exceptions: Optional[List[Type[Exception]]] = None
    special_handlers: Optional[dict[Type[Exception], Callable]] = None
    log_attempts: bool = True

    def __post_init__(self):
        """초기화 후 검증."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")
        if self.strategy == RetryStrategy.CUSTOM and not self.custom_delays:
            raise ValueError("custom_delays required for CUSTOM strategy")


@dataclass
class RetryAttempt:
    """
    재시도 시도 정보.

    Attributes:
        attempt_number: 시도 번호 (1부터 시작)
        exception: 발생한 예외
        delay: 다음 재시도까지의 지연 시간 (초)
        timestamp: 시도 시각
    """

    attempt_number: int
    exception: Exception
    delay: float
    timestamp: datetime


class RetryManager:
    """
    범용 재시도 관리자.

    비동기 작업의 재시도 로직을 관리하며, 다양한 재시도 전략과
    예외 처리 방식을 지원합니다.

    Example:
        >>> config = RetryConfig(
        ...     max_retries=3,
        ...     strategy=RetryStrategy.EXPONENTIAL,
        ...     retryable_exceptions=[NetworkError],
        ...     non_retryable_exceptions=[InvalidOrder]
        ... )
        >>> retry_manager = RetryManager(config)
        >>>
        >>> async def risky_operation():
        ...     # 실패할 수 있는 작업
        ...     return await make_api_call()
        >>>
        >>> result = await retry_manager.execute(risky_operation)
    """

    def __init__(self, config: RetryConfig):
        """
        RetryManager 초기화.

        Args:
            config: 재시도 설정
        """
        self.config = config
        self._retry_history: List[RetryAttempt] = []

    async def execute(
        self,
        operation: Callable[[], Any],
        *args,
        **kwargs,
    ) -> T:
        """
        재시도 로직과 함께 작업 실행.

        Args:
            operation: 실행할 비동기 함수
            *args: operation에 전달할 위치 인자
            **kwargs: operation에 전달할 키워드 인자

        Returns:
            operation의 반환값

        Raises:
            마지막 시도에서 발생한 예외
        """
        last_exception: Optional[Exception] = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                if self.config.log_attempts and attempt > 1:
                    logger.info(f"Retry attempt {attempt}/{self.config.max_retries}")

                # 작업 실행
                result = await operation(*args, **kwargs)
                return result

            except Exception as e:
                # 예외 분류
                classification = self._classify_exception(e)

                if classification == ErrorClassification.NON_RETRYABLE:
                    # 재시도 불가능한 에러
                    if self.config.log_attempts:
                        logger.error(f"Non-retryable error: {type(e).__name__}: {e}")
                    raise

                if classification == ErrorClassification.SPECIAL:
                    # 특수 처리
                    await self._handle_special_exception(e)

                last_exception = e

                # 마지막 시도인 경우
                if attempt >= self.config.max_retries:
                    if self.config.log_attempts:
                        logger.error(
                            f"Operation failed after {self.config.max_retries} attempts: "
                            f"{type(e).__name__}: {e}"
                        )
                    raise

                # 지연 시간 계산
                delay = self._calculate_delay(attempt)

                # 재시도 기록
                retry_attempt = RetryAttempt(
                    attempt_number=attempt,
                    exception=e,
                    delay=delay,
                    timestamp=datetime.now(),
                )
                self._retry_history.append(retry_attempt)

                # 로깅
                if self.config.log_attempts:
                    logger.warning(
                        f"Retryable error (attempt {attempt}/{self.config.max_retries}): "
                        f"{type(e).__name__}: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )

                # 지연
                await asyncio.sleep(delay)

        # 모든 재시도 실패
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError("Operation failed for unknown reason")

    def _classify_exception(self, exception: Exception) -> ErrorClassification:
        """
        예외를 분류.

        Args:
            exception: 발생한 예외

        Returns:
            ErrorClassification: 예외 분류 결과
        """
        # 재시도 불가능한 예외 (가장 먼저 체크하여 하위 클래스 우선 처리)
        if self.config.non_retryable_exceptions:
            for exc_type in self.config.non_retryable_exceptions:
                if isinstance(exception, exc_type):
                    return ErrorClassification.NON_RETRYABLE

        # 특수 처리 예외
        if self.config.special_handlers:
            for exc_type in self.config.special_handlers.keys():
                if isinstance(exception, exc_type):
                    return ErrorClassification.SPECIAL

        # 재시도 가능한 예외
        if self.config.retryable_exceptions:
            for exc_type in self.config.retryable_exceptions:
                if isinstance(exception, exc_type):
                    return ErrorClassification.RETRYABLE

        # 기본값: 재시도 불가능
        # (명시적으로 재시도 가능하다고 지정되지 않은 예외는 재시도하지 않음)
        return ErrorClassification.NON_RETRYABLE

    async def _handle_special_exception(self, exception: Exception):
        """
        특수 처리가 필요한 예외 처리.

        Args:
            exception: 발생한 예외
        """
        if not self.config.special_handlers:
            return

        for exc_type, handler in self.config.special_handlers.items():
            if isinstance(exception, exc_type):
                if asyncio.iscoroutinefunction(handler):
                    await handler(exception)
                else:
                    handler(exception)
                break

    def _calculate_delay(self, attempt: int) -> float:
        """
        재시도 지연 시간 계산.

        Args:
            attempt: 시도 번호 (1부터 시작)

        Returns:
            float: 지연 시간 (초)
        """
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
                delay = self.config.custom_delays[-1] if self.config.custom_delays else 1.0

        else:
            delay = self.config.base_delay

        # 최대 지연 시간 제한
        return min(delay, self.config.max_delay)

    def get_retry_history(self) -> List[RetryAttempt]:
        """
        재시도 히스토리 조회.

        Returns:
            List[RetryAttempt]: 재시도 시도 목록
        """
        return self._retry_history.copy()

    def clear_history(self):
        """재시도 히스토리 초기화."""
        self._retry_history.clear()

    def get_statistics(self) -> dict:
        """
        재시도 통계 조회.

        Returns:
            dict: 재시도 통계 정보
                - total_attempts: 총 재시도 횟수
                - total_delay: 총 지연 시간
                - avg_delay: 평균 지연 시간
                - exception_counts: 예외 타입별 발생 횟수
        """
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
