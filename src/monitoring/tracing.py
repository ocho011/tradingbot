"""
OpenTelemetry distributed tracing configuration and utilities.

Provides comprehensive tracing for the trading system including:
- Signal generation to order execution workflow tracing
- Exchange API call instrumentation
- Database operation tracking
- Custom span creation and tagging utilities
- Performance-optimized sampling strategies
"""

import logging
import os
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Optional

from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ParentBased,
    TraceIdRatioBased,
)
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)


class TracingConfig:
    """Configuration for OpenTelemetry tracing."""

    def __init__(
        self,
        service_name: str = "tradingbot",
        service_version: str = "0.1.0",
        jaeger_host: str = "localhost",
        jaeger_port: int = 6831,
        sampling_rate: float = 0.1,
        enabled: bool = True,
    ) -> None:
        """
        Initialize tracing configuration.

        Args:
            service_name: Name of the service for trace identification
            service_version: Version of the service
            jaeger_host: Jaeger agent host
            jaeger_port: Jaeger agent port (6831 for UDP, 14268 for HTTP)
            sampling_rate: Sampling rate (0.0 to 1.0). 0.1 = 10% of traces
            enabled: Enable or disable tracing
        """
        self.service_name = service_name
        self.service_version = service_version
        self.jaeger_host = jaeger_host
        self.jaeger_port = jaeger_port
        self.sampling_rate = sampling_rate
        self.enabled = enabled

    @classmethod
    def from_env(cls) -> "TracingConfig":
        """Create configuration from environment variables."""
        return cls(
            service_name=os.getenv("OTEL_SERVICE_NAME", "tradingbot"),
            service_version=os.getenv("SERVICE_VERSION", "0.1.0"),
            jaeger_host=os.getenv("JAEGER_HOST", "localhost"),
            jaeger_port=int(os.getenv("JAEGER_PORT", "6831")),
            sampling_rate=float(os.getenv("OTEL_SAMPLING_RATE", "0.1")),
            enabled=os.getenv("OTEL_TRACING_ENABLED", "true").lower() == "true",
        )


class TradingTracer:
    """Main tracing class for the trading system."""

    def __init__(self, config: Optional[TracingConfig] = None) -> None:
        """
        Initialize the trading tracer.

        Args:
            config: Tracing configuration. If None, loads from environment.
        """
        self.config = config or TracingConfig.from_env()
        self._tracer: Optional[trace.Tracer] = None
        self._provider: Optional[TracerProvider] = None

        if self.config.enabled:
            self._setup_tracing()

    def _setup_tracing(self) -> None:
        """Setup OpenTelemetry tracing with Jaeger exporter."""
        try:
            # Create resource with service information
            resource = Resource.create(
                {
                    SERVICE_NAME: self.config.service_name,
                    SERVICE_VERSION: self.config.service_version,
                }
            )

            # Create tracer provider with sampling
            sampler = ParentBased(root=TraceIdRatioBased(self.config.sampling_rate))
            self._provider = TracerProvider(resource=resource, sampler=sampler)

            # Configure Jaeger exporter
            jaeger_exporter = JaegerExporter(
                agent_host_name=self.config.jaeger_host,
                agent_port=self.config.jaeger_port,
            )

            # Add batch span processor for performance
            span_processor = BatchSpanProcessor(
                jaeger_exporter,
                max_queue_size=2048,
                schedule_delay_millis=5000,
                max_export_batch_size=512,
            )
            self._provider.add_span_processor(span_processor)

            # Set as global tracer provider
            trace.set_tracer_provider(self._provider)

            # Get tracer instance
            self._tracer = trace.get_tracer(__name__)

            logger.info(
                f"Tracing initialized: service={self.config.service_name}, "
                f"jaeger={self.config.jaeger_host}:{self.config.jaeger_port}, "
                f"sampling={self.config.sampling_rate * 100}%"
            )

        except Exception as e:
            logger.error(f"Failed to initialize tracing: {e}", exc_info=True)
            self.config.enabled = False

    def instrument_fastapi(self, app: Any) -> None:
        """
        Instrument FastAPI application for automatic tracing.

        Args:
            app: FastAPI application instance
        """
        if not self.config.enabled:
            return

        try:
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI instrumentation enabled")
        except Exception as e:
            logger.error(f"Failed to instrument FastAPI: {e}", exc_info=True)

    def instrument_sqlalchemy(self, engine: Any) -> None:
        """
        Instrument SQLAlchemy engine for database tracing.

        Args:
            engine: SQLAlchemy engine instance
        """
        if not self.config.enabled:
            return

        try:
            SQLAlchemyInstrumentor().instrument(engine=engine)
            logger.info("SQLAlchemy instrumentation enabled")
        except Exception as e:
            logger.error(f"Failed to instrument SQLAlchemy: {e}", exc_info=True)

    def instrument_aiohttp(self) -> None:
        """Instrument aiohttp client for HTTP request tracing."""
        if not self.config.enabled:
            return

        try:
            AioHttpClientInstrumentor().instrument()
            logger.info("AioHTTP client instrumentation enabled")
        except Exception as e:
            logger.error(f"Failed to instrument AioHTTP: {e}", exc_info=True)

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        kind: trace.SpanKind = trace.SpanKind.INTERNAL,
    ):
        """
        Context manager for creating spans.

        Args:
            name: Span name
            attributes: Span attributes/tags
            kind: Span kind (INTERNAL, CLIENT, SERVER, etc.)

        Yields:
            Span: The created span

        Example:
            with tracer.start_span("signal_generation", {"symbol": "BTCUSDT"}):
                # Your code here
                pass
        """
        if not self.config.enabled or not self._tracer:
            yield None
            return

        with self._tracer.start_as_current_span(name, kind=kind) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    def trace_function(
        self,
        span_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Callable:
        """
        Decorator for tracing function calls.

        Args:
            span_name: Custom span name. If None, uses function name
            attributes: Static attributes to add to span

        Example:
            @tracer.trace_function(attributes={"component": "signal_generator"})
            async def generate_signal(symbol: str):
                pass
        """

        def decorator(func: Callable) -> Callable:
            if not self.config.enabled:
                return func

            name = span_name or f"{func.__module__}.{func.__name__}"

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                with self.start_span(name, attributes) as span:
                    if span:
                        # Add function arguments as attributes
                        for i, arg in enumerate(args):
                            if i < 3:  # Limit to first 3 args
                                span.set_attribute(f"arg.{i}", str(arg)[:100])
                        for key, value in list(kwargs.items())[:3]:
                            span.set_attribute(f"kwarg.{key}", str(value)[:100])
                    return await func(*args, **kwargs)

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                with self.start_span(name, attributes) as span:
                    if span:
                        for i, arg in enumerate(args):
                            if i < 3:
                                span.set_attribute(f"arg.{i}", str(arg)[:100])
                        for key, value in list(kwargs.items())[:3]:
                            span.set_attribute(f"kwarg.{key}", str(value)[:100])
                    return func(*args, **kwargs)

            # Return appropriate wrapper based on function type
            import asyncio

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    def add_event(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add an event to the current span.

        Args:
            name: Event name
            attributes: Event attributes

        Example:
            tracer.add_event("order_placed", {"order_id": "123", "symbol": "BTCUSDT"})
        """
        if not self.config.enabled:
            return

        span = trace.get_current_span()
        if span and span.is_recording():
            span.add_event(name, attributes or {})

    def set_attribute(self, key: str, value: Any) -> None:
        """
        Set an attribute on the current span.

        Args:
            key: Attribute key
            value: Attribute value
        """
        if not self.config.enabled:
            return

        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute(key, value)

    def record_exception(self, exception: Exception) -> None:
        """
        Record an exception on the current span.

        Args:
            exception: Exception to record
        """
        if not self.config.enabled:
            return

        span = trace.get_current_span()
        if span and span.is_recording():
            span.record_exception(exception)
            span.set_status(Status(StatusCode.ERROR, str(exception)))

    def shutdown(self) -> None:
        """Shutdown tracing and flush remaining spans."""
        if self._provider:
            try:
                self._provider.shutdown()
                logger.info("Tracing shutdown complete")
            except Exception as e:
                logger.error(f"Error during tracing shutdown: {e}", exc_info=True)


# Global tracer instance
_tracer: Optional[TradingTracer] = None


def get_tracer() -> TradingTracer:
    """
    Get or create the global tracer instance.

    Returns:
        TradingTracer: Global tracer instance
    """
    global _tracer
    if _tracer is None:
        _tracer = TradingTracer()
    return _tracer


def init_tracing(config: Optional[TracingConfig] = None) -> TradingTracer:
    """
    Initialize global tracing.

    Args:
        config: Tracing configuration. If None, loads from environment.

    Returns:
        TradingTracer: Initialized tracer instance
    """
    global _tracer
    _tracer = TradingTracer(config)
    return _tracer


def shutdown_tracing() -> None:
    """Shutdown global tracing."""
    global _tracer
    if _tracer:
        _tracer.shutdown()
        _tracer = None
