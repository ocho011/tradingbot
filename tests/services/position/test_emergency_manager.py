"""
긴급 청산 관리자 테스트.
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.services.position.emergency_manager import EmergencyManager, EmergencyStatus
from src.services.position.position_manager import PositionManager
from src.services.exchange.order_executor import OrderExecutor, OrderResponse, OrderStatus
from src.core.constants import PositionSide, OrderSide, EventType
from src.core.events import EventBus


@pytest.fixture
def db_session():
    """Mock database session."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.commit = MagicMock()
    session.refresh = MagicMock()
    return session


@pytest.fixture
def event_bus():
    """Mock event bus."""
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def position_manager(db_session, event_bus):
    """Create PositionManager instance."""
    return PositionManager(db_session=db_session, event_bus=event_bus)


@pytest.fixture
def order_executor():
    """Mock OrderExecutor."""
    executor = MagicMock(spec=OrderExecutor)
    executor.execute_market_order = AsyncMock()
    return executor


@pytest.fixture
def emergency_manager(position_manager, order_executor, event_bus):
    """Create EmergencyManager instance."""
    return EmergencyManager(
        position_manager=position_manager,
        order_executor=order_executor,
        event_bus=event_bus,
    )


class TestEmergencyManager:
    """긴급 청산 관리자 테스트."""

    @pytest.mark.asyncio
    async def test_initialization(self, emergency_manager):
        """초기화 테스트."""
        assert emergency_manager.get_status() == EmergencyStatus.NORMAL
        assert not emergency_manager.is_orders_blocked()
        assert not emergency_manager.is_paused()
        assert emergency_manager.get_stats()["total_liquidations"] == 0
        assert emergency_manager.get_stats()["successful_liquidations"] == 0
        assert emergency_manager.get_stats()["failed_liquidations"] == 0

    @pytest.mark.asyncio
    async def test_emergency_liquidate_empty_positions(self, emergency_manager):
        """빈 포지션 청산 테스트."""
        result = await emergency_manager.emergency_liquidate_all("Test reason")

        assert result["total"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0
        assert len(result["details"]) == 0
        assert emergency_manager.get_status() == EmergencyStatus.PAUSED
        assert emergency_manager.is_orders_blocked()

    @pytest.mark.asyncio
    async def test_emergency_liquidate_single_position(
        self, emergency_manager, position_manager, order_executor
    ):
        """단일 포지션 긴급 청산 테스트."""
        # LONG 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # 청산 주문 성공 응답 (Mock OrderResponse)
        mock_response = MagicMock(spec=OrderResponse)
        mock_response.is_filled.return_value = True
        mock_response.order_id = "order123"
        mock_response.average_price = Decimal("51000")
        mock_response.price = Decimal("51000")
        mock_response.status = OrderStatus.FILLED
        order_executor.execute_market_order.return_value = mock_response

        result = await emergency_manager.emergency_liquidate_all("Test emergency")

        assert result["total"] == 1
        assert result["successful"] == 1
        assert result["failed"] == 0
        assert len(result["details"]) == 1
        assert result["details"][0]["symbol"] == "BTCUSDT"
        assert result["details"][0]["status"] == "success"

        # OrderExecutor 호출 확인 (LONG → SELL)
        order_executor.execute_market_order.assert_called_once()
        call_args = order_executor.execute_market_order.call_args
        assert call_args[1]["symbol"] == "BTCUSDT"
        assert call_args[1]["side"] == OrderSide.SELL
        assert call_args[1]["quantity"] == Decimal("0.1")
        assert call_args[1]["position_side"] == PositionSide.LONG
        assert call_args[1]["reduce_only"] is True

    @pytest.mark.asyncio
    async def test_emergency_liquidate_multiple_positions(
        self, emergency_manager, position_manager, order_executor
    ):
        """다중 포지션 긴급 청산 테스트."""
        # LONG 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # SHORT 포지션 생성
        await position_manager.open_position(
            symbol="ETHUSDT",
            strategy="test",
            side=PositionSide.SHORT,
            size=Decimal("1.0"),
            entry_price=Decimal("3000"),
            leverage=5,
        )

        # 청산 주문 성공 응답 (Mock OrderResponse)
        mock_response = MagicMock(spec=OrderResponse)
        mock_response.is_filled.return_value = True
        mock_response.order_id = "order123"
        mock_response.average_price = Decimal("50000")
        mock_response.price = Decimal("50000")
        mock_response.status = OrderStatus.FILLED
        order_executor.execute_market_order.return_value = mock_response

        result = await emergency_manager.emergency_liquidate_all("Test emergency")

        assert result["total"] == 2
        assert result["successful"] == 2
        assert result["failed"] == 0
        assert len(result["details"]) == 2

        # 두 번 호출되었는지 확인
        assert order_executor.execute_market_order.call_count == 2

        # SHORT → BUY 호출 확인
        calls = order_executor.execute_market_order.call_args_list
        eth_call = [c for c in calls if c[1]["symbol"] == "ETHUSDT"][0]
        assert eth_call[1]["side"] == OrderSide.BUY
        assert eth_call[1]["position_side"] == PositionSide.SHORT

    @pytest.mark.asyncio
    async def test_liquidation_failure_handling(
        self, emergency_manager, position_manager, order_executor
    ):
        """청산 실패 처리 테스트."""
        # 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # 청산 주문 실패 응답 (Mock OrderResponse)
        mock_response = MagicMock(spec=OrderResponse)
        mock_response.is_filled.return_value = False
        mock_response.order_id = None
        mock_response.average_price = None
        mock_response.price = None
        mock_response.status = OrderStatus.REJECTED
        order_executor.execute_market_order.return_value = mock_response

        result = await emergency_manager.emergency_liquidate_all("Test emergency")

        assert result["total"] == 1
        assert result["successful"] == 0
        assert result["failed"] == 1
        assert result["details"][0]["status"] == "failed"
        assert "not filled" in result["details"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_order_blocking_mechanism(self, emergency_manager):
        """주문 차단 메커니즘 테스트."""
        # 초기 상태
        assert not emergency_manager.is_orders_blocked()

        # 주문 차단
        emergency_manager.block_new_orders()
        assert emergency_manager.is_orders_blocked()

        # 주문 차단 해제
        emergency_manager.unblock_orders()
        assert not emergency_manager.is_orders_blocked()

    @pytest.mark.asyncio
    async def test_status_management(self, emergency_manager, position_manager):
        """상태 관리 테스트."""
        # 초기 상태
        assert emergency_manager.get_status() == EmergencyStatus.NORMAL
        assert not emergency_manager.is_paused()

        # 긴급 청산 (빈 포지션)
        await emergency_manager.emergency_liquidate_all("Test")

        # 청산 후 상태
        assert emergency_manager.get_status() == EmergencyStatus.PAUSED
        assert emergency_manager.is_paused()

    @pytest.mark.asyncio
    async def test_resume_functionality(self, emergency_manager):
        """시스템 재개 기능 테스트."""
        # 긴급 청산으로 PAUSED 상태로 변경
        await emergency_manager.emergency_liquidate_all("Test")
        assert emergency_manager.get_status() == EmergencyStatus.PAUSED
        assert emergency_manager.is_orders_blocked()

        # 시스템 재개
        emergency_manager.resume()
        assert emergency_manager.get_status() == EmergencyStatus.NORMAL
        assert not emergency_manager.is_orders_blocked()

    @pytest.mark.asyncio
    async def test_resume_from_wrong_status(self, emergency_manager):
        """잘못된 상태에서 재개 시도 테스트."""
        # NORMAL 상태에서 재개 시도 (아무 일도 일어나지 않음)
        emergency_manager.resume()
        assert emergency_manager.get_status() == EmergencyStatus.NORMAL

    @pytest.mark.asyncio
    async def test_statistics_tracking(
        self, emergency_manager, position_manager, order_executor
    ):
        """통계 추적 테스트."""
        # 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        await position_manager.open_position(
            symbol="ETHUSDT",
            strategy="test",
            side=PositionSide.SHORT,
            size=Decimal("1.0"),
            entry_price=Decimal("3000"),
            leverage=5,
        )

        # 하나는 성공, 하나는 실패
        mock_response_success = MagicMock(spec=OrderResponse)
        mock_response_success.is_filled.return_value = True
        mock_response_success.order_id = "order1"
        mock_response_success.average_price = Decimal("50000")
        mock_response_success.price = Decimal("50000")
        mock_response_success.status = OrderStatus.FILLED

        mock_response_fail = MagicMock(spec=OrderResponse)
        mock_response_fail.is_filled.return_value = False
        mock_response_fail.order_id = None
        mock_response_fail.average_price = None
        mock_response_fail.price = None
        mock_response_fail.status = OrderStatus.REJECTED

        order_executor.execute_market_order.side_effect = [
            mock_response_success,
            mock_response_fail,
        ]

        await emergency_manager.emergency_liquidate_all("Test")

        stats = emergency_manager.get_stats()
        assert stats["total_liquidations"] == 2
        assert stats["successful_liquidations"] == 1
        assert stats["failed_liquidations"] == 1
        assert stats["last_liquidation_time"] is not None
        assert stats["status"] == EmergencyStatus.PAUSED
        assert stats["orders_blocked"] is True

    @pytest.mark.asyncio
    async def test_event_publishing(self, emergency_manager, event_bus, position_manager, order_executor):
        """이벤트 발행 테스트."""
        # 포지션 생성하여 청산 이벤트가 2개 발생하도록 함
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # Mock response
        mock_response = MagicMock(spec=OrderResponse)
        mock_response.is_filled.return_value = True
        mock_response.order_id = "order123"
        mock_response.average_price = Decimal("50000")
        mock_response.price = Decimal("50000")
        mock_response.status = OrderStatus.FILLED
        order_executor.execute_market_order.return_value = mock_response

        await emergency_manager.emergency_liquidate_all("Test reason")

        # 이벤트 발행 확인 (position_opened + 시작 + position_closed + 완료 = 4개)
        assert event_bus.publish.call_count == 4

        # 시작 이벤트 확인 (두 번째, 인덱스 1)
        start_event = event_bus.publish.call_args_list[1][0][0]
        assert start_event.event_type == EventType.SYSTEM_STOP
        assert start_event.data["event"] == "emergency_liquidation_started"
        assert start_event.priority == 10

        # 완료 이벤트 확인 (마지막, 인덱스 3)
        complete_event = event_bus.publish.call_args_list[3][0][0]
        assert complete_event.event_type == EventType.SYSTEM_STOP
        assert complete_event.data["event"] == "emergency_liquidation_completed"
        assert complete_event.priority == 10

    @pytest.mark.asyncio
    async def test_liquidation_already_in_progress(self, emergency_manager):
        """이미 청산 진행 중 테스트."""
        # 상태를 LIQUIDATING으로 설정
        emergency_manager._status = EmergencyStatus.LIQUIDATING

        result = await emergency_manager.emergency_liquidate_all("Test")

        assert result["total"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0
        assert "error" in result
        assert result["error"] == "Liquidation already in progress"

    @pytest.mark.asyncio
    async def test_no_event_bus(self, position_manager, order_executor):
        """이벤트 버스 없이 동작 테스트."""
        # 이벤트 버스 없이 생성
        manager = EmergencyManager(
            position_manager=position_manager,
            order_executor=order_executor,
            event_bus=None,
        )

        # 포지션 없이 청산 (이벤트 없이 정상 동작)
        result = await manager.emergency_liquidate_all("Test")
        assert result["total"] == 0
        assert result["successful"] == 0

    @pytest.mark.asyncio
    async def test_liquidation_with_exception(
        self, emergency_manager, position_manager, order_executor
    ):
        """청산 중 예외 발생 테스트."""
        # 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # 예외 발생 시뮬레이션
        order_executor.execute_market_order.side_effect = Exception("Network error")

        result = await emergency_manager.emergency_liquidate_all("Test")

        assert result["total"] == 1
        assert result["successful"] == 0
        assert result["failed"] == 1
        assert result["details"][0]["status"] == "failed"
        assert "Network error" in result["details"][0]["error"]
