"""
Logging configuration for FPD MCP with file-based audit trail.

Security Features:
- RotatingFileHandler with 10MB max size, 5 backups
- Separate security log file (10 backups for longer retention)
- File permissions set to 600 (owner read/write only)
- Persistent audit trail for forensic analysis
"""
import logging
import logging.handlers
import sys
import os
from pathlib import Path

from ..shared.log_sanitizer import SanitizingFilter


class _ModeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that re-applies 0600 on every rollover.

    M-22: the chmod below runs once, at startup, against the file that exists
    then. On rollover the handler creates a fresh base file with the process
    umask (0644 in the container), so the audit trail lost its permissions the
    first time it filled up — silently, and permanently thereafter.
    """

    def _open(self):
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, 0o600)
        except OSError:
            pass
        return stream


def setup_logging(log_level: str = "INFO"):
    """
    Configure logging for FPD MCP with file-based audit trail.

    Creates two log files in ~/.uspto_fpd_mcp/logs/:
    - fpd_mcp.log: General application logs (10MB max, 5 backups)
    - security.log: Security events only (10MB max, 10 backups for compliance)

    File permissions are set to 600 (owner read/write only) for security.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Create logs directory with secure permissions.
    # LOG_DIR env var overrides the default (useful for Docker volume mounts).
    _log_dir_env = os.environ.get("LOG_DIR", "").strip()
    logs_dir = Path(_log_dir_env) if _log_dir_env else Path.home() / ".uspto_fpd_mcp" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Set directory permissions to 700 (owner only)
    if hasattr(os, 'chmod'):
        try:
            os.chmod(logs_dir, 0o700)
        except (OSError, PermissionError) as e:
            print(f"Warning: Could not set directory permissions: {e}", file=sys.stderr)

    # Retention is env-configurable (defaults: 10MB, 5 backups)
    max_bytes = int(os.getenv("FPD_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    backup_count = int(os.getenv("FPD_LOG_BACKUP_COUNT", "5"))

    # Application log file with rotation
    app_log_file = logs_dir / "fpd_mcp.log"
    file_handler = _ModeRotatingFileHandler(
        app_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    # Security log file with rotation (10MB max, 10 backups for compliance)
    security_log_file = logs_dir / "security.log"
    security_handler = _ModeRotatingFileHandler(
        security_log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,  # Keep more security logs for compliance
        encoding='utf-8'
    )
    security_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    # Console handler for stderr
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    # Sink-level sanitization guarantee: every record is scrubbed at the
    # handler regardless of which logger emitted it (library loggers included)
    sanitizing_filter = SanitizingFilter()
    for _sink in (file_handler, console_handler, security_handler):
        _sink.addFilter(sanitizing_filter)

    # Configure root logger explicitly — basicConfig is a NO-OP whenever the
    # root already has handlers, which silently skipped the file logging and
    # sanitization setup in embedded/test contexts.
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    for _existing in root_logger.handlers[:]:
        root_logger.removeHandler(_existing)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Configure security logger (separate file, WARNING and above).
    # The name must match the producer in shared/security_logger.py, which
    # emits on 'fpd_mcp.security'. 'security' is a sibling of that logger in
    # the hierarchy, not an ancestor, so binding this handler to 'security'
    # meant security.log was created, chmod'd and never written to.
    security_logger = logging.getLogger('fpd_mcp.security')
    security_logger.addHandler(security_handler)
    security_logger.setLevel(logging.WARNING)
    security_logger.propagate = False  # Don't duplicate to other handlers

    # Set file permissions to 600 (owner read/write only) - CRITICAL SECURITY
    if hasattr(os, 'chmod'):
        for log_file in [app_log_file, security_log_file]:
            try:
                log_file.touch(exist_ok=True)
                os.chmod(log_file, 0o600)
            except (OSError, PermissionError) as e:
                print(f"Warning: Could not set file permissions on {log_file}: {e}", file=sys.stderr)

    # Log initialization success
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Application log: {app_log_file}")
    logger.info(f"Security log: {security_log_file}")

    # Suppress noisy libraries (Safe: Only configuring log levels, not logging data)
    # uvicorn.access included: access lines contain request paths, and
    # /download/persistent/{hash} paths embed the link credential
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # FastMCP 4 dropped httpx for its vendored fork, which logs under the
    # httpx2/httpcore2 names — the httpx caps above no longer reach it, and an
    # INFO-level httpx2 request line carries the full URL.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("httpcore2").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
