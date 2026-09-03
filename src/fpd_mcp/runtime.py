"""Shared runtime singletons (DP-1/SOLID-5 — AppContext-lite).

Settings bootstrap, logging init, secure-storage key loading, and the
service singletons (FPD API client, field manager, FPDService) live here so
tool modules depend on ONE stable module instead of the composition root.
`get_api_client()` / `get_fpd_service()` are the lazy-init seams every tool
uses — tests can patch `runtime.api_client` / `runtime.fpd_service` (or the
getters) to inject fakes.
"""

import os

from .api.fpd_client import FPDClient
from .config.field_manager import FieldManager
from .config.settings import Settings
from .services.fpd_service import FPDService

# Configure comprehensive logging with rotation and security
from .config.log_config import setup_logging
from .util.secure_logger import get_secure_logger

log_manager = setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_secure_logger(__name__)

# Initialize settings to load API keys from secure storage
settings = Settings()

api_client = None  # Deferred initialization via get_api_client() to prevent async lifecycle issues


def get_api_client() -> FPDClient:
    """
    Get or create the global API client instance.

    This factory function ensures the API client is properly initialized
    before use, preventing async lifecycle errors when the global client
    is None or in an invalid state.

    Returns:
        FPDClient: Initialized API client instance

    Raises:
        ValueError: If USPTO API key is not available
    """
    global api_client
    if api_client is None:
        logger.info("Initializing FPD API client (deferred initialization)")
        api_client = FPDClient(api_key=settings.uspto_api_key)
    return api_client


# F-A7: this used to be a try/except whose handler called the identical
# constructor with the identical argument, so if the constructor was what
# raised it re-raised uncaught at import and the server did not start — while
# the comment asserted the opposite. FieldManager.load_config already catches
# everything and falls back to its in-code defaults, so the block was dead in
# every case it claimed to cover. Fallback happens once, inside the class,
# and says so in the log.
# F-A6: the path was computed here AND independently in config/settings.py,
# with a different number of .parent hops. One computation, one value.
config_path = settings.field_config_path
assert config_path is not None  # Settings.__init__ always resolves a default
field_manager = FieldManager(config_path)


fpd_service = None  # Deferred initialization via get_fpd_service(), matching get_api_client()'s idiom


def get_fpd_service() -> FPDService:
    """Get or create the global FPDService instance (lazy init, same idiom
    as get_api_client()). Wires the shared api_client + field_manager
    singletons so the search/details tools route through a single
    implementation instead of duplicating the inline API-call + filter
    logic (Phase 6B finding #1)."""
    global fpd_service
    if fpd_service is None:
        fpd_service = FPDService(get_api_client(), field_manager)
    return fpd_service
