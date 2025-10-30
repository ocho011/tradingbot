"""
Position sizing calculator based on account balance and risk parameters.

Calculates position sizes using:
- 2% risk per trade based on account balance
- 5x leverage application
- Min/max position size validation
"""

import logging
from typing import Dict, Any, Optional
from decimal import Decimal, ROUND_DOWN

from src.services.exchange.binance_manager import BinanceManager, BinanceConnectionError


logger = logging.getLogger(__name__)


class PositionSizingError(Exception):
    """Raised when position sizing calculation fails."""
    pass


class PositionSizer:
    """
    Calculate position sizes based on account balance and risk parameters.

    Features:
    - 2% risk-based position sizing
    - 5x leverage application
    - Min/max position size validation
    - Precision handling for exchange requirements

    Attributes:
        binance_manager: Binance exchange manager for balance queries
        risk_percentage: Risk percentage per trade (default: 2%)
        leverage: Leverage multiplier (default: 5x)
        min_position_size: Minimum position size in USDT
        max_position_size: Maximum position size in USDT
        precision: Decimal places for position size (default: 8)
    """

    def __init__(
        self,
        binance_manager: BinanceManager,
        risk_percentage: float = 2.0,
        leverage: int = 5,
        min_position_size: float = 10.0,
        max_position_size: Optional[float] = None,
        precision: int = 8
    ):
        """
        Initialize position sizer.

        Args:
            binance_manager: Binance manager instance for balance queries
            risk_percentage: Risk percentage per trade (default: 2.0%)
            leverage: Leverage multiplier (default: 5)
            min_position_size: Minimum position size in USDT (default: 10.0)
            max_position_size: Maximum position size in USDT (None = no limit)
            precision: Decimal places for position size (default: 8)

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate parameters
        if not isinstance(binance_manager, BinanceManager):
            raise ValueError("binance_manager must be a BinanceManager instance")

        if not 0 < risk_percentage <= 100:
            raise ValueError("risk_percentage must be between 0 and 100")

        if leverage <= 0:
            raise ValueError("leverage must be positive")

        if min_position_size <= 0:
            raise ValueError("min_position_size must be positive")

        if max_position_size is not None and max_position_size <= min_position_size:
            raise ValueError("max_position_size must be greater than min_position_size")

        if precision < 0:
            raise ValueError("precision must be non-negative")

        self.binance_manager = binance_manager
        self.risk_percentage = Decimal(str(risk_percentage))
        self.leverage = leverage
        self.min_position_size = Decimal(str(min_position_size))
        self.max_position_size = Decimal(str(max_position_size)) if max_position_size else None
        self.precision = precision

        logger.info(
            f"PositionSizer initialized: "
            f"risk={risk_percentage}%, leverage={leverage}x, "
            f"min={min_position_size} USDT, max={max_position_size} USDT"
        )

    async def get_account_balance(self, currency: str = 'USDT') -> Decimal:
        """
        Get available account balance for specified currency.

        Args:
            currency: Currency symbol (default: 'USDT')

        Returns:
            Available balance as Decimal

        Raises:
            PositionSizingError: If balance fetch fails
        """
        try:
            balance_data = await self.binance_manager.fetch_balance()

            # Get free balance for the currency
            free_balance = balance_data.get('free', {}).get(currency, 0)

            if free_balance is None or free_balance == 0:
                logger.warning(f"No available {currency} balance found")
                return Decimal('0')

            balance = Decimal(str(free_balance))
            logger.debug(f"Available {currency} balance: {balance}")

            return balance

        except BinanceConnectionError as e:
            error_msg = f"Failed to fetch account balance: {e}"
            logger.error(error_msg)
            raise PositionSizingError(error_msg) from e
        except Exception as e:
            error_msg = f"Unexpected error fetching balance: {e}"
            logger.error(error_msg, exc_info=True)
            raise PositionSizingError(error_msg) from e

    def calculate_risk_amount(self, balance: Decimal) -> Decimal:
        """
        Calculate risk amount based on balance and risk percentage.

        Formula: risk_amount = balance * (risk_percentage / 100)

        Args:
            balance: Account balance

        Returns:
            Risk amount (2% of balance)
        """
        risk_amount = balance * (self.risk_percentage / Decimal('100'))
        logger.debug(
            f"Risk calculation: {balance} * {self.risk_percentage}% = {risk_amount} USDT"
        )
        return risk_amount

    def apply_leverage(self, risk_amount: Decimal) -> Decimal:
        """
        Apply leverage multiplier to risk amount.

        Formula: position_size = risk_amount * leverage

        Args:
            risk_amount: Base risk amount

        Returns:
            Position size with leverage applied
        """
        position_size = risk_amount * Decimal(str(self.leverage))
        logger.debug(
            f"Leverage calculation: {risk_amount} * {self.leverage}x = {position_size} USDT"
        )
        return position_size

    def validate_position_size(self, position_size: Decimal) -> Decimal:
        """
        Validate and adjust position size to meet min/max constraints.

        Args:
            position_size: Calculated position size

        Returns:
            Validated position size within min/max bounds

        Raises:
            PositionSizingError: If position size is below minimum
        """
        original_size = position_size

        # Check minimum
        if position_size < self.min_position_size:
            error_msg = (
                f"Position size {position_size} USDT is below minimum "
                f"{self.min_position_size} USDT"
            )
            logger.error(error_msg)
            raise PositionSizingError(error_msg)

        # Check maximum
        if self.max_position_size and position_size > self.max_position_size:
            logger.warning(
                f"Position size {position_size} USDT exceeds maximum "
                f"{self.max_position_size} USDT, capping to maximum"
            )
            position_size = self.max_position_size

        if position_size != original_size:
            logger.info(f"Position size adjusted: {original_size} -> {position_size} USDT")

        return position_size

    def round_position_size(self, position_size: Decimal) -> Decimal:
        """
        Round position size to specified precision.

        Args:
            position_size: Position size to round

        Returns:
            Rounded position size
        """
        quantize_value = Decimal('1') / Decimal(10 ** self.precision)
        rounded = position_size.quantize(quantize_value, rounding=ROUND_DOWN)

        if rounded != position_size:
            logger.debug(f"Position size rounded: {position_size} -> {rounded}")

        return rounded

    async def calculate_position_size(
        self,
        currency: str = 'USDT',
        custom_balance: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate position size based on current account balance or custom balance.

        This is the main method that orchestrates the entire calculation:
        1. Get account balance (or use custom balance)
        2. Calculate 2% risk amount
        3. Apply 5x leverage
        4. Validate against min/max constraints
        5. Round to exchange precision

        Args:
            currency: Currency to check balance for (default: 'USDT')
            custom_balance: Optional custom balance for testing (bypasses API call)

        Returns:
            Dictionary containing:
            - 'balance': Account balance used
            - 'risk_amount': 2% risk amount
            - 'position_size_base': Position size before leverage
            - 'position_size': Final position size with leverage
            - 'leverage': Leverage used
            - 'risk_percentage': Risk percentage used
            - 'currency': Currency used
            - 'valid': Whether position size is valid

        Raises:
            PositionSizingError: If calculation fails or position size invalid
        """
        try:
            # Step 1: Get balance
            if custom_balance is not None:
                balance = Decimal(str(custom_balance))
                logger.debug(f"Using custom balance: {balance} {currency}")
            else:
                balance = await self.get_account_balance(currency)

            if balance <= 0:
                raise PositionSizingError(
                    f"Insufficient {currency} balance: {balance}"
                )

            # Step 2: Calculate risk amount (2% of balance)
            risk_amount = self.calculate_risk_amount(balance)

            # Step 3: Apply leverage (5x)
            position_size = self.apply_leverage(risk_amount)

            # Step 4: Validate min/max constraints
            position_size = self.validate_position_size(position_size)

            # Step 5: Round to precision
            position_size = self.round_position_size(position_size)

            # Prepare result
            result = {
                'balance': float(balance),
                'risk_amount': float(risk_amount),
                'position_size_base': float(risk_amount),  # Without leverage
                'position_size': float(position_size),
                'leverage': self.leverage,
                'risk_percentage': float(self.risk_percentage),
                'currency': currency,
                'valid': True,
                'min_position_size': float(self.min_position_size),
                'max_position_size': float(self.max_position_size) if self.max_position_size else None
            }

            logger.info(
                f"Position size calculated: {position_size} {currency} "
                f"(balance: {balance}, risk: {risk_amount}, leverage: {self.leverage}x)"
            )

            return result

        except PositionSizingError:
            # Re-raise position sizing errors
            raise
        except Exception as e:
            error_msg = f"Failed to calculate position size: {e}"
            logger.error(error_msg, exc_info=True)
            raise PositionSizingError(error_msg) from e

    def calculate_quantity_for_symbol(
        self,
        position_size_usdt: float,
        entry_price: float,
        symbol_precision: int = 3
    ) -> float:
        """
        Calculate trading quantity for a symbol given position size and entry price.

        Formula: quantity = position_size / entry_price

        Args:
            position_size_usdt: Position size in USDT
            entry_price: Entry price for the symbol
            symbol_precision: Decimal places for symbol quantity (default: 3)

        Returns:
            Trading quantity rounded to symbol precision

        Raises:
            ValueError: If parameters are invalid
        """
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        if position_size_usdt <= 0:
            raise ValueError("position_size_usdt must be positive")

        # Calculate quantity
        quantity = Decimal(str(position_size_usdt)) / Decimal(str(entry_price))

        # Round to symbol precision
        quantize_value = Decimal('1') / Decimal(10 ** symbol_precision)
        quantity = quantity.quantize(quantize_value, rounding=ROUND_DOWN)

        logger.debug(
            f"Quantity calculation: {position_size_usdt} USDT / {entry_price} = "
            f"{quantity} (precision: {symbol_precision})"
        )

        return float(quantity)

    def update_parameters(
        self,
        risk_percentage: Optional[float] = None,
        leverage: Optional[int] = None,
        min_position_size: Optional[float] = None,
        max_position_size: Optional[float] = None
    ) -> None:
        """
        Update position sizing parameters.

        Args:
            risk_percentage: New risk percentage (None = no change)
            leverage: New leverage (None = no change)
            min_position_size: New minimum position size (None = no change)
            max_position_size: New maximum position size (None = no change)

        Raises:
            ValueError: If new parameters are invalid
        """
        if risk_percentage is not None:
            if not 0 < risk_percentage <= 100:
                raise ValueError("risk_percentage must be between 0 and 100")
            self.risk_percentage = Decimal(str(risk_percentage))
            logger.info(f"Risk percentage updated to {risk_percentage}%")

        if leverage is not None:
            if leverage <= 0:
                raise ValueError("leverage must be positive")
            self.leverage = leverage
            logger.info(f"Leverage updated to {leverage}x")

        if min_position_size is not None:
            if min_position_size <= 0:
                raise ValueError("min_position_size must be positive")
            self.min_position_size = Decimal(str(min_position_size))
            logger.info(f"Minimum position size updated to {min_position_size} USDT")

        if max_position_size is not None:
            if max_position_size <= float(self.min_position_size):
                raise ValueError("max_position_size must be greater than min_position_size")
            self.max_position_size = Decimal(str(max_position_size))
            logger.info(f"Maximum position size updated to {max_position_size} USDT")

    def get_parameters(self) -> Dict[str, Any]:
        """
        Get current position sizing parameters.

        Returns:
            Dictionary with current parameters
        """
        return {
            'risk_percentage': float(self.risk_percentage),
            'leverage': self.leverage,
            'min_position_size': float(self.min_position_size),
            'max_position_size': float(self.max_position_size) if self.max_position_size else None,
            'precision': self.precision
        }
