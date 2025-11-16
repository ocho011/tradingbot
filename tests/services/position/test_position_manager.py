"""
PositionManager 테스트.

포지션 생명주기 관리, PnL 계산, 이벤트 발행, 데이터베이스 동기화를 검증합니다.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.constants import EventType, PositionSide
from src.core.events import EventBus
from src.database.models import Base
from src.database.models import Position as PositionModel
from src.services.position.position_manager import (
    PositionInfo,
    PositionManager,
    PositionStatus,
)


@pytest.fixture
def db_session():
    """인메모리 SQLite 데이터베이스 세션 픽스처."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def event_bus():
    """EventBus 목 픽스처."""
    mock_bus = Mock(spec=EventBus)
    mock_bus.publish = AsyncMock()
    return mock_bus


@pytest.fixture
def position_manager(db_session, event_bus):
    """PositionManager 픽스처."""
    return PositionManager(
        db_session=db_session,
        event_bus=event_bus,
    )


class TestPositionInfo:
    """PositionInfo 데이터 클래스 테스트."""

    def test_position_info_creation(self):
        """포지션 정보 생성 테스트."""
        position = PositionInfo(
            id=1,
            symbol="BTCUSDT",
            strategy="ict_strategy",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        assert position.id == 1
        assert position.symbol == "BTCUSDT"
        assert position.strategy == "ict_strategy"
        assert position.side == PositionSide.LONG
        assert position.size == Decimal("0.1")
        assert position.entry_price == Decimal("50000")
        assert position.leverage == 10
        assert position.status == PositionStatus.OPENED
        assert position.opened_at is not None

    def test_calculate_pnl_long(self):
        """LONG 포지션 PnL 계산 테스트."""
        position = PositionInfo(
            id=1,
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # 가격 상승 (수익)
        # Absolute PnL: (51000 - 50000) * 0.1 = 100 USDT
        # Position value (capital used): (50000 * 0.1) / 10 = 500 USDT
        # PnL %: 100 / 500 * 100 = 20%
        pnl, pnl_percent = position.calculate_pnl(Decimal("51000"))
        assert pnl == Decimal("100")  # (51000 - 50000) * 0.1
        assert pnl_percent == pytest.approx(20.0, rel=0.01)  # 100 / 500 * 100

        # 가격 하락 (손실)
        pnl, pnl_percent = position.calculate_pnl(Decimal("49000"))
        assert pnl == Decimal("-100")  # (49000 - 50000) * 0.1
        assert pnl_percent == pytest.approx(-20.0, rel=0.01)

    def test_calculate_pnl_short(self):
        """SHORT 포지션 PnL 계산 테스트."""
        position = PositionInfo(
            id=1,
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.SHORT,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # 가격 하락 (수익)
        # Absolute PnL: -(49000 - 50000) * 0.1 = 100 USDT
        # Position value (capital used): (50000 * 0.1) / 10 = 500 USDT
        # PnL %: 100 / 500 * 100 = 20%
        pnl, pnl_percent = position.calculate_pnl(Decimal("49000"))
        assert pnl == Decimal("100")  # -(49000 - 50000) * 0.1
        assert pnl_percent == pytest.approx(20.0, rel=0.01)

        # 가격 상승 (손실)
        pnl, pnl_percent = position.calculate_pnl(Decimal("51000"))
        assert pnl == Decimal("-100")  # -(51000 - 50000) * 0.1
        assert pnl_percent == pytest.approx(-20.0, rel=0.01)

    def test_calculate_pnl_closed_position(self):
        """종료된 포지션 PnL 계산 테스트."""
        position = PositionInfo(
            id=1,
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
            status=PositionStatus.CLOSED,
            realized_pnl=Decimal("150"),
            unrealized_pnl_percent=3.0,
        )

        # 종료된 포지션은 realized_pnl 반환
        pnl, pnl_percent = position.calculate_pnl(Decimal("52000"))
        assert pnl == Decimal("150")
        assert pnl_percent == 3.0

    def test_to_dict(self):
        """딕셔너리 변환 테스트."""
        position = PositionInfo(
            id=1,
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            current_price=Decimal("51000"),
            leverage=10,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
        )

        data = position.to_dict()

        assert data["id"] == 1
        assert data["symbol"] == "BTCUSDT"
        assert data["strategy"] == "test"
        assert data["side"] == "LONG"
        assert data["size"] == "0.1"
        assert data["entry_price"] == "50000"
        assert data["current_price"] == "51000"
        assert data["leverage"] == 10
        assert data["stop_loss"] == "49000"
        assert data["take_profit"] == "52000"
        assert data["status"] == "OPEN"


class TestPositionManager:
    """PositionManager 클래스 테스트."""

    @pytest.mark.asyncio
    async def test_open_position(self, position_manager, db_session, event_bus):
        """포지션 열기 테스트."""
        position = await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="ict_strategy",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
        )

        # 메모리 확인
        assert position.symbol == "BTCUSDT"
        assert position.side == PositionSide.LONG
        assert position.size == Decimal("0.1")
        assert position.entry_price == Decimal("50000")
        assert position.leverage == 10
        assert position.status == PositionStatus.OPENED

        # 데이터베이스 확인
        db_position = db_session.query(PositionModel).filter_by(symbol="BTCUSDT").first()
        assert db_position is not None
        assert db_position.status == "OPEN"
        assert db_position.size == Decimal("0.1")

        # 이벤트 발행 확인
        event_bus.publish.assert_called_once()
        published_event = event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.POSITION_OPENED
        assert published_event.data["symbol"] == "BTCUSDT"

        # 통계 확인
        stats = position_manager.get_stats()
        assert stats["total_opened"] == 1

    @pytest.mark.asyncio
    async def test_open_duplicate_position_raises_error(self, position_manager):
        """중복 포지션 열기 시 에러 발생 테스트."""
        # 첫 번째 포지션 열기
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
        )

        # 중복 포지션 열기 시도
        with pytest.raises(ValueError, match="Position already exists"):
            await position_manager.open_position(
                symbol="BTCUSDT",
                strategy="test",
                side=PositionSide.LONG,
                size=Decimal("0.2"),
                entry_price=Decimal("51000"),
            )

    @pytest.mark.asyncio
    async def test_update_position_price(self, position_manager, db_session, event_bus):
        """포지션 가격 업데이트 테스트."""
        # 포지션 열기
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # 가격 업데이트
        event_bus.publish.reset_mock()
        updated = await position_manager.update_position(
            symbol="BTCUSDT",
            current_price=Decimal("51000"),
        )

        assert updated is not None
        assert updated.current_price == Decimal("51000")
        assert updated.unrealized_pnl == Decimal("100")
        assert updated.unrealized_pnl_percent == pytest.approx(20.0, rel=0.01)

        # 데이터베이스 동기화 확인
        db_position = db_session.query(PositionModel).filter_by(symbol="BTCUSDT").first()
        assert db_position.current_price == Decimal("51000")
        assert db_position.unrealized_pnl == Decimal("100")

        # 이벤트 발행 확인 (0.1% 이상 변동 시)
        event_bus.publish.assert_called_once()
        published_event = event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.POSITION_UPDATED

    @pytest.mark.asyncio
    async def test_update_position_size(self, position_manager, db_session):
        """포지션 크기 변경 테스트."""
        # 포지션 열기
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
        )

        # 크기 증가 (추가 진입)
        updated = await position_manager.update_position(
            symbol="BTCUSDT",
            current_price=Decimal("50500"),
            size_change=Decimal("0.05"),
        )

        assert updated.size == Decimal("0.15")

        # 크기 감소 (부분 청산)
        updated = await position_manager.update_position(
            symbol="BTCUSDT",
            current_price=Decimal("51000"),
            size_change=Decimal("-0.05"),
        )

        assert updated.size == Decimal("0.10")

        # 데이터베이스 확인
        db_position = db_session.query(PositionModel).filter_by(symbol="BTCUSDT").first()
        assert db_position.size == Decimal("0.10")

    @pytest.mark.asyncio
    async def test_update_nonexistent_position(self, position_manager):
        """존재하지 않는 포지션 업데이트 테스트."""
        result = await position_manager.update_position(
            symbol="NONEXISTENT",
            current_price=Decimal("50000"),
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_close_position(self, position_manager, db_session, event_bus):
        """포지션 종료 테스트."""
        # 포지션 열기
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # 포지션 종료
        event_bus.publish.reset_mock()
        closed = await position_manager.close_position(
            symbol="BTCUSDT",
            exit_price=Decimal("51000"),
            exit_reason="TAKE_PROFIT",
            fees=Decimal("5"),
        )

        assert closed is not None
        assert closed.status == PositionStatus.CLOSED
        assert closed.current_price == Decimal("51000")
        assert closed.realized_pnl == Decimal("95")  # 100 - 5 (fees)
        assert closed.total_fees == Decimal("5")
        assert closed.closed_at is not None

        # 데이터베이스 확인
        db_position = db_session.query(PositionModel).filter_by(symbol="BTCUSDT").first()
        assert db_position.status == "CLOSED"
        assert float(db_position.realized_pnl) == pytest.approx(95.0, rel=0.01)
        assert db_position.closed_at is not None

        # 이벤트 발행 확인
        event_bus.publish.assert_called_once()
        published_event = event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.POSITION_CLOSED
        assert published_event.data["exit_reason"] == "TAKE_PROFIT"
        assert float(published_event.data["realized_pnl"]) == pytest.approx(95.0, rel=0.01)

        # 메모리에서 제거 확인
        assert position_manager.get_position("BTCUSDT") is None

        # 통계 확인
        stats = position_manager.get_stats()
        assert stats["total_closed"] == 1

    @pytest.mark.asyncio
    async def test_close_nonexistent_position(self, position_manager):
        """존재하지 않는 포지션 종료 테스트."""
        result = await position_manager.close_position(
            symbol="NONEXISTENT",
            exit_price=Decimal("50000"),
        )

        assert result is None

    def test_get_position(self, position_manager):
        """포지션 조회 테스트."""
        # 존재하지 않는 포지션
        assert position_manager.get_position("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_get_all_positions(self, position_manager):
        """모든 포지션 조회 테스트."""
        # 여러 포지션 열기
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
        )

        await position_manager.open_position(
            symbol="ETHUSDT",
            strategy="test",
            side=PositionSide.SHORT,
            size=Decimal("1.0"),
            entry_price=Decimal("3000"),
        )

        # 모든 포지션 조회
        all_positions = position_manager.get_all_positions()
        assert len(all_positions) == 2

        # 상태별 조회
        open_positions = position_manager.get_all_positions(status=PositionStatus.OPENED)
        assert len(open_positions) == 2

    @pytest.mark.asyncio
    async def test_get_open_positions(self, position_manager):
        """열린 포지션 조회 테스트."""
        # 포지션 열기
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
        )

        await position_manager.open_position(
            symbol="ETHUSDT",
            strategy="test",
            side=PositionSide.SHORT,
            size=Decimal("1.0"),
            entry_price=Decimal("3000"),
        )

        # 하나 종료
        await position_manager.close_position(
            symbol="ETHUSDT",
            exit_price=Decimal("2950"),
        )

        # 열린 포지션만 조회
        open_positions = position_manager.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_update_all_positions(self, position_manager):
        """일괄 포지션 업데이트 테스트."""
        # 여러 포지션 열기
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
        )

        await position_manager.open_position(
            symbol="ETHUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("3000"),
        )

        # 일괄 업데이트
        price_updates = {
            "BTCUSDT": Decimal("51000"),
            "ETHUSDT": Decimal("3100"),
        }

        updated_count = await position_manager.update_all_positions(price_updates)

        assert updated_count == 2

        btc_position = position_manager.get_position("BTCUSDT")
        assert btc_position.current_price == Decimal("51000")

        eth_position = position_manager.get_position("ETHUSDT")
        assert eth_position.current_price == Decimal("3100")

    def test_get_stats(self, position_manager):
        """통계 조회 테스트."""
        stats = position_manager.get_stats()

        assert "total_opened" in stats
        assert "total_closed" in stats
        assert "total_updated" in stats
        assert "current_open_positions" in stats
        assert "total_positions_in_memory" in stats

    @pytest.mark.asyncio
    async def test_position_manager_without_event_bus(self, db_session):
        """EventBus 없이 PositionManager 사용 테스트."""
        manager = PositionManager(db_session=db_session, event_bus=None)

        # 이벤트 없이도 정상 작동
        position = await manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
        )

        assert position is not None
        assert position.symbol == "BTCUSDT"
