"""
Rate limiting for USPTO API compliance

Implements USPTO's download limit of 5 files per 10 seconds per IP address.
"""
import time
from collections import deque
from typing import Dict, Deque
from ..config import api_constants
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)


def _log_rate_limit_exceeded(client_ip: str, current_rate: int, limit: int,
                             window_seconds: int) -> None:
    """Emit the typed rate-limit event (M-23).

    Imported lazily and never allowed to raise: a security-log write must not
    be able to turn a 429 into a 500.
    """
    try:
        from ..shared.security_logger import security_logger

        security_logger.log_rate_limit_exceeded(
            client_ip=client_ip,
            endpoint="proxy_download",
            current_rate=current_rate,
            limit=limit,
            window_seconds=window_seconds,
        )
    except Exception as audit_error:  # pragma: no cover - defensive
        logger.error(
            f"Security event write failed: {type(audit_error).__name__}"
        )


class RateLimiter:
    """Rate limiter for USPTO document downloads"""

    def __init__(self, max_requests: int = api_constants.USPTO_MAX_DOWNLOADS_PER_WINDOW, time_window: int = api_constants.USPTO_RATE_LIMIT_WINDOW_SECONDS):
        """
        Initialize rate limiter

        Args:
            max_requests: Maximum requests allowed in time window (default: 5)
            time_window: Time window in seconds (default: 10)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        # M-4: a plain dict, not a defaultdict. `requests` is keyed by remote
        # IP on an internet-reachable route, and the defaultdict made every
        # READ insert a permanent entry, so the map grew with the number of
        # distinct addresses ever seen. Buckets are now created only by
        # is_allowed() and are evicted the moment they fall empty.
        self.requests: Dict[str, Deque[float]] = {}

    def _trim(self, client_ip: str, now: float) -> Deque[float]:
        """Drop timestamps outside the window; evict the bucket if it empties."""
        client_requests = self.requests.get(client_ip)
        if client_requests is None:
            return deque()
        while client_requests and client_requests[0] < now - self.time_window:
            client_requests.popleft()
        if not client_requests:
            self.requests.pop(client_ip, None)
        return client_requests

    def is_allowed(self, client_ip: str) -> bool:
        """
        Check if a request from the given IP is allowed

        Args:
            client_ip: Client IP address

        Returns:
            True if request is allowed, False if rate limited
        """
        now = time.time()
        client_requests = self._trim(client_ip, now)

        # Check if we're at the limit
        if len(client_requests) >= self.max_requests:
            logger.warning(
                f"Rate limit exceeded for IP {client_ip}: "
                f"{len(client_requests)} requests in {self.time_window} seconds"
            )
            _log_rate_limit_exceeded(
                client_ip, len(client_requests), self.max_requests,
                self.time_window,
            )
            return False

        # Add the current request
        client_requests.append(now)
        self.requests[client_ip] = client_requests
        # L-22: this was INFO, one line per allowed request on the hot
        # download path, which accelerates rollover of the very file the
        # audit trail lives in. The rejected branch above stays at WARNING —
        # that one is the event worth keeping.
        logger.debug(
            f"Request allowed for IP {client_ip}: "
            f"{len(client_requests)}/{self.max_requests} requests in window"
        )
        return True

    def get_remaining_requests(self, client_ip: str) -> int:
        """
        Get number of remaining requests for the IP

        Args:
            client_ip: Client IP address

        Returns:
            Number of remaining requests in current window
        """
        client_requests = self._trim(client_ip, time.time())

        return max(0, self.max_requests - len(client_requests))

    def get_reset_time(self, client_ip: str) -> float:
        """
        Get time when rate limit will reset for the IP

        Args:
            client_ip: Client IP address

        Returns:
            Unix timestamp when oldest request will expire
        """
        client_requests = self.requests.get(client_ip)
        if not client_requests:
            return time.time()

        return client_requests[0] + self.time_window


# Global rate limiter instance
rate_limiter = RateLimiter()
