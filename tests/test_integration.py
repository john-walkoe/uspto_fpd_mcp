"""
Integration tests for Final Petition Decisions MCP with live API

IMPORTANT: These tests require a valid USPTO_API_KEY environment variable.
They make real API calls and should be run sparingly to avoid rate limits.

Run with: uv run pytest tests/test_integration.py
Skipped automatically if USPTO_API_KEY is not set.
"""

import os
import sys
from pathlib import Path

import pytest

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

requires_live_api = pytest.mark.skipif(
    not os.getenv("USPTO_API_KEY"),
    reason="USPTO_API_KEY not set - skipping live API integration test",
)


@requires_live_api
async def test_search_petitions_minimal():
    """Minimal search returns results (or an empty result set) with live API."""
    from fpd_mcp.api.fpd_client import FPDClient

    client = FPDClient()

    result = await client.search_petitions(
        query='decisionTypeCodeDescriptionText:GRANTED',
        limit=2
    )

    assert "error" not in result, f"API returned error: {result.get('error')}"
    assert "results" in result


@requires_live_api
async def test_search_by_art_unit():
    """Art unit search completes without error against live API."""
    from fpd_mcp.api.fpd_client import FPDClient

    client = FPDClient()

    result = await client.search_by_art_unit(
        art_unit="2100",
        limit=2
    )

    assert "error" not in result, f"API returned error: {result.get('error')}"
    assert "recordTotalQuantity" in result


@requires_live_api
async def test_api_authentication():
    """A simple search succeeds, confirming USPTO_API_KEY is valid."""
    from fpd_mcp.api.fpd_client import FPDClient

    client = FPDClient()

    result = await client.search_petitions(
        query='*',
        limit=1
    )

    if "error" in result:
        assert "429" in str(result), f"Authentication failed: {result['error']}"
        pytest.skip("Rate limit exceeded - try again later")

    assert "results" in result
