"""
Rate limiting for USPTO API compliance

Implements USPTO's download limit of 5 files per 10 seconds per IP address.
"""
import time
from collections import defaultdict, deque
from typing import Dict, Deque
from ..config import api_constants
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)


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
        self.requests: Dict[str, Deque[float]] = defaultdict(deque)

    def is_allowed(self, client_ip: str) -> bool:
        """
        Check if a request from the given IP is allowed

        Args:
            client_ip: Client IP address

        Returns:
            True if request is allowed, False if rate limited
        """
        now = time.time()
        client_requests = self.requests[client_ip]

        # Remove requests outside the time window
        while client_requests and client_requests[0] < now - self.time_window:
            client_requests.popleft()

        # Check if we're at the limit
        if len(client_requests) >= self.max_requests:
            logger.warning(
                f"Rate limit exceeded for IP {client_ip}: "
                f"{len(client_requests)} requests in {self.time_window} seconds"
            )
            return False

        # Add the current request
        client_requests.append(now)
        logger.info(
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
        now = time.time()
        client_requests = self.requests[client_ip]

        # Remove old requests
        while client_requests and client_requests[0] < now - self.time_window:
            client_requests.popleft()

        return max(0, self.max_requests - len(client_requests))

    def get_reset_time(self, client_ip: str) -> float:
        """
        Get time when rate limit will reset for the IP

        Args:
            client_ip: Client IP address

        Returns:
            Unix timestamp when oldest request will expire
        """
        client_requests = self.requests[client_ip]
        if not client_requests:
            return time.time()

        return client_requests[0] + self.time_window


# Global rate limiter instance
rate_limiter = RateLimiter()
