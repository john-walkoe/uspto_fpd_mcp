"""
Integration tests for Final Petition Decisions MCP with live API

IMPORTANT: These tests require a valid USPTO_API_KEY environment variable.
They make real API calls and should be run sparingly to avoid rate limits.

Run with: uv run python tests/test_integration.py
Or skip if no API key: pytest tests/test_basic.py (unit tests only)
"""

import sys
import os
import asyncio
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


async def test_search_petitions_minimal():
    """Test minimal search with live API"""
    print("\n[TEST] Testing fpd_search_petitions_minimal with live API...")

    # Check for API key
    if not os.getenv("USPTO_API_KEY"):
        print("[SKIP] No USPTO_API_KEY found - skipping integration test")
        return False

    try:
        from fpd_mcp.api.fpd_client import FPDClient

        client = FPDClient()

        # Test basic search
        result = await client.search_petitions(
            query='decisionTypeCodeDescriptionText:GRANTED',
            limit=2
        )

        if "error" in result:
            print(f"[FAIL] API returned error: {result['error']}")
            return False

        if result.get("recordTotalQuantity", 0) > 0:
            print(f"[OK] Found {result.get('recordTotalQuantity', 0)} results")
            print(f"[OK] Returned {len(result.get('results', []))} petitions")
            return True
        else:
            print("[WARN] No results found (might be expected)")
            return True

    except Exception as e:
        print(f"[FAIL] Test failed: {str(e)}")
        return False


async def test_search_by_art_unit():
    """Test art unit search with live API"""
    print("\n[TEST] Testing search_by_art_unit with live API...")

    if not os.getenv("USPTO_API_KEY"):
        print("[SKIP] No USPTO_API_KEY found - skipping integration test")
        return False

    try:
        from fpd_mcp.api.fpd_client import FPDClient

        client = FPDClient()

        # Test art unit search (use a common art unit)
        result = await client.search_by_art_unit(
            art_unit="2100",
            limit=2
        )

        if "error" in result:
            print(f"[FAIL] API returned error: {result['error']}")
            return False

        print(f"[OK] Art unit search completed")
        print(f"[OK] Found {result.get('recordTotalQuantity', 0)} results for art unit 2100")
        return True

    except Exception as e:
        print(f"[FAIL] Test failed: {str(e)}")
        return False


async def test_api_authentication():
    """Test API authentication and connectivity"""
    print("\n[TEST] Testing API authentication...")

    if not os.getenv("USPTO_API_KEY"):
        print("[SKIP] No USPTO_API_KEY found - skipping integration test")
        return False

    try:
        from fpd_mcp.api.fpd_client import FPDClient

        client = FPDClient()

        # Simple search to verify auth
        result = await client.search_petitions(
            query='*',
            limit=1
        )

        if "error" in result:
            if "401" in str(result):
                print("[FAIL] Authentication failed - check USPTO_API_KEY")
                return False
            elif "429" in str(result):
                print("[WARN] Rate limit exceeded - try again later")
                return True  # Not a failure, just rate limited
            else:
                print(f"[FAIL] API error: {result['error']}")
                return False

        print("[OK] Authentication successful")
        return True

    except Exception as e:
        print(f"[FAIL] Test failed: {str(e)}")
        return False


async def main():
    """Run all integration tests"""
    print("=" * 60)
    print("Final Petition Decisions MCP - Integration Tests")
    print("=" * 60)

    # Check for API key
    if not os.getenv("USPTO_API_KEY"):
        print("\n[INFO] These tests require a USPTO_API_KEY environment variable")
        print("[INFO] Set your API key:")
        print("  Windows: $env:USPTO_API_KEY='your_key_here'")
        print("  Linux:   export USPTO_API_KEY='your_key_here'")
        print("\n[SKIP] Skipping all integration tests")
        return 0

    results = []

    # Run tests
    results.append(("API Authentication", await test_api_authentication()))
    results.append(("Minimal Search", await test_search_petitions_minimal()))
    results.append(("Art Unit Search", await test_search_by_art_unit()))

    # Print summary
    print("\n" + "=" * 60)
    print("Integration Test Results:")
    print("=" * 60)

    for test_name, passed in results:
        status = "[PASSED]" if passed else "[FAILED]"
        print(f"{test_name}: {status}")

    all_passed = all(passed for _, passed in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("ALL INTEGRATION TESTS PASSED!")
    else:
        print("SOME INTEGRATION TESTS FAILED")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
