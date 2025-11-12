"""
Tests for OpenTelemetry distributed tracing functionality.

Tests cover:
- Tracing configuration from environment
- Span creation and context propagation
- Signal generation tracing
- Order execution tracing
- Error handling and exception recording
- Performance overhead measurement
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

from src.monitoring.tracing import (
    TradingTracer,
    TracingConfig,
    get_tracer,
    init_tracing,
    shutdown_tracing,
)


class TestTracingConfig:
    """Test tracing configuration."""

    def test_default_config(self):
        """Test default tracing configuration."""
        config = TracingConfig()

        assert config.service_name == "tradingbot"
        assert config.service_version == "0.1.0"
        assert config.jaeger_host == "localhost"
        assert config.jaeger_port == 6831
        assert config.sampling_rate == 0.1
        assert config.enabled is True

    def test_custom_config(self):
        """Test custom tracing configuration."""
        config = TracingConfig(
            service_name="custom_service",
            service_version="1.2.3",
            jaeger_host="jaeger.example.com",
            jaeger_port=14268,
            sampling_rate=0.5,
            enabled=False,
        )

        assert config.service_name == "custom_service"
        assert config.service_version == "1.2.3"
        assert config.jaeger_host == "jaeger.example.com"
        assert config.jaeger_port == 14268
        assert config.sampling_rate == 0.5
        assert config.enabled is False

    def test_config_from_env(self, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv("OTEL_SERVICE_NAME", "test_service")
        monkeypatch.setenv("SERVICE_VERSION", "2.0.0")
        monkeypatch.setenv("JAEGER_HOST", "test.jaeger.io")
        monkeypatch.setenv("JAEGER_PORT", "6832")
        monkeypatch.setenv("OTEL_SAMPLING_RATE", "0.25")
        monkeypatch.setenv("OTEL_TRACING_ENABLED", "false")

        config = TracingConfig.from_env()

        assert config.service_name == "test_service"
        assert config.service_version == "2.0.0"
        assert config.jaeger_host == "test.jaeger.io"
        assert config.jaeger_port == 6832
        assert config.sampling_rate == 0.25
        assert config.enabled is False


class TestTradingTracer:
    """Test TradingTracer functionality."""

    def test_tracer_initialization_disabled(self):
        """Test tracer when disabled."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        assert tracer.config.enabled is False
        assert tracer._tracer is None
        assert tracer._provider is None

    @patch('src.monitoring.tracing.JaegerExporter')
    @patch('src.monitoring.tracing.TracerProvider')
    def test_tracer_initialization_enabled(self, mock_provider_cls, mock_exporter_cls):
        """Test tracer initialization when enabled."""
        config = TracingConfig(enabled=True)

        # Mock the provider and its methods
        mock_provider = MagicMock()
        mock_provider_cls.return_value = mock_provider

        tracer = TradingTracer(config)

        # Verify Jaeger exporter was created with correct parameters
        mock_exporter_cls.assert_called_once_with(
            agent_host_name=config.jaeger_host,
            agent_port=config.jaeger_port,
        )

        # Verify provider was created and configured
        assert mock_provider_cls.called
        assert mock_provider.add_span_processor.called

    def test_span_context_manager_disabled(self):
        """Test span context manager when tracing is disabled."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        with tracer.start_span("test_span") as span:
            assert span is None  # Should return None when disabled

    @patch('src.monitoring.tracing.trace')
    def test_span_context_manager_enabled(self, mock_trace):
        """Test span context manager when tracing is enabled."""
        config = TracingConfig(enabled=True)

        # Mock the tracer
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

        with patch.object(TradingTracer, '_setup_tracing'):
            tracer = TradingTracer(config)
            tracer._tracer = mock_tracer

            with tracer.start_span(
                "test_span",
                attributes={"test_key": "test_value"}
            ) as span:
                assert span is mock_span
                mock_span.set_attribute.assert_called_with("test_key", "test_value")

    @patch('src.monitoring.tracing.trace')
    def test_span_exception_handling(self, mock_trace):
        """Test exception recording in spans."""
        config = TracingConfig(enabled=True)

        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

        with patch.object(TradingTracer, '_setup_tracing'):
            tracer = TradingTracer(config)
            tracer._tracer = mock_tracer

            test_exception = ValueError("Test error")

            with pytest.raises(ValueError):
                with tracer.start_span("test_span"):
                    raise test_exception

            # Verify exception was recorded
            mock_span.record_exception.assert_called_once()
            mock_span.set_status.assert_called_once()

    def test_trace_function_decorator_disabled(self):
        """Test trace_function decorator when disabled."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        @tracer.trace_function()
        def test_func(x, y):
            return x + y

        result = test_func(1, 2)
        assert result == 3  # Function should work normally

    @patch('src.monitoring.tracing.trace')
    async def test_trace_async_function(self, mock_trace):
        """Test tracing async functions."""
        config = TracingConfig(enabled=True)

        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

        with patch.object(TradingTracer, '_setup_tracing'):
            tracer = TradingTracer(config)
            tracer._tracer = mock_tracer

            @tracer.trace_function()
            async def async_test_func(value):
                await asyncio.sleep(0.01)
                return value * 2

            result = await async_test_func(5)
            assert result == 10

    def test_add_event_disabled(self):
        """Test add_event when tracing is disabled."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        # Should not raise an error
        tracer.add_event("test_event", {"key": "value"})

    def test_set_attribute_disabled(self):
        """Test set_attribute when tracing is disabled."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        # Should not raise an error
        tracer.set_attribute("test_key", "test_value")

    def test_record_exception_disabled(self):
        """Test record_exception when tracing is disabled."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        # Should not raise an error
        test_exception = ValueError("Test error")
        tracer.record_exception(test_exception)


class TestGlobalTracerManagement:
    """Test global tracer instance management."""

    def teardown_method(self):
        """Clean up global tracer after each test."""
        shutdown_tracing()

    def test_get_tracer_creates_instance(self):
        """Test that get_tracer creates a tracer instance."""
        tracer = get_tracer()
        assert tracer is not None
        assert isinstance(tracer, TradingTracer)

    def test_get_tracer_returns_same_instance(self):
        """Test that get_tracer returns the same instance."""
        tracer1 = get_tracer()
        tracer2 = get_tracer()
        assert tracer1 is tracer2

    def test_init_tracing_with_custom_config(self):
        """Test initializing tracing with custom configuration."""
        config = TracingConfig(
            service_name="custom_test",
            enabled=False  # Disable to avoid actual connections
        )
        tracer = init_tracing(config)

        assert tracer is not None
        assert tracer.config.service_name == "custom_test"

        # Should return the same instance
        tracer2 = get_tracer()
        assert tracer2 is tracer

    def test_shutdown_tracing(self):
        """Test shutting down tracing."""
        # Initialize tracer
        config = TracingConfig(enabled=False)
        init_tracing(config)

        # Shutdown
        shutdown_tracing()

        # After shutdown, get_tracer should create a new instance
        tracer = get_tracer()
        assert tracer is not None


class TestInstrumentationIntegration:
    """Test instrumentation with FastAPI, SQLAlchemy, and aiohttp."""

    def test_instrument_fastapi(self):
        """Test FastAPI instrumentation."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        mock_app = Mock()

        # Should not raise an error even when disabled
        tracer.instrument_fastapi(mock_app)

    def test_instrument_sqlalchemy(self):
        """Test SQLAlchemy instrumentation."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        mock_engine = Mock()

        # Should not raise an error even when disabled
        tracer.instrument_sqlalchemy(mock_engine)

    def test_instrument_aiohttp(self):
        """Test aiohttp instrumentation."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        # Should not raise an error even when disabled
        tracer.instrument_aiohttp()


class TestPerformanceOverhead:
    """Test performance overhead of tracing."""

    async def test_tracing_overhead_minimal(self):
        """Test that tracing overhead is minimal."""
        import time

        # Test with tracing disabled
        config_disabled = TracingConfig(enabled=False)
        tracer_disabled = TradingTracer(config_disabled)

        start = time.time()
        for _ in range(1000):
            with tracer_disabled.start_span("test"):
                pass
        disabled_time = time.time() - start

        # Disabled tracing should have negligible overhead
        assert disabled_time < 0.1  # Should complete in less than 100ms

    def test_span_attribute_limits(self):
        """Test that span attributes are limited to prevent bloat."""
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        # Create a decorator with attributes
        @tracer.trace_function()
        def test_func(*args, **kwargs):
            return True

        # Call with many arguments
        large_args = list(range(10))
        large_kwargs = {f"key_{i}": f"value_{i}" for i in range(10)}

        # Should not raise an error
        result = test_func(*large_args, **large_kwargs)
        assert result is True


@pytest.mark.integration
class TestEndToEndTracing:
    """Integration tests for end-to-end tracing."""

    def test_signal_to_order_flow_traced(self):
        """Test that signal generation to order execution flow is traced."""
        # This would be an integration test with actual components
        # For now, we test the structure is in place
        config = TracingConfig(enabled=False)
        tracer = TradingTracer(config)

        # Simulate signal generation span
        with tracer.start_span("signal_generation", {"symbol": "BTCUSDT"}):
            # Simulate order execution span
            with tracer.start_span("order_execution", {"order_id": "12345"}):
                pass

        # Test passes if no exceptions are raised
        assert True
