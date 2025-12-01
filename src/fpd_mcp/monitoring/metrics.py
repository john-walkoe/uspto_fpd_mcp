"""
Prometheus metrics for monitoring and alerting.

Fixes:
- CWE-778: Insufficient Logging (missing monitoring infrastructure)

Provides:
- API request metrics (count, duration, status codes)
- Security event metrics (authentication, validation, rate limiting)
- System health metrics (connections, cache hit rate)
- Error metrics (by type and severity)

Usage:
    from fpd_mcp.monitoring.metrics import track_request_metrics, track_security_event

    @track_request_metrics
    async def my_api_call(*args, **kwargs):
        ...

    track_security_event("authentication_failure", "high")
"""
from prometheus_client import Counter, Histogram, Gauge, Summary
import time
from functools import wraps
from typing import Optional


# API Request metrics
api_requests_total = Counter(
    'fpd_mcp_api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status_code']
)

api_request_duration_seconds = Histogram(
    'fpd_mcp_api_request_duration_seconds',
    'API request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)

# Security metrics
security_events_total = Counter(
    'fpd_mcp_security_events_total',
    'Total security events',
    ['event_type', 'severity']
)

validation_failures_total = Counter(
    'fpd_mcp_validation_failures_total',
    'Total input validation failures',
    ['field_name', 'validation_rule']
)

rate_limit_exceeded_total = Counter(
    'fpd_mcp_rate_limit_exceeded_total',
    'Rate limit exceeded count',
    ['client_ip', 'endpoint']
)

authentication_failures_total = Counter(
    'fpd_mcp_authentication_failures_total',
    'Authentication failures',
    ['reason']
)

# USPTO API metrics
uspto_api_calls_total = Counter(
    'fpd_mcp_uspto_api_calls_total',
    'Total USPTO API calls',
    ['endpoint', 'status_code']
)

uspto_api_duration_seconds = Histogram(
    'fpd_mcp_uspto_api_duration_seconds',
    'USPTO API call duration in seconds',
    ['endpoint'],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
)

# System metrics
active_connections = Gauge(
    'fpd_mcp_active_connections',
    'Number of active connections'
)

cache_hit_rate = Gauge(
    'fpd_mcp_cache_hit_rate',
    'Cache hit rate (0-1)'
)

cache_size_bytes = Gauge(
    'fpd_mcp_cache_size_bytes',
    'Cache size in bytes'
)

# Error metrics
errors_total = Counter(
    'fpd_mcp_errors_total',
    'Total errors',
    ['error_type', 'severity']
)

# Performance metrics
database_query_duration_seconds = Histogram(
    'fpd_mcp_database_query_duration_seconds',
    'Database query duration in seconds',
    ['query_type'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
)

# OCR metrics (Mistral)
ocr_requests_total = Counter(
    'fpd_mcp_ocr_requests_total',
    'Total OCR requests',
    ['status']
)

ocr_duration_seconds = Histogram(
    'fpd_mcp_ocr_duration_seconds',
    'OCR processing duration in seconds',
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0]
)


def track_request_metrics(func):
    """
    Decorator to track API request metrics.

    Usage:
        @track_request_metrics
        async def my_api_handler(request):
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        method = kwargs.get('method', 'UNKNOWN')
        endpoint = kwargs.get('endpoint', 'UNKNOWN')

        start_time = time.time()
        status_code = 500  # Default to error

        try:
            result = await func(*args, **kwargs)
            status_code = 200
            return result
        except Exception as e:
            errors_total.labels(
                error_type=type(e).__name__,
                severity='error'
            ).inc()
            raise
        finally:
            duration = time.time() - start_time

            api_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status_code=status_code
            ).inc()

            api_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)

    return wrapper


def track_security_event(event_type: str, severity: str = "medium"):
    """
    Track security events.

    Args:
        event_type: Type of security event (e.g., "authentication_failure")
        severity: Severity level (low, medium, high, critical)
    """
    security_events_total.labels(
        event_type=event_type,
        severity=severity
    ).inc()


def track_validation_failure(field_name: str, validation_rule: str):
    """
    Track validation failures.

    Args:
        field_name: Name of the field that failed validation
        validation_rule: Validation rule that failed
    """
    validation_failures_total.labels(
        field_name=field_name,
        validation_rule=validation_rule
    ).inc()


def track_rate_limit(client_ip: str, endpoint: str):
    """
    Track rate limiting events.

    Args:
        client_ip: Client IP address that hit rate limit
        endpoint: Endpoint that was rate limited
    """
    rate_limit_exceeded_total.labels(
        client_ip=client_ip,
        endpoint=endpoint
    ).inc()


def track_authentication_failure(reason: str):
    """
    Track authentication failures.

    Args:
        reason: Reason for authentication failure
    """
    authentication_failures_total.labels(
        reason=reason
    ).inc()


def track_uspto_api_call(endpoint: str, duration: float, status_code: int):
    """
    Track USPTO API calls.

    Args:
        endpoint: USPTO API endpoint called
        duration: Duration in seconds
        status_code: HTTP status code
    """
    uspto_api_calls_total.labels(
        endpoint=endpoint,
        status_code=status_code
    ).inc()

    uspto_api_duration_seconds.labels(
        endpoint=endpoint
    ).observe(duration)


def track_cache_stats(hit_rate: float, size_bytes: int):
    """
    Update cache statistics.

    Args:
        hit_rate: Cache hit rate (0.0 to 1.0)
        size_bytes: Cache size in bytes
    """
    cache_hit_rate.set(hit_rate)
    cache_size_bytes.set(size_bytes)


def track_active_connections(count: int):
    """
    Update active connection count.

    Args:
        count: Number of active connections
    """
    active_connections.set(count)


def track_ocr_request(duration: float, success: bool):
    """
    Track OCR request metrics.

    Args:
        duration: Duration in seconds
        success: Whether the OCR request succeeded
    """
    status = "success" if success else "failure"
    ocr_requests_total.labels(status=status).inc()
    ocr_duration_seconds.observe(duration)


def track_error(error_type: str, severity: str = "error"):
    """
    Track error occurrences.

    Args:
        error_type: Type of error (exception class name)
        severity: Severity level (warning, error, critical)
    """
    errors_total.labels(
        error_type=error_type,
        severity=severity
    ).inc()
