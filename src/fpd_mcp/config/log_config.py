"""
Comprehensive logging configuration with rotation, retention, and security.

Implements:
- Rotating file handlers with size limits
- Separate logs for app, security, errors
- Secure file permissions (600)
- JSON structured logging format
- Configurable retention policies

Fixes:
- CWE-779: Logging of Excessive Data (no rotation)
- Log rotation prevents disk space exhaustion
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional


class SecureLogManager:
    """
    Manages log rotation, retention, and security for FPD MCP.

    Features:
    - Rotating file handlers with size limits
    - Separate logs for app, security, errors
    - Secure file permissions (600)
    - JSON structured logging format
    - Configurable retention policies
    """

    def __init__(
        self,
        log_dir: Optional[str] = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB default
        backup_count: int = 30,  # Keep 30 rotated files
        log_level: str = "INFO"
    ):
        """
        Initialize secure log manager.

        Args:
            log_dir: Directory for log files (default: ./logs or /var/log/fpd-mcp)
            max_bytes: Maximum size per log file before rotation
            backup_count: Number of rotated files to keep
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        # Determine log directory
        if log_dir:
            self.log_dir = Path(log_dir)
        elif os.environ.get("FPD_LOG_DIR"):
            self.log_dir = Path(os.environ["FPD_LOG_DIR"])
        elif os.access("/var/log", os.W_OK):
            self.log_dir = Path("/var/log/fpd-mcp")
        else:
            self.log_dir = Path.cwd() / "logs"

        # Create log directory with secure permissions
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(os, 'chmod'):
            os.chmod(self.log_dir, 0o750)  # Owner and group only

        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.log_level = getattr(logging, log_level.upper())

        # Setup handlers
        self._setup_handlers()

    def _setup_handlers(self):
        """Setup rotating file handlers with security"""

        # 1. Main application log (INFO and above)
        self.main_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / "fpd-mcp.log",
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        self.main_handler.setLevel(logging.INFO)

        # Secure permissions on log file
        log_file = self.log_dir / "fpd-mcp.log"
        if log_file.exists() and hasattr(os, 'chmod'):
            os.chmod(log_file, 0o600)

        # JSON formatter for structured logging
        self.main_formatter = logging.Formatter(
            '%(message)s'  # StructuredLogger already formats as JSON
        )
        self.main_handler.setFormatter(self.main_formatter)

        # 2. Security events log (WARNING and above, longer retention)
        self.security_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / "fpd-mcp-security.log",
            maxBytes=self.max_bytes,
            backupCount=90,  # 90 rotations for security (longer retention)
            encoding='utf-8'
        )
        self.security_handler.setLevel(logging.WARNING)
        self.security_handler.setFormatter(self.main_formatter)

        # Secure permissions
        security_log = self.log_dir / "fpd-mcp-security.log"
        if security_log.exists() and hasattr(os, 'chmod'):
            os.chmod(security_log, 0o600)

        # 3. Error log (ERROR and CRITICAL only)
        self.error_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / "fpd-mcp-errors.log",
            maxBytes=5 * 1024 * 1024,  # 5MB for errors
            backupCount=60,
            encoding='utf-8'
        )
        self.error_handler.setLevel(logging.ERROR)
        self.error_handler.setFormatter(self.main_formatter)

        # Secure permissions
        error_log = self.log_dir / "fpd-mcp-errors.log"
        if error_log.exists() and hasattr(os, 'chmod'):
            os.chmod(error_log, 0o600)

        # 4. Console handler for development/debugging
        self.console_handler = logging.StreamHandler(sys.stderr)
        self.console_handler.setLevel(self.log_level)

        # Human-readable formatter for console
        self.console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.console_handler.setFormatter(self.console_formatter)

    def configure_root_logger(self):
        """Configure root logger with all handlers"""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # Capture all, filter at handler level

        # Remove existing handlers
        root_logger.handlers.clear()

        # Add our handlers
        root_logger.addHandler(self.main_handler)
        root_logger.addHandler(self.security_handler)
        root_logger.addHandler(self.error_handler)
        root_logger.addHandler(self.console_handler)

    def configure_security_logger(self):
        """Configure dedicated security logger"""
        security_logger = logging.getLogger("fpd_mcp.security")
        security_logger.setLevel(logging.WARNING)
        security_logger.addHandler(self.security_handler)
        security_logger.propagate = False  # Don't propagate to root
        return security_logger

    def get_stats(self) -> dict:
        """Get logging statistics"""
        return {
            "log_dir": str(self.log_dir),
            "log_dir_size_mb": sum(
                f.stat().st_size for f in self.log_dir.glob("**/*") if f.is_file()
            ) / (1024 * 1024),
            "main_log_size_mb": (self.log_dir / "fpd-mcp.log").stat().st_size / (1024 * 1024)
                if (self.log_dir / "fpd-mcp.log").exists() else 0,
            "max_bytes_per_file_mb": self.max_bytes / (1024 * 1024),
            "backup_count": self.backup_count,
            "total_retention_mb": (self.max_bytes * self.backup_count) / (1024 * 1024)
        }


def setup_logging():
    """Setup comprehensive logging with rotation"""
    log_manager = SecureLogManager(
        max_bytes=10 * 1024 * 1024,  # 10MB per file
        backup_count=30,  # 30 rotations = ~300MB total for main log
        log_level=os.environ.get("LOG_LEVEL", "INFO")
    )

    log_manager.configure_root_logger()
    security_logger = log_manager.configure_security_logger()

    # Log startup
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured: {log_manager.get_stats()}")

    return log_manager
