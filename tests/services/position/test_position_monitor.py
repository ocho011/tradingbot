"""
포지션 모니터 테스트.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.constants import EventType, PositionSide
from src.core.events import EventBus
from src.services.position.position_manager import PositionManager
from src.services.position.position_monitor import PositionMonitor


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
def binance_manager():
    """Mock Binance manager."""
    manager = MagicMock()
    manager.fetch_positions = AsyncMock(return_value=[])
    return manager


@pytest.fixture
def position_monitor(position_manager, binance_manager, event_bus):
    """Create PositionMonitor instance."""
    return PositionMonitor(
        position_manager=position_manager,
        binance_manager=binance_manager,
        event_bus=event_bus,
        sync_interval=60,
    )


class TestPositionMonitor:
    """포지션 모니터 테스트."""

    @pytest.mark.asyncio
    async def test_initialization(self, position_monitor):
        """초기화 테스트."""
        assert position_monitor.sync_interval == 60
        assert not position_monitor.is_monitoring()
        assert position_monitor._stats["total_recoveries"] == 0
        assert position_monitor._stats["total_syncs"] == 0
        assert position_monitor._stats["total_conflicts"] == 0

    @pytest.mark.asyncio
    async def test_recover_empty_positions(self, position_monitor, binance_manager):
        """빈 포지션 복구 테스트."""
        # Binance에 포지션이 없음
        binance_manager.fetch_positions.return_value = []

        result = await position_monitor.recover_positions()

        assert result["recovered"] == 0
        assert result["conflicts"] == 0
        assert len(result["details"]) == 0

    @pytest.mark.asyncio
    async def test_recover_single_position(
        self, position_monitor, binance_manager, position_manager
    ):
        """단일 포지션 복구 테스트."""
        # Binance에 LONG 포지션 존재
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "contracts": 0.1,
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "leverage": 10,
            }
        ]

        result = await position_monitor.recover_positions()

        assert result["recovered"] == 1
        assert result["conflicts"] == 0
        assert len(result["details"]) == 1
        assert result["details"][0]["action"] == "recovered"
        assert result["details"][0]["symbol"] == "BTCUSDT"
        assert result["details"][0]["side"] == "LONG"

        # 통계 확인
        stats = position_monitor.get_stats()
        assert stats["total_recoveries"] == 1

    @pytest.mark.asyncio
    async def test_recover_multiple_positions(
        self, position_monitor, binance_manager, position_manager
    ):
        """다중 포지션 복구 테스트."""
        # Binance에 여러 포지션 존재
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "contracts": 0.1,
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "leverage": 10,
            },
            {
                "symbol": "ETHUSDT",
                "side": "short",
                "contracts": 1.0,
                "entryPrice": 3000.0,
                "markPrice": 2950.0,
                "leverage": 5,
            },
        ]

        result = await position_monitor.recover_positions()

        assert result["recovered"] == 2
        assert result["conflicts"] == 0
        assert len(result["details"]) == 2

    @pytest.mark.asyncio
    async def test_detect_size_conflict(
        self, position_monitor, binance_manager, position_manager, event_bus
    ):
        """포지션 크기 충돌 감지 테스트."""
        # 로컬에 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # Binance에 다른 크기의 포지션 존재 (크기가 2배 차이 = 100% 차이)
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "contracts": 0.2,  # 로컬: 0.1, 거래소: 0.2 (100% 차이)
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "leverage": 10,
            }
        ]

        result = await position_monitor.recover_positions()

        assert result["recovered"] == 0
        assert result["conflicts"] == 1
        assert len(result["details"]) == 1
        assert result["details"][0]["action"] == "conflict"

        # 충돌 이벤트 발행 확인
        event_bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_detect_orphaned_position(
        self, position_monitor, binance_manager, position_manager
    ):
        """고아 포지션 감지 테스트 (로컬에만 존재)."""
        # 로컬에 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # Binance에 포지션 없음
        binance_manager.fetch_positions.return_value = []

        result = await position_monitor.recover_positions()

        assert result["recovered"] == 0
        assert result["conflicts"] == 1
        assert len(result["details"]) == 1
        assert result["details"][0]["action"] == "orphaned"
        assert result["details"][0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_sync_positions(self, position_monitor, binance_manager, position_manager):
        """포지션 동기화 테스트."""
        # 로컬에 포지션 생성
        await position_manager.open_position(
            symbol="BTCUSDT",
            strategy="test",
            side=PositionSide.LONG,
            size=Decimal("0.1"),
            entry_price=Decimal("50000"),
            leverage=10,
        )

        # Binance 현재 가격
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "contracts": 0.1,
                "entryPrice": 50000.0,
                "markPrice": 51500.0,  # 가격 상승
                "leverage": 10,
            }
        ]

        result = await position_monitor.sync_positions()

        assert result["updated"] == 1
        assert result["conflicts"] == 0

        # 로컬 포지션 가격 업데이트 확인
        position = position_manager.get_position("BTCUSDT")
        assert position.current_price == Decimal("51500.0")

        # 통계 확인
        stats = position_monitor.get_stats()
        assert stats["total_syncs"] == 1

    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, position_monitor):
        """모니터링 시작/중지 테스트."""
        # 초기 상태
        assert not position_monitor.is_monitoring()

        # 모니터링 시작
        await position_monitor.start_monitoring()
        assert position_monitor.is_monitoring()

        # 중복 시작 시도 (경고만)
        await position_monitor.start_monitoring()
        assert position_monitor.is_monitoring()

        # 모니터링 중지
        await position_monitor.stop_monitoring()
        assert not position_monitor.is_monitoring()

        # 중복 중지 시도 (경고만)
        await position_monitor.stop_monitoring()
        assert not position_monitor.is_monitoring()

    @pytest.mark.asyncio
    async def test_get_stats(self, position_monitor, binance_manager):
        """통계 조회 테스트."""
        # 초기 통계
        stats = position_monitor.get_stats()
        assert stats["total_recoveries"] == 0
        assert stats["total_syncs"] == 0
        assert stats["monitoring"] is False

        # 포지션 복구
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "contracts": 0.1,
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "leverage": 10,
            }
        ]
        await position_monitor.recover_positions()

        # 통계 업데이트 확인
        stats = position_monitor.get_stats()
        assert stats["total_recoveries"] == 1

    @pytest.mark.asyncio
    async def test_recovery_event_publishing(self, position_monitor, binance_manager, event_bus):
        """복구 이벤트 발행 테스트."""
        # 포지션 복구
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "contracts": 0.1,
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "leverage": 10,
            }
        ]

        await position_monitor.recover_positions()

        # 이벤트 발행 확인
        event_bus.publish.assert_called()
        published_event = event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.SYSTEM_START
        assert published_event.data["event"] == "position_recovery"
        assert published_event.data["recovered"] == 1

    @pytest.mark.asyncio
    async def test_no_event_bus(self, position_manager, binance_manager):
        """이벤트 버스 없이 동작 테스트."""
        # 이벤트 버스 없이 생성
        monitor = PositionMonitor(
            position_manager=position_manager,
            binance_manager=binance_manager,
            event_bus=None,
        )

        # 포지션 복구 (이벤트 없이 정상 동작)
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "contracts": 0.1,
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "leverage": 10,
            }
        ]

        result = await monitor.recover_positions()
        assert result["recovered"] == 1

    @pytest.mark.asyncio
    async def test_recovery_with_unknown_side(self, position_monitor, binance_manager):
        """알 수 없는 포지션 방향 처리 테스트."""
        # 잘못된 side 값
        binance_manager.fetch_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "unknown",  # 잘못된 값
                "contracts": 0.1,
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "leverage": 10,
            }
        ]

        result = await position_monitor.recover_positions()

        # 잘못된 포지션은 무시됨
        assert result["recovered"] == 0
        assert result["conflicts"] == 0
