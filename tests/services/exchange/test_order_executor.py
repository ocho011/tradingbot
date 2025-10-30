"""
Tests for OrderExecutor - 비동기 주문 실행 시스템.

테스트 범위:
- 주문 파라미터 검증
- 시장가/지정가/손절/익절 주문 실행
- 에러 처리 및 재시도 로직
- 이벤트 발행 검증
- 타임스탬프 동기화
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from ccxt.base.errors import (
    NetworkError,
    ExchangeError,
    InvalidOrder,
    InsufficientFunds,
    OrderNotFound,
)

from src.services.exchange.order_executor import (
    OrderExecutor,
    OrderRequest,
    OrderResponse,
    OrderStatus,
)
from src.core.constants import OrderSide, OrderType, PositionSide
from src.core.events import EventBus, EventType


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_exchange():
    """Mock CCXT exchange 인스턴스."""
    exchange = AsyncMock()
    exchange.create_order = AsyncMock()
    exchange.cancel_order = AsyncMock()
    exchange.fetch_order = AsyncMock()
    exchange.load_time_difference = AsyncMock()
    return exchange


@pytest.fixture
def event_bus():
    """Mock EventBus."""
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def order_executor(mock_exchange, event_bus):
    """OrderExecutor 인스턴스."""
    return OrderExecutor(
        exchange=mock_exchange,
        event_bus=event_bus,
        max_retries=3,
        retry_delay=0.1,  # 빠른 테스트를 위해 짧게 설정
    )


# ============================================================================
# OrderRequest Tests
# ============================================================================


class TestOrderRequest:
    """OrderRequest 검증 테스트."""

    def test_market_order_request_valid(self):
        """시장가 주문 요청 검증 - 정상."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=Decimal("0.001"),
        )

        # 검증 통과해야 함
        request.validate()

        assert request.symbol == "BTCUSDT"
        assert request.order_type == OrderType.MARKET
        assert request.side == OrderSide.BUY
        assert request.quantity == Decimal("0.001")

    def test_limit_order_request_valid(self):
        """지정가 주문 요청 검증 - 정상."""
        request = OrderRequest(
            symbol="ETHUSDT",
            order_type=OrderType.LIMIT,
            side=OrderSide.SELL,
            quantity=Decimal("1.5"),
            price=Decimal("2000.50"),
            time_in_force="GTC",
        )

        request.validate()

        assert request.price == Decimal("2000.50")
        assert request.time_in_force == "GTC"

    def test_stop_loss_order_request_valid(self):
        """손절 주문 요청 검증 - 정상."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.STOP_LOSS,
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_price=Decimal("30000"),
            reduce_only=True,
        )

        request.validate()

        assert request.stop_price == Decimal("30000")
        assert request.reduce_only is True

    def test_invalid_quantity_raises_error(self):
        """수량이 0 이하인 경우 검증 실패."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=Decimal("0"),  # Invalid
        )

        with pytest.raises(ValueError, match="Quantity must be positive"):
            request.validate()

    def test_limit_order_without_price_raises_error(self):
        """지정가 주문에 가격이 없는 경우 검증 실패."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=None,  # Missing price
        )

        with pytest.raises(ValueError, match="LIMIT order requires a valid price"):
            request.validate()

    def test_stop_loss_order_without_stop_price_raises_error(self):
        """손절 주문에 스톱 가격이 없는 경우 검증 실패."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.STOP_LOSS,
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_price=None,  # Missing stop_price
        )

        with pytest.raises(ValueError, match="requires a valid stop_price"):
            request.validate()

    def test_invalid_time_in_force_raises_error(self):
        """유효하지 않은 time_in_force 값."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("30000"),
            time_in_force="INVALID",
        )

        with pytest.raises(ValueError, match="Invalid time_in_force"):
            request.validate()

    def test_post_only_without_gtc_raises_error(self):
        """Post-only 주문은 GTC만 허용."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("30000"),
            time_in_force="IOC",
            post_only=True,
        )

        with pytest.raises(ValueError, match="Post-only orders must use GTC"):
            request.validate()

    def test_to_dict_conversion(self):
        """OrderRequest를 딕셔너리로 변환."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=Decimal("0.5"),
            price=Decimal("35000.50"),
            position_side=PositionSide.LONG,
            reduce_only=True,
        )

        data = request.to_dict()

        assert data["symbol"] == "BTCUSDT"
        assert data["type"] == "LIMIT"
        assert data["side"] == "BUY"
        assert data["quantity"] == 0.5
        assert data["price"] == 35000.50
        assert data["positionSide"] == "LONG"
        assert data["reduceOnly"] is True


# ============================================================================
# OrderResponse Tests
# ============================================================================


class TestOrderResponse:
    """OrderResponse 파싱 테스트."""

    def test_order_response_parsing(self):
        """거래소 응답 파싱."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        )

        raw_response = {
            "id": "12345",
            "clientOrderId": "client-123",
            "status": "closed",
            "symbol": "BTCUSDT",
            "type": "market",
            "side": "buy",
            "price": 30000.0,
            "amount": 0.1,
            "filled": 0.1,
            "remaining": 0.0,
            "average": 30000.0,
            "timestamp": 1234567890000,
            "fee": {"cost": 3.0, "currency": "USDT"},
        }

        response = OrderResponse(raw_response, request)

        assert response.order_id == "12345"
        assert response.status == OrderStatus.FILLED
        assert response.symbol == "BTCUSDT"
        assert response.filled_quantity == Decimal("0.1")
        assert response.average_price == Decimal("30000.0")
        assert response.is_filled() is True
        assert response.is_active() is False

    def test_status_parsing(self):
        """주문 상태 파싱 검증."""
        request = OrderRequest(
            symbol="BTCUSDT",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("30000"),
        )

        test_cases = [
            ("open", OrderStatus.SUBMITTED),
            ("closed", OrderStatus.FILLED),
            ("canceled", OrderStatus.CANCELLED),
            ("rejected", OrderStatus.REJECTED),
        ]

        for raw_status, expected_status in test_cases:
            raw_response = {
                "id": "123",
                "status": raw_status,
                "symbol": "BTCUSDT",
                "amount": 0.1,
                "filled": 0.0,
                "remaining": 0.1,
            }

            response = OrderResponse(raw_response, request)
            assert response.status == expected_status


# ============================================================================
# OrderExecutor Tests - Market Order
# ============================================================================


@pytest.mark.asyncio
class TestOrderExecutorMarketOrder:
    """시장가 주문 실행 테스트."""

    async def test_execute_market_order_success(self, order_executor, mock_exchange, event_bus):
        """시장가 주문 실행 - 성공."""
        # Mock 거래소 응답
        mock_exchange.create_order.return_value = {
            "id": "order-123",
            "status": "closed",
            "symbol": "BTCUSDT",
            "type": "market",
            "side": "buy",
            "amount": 0.01,
            "filled": 0.01,
            "remaining": 0.0,
            "average": 30000.0,
            "timestamp": 1234567890000,
        }

        # 시장가 주문 실행
        response = await order_executor.execute_market_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.01"),
        )

        # 검증
        assert response.order_id == "order-123"
        assert response.status == OrderStatus.FILLED
        assert response.filled_quantity == Decimal("0.01")

        # CCXT create_order 호출 확인
        mock_exchange.create_order.assert_called_once()
        call_args = mock_exchange.create_order.call_args

        assert call_args.kwargs["symbol"] == "BTCUSDT"
        assert call_args.kwargs["type"] == "market"
        assert call_args.kwargs["side"] == "buy"
        assert call_args.kwargs["amount"] == 0.01

        # 이벤트 발행 확인
        assert event_bus.emit.call_count >= 1

    async def test_execute_market_order_with_position_side(
        self, order_executor, mock_exchange
    ):
        """시장가 주문 실행 - 포지션 방향 지정."""
        mock_exchange.create_order.return_value = {
            "id": "order-456",
            "status": "closed",
            "symbol": "ETHUSDT",
            "type": "market",
            "side": "sell",
            "amount": 1.0,
            "filled": 1.0,
            "remaining": 0.0,
            "average": 2000.0,
            "timestamp": 1234567890000,
        }

        response = await order_executor.execute_market_order(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("1.0"),
            position_side=PositionSide.SHORT,
            reduce_only=True,
        )

        assert response.status == OrderStatus.FILLED

        # params에 positionSide와 reduceOnly가 포함되어야 함
        call_args = mock_exchange.create_order.call_args
        params = call_args.kwargs.get("params", {})

        assert params.get("positionSide") == "SHORT"
        assert params.get("reduceOnly") is True


# ============================================================================
# OrderExecutor Tests - Limit Order
# ============================================================================


@pytest.mark.asyncio
class TestOrderExecutorLimitOrder:
    """지정가 주문 실행 테스트."""

    async def test_execute_limit_order_success(self, order_executor, mock_exchange):
        """지정가 주문 실행 - 성공."""
        mock_exchange.create_order.return_value = {
            "id": "limit-123",
            "status": "open",
            "symbol": "BTCUSDT",
            "type": "limit",
            "side": "buy",
            "price": 29000.0,
            "amount": 0.05,
            "filled": 0.0,
            "remaining": 0.05,
            "timestamp": 1234567890000,
        }

        response = await order_executor.execute_limit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.05"),
            price=Decimal("29000"),
            time_in_force="GTC",
        )

        assert response.order_id == "limit-123"
        assert response.status == OrderStatus.SUBMITTED

        # CCXT create_order 호출 확인
        call_args = mock_exchange.create_order.call_args

        assert call_args.kwargs["type"] == "limit"
        assert call_args.kwargs["price"] == 29000.0

    async def test_execute_limit_order_post_only(self, order_executor, mock_exchange):
        """지정가 주문 실행 - Post-only."""
        mock_exchange.create_order.return_value = {
            "id": "limit-456",
            "status": "open",
            "symbol": "ETHUSDT",
            "type": "limit",
            "side": "sell",
            "price": 2100.0,
            "amount": 2.0,
            "filled": 0.0,
            "remaining": 2.0,
            "timestamp": 1234567890000,
        }

        response = await order_executor.execute_limit_order(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("2.0"),
            price=Decimal("2100"),
            post_only=True,
        )

        assert response.status == OrderStatus.SUBMITTED

        # params에 postOnly가 포함되어야 함
        call_args = mock_exchange.create_order.call_args
        params = call_args.kwargs.get("params", {})

        assert params.get("postOnly") is True


# ============================================================================
# OrderExecutor Tests - Stop Loss / Take Profit
# ============================================================================


@pytest.mark.asyncio
class TestOrderExecutorStopOrders:
    """손절/익절 주문 실행 테스트."""

    async def test_execute_stop_loss_order_success(
        self, order_executor, mock_exchange
    ):
        """손절 주문 실행 - 성공."""
        mock_exchange.create_order.return_value = {
            "id": "stop-123",
            "status": "open",
            "symbol": "BTCUSDT",
            "type": "STOP_MARKET",
            "side": "sell",
            "amount": 0.1,
            "filled": 0.0,
            "remaining": 0.1,
            "timestamp": 1234567890000,
        }

        response = await order_executor.execute_stop_loss_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_price=Decimal("28000"),
        )

        assert response.order_id == "stop-123"
        assert response.status == OrderStatus.SUBMITTED

        # params에 stopPrice가 포함되어야 함
        call_args = mock_exchange.create_order.call_args
        params = call_args.kwargs.get("params", {})

        assert params.get("stopPrice") == 28000.0

    async def test_execute_take_profit_order_success(
        self, order_executor, mock_exchange
    ):
        """익절 주문 실행 - 성공."""
        mock_exchange.create_order.return_value = {
            "id": "tp-456",
            "status": "open",
            "symbol": "ETHUSDT",
            "type": "STOP_MARKET",
            "side": "sell",
            "amount": 1.5,
            "filled": 0.0,
            "remaining": 1.5,
            "timestamp": 1234567890000,
        }

        response = await order_executor.execute_take_profit_order(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("1.5"),
            stop_price=Decimal("2200"),
        )

        assert response.order_id == "tp-456"


# ============================================================================
# OrderExecutor Tests - Error Handling
# ============================================================================


@pytest.mark.asyncio
class TestOrderExecutorErrorHandling:
    """에러 처리 및 재시도 로직 테스트."""

    async def test_invalid_order_raises_immediately(
        self, order_executor, mock_exchange
    ):
        """Invalid order 에러는 즉시 발생 (재시도 없음)."""
        mock_exchange.create_order.side_effect = InvalidOrder(
            "Invalid quantity precision"
        )

        with pytest.raises(InvalidOrder):
            await order_executor.execute_market_order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.00000001"),  # Too small
            )

        # 재시도 없이 1회만 호출되어야 함
        assert mock_exchange.create_order.call_count == 1

    async def test_insufficient_funds_raises_immediately(
        self, order_executor, mock_exchange
    ):
        """잔고 부족 에러는 즉시 발생 (재시도 없음)."""
        mock_exchange.create_order.side_effect = InsufficientFunds("Not enough balance")

        with pytest.raises(InsufficientFunds):
            await order_executor.execute_market_order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("100"),
            )

        assert mock_exchange.create_order.call_count == 1

    async def test_network_error_retries_then_succeeds(
        self, order_executor, mock_exchange
    ):
        """네트워크 에러는 재시도 후 성공."""
        # 첫 2회는 에러, 3회째 성공
        mock_exchange.create_order.side_effect = [
            NetworkError("Connection timeout"),
            NetworkError("Connection timeout"),
            {
                "id": "retry-123",
                "status": "closed",
                "symbol": "BTCUSDT",
                "type": "market",
                "side": "buy",
                "amount": 0.01,
                "filled": 0.01,
                "remaining": 0.0,
                "average": 30000.0,
                "timestamp": 1234567890000,
            },
        ]

        response = await order_executor.execute_market_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.01"),
        )

        assert response.order_id == "retry-123"
        assert mock_exchange.create_order.call_count == 3

    async def test_network_error_retries_exhausted_raises(
        self, order_executor, mock_exchange
    ):
        """네트워크 에러가 계속되면 최종적으로 예외 발생."""
        mock_exchange.create_order.side_effect = NetworkError("Connection timeout")

        with pytest.raises(NetworkError):
            await order_executor.execute_market_order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.01"),
            )

        # max_retries=3이므로 3회 시도
        assert mock_exchange.create_order.call_count == 3

    async def test_timestamp_error_triggers_synchronization(
        self, order_executor, mock_exchange
    ):
        """타임스탬프 에러 발생 시 동기화 후 재시도."""
        # 첫 시도: 타임스탬프 에러
        # 두 번째 시도: 성공
        mock_exchange.create_order.side_effect = [
            ExchangeError("Timestamp for this request is outside of the recvWindow"),
            {
                "id": "ts-sync-123",
                "status": "closed",
                "symbol": "BTCUSDT",
                "type": "market",
                "side": "buy",
                "amount": 0.01,
                "filled": 0.01,
                "remaining": 0.0,
                "average": 30000.0,
                "timestamp": 1234567890000,
            },
        ]

        response = await order_executor.execute_market_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.01"),
        )

        assert response.order_id == "ts-sync-123"

        # load_time_difference가 호출되어야 함
        mock_exchange.load_time_difference.assert_called_once()


# ============================================================================
# OrderExecutor Tests - Order Management
# ============================================================================


@pytest.mark.asyncio
class TestOrderExecutorManagement:
    """주문 관리 기능 테스트."""

    async def test_cancel_order_success(self, order_executor, mock_exchange):
        """주문 취소 - 성공."""
        mock_exchange.cancel_order.return_value = {
            "id": "order-123",
            "status": "canceled",
        }

        result = await order_executor.cancel_order("order-123", "BTCUSDT")

        assert result["status"] == "canceled"
        mock_exchange.cancel_order.assert_called_once_with("order-123", "BTCUSDT")

    async def test_cancel_order_not_found_raises(
        self, order_executor, mock_exchange
    ):
        """존재하지 않는 주문 취소 - 에러."""
        mock_exchange.cancel_order.side_effect = OrderNotFound("Order not found")

        with pytest.raises(OrderNotFound):
            await order_executor.cancel_order("nonexistent", "BTCUSDT")

    async def test_fetch_order_success(self, order_executor, mock_exchange):
        """주문 조회 - 성공."""
        mock_exchange.fetch_order.return_value = {
            "id": "order-123",
            "status": "closed",
            "symbol": "BTCUSDT",
            "filled": 0.01,
        }

        result = await order_executor.fetch_order("order-123", "BTCUSDT")

        assert result["id"] == "order-123"
        assert result["status"] == "closed"

    async def test_order_history_tracking(self, order_executor, mock_exchange):
        """주문 히스토리 추적."""
        mock_exchange.create_order.return_value = {
            "id": "order-1",
            "status": "closed",
            "symbol": "BTCUSDT",
            "type": "market",
            "side": "buy",
            "amount": 0.01,
            "filled": 0.01,
            "remaining": 0.0,
            "average": 30000.0,
            "timestamp": 1234567890000,
        }

        # 주문 실행
        await order_executor.execute_market_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.01"),
        )

        # 히스토리 확인
        history = order_executor.get_order_history()
        assert len(history) == 1
        assert history[0].order_id == "order-1"

        # 히스토리 초기화
        order_executor.clear_history()
        assert len(order_executor.get_order_history()) == 0


# ============================================================================
# OrderExecutor Tests - Event Emission
# ============================================================================


@pytest.mark.asyncio
class TestOrderExecutorEvents:
    """이벤트 발행 검증 테스트."""

    async def test_order_placed_event_emitted(
        self, order_executor, mock_exchange, event_bus
    ):
        """ORDER_PLACED 이벤트 발행 확인."""
        mock_exchange.create_order.return_value = {
            "id": "event-123",
            "status": "open",
            "symbol": "BTCUSDT",
            "type": "limit",
            "side": "buy",
            "price": 29000.0,
            "amount": 0.1,
            "filled": 0.0,
            "remaining": 0.1,
            "timestamp": 1234567890000,
        }

        await order_executor.execute_limit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("29000"),
        )

        # ORDER_PLACED 이벤트가 발행되었는지 확인
        event_calls = [call[0][0] for call in event_bus.emit.call_args_list]
        assert EventType.ORDER_PLACED in event_calls

    async def test_order_filled_event_emitted(
        self, order_executor, mock_exchange, event_bus
    ):
        """ORDER_FILLED 이벤트 발행 확인."""
        mock_exchange.create_order.return_value = {
            "id": "filled-123",
            "status": "closed",  # 전체 체결
            "symbol": "ETHUSDT",
            "type": "market",
            "side": "buy",
            "amount": 1.0,
            "filled": 1.0,
            "remaining": 0.0,
            "average": 2000.0,
            "timestamp": 1234567890000,
        }

        await order_executor.execute_market_order(
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("1.0"),
        )

        # ORDER_FILLED 이벤트가 발행되었는지 확인
        event_calls = [call[0][0] for call in event_bus.emit.call_args_list]
        assert EventType.ORDER_FILLED in event_calls

    async def test_order_cancelled_event_on_error(
        self, order_executor, mock_exchange, event_bus
    ):
        """에러 발생 시 ORDER_CANCELLED 이벤트 발행."""
        mock_exchange.create_order.side_effect = InvalidOrder("Invalid parameters")

        with pytest.raises(InvalidOrder):
            await order_executor.execute_market_order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.01"),
            )

        # ORDER_CANCELLED 이벤트가 발행되었는지 확인
        event_calls = [call[0][0] for call in event_bus.emit.call_args_list]
        assert EventType.ORDER_CANCELLED in event_calls
