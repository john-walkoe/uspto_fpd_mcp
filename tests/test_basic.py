"""
Basic tests for Final Petition Decisions MCP

Run with: uv run python tests/test_basic.py
Or: uv run pytest tests/test_basic.py
"""

import sys
import os
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

def test_imports():
    """Test that all modules can be imported"""
    print("Testing imports...")

    try:
        from fpd_mcp.config.settings import Settings
        print("[OK] Settings imported successfully")
    except Exception as e:
        print(f"[FAIL] Failed to import Settings: {e}")
        return False

    try:
        from fpd_mcp.config.field_manager import FieldManager
        print("[OK] FieldManager imported successfully")
    except Exception as e:
        print(f"[FAIL] Failed to import FieldManager: {e}")
        return False

    try:
        from fpd_mcp.api.fpd_client import FPDClient
        print("[OK] FPDClient imported successfully")
    except Exception as e:
        print(f"[FAIL] Failed to import FPDClient: {e}")
        return False

    return True


def test_field_manager():
    """Test field manager configuration loading"""
    print("\nTesting FieldManager...")

    from fpd_mcp.config.field_manager import FieldManager

    try:
        config_path = Path(__file__).parent.parent / "field_configs.yaml"
        field_manager = FieldManager(config_path)
        print(f"[OK] FieldManager loaded config from: {config_path}")

        # Test getting fields
        minimal_fields = field_manager.get_fields("petitions_minimal")
        print(f"[OK] Retrieved {len(minimal_fields)} minimal fields")

        balanced_fields = field_manager.get_fields("petitions_balanced")
        print(f"[OK] Retrieved {len(balanced_fields)} balanced fields")

        # Test context settings
        context_settings = field_manager.get_context_settings()
        print(f"[OK] Retrieved context settings: {context_settings}")

        return True
    except Exception as e:
        print(f"[FAIL] FieldManager test failed: {e}")
        return False


def test_settings():
    """Test settings configuration"""
    print("\nTesting Settings...")

    # Set temporary API key for testing
    os.environ["USPTO_API_KEY"] = "test_key_for_unit_tests"

    try:
        from fpd_mcp.config.settings import Settings

        settings = Settings()
        print(f"[OK] Settings loaded successfully")
        print(f"[OK] API Base URL: {settings.api_base_url}")
        print(f"[OK] Default minimal limit: {settings.default_minimal_limit}")
        print(f"[OK] Max search limit: {settings.max_search_limit}")

        # Check field config path
        if settings.field_config_exists:
            print(f"[OK] Field config exists at: {settings.field_config_path}")
        else:
            print(f"[WARN] Field config not found at: {settings.field_config_path}")

        return True
    except Exception as e:
        print(f"[FAIL] Settings test failed: {e}")
        return False
    finally:
        # Clean up
        if "USPTO_API_KEY" in os.environ:
            del os.environ["USPTO_API_KEY"]


def test_client_initialization():
    """Test FPD client initialization"""
    print("\nTesting FPDClient initialization...")

    # Set temporary API key for testing
    os.environ["USPTO_API_KEY"] = "test_key_for_unit_tests"

    try:
        from fpd_mcp.api.fpd_client import FPDClient

        client = FPDClient()
        print(f"[OK] FPDClient initialized successfully")
        print(f"[OK] Base URL: {client.base_url}")
        print(f"[OK] Max search limit: {client.MAX_SEARCH_LIMIT}")
        print(f"[OK] Retry attempts: {client.RETRY_ATTEMPTS}")

        return True
    except Exception as e:
        print(f"[FAIL] FPDClient initialization failed: {e}")
        return False
    finally:
        # Clean up
        if "USPTO_API_KEY" in os.environ:
            del os.environ["USPTO_API_KEY"]


def main():
    """Run all tests"""
    print("=" * 60)
    print("Final Petition Decisions MCP - Basic Tests")
    print("=" * 60)

    results = []

    results.append(("Imports", test_imports()))
    results.append(("Field Manager", test_field_manager()))
    results.append(("Settings", test_settings()))
    results.append(("Client Initialization", test_client_initialization()))

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)

    for test_name, passed in results:
        status = "[PASSED]" if passed else "[FAILED]"
        print(f"{test_name}: {status}")

    all_passed = all(passed for _, passed in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
