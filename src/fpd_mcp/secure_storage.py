"""
Windows DPAPI Secure Storage for USPTO API Keys

MIGRATION NOTE: This module is being phased out in favor of shared_secure_storage.py.

Recommended Migration Path:
1. Use shared_secure_storage.UnifiedSecureStorage for all new code
2. Run storage migration utility to convert existing keys:
   from fpd_mcp.shared.storage_migration import migrate_legacy_storage
   migrate_legacy_storage()

Benefits of Unified Storage:
- Single-key-per-file architecture (more secure isolation)
- Uses centralized dpapi_crypto module (no code duplication)
- Uses centralized storage_paths module
- Consistent with other USPTO MCPs (PFW, PTAB, Citations)

This module will be maintained for backward compatibility but may be
deprecated in a future version.

---

This module provides secure storage and retrieval of USPTO API keys using Windows Data Protection API (DPAPI).
DPAPI encrypts data per-user and per-machine, so only the same user on the same machine can decrypt it.

No PowerShell execution policies or external dependencies required - uses only Python ctypes.
"""

import ctypes
import ctypes.wintypes
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Optional, Dict


class DATA_BLOB(ctypes.Structure):
    """Windows DATA_BLOB structure for DPAPI operations."""
    _fields_ = [
        ('cbData', ctypes.wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char))
    ]


def _get_data_from_blob(blob: DATA_BLOB) -> bytes:
    """Extract bytes from a DATA_BLOB structure."""
    if not blob.cbData:
        return b''

    cbData = int(blob.cbData)
    pbData = blob.pbData
    buffer = ctypes.create_string_buffer(cbData)
    ctypes.memmove(buffer, pbData, cbData)
    ctypes.windll.kernel32.LocalFree(pbData)
    return buffer.raw


def encrypt_data(data: bytes, description: str = "USPTO FPD API Key") -> bytes:
    """
    Encrypt data using Windows DPAPI with secure random entropy.

    Args:
        data: The data to encrypt (API key as bytes)
        description: Optional description for the encrypted data

    Returns:
        Encrypted data as bytes (entropy + encrypted_data)

    Raises:
        OSError: If encryption fails
        RuntimeError: If not running on Windows
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    # Generate cryptographically secure random entropy (32 bytes = 256 bits)
    entropy_data = secrets.token_bytes(32)

    # Prepare input data blob
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char))
    data_in.cbData = len(data)

    # Prepare output data blob
    data_out = DATA_BLOB()

    # Prepare entropy blob
    entropy = DATA_BLOB()
    entropy.pbData = ctypes.cast(ctypes.create_string_buffer(entropy_data), ctypes.POINTER(ctypes.c_char))
    entropy.cbData = len(entropy_data)

    # Call CryptProtectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in),          # pDataIn
        description,                     # szDataDescr
        ctypes.byref(entropy),          # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptProtectData failed with error code: {error_code}")

    # Extract encrypted data
    encrypted_data = _get_data_from_blob(data_out)

    # Return entropy + encrypted data (entropy needed for decryption)
    return entropy_data + encrypted_data


def decrypt_data(encrypted_data: bytes) -> bytes:
    """
    Decrypt data using Windows DPAPI.

    Args:
        encrypted_data: The encrypted data (entropy + encrypted_data)

    Returns:
        Decrypted data as bytes

    Raises:
        OSError: If decryption fails
        RuntimeError: If not running on Windows
        ValueError: If encrypted data format is invalid
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    # Validate minimum data length (32 bytes entropy + some encrypted data)
    if len(encrypted_data) < 32:
        raise ValueError("Invalid encrypted data format: too short")

    # Extract entropy (first 32 bytes) and actual encrypted data
    entropy_data = encrypted_data[:32]
    actual_encrypted_data = encrypted_data[32:]

    # Prepare input data blob with actual encrypted data
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(ctypes.create_string_buffer(actual_encrypted_data), ctypes.POINTER(ctypes.c_char))
    data_in.cbData = len(actual_encrypted_data)

    # Prepare output data blob
    data_out = DATA_BLOB()

    # Prepare entropy blob with extracted entropy
    entropy = DATA_BLOB()
    entropy.pbData = ctypes.cast(ctypes.create_string_buffer(entropy_data), ctypes.POINTER(ctypes.c_char))
    entropy.cbData = len(entropy_data)

    # Prepare description pointer
    description_ptr = ctypes.wintypes.LPWSTR()

    # Call CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in),          # pDataIn
        ctypes.byref(description_ptr),  # ppszDataDescr
        ctypes.byref(entropy),          # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptUnprotectData failed with error code: {error_code}")

    # Clean up description
    if description_ptr.value:
        ctypes.windll.kernel32.LocalFree(description_ptr)

    # Extract decrypted data
    decrypted_data = _get_data_from_blob(data_out)
    return decrypted_data


class SecureStorage:
    """Secure storage manager for USPTO API keys using Windows DPAPI."""

    def __init__(self, storage_file: Optional[str] = None):
        """
        Initialize secure storage with PFW priority.

        Args:
            storage_file: Path to storage file. If None, uses priority-based detection.
        """
        if storage_file is None:
            # Priority 1: Check for PFW shared storage (if PFW is installed)
            pfw_storage = os.path.join(os.path.expanduser("~"), ".uspto_pfw_secure_keys")
            fpd_storage = os.path.join(os.path.expanduser("~"), ".uspto_fpd_secure_keys")

            if os.path.exists(pfw_storage):
                storage_file = pfw_storage
                self.using_shared_pfw_storage = True
            else:
                storage_file = fpd_storage
                self.using_shared_pfw_storage = False
        else:
            # Custom path provided
            self.using_shared_pfw_storage = storage_file.endswith(".uspto_pfw_secure_keys")

        self.storage_file = Path(storage_file)

    def store_api_key(self, api_key: str, key_name: str = "USPTO_API_KEY") -> bool:
        """
        Store API key securely using Windows DPAPI.

        Args:
            api_key: The API key to store
            key_name: Name of the key (USPTO_API_KEY or MISTRAL_API_KEY)

        Returns:
            True if successful, False otherwise
        """
        try:
            if sys.platform != "win32":
                # Fall back to environment variable on non-Windows
                return False

            # Basic validation - API keys should be reasonable length
            if not api_key or len(api_key) < 10:
                raise ValueError(f"Invalid {key_name} format")

            # Warn if storing to shared PFW storage
            if self.using_shared_pfw_storage:
                from fpd_mcp.shared.unified_logging import get_logger
                logger = get_logger(__name__)
                logger.info(f"Storing {key_name} to shared PFW storage: {self.storage_file}")

            # Load existing keys or create new structure
            keys_data = self._load_keys_data()

            # Add/update the key
            keys_data[key_name] = api_key

            # Encrypt the entire keys structure
            json_data = json.dumps(keys_data)
            encrypted_data = encrypt_data(json_data.encode('utf-8'))

            # Write to file
            self.storage_file.write_bytes(encrypted_data)

            # Set restrictive permissions (Windows)
            os.chmod(self.storage_file, 0o600)

            return True

        except Exception:
            return False

    def get_api_key(self, key_name: str = "USPTO_API_KEY") -> Optional[str]:
        """
        Retrieve API key from secure storage.

        Args:
            key_name: Name of the key to retrieve (USPTO_API_KEY or MISTRAL_API_KEY)

        Returns:
            The decrypted API key, or None if not found/failed
        """
        try:
            if sys.platform != "win32":
                # Fall back to environment variable on non-Windows
                return os.environ.get(key_name)

            if not self.storage_file.exists():
                # Fall back to environment variable if no secure storage
                return os.environ.get(key_name)

            # Load and decrypt all keys
            keys_data = self._load_keys_data()

            # Return the requested key or fall back to environment variable
            if key_name in keys_data:
                return keys_data[key_name]
            else:
                return os.environ.get(key_name)

        except Exception:
            # Fall back to environment variable on any error
            return os.environ.get(key_name)

    def _load_keys_data(self) -> Dict[str, str]:
        """Load and decrypt the keys data structure with backward compatibility."""
        try:
            if not self.storage_file.exists():
                return {}

            # Read encrypted data
            encrypted_data = self.storage_file.read_bytes()

            try:
                # Try new format first (entropy + encrypted_data)
                decrypted_data = decrypt_data(encrypted_data)
            except (ValueError, OSError):
                # Fall back to old format with hardcoded entropy
                try:
                    decrypted_data = self._decrypt_legacy_data(encrypted_data)
                    # Re-encrypt with new secure format
                    self._migrate_to_secure_format(decrypted_data)
                except Exception:
                    return {}

            json_data = decrypted_data.decode('utf-8')

            # Parse JSON
            keys_data = json.loads(json_data)

            # Validate it's a dictionary
            if not isinstance(keys_data, dict):
                return {}

            return keys_data

        except Exception:
            return {}

    def _decrypt_legacy_data(self, encrypted_data: bytes) -> bytes:
        """Decrypt data using legacy hardcoded entropy for backward compatibility."""
        if sys.platform != "win32":
            raise RuntimeError("DPAPI is only available on Windows")

        # Prepare input data blob
        data_in = DATA_BLOB()
        data_in.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_data), ctypes.POINTER(ctypes.c_char))
        data_in.cbData = len(encrypted_data)

        # Prepare output data blob
        data_out = DATA_BLOB()

        # Legacy hardcoded entropy
        entropy_data = b"uspto_fpd_entropy_v1"
        entropy = DATA_BLOB()
        entropy.pbData = ctypes.cast(ctypes.create_string_buffer(entropy_data), ctypes.POINTER(ctypes.c_char))
        entropy.cbData = len(entropy_data)

        # Prepare description pointer
        description_ptr = ctypes.wintypes.LPWSTR()

        # Call CryptUnprotectData
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        result = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(data_in),          # pDataIn
            ctypes.byref(description_ptr),  # ppszDataDescr
            ctypes.byref(entropy),          # pOptionalEntropy
            None,                           # pvReserved
            None,                           # pPromptStruct
            CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
            ctypes.byref(data_out)          # pDataOut
        )

        if not result:
            error_code = ctypes.windll.kernel32.GetLastError()
            raise OSError(f"Legacy decryption failed with error code: {error_code}")

        # Clean up description
        if description_ptr.value:
            ctypes.windll.kernel32.LocalFree(description_ptr)

        # Extract decrypted data
        return _get_data_from_blob(data_out)

    def _migrate_to_secure_format(self, decrypted_data: bytes):
        """Migrate old format to new secure format."""
        try:
            # Re-encrypt with new secure random entropy
            new_encrypted_data = encrypt_data(decrypted_data)

            # Write back to file with new format
            self.storage_file.write_bytes(new_encrypted_data)

            # Set restrictive permissions
            os.chmod(self.storage_file, 0o600)

        except Exception:
            # Migration failed, but don't break existing functionality
            pass

    def has_secure_key(self, key_name: str = "USPTO_API_KEY") -> bool:
        """
        Check if a secure key is stored.

        Args:
            key_name: Name of the key to check

        Returns:
            True if secure key exists and can be decrypted
        """
        try:
            api_key = self.get_api_key(key_name)
            return api_key is not None and len(api_key) >= 10
        except Exception:
            return False

    def remove_secure_key(self) -> bool:
        """
        Remove the secure key file.

        Returns:
            True if successful or file doesn't exist
        """
        try:
            if self.storage_file.exists():
                self.storage_file.unlink()
            return True
        except Exception:
            return False

    def get_storage_stats(self) -> Dict:
        """
        Get storage statistics for diagnostic purposes.

        Returns:
            Dictionary with storage file information
        """
        keys_data = self._load_keys_data()
        return {
            'storage_file_path': str(self.storage_file),
            'storage_file_exists': self.storage_file.exists(),
            'using_shared_pfw_storage': self.using_shared_pfw_storage,
            'storage_type': 'Shared PFW Storage' if self.using_shared_pfw_storage else 'FPD Local Storage',
            'platform': sys.platform,
            'stored_keys_count': len(keys_data)
        }

    def list_stored_keys(self) -> list:
        """
        List all keys stored in secure storage.

        Returns:
            List of key names
        """
        keys_data = self._load_keys_data()
        return list(keys_data.keys())


def get_secure_api_key(key_name: str = "USPTO_API_KEY") -> Optional[str]:
    """
    Convenience function to get API key from secure storage.

    Args:
        key_name: Name of the key to retrieve (USPTO_API_KEY or MISTRAL_API_KEY)

    Returns:
        The API key, or None if not available
    """
    storage = SecureStorage()
    return storage.get_api_key(key_name)


def store_secure_api_key(api_key: str, key_name: str = "USPTO_API_KEY") -> bool:
    """
    Convenience function to store API key securely.

    Args:
        api_key: The API key to store
        key_name: Name of the key (USPTO_API_KEY or MISTRAL_API_KEY)

    Returns:
        True if successful
    """
    storage = SecureStorage()
    return storage.store_api_key(api_key, key_name)


if __name__ == "__main__":
    # Simple test/demo with proper logging
    import logging
    from fpd_mcp.shared.unified_logging import get_logger
    logging.basicConfig(level=logging.INFO)
    logger = get_logger(__name__)

    if len(sys.argv) > 1:
        if sys.argv[1] == "test":
            # Test encryption/decryption
            test_data = "test_uspto_key_123456789"
            logger.info("Testing DPAPI encryption/decryption...")

            try:
                encrypted = encrypt_data(test_data.encode('utf-8'))
                logger.info(f"Encrypted: {len(encrypted)} bytes")

                decrypted = decrypt_data(encrypted)
                decrypted_str = decrypted.decode('utf-8')
                logger.info(f"Decrypted: {decrypted_str}")

                if decrypted_str == test_data:
                    logger.info("[SUCCESS] DPAPI test PASSED")
                else:
                    logger.error("[FAILED] DPAPI test FAILED")

            except Exception as e:
                logger.error(f"[FAILED] DPAPI test FAILED: {e}")

        elif sys.argv[1] == "store":
            if len(sys.argv) > 2:
                success = store_secure_api_key(sys.argv[2])
                if success:
                    logger.info("[SUCCESS] API key stored securely")
                else:
                    logger.error("[FAILED] Failed to store API key")
            else:
                logger.info("Usage: python secure_storage.py store <api_key>")

        elif sys.argv[1] == "get":
            api_key = get_secure_api_key()
            if api_key:
                logger.info(f"API key: {api_key[:10]}...")
            else:
                logger.warning("No API key found")

    else:
        logger.info("Usage:")
        logger.info("  python secure_storage.py test     - Test DPAPI functionality")
        logger.info("  python secure_storage.py store <key> - Store API key")
        logger.info("  python secure_storage.py get      - Retrieve API key")
