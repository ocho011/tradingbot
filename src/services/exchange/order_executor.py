"""
비동기 주문 실행 시스템 (Async Order Execution System).

바이낸스 선물 거래소에 주문을 비동기로 실행하는 핵심 시스템:
- 시장가, 지정가, 조건부 주문 지원
- 비동기 주문 전송 및 응답 처리
- 주문 파라미터 검증 및 타임스탬프 관리
- 에러 처리 및 재시도 로직 (RetryManager 사용)
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, List
from enum import Enum

from ccxt.base.errors import (
    NetworkError,
    ExchangeError,
    InvalidOrder,
    InsufficientFunds,
    OrderNotFound,
)

from src.core.constants import OrderSide, OrderType, PositionSide
from src.core.events import EventBus, EventType
from src.core.retry_manager import RetryManager, RetryConfig, RetryStrategy
from src.monitoring.metrics import record_order_execution


logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    """주문 상태."""

    PENDING = "pending"  # 주문 대기 중
    SUBMITTED = "submitted"  # 거래소에 제출됨
    PARTIALLY_FILLED = "partially_filled"  # 부분 체결
    FILLED = "filled"  # 전체 체결
    CANCELLED = "cancelled"  # 취소됨
    REJECTED = "rejected"  # 거부됨
    FAILED = "failed"  # 실패


class OrderRequest:
    """주문 요청 데이터 클래스."""

    def __init__(
        self,
        symbol: str,
        order_type: OrderType,
        side: OrderSide,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        position_side: Optional[PositionSide] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        post_only: bool = False,
        client_order_id: Optional[str] = None,
    ):
        """
        주문 요청 초기화.

        Args:
            symbol: 거래 심볼 (예: "BTCUSDT")
            order_type: 주문 타입 (MARKET, LIMIT, STOP_LOSS, TAKE_PROFIT)
            side: 주문 방향 (BUY, SELL)
            quantity: 주문 수량
            price: 지정가 (LIMIT 주문 시 필수)
            stop_price: 스톱 가격 (STOP_LOSS, TAKE_PROFIT 주문 시 필수)
            position_side: 포지션 방향 (LONG, SHORT)
            time_in_force: 주문 유효 기간 (GTC, IOC, FOK)
            reduce_only: 포지션 축소 전용 여부
            post_only: Post-only 주문 여부 (메이커 수수료 적용)
            client_order_id: 클라이언트 주문 ID (선택)
        """
        self.symbol = symbol
        self.order_type = order_type
        self.side = side
        self.quantity = quantity
        self.price = price
        self.stop_price = stop_price
        self.position_side = position_side
        self.time_in_force = time_in_force
        self.reduce_only = reduce_only
        self.post_only = post_only
        self.client_order_id = client_order_id
        self.timestamp = datetime.now(timezone.utc)

    def validate(self) -> None:
        """
        주문 파라미터 검증.

        Raises:
            ValueError: 주문 파라미터가 유효하지 않을 경우
        """
        # 기본 검증
        if not self.symbol:
            raise ValueError("Symbol is required")

        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")

        # 주문 타입별 검증
        if self.order_type == OrderType.LIMIT:
            if self.price is None or self.price <= 0:
                raise ValueError("LIMIT order requires a valid price")
            if self.post_only and self.time_in_force != "GTC":
                raise ValueError("Post-only orders must use GTC time in force")

        elif self.order_type in (OrderType.STOP_LOSS, OrderType.TAKE_PROFIT):
            if self.stop_price is None or self.stop_price <= 0:
                raise ValueError(
                    f"{self.order_type.value} order requires a valid stop_price"
                )

        # 포지션 방향 검증 (선물 거래)
        if self.position_side and self.position_side not in (
            PositionSide.LONG,
            PositionSide.SHORT,
        ):
            raise ValueError(f"Invalid position_side: {self.position_side}")

        # Time in force 검증
        valid_tif = ["GTC", "IOC", "FOK"]
        if self.time_in_force not in valid_tif:
            raise ValueError(
                f"Invalid time_in_force: {self.time_in_force}. Must be one of {valid_tif}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """주문 요청을 딕셔너리로 변환."""
        data = {
            "symbol": self.symbol,
            "type": self.order_type.value,
            "side": self.side.value,
            "quantity": float(self.quantity),
            "timeInForce": self.time_in_force,
        }

        if self.price:
            data["price"] = float(self.price)

        if self.stop_price:
            data["stopPrice"] = float(self.stop_price)

        if self.position_side:
            data["positionSide"] = self.position_side.value

        if self.reduce_only:
            data["reduceOnly"] = True

        if self.post_only:
            data["postOnly"] = True

        if self.client_order_id:
            data["clientOrderId"] = self.client_order_id

        return data


class OrderResponse:
    """주문 응답 데이터 클래스."""

    def __init__(self, raw_response: Dict[str, Any], request: OrderRequest):
        """
        주문 응답 초기화.

        Args:
            raw_response: 거래소로부터 받은 원본 응답
            request: 원본 주문 요청
        """
        self.raw_response = raw_response
        self.request = request

        # 응답 데이터 파싱
        self.order_id = raw_response.get("id")
        self.client_order_id = raw_response.get("clientOrderId")
        self.status = self._parse_status(raw_response.get("status"))
        self.symbol = raw_response.get("symbol")
        self.order_type = raw_response.get("type")
        self.side = raw_response.get("side")
        self.price = Decimal(str(raw_response.get("price", 0)))
        self.quantity = Decimal(str(raw_response.get("amount", 0)))
        self.filled_quantity = Decimal(str(raw_response.get("filled", 0)))
        self.remaining_quantity = Decimal(str(raw_response.get("remaining", 0)))
        self.average_price = Decimal(str(raw_response.get("average", 0)))
        self.timestamp = raw_response.get("timestamp")
        self.fee = raw_response.get("fee", {})

    def _parse_status(self, status: str) -> OrderStatus:
        """거래소 주문 상태를 내부 OrderStatus로 변환."""
        status_map = {
            "open": OrderStatus.SUBMITTED,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        return status_map.get(status.lower(), OrderStatus.PENDING)

    def is_filled(self) -> bool:
        """주문이 전체 체결되었는지 확인."""
        return self.status == OrderStatus.FILLED

    def is_active(self) -> bool:
        """주문이 아직 활성 상태인지 확인."""
        return self.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)

    def to_dict(self) -> Dict[str, Any]:
        """응답 데이터를 딕셔너리로 변환."""
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "status": self.status.value,
            "symbol": self.symbol,
            "order_type": self.order_type,
            "side": self.side,
            "price": float(self.price),
            "quantity": float(self.quantity),
            "filled_quantity": float(self.filled_quantity),
            "remaining_quantity": float(self.remaining_quantity),
            "average_price": float(self.average_price),
            "timestamp": self.timestamp,
            "fee": self.fee,
        }


class OrderExecutor:
    """
    비동기 주문 실행 엔진.

    바이낸스 선물 거래소에 주문을 비동기로 실행하고 관리:
    - 시장가, 지정가, 조건부 주문 실행
    - 주문 파라미터 검증 및 타임스탬프 동기화
    - 에러 처리 및 자동 재시도
    - 이벤트 발행 및 로깅
    """

    def __init__(
        self,
        exchange,
        event_bus: Optional[EventBus] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        OrderExecutor 초기화.

        Args:
            exchange: CCXT exchange 인스턴스 (BinanceManager.exchange)
            event_bus: 이벤트 버스 (선택)
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간격 (초)
        """
        self.exchange = exchange
        self.event_bus = event_bus
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # 실행 중인 주문 추적
        self._pending_orders: Dict[str, OrderRequest] = {}
        self._order_history: List[OrderResponse] = []

        # RetryManager 설정
        self._retry_manager = self._create_retry_manager()

        logger.info(
            f"OrderExecutor initialized (max_retries={max_retries}, "
            f"retry_delay={retry_delay}s)"
        )

    def _create_retry_manager(self) -> RetryManager:
        """
        RetryManager 생성 및 설정.

        Returns:
            RetryManager: 설정된 재시도 관리자
        """
        # 타임스탬프 동기화 핸들러
        async def timestamp_handler(exception: ExchangeError):
            error_msg = str(exception).lower()
            if "timestamp" in error_msg or "recvwindow" in error_msg:
                logger.warning(f"Timestamp error detected, synchronizing: {exception}")
                await self._synchronize_timestamp()

        # RetryConfig 설정
        config = RetryConfig(
            max_retries=self.max_retries,
            strategy=RetryStrategy.CUSTOM,
            custom_delays=[1.0, 2.0, 5.0],  # 1초, 2초, 5초 간격
            retryable_exceptions=[NetworkError],
            non_retryable_exceptions=[InvalidOrder, InsufficientFunds],
            special_handlers={ExchangeError: timestamp_handler},
            log_attempts=True,
        )

        return RetryManager(config)

    async def execute_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = False,
    ) -> OrderResponse:
        """
        시장가 주문 실행.

        Args:
            symbol: 거래 심볼
            side: 주문 방향 (BUY, SELL)
            quantity: 주문 수량
            position_side: 포지션 방향 (선물 거래)
            reduce_only: 포지션 축소 전용 여부

        Returns:
            OrderResponse: 주문 실행 응답

        Raises:
            ValueError: 주문 파라미터가 유효하지 않을 경우
            ExchangeError: 거래소 에러 발생 시
        """
        request = OrderRequest(
            symbol=symbol,
            order_type=OrderType.MARKET,
            side=side,
            quantity=quantity,
            position_side=position_side,
            reduce_only=reduce_only,
        )

        logger.info(
            f"Executing MARKET order: {symbol} {side.value} {quantity} "
            f"(position_side={position_side}, reduce_only={reduce_only})"
        )

        return await self._execute_order(request)

    async def execute_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        position_side: Optional[PositionSide] = None,
        time_in_force: str = "GTC",
        post_only: bool = False,
        reduce_only: bool = False,
    ) -> OrderResponse:
        """
        지정가 주문 실행.

        Args:
            symbol: 거래 심볼
            side: 주문 방향 (BUY, SELL)
            quantity: 주문 수량
            price: 지정 가격
            position_side: 포지션 방향 (선물 거래)
            time_in_force: 주문 유효 기간 (GTC, IOC, FOK)
            post_only: Post-only 주문 여부
            reduce_only: 포지션 축소 전용 여부

        Returns:
            OrderResponse: 주문 실행 응답

        Raises:
            ValueError: 주문 파라미터가 유효하지 않을 경우
            ExchangeError: 거래소 에러 발생 시
        """
        request = OrderRequest(
            symbol=symbol,
            order_type=OrderType.LIMIT,
            side=side,
            quantity=quantity,
            price=price,
            position_side=position_side,
            time_in_force=time_in_force,
            post_only=post_only,
            reduce_only=reduce_only,
        )

        logger.info(
            f"Executing LIMIT order: {symbol} {side.value} {quantity} @ {price} "
            f"(tif={time_in_force}, post_only={post_only})"
        )

        return await self._execute_order(request)

    async def execute_stop_loss_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_price: Decimal,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = True,
    ) -> OrderResponse:
        """
        손절(Stop Loss) 주문 실행.

        Args:
            symbol: 거래 심볼
            side: 주문 방향 (BUY, SELL)
            quantity: 주문 수량
            stop_price: 스톱 가격 (이 가격에 도달하면 시장가 주문 실행)
            position_side: 포지션 방향 (선물 거래)
            reduce_only: 포지션 축소 전용 여부 (기본값: True)

        Returns:
            OrderResponse: 주문 실행 응답

        Raises:
            ValueError: 주문 파라미터가 유효하지 않을 경우
            ExchangeError: 거래소 에러 발생 시
        """
        request = OrderRequest(
            symbol=symbol,
            order_type=OrderType.STOP_LOSS,
            side=side,
            quantity=quantity,
            stop_price=stop_price,
            position_side=position_side,
            reduce_only=reduce_only,
        )

        logger.info(
            f"Executing STOP_LOSS order: {symbol} {side.value} {quantity} @ stop={stop_price}"
        )

        return await self._execute_order(request)

    async def execute_take_profit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_price: Decimal,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = True,
    ) -> OrderResponse:
        """
        익절(Take Profit) 주문 실행.

        Args:
            symbol: 거래 심볼
            side: 주문 방향 (BUY, SELL)
            quantity: 주문 수량
            stop_price: 익절 가격 (이 가격에 도달하면 시장가 주문 실행)
            position_side: 포지션 방향 (선물 거래)
            reduce_only: 포지션 축소 전용 여부 (기본값: True)

        Returns:
            OrderResponse: 주문 실행 응답

        Raises:
            ValueError: 주문 파라미터가 유효하지 않을 경우
            ExchangeError: 거래소 에러 발생 시
        """
        request = OrderRequest(
            symbol=symbol,
            order_type=OrderType.TAKE_PROFIT,
            side=side,
            quantity=quantity,
            stop_price=stop_price,
            position_side=position_side,
            reduce_only=reduce_only,
        )

        logger.info(
            f"Executing TAKE_PROFIT order: {symbol} {side.value} {quantity} @ stop={stop_price}"
        )

        return await self._execute_order(request)

    async def _execute_order(self, request: OrderRequest) -> OrderResponse:
        """
        주문 실행 (내부 메서드).

        RetryManager를 사용한 자동 재시도 로직 포함:
        - 네트워크 에러: 자동 재시도 (1초, 2초, 5초 간격)
        - 타임스탬프 에러: 타임스탬프 동기화 후 재시도
        - 기타 에러: 로깅 후 예외 발생

        Args:
            request: 주문 요청

        Returns:
            OrderResponse: 주문 실행 응답

        Raises:
            ValueError: 주문 파라미터가 유효하지 않을 경우
            ExchangeError: 거래소 에러 발생 시
        """
        import time
        start_time = time.time()

        # 주문 파라미터 검증
        try:
            request.validate()
        except ValueError as e:
            logger.error(f"Order validation failed: {e}")
            await self._emit_order_event(
                EventType.ORDER_CANCELLED, request, error=str(e)
            )
            raise

        # RetryManager를 통한 주문 실행
        try:
            response = await self._retry_manager.execute(
                self._place_order_with_response, request
            )

            # Record execution latency metric on success
            execution_time = time.time() - start_time
            record_order_execution(
                symbol=request.symbol,
                order_type=request.order_type.value,
                side=request.side.value,
                execution_time=execution_time
            )

            return response

        except (InvalidOrder, InsufficientFunds) as e:
            # 재시도 불가능한 에러
            logger.error(f"Non-retryable error: {type(e).__name__}: {e}")
            await self._emit_order_event(
                EventType.ORDER_CANCELLED, request, error=str(e)
            )
            raise

        except NetworkError as e:
            # 모든 재시도 실패
            logger.error(f"Order failed after all retries: {e}")
            await self._emit_order_event(
                EventType.EXCHANGE_ERROR, request, error=str(e)
            )
            raise

        except ExchangeError as e:
            # 거래소 에러
            logger.error(f"Exchange error: {e}")
            await self._emit_order_event(
                EventType.EXCHANGE_ERROR, request, error=str(e)
            )
            raise

        except Exception as e:
            # 예상치 못한 에러
            logger.error(f"Unexpected error during order execution: {e}", exc_info=True)
            await self._emit_order_event(
                EventType.ERROR_OCCURRED, request, error=str(e)
            )
            raise

    async def _place_order_with_response(self, request: OrderRequest) -> OrderResponse:
        """
        주문을 거래소에 전송하고 응답 처리.

        RetryManager에서 호출되는 내부 메서드.

        Args:
            request: 주문 요청

        Returns:
            OrderResponse: 주문 실행 응답

        Raises:
            ExchangeError: 거래소 에러 발생 시
        """
        logger.debug(
            f"Placing order: {request.symbol} {request.order_type.value} "
            f"{request.side.value} {request.quantity}"
        )

        # CCXT exchange를 통한 주문 실행
        order_params = request.to_dict()
        raw_response = await self._place_order_on_exchange(order_params)

        # 응답 파싱
        response = OrderResponse(raw_response, request)
        self._order_history.append(response)

        logger.info(
            f"Order executed successfully: order_id={response.order_id}, "
            f"status={response.status.value}"
        )

        # 이벤트 발행
        await self._emit_order_event(EventType.ORDER_PLACED, request, response)

        if response.is_filled():
            await self._emit_order_event(
                EventType.ORDER_FILLED, request, response
            )

        return response

    async def _place_order_on_exchange(
        self, order_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        거래소에 주문 전송 (CCXT 사용).

        Args:
            order_params: 주문 파라미터

        Returns:
            Dict[str, Any]: 거래소 응답

        Raises:
            ExchangeError: 거래소 에러 발생 시
        """
        symbol = order_params["symbol"]
        order_type = order_params["type"]
        side = order_params["side"]
        amount = order_params["quantity"]

        # CCXT create_order 호출
        # 선물 거래소는 create_order 메서드 사용
        if order_type == "MARKET":
            response = await self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=side.lower(),
                amount=amount,
                params=self._build_order_params(order_params),
            )
        elif order_type == "LIMIT":
            price = order_params["price"]
            response = await self.exchange.create_order(
                symbol=symbol,
                type="limit",
                side=side.lower(),
                amount=amount,
                price=price,
                params=self._build_order_params(order_params),
            )
        elif order_type in ("STOP_LOSS", "TAKE_PROFIT"):
            stop_price = order_params["stopPrice"]
            # Binance Futures: STOP_MARKET 주문
            response = await self.exchange.create_order(
                symbol=symbol,
                type="STOP_MARKET",
                side=side.lower(),
                amount=amount,
                params={"stopPrice": stop_price, **self._build_order_params(order_params)},
            )
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        return response

    def _build_order_params(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        CCXT params 딕셔너리 구성.

        Args:
            order_params: 주문 파라미터

        Returns:
            Dict[str, Any]: CCXT params
        """
        params = {}

        # 포지션 방향
        if "positionSide" in order_params:
            params["positionSide"] = order_params["positionSide"]

        # Time in force
        if "timeInForce" in order_params:
            params["timeInForce"] = order_params["timeInForce"]

        # Reduce only
        if order_params.get("reduceOnly"):
            params["reduceOnly"] = True

        # Post only
        if order_params.get("postOnly"):
            params["postOnly"] = True

        # Client order ID
        if "clientOrderId" in order_params:
            params["clientOrderId"] = order_params["clientOrderId"]

        return params

    async def _synchronize_timestamp(self) -> None:
        """
        거래소와 로컬 타임스탬프 동기화.

        바이낸스 API는 타임스탬프가 서버 시간과 일치해야 함.
        """
        try:
            # CCXT의 load_time_difference 메서드 사용
            if hasattr(self.exchange, "load_time_difference"):
                await self.exchange.load_time_difference()
                logger.info("Timestamp synchronized with exchange")
            else:
                logger.warning("Exchange does not support timestamp synchronization")
        except Exception as e:
            logger.error(f"Failed to synchronize timestamp: {e}")

    async def _emit_order_event(
        self,
        event_type: EventType,
        request: OrderRequest,
        response: Optional[OrderResponse] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        주문 관련 이벤트 발행.

        Args:
            event_type: 이벤트 타입
            request: 주문 요청
            response: 주문 응답 (선택)
            error: 에러 메시지 (선택)
        """
        if not self.event_bus:
            return

        event_data = {
            "symbol": request.symbol,
            "order_type": request.order_type.value,
            "side": request.side.value,
            "quantity": float(request.quantity),
            "timestamp": request.timestamp.isoformat(),
        }

        if request.price:
            event_data["price"] = float(request.price)

        if request.stop_price:
            event_data["stop_price"] = float(request.stop_price)

        if response:
            event_data["order_id"] = response.order_id
            event_data["status"] = response.status.value
            event_data["filled_quantity"] = float(response.filled_quantity)
            event_data["average_price"] = float(response.average_price)

        if error:
            event_data["error"] = error

        try:
            await self.event_bus.emit(event_type, event_data)
        except Exception as e:
            logger.error(f"Failed to emit event {event_type}: {e}")

    async def cancel_order(
        self, order_id: str, symbol: str
    ) -> Dict[str, Any]:
        """
        주문 취소.

        Args:
            order_id: 주문 ID
            symbol: 거래 심볼

        Returns:
            Dict[str, Any]: 취소 응답

        Raises:
            OrderNotFound: 주문을 찾을 수 없을 경우
            ExchangeError: 거래소 에러 발생 시
        """
        try:
            logger.info(f"Cancelling order: {order_id} ({symbol})")
            response = await self.exchange.cancel_order(order_id, symbol)

            # 이벤트 발행
            if self.event_bus:
                await self.event_bus.emit(
                    EventType.ORDER_CANCELLED,
                    {
                        "order_id": order_id,
                        "symbol": symbol,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            logger.info(f"Order cancelled successfully: {order_id}")
            return response

        except OrderNotFound as e:
            logger.error(f"Order not found: {order_id} - {e}")
            raise

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}", exc_info=True)
            raise

    async def fetch_order(
        self, order_id: str, symbol: str
    ) -> Dict[str, Any]:
        """
        주문 조회.

        Args:
            order_id: 주문 ID
            symbol: 거래 심볼

        Returns:
            Dict[str, Any]: 주문 정보

        Raises:
            OrderNotFound: 주문을 찾을 수 없을 경우
            ExchangeError: 거래소 에러 발생 시
        """
        try:
            response = await self.exchange.fetch_order(order_id, symbol)
            return response

        except OrderNotFound as e:
            logger.error(f"Order not found: {order_id} - {e}")
            raise

        except Exception as e:
            logger.error(f"Failed to fetch order {order_id}: {e}", exc_info=True)
            raise

    def get_order_history(self) -> List[OrderResponse]:
        """주문 실행 히스토리 반환."""
        return self._order_history.copy()

    def clear_history(self) -> None:
        """주문 히스토리 초기화."""
        self._order_history.clear()
        logger.info("Order history cleared")
