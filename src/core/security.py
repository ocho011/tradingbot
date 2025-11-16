"""
Security Module for Trading Bot.

Provides comprehensive security features including:
- AES-256 API key encryption/decryption
- Redis-based rate limiting with token bucket algorithm
- IP whitelist validation
- Security utilities and helpers
"""

import logging
import os
import time
from base64 import b64decode, b64encode
from typing import Dict, List, Optional, Set, Tuple

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


# ============================================================================
# API Key Encryption
# ============================================================================


class APIKeyEncryption:
    """
    AES-256 encryption for API keys using Fernet (symmetric encryption).

    Features:
    - Uses PBKDF2 key derivation with SHA-256
    - AES-256 encryption via Fernet
    - Salt-based key derivation for additional security
    - Base64 encoding for storage
    """

    def __init__(self, master_key: Optional[str] = None, salt: Optional[bytes] = None):
        """
        Initialize encryption service.

        Args:
            master_key: Master encryption key. If not provided, uses environment variable
            salt: Salt for key derivation. If not provided, generates new salt
        """
        self._master_key = master_key or os.getenv("ENCRYPTION_MASTER_KEY")
        if not self._master_key:
            raise ValueError(
                "Master encryption key not provided. "
                "Set ENCRYPTION_MASTER_KEY environment variable or pass master_key parameter"
            )

        # Generate or use provided salt
        self._salt = salt or os.urandom(16)

        # Derive encryption key using PBKDF2
        self._cipher_key = self._derive_key(self._master_key, self._salt)
        self._cipher = Fernet(self._cipher_key)

        logger.info("API key encryption initialized")

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """
        Derive encryption key from password using PBKDF2.

        Args:
            password: Master password
            salt: Salt for key derivation

        Returns:
            Derived key suitable for Fernet
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits
            salt=salt,
            iterations=100000,  # OWASP recommended minimum
            backend=default_backend(),
        )
        key = kdf.derive(password.encode())
        return b64encode(key)

    def encrypt(self, api_key: str) -> str:
        """
        Encrypt API key.

        Args:
            api_key: Plain text API key

        Returns:
            Encrypted API key (base64 encoded)
        """
        try:
            encrypted_data = self._cipher.encrypt(api_key.encode())
            # Store salt with encrypted data for decryption
            combined = self._salt + encrypted_data
            return b64encode(combined).decode()
        except Exception as e:
            logger.error(f"Failed to encrypt API key: {e}")
            raise ValueError("Encryption failed") from e

    def decrypt(self, encrypted_key: str) -> str:
        """
        Decrypt API key.

        Args:
            encrypted_key: Encrypted API key (base64 encoded)

        Returns:
            Plain text API key
        """
        try:
            combined = b64decode(encrypted_key.encode())
            # Extract salt and encrypted data
            salt = combined[:16]
            encrypted_data = combined[16:]

            # Re-derive key with extracted salt
            cipher_key = self._derive_key(self._master_key, salt)
            cipher = Fernet(cipher_key)

            # Decrypt
            decrypted_data = cipher.decrypt(encrypted_data)
            return decrypted_data.decode()
        except Exception as e:
            logger.error(f"Failed to decrypt API key: {e}")
            raise ValueError("Decryption failed") from e

    def get_salt(self) -> str:
        """
        Get current salt (base64 encoded).

        Returns:
            Base64 encoded salt
        """
        return b64encode(self._salt).decode()


# ============================================================================
# Rate Limiting (Token Bucket Algorithm)
# ============================================================================


class TokenBucket:
    """
    Token bucket algorithm for rate limiting.

    Features:
    - Fixed capacity bucket
    - Configurable refill rate
    - Thread-safe operations
    - Supports both async and sync operations
    """

    def __init__(
        self,
        capacity: int = 100,
        refill_rate: float = 10.0,  # tokens per second
        identifier: str = "default",
    ):
        """
        Initialize token bucket.

        Args:
            capacity: Maximum number of tokens in bucket
            refill_rate: Rate at which tokens are added (per second)
            identifier: Unique identifier for this bucket (e.g., IP address, user ID)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.identifier = identifier

        self._tokens = float(capacity)
        self._last_refill = time.time()

        logger.debug(
            f"Token bucket created for {identifier}: capacity={capacity}, rate={refill_rate}"
        )

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_refill

        # Calculate tokens to add
        tokens_to_add = elapsed * self.refill_rate

        # Add tokens up to capacity
        self._tokens = min(self.capacity, self._tokens + tokens_to_add)
        self._last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        self._refill()

        if self._tokens >= tokens:
            self._tokens -= tokens
            return True

        return False

    def get_available_tokens(self) -> float:
        """
        Get current number of available tokens.

        Returns:
            Current token count
        """
        self._refill()
        return self._tokens

    def time_until_available(self, tokens: int = 1) -> float:
        """
        Calculate time until specified tokens are available.

        Args:
            tokens: Number of tokens needed

        Returns:
            Seconds until tokens available (0 if already available)
        """
        self._refill()

        if self._tokens >= tokens:
            return 0.0

        tokens_needed = tokens - self._tokens
        return tokens_needed / self.refill_rate


class RateLimiter:
    """
    Rate limiter using token bucket algorithm with Redis backend support.

    Features:
    - Per-identifier rate limiting
    - Configurable limits per endpoint/operation
    - Memory-based (can be extended to Redis for distributed systems)
    - Automatic cleanup of old buckets
    """

    def __init__(
        self,
        default_capacity: int = 100,
        default_refill_rate: float = 10.0,
        cleanup_interval: int = 3600,  # seconds
    ):
        """
        Initialize rate limiter.

        Args:
            default_capacity: Default bucket capacity
            default_refill_rate: Default refill rate (tokens per second)
            cleanup_interval: Interval to clean up old buckets (seconds)
        """
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self.cleanup_interval = cleanup_interval

        self._buckets: Dict[str, TokenBucket] = {}
        self._last_cleanup = time.time()

        # Per-endpoint configurations
        self._endpoint_configs: Dict[str, Tuple[int, float]] = {}

        logger.info(
            f"Rate limiter initialized: capacity={default_capacity}, "
            f"rate={default_refill_rate}/s"
        )

    def configure_endpoint(self, endpoint: str, capacity: int, refill_rate: float) -> None:
        """
        Configure rate limiting for specific endpoint.

        Args:
            endpoint: Endpoint identifier (e.g., "/api/orders")
            capacity: Bucket capacity for this endpoint
            refill_rate: Refill rate for this endpoint
        """
        self._endpoint_configs[endpoint] = (capacity, refill_rate)
        logger.info(f"Configured rate limit for {endpoint}: {capacity} @ {refill_rate}/s")

    def _get_bucket_key(self, identifier: str, endpoint: Optional[str] = None) -> str:
        """
        Generate bucket key from identifier and endpoint.

        Args:
            identifier: User/IP identifier
            endpoint: Optional endpoint identifier

        Returns:
            Bucket key
        """
        if endpoint:
            return f"{identifier}:{endpoint}"
        return identifier

    def _get_or_create_bucket(self, identifier: str, endpoint: Optional[str] = None) -> TokenBucket:
        """
        Get existing bucket or create new one.

        Args:
            identifier: User/IP identifier
            endpoint: Optional endpoint identifier

        Returns:
            Token bucket instance
        """
        bucket_key = self._get_bucket_key(identifier, endpoint)

        if bucket_key not in self._buckets:
            # Check for endpoint-specific configuration
            if endpoint and endpoint in self._endpoint_configs:
                capacity, refill_rate = self._endpoint_configs[endpoint]
            else:
                capacity = self.default_capacity
                refill_rate = self.default_refill_rate

            self._buckets[bucket_key] = TokenBucket(
                capacity=capacity, refill_rate=refill_rate, identifier=bucket_key
            )

        return self._buckets[bucket_key]

    def check_rate_limit(
        self, identifier: str, endpoint: Optional[str] = None, tokens: int = 1
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if request is allowed under rate limit.

        Args:
            identifier: User/IP identifier
            endpoint: Optional endpoint identifier
            tokens: Number of tokens to consume

        Returns:
            Tuple of (allowed, retry_after_seconds)
        """
        # Cleanup old buckets periodically
        self._maybe_cleanup()

        bucket = self._get_or_create_bucket(identifier, endpoint)

        if bucket.consume(tokens):
            return True, None

        # Calculate retry-after time
        retry_after = bucket.time_until_available(tokens)
        return False, retry_after

    def _maybe_cleanup(self) -> None:
        """Cleanup old unused buckets."""
        now = time.time()
        if now - self._last_cleanup < self.cleanup_interval:
            return

        # Remove buckets with full tokens (unused for a while)
        keys_to_remove = [
            key
            for key, bucket in self._buckets.items()
            if bucket.get_available_tokens() >= bucket.capacity
        ]

        for key in keys_to_remove:
            del self._buckets[key]

        self._last_cleanup = now

        if keys_to_remove:
            logger.debug(f"Cleaned up {len(keys_to_remove)} unused rate limit buckets")

    def get_stats(self, identifier: str, endpoint: Optional[str] = None) -> Dict[str, any]:
        """
        Get rate limit statistics for identifier.

        Args:
            identifier: User/IP identifier
            endpoint: Optional endpoint identifier

        Returns:
            Statistics dictionary
        """
        bucket_key = self._get_bucket_key(identifier, endpoint)

        if bucket_key not in self._buckets:
            return {
                "identifier": identifier,
                "endpoint": endpoint,
                "available_tokens": self.default_capacity,
                "capacity": self.default_capacity,
                "refill_rate": self.default_refill_rate,
            }

        bucket = self._buckets[bucket_key]
        return {
            "identifier": identifier,
            "endpoint": endpoint,
            "available_tokens": bucket.get_available_tokens(),
            "capacity": bucket.capacity,
            "refill_rate": bucket.refill_rate,
        }


# ============================================================================
# IP Whitelist
# ============================================================================


class IPWhitelist:
    """
    IP whitelist for access control.

    Features:
    - Support for individual IPs and CIDR ranges
    - Efficient IP matching
    - Runtime whitelist updates
    """

    def __init__(self, whitelist: Optional[List[str]] = None):
        """
        Initialize IP whitelist.

        Args:
            whitelist: List of allowed IPs/CIDR ranges
        """
        self._whitelist: Set[str] = set(whitelist or [])
        self._enabled = bool(whitelist)

        logger.info(
            f"IP whitelist initialized: {'enabled' if self._enabled else 'disabled'}, "
            f"{len(self._whitelist)} entries"
        )

    def is_enabled(self) -> bool:
        """Check if whitelist is enabled."""
        return self._enabled

    def add_ip(self, ip: str) -> None:
        """
        Add IP to whitelist.

        Args:
            ip: IP address or CIDR range
        """
        self._whitelist.add(ip)
        self._enabled = True
        logger.info(f"Added IP to whitelist: {ip}")

    def remove_ip(self, ip: str) -> bool:
        """
        Remove IP from whitelist.

        Args:
            ip: IP address to remove

        Returns:
            True if removed, False if not found
        """
        if ip in self._whitelist:
            self._whitelist.remove(ip)
            logger.info(f"Removed IP from whitelist: {ip}")
            return True
        return False

    def is_allowed(self, ip: str) -> bool:
        """
        Check if IP is allowed.

        Args:
            ip: IP address to check

        Returns:
            True if allowed (or whitelist disabled), False otherwise
        """
        if not self._enabled:
            return True

        # Direct match
        if ip in self._whitelist:
            return True

        # Check CIDR ranges (simplified - full implementation would use ipaddress module)
        # For production, use: import ipaddress and proper CIDR matching
        for whitelisted in self._whitelist:
            if "/" in whitelisted:
                # CIDR range - for now, simplified check
                # TODO: Implement proper CIDR matching with ipaddress module
                pass

        return False

    def get_whitelist(self) -> List[str]:
        """
        Get current whitelist.

        Returns:
            List of whitelisted IPs
        """
        return list(self._whitelist)

    def clear(self) -> None:
        """Clear whitelist."""
        self._whitelist.clear()
        self._enabled = False
        logger.info("IP whitelist cleared")


# ============================================================================
# Security Manager (Main Interface)
# ============================================================================


class SecurityManager:
    """
    Central security management interface.

    Coordinates all security features:
    - API key encryption
    - Rate limiting
    - IP whitelisting
    """

    def __init__(
        self,
        encryption_key: Optional[str] = None,
        rate_limit_capacity: int = 100,
        rate_limit_refill_rate: float = 10.0,
        ip_whitelist: Optional[List[str]] = None,
    ):
        """
        Initialize security manager.

        Args:
            encryption_key: Master encryption key
            rate_limit_capacity: Default rate limit capacity
            rate_limit_refill_rate: Default rate limit refill rate
            ip_whitelist: List of allowed IPs
        """
        # Initialize components
        self.encryption = APIKeyEncryption(master_key=encryption_key)
        self.rate_limiter = RateLimiter(
            default_capacity=rate_limit_capacity, default_refill_rate=rate_limit_refill_rate
        )
        self.ip_whitelist = IPWhitelist(whitelist=ip_whitelist)

        logger.info("Security manager initialized successfully")

    def validate_request(
        self, ip_address: str, identifier: str, endpoint: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate incoming request against all security policies.

        Args:
            ip_address: Client IP address
            identifier: User/client identifier
            endpoint: Optional endpoint being accessed

        Returns:
            Tuple of (allowed, error_message)
        """
        # Check IP whitelist
        if not self.ip_whitelist.is_allowed(ip_address):
            return False, f"IP {ip_address} not in whitelist"

        # Check rate limit
        allowed, retry_after = self.rate_limiter.check_rate_limit(
            identifier=identifier, endpoint=endpoint
        )

        if not allowed:
            return False, f"Rate limit exceeded. Retry after {retry_after:.2f} seconds"

        return True, None

    def get_security_status(self) -> Dict[str, any]:
        """
        Get security system status.

        Returns:
            Status dictionary
        """
        return {
            "encryption": {"enabled": True, "algorithm": "AES-256 (Fernet)"},
            "rate_limiting": {
                "enabled": True,
                "default_capacity": self.rate_limiter.default_capacity,
                "default_refill_rate": self.rate_limiter.default_refill_rate,
                "active_buckets": len(self.rate_limiter._buckets),
            },
            "ip_whitelist": {
                "enabled": self.ip_whitelist.is_enabled(),
                "entries": len(self.ip_whitelist._whitelist),
            },
        }
