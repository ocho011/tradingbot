import logging
from decimal import Decimal
from src.core.events import EventHandler, Event, EventType
from src.core.constants import OrderSide, PositionSide
from src.services.exchange.order_executor import OrderExecutor

logger = logging.getLogger(__name__)

class ExitSignalHandler(EventHandler):
    """
    Handles exit signals (Stop Loss, Take Profit) by executing close orders.
    """
    def __init__(self, order_executor: OrderExecutor):
        super().__init__(name="ExitSignalHandler")
        self.order_executor = order_executor

    async def handle(self, event: Event) -> None:
        if event.event_type not in [EventType.STOP_LOSS_HIT, EventType.TAKE_PROFIT_HIT]:
            return

        try:
            data = event.data
            symbol = data.get("symbol")
            side_str = data.get("side") # Position side (LONG/SHORT)
            size = Decimal(str(data.get("size")))
            
            # Determine order side to close position
            if side_str == "LONG":
                order_side = OrderSide.SELL
                position_side = PositionSide.LONG
            elif side_str == "SHORT":
                order_side = OrderSide.BUY
                position_side = PositionSide.SHORT
            else:
                logger.error(f"Unknown position side: {side_str}")
                return

            logger.info(f"Executing exit order for {symbol} {side_str} (Reason: {event.event_type.value})")
            
            # Execute Market Order with reduce_only=True
            await self.order_executor.execute_market_order(
                symbol=symbol,
                side=order_side,
                quantity=size,
                position_side=position_side,
                reduce_only=True
            )
            
        except Exception as e:
            logger.error(f"Failed to handle exit signal: {e}", exc_info=True)
