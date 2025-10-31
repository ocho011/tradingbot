"""
포지션 상태 관리 시스템.

이 모듈은 포지션의 전체 생명주기를 관리하고 이벤트를 발행합니다:
- 포지션 생성, 업데이트, 종료
- 실시간 손익 계산
- position_opened/closed/updated 이벤트 발행
- 메모리 및 데이터베이스 동기화
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.core.events import Event, EventBus
from src.core.constants import EventType, PositionSide
from src.database.models import Position as PositionModel

logger = logging.getLogger(__name__)


class PositionStatus(str, Enum):
    """
    포지션 상태 열거형.

    포지션의 현재 상태를 표현합니다.
    """

    OPENED = "OPEN"      # 포지션 열림
    CLOSED = "CLOSED"    # 포지션 닫힘
    UPDATED = "UPDATED"  # 포지션 업데이트됨 (크기, 가격 변경)


@dataclass
class PositionInfo:
    """
    포지션 정보 데이터 클래스.

    메모리에서 관리되는 포지션의 핵심 정보를 담습니다.
    """

    id: int
    symbol: str
    strategy: str
    side: PositionSide
    size: Decimal
    entry_price: Decimal
    current_price: Optional[Decimal] = None
    leverage: int = 1
    unrealized_pnl: Decimal = Decimal("0")
    unrealized_pnl_percent: float = 0.0
    realized_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    status: PositionStatus = PositionStatus.OPENED
    opened_at: datetime = None
    closed_at: Optional[datetime] = None

    def __post_init__(self):
        """초기화 후 처리."""
        if self.opened_at is None:
            self.opened_at = datetime.now(timezone.utc)

    def calculate_pnl(self, current_price: Decimal) -> tuple[Decimal, float]:
        """
        현재 가격 기준 손익 계산.

        Args:
            current_price: 현재 시장 가격

        Returns:
            tuple[Decimal, float]: (절대 손익, 손익률)
        """
        if self.status == PositionStatus.CLOSED:
            return self.realized_pnl, float(self.unrealized_pnl_percent)

        price_diff = current_price - self.entry_price

        # Absolute PnL calculation (USDT value)
        # LONG: (current - entry) * size
        # SHORT: (entry - current) * size
        if self.side == PositionSide.LONG:
            pnl = price_diff * self.size
        else:  # SHORT
            pnl = -price_diff * self.size

        # 손익률 계산 (%)
        # With leverage, the % return is amplified
        # Position value: actual capital used = (entry_price * size) / leverage
        position_value = (self.entry_price * self.size) / Decimal(self.leverage)
        pnl_percent = float((pnl / position_value) * 100) if position_value > 0 else 0.0

        return pnl, pnl_percent

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "side": self.side.value,
            "size": str(self.size),
            "entry_price": str(self.entry_price),
            "current_price": str(self.current_price) if self.current_price else None,
            "leverage": self.leverage,
            "unrealized_pnl": str(self.unrealized_pnl),
            "unrealized_pnl_percent": self.unrealized_pnl_percent,
            "realized_pnl": str(self.realized_pnl),
            "total_fees": str(self.total_fees),
            "stop_loss": str(self.stop_loss) if self.stop_loss else None,
            "take_profit": str(self.take_profit) if self.take_profit else None,
            "status": self.status.value,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class PositionManager:
    """
    포지션 생명주기 관리자.

    포지션의 생성, 업데이트, 종료를 관리하고 관련 이벤트를 발행합니다.
    실시간 PnL 계산 및 데이터베이스 동기화를 수행합니다.
    """

    def __init__(
        self,
        db_session: Session,
        event_bus: Optional[EventBus] = None
    ):
        """
        PositionManager 초기화.

        Args:
            db_session: 데이터베이스 세션
            event_bus: 이벤트 버스 (선택)
        """
        self.db_session = db_session
        self.event_bus = event_bus

        # 메모리 포지션 맵: symbol -> PositionInfo
        self._positions: Dict[str, PositionInfo] = {}

        # 통계
        self._stats = {
            "total_opened": 0,
            "total_closed": 0,
            "total_updated": 0,
        }

        logger.info("PositionManager initialized")

    async def open_position(
        self,
        symbol: str,
        strategy: str,
        side: PositionSide,
        size: Decimal,
        entry_price: Decimal,
        leverage: int = 1,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        timeframe: Optional[str] = None,
    ) -> PositionInfo:
        """
        새 포지션 열기.

        Args:
            symbol: 거래 심볼
            strategy: 전략 이름
            side: 포지션 방향 (LONG/SHORT)
            size: 포지션 크기
            entry_price: 진입 가격
            leverage: 레버리지 (기본값: 1)
            stop_loss: 손절가 (선택)
            take_profit: 익절가 (선택)
            timeframe: 타임프레임 (선택)

        Returns:
            PositionInfo: 생성된 포지션 정보

        Raises:
            ValueError: 이미 열린 포지션이 존재하는 경우
        """
        # 중복 체크
        if symbol in self._positions:
            existing = self._positions[symbol]
            if existing.status == PositionStatus.OPENED:
                raise ValueError(f"Position already exists for {symbol}")

        # 데이터베이스에 저장
        db_position = PositionModel(
            symbol=symbol,
            strategy=strategy,
            side=side.value,
            size=size,
            entry_price=entry_price,
            current_price=entry_price,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="OPEN",
            opened_at=datetime.now(timezone.utc),
            timeframe=timeframe if timeframe else "1h",
        )

        self.db_session.add(db_position)
        self.db_session.commit()
        self.db_session.refresh(db_position)

        # 메모리 포지션 생성
        position = PositionInfo(
            id=db_position.id,
            symbol=symbol,
            strategy=strategy,
            side=side,
            size=size,
            entry_price=entry_price,
            current_price=entry_price,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=PositionStatus.OPENED,
            opened_at=db_position.opened_at,
        )

        self._positions[symbol] = position
        self._stats["total_opened"] += 1

        # 이벤트 발행
        await self._publish_event(
            EventType.POSITION_OPENED,
            position,
            priority=7
        )

        logger.info(
            f"Position opened: {symbol} {side.value} size={size} "
            f"entry={entry_price} leverage={leverage}x"
        )

        return position

    async def update_position(
        self,
        symbol: str,
        current_price: Decimal,
        size_change: Optional[Decimal] = None,
    ) -> Optional[PositionInfo]:
        """
        포지션 업데이트 (가격, 크기 변경).

        Args:
            symbol: 거래 심볼
            current_price: 현재 시장 가격
            size_change: 크기 변경 (선택, +/- 값)

        Returns:
            PositionInfo: 업데이트된 포지션 정보 (없으면 None)
        """
        position = self._positions.get(symbol)
        if not position or position.status != PositionStatus.OPENED:
            logger.warning(f"No open position found for {symbol}")
            return None

        # 현재 가격 업데이트
        old_price = position.current_price
        position.current_price = current_price

        # 크기 변경 (부분 청산 또는 추가 진입)
        if size_change is not None:
            new_size = position.size + size_change
            if new_size <= 0:
                logger.warning(f"Size change would result in zero/negative size for {symbol}")
                return position
            position.size = new_size

        # PnL 재계산
        pnl, pnl_percent = position.calculate_pnl(current_price)
        position.unrealized_pnl = pnl
        position.unrealized_pnl_percent = pnl_percent

        # 데이터베이스 동기화
        db_position = self.db_session.query(PositionModel).filter_by(
            id=position.id
        ).first()

        if db_position:
            db_position.current_price = current_price
            db_position.size = position.size
            db_position.unrealized_pnl = pnl
            db_position.unrealized_pnl_percent = pnl_percent
            db_position.updated_at = datetime.now(timezone.utc)
            self.db_session.commit()

        self._stats["total_updated"] += 1

        # 이벤트 발행 (가격이 크게 변했거나 크기가 변한 경우)
        should_publish = False
        if size_change is not None:
            should_publish = True
        elif old_price and abs(current_price - old_price) / old_price > Decimal("0.001"):
            # 0.1% 이상 가격 변동 시 이벤트 발행
            should_publish = True

        if should_publish:
            await self._publish_event(
                EventType.POSITION_UPDATED,
                position,
                priority=5
            )

        return position

    async def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        exit_reason: Optional[str] = None,
        fees: Decimal = Decimal("0"),
    ) -> Optional[PositionInfo]:
        """
        포지션 종료.

        Args:
            symbol: 거래 심볼
            exit_price: 청산 가격
            exit_reason: 청산 이유 (선택)
            fees: 수수료 (기본값: 0)

        Returns:
            PositionInfo: 종료된 포지션 정보 (없으면 None)
        """
        position = self._positions.get(symbol)
        if not position or position.status != PositionStatus.OPENED:
            logger.warning(f"No open position found for {symbol}")
            return None

        # 최종 PnL 계산
        pnl, pnl_percent = position.calculate_pnl(exit_price)
        realized_pnl = pnl - fees

        # 포지션 상태 업데이트
        position.status = PositionStatus.CLOSED
        position.current_price = exit_price
        position.unrealized_pnl = Decimal("0")
        position.unrealized_pnl_percent = 0.0
        position.realized_pnl = realized_pnl
        position.total_fees = fees
        position.closed_at = datetime.now(timezone.utc)

        # 데이터베이스 동기화
        db_position = self.db_session.query(PositionModel).filter_by(
            id=position.id
        ).first()

        if db_position:
            db_position.status = "CLOSED"
            db_position.current_price = exit_price
            db_position.unrealized_pnl = Decimal("0")
            db_position.unrealized_pnl_percent = 0.0
            db_position.realized_pnl = realized_pnl
            db_position.total_fees = fees
            db_position.closed_at = position.closed_at
            db_position.updated_at = datetime.now(timezone.utc)
            self.db_session.commit()

        self._stats["total_closed"] += 1

        # 이벤트 발행
        await self._publish_event(
            EventType.POSITION_CLOSED,
            position,
            priority=8,
            extra_data={
                "exit_price": str(exit_price),
                "exit_reason": exit_reason,
                "realized_pnl": str(realized_pnl),
                "fees": str(fees),
            }
        )

        logger.info(
            f"Position closed: {symbol} exit={exit_price} "
            f"realized_pnl={realized_pnl} reason={exit_reason}"
        )

        # 메모리에서 제거 (또는 히스토리로 이동)
        del self._positions[symbol]

        return position

    def get_position(self, symbol: str) -> Optional[PositionInfo]:
        """
        심볼별 포지션 조회.

        Args:
            symbol: 거래 심볼

        Returns:
            PositionInfo: 포지션 정보 (없으면 None)
        """
        return self._positions.get(symbol)

    def get_all_positions(self, status: Optional[PositionStatus] = None) -> List[PositionInfo]:
        """
        모든 포지션 조회.

        Args:
            status: 상태 필터 (선택)

        Returns:
            List[PositionInfo]: 포지션 리스트
        """
        if status is None:
            return list(self._positions.values())

        return [
            pos for pos in self._positions.values()
            if pos.status == status
        ]

    def get_open_positions(self) -> List[PositionInfo]:
        """
        열린 포지션만 조회.

        Returns:
            List[PositionInfo]: 열린 포지션 리스트
        """
        return self.get_all_positions(status=PositionStatus.OPENED)

    async def update_all_positions(self, price_updates: Dict[str, Decimal]) -> int:
        """
        여러 포지션 일괄 업데이트.

        Args:
            price_updates: {symbol: current_price} 맵

        Returns:
            int: 업데이트된 포지션 수
        """
        updated_count = 0

        for symbol, current_price in price_updates.items():
            result = await self.update_position(symbol, current_price)
            if result:
                updated_count += 1

        return updated_count

    def get_stats(self) -> Dict[str, Any]:
        """
        통계 조회.

        Returns:
            Dict[str, Any]: 통계 정보
        """
        return {
            **self._stats,
            "current_open_positions": len(self.get_open_positions()),
            "total_positions_in_memory": len(self._positions),
        }

    async def _publish_event(
        self,
        event_type: EventType,
        position: PositionInfo,
        priority: int = 5,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        포지션 이벤트 발행.

        Args:
            event_type: 이벤트 타입
            position: 포지션 정보
            priority: 우선순위 (0-10, 높을수록 우선)
            extra_data: 추가 데이터 (선택)
        """
        if not self.event_bus:
            return

        data = position.to_dict()
        if extra_data:
            data.update(extra_data)

        event = Event(
            priority=priority,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            data=data,
            source="PositionManager",
        )

        await self.event_bus.publish(event)

        logger.debug(
            f"Published {event_type.value} event for {position.symbol}"
        )
