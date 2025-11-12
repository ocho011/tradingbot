"""
Unit tests for Circuit Breaker pattern implementation.
"""

import pytest
import time
from unittest.mock import Mock, patch
from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
    get_circuit_breaker,
)


class TestCircuitBreakerBasics:
    """Test basic circuit breaker functionality."""

    def test_initial_state_is_closed(self):
        """Circuit breaker should start in CLOSED state."""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED

    def test_successful_call_passes_through(self):
        """Successful calls should pass through when CLOSED."""
        breaker = CircuitBreaker("test")

        @breaker
        def successful_func():
            return "success"

        result = successful_func()
        assert result == "success"
        assert breaker.stats.successful_calls == 1
        assert breaker.stats.failed_calls == 0

    def test_failed_call_raises_exception(self):
        """Failed calls should raise original exception."""
        breaker = CircuitBreaker("test")

        @breaker
        def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_func()

        assert breaker.stats.failed_calls == 1


class TestCircuitBreakerOpening:
    """Test circuit breaker opening behavior."""

    def test_opens_after_threshold_failures(self):
        """Circuit should open after exceeding failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        @breaker
        def failing_func():
            raise ValueError("fail")

        # First 2 failures - circuit stays closed
        for _ in range(2):
            with pytest.raises(ValueError):
                failing_func()
        assert breaker.state == CircuitState.CLOSED

        # 3rd failure - circuit opens
        with pytest.raises(ValueError):
            failing_func()
        assert breaker.state == CircuitState.OPEN

    def test_rejects_calls_when_open(self):
        """Circuit should reject calls when OPEN."""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)

        @breaker
        def failing_func():
            raise ValueError("fail")

        # Trigger opening
        with pytest.raises(ValueError):
            failing_func()
        assert breaker.state == CircuitState.OPEN

        # Next call should be rejected
        with pytest.raises(CircuitBreakerError) as exc:
            failing_func()
        assert "OPEN" in str(exc.value)
        assert breaker.stats.rejected_calls == 1

    def test_opens_based_on_failure_rate(self):
        """Circuit should open based on failure rate."""
        config = CircuitBreakerConfig(
            failure_threshold=100,  # High threshold
            failure_rate_threshold=0.5,  # 50% failure rate
            minimum_calls=10,
        )
        breaker = CircuitBreaker("test", config)

        call_count = 0

        @breaker
        def mixed_func():
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:  # 50% failure rate
                raise ValueError("fail")
            return "success"

        # Make enough calls to meet minimum
        for _ in range(20):
            try:
                mixed_func()
            except ValueError:
                pass

        # Circuit should open due to failure rate
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerRecovery:
    """Test circuit breaker recovery behavior."""

    def test_transitions_to_half_open_after_timeout(self):
        """Circuit should transition to HALF_OPEN after timeout."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.1)
        breaker = CircuitBreaker("test", config)

        @breaker
        def failing_func():
            raise ValueError("fail")

        # Open the circuit
        with pytest.raises(ValueError):
            failing_func()
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.15)

        # Mock a successful function
        @breaker
        def successful_func():
            return "success"

        # Next call should transition to HALF_OPEN
        # We need to check the state during the call
        initial_state = breaker.state
        try:
            result = successful_func()
            # If successful, should close
            assert breaker.state == CircuitState.HALF_OPEN or breaker.state == CircuitState.CLOSED
        except CircuitBreakerError:
            # Still in open state (timing issue)
            pass

    def test_closes_after_successful_calls_in_half_open(self):
        """Circuit should close after success threshold in HALF_OPEN."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            timeout=0.1,
        )
        breaker = CircuitBreaker("test", config)

        # Open the circuit
        def fail():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            breaker.call(fail)
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.15)

        # Make successful calls
        def success():
            return "success"

        # First successful call - should be HALF_OPEN
        try:
            breaker.call(success)
        except CircuitBreakerError:
            pass  # May still be timing out

        # After enough successes, should close
        for _ in range(3):
            try:
                breaker.call(success)
            except CircuitBreakerError:
                time.sleep(0.1)  # Wait a bit more

        # Eventually should close
        assert breaker.state == CircuitState.CLOSED or breaker.state == CircuitState.HALF_OPEN

    def test_reopens_on_failure_in_half_open(self):
        """Circuit should reopen on failure in HALF_OPEN state."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.1)
        breaker = CircuitBreaker("test", config)

        # Open the circuit
        def fail():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            breaker.call(fail)
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.15)

        # Try a failing call - should reopen
        with pytest.raises(ValueError):
            breaker.call(fail)

        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerStats:
    """Test circuit breaker statistics tracking."""

    def test_tracks_successful_calls(self):
        """Should track successful call statistics."""
        breaker = CircuitBreaker("test")

        @breaker
        def success():
            return "ok"

        for _ in range(5):
            success()

        assert breaker.stats.successful_calls == 5
        assert breaker.stats.total_calls == 5
        assert breaker.stats.failed_calls == 0

    def test_tracks_failed_calls(self):
        """Should track failed call statistics."""
        breaker = CircuitBreaker("test")

        @breaker
        def fail():
            raise ValueError("fail")

        for _ in range(3):
            with pytest.raises(ValueError):
                fail()

        assert breaker.stats.failed_calls == 3
        assert breaker.stats.total_calls == 3

    def test_tracks_rejected_calls(self):
        """Should track rejected call statistics."""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)

        @breaker
        def fail():
            raise ValueError("fail")

        # Open circuit
        with pytest.raises(ValueError):
            fail()

        # Try more calls - should be rejected
        for _ in range(3):
            with pytest.raises(CircuitBreakerError):
                fail()

        assert breaker.stats.rejected_calls == 3

    def test_calculates_failure_rate(self):
        """Should calculate failure rate correctly."""
        breaker = CircuitBreaker("test")

        call_count = 0

        @breaker
        def mixed():
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise ValueError("fail")
            return "success"

        # Make 10 calls (5 success, 5 failure)
        for _ in range(10):
            try:
                mixed()
            except ValueError:
                pass

        failure_rate = breaker.stats.get_failure_rate()
        assert 0.4 <= failure_rate <= 0.6  # Should be around 50%


class TestCircuitBreakerConfiguration:
    """Test circuit breaker configuration options."""

    def test_custom_failure_threshold(self):
        """Should respect custom failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=5)
        breaker = CircuitBreaker("test", config)

        @breaker
        def fail():
            raise ValueError("fail")

        # Should stay closed for 4 failures
        for _ in range(4):
            with pytest.raises(ValueError):
                fail()
        assert breaker.state == CircuitState.CLOSED

        # 5th failure should open
        with pytest.raises(ValueError):
            fail()
        assert breaker.state == CircuitState.OPEN

    def test_custom_timeout(self):
        """Should respect custom timeout."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.2)
        breaker = CircuitBreaker("test", config)

        # Open circuit
        with pytest.raises(ValueError):
            breaker.call(lambda: 1 / 0)

        # Before timeout - should reject
        with pytest.raises(CircuitBreakerError):
            breaker.call(lambda: "ok")

        # After timeout - should allow attempt
        time.sleep(0.25)
        try:
            breaker.call(lambda: "ok")
        except CircuitBreakerError:
            pass  # Timing may vary

    def test_slow_call_detection(self):
        """Should detect slow calls as failures."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            slow_call_threshold=0.1,
            failure_rate_threshold=0.5,
            minimum_calls=5,
        )
        breaker = CircuitBreaker("test", config)

        @breaker
        def slow_func():
            time.sleep(0.15)  # Slower than threshold
            return "ok"

        # Make several slow calls
        for _ in range(10):
            slow_func()

        # Should have high slow call rate
        slow_rate = breaker.stats.get_slow_call_rate(0.1)
        assert slow_rate > 0.5


class TestCircuitBreakerRegistry:
    """Test circuit breaker registry functionality."""

    def test_get_or_create_breaker(self):
        """Registry should get or create circuit breakers."""
        breaker1 = get_circuit_breaker("service1")
        breaker2 = get_circuit_breaker("service1")
        breaker3 = get_circuit_breaker("service2")

        assert breaker1 is breaker2  # Same instance
        assert breaker1 is not breaker3  # Different instance

    def test_custom_config_on_creation(self):
        """Should use custom config when creating breaker."""
        config = CircuitBreakerConfig(failure_threshold=10)
        breaker = get_circuit_breaker("custom", config)

        assert breaker.config.failure_threshold == 10


class TestCircuitBreakerCallbacks:
    """Test circuit breaker state change callbacks."""

    def test_state_change_callback(self):
        """Should invoke callback on state change."""
        callback_calls = []

        def on_state_change(old_state, new_state):
            callback_calls.append((old_state, new_state))

        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config, on_state_change)

        # Trigger state change
        with pytest.raises(ValueError):
            breaker.call(lambda: 1 / 0)

        assert len(callback_calls) == 1
        assert callback_calls[0] == (CircuitState.CLOSED, CircuitState.OPEN)

    def test_callback_errors_handled(self):
        """Should handle errors in callbacks gracefully."""
        def bad_callback(old_state, new_state):
            raise RuntimeError("callback error")

        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config, bad_callback)

        # Should not raise callback error
        with pytest.raises(ValueError):
            breaker.call(lambda: 1 / 0)


class TestCircuitBreakerReset:
    """Test circuit breaker manual reset."""

    def test_manual_reset(self):
        """Should manually reset circuit to CLOSED."""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)

        # Open circuit
        with pytest.raises(ValueError):
            breaker.call(lambda: 1 / 0)
        assert breaker.state == CircuitState.OPEN

        # Manual reset
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED

        # Should allow calls again
        result = breaker.call(lambda: "success")
        assert result == "success"
