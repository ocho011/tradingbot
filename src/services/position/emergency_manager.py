"""
긴급 청산 관리 시스템.

이 모듈은 긴급 상황 시 모든 포지션을 강제 청산하는 기능을 제공합니다:
- 모든 미청산 포지션 즉시 시장가 청산
- 신규 주문 차단
- 청산 진행 상황 실시간 로깅
- 청산 완료 후 시스템 일시 정지
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Any

from src.core.events import Event, EventBus
from src.core.constants import EventType, OrderSide, PositionSide
from src.services.position.position_manager import PositionManager
from src.services.exchange.order_executor import OrderExecutor

logger = logging.getLogger(__name__)


class EmergencyStatus:
    """긴급 상태."""
    NORMAL = "normal"
    LIQUIDATING = "liquidating"
    PAUSED = "paused"


class EmergencyManager:
    """
    긴급 청산 관리자.

    긴급 상황 시 모든 포지션을 강제 청산하고 시스템을 일시 정지합니다.
    """

    def __init__(
        self,
        position_manager: PositionManager,
        order_executor: OrderExecutor,
        event_bus: Optional[EventBus] = None,
    ):
        """
        EmergencyManager 초기화.

        Args:
            position_manager: 포지션 관리자
            order_executor: 주문 실행자
            event_bus: 이벤트 버스 (선택)
        """
        self.position_manager = position_manager
        self.order_executor = order_executor
        self.event_bus = event_bus

        # 긴급 상태
        self._status = EmergencyStatus.NORMAL
        self._orders_blocked = False

        # 청산 통계
        self._stats = {
            "total_liquidations": 0,
            "successful_liquidations": 0,
            "failed_liquidations": 0,
            "last_liquidation_time": None,
        }

        logger.info("EmergencyManager initialized")

    async def emergency_liquidate_all(self, reason: str = "Emergency") -> Dict[str, Any]:
        """
        모든 포지션 긴급 청산.

        Args:
            reason: 청산 사유

        Returns:
            Dict[str, Any]: 청산 결과
                - total: 총 포지션 수
                - successful: 성공한 청산 수
                - failed: 실패한 청산 수
                - details: 상세 정보
        """
        if self._status == EmergencyStatus.LIQUIDATING:
            logger.warning("Emergency liquidation already in progress")
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "error": "Liquidation already in progress",
            }

        logger.critical(f"🚨 EMERGENCY LIQUIDATION INITIATED: {reason}")

        # 상태 변경
        self._status = EmergencyStatus.LIQUIDATING
        self._orders_blocked = True

        # 긴급 청산 시작 이벤트 발행
        await self._publish_event(
            EventType.SYSTEM_STOP,
            {
                "event": "emergency_liquidation_started",
                "reason": reason,
            },
            priority=10,
        )

        # 열린 포지션 조회
        open_positions = self.position_manager.get_open_positions()

        if not open_positions:
            logger.info("No open positions to liquidate")
            self._status = EmergencyStatus.PAUSED
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "details": [],
            }

        total = len(open_positions)
        successful = 0
        failed = 0
        details = []

        logger.info(f"Found {total} open positions to liquidate")

        # 각 포지션 청산
        for position in open_positions:
            try:
                logger.info(
                    f"Liquidating position: {position.symbol} "
                    f"{position.side.value} {position.size}"
                )

                # 청산 주문 방향 결정
                # LONG 포지션 → SELL 주문
                # SHORT 포지션 → BUY 주문
                if position.side == PositionSide.LONG:
                    order_side = OrderSide.SELL
                elif position.side == PositionSide.SHORT:
                    order_side = OrderSide.BUY
                else:
                    logger.error(f"Unknown position side: {position.side}")
                    failed += 1
                    details.append({
                        "symbol": position.symbol,
                        "status": "failed",
                        "error": "Unknown position side",
                    })
                    continue

                # 시장가 청산 주문 실행
                response = await self.order_executor.execute_market_order(
                    symbol=position.symbol,
                    side=order_side,
                    quantity=position.size,
                    position_side=position.side,
                    reduce_only=True,
                )

                # 청산 성공 (주문이 체결되었는지 확인)
                if response.is_filled():
                    logger.info(
                        f"✓ Successfully liquidated {position.symbol}: "
                        f"order_id={response.order_id}"
                    )

                    # 포지션 종료
                    await self.position_manager.close_position(
                        symbol=position.symbol,
                        exit_price=response.average_price or response.price or position.current_price or position.entry_price,
                        exit_reason=f"Emergency liquidation: {reason}",
                        fees=Decimal("0"),  # 수수료는 별도로 계산
                    )

                    successful += 1
                    details.append({
                        "symbol": position.symbol,
                        "status": "success",
                        "order_id": response.order_id,
                        "price": str(response.average_price or response.price) if (response.average_price or response.price) else None,
                    })

                else:
                    # 청산 실패 또는 부분 체결
                    logger.error(
                        f"✗ Failed to liquidate {position.symbol}: "
                        f"order status={response.status.value}"
                    )

                    failed += 1
                    details.append({
                        "symbol": position.symbol,
                        "status": "failed",
                        "error": f"Order not filled: {response.status.value}",
                    })

            except Exception as e:
                logger.error(
                    f"Exception during liquidation of {position.symbol}: {e}",
                    exc_info=True
                )
                failed += 1
                details.append({
                    "symbol": position.symbol,
                    "status": "failed",
                    "error": str(e),
                })

        # 통계 업데이트
        self._stats["total_liquidations"] += total
        self._stats["successful_liquidations"] += successful
        self._stats["failed_liquidations"] += failed
        self._stats["last_liquidation_time"] = datetime.now(timezone.utc).isoformat()

        # 상태 변경: 일시 정지
        self._status = EmergencyStatus.PAUSED

        result = {
            "total": total,
            "successful": successful,
            "failed": failed,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.critical(
            f"🚨 EMERGENCY LIQUIDATION COMPLETED: "
            f"total={total}, successful={successful}, failed={failed}"
        )

        # 청산 완료 이벤트 발행
        await self._publish_event(
            EventType.SYSTEM_STOP,
            {
                "event": "emergency_liquidation_completed",
                "reason": reason,
                "result": result,
            },
            priority=10,
        )

        return result

    def block_new_orders(self) -> None:
        """신규 주문 차단."""
        self._orders_blocked = True
        logger.warning("🚫 New orders are now BLOCKED")

    def unblock_orders(self) -> None:
        """주문 차단 해제."""
        self._orders_blocked = False
        logger.info("✓ New orders are now UNBLOCKED")

    def is_orders_blocked(self) -> bool:
        """
        주문 차단 상태 확인.

        Returns:
            bool: 차단 중이면 True
        """
        return self._orders_blocked

    def get_status(self) -> str:
        """
        현재 긴급 상태 조회.

        Returns:
            str: 현재 상태 (NORMAL, LIQUIDATING, PAUSED)
        """
        return self._status

    def is_paused(self) -> bool:
        """
        시스템 일시 정지 상태 확인.

        Returns:
            bool: 일시 정지 중이면 True
        """
        return self._status == EmergencyStatus.PAUSED

    def resume(self) -> None:
        """시스템 재개 (정상 상태로 복귀)."""
        if self._status != EmergencyStatus.PAUSED:
            logger.warning(f"Cannot resume from status: {self._status}")
            return

        self._status = EmergencyStatus.NORMAL
        self._orders_blocked = False
        logger.info("✓ System RESUMED to normal operation")

    def get_stats(self) -> Dict[str, Any]:
        """
        청산 통계 조회.

        Returns:
            Dict[str, Any]: 통계 정보
        """
        return {
            **self._stats,
            "status": self._status,
            "orders_blocked": self._orders_blocked,
        }

    async def _publish_event(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        priority: int = 10,
    ) -> None:
        """
        긴급 이벤트 발행.

        Args:
            event_type: 이벤트 타입
            data: 이벤트 데이터
            priority: 우선순위 (기본값: 10 - 최고 우선순위)
        """
        if not self.event_bus:
            return

        event = Event(
            priority=priority,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            data=data,
            source="EmergencyManager",
        )

        await self.event_bus.publish(event)
        logger.debug(f"Published emergency event: {event_type.value}")
