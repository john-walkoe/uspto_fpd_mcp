"""
Feature Flags for Graceful Degradation and Emergency Control

Provides runtime feature toggles for:
- Emergency feature shutdowns during incidents
- Gradual feature rollouts
- A/B testing capabilities
- Graceful degradation under load

Usage:
    from fpd_mcp.config.feature_flags import feature_flags

    if feature_flags.is_enabled("ocr_enabled"):
        # Perform OCR operation
    else:
        # Return error or use fallback
"""
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class FeatureFlags:
    """
    Feature flag management for runtime feature control.

    Flags are loaded from environment variables with sensible defaults.
    All flags default to enabled unless explicitly disabled.
    """

    def __init__(self):
        """Initialize feature flags from environment variables"""

        self.flags = {
            # Core features (critical - should rarely be disabled)
            "search_enabled": self._get_flag("FPD_SEARCH_ENABLED", True),
            "petition_details_enabled": self._get_flag("FPD_PETITION_DETAILS_ENABLED", True),
            "document_download_enabled": self._get_flag("FPD_DOCUMENT_DOWNLOAD_ENABLED", True),

            # Optional features (can be disabled during incidents)
            "ocr_enabled": self._get_flag("FPD_OCR_ENABLED", True),
            "mistral_ocr_enabled": self._get_flag("FPD_MISTRAL_OCR_ENABLED", True),
            "pypdf2_extraction_enabled": self._get_flag("FPD_PYPDF2_EXTRACTION_ENABLED", True),

            # Infrastructure features
            "cache_enabled": self._get_flag("FPD_CACHE_ENABLED", True),
            "rate_limiting_enabled": self._get_flag("FPD_RATE_LIMITING_ENABLED", True),
            "circuit_breaker_enabled": self._get_flag("FPD_CIRCUIT_BREAKER_ENABLED", True),

            # Proxy and networking
            "proxy_downloads_enabled": self._get_flag("FPD_PROXY_DOWNLOADS_ENABLED", True),
            "centralized_proxy_enabled": self._get_flag("FPD_CENTRALIZED_PROXY_ENABLED", True),

            # Advanced features
            "field_filtering_enabled": self._get_flag("FPD_FIELD_FILTERING_ENABLED", True),
            "prompt_templates_enabled": self._get_flag("FPD_PROMPT_TEMPLATES_ENABLED", True),

            # Monitoring and observability
            "metrics_enabled": self._get_flag("FPD_METRICS_ENABLED", True),
            "detailed_logging_enabled": self._get_flag("FPD_DETAILED_LOGGING_ENABLED", True),

            # Emergency kill switches
            "maintenance_mode": self._get_flag("FPD_MAINTENANCE_MODE", False),  # Defaults to OFF
            "read_only_mode": self._get_flag("FPD_READ_ONLY_MODE", False),  # Defaults to OFF
        }

        # Log feature flag status at startup
        enabled_features = [name for name, enabled in self.flags.items() if enabled]
        disabled_features = [name for name, enabled in self.flags.items() if not enabled]

        logger.info(f"Feature flags initialized: {len(enabled_features)} enabled, {len(disabled_features)} disabled")

        if disabled_features:
            logger.warning(f"Disabled features: {', '.join(disabled_features)}")

        # Log maintenance mode prominently
        if self.flags.get("maintenance_mode"):
            logger.critical("⚠️  MAINTENANCE MODE ENABLED - Service may be degraded")

        if self.flags.get("read_only_mode"):
            logger.warning("📖 READ-ONLY MODE ENABLED - Write operations disabled")

    def _get_flag(self, env_var: str, default: bool) -> bool:
        """
        Get boolean feature flag from environment variable.

        Args:
            env_var: Environment variable name
            default: Default value if not set

        Returns:
            Boolean flag value
        """
        value = os.getenv(env_var)

        if value is None:
            return default

        # Handle various boolean string representations
        return value.lower() in ("true", "1", "yes", "on", "enabled")

    def is_enabled(self, feature: str) -> bool:
        """
        Check if a feature is enabled.

        Args:
            feature: Feature name

        Returns:
            True if feature is enabled, False otherwise
        """
        if feature not in self.flags:
            logger.warning(f"Unknown feature flag queried: {feature} - defaulting to False")
            return False

        return self.flags.get(feature, False)

    def is_disabled(self, feature: str) -> bool:
        """
        Check if a feature is disabled.

        Args:
            feature: Feature name

        Returns:
            True if feature is disabled, False otherwise
        """
        return not self.is_enabled(feature)

    def get_all(self) -> Dict[str, bool]:
        """
        Get all feature flags and their current values.

        Returns:
            Dictionary of feature names to boolean values
        """
        return self.flags.copy()

    def get_status(self) -> Dict[str, Any]:
        """
        Get feature flag status summary.

        Returns:
            Dictionary with summary statistics
        """
        enabled_count = sum(1 for enabled in self.flags.values() if enabled)
        disabled_count = len(self.flags) - enabled_count

        return {
            "total_flags": len(self.flags),
            "enabled": enabled_count,
            "disabled": disabled_count,
            "maintenance_mode": self.flags.get("maintenance_mode", False),
            "read_only_mode": self.flags.get("read_only_mode", False),
            "flags": self.get_all()
        }

    def require_feature(self, feature: str, error_message: Optional[str] = None):
        """
        Require a feature to be enabled, raise exception if disabled.

        Args:
            feature: Feature name
            error_message: Optional custom error message

        Raises:
            RuntimeError: If feature is disabled
        """
        if not self.is_enabled(feature):
            msg = error_message or f"Feature '{feature}' is currently disabled"
            logger.error(msg)
            raise RuntimeError(msg)


# Global feature flags instance
feature_flags = FeatureFlags()


# Convenience functions
def is_enabled(feature: str) -> bool:
    """Check if feature is enabled (convenience function)"""
    return feature_flags.is_enabled(feature)


def require_feature(feature: str, error_message: Optional[str] = None):
    """Require feature to be enabled (convenience function)"""
    feature_flags.require_feature(feature, error_message)
