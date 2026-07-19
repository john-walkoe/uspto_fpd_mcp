"""
Database utilities with security enhancements for SQLite connections.

Provides secure connection management with proper timeouts and security PRAGMAs.
Copied from the PTAB/PFW reference implementation.
"""
import os
import sqlite3

from ..shared.unified_logging import get_logger

logger = get_logger(__name__)


def create_secure_connection(db_path: str, timeout: float = 30.0) -> sqlite3.Connection:
    """
    Create a secure SQLite connection with timeouts and security PRAGMAs.

    Args:
        db_path: Path to SQLite database file
        timeout: Connection timeout in seconds (default: 30.0)

    Returns:
        Configured SQLite connection

    Raises:
        sqlite3.OperationalError: If connection fails
    """
    try:
        conn = sqlite3.connect(
            db_path,
            timeout=timeout,
            check_same_thread=False
        )

        # NOTE: WAL mode is used for concurrency but is NOT safe on network
        # filesystems (NFS, CIFS/SMB). Set USPTO_DB_JOURNAL_MODE=DELETE there.
        conn.execute("PRAGMA busy_timeout = 30000")
        journal_mode = os.environ.get("USPTO_DB_JOURNAL_MODE", "WAL").upper()
        if journal_mode not in ("WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY"):
            logger.warning(f"Invalid USPTO_DB_JOURNAL_MODE '{journal_mode}', using WAL")
            journal_mode = "WAL"
        conn.execute(f"PRAGMA journal_mode = {journal_mode}")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA temp_store = MEMORY")

        conn.execute("SELECT 1").fetchone()

        logger.debug(f"Secure SQLite connection established: {db_path}")
        return conn

    except sqlite3.OperationalError as e:
        logger.error(f"Failed to create secure SQLite connection to {db_path}: {e}")
        raise
