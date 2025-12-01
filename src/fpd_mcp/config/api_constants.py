"""
API Configuration Constants

This module defines all configuration constants used throughout the USPTO FPD MCP
to eliminate magic numbers and provide a single source of truth for tuning.

All values can be overridden via environment variables where applicable.
"""

# =============================================================================
# CONNECTION POOL CONFIGURATION
# =============================================================================

# HTTP connection pool limits for httpx AsyncClient
DEFAULT_MAX_CONNECTIONS = 100
"""Maximum total connections across all hosts (prevents connection pool exhaustion)"""

DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
"""Maximum persistent keep-alive connections to maintain"""

DEFAULT_KEEPALIVE_EXPIRY_SECONDS = 5.0
"""Idle timeout for keep-alive connections before closing"""


# =============================================================================
# CACHE CONFIGURATION
# =============================================================================

# Response cache settings for circuit breaker fallback
DEFAULT_CACHE_SIZE = 100
"""Maximum number of cached responses (LRU eviction when full)"""

DEFAULT_CACHE_TTL_SECONDS = 600
"""Cache time-to-live in seconds (10 minutes for circuit breaker fallback)"""


# =============================================================================
# SEARCH LIMITS
# =============================================================================

# Pagination limits for petition search
MIN_SEARCH_LIMIT = 1
"""Minimum number of search results per page"""

MAX_SEARCH_LIMIT = 200
"""Maximum number of search results per page (USPTO API constraint)"""

DEFAULT_MINIMAL_SEARCH_LIMIT = 50
"""Default limit for minimal tier searches (discovery)"""

DEFAULT_BALANCED_SEARCH_LIMIT = 10
"""Default limit for balanced tier searches (detailed analysis)"""

MAX_QUERY_LENGTH = 2000
"""Maximum combined query string length (characters)"""


# =============================================================================
# TIMEOUT CONFIGURATION
# =============================================================================

# Operation timeout multipliers
OCR_TIMEOUT_MULTIPLIER = 2
"""Multiplier for OCR timeout (2x download_timeout for large PDFs)"""


# =============================================================================
# RETRY CONFIGURATION
# =============================================================================

# Retry settings for PFW proxy detection
DEFAULT_MAX_RETRIES = 3
"""Maximum retry attempts for proxy detection and recoverable operations"""

DEFAULT_RETRY_DELAY_SECONDS = 1.0
"""Base delay between retry attempts in seconds"""


# =============================================================================
# RATE LIMITING (USPTO REQUIREMENTS)
# =============================================================================

# USPTO API download limits
USPTO_MAX_DOWNLOADS_PER_WINDOW = 5
"""USPTO allows maximum 5 document downloads per time window"""

USPTO_RATE_LIMIT_WINDOW_SECONDS = 10
"""USPTO rate limit time window in seconds"""


# =============================================================================
# VALIDATION LIMITS
# =============================================================================

# String parameter validation
DEFAULT_MAX_STRING_LENGTH = 200
"""Default maximum length for string parameters"""

# Date validation
MIN_PETITION_YEAR = 1990
"""Minimum valid year for petition dates (USPTO Final Petition Decisions history)"""

MAX_PETITION_YEAR_OFFSET = 5
"""Maximum years in the future allowed for petition dates (current_year + offset)"""

# Application number validation
MIN_APPLICATION_NUMBER_LENGTH = 6
"""Minimum digits in USPTO application number"""

MAX_APPLICATION_NUMBER_LENGTH = 10
"""Maximum digits in USPTO application number"""


# =============================================================================
# SECURITY & CRYPTOGRAPHY CONSTANTS
# =============================================================================

# DPAPI encryption settings
DPAPI_ENTROPY_BYTES = 32
"""Cryptographically secure entropy size for DPAPI encryption (256 bits)"""

# Log sanitization settings
LOG_SANITIZER_MAX_LENGTH = 1000
"""Maximum length for log messages before truncation"""

LOG_FIELD_VALUE_TRUNCATE_LENGTH = 100
"""Maximum length for field values in logs before truncation"""

LONG_STRING_REDACTION_THRESHOLD = 32
"""Minimum length for strings to be redacted as potentially sensitive"""

# API Key format constants
USPTO_API_KEY_LENGTH = 30
"""Required length for USPTO API keys (30 lowercase letters)"""

MISTRAL_API_KEY_LENGTH = 32
"""Required length for Mistral API keys (32 alphanumeric characters)"""
