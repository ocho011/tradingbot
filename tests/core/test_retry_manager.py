"""
Tests for RetryManager.
"""

import pytest

from src.core.retry_manager import (
    RetryManager,
    RetryConfig,
    RetryStrategy,
    ErrorClassification,
    RetryAttempt,
)


# 테스트용 예외 클래스들
class RetryableError(Exception):
    """재시도 가능한 테스트 에러."""
    pass


class NonRetryableError(Exception):
    """재시도 불가능한 테스트 에러."""
    pass


class SpecialError(Exception):
    """특수 처리가 필요한 테스트 에러."""
    pass


class TestRetryConfig:
    """RetryConfig 테스트."""

    def test_default_config(self):
        """기본 설정 테스트."""
        config = RetryConfig()

        assert config.max_retries == 3
        assert config.strategy == RetryStrategy.EXPONENTIAL
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.log_attempts is True

    def test_custom_config(self):
        """사용자 정의 설정 테스트."""
        config = RetryConfig(
            max_retries=5,
            strategy=RetryStrategy.LINEAR,
            base_delay=2.0,
            max_delay=30.0,
        )

        assert config.max_retries == 5
        assert config.strategy == RetryStrategy.LINEAR
        assert config.base_delay == 2.0
        assert config.max_delay == 30.0

    def test_invalid_max_retries(self):
        """유효하지 않은 max_retries 검증."""
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            RetryConfig(max_retries=-1)

    def test_invalid_base_delay(self):
        """유효하지 않은 base_delay 검증."""
        with pytest.raises(ValueError, match="base_delay must be positive"):
            RetryConfig(base_delay=0)

    def test_invalid_max_delay(self):
        """유효하지 않은 max_delay 검증."""
        with pytest.raises(ValueError, match="max_delay must be >= base_delay"):
            RetryConfig(base_delay=10.0, max_delay=5.0)

    def test_custom_strategy_without_delays(self):
        """CUSTOM 전략에 delays 없이 생성 시 에러."""
        with pytest.raises(ValueError, match="custom_delays required"):
            RetryConfig(strategy=RetryStrategy.CUSTOM)

    def test_custom_strategy_with_delays(self):
        """CUSTOM 전략에 delays와 함께 생성."""
        config = RetryConfig(
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[1.0, 2.0, 5.0],
        )
        assert config.custom_delays == [1.0, 2.0, 5.0]


class TestRetryManager:
    """RetryManager 기본 기능 테스트."""

    @pytest.mark.asyncio
    async def test_successful_first_attempt(self):
        """첫 시도에 성공하는 경우."""
        config = RetryConfig(max_retries=3)
        retry_manager = RetryManager(config)

        async def successful_operation():
            return "success"

        result = await retry_manager.execute(successful_operation)
        assert result == "success"
        assert len(retry_manager.get_retry_history()) == 0

    @pytest.mark.asyncio
    async def test_retry_on_retryable_error(self):
        """재시도 가능한 에러 발생 시 재시도."""
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[0.01, 0.02, 0.03],
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        call_count = 0

        async def failing_then_succeeding():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError(f"Attempt {call_count} failed")
            return "success"

        result = await retry_manager.execute(failing_then_succeeding)
        assert result == "success"
        assert call_count == 3
        assert len(retry_manager.get_retry_history()) == 2  # 2번 재시도

    @pytest.mark.asyncio
    async def test_fail_on_non_retryable_error(self):
        """재시도 불가능한 에러 발생 시 즉시 실패."""
        config = RetryConfig(
            max_retries=3,
            retryable_exceptions=[RetryableError],
            non_retryable_exceptions=[NonRetryableError],
        )
        retry_manager = RetryManager(config)

        async def non_retryable_operation():
            raise NonRetryableError("Cannot retry")

        with pytest.raises(NonRetryableError):
            await retry_manager.execute(non_retryable_operation)

        # 재시도 히스토리가 없어야 함 (즉시 실패)
        assert len(retry_manager.get_retry_history()) == 0

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        """모든 재시도 소진 시 예외 발생."""
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[0.01, 0.01, 0.01],
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        call_count = 0

        async def always_failing():
            nonlocal call_count
            call_count += 1
            raise RetryableError(f"Attempt {call_count} failed")

        with pytest.raises(RetryableError):
            await retry_manager.execute(always_failing)

        assert call_count == 3  # max_retries=3이면 총 3번 시도
        assert len(retry_manager.get_retry_history()) == 2  # 마지막 시도는 history에 미포함


class TestRetryStrategies:
    """재시도 전략 테스트."""

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """지수 백오프 전략 테스트."""
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.EXPONENTIAL,
            base_delay=1.0,
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        call_count = 0

        async def always_failing():
            nonlocal call_count
            call_count += 1
            raise RetryableError(f"Attempt {call_count}")

        with pytest.raises(RetryableError):
            await retry_manager.execute(always_failing)

        history = retry_manager.get_retry_history()
        assert len(history) == 2  # 마지막 시도는 history에 미포함
        # 지수 백오프: 1초, 2초
        assert history[0].delay == 1.0
        assert history[1].delay == 2.0

    @pytest.mark.asyncio
    async def test_linear_backoff(self):
        """선형 백오프 전략 테스트."""
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.LINEAR,
            base_delay=1.0,
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        async def always_failing():
            raise RetryableError("Failed")

        with pytest.raises(RetryableError):
            await retry_manager.execute(always_failing)

        history = retry_manager.get_retry_history()
        # 선형 증가: 1초, 2초 (마지막 시도는 history 미포함)
        assert history[0].delay == 1.0
        assert history[1].delay == 2.0

    @pytest.mark.asyncio
    async def test_fixed_delay(self):
        """고정 지연 전략 테스트."""
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.FIXED,
            base_delay=2.0,
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        async def always_failing():
            raise RetryableError("Failed")

        with pytest.raises(RetryableError):
            await retry_manager.execute(always_failing)

        history = retry_manager.get_retry_history()
        # 고정 간격: 2초, 2초, 2초
        assert all(attempt.delay == 2.0 for attempt in history)

    @pytest.mark.asyncio
    async def test_custom_delays(self):
        """사용자 정의 지연 전략 테스트."""
        custom_delays = [0.5, 1.0, 2.5]
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=custom_delays,
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        async def always_failing():
            raise RetryableError("Failed")

        with pytest.raises(RetryableError):
            await retry_manager.execute(always_failing)

        history = retry_manager.get_retry_history()
        # max_retries=3이면 총 3번 시도, 마지막 시도는 history에 미포함
        assert len(history) == 2
        assert history[0].delay == 0.5
        assert history[1].delay == 1.0

    @pytest.mark.asyncio
    async def test_max_delay_limit(self):
        """최대 지연 시간 제한 테스트."""
        config = RetryConfig(
            max_retries=5,
            strategy=RetryStrategy.EXPONENTIAL,
            base_delay=1.0,
            max_delay=5.0,  # 최대 5초
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        async def always_failing():
            raise RetryableError("Failed")

        with pytest.raises(RetryableError):
            await retry_manager.execute(always_failing)

        history = retry_manager.get_retry_history()
        # max_retries=5이면 총 5번 시도, 마지막 시도는 history에 미포함
        # 지수 백오프지만 5초 제한: 1, 2, 4, 5
        assert len(history) == 4
        assert history[0].delay == 1.0
        assert history[1].delay == 2.0
        assert history[2].delay == 4.0
        assert history[3].delay == 5.0  # 8초 → 5초로 제한


class TestSpecialHandlers:
    """특수 핸들러 테스트."""

    @pytest.mark.asyncio
    async def test_special_handler_called(self):
        """특수 핸들러가 호출되는지 테스트."""
        handler_called = False

        async def special_handler(exception):
            nonlocal handler_called
            handler_called = True

        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[0.01, 0.01, 0.01],
            special_handlers={SpecialError: special_handler},
        )
        retry_manager = RetryManager(config)

        call_count = 0

        async def operation_with_special_error():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise SpecialError("Special handling needed")
            return "success"

        result = await retry_manager.execute(operation_with_special_error)
        assert result == "success"
        assert handler_called is True

    @pytest.mark.asyncio
    async def test_sync_special_handler(self):
        """동기 특수 핸들러 테스트."""
        handler_called = False

        def sync_special_handler(exception):
            nonlocal handler_called
            handler_called = True

        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[0.01, 0.01, 0.01],
            special_handlers={SpecialError: sync_special_handler},
        )
        retry_manager = RetryManager(config)

        async def operation_with_special_error():
            raise SpecialError("Special handling needed")

        with pytest.raises(SpecialError):
            await retry_manager.execute(operation_with_special_error)

        assert handler_called is True


class TestRetryHistory:
    """재시도 히스토리 및 통계 테스트."""

    @pytest.mark.asyncio
    async def test_retry_history_tracking(self):
        """재시도 히스토리 추적 테스트."""
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[0.01, 0.02, 0.03],
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        call_count = 0

        async def failing_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError(f"Attempt {call_count}")
            return "success"

        await retry_manager.execute(failing_operation)

        history = retry_manager.get_retry_history()
        # 3번 시도 중 2번 실패하고 3번째에 성공 -> 2개의 실패만 history에 기록
        assert len(history) == 2

        # 각 시도마다 RetryAttempt 객체 확인
        for i, attempt in enumerate(history, 1):
            assert attempt.attempt_number == i
            assert isinstance(attempt.exception, RetryableError)
            assert attempt.timestamp is not None

    @pytest.mark.asyncio
    async def test_get_statistics(self):
        """재시도 통계 조회 테스트."""
        config = RetryConfig(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[0.01, 0.02, 0.03],
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        async def always_failing():
            raise RetryableError("Failed")

        with pytest.raises(RetryableError):
            await retry_manager.execute(always_failing)

        stats = retry_manager.get_statistics()
        # max_retries=3이면 총 3번 시도하지만 마지막 실패는 history에 미포함
        assert stats["total_attempts"] == 2
        assert stats["total_delay"] == 0.03  # 0.01 + 0.02
        assert stats["avg_delay"] == 0.015  # 0.03 / 2
        assert stats["exception_counts"]["RetryableError"] == 2

    def test_clear_history(self):
        """히스토리 초기화 테스트."""
        config = RetryConfig()
        retry_manager = RetryManager(config)

        # 히스토리에 직접 추가
        retry_manager._retry_history.append(
            RetryAttempt(1, RetryableError("test"), 1.0, None)
        )
        assert len(retry_manager.get_retry_history()) == 1

        retry_manager.clear_history()
        assert len(retry_manager.get_retry_history()) == 0

    def test_empty_statistics(self):
        """빈 히스토리의 통계 테스트."""
        config = RetryConfig()
        retry_manager = RetryManager(config)

        stats = retry_manager.get_statistics()
        assert stats["total_attempts"] == 0
        assert stats["total_delay"] == 0.0
        assert stats["avg_delay"] == 0.0
        assert stats["exception_counts"] == {}


class TestErrorClassification:
    """에러 분류 테스트."""

    def test_classify_retryable_exception(self):
        """재시도 가능한 예외 분류."""
        config = RetryConfig(
            retryable_exceptions=[RetryableError],
            non_retryable_exceptions=[NonRetryableError],
        )
        retry_manager = RetryManager(config)

        classification = retry_manager._classify_exception(RetryableError())
        assert classification == ErrorClassification.RETRYABLE

    def test_classify_non_retryable_exception(self):
        """재시도 불가능한 예외 분류."""
        config = RetryConfig(
            retryable_exceptions=[RetryableError],
            non_retryable_exceptions=[NonRetryableError],
        )
        retry_manager = RetryManager(config)

        classification = retry_manager._classify_exception(NonRetryableError())
        assert classification == ErrorClassification.NON_RETRYABLE

    def test_classify_special_exception(self):
        """특수 처리가 필요한 예외 분류."""
        def dummy_handler(e):
            pass

        config = RetryConfig(
            special_handlers={SpecialError: dummy_handler},
        )
        retry_manager = RetryManager(config)

        classification = retry_manager._classify_exception(SpecialError())
        assert classification == ErrorClassification.SPECIAL

    def test_classify_unlisted_exception(self):
        """목록에 없는 예외는 재시도 불가능으로 분류."""
        config = RetryConfig(
            retryable_exceptions=[RetryableError],
        )
        retry_manager = RetryManager(config)

        # ValueError는 명시적으로 retryable에 없으므로 NON_RETRYABLE
        classification = retry_manager._classify_exception(ValueError())
        assert classification == ErrorClassification.NON_RETRYABLE
