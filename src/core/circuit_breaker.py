"""
Circuit Breaker Pattern Implementation
Provides fault tolerance and prevents cascading failures.
"""

import time
import logging
from enum import Enum
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from threading import Lock
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Fault detected, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5  # Number of failures before opening
    success_threshold: int = 2  # Number of successes in half-open to close
    timeout: float = 60.0  # Seconds to wait before trying half-open
    window_size: int = 100  # Size of rolling window for failure rate
    failure_rate_threshold: float = 0.5  # Failure rate to open circuit (0.0-1.0)

    # Advanced settings
    half_open_max_calls: int = 1  # Max concurrent calls in half-open state
    slow_call_threshold: float = 5.0  # Seconds - calls slower than this are failures
    minimum_calls: int = 10  # Minimum calls before checking failure rate


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_changes: int = 0
    current_state: CircuitState = CircuitState.CLOSED

    # Rolling window for recent calls
    recent_calls: deque = field(default_factory=lambda: deque(maxlen=100))

    def record_success(self, duration: float):
        """Record successful call."""
        self.total_calls += 1
        self.successful_calls += 1
        self.last_success_time = time.time()
        self.recent_calls.append(("success", duration, time.time()))

    def record_failure(self, duration: float):
        """Record failed call."""
        self.total_calls += 1
        self.failed_calls += 1
        self.last_failure_time = time.time()
        self.recent_calls.append(("failure", duration, time.time()))

    def record_rejection(self):
        """Record rejected call."""
        self.rejected_calls += 1
        self.recent_calls.append(("rejected", 0, time.time()))

    def get_failure_rate(self) -> float:
        """Calculate current failure rate from recent calls."""
        if not self.recent_calls:
            return 0.0

        failures = sum(1 for call_type, _, _ in self.recent_calls if call_type == "failure")
        return failures / len(self.recent_calls)

    def get_slow_call_rate(self, threshold: float) -> float:
        """Calculate rate of slow calls."""
        if not self.recent_calls:
            return 0.0

        slow_calls = sum(
            1 for call_type, duration, _ in self.recent_calls
            if call_type in ("success", "failure") and duration > threshold
        )
        return slow_calls / len(self.recent_calls)


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, message: str, stats: Optional[CircuitBreakerStats] = None):
        super().__init__(message)
        self.stats = stats


class CircuitBreaker:
    """
    Circuit Breaker implementation for fault tolerance.

    States:
    - CLOSED: Normal operation, all calls go through
    - OPEN: Too many failures, calls fail immediately
    - HALF_OPEN: Testing if service recovered, limited calls allowed

    Example:
        breaker = CircuitBreaker("api_service")

        @breaker
        def call_api():
            return requests.get("https://api.example.com")

        try:
            result = call_api()
        except CircuitBreakerError:
            # Circuit is open, service is down
            return fallback_response()
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Identifier for this circuit breaker
            config: Configuration settings
            on_state_change: Callback when state changes (old_state, new_state)
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._opened_at: Optional[float] = None
        self._half_open_calls = 0

        self._lock = Lock()
        self.stats = CircuitBreakerStats()

        logger.info(
            f"Circuit breaker '{name}' initialized with "
            f"failure_threshold={self.config.failure_threshold}, "
            f"timeout={self.config.timeout}s"
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state

    def _change_state(self, new_state: CircuitState):
        """Change circuit state and invoke callback."""
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state
        self.stats.current_state = new_state
        self.stats.state_changes += 1

        logger.warning(
            f"Circuit breaker '{self.name}' state changed: {old_state.value} -> {new_state.value}"
        )

        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()

        if self.on_state_change:
            try:
                self.on_state_change(old_state, new_state)
            except Exception as e:
                logger.error(f"Error in state change callback: {e}")

    def _should_open(self) -> bool:
        """Check if circuit should open based on failure criteria."""
        # Check consecutive failures
        if self._failure_count >= self.config.failure_threshold:
            return True

        # Check failure rate if we have enough calls
        if len(self.stats.recent_calls) >= self.config.minimum_calls:
            failure_rate = self.stats.get_failure_rate()
            if failure_rate >= self.config.failure_rate_threshold:
                logger.warning(
                    f"Circuit breaker '{self.name}' failure rate {failure_rate:.2%} "
                    f"exceeds threshold {self.config.failure_rate_threshold:.2%}"
                )
                return True

        # Check slow call rate
        slow_call_rate = self.stats.get_slow_call_rate(self.config.slow_call_threshold)
        if slow_call_rate >= self.config.failure_rate_threshold:
            logger.warning(
                f"Circuit breaker '{self.name}' slow call rate {slow_call_rate:.2%} "
                f"exceeds threshold"
            )
            return True

        return False

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try half-open state."""
        if self._opened_at is None:
            return False

        return time.time() - self._opened_at >= self.config.timeout

    def _on_success(self, duration: float):
        """Handle successful call."""
        with self._lock:
            self.stats.record_success(duration)

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                self._half_open_calls -= 1

                if self._success_count >= self.config.success_threshold:
                    logger.info(
                        f"Circuit breaker '{self.name}' closing after "
                        f"{self._success_count} successful calls"
                    )
                    self._failure_count = 0
                    self._success_count = 0
                    self._change_state(CircuitState.CLOSED)

            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def _on_failure(self, duration: float, error: Exception):
        """Handle failed call."""
        with self._lock:
            self.stats.record_failure(duration)
            self._failure_count += 1
            self._last_failure_time = time.time()

            logger.warning(
                f"Circuit breaker '{self.name}' recorded failure "
                f"(count: {self._failure_count}): {error}"
            )

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately reopens circuit
                self._half_open_calls -= 1
                logger.warning(
                    f"Circuit breaker '{self.name}' reopening after failure in half-open state"
                )
                self._success_count = 0
                self._change_state(CircuitState.OPEN)

            elif self._state == CircuitState.CLOSED:
                if self._should_open():
                    logger.error(
                        f"Circuit breaker '{self.name}' opening after "
                        f"{self._failure_count} failures"
                    )
                    self._change_state(CircuitState.OPEN)

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Original exception from function
        """
        with self._lock:
            # Check if we should transition to half-open
            if self._state == CircuitState.OPEN and self._should_attempt_reset():
                logger.info(f"Circuit breaker '{self.name}' entering half-open state")
                self._change_state(CircuitState.HALF_OPEN)
                self._success_count = 0

            # Reject call if circuit is open
            if self._state == CircuitState.OPEN:
                self.stats.record_rejection()
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is OPEN",
                    stats=self.stats
                )

            # Limit concurrent calls in half-open state
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self.stats.record_rejection()
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN (max calls reached)",
                        stats=self.stats
                    )
                self._half_open_calls += 1

        # Execute function and measure duration
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            self._on_success(duration)
            return result

        except Exception as e:
            duration = time.time() - start_time
            self._on_failure(duration, e)
            raise

    def __call__(self, func: Callable) -> Callable:
        """Decorator for protecting functions."""
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    def get_stats(self) -> CircuitBreakerStats:
        """Get current statistics."""
        return self.stats

    def reset(self):
        """Manually reset circuit breaker to closed state."""
        with self._lock:
            logger.info(f"Circuit breaker '{self.name}' manually reset")
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._change_state(CircuitState.CLOSED)


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    def register(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
    ) -> CircuitBreaker:
        """Register or get circuit breaker."""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, config, on_state_change)
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name."""
        return self._breakers.get(name)

    def get_all_stats(self) -> dict[str, CircuitBreakerStats]:
        """Get statistics for all circuit breakers."""
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self):
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()


# Global registry
_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None,
    on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
) -> CircuitBreaker:
    """Get or create circuit breaker from global registry."""
    return _registry.register(name, config, on_state_change)
