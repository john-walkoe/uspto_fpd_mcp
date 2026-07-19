"""Shared input validators for the search/details and document tools.

Extracted verbatim from main.py (mechanical decomposition, no behavior
change) — moved here because validate_petition_id / validate_document_identifier
are used by both tools/petitions.py and tools/documents.py.
"""

import re
from datetime import datetime

from .shared.error_utils import ValidationError, generate_request_id


def validate_date_range(date_str: str) -> str:
    """Validate date string in YYYY-MM-DD format"""
    if not date_str:
        return None

    # Remove whitespace
    clean_date = date_str.strip()

    # If empty after stripping, return None
    if not clean_date:
        return None

    # Check format YYYY-MM-DD
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', clean_date):
        raise ValidationError("Date must be in YYYY-MM-DD format (e.g., '2024-01-01')", generate_request_id())

    # Validate actual date values
    try:
        datetime.strptime(clean_date, '%Y-%m-%d')
    except ValueError:
        raise ValidationError("Invalid date. Please check year, month, and day values.", generate_request_id())

    # Check reasonable date range (1990 to current year + 5)
    year = int(clean_date[:4])
    current_year = datetime.now().year
    if year < 1990 or year > current_year + 5:
        raise ValidationError(f"Date year must be between 1990 and {current_year + 5}", generate_request_id())

    return clean_date


# M2: allowlist (not denylist) for values interpolated into Lucene query
# strings in _build_convenience_query. Letters/digits/underscore (\w),
# whitespace, and the punctuation legitimate names/offices actually use
# (period, comma, ampersand, apostrophe, hyphen) are permitted; Lucene
# metacharacters (: ( ) [ ] * ? ~ ^ " etc.) and anything else are rejected
# outright rather than merely escaped, since none of the convenience
# parameters need them.
_ALLOWED_STRING_PARAM_RE = re.compile(r"^[\w\s.,&'-]+$")


def validate_string_param(param_name: str, param_value: str, max_length: int = 200) -> str:
    """Validate string parameter input"""
    if not param_value:
        return None

    # Trim whitespace
    clean_value = param_value.strip()

    if not clean_value:
        return None

    # Check length limits
    if len(clean_value) > max_length:
        raise ValidationError(f"{param_name} too long. Maximum {max_length} characters.", generate_request_id())

    # Allowlist: reject anything outside the safe character set (M2) —
    # this blocks Lucene metacharacters (: ( ) [ ] * ? ~ ^ " etc.) that a
    # denylist alone would miss, while still permitting legitimate values
    # like "Johnson & Johnson" or "O'Brien-Smith".
    if not _ALLOWED_STRING_PARAM_RE.match(clean_value):
        raise ValidationError(f"{param_name} contains invalid characters.", generate_request_id())

    return clean_value


def validate_application_number(app_number: str) -> str:
    """Validate and clean USPTO application number format"""
    if not app_number:
        return None

    # Remove whitespace and clean format
    clean_number = app_number.strip().replace("/", "").replace(" ", "")

    if not clean_number:
        return None

    # Basic length validation (USPTO application numbers are typically 8 digits)
    if len(clean_number) < 6 or len(clean_number) > 10:
        raise ValidationError("Application number should be 6-10 digits", generate_request_id())

    # Check if all characters are digits
    if not clean_number.isdigit():
        raise ValidationError("Application number should contain only digits", generate_request_id())

    return clean_number


# M4: petition_id is documented as a UUID (e.g.
# "e55bd36d-961f-511e-b72c-b4b1529d67ef" from real search results) but was
# previously checked only for non-emptiness before being concatenated
# straight into the outbound USPTO API path. document_identifier is
# documented as an alnum code (e.g. "HY1J6ICXPXXIFW4"); the pattern below is
# a safe superset of the observed 15-17 char uppercase-alnum shape.
_PETITION_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_DOCUMENT_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9]{8,32}$")


def validate_petition_id(petition_id: str) -> str:
    """Validate petition_id is UUID-shaped before it reaches URL construction."""
    petition_id = (petition_id or "").strip()
    if not petition_id:
        raise ValidationError("Petition ID cannot be empty", generate_request_id())
    if not _PETITION_ID_RE.match(petition_id):
        raise ValidationError("Petition ID must be a valid UUID", generate_request_id())
    return petition_id


def validate_document_identifier(document_identifier: str) -> str:
    """Validate document_identifier is an alnum code of the expected shape."""
    document_identifier = (document_identifier or "").strip()
    if not document_identifier:
        raise ValidationError("Document identifier cannot be empty", generate_request_id())
    if not _DOCUMENT_IDENTIFIER_RE.match(document_identifier):
        raise ValidationError("Document identifier is invalid", generate_request_id())
    return document_identifier
