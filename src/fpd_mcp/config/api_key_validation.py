"""
API Key Validation Rules - Single Source of Truth

This module provides centralized API key validation rules, eliminating duplication
between PowerShell and Bash deployment scripts.

Fixes Code Duplication:
- Single source of truth for validation rules
- Eliminates logic duplication between:
  * deploy/Validation-Helpers.psm1 (PowerShell)
  * deploy/Validation-Helpers.sh (Bash)
- Scripts reference these rules in comments for consistency

Benefits:
- Easy to update validation rules in one place
- Ensures Python, PowerShell, and Bash use same rules
- Type-safe validation with detailed error messages

Validation Rules:
- USPTO_API_KEY: Exactly 30 lowercase letters (a-z)
- MISTRAL_API_KEY: Exactly 32 alphanumeric characters (A-Z, a-z, 0-9)

Usage:
    from fpd_mcp.config.api_key_validation import validate_api_key, API_KEY_RULES

    # Validate a key
    is_valid, error_msg = validate_api_key("mykey123", "USPTO_API_KEY")
    if not is_valid:
        print(f"Validation failed: {error_msg}")

    # Get validation rules
    rules = API_KEY_RULES["USPTO_API_KEY"]
    print(f"Expected length: {rules['length']}")
    print(f"Pattern: {rules['pattern']}")
"""

import re
from typing import Tuple, Dict, Optional


# ===== API Key Validation Rules =====
# NOTE: These rules must match validation in deployment scripts:
#   - deploy/Validation-Helpers.psm1 (PowerShell)
#   - deploy/Validation-Helpers.sh (Bash)

API_KEY_RULES = {
    'USPTO_API_KEY': {
        'length': 30,
        'pattern': r'^[a-z]+$',
        'description': '30 lowercase letters (a-z)',
        'regex_flags': 0,
        'example': 'abcdefghijklmnopqrstuvwxyzabcd'
    },
    'MISTRAL_API_KEY': {
        'length': 32,
        'pattern': r'^[A-Za-z0-9]+$',
        'description': '32 alphanumeric characters (A-Z, a-z, 0-9)',
        'regex_flags': 0,
        'example': 'aBcDeF1234567890ghIjKlMnOpQr5678'
    }
}


def validate_api_key(key: str, key_type: str) -> Tuple[bool, str]:
    """
    Validate API key format against defined rules.

    Args:
        key: The API key to validate
        key_type: Type of key ("USPTO_API_KEY" or "MISTRAL_API_KEY")

    Returns:
        Tuple of (is_valid: bool, error_message: str)
        - If valid: (True, "Valid")
        - If invalid: (False, detailed error message)

    Example:
        >>> is_valid, msg = validate_api_key("test", "USPTO_API_KEY")
        >>> print(f"Valid: {is_valid}, Message: {msg}")
        Valid: False, Message: USPTO_API_KEY must be exactly 30 characters (got 4)
    """
    # Check if key type is known
    if key_type not in API_KEY_RULES:
        return False, f"Unknown key type: {key_type}"

    rules = API_KEY_RULES[key_type]

    # Check for empty key (special case for optional keys like Mistral)
    if not key:
        if key_type == "MISTRAL_API_KEY":
            # Mistral is optional - empty is allowed
            return True, "Valid (optional key not provided)"
        else:
            return False, f"{key_type} cannot be empty"

    # Check length
    expected_length = rules['length']
    if len(key) != expected_length:
        return False, (
            f"{key_type} must be exactly {expected_length} characters "
            f"(got {len(key)})"
        )

    # Check pattern
    pattern = rules['pattern']
    flags = rules.get('regex_flags', 0)
    if not re.match(pattern, key, flags):
        return False, (
            f"{key_type} format invalid. "
            f"Expected: {rules['description']}"
        )

    # All checks passed
    return True, "Valid"


def validate_uspto_api_key(key: str) -> Tuple[bool, str]:
    """
    Validate USPTO API key format.

    Convenience wrapper for validate_api_key() specific to USPTO keys.

    Args:
        key: The USPTO API key to validate

    Returns:
        Tuple of (is_valid: bool, error_message: str)

    Example:
        >>> is_valid, msg = validate_uspto_api_key("abcdefghijklmnopqrstuvwxyzabcd")
        >>> print(is_valid)
        True
    """
    return validate_api_key(key, "USPTO_API_KEY")


def validate_mistral_api_key(key: str) -> Tuple[bool, str]:
    """
    Validate Mistral API key format.

    Convenience wrapper for validate_api_key() specific to Mistral keys.
    Note: Empty keys are allowed (Mistral is optional for OCR).

    Args:
        key: The Mistral API key to validate

    Returns:
        Tuple of (is_valid: bool, error_message: str)

    Example:
        >>> is_valid, msg = validate_mistral_api_key("")
        >>> print(is_valid)  # True - optional key
        True
    """
    return validate_api_key(key, "MISTRAL_API_KEY")


def get_validation_rules(key_type: str) -> Optional[Dict]:
    """
    Get validation rules for a specific key type.

    Args:
        key_type: Type of key ("USPTO_API_KEY" or "MISTRAL_API_KEY")

    Returns:
        Dictionary with validation rules, or None if key_type unknown

    Example:
        >>> rules = get_validation_rules("USPTO_API_KEY")
        >>> print(f"Length: {rules['length']}, Pattern: {rules['description']}")
        Length: 30, Pattern: 30 lowercase letters (a-z)
    """
    return API_KEY_RULES.get(key_type)


def format_validation_error(key: str, key_type: str, error_message: str) -> str:
    """
    Format a detailed validation error message with examples.

    Args:
        key: The invalid key (will be truncated for security)
        key_type: Type of key that failed validation
        error_message: Error message from validation

    Returns:
        Formatted error message with examples and guidance

    Example:
        >>> error = format_validation_error("short", "USPTO_API_KEY",
        ...                                  "Must be 30 characters")
        >>> print(error)
        Validation Error: USPTO_API_KEY
        Error: Must be 30 characters
        Expected format: 30 lowercase letters (a-z)
        Example: abcdefghijklmnopqrstuvwxyzabcd
    """
    rules = API_KEY_RULES.get(key_type, {})

    # Truncate key for security (show first/last few chars only)
    if len(key) > 10:
        key_display = f"{key[:5]}...{key[-3:]}"
    else:
        key_display = f"{key[:3]}..." if len(key) > 3 else "***"

    lines = [
        f"Validation Error: {key_type}",
        f"Error: {error_message}",
        f"Provided key: {key_display} (length: {len(key)})",
    ]

    if rules:
        lines.append(f"Expected format: {rules['description']}")
        lines.append(f"Example: {rules.get('example', 'N/A')}")

    return "\n".join(lines)


# ===== Validation for Deployment Scripts =====
# These constants are used by deployment scripts for consistency

USPTO_KEY_LENGTH = API_KEY_RULES['USPTO_API_KEY']['length']
USPTO_KEY_PATTERN = API_KEY_RULES['USPTO_API_KEY']['pattern']
USPTO_KEY_DESCRIPTION = API_KEY_RULES['USPTO_API_KEY']['description']

MISTRAL_KEY_LENGTH = API_KEY_RULES['MISTRAL_API_KEY']['length']
MISTRAL_KEY_PATTERN = API_KEY_RULES['MISTRAL_API_KEY']['pattern']
MISTRAL_KEY_DESCRIPTION = API_KEY_RULES['MISTRAL_API_KEY']['description']


if __name__ == "__main__":
    """Test validation rules"""
    print("Testing API Key Validation Rules\n")

    # Test USPTO key validation
    print("=== USPTO API Key Tests ===")
    test_cases_uspto = [
        ("abcdefghijklmnopqrstuvwxyzabcd", True),  # Valid
        ("short", False),  # Too short
        ("ABCDEFGHIJKLMNOPQRSTUVWXYZABCD", False),  # Uppercase
        ("abcdefghijklmnopqrstuvwxyz1234", False),  # Contains numbers
        ("", False),  # Empty
    ]

    for key, should_pass in test_cases_uspto:
        is_valid, msg = validate_uspto_api_key(key)
        status = "✓ PASS" if is_valid == should_pass else "✗ FAIL"
        print(f"{status}: '{key[:10]}...' -> {msg}")

    # Test Mistral key validation
    print("\n=== Mistral API Key Tests ===")
    test_cases_mistral = [
        ("aBcDeF1234567890ghIjKlMnOpQr5678", True),  # Valid
        ("", True),  # Empty (optional)
        ("short", False),  # Too short
        ("aBcDeF123456-890ghIjKlMnOpQr5678", False),  # Special chars
    ]

    for key, should_pass in test_cases_mistral:
        is_valid, msg = validate_mistral_api_key(key)
        status = "✓ PASS" if is_valid == should_pass else "✗ FAIL"
        key_display = "''" if not key else f"'{key[:10]}...'"
        print(f"{status}: {key_display} -> {msg}")
