"""
Structured JSON logging for monitoring and observability

Provides consistent structured logging format for better monitoring integration
and improved debugging capabilities.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional
from enum import Enum
from .log_sanitizer import LogSanitizer


class LogLevel(Enum):
    """Log levels for structured logging"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(Enum):
    """Types of events for categorization"""
    API_REQUEST = "api_request"
    API_RESPONSE = "api_response"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    CIRCUIT_BREAKER = "circuit_breaker"
    SECURITY_EVENT = "security_event"
    ERROR_EVENT = "error_event"
    PERFORMANCE = "performance"
    HEALTH_CHECK = "health_check"
    VALIDATION = "validation"


class StructuredLogger:
    """Structured logger for consistent JSON logging format"""
    
    def __init__(self, logger_name: str = __name__):
        """
        Initialize structured logger
        
        Args:
            logger_name: Name for the logger instance
        """
        self.logger = logging.getLogger(logger_name)
        self.sanitizer = LogSanitizer()
    
    def _create_base_event(
        self,
        level: LogLevel,
        event_type: EventType,
        message: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Create base event structure with sanitization"""
        # Sanitize message and all kwargs
        safe_message = self.sanitizer.sanitize_string(message)
        safe_kwargs = self.sanitizer.sanitize_for_json(kwargs)
        
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level.value,
            "event_type": event_type.value,
            "message": safe_message,
            "logger": self.logger.name,
            **safe_kwargs
        }
    
    def log_api_request(
        self,
        method: str,
        endpoint: str,
        request_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        user_agent: Optional[str] = None
    ):
        """Log API request with structured format"""
        event = self._create_base_event(
            LogLevel.INFO,
            EventType.API_REQUEST,
            f"{method} {endpoint}",
            request_id=request_id,
            method=method,
            endpoint=endpoint,
            parameters=parameters or {},
            user_agent=user_agent
        )
        self.logger.info(json.dumps(event))
    
    def log_api_response(
        self,
        request_id: str,
        status_code: int,
        response_time_ms: float,
        response_size_bytes: Optional[int] = None,
        error_details: Optional[str] = None
    ):
        """Log API response with performance metrics"""
        level = LogLevel.ERROR if status_code >= 400 else LogLevel.INFO
        
        event = self._create_base_event(
            level,
            EventType.API_RESPONSE,
            f"Response {status_code} in {response_time_ms:.2f}ms",
            request_id=request_id,
            status_code=status_code,
            response_time_ms=response_time_ms,
            response_size_bytes=response_size_bytes,
            error_details=error_details
        )
        
        if level == LogLevel.ERROR:
            self.logger.error(json.dumps(event))
        else:
            self.logger.info(json.dumps(event))
    
    def log_cache_event(
        self,
        cache_key: str,
        hit: bool,
        method_name: str,
        ttl_seconds: Optional[int] = None
    ):
        """Log cache hit/miss events"""
        event_type = EventType.CACHE_HIT if hit else EventType.CACHE_MISS
        message = f"Cache {'hit' if hit else 'miss'} for {method_name}"
        
        event = self._create_base_event(
            LogLevel.DEBUG,
            event_type,
            message,
            cache_key=cache_key[:16] + "..." if len(cache_key) > 16 else cache_key,
            method_name=method_name,
            ttl_seconds=ttl_seconds
        )
        self.logger.debug(json.dumps(event))
    
    def log_circuit_breaker_event(
        self,
        circuit_name: str,
        old_state: str,
        new_state: str,
        failure_count: int,
        failure_threshold: int
    ):
        """Log circuit breaker state changes"""
        event = self._create_base_event(
            LogLevel.WARNING,
            EventType.CIRCUIT_BREAKER,
            f"Circuit breaker '{circuit_name}' changed from {old_state} to {new_state}",
            circuit_name=circuit_name,
            old_state=old_state,
            new_state=new_state,
            failure_count=failure_count,
            failure_threshold=failure_threshold
        )
        self.logger.warning(json.dumps(event))
    
    def log_security_event(
        self,
        event_description: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_details: Optional[Dict[str, Any]] = None,
        severity: str = "medium"
    ):
        """Log security-related events"""
        event = self._create_base_event(
            LogLevel.WARNING,
            EventType.SECURITY_EVENT,
            event_description,
            client_ip=client_ip,
            user_agent=user_agent,
            request_details=request_details or {},
            severity=severity
        )
        self.logger.warning(json.dumps(event))
    
    def log_performance_metric(
        self,
        operation: str,
        duration_ms: float,
        details: Optional[Dict[str, Any]] = None
    ):
        """Log performance metrics"""
        event = self._create_base_event(
            LogLevel.INFO,
            EventType.PERFORMANCE,
            f"{operation} completed in {duration_ms:.2f}ms",
            operation=operation,
            duration_ms=duration_ms,
            details=details or {}
        )
        self.logger.info(json.dumps(event))
    
    def log_health_check(
        self,
        component: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        response_time_ms: Optional[float] = None
    ):
        """Log health check results"""
        level = LogLevel.ERROR if status.lower() == "unhealthy" else LogLevel.INFO
        
        event = self._create_base_event(
            level,
            EventType.HEALTH_CHECK,
            f"{component} health check: {status}",
            component=component,
            status=status,
            response_time_ms=response_time_ms,
            details=details or {}
        )
        
        if level == LogLevel.ERROR:
            self.logger.error(json.dumps(event))
        else:
            self.logger.info(json.dumps(event))
    
    def log_validation_error(
        self,
        field_name: str,
        field_value: Any,
        validation_rule: str,
        error_message: str
    ):
        """Log validation errors"""
        event = self._create_base_event(
            LogLevel.WARNING,
            EventType.VALIDATION,
            f"Validation failed for {field_name}: {error_message}",
            field_name=field_name,
            field_value=str(field_value)[:100],  # Truncate long values
            validation_rule=validation_rule,
            error_message=error_message
        )
        self.logger.warning(json.dumps(event))
    
    def log_error(
        self,
        error_message: str,
        error_type: str,
        stack_trace: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Log error events with context"""
        event = self._create_base_event(
            LogLevel.ERROR,
            EventType.ERROR_EVENT,
            error_message,
            error_type=error_type,
            stack_trace=stack_trace,
            context=context or {}
        )
        self.logger.error(json.dumps(event))


class PerformanceTimer:
    """Context manager for measuring operation performance"""
    
    def __init__(self, structured_logger: StructuredLogger, operation_name: str, details: Optional[Dict[str, Any]] = None):
        self.logger = structured_logger
        self.operation_name = operation_name
        self.details = details or {}
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration_ms = (time.time() - self.start_time) * 1000
            
            if exc_type is not None:
                # Log error with performance context
                self.details["duration_ms"] = duration_ms
                self.logger.log_error(
                    f"Operation '{self.operation_name}' failed after {duration_ms:.2f}ms: {str(exc_val)}",
                    error_type=exc_type.__name__,
                    context=self.details
                )
            else:
                # Log successful performance metric
                self.logger.log_performance_metric(
                    operation=self.operation_name,
                    duration_ms=duration_ms,
                    details=self.details
                )


# Global structured logger instance
structured_logger = StructuredLogger("fpd_mcp")