# Test Suite

This directory contains the test scripts for the USPTO Final Petition Decisions MCP Server.

**Start with [`TEST_SUITE.md`](TEST_SUITE.md)** — the manual end-to-end
suite for the FastMCP 4.0.1 server (search views, persistent downloads,
centralized proxy, HTTP mode), with live-validated anchors.

**Automated tests:** plain `uv run pytest` is now safe.
`test_unified_key_management.py` and `test_unified_storage.py` are excluded via
`addopts` in `pyproject.toml` and gated by a module-level `pytest.skip` unless
`FPD_RUN_KEY_TESTS=1` (defense in depth) — they touch the REAL DPAPI-stored
keys (they overwrite and restore them mid-test — a crash in between loses the
real keys, and `test_unified_storage.py` touches the other 3 USPTO MCPs' keys
too). Only run them deliberately with
`FPD_RUN_KEY_TESTS=1 uv run pytest tests/test_unified_key_management.py tests/test_unified_storage.py`.

## Available MCP Tools (8 Total)

The server provides these tools for petition research:

### Search Tools
- **`FPD_Search_petitions_minimal`** - Minimal fields (95-99% context reduction)
- **`FPD_Search_petitions_balanced`** - Balanced fields (80-88% context reduction)
- **`FPD_Search_petitions_by_art_unit`** - Art unit quality assessment with date range filtering
- **`FPD_Search_petitions_by_application`** - Complete petition history for specific application

### Document & Detail Tools
- **`FPD_Get_petition_details`** - Full petition details by UUID with optional documentBag
- **`FPD_get_document_content_with_ocr`** - Intelligent text extraction: native `pypdf` text layer first, OCR (Mistral or self-hosted Docling) for scanned pages
- **`FPD_get_document_download`** - Secure browser-accessible download URLs

### Utility Tools
- **`FPD_get_guidance`** - Selective guidance sections for context-efficient workflows and cross-MCP integration

## Essential Tests

### Core Functionality Tests
- **`test_basic.py`** - Tests core functionality, settings, field manager, and API client initialization
- **`test_integration.py`** - Integration tests with real API calls (requires USPTO API key)
- **`test_tiered_convenience_params.py`** - Tests convenience parameters implementation (date validation, query building)
- **`test_unified_key_management.py`** - Tests unified secure storage for API keys across USPTO MCPs
- **`test_unified_storage.py`** - Tests unified storage functionality and cross-MCP compatibility

## API Key Setup

**Option 1: Environment Variable (Recommended)**
```bash
# Windows Command Prompt
set USPTO_API_KEY=your_api_key_here
set MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL

# Windows PowerShell
$env:USPTO_API_KEY="your_api_key_here"
$env:MISTRAL_API_KEY="your_mistral_api_key_here_OPTIONAL"

# Linux/macOS
export USPTO_API_KEY=your_api_key_here
export MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
```

**Option 2: Testing Without Real API Key**
If you don't have a USPTO API key yet, the test files will automatically use a test key for basic functionality testing. However, actual API calls will fail without a real key.

**Note:** The MISTRAL_API_KEY is optional. Without it, document extraction reads the PDF's native text layer with `pypdf`, which covers text-based PDFs. Add it, or set `DOCLING_SERVE_URL` to a self-hosted Docling backend, to OCR scanned documents.

**Secure Storage:** API keys can be stored securely using Windows DPAPI (preferred) or environment variables (fallback). The secure storage automatically encrypts keys and eliminates the need to set environment variables each session.

## Running Tests

### With uv (Recommended)
```bash
# Whole suite (most important) - key-management/storage tests auto-skip
uv run pytest

# Core functionality test only
uv run pytest tests/test_basic.py

# Integration tests with real API calls (requires USPTO_API_KEY; auto-skip otherwise)
uv run pytest tests/test_integration.py

# Test convenience parameters implementation
uv run python tests/test_tiered_convenience_params.py

# Test unified secure storage for API keys (destructive - opt in deliberately)
FPD_RUN_KEY_TESTS=1 uv run pytest tests/test_unified_key_management.py

# Test unified storage functionality (destructive - opt in deliberately)
FPD_RUN_KEY_TESTS=1 uv run pytest tests/test_unified_storage.py
```

## Expected Results

### test_basic.py
```
tests/test_basic.py::test_imports PASSED
tests/test_basic.py::test_field_manager PASSED
tests/test_basic.py::test_settings PASSED
tests/test_basic.py::test_client_initialization PASSED
```

### test_integration.py
Without `USPTO_API_KEY` set, all three tests auto-skip:
```
tests/test_integration.py::test_search_petitions_minimal SKIPPED
tests/test_integration.py::test_search_by_art_unit SKIPPED
tests/test_integration.py::test_api_authentication SKIPPED
```
With a valid `USPTO_API_KEY`, they run against the live API and PASS.

### test_tiered_convenience_params.py
```
Starting tiered convenience parameters tests...

Testing date validation...
Date validation tests passed
Testing string validation...
String validation tests passed
Testing application number validation...
Application number validation tests passed
Testing minimal query building...
Minimal query building tests passed
Testing balanced query building...
Balanced query building tests passed
Testing progressive disclosure enforcement...
Progressive disclosure enforcement tests passed

All tests passed! Tiered convenience parameters implementation is working correctly.
```

### test_unified_key_management.py
```
============================================================
USPTO MCP Unified Key Management Test
============================================================
[OK] UnifiedSecureStorage imported successfully
[OK] USPTO_API_KEY: Present (30 chars, ending: ...abcde)
[OK] MISTRAL_API_KEY: Present (32 chars, ending: ...xyz12)
[OK] Key retrieval functionality working
[OK] Cross-MCP compatibility verified
ALL UNIFIED KEY MANAGEMENT TESTS PASSED!
```

### test_unified_storage.py
```
[OK] Unified storage initialization passed
[OK] Key storage functionality passed
[OK] Key retrieval functionality passed
[OK] Cross-platform compatibility verified
ALL UNIFIED STORAGE TESTS PASSED!
```


## Prerequisites

### Required Setup
- **Python 3.10+** with required dependencies installed
- **Internet connection** for USPTO API access
- **USPTO API Key** (see setup instructions below)

**Getting a USPTO API Key:**
1. Visit [USPTO Open Data Portal](https://data.uspto.gov/myodp/)
2. Register for an account - Select "I don't have a MyUSPTO account and need to create one"
3. Log in
4. Generate an API key for the Final Petition Decisions API
5. Set the key in your environment as shown above

**Getting a Mistral API Key (Optional for OCR):**
1. Visit [Mistral AI Console](https://console.mistral.ai/api-keys/)
2. Create an account
3. Generate an API key
4. Set the key in your environment as shown above

**Security Note:** Never commit API keys to version control. The test files now use secure environment variable patterns.

## Test File Descriptions

### test_basic.py
- Tests core imports (settings, field_manager, fpd_client)
- Verifies FPDClient can be initialized
- Validates project structure and dependencies
- **No API calls made** - safe to run without real API key

### test_integration.py
- Tests real API calls to USPTO Final Petition Decisions API
- Validates search functionality with live data
- Tests petition details retrieval
- **Requires USPTO_API_KEY** - makes actual API calls

### test_tiered_convenience_params.py
- Tests convenience parameters implementation and validation
- Validates date range checking and format validation
- Tests query building with convenience parameters
- **No API calls made** - pure functionality testing

### test_unified_key_management.py
- Tests unified secure storage functionality across USPTO MCPs
- Validates API key storage and retrieval
- Tests cross-MCP compatibility for shared keys
- **No API calls made** - tests storage infrastructure

### test_unified_storage.py
- Tests unified storage system functionality
- Validates storage initialization and key management
- Tests cross-platform compatibility
- **No API calls made** - tests storage mechanisms


## Environment Variables

The following environment variables can be set for testing:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `USPTO_API_KEY` | ✅ Yes | None | USPTO API key (for actual API tests) |
| `MISTRAL_API_KEY` | ❌ No | None | Mistral API key for OCR (optional) |
| `FPD_PROXY_PORT` | ❌ No | `8081` | Proxy server port |
| `ENABLE_PROXY_SERVER` | ❌ No | `true` | Enable/disable proxy server |
| `USPTO_TIMEOUT` | ❌ No | `30.0` | API request timeout in seconds |
| `USPTO_DOWNLOAD_TIMEOUT` | ❌ No | `60.0` | Document download/OCR timeout in seconds |

## Troubleshooting

### "USPTO_API_KEY environment variable is required"
**Solution:** Set your API key in the environment:
```bash
# Windows PowerShell
$env:USPTO_API_KEY="your_key_here"

# Linux/macOS
export USPTO_API_KEY="your_key_here"
```

### Import Errors
**Solution:** Reinstall dependencies:
```bash
cd uspto_fpd_mcp
uv sync --reinstall
```

### Test Failures
1. Check that you're in the project root directory
2. Verify dependencies are installed (`uv sync`)
3. Ensure environment variables are set if testing API functionality
4. Check internet connection for API tests

## Test Development Guidelines

When adding new tests:

1. **Use environment variables** for API keys (never hardcode)
2. **Handle missing keys gracefully** for unit tests
3. **Document expected behavior** in test docstrings
4. **Keep tests focused** - one concept per test file
5. **Follow naming conventions** - `test_*.py` for test files

## Additional Resources

- **Main README:** `../README.md` - Project overview and features
- **Installation Guide:** `../INSTALL.md` - Complete setup instructions
- **Usage Examples:** `../USAGE_EXAMPLES.md` - Function examples and workflows
- **Security Guidelines:** `../SECURITY_GUIDELINES.md` - API key security best practices

## Questions?

For more detailed examples and workflow guidance, use the `FPD_get_guidance` tool with specific sections (e.g., "workflows_pfw", "workflows_ptab") which provides comprehensive LLM-friendly guidance for complex multi-step analyses.
