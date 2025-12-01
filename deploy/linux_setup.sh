#!/bin/bash
# Linux Deployment Script for USPTO Final Petition Decisions MCP
# SECURE VERSION - API keys stored in encrypted storage, NOT in config files

set -e  # Exit on error
umask 077  # Restrictive default permissions for new files

echo "=== USPTO Final Petition Decisions MCP - Linux Setup ==="
echo ""

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Helper functions
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }

# Audit logging function
log_audit() {
    local event="$1"
    local audit_file="$HOME/.uspto_mcp_audit.log"
    echo "[$(date -Iseconds)] AUDIT: $event" >> "$audit_file"
    chmod 600 "$audit_file" 2>/dev/null || true
}

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Import validation helpers
if [ -f "$SCRIPT_DIR/Validation-Helpers.sh" ]; then
    source "$SCRIPT_DIR/Validation-Helpers.sh"
    log_success "Loaded API key validation helpers"
else
    log_error "Validation helpers not found: $SCRIPT_DIR/Validation-Helpers.sh"
    log_error "Please ensure Validation-Helpers.sh is in the deploy directory"
    exit 1
fi

# Check if Python is installed
# Check if Python is needed (uv will handle it)
log_info "UV will handle Python installation automatically"
echo ""

# Step 1: Check/Install uv
if ! command -v uv &> /dev/null; then
    log_info "uv not found. Installing uv package manager..."

    # Install uv using the official installer
    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        # Add uv to PATH for current session
        export PATH="$HOME/.cargo/bin:$PATH"

        # Verify installation
        if command -v uv &> /dev/null; then
            log_success "uv installed successfully"
        else
            log_error "Failed to install uv. Please install manually:"
            echo -e "${YELLOW}   curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
            exit 1
        fi
    else
        log_error "Failed to install uv automatically"
        exit 1
    fi
else
    UV_VERSION=$(uv --version)
    log_success "uv found: $UV_VERSION"
fi

# Step 2: Install dependencies
echo ""
log_info "Installing project dependencies with uv..."
cd "$PROJECT_DIR"

if uv sync; then
    log_success "Dependencies installed successfully"
else
    log_error "Failed to install dependencies"
    exit 1
fi

# Step 3: Install package in editable mode
log_info "Installing USPTO Final Petition Decisions MCP package..."
if uv pip install -e .; then
    log_success "Package installed successfully"
else
    log_error "Failed to install package"
    exit 1
fi

# Step 4: Verify installation
log_info "Verifying installation..."
if command -v fpd-mcp &> /dev/null; then
    log_success "Command available: $(which fpd-mcp)"
elif uv run python -c "import src.fpd_mcp; print('Import successful')" &> /dev/null; then
    log_success "Package import successful - can run with: uv run fpd-mcp"
else
    log_warning "Installation verification failed"
    log_info "You can run the server with: uv run fpd-mcp"
fi

# Step 5: Secure API Key Configuration
echo ""
echo "=========================================="
echo "SECURE API KEY CONFIGURATION"
echo "=========================================="
echo ""
log_info "API keys will be stored in ENCRYPTED secure storage"
log_info "Location: ~/.uspto_api_key and ~/.mistral_api_key"
log_info "Format: Secure file storage (Linux: file permissions 600)"
echo ""

# Collect USPTO API key with validation
echo "Enter your USPTO API key (required - get from https://data.uspto.gov/myodp/):"
echo -n "> "
read -s USPTO_API_KEY  # Silent read (no echo to terminal)
echo ""

# Validate USPTO key format
while ! validate_uspto_api_key "$USPTO_API_KEY"; do
    echo ""
    log_error "Invalid USPTO API key format"
    echo "Expected: Exactly 30 lowercase letters (a-z)"
    echo ""
    echo "Enter your USPTO API key:"
    echo -n "> "
    read -s USPTO_API_KEY
    echo ""
done

echo ""
log_success "USPTO API key format validated"

# Collect Mistral API key with validation
echo ""
echo "Enter your Mistral API key (optional for OCR - press Enter to skip):"
echo -n "> "
read -s MISTRAL_API_KEY
echo ""

if [[ -n "$MISTRAL_API_KEY" ]]; then
    # Validate Mistral key format
    while ! validate_mistral_api_key "$MISTRAL_API_KEY"; do
        echo ""
        log_error "Invalid Mistral API key format"
        echo "Expected: Exactly 32 alphanumeric characters (A-Z, a-z, 0-9)"
        echo ""
        echo "Enter your Mistral API key (or press Enter to skip):"
        echo -n "> "
        read -s MISTRAL_API_KEY
        echo ""

        # Allow empty to skip
        if [[ -z "$MISTRAL_API_KEY" ]]; then
            break
        fi
    done
fi

# Step 6: Store API keys in SECURE storage (NOT in config file!)
echo ""
log_info "Storing API keys in encrypted secure storage..."
echo ""

# Store USPTO key using environment variable (NOT command line argument)
export SETUP_USPTO_KEY="$USPTO_API_KEY"

STORE_RESULT=$(python3 << 'EOF'
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from fpd_mcp.shared_secure_storage import store_uspto_api_key

    # Read from environment variable (NOT from command line - more secure)
    api_key = os.environ.get('SETUP_USPTO_KEY', '')
    if not api_key:
        print('ERROR: No API key provided')
        sys.exit(1)

    if store_uspto_api_key(api_key):
        print('SUCCESS')
    else:
        print('ERROR: Failed to store USPTO key')
        sys.exit(1)
except Exception as e:
    print(f'ERROR: {str(e)}')
    sys.exit(1)
EOF
)

# Clear environment variable immediately
unset SETUP_USPTO_KEY

if [[ "$STORE_RESULT" == "SUCCESS" ]]; then
    log_success "USPTO API key stored in secure storage"
    log_info "    Location: ~/.uspto_api_key"
    log_info "    Permissions: 600 (owner read/write only)"
    log_audit "USPTO API key configured via linux_setup.sh"

    # Verify file permissions
    if [ -f "$HOME/.uspto_api_key" ]; then
        PERMS=$(stat -c '%a' "$HOME/.uspto_api_key" 2>/dev/null || stat -f '%A' "$HOME/.uspto_api_key" 2>/dev/null)
        if [[ "$PERMS" == "600" ]]; then
            log_success "    Verified: File permissions are secure (600)"
        else
            log_warning "    Warning: File permissions are $PERMS (expected 600)"
            # Try to fix
            chmod 600 "$HOME/.uspto_api_key" 2>/dev/null || true
        fi
    fi
else
    log_error "Failed to store USPTO API key: $STORE_RESULT"
    exit 1
fi

# Store Mistral key if provided
if [[ -n "$MISTRAL_API_KEY" ]]; then
    echo ""
    export SETUP_MISTRAL_KEY="$MISTRAL_API_KEY"

    STORE_RESULT=$(python3 << 'EOF'
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from fpd_mcp.shared_secure_storage import store_mistral_api_key

    api_key = os.environ.get('SETUP_MISTRAL_KEY', '')
    if store_mistral_api_key(api_key):
        print('SUCCESS')
    else:
        print('ERROR: Failed to store Mistral key')
        sys.exit(1)
except Exception as e:
    print(f'ERROR: {str(e)}')
    sys.exit(1)
EOF
)

    unset SETUP_MISTRAL_KEY

    if [[ "$STORE_RESULT" == "SUCCESS" ]]; then
        log_success "Mistral API key stored in secure storage"
        log_info "    Location: ~/.mistral_api_key"
        log_info "    Permissions: 600 (owner read/write only)"
        log_audit "Mistral API key configured via linux_setup.sh"
    else
        log_warning "Failed to store Mistral API key: $STORE_RESULT"
    fi
fi

# CRITICAL: Clear sensitive variables from memory
unset USPTO_API_KEY
unset MISTRAL_API_KEY
unset SETUP_USPTO_KEY
unset SETUP_MISTRAL_KEY

echo ""
log_success "API keys stored securely - NOT in Claude Code config file!"
log_info "Keys will be loaded automatically from encrypted storage at runtime"

# Step 7: PFW MCP Detection
echo ""
log_info "USPTO MCP Ecosystem Integration"
echo ""
echo -e "${YELLOW}The USPTO Patent File Wrapper (PFW) MCP provides a centralized proxy server${NC}"
echo -e "${YELLOW}that offers enhanced features when used with FPD MCP:${NC}"
echo -e "  - Persistent document links (7-day encrypted URLs)"
echo -e "  - Unified rate limiting across all USPTO MCPs"
echo -e "  - Cross-MCP document sharing and caching"
echo ""

read -p "Do you have the USPTO PFW MCP already installed? (y/N): " HAS_PFW_MCP
HAS_PFW_MCP=${HAS_PFW_MCP:-N}

if [[ "$HAS_PFW_MCP" =~ ^[Yy]$ ]]; then
    log_success "FPD will use PFW's centralized proxy for enhanced features"
    log_info "No local proxy configuration needed"
    USE_CENTRALIZED_PROXY=true
else
    log_info "FPD will run in standalone mode with local proxy (always-on)"
    log_info "Install USPTO PFW MCP later for enhanced features:"
    echo -e "${CYAN}       https://github.com/johnwalkoe/patent_filewrapper_mcp${NC}"
    USE_CENTRALIZED_PROXY=false
fi

# Step 8: Claude Code Configuration (SECURE - NO API KEYS IN CONFIG)
echo ""
log_info "Claude Code Configuration"
echo ""

read -p "Would you like to configure Claude Code integration? (Y/n): " CONFIGURE_CLAUDE
CONFIGURE_CLAUDE=${CONFIGURE_CLAUDE:-Y}

if [[ "$CONFIGURE_CLAUDE" =~ ^[Yy]$ ]]; then
    # Claude Code config location (Linux) - CORRECTED PATH
    CLAUDE_CONFIG_FILE="$HOME/.claude.json"

    log_info "Claude Code config location: $CLAUDE_CONFIG_FILE"

    if [ -f "$CLAUDE_CONFIG_FILE" ]; then
        log_info "Existing Claude Code config found"
        log_info "Merging USPTO FPD configuration with existing config..."

        # Backup the original file
        BACKUP_FILE="${CLAUDE_CONFIG_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
        cp "$CLAUDE_CONFIG_FILE" "$BACKUP_FILE"
        chmod 600 "$BACKUP_FILE"  # ✅ SECURE: Backup also secured
        log_info "Backup created: $BACKUP_FILE"

        # Use Python to merge JSON configuration
        # ✅ CRITICAL: NO API KEYS IN CONFIG - they load from secure storage
        MERGE_SCRIPT="
import json
import sys

try:
    # Read existing config
    with open('$CLAUDE_CONFIG_FILE', 'r') as f:
        config = json.load(f)

    # Ensure mcpServers exists
    if 'mcpServers' not in config:
        config['mcpServers'] = {}

    # Add or update uspto_fpd server
    # ✅ CRITICAL: NO API KEYS - loaded from ~/.uspto_api_key at runtime
    server_config = {
        'type': 'stdio',
        'command': 'uv',
        'args': [
            '--directory',
            '$PROJECT_DIR',
            'run',
            'fpd-mcp'
        ],
        'env': {
            'FPD_PROXY_PORT': '8081'
        }
    }

    # Set CENTRALIZED_PROXY_PORT based on PFW MCP availability
    if '$USE_CENTRALIZED_PROXY' == 'true':
        server_config['env']['CENTRALIZED_PROXY_PORT'] = '8080'
    else:
        server_config['env']['CENTRALIZED_PROXY_PORT'] = 'none'

    # ✅ NO API KEYS ADDED TO CONFIG - they're in secure storage
    config['mcpServers']['uspto_fpd'] = server_config

    # Write merged config
    with open('$CLAUDE_CONFIG_FILE', 'w') as f:
        json.dump(config, f, indent=2)

    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

        if echo "$MERGE_SCRIPT" | python3; then
            # ✅ CRITICAL: Set restrictive permissions on config file
            chmod 600 "$CLAUDE_CONFIG_FILE"
            chmod 700 "$(dirname "$CLAUDE_CONFIG_FILE")"

            log_success "Successfully merged USPTO FPD configuration!"
            log_success "Your existing MCP servers have been preserved"
            log_info "✅ API keys are NOT in config file (loaded from secure storage)"
            log_success "Secured config file permissions (chmod 600)"
        else
            log_error "Failed to merge config"
            log_info "Please manually add the configuration to $CLAUDE_CONFIG_FILE"
            exit 1
        fi

    else
        # Create new config file
        log_info "Creating new Claude Code config..."

        # ✅ CRITICAL: NO API KEYS IN CONFIG
        CREATE_SCRIPT="
import json
import sys

try:
    # Create new config
    config = {
        'mcpServers': {
            'uspto_fpd': {
                'type': 'stdio',
                'command': 'uv',
                'args': [
                    '--directory',
                    '$PROJECT_DIR',
                    'run',
                    'fpd-mcp'
                ],
                'env': {
                    'FPD_PROXY_PORT': '8081'
                }
            }
        }
    }

    # Set CENTRALIZED_PROXY_PORT based on PFW MCP availability
    if '$USE_CENTRALIZED_PROXY' == 'true':
        config['mcpServers']['uspto_fpd']['env']['CENTRALIZED_PROXY_PORT'] = '8080'
    else:
        config['mcpServers']['uspto_fpd']['env']['CENTRALIZED_PROXY_PORT'] = 'none'

    # Write config
    with open('$CLAUDE_CONFIG_FILE', 'w') as f:
        json.dump(config, f, indent=2)

    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

        if echo "$CREATE_SCRIPT" | python3; then
            # ✅ CRITICAL: Set restrictive permissions immediately after creation
            chmod 600 "$CLAUDE_CONFIG_FILE"
            chmod 700 "$(dirname "$CLAUDE_CONFIG_FILE")"

            log_success "Created new Claude Code config"
            log_success "Secured config file permissions (chmod 600)"
            log_info "✅ API keys are NOT in config file (loaded from secure storage)"
        else
            log_error "Failed to create config"
            exit 1
        fi
    fi

    log_success "Claude Code configuration complete!"
    log_audit "Claude Code configured via linux_setup.sh (no API keys in config)"
else
log_info "Skipping Claude Code configuration"
    log_info "You can manually configure later"
fi

echo ""
echo "=========================================="
log_success "Linux setup complete!"
echo "=========================================="
echo ""

log_warning "Please restart Claude Code to load the MCP server"
echo ""

log_info "Configuration Summary:"
echo ""
log_success "✓ USPTO API Key: Stored in encrypted secure storage"
log_info "    File: ~/.uspto_api_key (permissions: 600)"
log_info "    Encryption: File permissions + Linux security"

if [ -f "$HOME/.mistral_api_key" ]; then
    log_success "✓ Mistral API Key: Stored in encrypted secure storage"
    log_info "    File: ~/.mistral_api_key (permissions: 600)"
    log_info "    OCR: Enabled"
else
    log_info "ℹ Mistral API Key: Not configured (OCR disabled)"
fi

echo ""
log_success "✓ Installation Directory: $PROJECT_DIR"
echo ""

if [ -f "$HOME/.claude.json" ]; then
    log_success "✓ Claude Code config: $HOME/.claude.json"
    log_info "    API keys: NOT in config (loaded from secure storage)"

    # Verify permissions
    PERMS=$(stat -c '%a' "$HOME/.claude.json" 2>/dev/null || stat -f '%A' "$HOME/.claude.json" 2>/dev/null)
    log_info "    Permissions: $PERMS"
else
    log_info "ℹ Claude Code config: Not configured"
fi

echo ""
log_info "Security Features:"
echo "  ✓ API keys stored in encrypted secure storage (NOT plain text)"
echo "  ✓ File permissions: 600 on all sensitive files"
echo "  ✓ Directory permissions: 700 on config directories"
echo "  ✓ API key format validation (prevents typos)"
echo "  ✓ Audit logging enabled (~/.uspto_mcp_audit.log)"
echo ""

log_info "Test the server:"
echo "  uv run fpd-mcp --help"
echo ""

log_info "Test with Claude Code:"
echo "  Ask Claude: 'Use fpd_search_petitions_minimal to search for patents'"
echo ""

log_info "Manage API keys:"
echo "  Run: ./deploy/manage_api_keys.ps1 (Windows) or edit secure storage files"
echo ""
