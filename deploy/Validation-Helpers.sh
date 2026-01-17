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

# ============================================
# Existing Key Detection Functions
# ============================================

# Check if USPTO API key exists in secure storage
check_existing_uspto_key() {
    if [[ -f "$HOME/.uspto_api_key" ]]; then
        return 0  # Exists
    else
        return 1  # Does not exist
    fi
}

# Check if Mistral API key exists in secure storage
check_existing_mistral_key() {
    if [[ -f "$HOME/.mistral_api_key" ]]; then
        return 0  # Exists
    else
        return 1  # Does not exist
    fi
}

# Load existing USPTO key from secure storage (uses Python)
load_existing_uspto_key() {
    # Use Python to load from secure storage
    python3 << 'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from fpd_mcp.shared_secure_storage import get_uspto_api_key
    key = get_uspto_api_key()
    if key:
        print(key)
        sys.exit(0)
    else:
        sys.exit(1)
except Exception as e:
    sys.exit(1)
EOF
}

# Load existing Mistral key from secure storage (uses Python)
load_existing_mistral_key() {
    # Use Python to load from secure storage
    python3 << 'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from fpd_mcp.shared_secure_storage import get_mistral_api_key
    key = get_mistral_api_key()
    if key:
        print(key)
        sys.exit(0)
    else:
        sys.exit(1)
except Exception as e:
    sys.exit(1)
EOF
}

# Mask API key for display (show last 5 characters)
mask_api_key() {
    local key="$1"
    local key_length=${#key}

    if [[ $key_length -le 5 ]]; then
        echo "$key"  # Too short to mask
    else
        echo "...${key: -5}"
    fi
}

# Prompt user if they want to use existing key
prompt_use_existing_key() {
    local key_type="$1"  # "USPTO" or "Mistral"
    local masked_key="$2"

    echo ""
    echo -e "${GREEN}✓ Detected existing $key_type API key in secure storage${NC}"
    echo -e "  Key (masked): ${masked_key}"
    echo ""
    read -p "Would you like to use this existing key? (Y/n): " USE_EXISTING
    USE_EXISTING=${USE_EXISTING:-Y}

    if [[ "$USE_EXISTING" =~ ^[Yy]$ ]]; then
        return 0  # Use existing
    else
        return 1  # Don't use existing
    fi
}

# Securely read API key (no echo to terminal)
read_api_key_secure() {
    local prompt="$1"
    local varname="$2"

    read -s -p "$prompt: " $varname
    echo  # Newline after hidden input
}

# Prompt for API key with validation loop (with existing key detection)
prompt_and_validate_uspto_key() {
    local key=""
    local max_attempts=3
    local attempt=0

    # STEP 1: Check if key already exists in secure storage
    if check_existing_uspto_key; then
        echo -e "${YELLOW}ℹ Checking existing USPTO API key from another USPTO MCP installation...${NC}"

        # Try to load the existing key
        local existing_key=$(load_existing_uspto_key)
        if [[ $? -eq 0 && -n "$existing_key" ]]; then
            # Mask the key for display
            local masked_key=$(mask_api_key "$existing_key")

            # Ask user if they want to use it
            if prompt_use_existing_key "USPTO" "$masked_key"; then
                echo -e "${GREEN}✓ Using existing USPTO API key from secure storage${NC}"
                echo "$existing_key"
                return 0
            else
                echo -e "${YELLOW}ℹ You chose to enter a new USPTO API key${NC}"
                echo -e "${RED}⚠ This will OVERWRITE the existing key for ALL USPTO MCPs${NC}"
                read -p "Are you sure you want to continue? (y/N): " CONFIRM_OVERWRITE
                if [[ ! "$CONFIRM_OVERWRITE" =~ ^[Yy]$ ]]; then
                    echo -e "${GREEN}ℹ Keeping existing key${NC}"
                    echo "$existing_key"
                    return 0
                fi
            fi
        else
            echo -e "${YELLOW}⚠ Existing key file found but could not load (may be corrupted)${NC}"
            echo -e "${YELLOW}ℹ You will need to enter a new key${NC}"
        fi
    fi

    # STEP 2: Prompt for new key (either no existing key, or user wants to override)
    while [[ $attempt -lt $max_attempts ]]; do
        ((attempt++))

        read_api_key_secure "Enter your USPTO API key" key

        if [[ -z "$key" ]]; then
            echo -e "${RED}ERROR: USPTO API key cannot be empty${NC}"
            if [[ $attempt -lt $max_attempts ]]; then
                echo -e "${YELLOW}Attempt $attempt of $max_attempts${NC}"
            fi
            continue
        fi

        if validate_uspto_api_key "$key"; then
            # Success - return key via echo
            echo "$key"
            return 0
        else
            if [[ $attempt -lt $max_attempts ]]; then
                echo -e "${YELLOW}Attempt $attempt of $max_attempts - please try again${NC}"
                echo -e "${YELLOW}USPTO API key format: 30 lowercase letters (a-z)${NC}"
            fi
        fi
    done

    echo -e "${RED}ERROR: Failed to provide valid USPTO API key after $max_attempts attempts${NC}"
    return 1
}

# Prompt for Mistral API key with validation loop (optional, with existing key detection)
prompt_and_validate_mistral_key() {
    local key=""
    local max_attempts=3
    local attempt=0

    # STEP 1: Check if key already exists in secure storage
    if check_existing_mistral_key; then
        echo -e "${YELLOW}ℹ Checking existing Mistral API key from another USPTO MCP installation...${NC}"

        # Try to load the existing key
        local existing_key=$(load_existing_mistral_key)
        if [[ $? -eq 0 && -n "$existing_key" ]]; then
            # Mask the key for display
            local masked_key=$(mask_api_key "$existing_key")

            # Ask user if they want to use it
            if prompt_use_existing_key "Mistral" "$masked_key"; then
                echo -e "${GREEN}✓ Using existing Mistral API key from secure storage${NC}"
                echo "$existing_key"
                return 0
            else
                echo -e "${YELLOW}ℹ You chose to enter a new Mistral API key${NC}"
                echo -e "${RED}⚠ This will OVERWRITE the existing key for ALL USPTO MCPs${NC}"
                read -p "Are you sure you want to continue? (y/N): " CONFIRM_OVERWRITE
                if [[ ! "$CONFIRM_OVERWRITE" =~ ^[Yy]$ ]]; then
                    echo -e "${GREEN}ℹ Keeping existing key${NC}"
                    echo "$existing_key"
                    return 0
                fi
            fi
        else
            echo -e "${YELLOW}⚠ Existing key file found but could not load (may be corrupted)${NC}"
            echo -e "${YELLOW}ℹ You will need to enter a new key${NC}"
        fi
    fi

    # STEP 2: Prompt for new key (either no existing key, or user wants to override)
    echo -e "${YELLOW}ℹ Mistral API key is OPTIONAL (for OCR on scanned documents)${NC}"
    echo -e "${YELLOW}ℹ Press Enter to skip, or enter your 32-character Mistral API key${NC}"
    echo

    while [[ $attempt -lt $max_attempts ]]; do
        ((attempt++))

        read_api_key_secure "Enter your Mistral API key (or press Enter to skip)" key

        # Empty is OK (optional)
        if [[ -z "$key" ]]; then
            echo -e "${YELLOW}ℹ Skipping Mistral API key (OCR disabled)${NC}"
            echo ""  # Return empty string
            return 0
        fi

        if validate_mistral_api_key "$key"; then
            # Success - return key
            echo "$key"
            return 0
        else
            if [[ $attempt -lt $max_attempts ]]; then
                echo -e "${YELLOW}Attempt $attempt of $max_attempts - please try again${NC}"
                echo -e "${YELLOW}Mistral API key format: 32 alphanumeric characters (a-z, A-Z, 0-9)${NC}"
            fi
        fi
    done

    echo -e "${RED}ERROR: Failed to provide valid Mistral API key after $max_attempts attempts${NC}"
    return 1
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
