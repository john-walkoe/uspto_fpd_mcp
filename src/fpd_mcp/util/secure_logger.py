"""
Secure logger wrapper that enforces sanitization.

DEPRECATED: This module is deprecated in favor of shared.unified_logging.
Use get_logger() from fpd_mcp.shared.unified_logging instead.

Migration:
    # Old code:
    from fpd_mcp.util.secure_logger import get_secure_logger
    logger = get_secure_logger(__name__)

    # New code:
    from fpd_mcp.shared.unified_logging import get_logger
    logger = get_logger(__name__)

The new unified logging provides:
- All functionality of SecureLogger
- Additional structured logging (JSON)
- Security event logging
- Performance timing
- Automatic sanitization

This module will be removed in a future version.

Fixes:
- CWE-117: Improper Output Neutralization for Logs (log injection)
- CWE-532: Insertion of Sensitive Information into Log File
- CWE-209: Information Exposure Through an Error Message

All logging automatically sanitized to prevent:
- Log injection attacks
- Sensitive data leakage (API keys, tokens, PII)
- Control character injection
- Exception information exposure
"""
import logging
import warnings
from typing import Any
from ..shared.log_sanitizer import LogSanitizer


class SecureLogger:
    """
    Logger wrapper that automatically sanitizes all log output.

    Usage:
        from fpd_mcp.util.secure_logger import get_secure_logger

        logger = get_secure_logger(__name__)
        logger.info("Safe message", extra={"user_input": untrusted_data})
    """

    def __init__(self, logger_instance: logging.Logger):
        self.logger = logger_instance
        self.sanitizer = LogSanitizer()

    def _sanitize_message(self, msg: str, *args) -> tuple:
        """Sanitize message and arguments"""
        if args:
            # Sanitize format arguments
            safe_args = [
                self.sanitizer.sanitize_string(str(arg)) if isinstance(arg, str) else arg
                for arg in args
            ]
            safe_msg = self.sanitizer.sanitize_string(str(msg))
            return safe_msg, safe_args
        else:
            return self.sanitizer.sanitize_string(str(msg)), ()

    def _sanitize_kwargs(self, kwargs: dict) -> dict:
        """Sanitize keyword arguments"""
        safe_kwargs = kwargs.copy()

        if 'extra' in safe_kwargs:
            safe_kwargs['extra'] = self.sanitizer.sanitize_for_json(safe_kwargs['extra'])

        if 'exc_info' in safe_kwargs and safe_kwargs['exc_info']:
            # Sanitize exception info
            exc_info = safe_kwargs['exc_info']
            if isinstance(exc_info, BaseException):
                # Create sanitized exception message
                sanitized_msg = self.sanitizer.sanitize_string(str(exc_info))
                safe_kwargs['exc_info'] = type(exc_info)(sanitized_msg)

        return safe_kwargs

    def debug(self, msg, *args, **kwargs):
        """Log debug message with sanitization"""
        safe_msg, safe_args = self._sanitize_message(msg, *args)
        safe_kwargs = self._sanitize_kwargs(kwargs)
        self.logger.debug(safe_msg, *safe_args, **safe_kwargs)

    def info(self, msg, *args, **kwargs):
        """Log info message with sanitization"""
        safe_msg, safe_args = self._sanitize_message(msg, *args)
        safe_kwargs = self._sanitize_kwargs(kwargs)
        self.logger.info(safe_msg, *safe_args, **safe_kwargs)

    def warning(self, msg, *args, **kwargs):
        """Log warning message with sanitization"""
        safe_msg, safe_args = self._sanitize_message(msg, *args)
        safe_kwargs = self._sanitize_kwargs(kwargs)
        self.logger.warning(safe_msg, *safe_args, **safe_kwargs)

    def error(self, msg, *args, **kwargs):
        """Log error message with sanitization"""
        safe_msg, safe_args = self._sanitize_message(msg, *args)
        safe_kwargs = self._sanitize_kwargs(kwargs)
        self.logger.error(safe_msg, *safe_args, **safe_kwargs)

    def critical(self, msg, *args, **kwargs):
        """Log critical message with sanitization"""
        safe_msg, safe_args = self._sanitize_message(msg, *args)
        safe_kwargs = self._sanitize_kwargs(kwargs)
        self.logger.critical(safe_msg, *safe_args, **safe_kwargs)

    def exception(self, msg, *args, **kwargs):
        """Log exception with automatic sanitization"""
        safe_msg, safe_args = self._sanitize_message(msg, *args)
        safe_kwargs = self._sanitize_kwargs(kwargs)
        safe_kwargs.setdefault('exc_info', True)
        self.logger.error(safe_msg, *safe_args, **safe_kwargs)


def get_secure_logger(name: str) -> SecureLogger:
    """
    Get a secure logger that automatically sanitizes all output.

    DEPRECATED: Use get_logger() from fpd_mcp.shared.unified_logging instead.

    Args:
        name: Logger name (typically __name__)

    Returns:
        SecureLogger instance

    Example Migration:
        # Old code:
        from fpd_mcp.util.secure_logger import get_secure_logger
        logger = get_secure_logger(__name__)

        # New code:
        from fpd_mcp.shared.unified_logging import get_logger
        logger = get_logger(__name__)
    """
    warnings.warn(
        "get_secure_logger is deprecated. "
        "Use get_logger() from fpd_mcp.shared.unified_logging instead. "
        "This function will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )
    return SecureLogger(logging.getLogger(name))
