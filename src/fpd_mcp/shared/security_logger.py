"""
Comprehensive security event logging.

Fixes:
- CWE-223: Omission of Security-relevant Information
- CWE-778: Insufficient Logging

Provides specific security event types for:
- Authentication failures/successes
- Authorization denials
- Input validation failures
- Rate limiting events
- Suspicious activity detection
- Configuration changes
- Data access violations
"""
from enum import Enum
from typing import Optional, Dict, Any
import logging
from .structured_logging import StructuredLogger
from .log_sanitizer import LogSanitizer


class SecurityEventType(Enum):
    """Specific security event types for detailed tracking"""
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHORIZATION_DENIED = "authorization_denied"
    API_KEY_VALIDATION_FAILED = "api_key_validation_failed"
    INPUT_VALIDATION_FAILED = "input_validation_failed"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    UNUSUAL_ACCESS_PATTERN = "unusual_access_pattern"
    CONFIGURATION_CHANGED = "configuration_changed"
    PRIVILEGE_ESCALATION_ATTEMPT = "privilege_escalation_attempt"
    DATA_ACCESS_VIOLATION = "data_access_violation"
    LOG_TAMPERING_DETECTED = "log_tampering_detected"
    SECURITY_SCAN_DETECTED = "security_scan_detected"


class SecurityLogger:
    """Enhanced security logger with specific event types"""

    def __init__(self):
        self.logger = StructuredLogger("fpd_mcp.security")
        self.sanitizer = LogSanitizer()

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
            request_id: Optional request ID for correlation
            api_key_prefix: First 5 characters of API key (safe to log)
        """
        self.logger.log_security_event(
            event_description=f"Authentication failed: {reason}",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.AUTHENTICATION_FAILURE.value,
                "reason": reason,
                "api_key_prefix": api_key_prefix,  # Only first 5 chars
                "request_id": request_id
            },
            severity="high"
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
            request_id: Optional request ID for correlation
        """
        self.logger.log_security_event(
            event_description="Authentication successful",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.AUTHENTICATION_SUCCESS.value,
                "api_key_prefix": api_key_prefix,
                "request_id": request_id
            },
            severity="low"
        )

    def log_authorization_denied(
        self,
        client_ip: str,
        resource: str,
        required_permission: str,
        request_id: Optional[str] = None
    ):
        """
        Log authorization denials.

        Args:
            client_ip: Client IP address
            resource: Resource that was denied
            required_permission: Permission that was required
            request_id: Optional request ID for correlation
        """
        self.logger.log_security_event(
            event_description=f"Authorization denied for resource: {resource}",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.AUTHORIZATION_DENIED.value,
                "resource": resource,
                "required_permission": required_permission,
                "request_id": request_id
            },
            severity="medium"
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
        self.logger.log_security_event(
            event_description=f"Rate limit exceeded on {endpoint}",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.RATE_LIMIT_EXCEEDED.value,
                "endpoint": endpoint,
                "current_rate": current_rate,
                "limit": limit,
                "window_seconds": window_seconds
            },
            severity="medium"
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
            client_ip: Optional client IP address
            request_id: Optional request ID for correlation
        """
        # Sanitize field value
        safe_value = self.sanitizer.sanitize_string(str(field_value)[:50])

        self.logger.log_security_event(
            event_description=f"Input validation failed: {field_name}",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.INPUT_VALIDATION_FAILED.value,
                "field_name": field_name,
                "field_value": safe_value,
                "validation_rule": validation_rule,
                "request_id": request_id
            },
            severity="medium"
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
        # Sanitize indicators
        safe_indicators = self.sanitizer.sanitize_for_json(indicators)

        self.logger.log_security_event(
            event_description=f"Suspicious activity: {activity_description}",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.SUSPICIOUS_ACTIVITY.value,
                "indicators": safe_indicators,
                "risk_score": risk_score
            },
            severity="high"
        )

    def log_configuration_change(
        self,
        setting_name: str,
        old_value: Any,
        new_value: Any,
        changed_by: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """
        Log security-relevant configuration changes.

        Args:
            setting_name: Name of the setting changed
            old_value: Previous value (will be sanitized)
            new_value: New value (will be sanitized)
            changed_by: User/process that made the change
            reason: Optional reason for the change
        """
        # Sanitize values
        safe_old = self.sanitizer.sanitize_string(str(old_value)[:100])
        safe_new = self.sanitizer.sanitize_string(str(new_value)[:100])

        self.logger.log_security_event(
            event_description=f"Configuration changed: {setting_name}",
            client_ip=None,
            request_details={
                "event_type": SecurityEventType.CONFIGURATION_CHANGED.value,
                "setting_name": setting_name,
                "old_value": safe_old,
                "new_value": safe_new,
                "changed_by": changed_by,
                "reason": reason
            },
            severity="medium"
        )

    def log_data_access_violation(
        self,
        client_ip: str,
        resource: str,
        violation_type: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log data access violations.

        Args:
            client_ip: Client IP address
            resource: Resource that was accessed
            violation_type: Type of violation (e.g., "unauthorized_access", "data_leak")
            details: Optional additional details
        """
        safe_details = self.sanitizer.sanitize_for_json(details) if details else {}

        self.logger.log_security_event(
            event_description=f"Data access violation: {violation_type} on {resource}",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.DATA_ACCESS_VIOLATION.value,
                "resource": resource,
                "violation_type": violation_type,
                "details": safe_details
            },
            severity="high"
        )

    def log_security_scan_detected(
        self,
        client_ip: str,
        scan_type: str,
        indicators: Dict[str, Any]
    ):
        """
        Log detected security scanning activity.

        Args:
            client_ip: Client IP address
            scan_type: Type of scan detected (e.g., "port_scan", "vulnerability_scan")
            indicators: Indicators that led to detection
        """
        safe_indicators = self.sanitizer.sanitize_for_json(indicators)

        self.logger.log_security_event(
            event_description=f"Security scan detected: {scan_type}",
            client_ip=client_ip,
            request_details={
                "event_type": SecurityEventType.SECURITY_SCAN_DETECTED.value,
                "scan_type": scan_type,
                "indicators": safe_indicators
            },
            severity="high"
        )


# Global security logger instance
security_logger = SecurityLogger()
