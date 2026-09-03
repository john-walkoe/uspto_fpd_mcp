"""
Basic tests for Final Petition Decisions MCP

Run with: uv run pytest tests/test_basic.py
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


def test_the_package_imports_without_a_uspto_api_key():
    """All core modules import without error."""
    from fpd_mcp.api.fpd_client import FPDClient  # noqa: F401
    from fpd_mcp.config.field_manager import FieldManager  # noqa: F401
    from fpd_mcp.config.settings import Settings  # noqa: F401


def test_field_manager_loads_the_configured_sets():
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


def _field_manager():
    from fpd_mcp.config.field_manager import FieldManager

    return FieldManager(Path(__file__).parent.parent / "field_configs.yaml")


def test_context_info_counts_are_comparable_on_a_sparse_record():
    """The API omits null fields, so a record routinely carries FEWER fields
    than were requested. filtered_field_count used to be the size of the
    CONFIGURED set, which on such a record produced the nonsense "filtered 7
    fields down to 8" — a claim to have filtered a record down to more fields
    than it had. Both counts are now counts of the same sampled record, so
    filtered can never exceed original.
    """
    field_manager = _field_manager()
    minimal_fields = field_manager.get_fields("petitions_minimal")
    sparse = {
        f: "x" for f in minimal_fields[:-1]  # one requested field simply absent
    }

    result = field_manager.filter_response(
        {"petitionDecisionDataBag": [sparse], "count": 1}, "petitions_minimal"
    )

    info = result["context_info"]
    assert info["original_field_count"] == len(minimal_fields) - 1
    assert info["filtered_field_count"] <= info["original_field_count"]
    assert info["configured_field_count"] == len(minimal_fields)
    assert info["context_reduction"] == "0%"


def test_context_reduction_never_claims_a_reduction_it_did_not_make():
    """A projection that dropped nothing saved nothing."""
    field_manager = _field_manager()
    manager_cls = type(field_manager)

    assert manager_cls._calculate_reduction(field_manager, {"a": "x"}, {"a": "x"}) == "0%"
    # A payload that somehow grew must still report 0%, never a negative.
    assert manager_cls._calculate_reduction(field_manager, {"a": "x"}, {"a": "xxxxxxxx"}) == "0%"
    # And a real reduction is still reported.
    assert manager_cls._calculate_reduction(
        field_manager, {"a": "x", "b": "y" * 100}, {"a": "x"}
    ) != "0%"


def test_context_reduction_is_reported_when_fields_are_actually_dropped():
    """The dense case: a record carrying more than the tier asked for."""
    field_manager = _field_manager()
    minimal_fields = field_manager.get_fields("petitions_minimal")
    dense = {f: "x" for f in minimal_fields}
    dense.update({f"extraField{i}": "y" * 20 for i in range(10)})

    info = field_manager.filter_response(
        {"petitionDecisionDataBag": [dense], "count": 1}, "petitions_minimal"
    )["context_info"]

    assert info["original_field_count"] == len(minimal_fields) + 10
    assert info["filtered_field_count"] == len(minimal_fields)
    assert info["context_reduction"] != "0%"


def test_settings_expose_the_configured_limits_and_paths(monkeypatch):
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
