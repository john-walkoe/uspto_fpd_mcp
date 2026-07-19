# Windows Deployment Script for USPTO Final Petition Decisions MCP
# SECURE VERSION - API keys stored in DPAPI encrypted storage, NOT in config files

Write-Host "=== USPTO Final Petition Decisions MCP - Windows Setup ===" -ForegroundColor Green
Write-Host ""

# Get project directory
$ProjectDir = Get-Location

# Import validation helpers
$ValidationModule = Join-Path $PSScriptRoot "Validation-Helpers.psm1"
if (Test-Path $ValidationModule) {
    Import-Module $ValidationModule -Force
    Write-Host "[OK] Loaded API key validation helpers" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Validation helpers not found: $ValidationModule" -ForegroundColor Red
    Write-Host "        Please ensure Validation-Helpers.psm1 is in the deploy directory" -ForegroundColor Yellow
    exit 1
}

# Audit logging function
function Write-AuditLog {
    param([string]$Event)

    $auditFile = Join-Path $env:USERPROFILE ".uspto_mcp_audit.log"
    $timestamp = Get-Date -Format "o"
    Add-Content -Path $auditFile -Value "[$timestamp] AUDIT: $Event"

    # Secure the audit log (best-effort, requires admin privileges)
    if (Test-Path $auditFile) {
        try {
            $acl = Get-Acl $auditFile
            $acl.SetAccessRuleProtection($true, $false)
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
                "FullControl",
                "Allow"
            )
            $acl.SetAccessRule($rule)
            Set-Acl $auditFile $acl -ErrorAction Stop
        }
        catch {
            # Silently ignore if we don't have SeSecurityPrivilege (requires admin)
            # Audit log will still work, just without restricted ACL
        }
    }
}

# SECURE: Unified secure storage functions using ENVIRONMENT VARIABLES
function Set-UnifiedUsptoKey {
    <#
    .SYNOPSIS
    Securely stores USPTO API key using DPAPI encryption

    .DESCRIPTION
    Stores the USPTO API key in encrypted storage using environment variables
    to pass the key to Python (NOT visible in process list)
    #>
    param([string]$ApiKey)

    try {
        Set-Location $ProjectDir

        # ✅ SECURE: Use environment variable (NOT embedded in command)
        $env:TEMP_USPTO_API_KEY = $ApiKey

        $result = uv run python -c "
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))

try:
    from fpd_mcp.shared_secure_storage import store_uspto_api_key

    # Read from environment variable (NOT from command line)
    api_key = os.environ.get('TEMP_USPTO_API_KEY', '')
    if not api_key:
        print('ERROR: No API key provided')
        sys.exit(1)

    success = store_uspto_api_key(api_key)
    print('SUCCESS' if success else 'FAILED')
except Exception as e:
    print(f'ERROR: {str(e)}')
    sys.exit(1)
" 2>&1 | Out-String

        # ✅ CRITICAL: Clear environment variable immediately
        Remove-Item Env:TEMP_USPTO_API_KEY -ErrorAction SilentlyContinue

        # Parse result - get last non-empty line (uv may output diagnostic messages to stderr)
        $lines = $result -split "`n" | Where-Object { $_.Trim() -ne "" }
        $lastLine = if ($lines.Count -gt 0) { ([string]$lines[-1]).Trim() } else { "" }

        if ($lastLine -eq "SUCCESS") {
            Write-Host "[OK] USPTO API key stored in DPAPI encrypted storage" -ForegroundColor Green
            Write-Host "     Location: ~/.uspto_api_key (DPAPI encrypted)" -ForegroundColor Yellow

            # ✅ SECURE: Mark file as hidden
            $keyFile = Join-Path $env:USERPROFILE ".uspto_api_key"
            if (Test-Path $keyFile) {
                attrib +H "$keyFile"
                Write-Host "     File marked as hidden" -ForegroundColor Yellow
            }

            # Log audit event
            Write-AuditLog "USPTO API key stored via windows_setup.ps1"

            return $true
        } else {
            Write-Host "[ERROR] Failed to store USPTO API key: $result" -ForegroundColor Red
            return $false
        }
    }
    catch {
        # Clear environment variable on error too
        Remove-Item Env:TEMP_USPTO_API_KEY -ErrorAction SilentlyContinue
        Write-Host "[ERROR] Failed to store USPTO API key: $_" -ForegroundColor Red
        return $false
    }
}

function Set-UnifiedMistralKey {
    <#
    .SYNOPSIS
    Securely stores Mistral API key using DPAPI encryption

    .DESCRIPTION
    Stores the Mistral API key in encrypted storage using environment variables
    to pass the key to Python (NOT visible in process list)
    #>
    param([string]$ApiKey)

    try {
        Set-Location $ProjectDir

        # ✅ SECURE: Use environment variable (NOT embedded in command)
        $env:TEMP_MISTRAL_API_KEY = $ApiKey

        $result = uv run python -c "
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))

try:
    from fpd_mcp.shared_secure_storage import store_mistral_api_key

    # Read from environment variable (NOT from command line)
    api_key = os.environ.get('TEMP_MISTRAL_API_KEY', '')
    if not api_key:
        print('ERROR: No API key provided')
        sys.exit(1)

    success = store_mistral_api_key(api_key)
    print('SUCCESS' if success else 'FAILED')
except Exception as e:
    print(f'ERROR: {str(e)}')
    sys.exit(1)
" 2>&1 | Out-String

        # ✅ CRITICAL: Clear environment variable immediately
        Remove-Item Env:TEMP_MISTRAL_API_KEY -ErrorAction SilentlyContinue

        # Parse result - get last non-empty line (uv may output diagnostic messages to stderr)
        $lines = $result -split "`n" | Where-Object { $_.Trim() -ne "" }
        $lastLine = if ($lines.Count -gt 0) { ([string]$lines[-1]).Trim() } else { "" }

        if ($lastLine -eq "SUCCESS") {
            Write-Host "[OK] Mistral API key stored in DPAPI encrypted storage" -ForegroundColor Green
            Write-Host "     Location: ~/.mistral_api_key (DPAPI encrypted)" -ForegroundColor Yellow

            # ✅ SECURE: Mark file as hidden
            $keyFile = Join-Path $env:USERPROFILE ".mistral_api_key"
            if (Test-Path $keyFile) {
                attrib +H "$keyFile"
                Write-Host "     File marked as hidden" -ForegroundColor Yellow
            }

            # Log audit event
            Write-AuditLog "Mistral API key stored via windows_setup.ps1"

            return $true
        } else {
            Write-Host "[ERROR] Failed to store Mistral API key: $result" -ForegroundColor Red
            return $false
        }
    }
    catch {
        # Clear environment variable on error too
        Remove-Item Env:TEMP_MISTRAL_API_KEY -ErrorAction SilentlyContinue
        Write-Host "[ERROR] Failed to store Mistral API key: $_" -ForegroundColor Red
        return $false
    }
}

function Test-UnifiedKeys {
    <#
    .SYNOPSIS
    Tests if API keys exist in secure storage

    .DESCRIPTION
    Checks for the presence of USPTO and Mistral API keys in encrypted storage
    #>
    try {
        Set-Location $ProjectDir
        $result = uv run python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))

try:
    from fpd_mcp.shared_secure_storage import UnifiedSecureStorage

    storage = UnifiedSecureStorage()
    uspto_key = storage.get_uspto_key()
    mistral_key = storage.get_mistral_key()

    print(f'USPTO:{'YES' if uspto_key and len(uspto_key) >= 10 else 'NO'}')
    print(f'MISTRAL:{'YES' if mistral_key and len(mistral_key) >= 10 else 'NO'}')
except Exception as e:
    print(f'ERROR: {str(e)}')
    sys.exit(1)
" 2>&1 | Out-String

        $lines = $result -split "`n" | Where-Object { $_.Trim() -ne "" }
        $usptoFound = $false
        $mistralFound = $false

        foreach ($line in $lines) {
            if ($line -match "USPTO:(YES|NO)") {
                $usptoFound = ($matches[1] -eq "YES")
            }
            if ($line -match "MISTRAL:(YES|NO)") {
                $mistralFound = ($matches[1] -eq "YES")
            }
        }

        return @{
            "USPTO" = $usptoFound
            "MISTRAL" = $mistralFound
        }
    }
    catch {
        return @{
            "USPTO" = $false
            "MISTRAL" = $false
        }
    }
}

# Check if uv is installed, install if not
Write-Host "[INFO] Python NOT required - uv will manage Python automatically" -ForegroundColor Cyan
Write-Host ""
try {
    $uvVersion = uv --version 2>$null
    Write-Host "[OK] uv found: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "[INFO] uv not found. Installing uv..." -ForegroundColor Yellow

    # Try winget first (preferred method)
    try {
        winget install --id=astral-sh.uv -e
        Write-Host "[OK] uv installed via winget" -ForegroundColor Green
    } catch {
        Write-Host "[INFO] winget failed, trying PowerShell install method..." -ForegroundColor Yellow
        try {
            powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
            Write-Host "[OK] uv installed via PowerShell script" -ForegroundColor Green
        } catch {
            Write-Host "[ERROR] Failed to install uv. Please install manually:" -ForegroundColor Red
            Write-Host "   winget install --id=astral-sh.uv -e" -ForegroundColor Yellow
            Write-Host "   OR visit: https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Yellow
            exit 1
        }
    }

    # Refresh PATH for current session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")

    # Add uv's typical installation paths if not already in PATH
    $uvPaths = @(
        "$env:USERPROFILE\.cargo\bin",           # cargo install location
        "$env:LOCALAPPDATA\Programs\uv\bin",      # winget install location
        "$env:APPDATA\uv\bin"                     # alternative location
    )

    foreach ($uvPath in $uvPaths) {
        if (Test-Path $uvPath) {
            if ($env:PATH -notlike "*$uvPath*") {
                $env:PATH = "$uvPath;$env:PATH"
                Write-Host "[INFO] Added $uvPath to PATH" -ForegroundColor Yellow
            }
        }
    }

    # Verify uv is now accessible
    try {
        $uvVersion = uv --version 2>$null
        Write-Host "[OK] uv is now accessible: $uvVersion" -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] uv installed but not accessible. Please restart PowerShell and run script again." -ForegroundColor Red
        Write-Host "[INFO] Or manually add uv to PATH and continue." -ForegroundColor Yellow
        exit 1
    }
}

# Install dependencies with uv
Write-Host "[INFO] Installing dependencies with uv..." -ForegroundColor Yellow

# Force uv to use prebuilt wheels (avoid Rust compilation)
Write-Host "[INFO] Installing dependencies with prebuilt wheels (Python 3.12)..." -ForegroundColor Yellow

try {
    # Use Python 3.12 which has guaranteed prebuilt wheels for all dependencies
    # Python 3.14 is too new and doesn't have wheels yet
    uv sync --python 3.12
    Write-Host "[OK] Dependencies installed" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Fix: Ensure pyvenv.cfg exists (required for secure storage on older uv versions)
$pyvenvCfgPath = ".venv\pyvenv.cfg"
if (-not (Test-Path $pyvenvCfgPath)) {
    Write-Host "[INFO] Creating missing pyvenv.cfg file (older uv version)..." -ForegroundColor Yellow
    try {
        # Get the Python path that uv is using
        $uvPythonInfo = uv python list --only-managed 2>$null | Select-String "cpython-3\.1[2-4].*-windows" | Select-Object -First 1
        if ($uvPythonInfo) {
            $pythonVersion = ($uvPythonInfo.Line -split '\s+')[1]  # Extract version like "3.12.8"
            $pythonPath = ($uvPythonInfo.Line -split '\s+')[2]    # Extract path

            # Create pyvenv.cfg content
            $pyvenvContent = @"
home = $pythonPath
implementation = CPython
uv = 0.9.11
version_info = $pythonVersion
include-system-site-packages = false
prompt = uspto-fpd-mcp
"@
            Set-Content -Path $pyvenvCfgPath -Value $pyvenvContent -Encoding UTF8
            Write-Host "[OK] Created pyvenv.cfg file" -ForegroundColor Green
        } else {
            # Fallback: Create minimal pyvenv.cfg
            Write-Host "[WARN] Could not detect uv Python path, creating minimal pyvenv.cfg" -ForegroundColor Yellow
            $fallbackContent = @"
implementation = CPython
version_info = 3.12.8
include-system-site-packages = false
prompt = uspto-fpd-mcp
"@
            Set-Content -Path $pyvenvCfgPath -Value $fallbackContent -Encoding UTF8
            Write-Host "[OK] Created minimal pyvenv.cfg file" -ForegroundColor Green
        }
    } catch {
        Write-Host "[WARN] Could not create pyvenv.cfg, but continuing..." -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] pyvenv.cfg already exists (newer uv version)" -ForegroundColor Green
}

# Verify installation
Write-Host "[INFO] Verifying installation..." -ForegroundColor Yellow
try {
    $commandCheck = Get-Command fpd-mcp -ErrorAction SilentlyContinue
    if ($commandCheck) {
        Write-Host "[OK] Command available: $($commandCheck.Source)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Warning: Command verification failed - check PATH" -ForegroundColor Yellow
        Write-Host "[INFO] You can run the server with: uv run fpd-mcp" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[WARN] Warning: Command verification failed - check PATH" -ForegroundColor Yellow
    Write-Host "[INFO] You can run the server with: uv run fpd-mcp" -ForegroundColor Yellow
}

# API Key Configuration with Unified Storage
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "SECURE API KEY CONFIGURATION" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "API keys will be stored in DPAPI encrypted storage" -ForegroundColor Yellow
Write-Host "Location: ~/.uspto_api_key and ~/.mistral_api_key" -ForegroundColor Yellow
Write-Host "Encryption: Windows Data Protection API (user + machine specific)" -ForegroundColor Yellow
Write-Host ""

# Step 1: Check for existing keys first
Write-Host "[INFO] Checking for existing API keys in secure storage..." -ForegroundColor Yellow
$existingKeys = Test-UnifiedKeys

# Flags for tracking configuration path
$usingPreexistingDPAPI = $false
$newKeyAsEnv = $false
$finalConfigMethod = "none"  # Track final config method: "dpapi", "traditional", or "none"

# Test secure storage system ONLY if no keys exist yet (avoids deleting existing keys)
if (-not $existingKeys.USPTO -and -not $existingKeys.MISTRAL) {
    Write-Host "[INFO] Testing secure storage system..." -ForegroundColor Yellow
    try {
        $pythonExe = ".venv/Scripts/python.exe"
        $testCode = @"
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))

try:
    from fpd_mcp.shared_secure_storage import UnifiedSecureStorage
    storage = UnifiedSecureStorage()
    test_result = storage.store_uspto_key('testkey12345678901234567890')
    storage.uspto_key_path.unlink(missing_ok=True)  # Clean up test - safe because no real keys exist yet
    print('SUCCESS' if test_result else 'FAILED')
except Exception as e:
    print(f'ERROR: {e}')
"@

        $storageResult = & $pythonExe -c $testCode 2>$null | Out-String
        if ($storageResult -match "SUCCESS") {
            Write-Host "[OK] Secure storage system working" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Secure storage test failed - API key storage may not work properly" -ForegroundColor Yellow
            Write-Host "[INFO] Error details: $storageResult" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[WARN] Could not test secure storage system" -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] Secure storage system verified (existing keys found)" -ForegroundColor Green
}

# Step 2: Ask user to use existing or update
if ($existingKeys.USPTO -and $existingKeys.MISTRAL) {
    Write-Host "[OK] Both USPTO and Mistral API keys found in encrypted storage" -ForegroundColor Green
    Write-Host "[INFO] Configuration: [1] Use existing keys [2] Update keys" -ForegroundColor Cyan
    $keyChoice = Read-Host "Enter choice (1 or 2, default is 1)"

    if ($keyChoice -eq "2") {
        $updateKeys = $true
    } else {
        $updateKeys = $false
        $usingPreexistingDPAPI = $true  # Flag: Using existing DPAPI keys
        Write-Host "[OK] Using existing encrypted API keys" -ForegroundColor Green
    }
} elseif ($existingKeys.USPTO) {
    Write-Host "[OK] USPTO API key found in encrypted storage" -ForegroundColor Green
    Write-Host "[INFO] Mistral API key not found" -ForegroundColor Yellow
    Write-Host "[INFO] Configuration: [1] Add Mistral key [2] Use USPTO key only [3] Update both keys" -ForegroundColor Cyan
    $keyChoice = Read-Host "Enter choice (1, 2, or 3, default is 1)"

    if ($keyChoice -eq "2") {
        $updateKeys = $false
        $usingPreexistingDPAPI = $true  # Flag: Using existing USPTO DPAPI key
        Write-Host "[OK] Using existing USPTO key, skipping Mistral" -ForegroundColor Green
    } elseif ($keyChoice -eq "3") {
        $updateKeys = $true
    } else {
        $updateKeys = "mistral_only"
        # Note: Don't set $usingPreexistingDPAPI here because adding new Mistral key
    }
} elseif ($existingKeys.MISTRAL) {
    Write-Host "[WARN] Only Mistral API key found, USPTO key missing (required)" -ForegroundColor Yellow
    $updateKeys = $true
} else {
    Write-Host "[INFO] No API keys found in encrypted storage" -ForegroundColor Yellow
    $updateKeys = $true
}

# Step 3: Collect and store keys if needed
if ($updateKeys -eq $true -or $updateKeys -eq "mistral_only") {
    # Show API key format requirements
    Show-ApiKeyRequirements

    # Collect USPTO API key if needed (skip for mistral_only case)
    $usptoApiKey = ""
    if ($updateKeys -eq $true) {
        if ($existingKeys.USPTO) {
            Write-Host ""
            Write-Host "[INFO] USPTO API key already exists in encrypted storage" -ForegroundColor Yellow
            Write-Host ""
            $updateUspto = Read-Host "Do you want to update the USPTO API key? (y/N)"

            if ($updateUspto -eq "y" -or $updateUspto -eq "Y") {
                Write-Host ""
                Write-Host "Enter your USPTO API key (required - get from https://data.uspto.gov/myodp/):" -ForegroundColor Cyan
                Write-Host ""
                $usptoApiKey = Read-UsptoApiKeyWithValidation
                if (-not $usptoApiKey) {
                    Write-Host "[ERROR] Cannot proceed without valid USPTO API key" -ForegroundColor Red
                    exit 1
                }
            } else {
                Write-Host "[OK] Keeping existing USPTO API key" -ForegroundColor Green
            }
        } else {
            Write-Host ""
            Write-Host "Enter your USPTO API key (required - get from https://data.uspto.gov/myodp/):" -ForegroundColor Cyan
            Write-Host ""
            $usptoApiKey = Read-UsptoApiKeyWithValidation
            if (-not $usptoApiKey) {
                Write-Host "[ERROR] Cannot proceed without valid USPTO API key" -ForegroundColor Red
                exit 1
            }
        }
    }

    # Collect Mistral API key with validation (uses helper function with retry logic)
    $mistralApiKey = ""
    if ($updateKeys -eq "mistral_only") {
        # Special case: Only adding Mistral key, USPTO already exists
        Write-Host ""
        Write-Host "[INFO] Mistral API key is OPTIONAL (for OCR on scanned petition documents)" -ForegroundColor Yellow
        Write-Host "       Without it, you can still use free PyPDF2 extraction for text-based PDFs" -ForegroundColor Yellow
        Write-Host ""
        $mistralApiKey = Read-MistralApiKeyWithValidation
        if ($null -eq $mistralApiKey) {
            Write-Host "[ERROR] Mistral API key validation failed" -ForegroundColor Red
            exit 1
        }
    } elseif ($existingKeys.MISTRAL) {
        Write-Host ""
        Write-Host "[INFO] Mistral API key already exists in encrypted storage" -ForegroundColor Yellow
        Write-Host "[INFO] Mistral API key is OPTIONAL (for OCR on scanned petition documents)" -ForegroundColor Yellow
        Write-Host ""
        $updateMistral = Read-Host "Do you want to update the Mistral API key? (y/N)"

        if ($updateMistral -eq "y" -or $updateMistral -eq "Y") {
            Write-Host ""
            $mistralApiKey = Read-MistralApiKeyWithValidation
            if ($null -eq $mistralApiKey) {
                Write-Host "[ERROR] Mistral API key validation failed" -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host "[OK] Keeping existing Mistral API key" -ForegroundColor Green
        }
    } else {
        Write-Host ""
        Write-Host "[INFO] Mistral API key is OPTIONAL (for OCR on scanned petition documents)" -ForegroundColor Yellow
        Write-Host "       Without it, you can still use free PyPDF2 extraction for text-based PDFs" -ForegroundColor Yellow
        Write-Host ""

        $mistralApiKey = Read-MistralApiKeyWithValidation

        if ($null -eq $mistralApiKey) {
            Write-Host "[ERROR] Mistral API key validation failed" -ForegroundColor Red
            exit 1
        }
    }

    # Store keys in unified encrypted storage
    Write-Host ""
    Write-Host "[INFO] Storing API keys in DPAPI encrypted storage..." -ForegroundColor Yellow
    Write-Host ""

    if (-not [string]::IsNullOrWhiteSpace($usptoApiKey)) {
        if (Set-UnifiedUsptoKey -ApiKey $usptoApiKey) {
            Write-Host "[OK] USPTO API key stored in encrypted storage" -ForegroundColor Green
            $newKeyAsEnv = $true  # Flag: New key entered and stored
        } else {
            Write-Host "[ERROR] Failed to store USPTO API key" -ForegroundColor Red
            exit 1
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($mistralApiKey)) {
        if (Set-UnifiedMistralKey -ApiKey $mistralApiKey) {
            Write-Host "[OK] Mistral API key stored in encrypted storage" -ForegroundColor Green
            $newKeyAsEnv = $true  # Flag: New key entered and stored
        } else {
            Write-Host "[WARN] Failed to store Mistral API key" -ForegroundColor Yellow
        }
    }

    # Clear sensitive variables from memory
    $usptoApiKey = $null
    $mistralApiKey = $null
    [System.GC]::Collect()

    if ($newKeyAsEnv) {
        Write-Host ""
        Write-Host "[OK] Encrypted storage benefits:" -ForegroundColor Cyan
        Write-Host "     - Single-key-per-file architecture" -ForegroundColor White
        Write-Host "     - DPAPI encryption (user + machine specific)" -ForegroundColor White
        Write-Host "     - Shared across all USPTO MCPs (FPD/PFW/PTAB/Citations)" -ForegroundColor White
        Write-Host "     - Files: ~/.uspto_api_key, ~/.mistral_api_key" -ForegroundColor White
        Write-Host "     - Hidden file attributes applied" -ForegroundColor White
    }
}

# Get current directory and convert backslashes to forward slashes
$CurrentDir = (Get-Location).Path -replace "\\","/"

# PFW MCP Detection
Write-Host ""
Write-Host "USPTO MCP Ecosystem Integration" -ForegroundColor Cyan
Write-Host ""
Write-Host "The USPTO Patent File Wrapper (PFW) MCP provides a centralized proxy server" -ForegroundColor Yellow
Write-Host "that offers enhanced features when used with FPD MCP:" -ForegroundColor Yellow
Write-Host "  - Persistent document links (7-day encrypted URLs)" -ForegroundColor White
Write-Host "  - Unified rate limiting across all USPTO MCPs" -ForegroundColor White
Write-Host "  - Cross-MCP document sharing and caching" -ForegroundColor White
Write-Host ""

$hasPfwMcp = Read-Host "Do you have the USPTO PFW MCP already installed? (y/N)"

if ($hasPfwMcp -eq "y" -or $hasPfwMcp -eq "Y") {
    Write-Host "[OK] FPD will use PFW's centralized proxy for enhanced features" -ForegroundColor Green
    Write-Host "     No local proxy configuration needed" -ForegroundColor Yellow
    $useCentralizedProxy = $true
} else {
    Write-Host "[INFO] FPD will run in standalone mode with local proxy (always-on)" -ForegroundColor Yellow
    Write-Host "       Install USPTO PFW MCP later for enhanced features:" -ForegroundColor Cyan
    Write-Host "       https://github.com/johnwalkoe/patent_filewrapper_mcp" -ForegroundColor Cyan
    $useCentralizedProxy = $false
}

# Get or generate shared INTERNAL_AUTH_SECRET using unified storage
Write-Host ""
Write-Host "[INFO] Configuring shared INTERNAL_AUTH_SECRET..." -ForegroundColor Yellow

try {
    Set-Location $ProjectDir

    # Use uv run python (not direct python.exe) to avoid stderr diagnostic messages
    $result = uv run python -c @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from fpd_mcp.shared_secure_storage import ensure_internal_auth_secret

# Get or create shared secret
secret = ensure_internal_auth_secret()
if secret:
    print(secret)
else:
    sys.exit(1)
'@ 2>&1 | Out-String

    $lines = $result -split "`n" | Where-Object { $_.Trim() -ne "" }

    # Filter to find the secret (base64 pattern, 40+ chars, ignoring diagnostic/error messages)
    $internalSecret = ""
    foreach ($line in $lines) {
        $trimmed = ([string]$line).Trim()
        # Match base64 pattern: alphanumeric+/= characters, ends with =, length 40+
        if ($trimmed -match '^[A-Za-z0-9+/]+=*$' -and $trimmed.Length -ge 40) {
            $internalSecret = $trimmed
            break
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($internalSecret)) {
        # Check if this was a newly generated secret or existing one
        if ($result -match "Generating new internal auth secret") {
            Write-Host "[OK] Generated new INTERNAL_AUTH_SECRET (first USPTO MCP installation)" -ForegroundColor Green
            Write-Host "     Location: ~/.uspto_internal_auth_secret (DPAPI encrypted)" -ForegroundColor Yellow
            Write-Host "     This secret will be SHARED across all USPTO MCPs (FPD/PFW/PTAB/Citations)" -ForegroundColor Yellow
        } else {
            Write-Host "[OK] Using existing INTERNAL_AUTH_SECRET from unified storage" -ForegroundColor Green
            Write-Host "     Location: ~/.uspto_internal_auth_secret (DPAPI encrypted)" -ForegroundColor Yellow
            Write-Host "     Shared with other installed USPTO MCPs" -ForegroundColor Yellow
        }
        Write-Host "     This secret authenticates internal MCP communication" -ForegroundColor Yellow
    } else {
        Write-Host "[ERROR] Failed to get or generate INTERNAL_AUTH_SECRET" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "[ERROR] Failed to configure INTERNAL_AUTH_SECRET: $_" -ForegroundColor Red
    exit 1
}

# Step 4: Ask about Claude Desktop configuration
Write-Host ""
Write-Host "Claude Desktop Configuration" -ForegroundColor Cyan
Write-Host ""

$configureClaudeDesktop = Read-Host "Would you like to configure Claude Desktop integration? (Y/n)"
if ($configureClaudeDesktop -eq "" -or $configureClaudeDesktop -eq "Y" -or $configureClaudeDesktop -eq "y") {

    # Step 5 & 6: Determine configuration method based on flags
    $useSecureStorage = $false
    $configureUsptoApiKey = ""
    $configureMistralApiKey = ""

    if ($usingPreexistingDPAPI -and -not $newKeyAsEnv) {
        # Step 5: User is using existing DPAPI keys → Auto-configure as DPAPI
        Write-Host ""
        Write-Host "[OK] Using DPAPI encrypted storage (secure)" -ForegroundColor Green
        Write-Host "     API keys will be loaded automatically from encrypted storage" -ForegroundColor Yellow
        Write-Host "     No API keys will be stored in Claude Desktop config file" -ForegroundColor Yellow
        Write-Host ""
        $useSecureStorage = $true
        $finalConfigMethod = "dpapi"
    } elseif ($newKeyAsEnv) {
        # Step 6: User just entered a new key → Give choice between Secure and Traditional
        Write-Host ""
        Write-Host "Claude Desktop Configuration Method:" -ForegroundColor Cyan
        Write-Host "  [1] Secure Python DPAPI (recommended) - API keys loaded from encrypted storage" -ForegroundColor White
        Write-Host "  [2] Traditional - API keys stored in Claude Desktop config file" -ForegroundColor White
        Write-Host ""
        $configChoice = Read-Host "Enter choice (1 or 2, default is 1)"

        if ($configChoice -eq "2") {
            # Step 8: Traditional configuration
            Write-Host "[INFO] Using traditional method (API keys in config file)" -ForegroundColor Yellow
            $useSecureStorage = $false
            $finalConfigMethod = "traditional"

            # Retrieve the keys from DPAPI storage for config file
            try {
                Set-Location $ProjectDir
                $pythonCode = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from fpd_mcp.shared_secure_storage import UnifiedSecureStorage
storage = UnifiedSecureStorage()
uspto_key = storage.get_uspto_key()
mistral_key = storage.get_mistral_key()
if uspto_key:
    print(f'USPTO:{uspto_key}')
if mistral_key:
    print(f'MISTRAL:{mistral_key}')
'@
                $result = uv run python -c $pythonCode 2>$null | Out-String
                $lines = $result -split "`n"
                foreach ($line in $lines) {
                    if ($line.StartsWith("USPTO:")) {
                        $configureUsptoApiKey = $line.Substring(6).Trim()
                    } elseif ($line.StartsWith("MISTRAL:")) {
                        $configureMistralApiKey = $line.Substring(8).Trim()
                    }
                }
            }
            catch {
                $configureUsptoApiKey = ""
                $configureMistralApiKey = ""
            }
        } else {
            # Step 7: Secure DPAPI configuration
            Write-Host "[OK] Using DPAPI encrypted storage (secure)" -ForegroundColor Green
            Write-Host "     API keys will be loaded automatically from encrypted storage" -ForegroundColor Yellow
            Write-Host "     No API keys will be stored in Claude Desktop config file" -ForegroundColor Yellow
            Write-Host ""
            $useSecureStorage = $true
            $finalConfigMethod = "dpapi"
        }
    } else {
        # No keys configured → Default to DPAPI (no keys to store)
        Write-Host ""
        Write-Host "[OK] Using DPAPI encrypted storage (secure)" -ForegroundColor Green
        Write-Host "     No API keys configured" -ForegroundColor Yellow
        Write-Host ""
        $useSecureStorage = $true
        $finalConfigMethod = "dpapi"
    }

    # Function to generate env section based on configuration choice
    function Get-EnvSection {
        param($centralized = $false, $indent = "        ")

        $envItems = @()

        if ($useSecureStorage) {
            # Secure storage - no API keys in config
            if ($centralized) {
                $envItems += "$indent`"CENTRALIZED_PROXY_PORT`": `"8080`""
                $envItems += "$indent`"FPD_PROXY_PORT`": `"8081`""
                $envItems += "$indent`"INTERNAL_AUTH_SECRET`": `"$internalSecret`""
            } else {
                $envItems += "$indent`"CENTRALIZED_PROXY_PORT`": `"none`""
                $envItems += "$indent`"FPD_PROXY_PORT`": `"8081`""
            }
        } else {
            # Traditional - API keys in config
            if ($configureUsptoApiKey) { $envItems += "$indent`"USPTO_API_KEY`": `"$configureUsptoApiKey`"" }
            if ($configureMistralApiKey) { $envItems += "$indent`"MISTRAL_API_KEY`": `"$configureMistralApiKey`"" }
            if ($centralized) {
                $envItems += "$indent`"CENTRALIZED_PROXY_PORT`": `"8080`""
                $envItems += "$indent`"FPD_PROXY_PORT`": `"8081`""
                $envItems += "$indent`"INTERNAL_AUTH_SECRET`": `"$internalSecret`""
            } else {
                $envItems += "$indent`"CENTRALIZED_PROXY_PORT`": `"none`""
                $envItems += "$indent`"FPD_PROXY_PORT`": `"8081`""
            }
        }

        return $envItems -join ",`n"
    }

    # Function to generate server JSON entry
    function Get-ServerJson {
        param($centralized = $false, $indent = "    ")

        $envSection = Get-EnvSection -centralized $centralized -indent "      "

        return @"
$indent"uspto_fpd": {
$indent  "command": "$CurrentDir/.venv/Scripts/python.exe",
$indent  "args": [
$indent    "-m",
$indent    "fpd_mcp.main"
$indent  ],
$indent  "cwd": "$CurrentDir",
$indent  "env": {
$envSection
$indent  }
$indent}
"@
    }

    # Claude Desktop config location
    $ClaudeConfigDir = "$env:APPDATA\Claude"
    $ClaudeConfigFile = "$ClaudeConfigDir\claude_desktop_config.json"

    Write-Host "[INFO] Claude Desktop config location: $ClaudeConfigFile" -ForegroundColor Yellow

    if (Test-Path $ClaudeConfigFile) {
        Write-Host "[INFO] Existing Claude Desktop config found" -ForegroundColor Yellow
        Write-Host "[INFO] Merging USPTO FPD configuration with existing config..." -ForegroundColor Yellow

        try {
            # Read existing config as raw text
            $existingJsonText = Get-Content $ClaudeConfigFile -Raw

            # Backup the original file
            $backupFile = "$ClaudeConfigFile.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
            Copy-Item $ClaudeConfigFile $backupFile
            Write-Host "[INFO] Backup created: $backupFile" -ForegroundColor Yellow

            # Try to parse JSON, with better error handling for malformed JSON
            try {
                $existingConfig = $existingJsonText | ConvertFrom-Json
            } catch {
                Write-Host "[ERROR] Existing Claude Desktop config has JSON syntax errors" -ForegroundColor Red
                Write-Host "[ERROR] Common issue: Missing comma after closing braces '}' between MCP server sections" -ForegroundColor Red
                Write-Host "[INFO] Please fix the JSON syntax and run the setup script again" -ForegroundColor Yellow
                Write-Host "[INFO] Your backup is saved at: $backupFile" -ForegroundColor Yellow
                Write-Host ""
                Write-Host "Quick fix: Look for lines like this pattern and add missing commas:" -ForegroundColor Yellow
                Write-Host "    }" -ForegroundColor White
                Write-Host "    `"next_server`": {" -ForegroundColor White
                Write-Host ""
                Write-Host "Should be:" -ForegroundColor Yellow
                Write-Host "    }," -ForegroundColor Green
                Write-Host "    `"next_server`": {" -ForegroundColor White
                Write-Host ""
                exit 1
            }

            # Check if mcpServers exists, create if not
            if (-not $existingConfig.mcpServers) {
                # Empty config - create from scratch (NO API KEYS)
                if ($useCentralizedProxy) {
                    # PFW centralized proxy
                    $envSection = Get-EnvSection -centralized $true
                    $jsonConfig = @"
{
  "mcpServers": {
    "uspto_fpd": {
      "command": "$CurrentDir/.venv/Scripts/python.exe",
      "args": [
        "-m",
        "fpd_mcp.main"
      ],
      "cwd": "$CurrentDir",
      "env": {
$envSection
      }
    }
  }
}
"@
                } else {
                    # Standalone mode
                    $envSection = Get-EnvSection -centralized $false
                    $jsonConfig = @"
{
  "mcpServers": {
    "uspto_fpd": {
      "command": "$CurrentDir/.venv/Scripts/python.exe",
      "args": [
        "-m",
        "fpd_mcp.main"
      ],
      "cwd": "$CurrentDir",
      "env": {
$envSection
      }
    }
  }
}
"@
                }
            } else {
                # Has existing servers - need to merge manually
                # Build the uspto_fpd section
                $usptoFpdJson = Get-ServerJson -centralized $useCentralizedProxy

                # Get all existing server names
                $existingServers = $existingConfig.mcpServers.PSObject.Properties.Name

                # Build the mcpServers object with all servers
                $serverEntries = @()

                foreach ($serverName in $existingServers) {
                    if ($serverName -ne "uspto_fpd") {
                        # Convert to JSON without compression for readability
                        $serverJson = $existingConfig.mcpServers.$serverName | ConvertTo-Json -Depth 10

                        # Split into lines and format properly
                        $jsonLines = $serverJson -split "`n"

                        # First line: "serverName": {
                        $formattedEntry = "    `"$serverName`": $($jsonLines[0])"

                        # Remaining lines: indent by 4 spaces
                        for ($i = 1; $i -lt $jsonLines.Length; $i++) {
                            $formattedEntry += "`n    $($jsonLines[$i])"
                        }

                        # Add the formatted server entry
                        $serverEntries += $formattedEntry
                    }
                }

                # Add uspto_fpd
                $serverEntries += $usptoFpdJson.TrimEnd()

                $allServers = $serverEntries -join ",`n"

                $jsonConfig = @"
{
  "mcpServers": {
$allServers
  }
}
"@
            }

            # Write with UTF8 without BOM
            $utf8NoBom = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($ClaudeConfigFile, $jsonConfig, $utf8NoBom)

            Write-Host "[OK] Successfully merged USPTO FPD configuration!" -ForegroundColor Green
            Write-Host "[OK] Your existing MCP servers have been preserved" -ForegroundColor Green
            if ($useSecureStorage) {
                Write-Host "[INFO] API keys are NOT in config file (loaded from encrypted storage)" -ForegroundColor Yellow
            } else {
                Write-Host "[INFO] API keys are stored in config file (traditional method)" -ForegroundColor Yellow
            }
            Write-Host "[INFO] Configuration backup saved at: $backupFile" -ForegroundColor Yellow

            # Log audit event
            $auditMsg = if ($useSecureStorage) { "Claude Desktop configured via windows_setup.ps1 (secure DPAPI)" } else { "Claude Desktop configured via windows_setup.ps1 (traditional with API keys in config)" }
            Write-AuditLog $auditMsg

        } catch {
            Write-Host "[ERROR] Failed to merge configuration: $_" -ForegroundColor Red
            Write-Host "[ERROR] Details: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host ""
            Write-Host "Please manually add this configuration to: $ClaudeConfigFile" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "Add this to your mcpServers section:" -ForegroundColor White

            # Manual JSON string for display
            $manualJson = Get-ServerJson -centralized $useCentralizedProxy -indent ""
            Write-Host $manualJson -ForegroundColor Cyan
            Write-Host ""
            if (Test-Path $backupFile) {
                Write-Host "Your backup is saved at: $backupFile" -ForegroundColor Yellow
            }
            exit 1
        }

    } else {
        # Create new config file
        Write-Host "[INFO] Creating new Claude Desktop config..." -ForegroundColor Yellow

        # Create directory if it doesn't exist
        if (-not (Test-Path $ClaudeConfigDir)) {
            New-Item -ItemType Directory -Path $ClaudeConfigDir -Force | Out-Null
        }

        # Create config (NO API KEYS)
        $serverJson = Get-ServerJson -centralized $useCentralizedProxy
        $jsonConfig = @"
{
  "mcpServers": {
$serverJson
  }
}
"@
        # Write with UTF8 without BOM
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($ClaudeConfigFile, $jsonConfig, $utf8NoBom)

        Write-Host "[OK] Created new Claude Desktop config" -ForegroundColor Green
        if ($useSecureStorage) {
            Write-Host "[INFO] ✅ API keys are NOT in config file (loaded from encrypted storage)" -ForegroundColor Yellow
        } else {
            Write-Host "[INFO] API keys are stored in config file (traditional method)" -ForegroundColor Yellow
        }

        # Log audit event
        $auditMsg = if ($useSecureStorage) { "Claude Desktop configured via windows_setup.ps1 (secure DPAPI)" } else { "Claude Desktop configured via windows_setup.ps1 (traditional with API keys in config)" }
        Write-AuditLog $auditMsg
    }

    Write-Host "[OK] Claude Desktop configuration complete!" -ForegroundColor Green
}

# Final summary
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Windows setup complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Please restart Claude Desktop to load the MCP server" -ForegroundColor Yellow
Write-Host ""

Write-Host "Configuration Summary:" -ForegroundColor Cyan
Write-Host ""

# Check final key status
$finalKeys = Test-UnifiedKeys
if ($finalKeys.USPTO) {
    Write-Host "  [OK] USPTO API Key: Stored in DPAPI encrypted storage" -ForegroundColor Green
    Write-Host "       Location: ~/.uspto_api_key (DPAPI encrypted + hidden)" -ForegroundColor Yellow
} else {
    Write-Host "  [WARN] USPTO API Key: Not found in encrypted storage" -ForegroundColor Yellow
}

if ($finalKeys.MISTRAL) {
    Write-Host "  [OK] Mistral API Key: Stored in DPAPI encrypted storage" -ForegroundColor Green
    Write-Host "       Location: ~/.mistral_api_key (DPAPI encrypted + hidden)" -ForegroundColor Yellow
} else {
    Write-Host "  [INFO] Mistral API Key: Not set (PyPDF2 fallback for text PDFs)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  [OK] Storage Architecture: Single-key-per-file (shared across USPTO MCPs)" -ForegroundColor Green
Write-Host "  [OK] Proxy Port: 8081" -ForegroundColor Green
Write-Host "  [OK] Installation Directory: $CurrentDir" -ForegroundColor Green
Write-Host ""

Write-Host "Security Features:" -ForegroundColor Cyan
if ($finalConfigMethod -eq "dpapi") {
    Write-Host "  [*] Configuration Method: DPAPI Encrypted Storage (Secure)" -ForegroundColor White
    Write-Host "  [*] API keys encrypted with Windows DPAPI (user and machine specific)" -ForegroundColor White
    Write-Host "  [*] API keys NOT in Claude Desktop config file" -ForegroundColor White
    Write-Host "  [*] API keys NOT visible in process list (environment variables used)" -ForegroundColor White
} elseif ($finalConfigMethod -eq "traditional") {
    Write-Host "  [*] Configuration Method: Traditional (API keys in config file)" -ForegroundColor White
    Write-Host "  [*] API keys stored in Claude Desktop config file" -ForegroundColor White
    Write-Host "  [*] API keys also backed up in DPAPI encrypted storage" -ForegroundColor White
} else {
    Write-Host "  [*] Configuration Method: Not configured" -ForegroundColor White
}
Write-Host "  [*] API key format validation (prevents typos)" -ForegroundColor White
Write-Host "  [*] Hidden file attributes applied to key files" -ForegroundColor White
Write-Host "  [*] Audit logging enabled (~/.uspto_mcp_audit.log)" -ForegroundColor White
Write-Host ""

Write-Host "Available Tools (7):" -ForegroundColor Cyan
Write-Host "  - fpd_search_petitions_minimal (ultra-fast discovery)" -ForegroundColor White
Write-Host "  - fpd_search_petitions_balanced (detailed analysis)" -ForegroundColor White
Write-Host "  - fpd_search_by_art_unit (art unit quality)" -ForegroundColor White
Write-Host "  - fpd_search_by_application (petition history)" -ForegroundColor White
Write-Host "  - fpd_get_petition_details (full details)" -ForegroundColor White
Write-Host "  - fpd_get_document_download (PDF downloads)" -ForegroundColor White
Write-Host "  - fpd_get_tool_reflections (workflow guidance)" -ForegroundColor White
Write-Host ""

Write-Host "Proxy Server:" -ForegroundColor Cyan
Write-Host "  Start with: uv run fpd-proxy" -ForegroundColor Yellow
Write-Host "  Port: 8081 (avoids conflict with PFW on 8080)" -ForegroundColor White
Write-Host ""

Write-Host "Key Management:" -ForegroundColor Cyan
Write-Host "  Manage keys: ./deploy/manage_api_keys.ps1" -ForegroundColor Yellow
Write-Host "  Cross-MCP:   Keys shared with PFW, PTAB, and Citations MCPs" -ForegroundColor White
Write-Host ""

Write-Host "Test with: fpd_search_petitions_minimal" -ForegroundColor Yellow
Write-Host "Learn workflows: fpd_get_tool_reflections" -ForegroundColor Yellow
Write-Host ""
