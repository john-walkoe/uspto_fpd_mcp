"""
Comprehensive security event logging.

Fixes:
- CWE-223: Omission of Security-relevant Information
- CWE-778: Insufficient Logging

Provides specific security event types for:
- Authentication failures/successes
- Input validation failures
- Rate limiting events
- Suspicious activity detection

L25: log_authorization_denied, log_configuration_change,
log_data_access_violation, and log_security_scan_detected were removed —
they were defined but never invoked anywhere in the codebase (dead code
giving false monitoring confidence). Re-add only alongside a real call site.
"""
from enum import Enum
from typing import Optional, Dict, Any
from .structured_logging import StructuredLogger
from .log_sanitizer import LogSanitizer


class SecurityEventType(Enum):
    """Specific security event types for detailed tracking"""
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHENTICATION_SUCCESS = "authentication_success"
    API_KEY_VALIDATION_FAILED = "api_key_validation_failed"
    INPUT_VALIDATION_FAILED = "input_validation_failed"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    UNUSUAL_ACCESS_PATTERN = "unusual_access_pattern"
    PRIVILEGE_ESCALATION_ATTEMPT = "privilege_escalation_attempt"
    LOG_TAMPERING_DETECTED = "log_tampering_detected"
    ADMIN_ACTION = "admin_action"


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

    def log_admin_action(
        self,
        actor: str,
        action: str,
        target: str,
        success: bool = True,
        role: Optional[str] = None,
        detail: Optional[str] = None
    ):
        """
        Log a privileged mcp_users mutation.

        The user table is the authorization source of truth for OAuth sign-in
        and is shared with PFW and PTAB, so a grant made here is a grant on
        three servers. Every add / set_role / activate / deactivate needs a
        record naming who made it. Emails are masked by the sink filter.

        Args:
            actor: Authenticated identity performing the action
            action: One of add, set_role, activate, deactivate
            target: Email of the affected user
            success: Whether the mutation was applied
            role: Role granted, for add / set_role
            detail: Optional failure reason
        """
        self.logger.log_security_event(
            event_description=f"User management action: {action} on {target}",
            request_details={
                "event_type": SecurityEventType.ADMIN_ACTION.value,
                "actor": actor,
                "action": action,
                "target": target,
                "role": role,
                "success": success,
                "detail": detail
            },
            severity="high"
        )


# Global security logger instance
security_logger = SecurityLogger()
