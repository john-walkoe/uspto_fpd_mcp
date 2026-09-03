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
from typing import Dict, Any, Optional
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)


class FeatureFlags:
    """
    Feature flag management for runtime feature control.

    Flags are loaded from environment variables with sensible defaults.
    All flags default to enabled unless explicitly disabled.
    """

    def __init__(self):
        """Initialize feature flags from environment variables"""

        # F-E6: fifteen of the seventeen flags declared here had no reader
        # anywhere in src/. The two that work are the OCR gates below. The
        # rest were removed rather than left declared: an operator who set
        # FPD_MAINTENANCE_MODE=true during an incident got a CRITICAL log line
        # asserting an action that did not happen and a fully live server,
        # which is worse than having no switch at all.
        #
        # maintenance_mode is KEPT and is now wired for real, at registration
        # time in tools/__init__.py::register_all — the FPD_ENABLE_* idiom
        # this repo already uses for the admin tool and the prompts.
        self.flags = {
            # OCR tiers (both read by services/document_extraction.py)
            "ocr_enabled": self._get_flag("FPD_OCR_ENABLED", True),
            "mistral_ocr_enabled": self._get_flag("FPD_MISTRAL_OCR_ENABLED", True),

            # Emergency kill switch (read by tools/__init__.py::register_all)
            "maintenance_mode": self._get_flag("FPD_MAINTENANCE_MODE", False),
        }

        # Log feature flag status at startup
        enabled_features = [name for name, enabled in self.flags.items() if enabled]
        disabled_features = [name for name, enabled in self.flags.items() if not enabled]

        logger.info(f"Feature flags initialized: {len(enabled_features)} enabled, {len(disabled_features)} disabled")

        if disabled_features:
            logger.warning(f"Disabled features: {', '.join(disabled_features)}")

        # Log maintenance mode prominently
        if self.flags.get("maintenance_mode"):
            logger.critical(
                "MAINTENANCE MODE ENABLED - only FPD_get_guidance is registered"
            )


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
