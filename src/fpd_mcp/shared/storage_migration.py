"""
Storage Migration Utility

This module provides utilities to migrate from legacy multi-key JSON storage
to the new unified single-key-per-file storage architecture.

Fixes Code Duplication:
- Enables deprecation of secure_storage.py (503 lines)
- Consolidates storage architecture to shared_secure_storage.py only

Migration Path:
  Legacy: .uspto_fpd_secure_keys (multi-key JSON)
          .uspto_pfw_secure_keys (multi-key JSON)
      ↓
  Unified: .uspto_api_key (single key, DPAPI encrypted)
           .mistral_api_key (single key, DPAPI encrypted)

Usage:
    from fpd_mcp.shared.storage_migration import migrate_legacy_storage

    # Migrate automatically
    success = migrate_legacy_storage()

    # Or check status first
    from fpd_mcp.shared.storage_migration import check_migration_needed
    if check_migration_needed():
        migrate_legacy_storage()
"""

from pathlib import Path
from typing import Optional, Dict, Tuple

from ..config.storage_paths import StoragePaths
from .unified_logging import get_logger

logger = get_logger(__name__)


def check_migration_needed() -> Tuple[bool, str]:
    """
    Check if migration from legacy storage is needed.

    Returns:
        Tuple of (needs_migration: bool, reason: str)

    Example:
        >>> needs_migration, reason = check_migration_needed()
        >>> if needs_migration:
        ...     print(f"Migration needed: {reason}")
    """
    # Check if unified storage already exists
    if StoragePaths.has_unified_storage():
        return False, "Unified storage already exists"

    # Check for legacy storage
    if StoragePaths.PFW_SHARED_STORAGE.exists():
        return True, f"PFW shared storage found at {StoragePaths.PFW_SHARED_STORAGE}"

    if StoragePaths.FPD_LOCAL_STORAGE.exists():
        return True, f"FPD local storage found at {StoragePaths.FPD_LOCAL_STORAGE}"

    return False, "No storage found - fresh installation"


def migrate_legacy_storage(
    backup: bool = True,
    remove_legacy: bool = False
) -> bool:
    """
    Migrate API keys from legacy multi-key JSON storage to unified single-key storage.

    Args:
        backup: Create backup of legacy files before migration (default: True)
        remove_legacy: Remove legacy files after successful migration (default: False)

    Returns:
        True if migration successful or not needed, False on error

    Example:
        >>> # Migrate with backup, keep legacy files
        >>> success = migrate_legacy_storage()

        >>> # Migrate and remove legacy files
        >>> success = migrate_legacy_storage(remove_legacy=True)
    """
    try:
        # Import here to avoid circular dependencies
        from ..secure_storage import SecureStorage as LegacyStorage
        from ..shared_secure_storage import UnifiedSecureStorage

        logger.info("Starting storage migration check...")

        # Check if migration is needed
        needs_migration, reason = check_migration_needed()
        if not needs_migration:
            logger.info(f"Migration not needed: {reason}")
            return True

        logger.info(f"Migration needed: {reason}")

        # Determine which legacy storage to migrate from (PFW has priority)
        legacy_path = None
        if StoragePaths.PFW_SHARED_STORAGE.exists():
            legacy_path = StoragePaths.PFW_SHARED_STORAGE
            logger.info(f"Migrating from PFW shared storage: {legacy_path}")
        elif StoragePaths.FPD_LOCAL_STORAGE.exists():
            legacy_path = StoragePaths.FPD_LOCAL_STORAGE
            logger.info(f"Migrating from FPD local storage: {legacy_path}")
        else:
            logger.warning("No legacy storage found, nothing to migrate")
            return True

        # Backup legacy file if requested
        if backup and legacy_path:
            backup_path = Path(str(legacy_path) + ".backup")
            try:
                import shutil
                shutil.copy2(legacy_path, backup_path)
                logger.info(f"Created backup: {backup_path}")
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")
                # Continue anyway - backup is optional

        # Load keys from legacy storage
        legacy_storage = LegacyStorage(str(legacy_path))
        uspto_key = legacy_storage.get_api_key("USPTO_API_KEY")
        mistral_key = legacy_storage.get_api_key("MISTRAL_API_KEY")

        if not uspto_key and not mistral_key:
            logger.warning("No API keys found in legacy storage")
            return True

        # Store in new unified storage
        unified = UnifiedSecureStorage()
        migration_success = True

        if uspto_key:
            logger.info("Migrating USPTO API key...")
            if unified.store_uspto_key(uspto_key):
                logger.info(f"✓ USPTO API key migrated to {StoragePaths.USPTO_API_KEY}")
            else:
                logger.error("✗ Failed to migrate USPTO API key")
                migration_success = False

        if mistral_key:
            logger.info("Migrating Mistral API key...")
            if unified.store_mistral_key(mistral_key):
                logger.info(f"✓ Mistral API key migrated to {StoragePaths.MISTRAL_API_KEY}")
            else:
                logger.warning("✗ Failed to migrate Mistral API key (optional)")
                # Don't fail migration for optional Mistral key

        if not migration_success:
            logger.error("Migration failed - legacy files preserved")
            return False

        # Remove legacy files if requested and migration succeeded
        if remove_legacy and legacy_path:
            try:
                legacy_path.unlink()
                logger.info(f"Removed legacy storage: {legacy_path}")
            except Exception as e:
                logger.warning(f"Failed to remove legacy file: {e}")
                logger.warning("Please remove manually if desired")

        logger.info("✓ Migration completed successfully")
        logger.info("Legacy storage files preserved for safety")
        logger.info("You can remove them manually after verifying the migration")

        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


def get_migration_status() -> Dict[str, any]:
    """
    Get detailed migration status information.

    Returns:
        Dictionary with migration status details

    Example:
        >>> status = get_migration_status()
        >>> print(f"Needs migration: {status['needs_migration']}")
        >>> print(f"Unified storage exists: {status['has_unified']}")
        >>> print(f"Legacy storage exists: {status['has_legacy']}")
    """
    needs_migration, reason = check_migration_needed()

    status = {
        'needs_migration': needs_migration,
        'reason': reason,
        'has_unified': StoragePaths.has_unified_storage(),
        'has_legacy': StoragePaths.has_legacy_storage(),
        'unified_paths': {
            'uspto_key': str(StoragePaths.USPTO_API_KEY),
            'mistral_key': str(StoragePaths.MISTRAL_API_KEY),
            'uspto_exists': StoragePaths.USPTO_API_KEY.exists(),
            'mistral_exists': StoragePaths.MISTRAL_API_KEY.exists()
        },
        'legacy_paths': {
            'pfw_shared': str(StoragePaths.PFW_SHARED_STORAGE),
            'fpd_local': str(StoragePaths.FPD_LOCAL_STORAGE),
            'pfw_exists': StoragePaths.PFW_SHARED_STORAGE.exists(),
            'fpd_exists': StoragePaths.FPD_LOCAL_STORAGE.exists()
        }
    }

    return status


def auto_migrate_on_import() -> None:
    """
    Automatically migrate legacy storage when module is imported.

    This function is called automatically when the module is imported.
    It silently attempts migration without failing if unsuccessful.

    Logs:
        - Info level: Migration progress and success
        - Warning level: Migration failures (non-critical)
    """
    try:
        needs_migration, _ = check_migration_needed()
        if needs_migration:
            logger.info("Auto-migration: Legacy storage detected")
            success = migrate_legacy_storage(backup=True, remove_legacy=False)
            if success:
                logger.info("Auto-migration: Completed successfully")
            else:
                logger.warning("Auto-migration: Failed, using legacy storage")
    except Exception as e:
        # Don't break import if auto-migration fails
        logger.warning(f"Auto-migration failed: {e}")


# Auto-migrate on import (silent, non-breaking)
# Uncomment when ready to enable automatic migration:
# auto_migrate_on_import()
