"""
Log retention and disposal policy implementation.

Fixes:
- CWE-404: Improper Resource Shutdown or Release
- GDPR Article 17 (right to erasure) compliance
- SOC 2, PCI-DSS log retention requirements

Retention Periods:
- Security logs: 90 days (compliance requirement)
- Application logs: 30 days (operational needs)
- Error logs: 60 days (debugging window)
- Audit logs: 365 days (legal/compliance)
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any


class LogRetentionPolicy:
    """
    Implements log retention and automated cleanup.

    Retention Periods:
    - Security logs: 90 days (compliance requirement)
    - Application logs: 30 days (operational needs)
    - Error logs: 60 days (debugging window)
    - Audit logs: 365 days (legal/compliance)
    """

    RETENTION_PERIODS = {
        "fpd-mcp-security.log": 90,  # days
        "fpd-mcp.log": 30,
        "fpd-mcp-errors.log": 60,
        "fpd-mcp-audit.log": 365
    }

    def __init__(self, log_dir: Path):
        """
        Initialize retention policy manager.

        Args:
            log_dir: Directory containing log files
        """
        self.log_dir = log_dir
        self.logger = logging.getLogger(__name__)

    def cleanup_old_logs(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Remove log files older than retention period.

        Args:
            dry_run: If True, only report what would be deleted

        Returns:
            Dictionary with cleanup statistics
        """
        now = datetime.now()
        total_deleted = 0
        total_size_freed = 0

        for log_file_pattern, retention_days in self.RETENTION_PERIODS.items():
            cutoff_date = now - timedelta(days=retention_days)

            # Find all rotated versions (e.g., fpd-mcp.log.1, fpd-mcp.log.2.gz)
            for log_file in self.log_dir.glob(f"{log_file_pattern}*"):
                if not log_file.is_file():
                    continue

                # Skip the current active log file (without rotation suffix)
                if log_file.name == log_file_pattern:
                    continue

                # Check file modification time
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)

                if mtime < cutoff_date:
                    size = log_file.stat().st_size

                    if dry_run:
                        self.logger.info(
                            f"Would delete: {log_file} (age: {(now - mtime).days} days, "
                            f"size: {size / (1024*1024):.2f}MB)"
                        )
                    else:
                        self.logger.info(
                            f"Deleting old log: {log_file} (age: {(now - mtime).days} days)"
                        )
                        try:
                            log_file.unlink()
                        except Exception as e:
                            self.logger.error(f"Failed to delete {log_file}: {e}")
                            continue

                    total_deleted += 1
                    total_size_freed += size

        self.logger.info(
            f"Log cleanup complete: {total_deleted} files, "
            f"{total_size_freed / (1024*1024):.2f}MB freed"
        )

        return {
            "files_deleted": total_deleted,
            "bytes_freed": total_size_freed,
            "mb_freed": total_size_freed / (1024*1024),
            "dry_run": dry_run
        }

    def get_retention_status(self) -> Dict[str, Any]:
        """
        Get current status of log retention.

        Returns:
            Dictionary with retention statistics
        """
        now = datetime.now()
        status = {}

        for log_file_pattern, retention_days in self.RETENTION_PERIODS.items():
            cutoff_date = now - timedelta(days=retention_days)

            files_to_delete = []
            files_to_keep = []
            size_to_delete = 0
            size_to_keep = 0

            for log_file in self.log_dir.glob(f"{log_file_pattern}*"):
                if not log_file.is_file():
                    continue

                # Skip active log file
                if log_file.name == log_file_pattern:
                    files_to_keep.append(log_file.name)
                    size_to_keep += log_file.stat().st_size
                    continue

                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                size = log_file.stat().st_size

                if mtime < cutoff_date:
                    files_to_delete.append({
                        "file": log_file.name,
                        "age_days": (now - mtime).days,
                        "size_mb": size / (1024*1024)
                    })
                    size_to_delete += size
                else:
                    files_to_keep.append(log_file.name)
                    size_to_keep += size

            status[log_file_pattern] = {
                "retention_days": retention_days,
                "files_to_delete": len(files_to_delete),
                "files_to_keep": len(files_to_keep),
                "size_to_delete_mb": size_to_delete / (1024*1024),
                "size_to_keep_mb": size_to_keep / (1024*1024),
                "details": files_to_delete
            }

        return status

    def verify_compliance(self) -> Dict[str, bool]:
        """
        Verify retention policy compliance.

        Returns:
            Dictionary with compliance status for each log type
        """
        now = datetime.now()
        compliance = {}

        for log_file_pattern, retention_days in self.RETENTION_PERIODS.items():
            cutoff_date = now - timedelta(days=retention_days)

            # Check if any files older than retention period exist
            has_old_files = False
            for log_file in self.log_dir.glob(f"{log_file_pattern}*"):
                if not log_file.is_file():
                    continue

                # Skip active log file
                if log_file.name == log_file_pattern:
                    continue

                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff_date:
                    has_old_files = True
                    break

            # Compliance is True if no old files exist
            compliance[log_file_pattern] = not has_old_files

        return compliance


def schedule_cleanup(log_dir: Path, dry_run: bool = False):
    """
    Schedule log cleanup based on retention policy.

    This function should be called periodically (e.g., daily via cron).

    Args:
        log_dir: Directory containing log files
        dry_run: If True, only report what would be deleted

    Returns:
        Cleanup statistics
    """
    policy = LogRetentionPolicy(log_dir)
    logger = logging.getLogger(__name__)

    logger.info("Starting scheduled log cleanup")

    # Get retention status before cleanup
    status_before = policy.get_retention_status()
    logger.info(f"Retention status before cleanup: {status_before}")

    # Perform cleanup
    results = policy.cleanup_old_logs(dry_run=dry_run)

    # Verify compliance after cleanup
    compliance = policy.verify_compliance()
    logger.info(f"Retention compliance after cleanup: {compliance}")

    return {
        "cleanup_results": results,
        "compliance_status": compliance,
        "status_before": status_before
    }
