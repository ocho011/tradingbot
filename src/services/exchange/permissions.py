"""
Binance API permission verification and monitoring system.

Features:
- Read permission verification (account access)
- Trading permission verification (order placement capability)
- Permission caching with 1-hour TTL
- Periodic re-validation (1-hour interval)
- Change detection and event notifications
- Permission status tracking and alerts
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from src.core.constants import EventType
from src.core.events import Event, EventBus

logger = logging.getLogger(__name__)


class PermissionType(Enum):
    """API permission types."""

    READ = "read"
    TRADE = "trade"
    WITHDRAW = "withdraw"  # Not checked by default, but available


@dataclass
class PermissionStatus:
    """
    Tracks the status of API permissions.

    Attributes:
        read: Whether read permission is granted
        trade: Whether trading permission is granted
        last_checked: Timestamp of last verification
        last_changed: Timestamp of last permission change
        check_count: Number of verification checks performed
        error_count: Number of verification errors encountered
    """

    read: bool = False
    trade: bool = False
    last_checked: Optional[float] = None
    last_changed: Optional[float] = None
    check_count: int = 0
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert status to dictionary."""
        return {
            "read": self.read,
            "trade": self.trade,
            "last_checked": self.last_checked,
            "last_checked_datetime": (
                datetime.fromtimestamp(self.last_checked).isoformat() if self.last_checked else None
            ),
            "last_changed": self.last_changed,
            "last_changed_datetime": (
                datetime.fromtimestamp(self.last_changed).isoformat() if self.last_changed else None
            ),
            "check_count": self.check_count,
            "error_count": self.error_count,
        }

    def has_changed(self, new_read: bool, new_trade: bool) -> bool:
        """Check if permissions have changed."""
        return self.read != new_read or self.trade != new_trade

    def update(self, read: bool, trade: bool) -> None:
        """Update permission status and track changes."""
        current_time = time.time()

        if self.has_changed(read, trade):
            self.last_changed = current_time
            logger.info(
                f"Permission change detected: "
                f"read {self.read}→{read}, trade {self.trade}→{trade}"
            )

        self.read = read
        self.trade = trade
        self.last_checked = current_time
        self.check_count += 1


class PermissionVerifier:
    """
    Manages Binance API permission verification with caching and monitoring.

    Features:
    - Periodic permission verification (default: 1 hour interval)
    - In-memory caching with TTL
    - Change detection and event publishing
    - Error tracking and alerting
    - Graceful degradation on verification failures

    Attributes:
        exchange: ccxt Binance exchange instance
        event_bus: Optional event bus for publishing permission events
        cache_ttl: Cache time-to-live in seconds (default: 3600 = 1 hour)
        revalidate_interval: Interval for periodic re-validation in seconds
    """

    def __init__(
        self,
        exchange: Any,
        event_bus: Optional[EventBus] = None,
        cache_ttl: int = 3600,
        revalidate_interval: int = 3600,
    ):
        """
        Initialize permission verifier.

        Args:
            exchange: ccxt Binance exchange instance
            event_bus: Optional event bus for publishing events
            cache_ttl: Cache TTL in seconds (default: 3600)
            revalidate_interval: Re-validation interval in seconds (default: 3600)
        """
        self.exchange = exchange
        self.event_bus = event_bus
        self.cache_ttl = cache_ttl
        self.revalidate_interval = revalidate_interval

        # Permission status cache
        self._status = PermissionStatus()
        self._status_lock = asyncio.Lock()

        # Periodic validation tracking
        self._validation_task: Optional[asyncio.Task] = None
        self._validation_running = False

        # Warning thresholds
        self._max_consecutive_errors = 3
        self._consecutive_errors = 0

        logger.info(
            f"PermissionVerifier initialized "
            f"(cache_ttl={cache_ttl}s, interval={revalidate_interval}s)"
        )

    async def verify_permissions(self, force_refresh: bool = False) -> Dict[str, bool]:
        """
        Verify API key permissions with caching.

        Args:
            force_refresh: Force re-verification ignoring cache

        Returns:
            Dictionary with permission status:
            - 'read': Can read account data
            - 'trade': Can place orders

        Raises:
            Exception: If verification fails and no cached data available
        """
        async with self._status_lock:
            # Check cache validity
            if not force_refresh and self._is_cache_valid():
                logger.debug(f"Using cached permissions (age: {self._get_cache_age():.1f}s)")
                return {"read": self._status.read, "trade": self._status.trade}

            # Perform fresh verification
            logger.info("Performing fresh permission verification...")

            try:
                # Verify read permission
                read_permission = await self._verify_read_permission()

                # Verify trade permission
                trade_permission = await self._verify_trade_permission()

                # Store previous status before update
                previous_status = (self._status.read, self._status.trade)

                # Check for changes
                permissions_changed = self._status.has_changed(read_permission, trade_permission)

                # Update status
                self._status.update(read_permission, trade_permission)

                # Track consecutive errors for verification failures
                # (not exceptions, but permission denial)
                if not read_permission or not trade_permission:
                    self._consecutive_errors += 1
                else:
                    # Reset error counter only when both permissions succeed
                    self._consecutive_errors = 0

                # Log results
                logger.info(
                    f"✓ Permissions verified: read={read_permission}, trade={trade_permission}"
                )

                # Check if we should alert on consecutive errors
                if self._consecutive_errors >= self._max_consecutive_errors:
                    logger.error(
                        f"⚠ {self._consecutive_errors} consecutive permission "
                        f"verification failures detected!"
                    )

                    # Publish error event after reaching threshold
                    if self.event_bus and self._consecutive_errors == self._max_consecutive_errors:
                        await self.event_bus.publish(
                            Event(
                                event_type=EventType.EXCHANGE_ERROR,
                                priority=8,
                                data={
                                    "exchange": "binance",
                                    "event": "permission_verification_failures",
                                    "consecutive_errors": self._consecutive_errors,
                                    "error": "Permission denied",
                                },
                                source="PermissionVerifier",
                            )
                        )

                # Publish events
                if self.event_bus:
                    # Publish verification success
                    await self.event_bus.publish(
                        Event(
                            event_type=EventType.EXCHANGE_CONNECTED,
                            priority=6,
                            data={
                                "exchange": "binance",
                                "event": "permissions_verified",
                                "permissions": self._status.to_dict(),
                            },
                            source="PermissionVerifier",
                        )
                    )

                    # Publish change event if permissions changed
                    if permissions_changed:
                        await self._publish_change_event(previous_status)

                # Warn if permissions are insufficient
                await self._check_permission_sufficiency()

                return {"read": read_permission, "trade": trade_permission}

            except Exception as e:
                self._status.error_count += 1
                self._consecutive_errors += 1

                logger.error(f"Permission verification failed: {e}", exc_info=True)

                # Check if we should alert on consecutive errors
                if self._consecutive_errors >= self._max_consecutive_errors:
                    logger.error(
                        f"⚠ {self._consecutive_errors} consecutive permission "
                        f"verification failures detected!"
                    )

                    # Publish error event after reaching threshold
                    if self.event_bus and self._consecutive_errors == self._max_consecutive_errors:
                        await self.event_bus.publish(
                            Event(
                                event_type=EventType.EXCHANGE_ERROR,
                                priority=8,
                                data={
                                    "exchange": "binance",
                                    "event": "permission_verification_failures",
                                    "consecutive_errors": self._consecutive_errors,
                                    "error": str(e),
                                },
                                source="PermissionVerifier",
                            )
                        )

                # Return cached data if available, otherwise raise
                if self._status.last_checked:
                    logger.warning(
                        f"Using stale cached permissions " f"(age: {self._get_cache_age():.1f}s)"
                    )
                    return {"read": self._status.read, "trade": self._status.trade}
                else:
                    raise

    async def _verify_read_permission(self) -> bool:
        """
        Verify read permission by fetching account balance.

        Returns:
            True if read permission is granted, False otherwise
        """
        try:
            logger.debug("Testing read permission (fetch_balance)...")
            await self.exchange.fetch_balance()
            logger.debug("✓ Read permission: GRANTED")
            return True
        except Exception as e:
            logger.warning(f"✗ Read permission: DENIED - {e}")
            return False

    async def _verify_trade_permission(self) -> bool:
        """
        Verify trading permission by fetching open orders.

        Note: We use fetch_open_orders as a safe way to test trading permission
        without actually placing orders that could affect the account.

        Returns:
            True if trading permission is granted, False otherwise
        """
        try:
            logger.debug("Testing trade permission (fetch_open_orders)...")
            await self.exchange.fetch_open_orders()
            logger.debug("✓ Trade permission: GRANTED")
            return True
        except Exception as e:
            logger.warning(f"✗ Trade permission: DENIED - {e}")
            return False

    def _is_cache_valid(self) -> bool:
        """Check if cached permission status is still valid."""
        if not self._status.last_checked:
            return False

        age = self._get_cache_age()
        return age < self.cache_ttl

    def _get_cache_age(self) -> float:
        """Get age of cached data in seconds."""
        if not self._status.last_checked:
            return float("inf")
        return time.time() - self._status.last_checked

    async def _check_permission_sufficiency(self) -> None:
        """Check if permissions are sufficient and warn if not."""
        warnings = []

        if not self._status.read:
            warnings.append("⚠ READ permission DENIED - Cannot access account data")

        if not self._status.trade:
            warnings.append("⚠ TRADE permission DENIED - Cannot place orders")

        if warnings:
            for warning in warnings:
                logger.warning(warning)

            if self.event_bus:
                await self.event_bus.publish(
                    Event(
                        event_type=EventType.EXCHANGE_ERROR,
                        priority=7,
                        data={
                            "exchange": "binance",
                            "event": "insufficient_permissions",
                            "warnings": warnings,
                            "permissions": self._status.to_dict(),
                        },
                        source="PermissionVerifier",
                    )
                )

    async def _publish_change_event(self, previous_status: tuple[bool, bool]) -> None:
        """
        Publish permission change event.

        Args:
            previous_status: Tuple of (previous_read, previous_trade)
        """
        if not self.event_bus:
            return

        prev_read, prev_trade = previous_status

        changes = []
        if prev_read != self._status.read:
            changes.append(f"read: {prev_read} → {self._status.read}")
        if prev_trade != self._status.trade:
            changes.append(f"trade: {prev_trade} → {self._status.trade}")

        logger.warning(f"🔔 Permission changes detected: {', '.join(changes)}")

        await self.event_bus.publish(
            Event(
                event_type=EventType.EXCHANGE_ERROR,
                priority=8,
                data={
                    "exchange": "binance",
                    "event": "permissions_changed",
                    "changes": changes,
                    "previous": {"read": prev_read, "trade": prev_trade},
                    "current": {"read": self._status.read, "trade": self._status.trade},
                    "timestamp": time.time(),
                },
                source="PermissionVerifier",
            )
        )

    async def start_periodic_validation(self) -> None:
        """
        Start periodic permission re-validation.

        Automatically re-validates permissions at the configured interval.
        """
        if self._validation_running:
            logger.debug("Periodic validation already running")
            return

        self._validation_running = True
        self._validation_task = asyncio.create_task(
            self._periodic_validation_loop(), name="permission_validation"
        )

        logger.info(
            f"✓ Periodic permission validation started " f"(interval: {self.revalidate_interval}s)"
        )

    async def _periodic_validation_loop(self) -> None:
        """Periodic validation loop implementation."""
        logger.info("Starting periodic permission validation loop")

        try:
            while self._validation_running:
                try:
                    # Wait for the validation interval
                    await asyncio.sleep(self.revalidate_interval)

                    # Perform validation
                    logger.debug("Running periodic permission validation...")
                    await self.verify_permissions(force_refresh=True)

                except asyncio.CancelledError:
                    logger.info("Periodic validation cancelled")
                    raise

                except Exception as e:
                    logger.error(f"Error in periodic validation: {e}", exc_info=True)
                    # Continue despite errors
                    await asyncio.sleep(60)  # Wait 1 minute before retry

        except asyncio.CancelledError:
            logger.info("Periodic validation loop stopped")
        except Exception as e:
            logger.error(f"Fatal error in periodic validation loop: {e}", exc_info=True)
        finally:
            self._validation_running = False
            logger.info("Periodic validation loop terminated")

    async def stop_periodic_validation(self) -> None:
        """Stop periodic permission validation."""
        if not self._validation_running:
            return

        logger.info("Stopping periodic permission validation...")
        self._validation_running = False

        if self._validation_task and not self._validation_task.done():
            self._validation_task.cancel()
            try:
                await self._validation_task
            except asyncio.CancelledError:
                pass

        self._validation_task = None
        logger.info("Periodic permission validation stopped")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current permission status.

        Returns:
            Dictionary with detailed permission status information
        """
        return self._status.to_dict()

    def is_permission_granted(self, permission: PermissionType) -> bool:
        """
        Check if a specific permission is granted.

        Args:
            permission: Permission type to check

        Returns:
            True if permission is granted, False otherwise
        """
        if permission == PermissionType.READ:
            return self._status.read
        elif permission == PermissionType.TRADE:
            return self._status.trade
        else:
            return False

    @property
    def has_read_permission(self) -> bool:
        """Check if read permission is granted."""
        return self._status.read

    @property
    def has_trade_permission(self) -> bool:
        """Check if trading permission is granted."""
        return self._status.trade

    @property
    def is_validation_running(self) -> bool:
        """Check if periodic validation is active."""
        return self._validation_running
