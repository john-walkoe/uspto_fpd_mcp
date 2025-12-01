#!/bin/bash
# API Key Validation Helpers for Linux/macOS
#
# Validates USPTO and Mistral API key formats before storage
# Prevents typos and malformed keys from being stored

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Validate USPTO API key format
# Expected: Exactly 30 lowercase letters
validate_uspto_api_key() {
    local api_key="$1"
    local expected_length=30

    # Check if empty
    if [[ -z "$api_key" ]]; then
        echo -e "${RED}ERROR: USPTO API key cannot be empty${NC}" >&2
        return 1
    fi

    # Check exact length
    if [[ ${#api_key} -ne $expected_length ]]; then
        echo -e "${RED}ERROR: USPTO API key must be exactly $expected_length characters${NC}" >&2
        echo -e "${RED}       Got ${#api_key} characters${NC}" >&2
        return 1
    fi

    # Check character set (lowercase letters only)
    if ! [[ "$api_key" =~ ^[a-z]+$ ]]; then
        echo -e "${RED}ERROR: USPTO API key must contain only lowercase letters (a-z)${NC}" >&2
        echo -e "${YELLOW}       Expected format: 30 lowercase letters${NC}" >&2

        # Show which characters are invalid
        invalid_chars=$(echo "$api_key" | grep -o '[^a-z]' | sort -u | tr -d '\n')
        if [[ -n "$invalid_chars" ]]; then
            echo -e "${YELLOW}       Invalid characters found: '$invalid_chars'${NC}" >&2
        fi

        return 1
    fi

    echo -e "${GREEN}✓ USPTO API key format valid (30 lowercase letters)${NC}"
    return 0
}

# Validate Mistral API key format
# Expected: Exactly 32 alphanumeric characters (upper and lowercase letters, numbers)
validate_mistral_api_key() {
    local api_key="$1"
    local expected_length=32

    # Allow empty (optional key)
    if [[ -z "$api_key" ]]; then
        echo -e "${YELLOW}ℹ Mistral API key not provided (optional - OCR disabled)${NC}"
        return 0
    fi

    # Check exact length
    if [[ ${#api_key} -ne $expected_length ]]; then
        echo -e "${RED}ERROR: Mistral API key must be exactly $expected_length characters${NC}" >&2
        echo -e "${RED}       Got ${#api_key} characters${NC}" >&2
        return 1
    fi

    # Check alphanumeric (uppercase, lowercase, numbers)
    if ! [[ "$api_key" =~ ^[A-Za-z0-9]+$ ]]; then
        echo -e "${RED}ERROR: Mistral API key must contain only letters and numbers${NC}" >&2
        echo -e "${YELLOW}       Expected format: 32 alphanumeric characters (A-Z, a-z, 0-9)${NC}" >&2

        # Show which characters are invalid
        invalid_chars=$(echo "$api_key" | grep -o '[^A-Za-z0-9]' | sort -u | tr -d '\n')
        if [[ -n "$invalid_chars" ]]; then
            echo -e "${YELLOW}       Invalid characters found: '$invalid_chars'${NC}" >&2
        fi

        return 1
    fi

    echo -e "${GREEN}✓ Mistral API key format valid (32 alphanumeric characters)${NC}"
    return 0
}

# Test function (run with: bash Validation-Helpers.sh test)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]] && [[ "$1" == "test" ]]; then
    echo "Testing API Key Validation..."
    echo ""

    echo "=== USPTO API Key Tests ==="

    # Test valid USPTO key
    echo "Test 1: Valid USPTO key (30 lowercase letters)"
    if validate_uspto_api_key "abcdefghijklmnopqrstuvwxyzabcd"; then
        echo -e "${GREEN}✓ PASSED${NC}"
    else
        echo -e "${RED}✗ FAILED${NC}"
    fi
    echo ""

    # Test too short
    echo "Test 2: Too short USPTO key"
    if ! validate_uspto_api_key "short"; then
        echo -e "${GREEN}✓ PASSED (correctly rejected)${NC}"
    else
        echo -e "${RED}✗ FAILED (should have been rejected)${NC}"
    fi
    echo ""

    # Test uppercase
    echo "Test 3: USPTO key with uppercase letters"
    if ! validate_uspto_api_key "ABCDEFGHIJKLMNOPQRSTUVWXYZABCD"; then
        echo -e "${GREEN}✓ PASSED (correctly rejected)${NC}"
    else
        echo -e "${RED}✗ FAILED (should have been rejected)${NC}"
    fi
    echo ""

    # Test with numbers
    echo "Test 4: USPTO key with numbers"
    if ! validate_uspto_api_key "abcdefghijklmnopqrstuvwxyz1234"; then
        echo -e "${GREEN}✓ PASSED (correctly rejected)${NC}"
    else
        echo -e "${RED}✗ FAILED (should have been rejected)${NC}"
    fi
    echo ""

    echo "=== Mistral API Key Tests ==="

    # Test valid Mistral key
    echo "Test 5: Valid Mistral key (32 alphanumeric)"
    if validate_mistral_api_key "aBcDeF1234567890ghIjKlMnOpQr5678"; then
        echo -e "${GREEN}✓ PASSED${NC}"
    else
        echo -e "${RED}✗ FAILED${NC}"
    fi
    echo ""

    # Test empty (should pass - optional)
    echo "Test 6: Empty Mistral key (optional)"
    if validate_mistral_api_key ""; then
        echo -e "${GREEN}✓ PASSED (optional key)${NC}"
    else
        echo -e "${RED}✗ FAILED${NC}"
    fi
    echo ""

    # Test too long
    echo "Test 7: Too long Mistral key"
    if ! validate_mistral_api_key "aBcDeF1234567890ghIjKlMnOpQr5678EXTRA"; then
        echo -e "${GREEN}✓ PASSED (correctly rejected)${NC}"
    else
        echo -e "${RED}✗ FAILED (should have been rejected)${NC}"
    fi
    echo ""

    # Test with special characters
    echo "Test 8: Mistral key with special characters"
    if ! validate_mistral_api_key "aBcDeF123456-890ghIjKlMnOpQr5678"; then
        echo -e "${GREEN}✓ PASSED (correctly rejected)${NC}"
    else
        echo -e "${RED}✗ FAILED (should have been rejected)${NC}"
    fi
    echo ""

    echo "=== All Tests Complete ==="
fi
