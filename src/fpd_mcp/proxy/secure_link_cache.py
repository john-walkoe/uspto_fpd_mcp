"""
Secure SQLite persistent link cache for FPD petition document downloads.

Provides encrypted persistent download links that remain valid for a
configurable duration (default 7 days) while keeping all sensitive data
encrypted. The opaque link hash in the URL is the sole credential —
browser navigation needs no headers (Lesson 43).

Adapted from the PTAB/PFW reference implementation with FPD differences:
- Payload carries petition_id/document_identifier (PFW: app_number/doc_id)
  plus the resolved USPTO download URL and enhanced filename, so persistent
  downloads can stream directly without re-fetching petition metadata.
- Own database file and encryption key, never shared with PTAB/PFW caches.
- DPAPI entropy is real bytes (the PTAB/PFW copies passed an int constant,
  which made the DPAPI path fail silently and fall back to the file key).

TODO(architectural): the Fernet key falls back to a plain file on Linux.
DPAPI is Windows-only; any user with filesystem read access can recover
the key there. Same accepted limitation as PTAB/PFW.
"""

import hashlib
import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from cryptography.fernet import Fernet

from ..util.database import create_secure_connection
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)

_KEY_FILE_NAME = ".fpd_proxy_encryption_key"
_DB_FILE_NAME = "fpd_proxy_link_cache.db"

# Deterministic DPAPI entropy — must be identical across runs to decrypt.
# DPAPI itself binds the encryption to this user + machine; the entropy is
# defense-in-depth against other DPAPI-capable processes.
_DPAPI_ENTROPY = hashlib.sha256(b"fpd_mcp.proxy.secure_link_cache.v1").digest()

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def _default_data_dir() -> Path:
    """Writable home for the link-cache db and encryption key.

    Priority: FPD_LINK_CACHE_DIR env override → alongside the OAuth user DB
    (FPD_AUTH_DB_PATH's directory — the mounted, uid-aligned data dir in the
    Docker deployments) → project root (bare stdio installs). Each candidate
    is write-probed; the last resort is the system temp dir, so an
    unwritable install degrades to session-lived links instead of a 500 on
    every download (h3 staging 2026-08-16: /app is root-owned under the
    uid-1000 runtime and SecureLinkCache() died on the sqlite connect,
    failing FPD_get_document_download outright).
    """
    candidates: list[Path] = []
    env_dir = os.getenv("FPD_LINK_CACHE_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    auth_db = os.getenv("FPD_AUTH_DB_PATH")
    if auth_db:
        candidates.append(Path(auth_db).parent)
    candidates.append(_PROJECT_ROOT)
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".fpd_link_cache_write_probe"
            probe.touch()
            probe.unlink()
            return cand
        except OSError:
            continue
    import tempfile
    return Path(tempfile.gettempdir())


class LinkCacheUnavailable(Exception):
    """The persistent-link store could not be read.

    F-X1: distinct from "no such link". Both used to surface as None, so a
    corrupt or unreadable database was reported to the user as an expired
    link, and the remedy that message suggests (generate a new link) produces
    another link that also fails.
    """


class SecureLinkCache:
    """
    Secure persistent link cache with encryption.

    Features:
    - Encrypted storage of petition identifiers, document IDs and download URLs
    - Opaque URLs that don't reveal business data
    - Configurable link expiration (default 7 days)
    - Automatic cleanup of expired links
    - Windows DPAPI protection for the encryption key, file fallback elsewhere
    """

    def __init__(self, cache_duration_days: int = 7, db_path: Optional[str] = None):
        self.cache_duration = timedelta(days=cache_duration_days)

        if db_path:
            self.db_path = db_path
        else:
            self.db_path = str(_default_data_dir() / _DB_FILE_NAME)

        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)
        self._init_database()

    def _get_or_create_encryption_key(self) -> bytes:
        """
        Get the Fernet key from DPAPI-protected storage or create a new one.

        On Windows the key file content is DPAPI-encrypted (per-user,
        per-machine). On non-Windows the raw key is stored with restrictive
        file permissions (0o600).
        """
        # Prefer a legacy project-root key when one already exists (pre-2026-08
        # installs stored it there; moving away from it would orphan every
        # previously issued persistent link), else live beside the db.
        legacy_key = _PROJECT_ROOT / _KEY_FILE_NAME
        if legacy_key.exists():
            key_file = legacy_key
        else:
            key_file = _default_data_dir() / _KEY_FILE_NAME

        try:
            from ..shared.dpapi_crypto import (
                encrypt_with_dpapi,
                decrypt_with_dpapi,
                is_dpapi_available,
            )

            if is_dpapi_available():
                if key_file.exists():
                    encrypted = key_file.read_bytes()
                    return decrypt_with_dpapi(encrypted, _DPAPI_ENTROPY)

                key = Fernet.generate_key()
                encrypted = encrypt_with_dpapi(
                    key, _DPAPI_ENTROPY, description="FPD Proxy Link Encryption Key"
                )
                key_file.write_bytes(encrypted)
                logger.info("Generated new DPAPI-protected proxy encryption key")
                return key
        except Exception as e:
            logger.warning(f"DPAPI key storage unavailable ({type(e).__name__}), using file-based key")

        return self._get_file_based_key(key_file)

    def _get_file_based_key(self, key_file: Path) -> bytes:
        """Fallback plain-file key storage for non-Windows systems."""
        if key_file.exists():
            try:
                return key_file.read_bytes()
            except Exception as e:
                logger.warning(f"Error reading encryption key file: {e}, generating new key")

        # SECURITY NOTE: on Linux/macOS the Fernet key is protected only by
        # filesystem permissions (0o600) — same accepted limitation as PFW.
        key = Fernet.generate_key()
        try:
            key_file.write_bytes(key)
            os.chmod(key_file, 0o600)
            logger.info("Generated new file-based proxy encryption key")
        except Exception as e:
            logger.warning(f"Could not save encryption key to file: {e}")

        return key

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        """Open a connection and guarantee it closes (L10: previously every
        call site opened a connection with no try/finally, leaking the
        handle on any exception path)."""
        conn = create_secure_connection(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self):
        """Initialize SQLite database with encrypted storage design."""
        try:
            with self._connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS download_links (
                        link_hash TEXT PRIMARY KEY,           -- Irreversible hash for lookup
                        encrypted_token TEXT,                 -- Fernet-encrypted data
                        created_at TIMESTAMP,                 -- When link was created
                        last_accessed TIMESTAMP,              -- Last access time
                        access_count INTEGER DEFAULT 0,       -- Number of times accessed
                        expires_at TIMESTAMP                  -- When link expires
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON download_links(expires_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON download_links(created_at)")
                conn.commit()
            logger.info(f"Initialized secure link cache database: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize link cache database: {e}")
            raise

    def generate_persistent_link(
        self,
        petition_id: str,
        document_identifier: str,
        file_download_uri: str,
        enhanced_filename: str,
        base_url: str = "http://localhost:8081",
    ) -> str:
        """
        Generate a secure persistent link with encrypted storage.

        Args:
            petition_id: Petition decision record identifier (UUID)
            document_identifier: Document ID from documentBag
            file_download_uri: Resolved USPTO download URL to stream from
            enhanced_filename: Human-readable download filename
            base_url: Externally reachable base URL of the FPD proxy

        Returns:
            Opaque persistent download URL
        """
        try:
            token_data = json.dumps({
                'petition_id': petition_id,
                'document_identifier': document_identifier,
                'file_download_uri': file_download_uri,
                'enhanced_filename': enhanced_filename,
                'timestamp': datetime.now().isoformat(),
                # Random component prevents pattern analysis of equal payloads
                'random': secrets.token_hex(16),
            })

            encrypted_token = self.cipher.encrypt(token_data.encode('utf-8')).decode('utf-8')

            # Irreversible hash for database lookup — 24 hex chars (~96 bits)
            link_hash = hashlib.sha256(encrypted_token.encode('utf-8')).hexdigest()[:24]

            expires_at = datetime.now() + self.cache_duration

            with self._connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO download_links
                    (link_hash, encrypted_token, created_at, last_accessed, access_count, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (link_hash, encrypted_token, datetime.now(), datetime.now(), 0, expires_at))
                conn.commit()

            persistent_url = f"{base_url.rstrip('/')}/download/persistent/{link_hash}"
            # Truncated hash only — the full hash is the credential (Lesson 43)
            logger.info(
                f"Generated persistent link {link_hash[:8]}... for petition "
                f"{petition_id}, expires {expires_at}"
            )
            return persistent_url

        except Exception as e:
            logger.error(f"Failed to generate persistent link: {e}")
            raise

    def resolve_persistent_link(self, link_hash: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a persistent link by decrypting the stored token.

        Returns:
            Dict with petition_id, document_identifier, file_download_uri,
            enhanced_filename and access metadata, or None if invalid/expired.

        Raises:
            LinkCacheUnavailable: the cache itself could not be read. None
                means "no such link, or expired"; the two are different
                answers and used to be indistinguishable (F-X1).
        """
        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT encrypted_token, created_at, access_count, expires_at
                    FROM download_links
                    WHERE link_hash = ? AND expires_at > ?
                """, (link_hash, datetime.now()))
                result = cursor.fetchone()

            if not result:
                logger.warning(f"Persistent link {link_hash[:8]}... not found or expired")
                return None

            encrypted_token, created_at, access_count, expires_at = result

            try:
                decrypted = self.cipher.decrypt(encrypted_token.encode('utf-8')).decode('utf-8')
                token_data = json.loads(decrypted)

                self._update_access(link_hash)

                return {
                    'petition_id': token_data['petition_id'],
                    'document_identifier': token_data['document_identifier'],
                    'file_download_uri': token_data.get('file_download_uri'),
                    'enhanced_filename': token_data.get('enhanced_filename'),
                    'created_at': created_at,
                    'access_count': access_count + 1,
                    'expires_at': expires_at,
                }
            except Exception as decrypt_error:
                logger.error(f"Failed to decrypt token for link {link_hash[:8]}...: {type(decrypt_error).__name__}")
                self._remove_link(link_hash)
                return None

        except Exception as e:
            # F-X1: this used to return None like a genuine miss, so the route
            # told the user "your link expired, generate a new one" — an
            # operational fault presented as a user error, with the suggested
            # remedy producing another link that also failed. The route
            # answers 503 for this now.
            logger.error(
                f"Link cache unavailable while resolving {link_hash[:8]}...: "
                f"{type(e).__name__}"
            )
            raise LinkCacheUnavailable(str(e)) from e

    def _update_access(self, link_hash: str):
        """Update access tracking for a link."""
        try:
            with self._connection() as conn:
                conn.execute("""
                    UPDATE download_links
                    SET last_accessed = ?, access_count = access_count + 1
                    WHERE link_hash = ?
                """, (datetime.now(), link_hash))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update access tracking for {link_hash[:8]}...: {e}")

    def _remove_link(self, link_hash: str):
        """Remove a corrupted or invalid link."""
        try:
            with self._connection() as conn:
                conn.execute("DELETE FROM download_links WHERE link_hash = ?", (link_hash,))
                conn.commit()
            logger.info(f"Removed corrupted link {link_hash[:8]}...")
        except Exception as e:
            logger.warning(f"Failed to remove link {link_hash[:8]}...: {e}")

    def cleanup_expired_links(self) -> int:
        """Delete expired links. Returns the number removed."""
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM download_links WHERE expires_at < ?", (datetime.now(),)
                )
                deleted_count = cursor.rowcount
                conn.commit()
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired persistent links")
            return deleted_count
        except Exception as e:
            logger.error(f"Error during link cleanup: {e}")
            return 0


# Global cache instance
_link_cache = None


def get_link_cache() -> SecureLinkCache:
    """Get the global secure link cache instance."""
    global _link_cache
    if _link_cache is None:
        _link_cache = SecureLinkCache()
    return _link_cache
