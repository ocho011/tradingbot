"""
포지션 모니터링 및 복구 시스템.

이 모듈은 다음 기능을 제공합니다:
- 실시간 포지션 모니터링
- 시스템 재시작 시 포지션 복구 (Binance API 조회)
- 로컬 상태와 거래소 상태 동기화
- 불일치 감지 및 알림
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Any

from src.core.events import Event, EventBus
from src.core.constants import EventType, PositionSide
from src.services.position.position_manager import PositionManager
from src.services.exchange.binance_manager import BinanceManager

logger = logging.getLogger(__name__)


class SyncStatus:
    """동기화 상태."""
    SYNCED = "synced"
    CONFLICT = "conflict"
    RECOVERY_NEEDED = "recovery_needed"


class PositionMonitor:
    """
    포지션 모니터링 및 복구 관리자.

    시스템 재시작 시 Binance API로부터 포지션을 복구하고,
    로컬 상태와 거래소 상태를 지속적으로 동기화합니다.
    """

    def __init__(
        self,
        position_manager: PositionManager,
        binance_manager: BinanceManager,
        event_bus: Optional[EventBus] = None,
        sync_interval: int = 60,
    ):
        """
        PositionMonitor 초기화.

        Args:
            position_manager: 포지션 관리자
            binance_manager: 바이낸스 API 관리자
            event_bus: 이벤트 버스 (선택)
            sync_interval: 동기화 간격 (초, 기본값: 60)
        """
        self.position_manager = position_manager
        self.binance_manager = binance_manager
        self.event_bus = event_bus
        self.sync_interval = sync_interval

        # 모니터링 상태
        self._monitoring = False
        self._last_sync_time: Optional[datetime] = None

        # 동기화 통계
        self._stats = {
            "total_recoveries": 0,
            "total_syncs": 0,
            "total_conflicts": 0,
            "last_recovery_time": None,
            "last_sync_time": None,
        }

        logger.info("PositionMonitor initialized")

    async def recover_positions(self) -> Dict[str, Any]:
        """
        시스템 재시작 시 Binance API로부터 포지션 복구.

        Returns:
            Dict[str, Any]: 복구 결과
                - recovered: 복구된 포지션 수
                - conflicts: 충돌 발견 수
                - details: 상세 정보
        """
        logger.info("Starting position recovery from Binance...")

        try:
            # Binance에서 현재 포지션 조회
            exchange_positions = await self.binance_manager.fetch_positions()

            # 로컬 포지션 조회
            local_positions = {
                pos.symbol: pos
                for pos in self.position_manager.get_open_positions()
            }

            recovered = 0
            conflicts = 0
            details = []

            # Exchange 포지션 처리
            for ex_pos in exchange_positions:
                symbol = ex_pos.get("symbol")
                size = Decimal(str(ex_pos.get("contracts", 0)))
                entry_price = Decimal(str(ex_pos.get("entryPrice", 0)))
                side_str = ex_pos.get("side", "").upper()
                leverage = int(ex_pos.get("leverage", 1))
                mark_price = Decimal(str(ex_pos.get("markPrice", 0)))

                # 포지션 방향 변환
                if side_str == "LONG":
                    side = PositionSide.LONG
                elif side_str == "SHORT":
                    side = PositionSide.SHORT
                else:
                    logger.warning(f"Unknown position side: {side_str} for {symbol}")
                    continue

                # 로컬에 포지션이 없으면 복구
                if symbol not in local_positions:
                    logger.info(f"Recovering missing position: {symbol} {side.value} {size}")

                    # 포지션 복구
                    await self.position_manager.open_position(
                        symbol=symbol,
                        strategy="recovered",
                        side=side,
                        size=size,
                        entry_price=entry_price,
                        leverage=leverage,
                    )

                    # 현재 가격으로 업데이트
                    await self.position_manager.update_position(symbol, mark_price)

                    recovered += 1
                    details.append({
                        "action": "recovered",
                        "symbol": symbol,
                        "side": side.value,
                        "size": str(size),
                        "entry_price": str(entry_price),
                    })

                else:
                    # 로컬 포지션과 비교
                    local_pos = local_positions[symbol]
                    conflict_detected = False

                    # 크기 차이 체크 (1% 이상 차이)
                    size_diff = abs(local_pos.size - size)
                    if size_diff / size > Decimal("0.01"):
                        logger.warning(
                            f"Position size conflict for {symbol}: "
                            f"local={local_pos.size}, exchange={size}"
                        )
                        conflict_detected = True

                    # 진입 가격 차이 체크 (1% 이상 차이)
                    price_diff = abs(local_pos.entry_price - entry_price)
                    if price_diff / entry_price > Decimal("0.01"):
                        logger.warning(
                            f"Entry price conflict for {symbol}: "
                            f"local={local_pos.entry_price}, exchange={entry_price}"
                        )
                        conflict_detected = True

                    if conflict_detected:
                        conflicts += 1
                        details.append({
                            "action": "conflict",
                            "symbol": symbol,
                            "local_size": str(local_pos.size),
                            "exchange_size": str(size),
                            "local_entry": str(local_pos.entry_price),
                            "exchange_entry": str(entry_price),
                        })

                        # 충돌 이벤트 발행
                        await self._publish_conflict_event(symbol, local_pos, ex_pos)

            # Exchange에 없지만 로컬에 있는 포지션 체크
            exchange_symbols = {pos.get("symbol") for pos in exchange_positions}
            for symbol, local_pos in local_positions.items():
                if symbol not in exchange_symbols:
                    logger.warning(
                        f"Position exists locally but not on exchange: {symbol}"
                    )
                    conflicts += 1
                    details.append({
                        "action": "orphaned",
                        "symbol": symbol,
                        "local_size": str(local_pos.size),
                        "local_entry": str(local_pos.entry_price),
                    })

            # 통계 업데이트
            self._stats["total_recoveries"] += recovered
            self._stats["total_conflicts"] += conflicts
            self._stats["last_recovery_time"] = datetime.now(timezone.utc).isoformat()

            result = {
                "recovered": recovered,
                "conflicts": conflicts,
                "details": details,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(
                f"Position recovery completed: "
                f"recovered={recovered}, conflicts={conflicts}"
            )

            # 복구 이벤트 발행
            await self._publish_recovery_event(result)

            return result

        except Exception as e:
            logger.error(f"Position recovery failed: {e}", exc_info=True)
            raise

    async def sync_positions(self) -> Dict[str, Any]:
        """
        로컬 포지션과 거래소 포지션 동기화.

        Returns:
            Dict[str, Any]: 동기화 결과
        """
        logger.debug("Syncing positions with exchange...")

        try:
            # Binance에서 현재 포지션 조회
            exchange_positions = await self.binance_manager.fetch_positions()

            # 로컬 포지션 조회
            local_positions = {
                pos.symbol: pos
                for pos in self.position_manager.get_open_positions()
            }

            updated = 0
            conflicts = 0

            # Exchange 포지션으로 로컬 상태 업데이트
            for ex_pos in exchange_positions:
                symbol = ex_pos.get("symbol")
                mark_price = Decimal(str(ex_pos.get("markPrice", 0)))

                if symbol in local_positions:
                    # 현재 가격 업데이트
                    await self.position_manager.update_position(symbol, mark_price)
                    updated += 1

            # 통계 업데이트
            self._stats["total_syncs"] += 1
            self._stats["last_sync_time"] = datetime.now(timezone.utc).isoformat()
            self._last_sync_time = datetime.now(timezone.utc)

            result = {
                "updated": updated,
                "conflicts": conflicts,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            logger.debug(f"Position sync completed: updated={updated}")

            return result

        except Exception as e:
            logger.error(f"Position sync failed: {e}", exc_info=True)
            raise

    async def start_monitoring(self) -> None:
        """
        실시간 포지션 모니터링 시작.

        주기적으로 포지션 상태를 동기화합니다.
        """
        if self._monitoring:
            logger.warning("Position monitoring already running")
            return

        self._monitoring = True
        logger.info(f"Started position monitoring (interval: {self.sync_interval}s)")

    async def stop_monitoring(self) -> None:
        """포지션 모니터링 중지."""
        if not self._monitoring:
            logger.warning("Position monitoring not running")
            return

        self._monitoring = False
        logger.info("Stopped position monitoring")

    def is_monitoring(self) -> bool:
        """
        모니터링 상태 확인.

        Returns:
            bool: 모니터링 중이면 True
        """
        return self._monitoring

    def get_stats(self) -> Dict[str, Any]:
        """
        모니터링 통계 조회.

        Returns:
            Dict[str, Any]: 통계 정보
        """
        return {
            **self._stats,
            "monitoring": self._monitoring,
            "sync_interval": self.sync_interval,
            "last_sync_time": self._last_sync_time.isoformat() if self._last_sync_time else None,
        }

    async def _publish_recovery_event(self, result: Dict[str, Any]) -> None:
        """
        포지션 복구 이벤트 발행.

        Args:
            result: 복구 결과
        """
        if not self.event_bus:
            return

        event = Event(
            priority=9,
            event_type=EventType.SYSTEM_START,
            timestamp=datetime.now(timezone.utc),
            data={
                "event": "position_recovery",
                "recovered": result["recovered"],
                "conflicts": result["conflicts"],
                "details": result["details"],
            },
            source="PositionMonitor",
        )

        await self.event_bus.publish(event)
        logger.debug("Published position recovery event")

    async def _publish_conflict_event(
        self,
        symbol: str,
        local_pos: Any,
        exchange_pos: Dict[str, Any]
    ) -> None:
        """
        포지션 충돌 이벤트 발행.

        Args:
            symbol: 심볼
            local_pos: 로컬 포지션
            exchange_pos: 거래소 포지션
        """
        if not self.event_bus:
            return

        event = Event(
            priority=8,
            event_type=EventType.ERROR_OCCURRED,
            timestamp=datetime.now(timezone.utc),
            data={
                "event": "position_conflict",
                "symbol": symbol,
                "local_size": str(local_pos.size),
                "exchange_size": str(exchange_pos.get("contracts", 0)),
                "local_entry": str(local_pos.entry_price),
                "exchange_entry": str(exchange_pos.get("entryPrice", 0)),
            },
            source="PositionMonitor",
        )

        await self.event_bus.publish(event)
        logger.debug(f"Published position conflict event for {symbol}")
