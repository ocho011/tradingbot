"""
주문 상태 추적 및 이벤트 발행 시스템.

이 모듈은 주문 상태를 실시간으로 추적하고 관련 이벤트를 발행합니다:
- 주문 상태 추적 (PENDING, PLACED, FILLED, FAILED, CANCELLED)
- 실시간 상태 업데이트 (바이낸스 웹소켓 연동)
- 이벤트 자동 발행 (order_placed, order_filled, order_failed)
- 주문 히스토리 관리
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any

from src.core.events import Event, EventBus
from src.core.constants import EventType

logger = logging.getLogger(__name__)


class OrderTrackingStatus(str, Enum):
    """
    주문 추적 상태 열거형.

    바이낸스 주문 상태를 추상화한 내부 상태 표현.
    """

    PENDING = "PENDING"  # 주문 생성 중
    PLACED = "PLACED"  # 주문이 거래소에 전송됨
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 부분 체결
    FILLED = "FILLED"  # 완전 체결
    FAILED = "FAILED"  # 주문 실패
    CANCELLED = "CANCELLED"  # 주문 취소됨
    EXPIRED = "EXPIRED"  # 주문 만료됨


@dataclass
class TrackedOrder:
    """
    추적 중인 주문 정보.

    주문의 전체 생명주기 동안 상태 변경을 추적합니다.
    """

    order_id: str
    client_order_id: Optional[str]
    symbol: str
    order_type: str
    side: str
    quantity: float
    price: Optional[float]
    stop_price: Optional[float]

    status: OrderTrackingStatus = OrderTrackingStatus.PENDING
    filled_quantity: float = 0.0
    average_price: float = 0.0

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 상태 변경 히스토리
    status_history: List[Dict[str, Any]] = field(default_factory=list)

    # 추가 메타데이터
    error_message: Optional[str] = None
    exchange_response: Optional[Dict[str, Any]] = None

    def update_status(
        self,
        new_status: OrderTrackingStatus,
        filled_qty: Optional[float] = None,
        avg_price: Optional[float] = None,
        error_msg: Optional[str] = None
    ) -> None:
        """
        주문 상태 업데이트 및 히스토리 기록.

        Args:
            new_status: 새로운 상태
            filled_qty: 체결 수량 (선택)
            avg_price: 평균 체결가 (선택)
            error_msg: 에러 메시지 (선택)
        """
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

        if filled_qty is not None:
            self.filled_quantity = filled_qty

        if avg_price is not None:
            self.average_price = avg_price

        if error_msg is not None:
            self.error_message = error_msg

        # 상태 변경 히스토리 기록
        self.status_history.append({
            "timestamp": self.updated_at.isoformat(),
            "old_status": old_status.value,
            "new_status": new_status.value,
            "filled_quantity": self.filled_quantity,
            "average_price": self.average_price,
            "error_message": error_msg
        })

    def is_final_state(self) -> bool:
        """
        주문이 최종 상태인지 확인.

        Returns:
            최종 상태 여부 (FILLED, FAILED, CANCELLED, EXPIRED)
        """
        return self.status in (
            OrderTrackingStatus.FILLED,
            OrderTrackingStatus.FAILED,
            OrderTrackingStatus.CANCELLED,
            OrderTrackingStatus.EXPIRED
        )

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환."""
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "order_type": self.order_type,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "stop_price": self.stop_price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "average_price": self.average_price,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error_message": self.error_message,
            "status_history": self.status_history
        }


class OrderTracker:
    """
    주문 상태 추적 및 이벤트 발행 시스템.

    주문의 생명주기를 추적하고 상태 변경 시 이벤트를 발행합니다:
    - 주문 ID별 상태 관리
    - 실시간 상태 업데이트
    - 자동 이벤트 발행 (order_placed, order_filled, order_failed 등)
    - 웹소켓 통합 지원
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        max_history_size: int = 1000
    ):
        """
        OrderTracker 초기화.

        Args:
            event_bus: 이벤트 버스 (선택)
            max_history_size: 최대 히스토리 크기
        """
        self.event_bus = event_bus
        self.max_history_size = max_history_size

        # 활성 주문 추적 (order_id -> TrackedOrder)
        self._active_orders: Dict[str, TrackedOrder] = {}

        # Client order ID 매핑 (client_order_id -> order_id)
        self._client_id_map: Dict[str, str] = {}

        # 완료된 주문 히스토리
        self._completed_orders: List[TrackedOrder] = []

        # 통계
        self._stats = {
            "total_tracked": 0,
            "currently_active": 0,
            "total_filled": 0,
            "total_failed": 0,
            "total_cancelled": 0,
            "events_published": 0
        }

        logger.info(
            f"OrderTracker initialized (max_history={max_history_size})"
        )

    async def track_order(
        self,
        order_id: str,
        symbol: str,
        order_type: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        exchange_response: Optional[Dict[str, Any]] = None
    ) -> TrackedOrder:
        """
        새 주문 추적 시작.

        Args:
            order_id: 거래소 주문 ID
            symbol: 거래 심볼
            order_type: 주문 타입
            side: 주문 방향
            quantity: 주문 수량
            price: 지정가 (선택)
            stop_price: 스톱 가격 (선택)
            client_order_id: 클라이언트 주문 ID (선택)
            exchange_response: 거래소 응답 (선택)

        Returns:
            TrackedOrder: 생성된 추적 주문 객체
        """
        # 기존 주문 확인
        if order_id in self._active_orders:
            logger.warning(f"Order {order_id} already being tracked")
            return self._active_orders[order_id]

        # 추적 주문 생성
        tracked_order = TrackedOrder(
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            order_type=order_type,
            side=side,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            exchange_response=exchange_response
        )

        # 활성 주문에 추가
        self._active_orders[order_id] = tracked_order

        # Client ID 매핑
        if client_order_id:
            self._client_id_map[client_order_id] = order_id

        # 통계 업데이트
        self._stats["total_tracked"] += 1
        self._stats["currently_active"] = len(self._active_orders)

        logger.info(
            f"Started tracking order: {order_id} ({symbol} {side} {quantity})"
        )

        # ORDER_PLACED 이벤트 발행
        await self._publish_event(
            EventType.ORDER_PLACED,
            tracked_order,
            priority=7
        )

        return tracked_order

    async def update_order_status(
        self,
        order_id: str,
        new_status: OrderTrackingStatus,
        filled_quantity: Optional[float] = None,
        average_price: Optional[float] = None,
        error_message: Optional[str] = None,
        exchange_response: Optional[Dict[str, Any]] = None
    ) -> Optional[TrackedOrder]:
        """
        주문 상태 업데이트 및 이벤트 발행.

        Args:
            order_id: 주문 ID
            new_status: 새로운 상태
            filled_quantity: 체결 수량 (선택)
            average_price: 평균 체결가 (선택)
            error_message: 에러 메시지 (선택)
            exchange_response: 거래소 응답 (선택)

        Returns:
            Optional[TrackedOrder]: 업데이트된 주문 객체 (없으면 None)
        """
        # 주문 조회
        tracked_order = self._active_orders.get(order_id)
        if not tracked_order:
            logger.warning(f"Order {order_id} not found in active orders")
            return None

        # 이전 상태 저장
        old_status = tracked_order.status

        # 상태 업데이트
        tracked_order.update_status(
            new_status=new_status,
            filled_qty=filled_quantity,
            avg_price=average_price,
            error_msg=error_message
        )

        if exchange_response:
            tracked_order.exchange_response = exchange_response

        logger.info(
            f"Order {order_id} status updated: {old_status.value} → {new_status.value}"
        )

        # 상태별 이벤트 발행
        await self._publish_status_event(tracked_order, old_status)

        # 최종 상태 처리
        if tracked_order.is_final_state():
            await self._finalize_order(tracked_order)

        return tracked_order

    async def update_from_websocket(self, ws_data: Dict[str, Any]) -> None:
        """
        웹소켓 데이터로부터 주문 상태 업데이트.

        바이낸스 웹소켓 User Data Stream의 executionReport 이벤트를 처리합니다.

        Args:
            ws_data: 웹소켓 데이터
        """
        try:
            # 이벤트 타입 확인
            if ws_data.get("e") != "executionReport":
                return

            order_id = ws_data.get("i")  # order ID
            client_order_id = ws_data.get("c")  # client order ID
            order_status = ws_data.get("X")  # order status

            if not order_id:
                logger.warning("WebSocket data missing order ID")
                return

            # Client order ID로 조회
            if order_id not in self._active_orders and client_order_id:
                order_id = self._client_id_map.get(client_order_id, order_id)

            # 상태 매핑 (바이낸스 → 내부 상태)
            status_mapping = {
                "NEW": OrderTrackingStatus.PLACED,
                "PARTIALLY_FILLED": OrderTrackingStatus.PARTIALLY_FILLED,
                "FILLED": OrderTrackingStatus.FILLED,
                "CANCELED": OrderTrackingStatus.CANCELLED,
                "REJECTED": OrderTrackingStatus.FAILED,
                "EXPIRED": OrderTrackingStatus.EXPIRED
            }

            new_status = status_mapping.get(
                order_status,
                OrderTrackingStatus.PENDING
            )

            # 체결 정보
            filled_qty = float(ws_data.get("z", 0))  # cumulative filled quantity
            avg_price = float(ws_data.get("Z", 0)) / filled_qty if filled_qty > 0 else 0.0

            # 상태 업데이트
            await self.update_order_status(
                order_id=order_id,
                new_status=new_status,
                filled_quantity=filled_qty,
                average_price=avg_price,
                exchange_response=ws_data
            )

        except Exception as e:
            logger.error(f"Error processing websocket data: {e}", exc_info=True)

    async def _publish_status_event(
        self,
        order: TrackedOrder,
        old_status: OrderTrackingStatus
    ) -> None:
        """
        상태 변경에 따른 적절한 이벤트 발행.

        Args:
            order: 추적 주문
            old_status: 이전 상태
        """
        # FILLED 이벤트
        if order.status == OrderTrackingStatus.FILLED:
            await self._publish_event(
                EventType.ORDER_FILLED,
                order,
                priority=8
            )
            self._stats["total_filled"] += 1

        # CANCELLED 이벤트
        elif order.status in (OrderTrackingStatus.CANCELLED, OrderTrackingStatus.EXPIRED):
            await self._publish_event(
                EventType.ORDER_CANCELLED,
                order,
                priority=6
            )
            self._stats["total_cancelled"] += 1

        # FAILED 이벤트 (ERROR_OCCURRED 사용)
        elif order.status == OrderTrackingStatus.FAILED:
            await self._publish_event(
                EventType.ERROR_OCCURRED,
                order,
                priority=9,
                additional_data={"error": order.error_message}
            )
            self._stats["total_failed"] += 1

    async def _publish_event(
        self,
        event_type: EventType,
        order: TrackedOrder,
        priority: int = 5,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        이벤트 발행.

        Args:
            event_type: 이벤트 타입
            order: 추적 주문
            priority: 이벤트 우선순위
            additional_data: 추가 데이터 (선택)
        """
        if not self.event_bus:
            return

        # 이벤트 데이터 구성
        event_data = {
            "order_id": order.order_id,
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "order_type": order.order_type,
            "side": order.side,
            "quantity": order.quantity,
            "price": order.price,
            "stop_price": order.stop_price,
            "status": order.status.value,
            "filled_quantity": order.filled_quantity,
            "average_price": order.average_price,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat()
        }

        # 추가 데이터 병합
        if additional_data:
            event_data.update(additional_data)

        # 이벤트 생성 및 발행
        event = Event(
            priority=priority,
            event_type=event_type,
            data=event_data,
            source="OrderTracker"
        )

        try:
            await self.event_bus.publish(event)
            self._stats["events_published"] += 1

            logger.debug(
                f"Published {event_type.value} event for order {order.order_id}"
            )
        except Exception as e:
            logger.error(f"Failed to publish event {event_type}: {e}")

    async def _finalize_order(self, order: TrackedOrder) -> None:
        """
        주문 완료 처리 (히스토리로 이동).

        Args:
            order: 완료된 주문
        """
        # 활성 주문에서 제거
        if order.order_id in self._active_orders:
            del self._active_orders[order.order_id]

        # Client ID 매핑 제거
        if order.client_order_id and order.client_order_id in self._client_id_map:
            del self._client_id_map[order.client_order_id]

        # 히스토리에 추가
        self._completed_orders.append(order)

        # 히스토리 크기 제한
        if len(self._completed_orders) > self.max_history_size:
            self._completed_orders = self._completed_orders[-self.max_history_size:]

        # 통계 업데이트
        self._stats["currently_active"] = len(self._active_orders)

        logger.info(
            f"Order {order.order_id} finalized with status {order.status.value}"
        )

    def get_order(self, order_id: str) -> Optional[TrackedOrder]:
        """
        주문 ID로 추적 주문 조회 (활성 + 완료).

        Args:
            order_id: 주문 ID

        Returns:
            Optional[TrackedOrder]: 추적 주문 (없으면 None)
        """
        # 활성 주문 조회
        if order_id in self._active_orders:
            return self._active_orders[order_id]

        # 완료 주문 조회
        for order in reversed(self._completed_orders):
            if order.order_id == order_id:
                return order

        return None

    def get_order_by_client_id(self, client_order_id: str) -> Optional[TrackedOrder]:
        """
        클라이언트 주문 ID로 조회.

        Args:
            client_order_id: 클라이언트 주문 ID

        Returns:
            Optional[TrackedOrder]: 추적 주문 (없으면 None)
        """
        order_id = self._client_id_map.get(client_order_id)
        if order_id:
            return self.get_order(order_id)
        return None

    def get_active_orders(self, symbol: Optional[str] = None) -> List[TrackedOrder]:
        """
        활성 주문 목록 조회.

        Args:
            symbol: 심볼 필터 (선택)

        Returns:
            List[TrackedOrder]: 활성 주문 목록
        """
        if symbol:
            return [
                order for order in self._active_orders.values()
                if order.symbol == symbol
            ]
        return list(self._active_orders.values())

    def get_completed_orders(
        self,
        symbol: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[TrackedOrder]:
        """
        완료된 주문 목록 조회.

        Args:
            symbol: 심볼 필터 (선택)
            limit: 최대 개수 (선택)

        Returns:
            List[TrackedOrder]: 완료된 주문 목록
        """
        orders = self._completed_orders

        if symbol:
            orders = [order for order in orders if order.symbol == symbol]

        if limit:
            orders = orders[-limit:]

        return orders

    def get_stats(self) -> Dict[str, Any]:
        """
        추적 통계 조회.

        Returns:
            Dict[str, Any]: 통계 정보
        """
        return {
            **self._stats,
            "history_size": len(self._completed_orders)
        }

    def clear_history(self) -> None:
        """완료된 주문 히스토리 초기화."""
        self._completed_orders.clear()
        logger.info("Order history cleared")
