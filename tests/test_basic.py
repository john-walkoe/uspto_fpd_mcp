"""
Basic tests for Final Petition Decisions MCP

Run with: uv run pytest tests/test_basic.py
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


def test_imports():
    """All core modules import without error."""
    from fpd_mcp.api.fpd_client import FPDClient  # noqa: F401
    from fpd_mcp.config.field_manager import FieldManager  # noqa: F401
    from fpd_mcp.config.settings import Settings  # noqa: F401


def test_field_manager():
    """FieldManager loads config and exposes tiered field sets."""
    from fpd_mcp.config.field_manager import FieldManager

    config_path = Path(__file__).parent.parent / "field_configs.yaml"
    field_manager = FieldManager(config_path)

    minimal_fields = field_manager.get_fields("petitions_minimal")
    assert len(minimal_fields) > 0

    balanced_fields = field_manager.get_fields("petitions_balanced")
    assert len(balanced_fields) > len(minimal_fields)

    context_settings = field_manager.get_context_settings()
    assert context_settings is not None


def test_settings(monkeypatch):
    """Settings load successfully with an API key present."""
    monkeypatch.setenv("USPTO_API_KEY", "test_key_for_unit_tests")

    from fpd_mcp.config.settings import Settings

    settings = Settings()
    assert settings.api_base_url
    assert settings.default_minimal_limit > 0
    assert settings.max_search_limit > 0
    assert settings.field_config_exists


def test_client_initialization(monkeypatch):
    """FPDClient initializes successfully with an API key present."""
    monkeypatch.setenv("USPTO_API_KEY", "test_key_for_unit_tests")

    from fpd_mcp.api.fpd_client import FPDClient

    client = FPDClient()
    assert client.base_url
    assert client.MAX_SEARCH_LIMIT > 0
    assert client.RETRY_ATTEMPTS > 0
