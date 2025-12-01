"""
Unified Logging Facade for USPTO FPD MCP

This module consolidates all logging functionality into a single, cohesive interface,
eliminating duplication across 5 separate logging modules.

Fixes Code Duplication:
- Consolidates ~400 lines of duplicated logging/sanitization code
- Combines functionality from:
  * util/logging.py (API key sanitization, HTTP logging)
  * util/secure_logger.py (SecureLogger wrapper)
  * shared/structured_logging.py (StructuredLogger, PerformanceTimer)
  * shared/security_logger.py (SecurityLogger, security events)
  * shared/log_sanitizer.py (LogSanitizer - used as core)

Features:
- Automatic sanitization of all log output (API keys, PII, credentials)
- Structured JSON logging for monitoring integration
- Security event logging with specific event types
- Performance timing with context managers
- HTTP request/response logging
- Single unified interface

Usage:
    from fpd_mcp.shared.unified_logging import get_logger

    logger = get_logger(__name__)

    # Standard logging (automatically sanitized)
    logger.info("Processing request", extra={"user_input": untrusted_data})
    logger.error("Operation failed", exc_info=True)

    # Structured API logging
    logger.log_api_request("POST", "/api/search", request_id="abc123")
    logger.log_api_response(request_id="abc123", status_code=200, response_time_ms=125.5)

    # Security events
    logger.log_authentication_failure(client_ip="127.0.0.1", reason="Invalid API key")
    logger.log_rate_limit_exceeded(client_ip="127.0.0.1", endpoint="/api/search",
                                     current_rate=10, limit=5, window_seconds=10)

    # Performance timing
    with logger.performance_timer("expensive_operation"):
        # Your code here
        pass
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional
from contextlib import contextmanager

from .log_sanitizer import LogSanitizer
from .structured_logging import StructuredLogger, PerformanceTimer
from .security_logger import SecurityLogger


class UnifiedLogger:
    """
    Unified logger combining all logging capabilities with automatic sanitization.

    This class wraps StructuredLogger, SecurityLogger, and LogSanitizer to provide
    a single, comprehensive logging interface.
    """

    def __init__(self, logger_name: str):
        """
        Initialize unified logger.

        Args:
            logger_name: Name for the logger instance (typically __name__)
        """
        self.logger_name = logger_name
        self.logger = logging.getLogger(logger_name)
        self.structured_logger = StructuredLogger(logger_name)
        self.security_logger = SecurityLogger()
        self.sanitizer = LogSanitizer()

    # ===== Standard Logging Methods (with automatic sanitization) =====

    def debug(self, msg: str, *args, **kwargs):
        """
        Log debug message with automatic sanitization.

        Args:
            msg: Log message
            *args: Format arguments
            **kwargs: Additional keyword arguments (extra, exc_info, etc.)
        """
        safe_msg = self.sanitizer.sanitize_string(str(msg))
        if 'extra' in kwargs:
            kwargs['extra'] = self.sanitizer.sanitize_for_json(kwargs['extra'])
        self.logger.debug(safe_msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """
        Log info message with automatic sanitization.

        Args:
            msg: Log message
            *args: Format arguments
            **kwargs: Additional keyword arguments (extra, exc_info, etc.)
        """
        safe_msg = self.sanitizer.sanitize_string(str(msg))
        if 'extra' in kwargs:
            kwargs['extra'] = self.sanitizer.sanitize_for_json(kwargs['extra'])
        self.logger.info(safe_msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """
        Log warning message with automatic sanitization.

        Args:
            msg: Log message
            *args: Format arguments
            **kwargs: Additional keyword arguments (extra, exc_info, etc.)
        """
        safe_msg = self.sanitizer.sanitize_string(str(msg))
        if 'extra' in kwargs:
            kwargs['extra'] = self.sanitizer.sanitize_for_json(kwargs['extra'])
        self.logger.warning(safe_msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """
        Log error message with automatic sanitization.

        Args:
            msg: Log message
            *args: Format arguments
            **kwargs: Additional keyword arguments (extra, exc_info, etc.)
        """
        safe_msg = self.sanitizer.sanitize_string(str(msg))
        if 'extra' in kwargs:
            kwargs['extra'] = self.sanitizer.sanitize_for_json(kwargs['extra'])
        self.logger.error(safe_msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """
        Log critical message with automatic sanitization.

        Args:
            msg: Log message
            *args: Format arguments
            **kwargs: Additional keyword arguments (extra, exc_info, etc.)
        """
        safe_msg = self.sanitizer.sanitize_string(str(msg))
        if 'extra' in kwargs:
            kwargs['extra'] = self.sanitizer.sanitize_for_json(kwargs['extra'])
        self.logger.critical(safe_msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """
        Log exception with automatic sanitization and stack trace.

        Args:
            msg: Log message
            *args: Format arguments
            **kwargs: Additional keyword arguments (extra, etc.)
        """
        safe_msg = self.sanitizer.sanitize_string(str(msg))
        if 'extra' in kwargs:
            kwargs['extra'] = self.sanitizer.sanitize_for_json(kwargs['extra'])
        kwargs.setdefault('exc_info', True)
        self.logger.error(safe_msg, *args, **kwargs)

    # ===== Structured Logging Methods =====

    def log_api_request(
        self,
        method: str,
        endpoint: str,
        request_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        user_agent: Optional[str] = None
    ):
        """
        Log API request with structured format.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint called
            request_id: Request identifier for tracing
            parameters: Request parameters (will be sanitized)
            user_agent: User agent string
        """
        self.structured_logger.log_api_request(
            method=method,
            endpoint=endpoint,
            request_id=request_id,
            parameters=parameters,
            user_agent=user_agent
        )

    def log_api_response(
        self,
        request_id: str,
        status_code: int,
        response_time_ms: float,
        response_size_bytes: Optional[int] = None,
        error_details: Optional[str] = None
    ):
        """
        Log API response with performance metrics.

        Args:
            request_id: Request identifier for correlation
            status_code: HTTP status code
            response_time_ms: Response time in milliseconds
            response_size_bytes: Response size in bytes
            error_details: Error details if status_code >= 400
        """
        self.structured_logger.log_api_response(
            request_id=request_id,
            status_code=status_code,
            response_time_ms=response_time_ms,
            response_size_bytes=response_size_bytes,
            error_details=error_details
        )

    def log_cache_event(
        self,
        cache_key: str,
        hit: bool,
        method_name: str,
        ttl_seconds: Optional[int] = None
    ):
        """
        Log cache hit/miss events.

        Args:
            cache_key: Cache key (will be truncated for privacy)
            hit: True for cache hit, False for cache miss
            method_name: Method that accessed the cache
            ttl_seconds: TTL for cached data
        """
        self.structured_logger.log_cache_event(
            cache_key=cache_key,
            hit=hit,
            method_name=method_name,
            ttl_seconds=ttl_seconds
        )

    def log_circuit_breaker_event(
        self,
        circuit_name: str,
        old_state: str,
        new_state: str,
        failure_count: int,
        failure_threshold: int
    ):
        """
        Log circuit breaker state changes.

        Args:
            circuit_name: Name of the circuit breaker
            old_state: Previous state (CLOSED, OPEN, HALF_OPEN)
            new_state: New state
            failure_count: Current failure count
            failure_threshold: Threshold for opening circuit
        """
        self.structured_logger.log_circuit_breaker_event(
            circuit_name=circuit_name,
            old_state=old_state,
            new_state=new_state,
            failure_count=failure_count,
            failure_threshold=failure_threshold
        )

    def log_performance_metric(
        self,
        operation: str,
        duration_ms: float,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log performance metrics.

        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds
            details: Additional performance details
        """
        self.structured_logger.log_performance_metric(
            operation=operation,
            duration_ms=duration_ms,
            details=details
        )

    def log_health_check(
        self,
        component: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        response_time_ms: Optional[float] = None
    ):
        """
        Log health check results.

        Args:
            component: Component being checked
            status: Health status (healthy, unhealthy, degraded)
            details: Additional health check details
            response_time_ms: Health check response time
        """
        self.structured_logger.log_health_check(
            component=component,
            status=status,
            details=details,
            response_time_ms=response_time_ms
        )

    def log_validation_error(
        self,
        field_name: str,
        field_value: Any,
        validation_rule: str,
        error_message: str
    ):
        """
        Log validation errors.

        Args:
            field_name: Name of the field that failed validation
            field_value: Value that failed (will be sanitized and truncated)
            validation_rule: Validation rule that failed
            error_message: Error message
        """
        self.structured_logger.log_validation_error(
            field_name=field_name,
            field_value=field_value,
            validation_rule=validation_rule,
            error_message=error_message
        )

    # ===== Security Event Logging =====

    def log_security_event(
        self,
        event_description: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_details: Optional[Dict[str, Any]] = None,
        severity: str = "medium"
    ):
        """
        Log generic security event.

        Args:
            event_description: Description of the security event
            client_ip: Client IP address
            user_agent: User agent string
            request_details: Additional request details
            severity: Severity level (low, medium, high)
        """
        self.structured_logger.log_security_event(
            event_description=event_description,
            client_ip=client_ip,
            user_agent=user_agent,
            request_details=request_details,
            severity=severity
        )

    def log_authentication_failure(
        self,
        client_ip: str,
        reason: str,
        request_id: Optional[str] = None,
        api_key_prefix: Optional[str] = None
    ):
        """
        Log authentication failures.

        Args:
            client_ip: Client IP address
            reason: Reason for authentication failure
            request_id: Request ID for correlation
            api_key_prefix: First 5 characters of API key (safe to log)
        """
        self.security_logger.log_authentication_failure(
            client_ip=client_ip,
            reason=reason,
            request_id=request_id,
            api_key_prefix=api_key_prefix
        )

    def log_authentication_success(
        self,
        client_ip: str,
        api_key_prefix: Optional[str] = None,
        request_id: Optional[str] = None
    ):
        """
        Log successful authentication.

        Args:
            client_ip: Client IP address
            api_key_prefix: First 5 characters of API key (safe to log)
            request_id: Request ID for correlation
        """
        self.security_logger.log_authentication_success(
            client_ip=client_ip,
            api_key_prefix=api_key_prefix,
            request_id=request_id
        )

    def log_rate_limit_exceeded(
        self,
        client_ip: str,
        endpoint: str,
        current_rate: int,
        limit: int,
        window_seconds: int
    ):
        """
        Log rate limiting events.

        Args:
            client_ip: Client IP address
            endpoint: Endpoint that was rate limited
            current_rate: Current request rate
            limit: Rate limit threshold
            window_seconds: Time window for rate limiting
        """
        self.security_logger.log_rate_limit_exceeded(
            client_ip=client_ip,
            endpoint=endpoint,
            current_rate=current_rate,
            limit=limit,
            window_seconds=window_seconds
        )

    def log_input_validation_failure(
        self,
        field_name: str,
        field_value: Any,
        validation_rule: str,
        client_ip: Optional[str] = None,
        request_id: Optional[str] = None
    ):
        """
        Log input validation failures.

        Args:
            field_name: Name of the field that failed validation
            field_value: Value that failed (will be sanitized)
            validation_rule: Validation rule that failed
            client_ip: Client IP address
            request_id: Request ID for correlation
        """
        self.security_logger.log_input_validation_failure(
            field_name=field_name,
            field_value=field_value,
            validation_rule=validation_rule,
            client_ip=client_ip,
            request_id=request_id
        )

    def log_suspicious_activity(
        self,
        activity_description: str,
        client_ip: str,
        indicators: Dict[str, Any],
        risk_score: int = 50
    ):
        """
        Log suspicious activity detection.

        Args:
            activity_description: Description of suspicious activity
            client_ip: Client IP address
            indicators: Dictionary of suspicious indicators
            risk_score: Risk score (0-100, default 50)
        """
        self.security_logger.log_suspicious_activity(
            activity_description=activity_description,
            client_ip=client_ip,
            indicators=indicators,
            risk_score=risk_score
        )

    # ===== Performance Timing =====

    @contextmanager
    def performance_timer(self, operation_name: str, details: Optional[Dict[str, Any]] = None):
        """
        Context manager for measuring operation performance.

        Args:
            operation_name: Name of the operation being timed
            details: Additional context about the operation

        Usage:
            with logger.performance_timer("database_query", {"table": "users"}):
                # Your code here
                pass
        """
        timer = PerformanceTimer(self.structured_logger, operation_name, details)
        with timer:
            yield timer


def get_logger(name: str) -> UnifiedLogger:
    """
    Get unified logger instance with automatic sanitization.

    Args:
        name: Logger name (typically __name__)

    Returns:
        UnifiedLogger instance

    Usage:
        from fpd_mcp.shared.unified_logging import get_logger

        logger = get_logger(__name__)
        logger.info("Processing request")
    """
    return UnifiedLogger(name)


# Convenience alias for backward compatibility
get_unified_logger = get_logger
