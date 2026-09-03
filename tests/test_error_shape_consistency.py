"""One error shape reaches the model, and a fault is not reported as a miss.

F-E2  three shapes reached the caller: the envelope, a bare dict with no
      status_code from tools/admin.py, and a plain string from
      tools/guidance.py that bypassed the sanitizer entirely
F-E6  fifteen of seventeen feature flags had no reader, including every
      kill switch; maintenance_mode logged CRITICAL and changed nothing
F-X1  a corrupt link database was indistinguishable from an expired link
testing-implementation §4: the four search tools were never tested against
      each other for the same bad input, so their divergence (two raise, two
      return) looked intentional to the suite
"""

import pytest

import fpd_mcp.tools.admin as admin_module
from fpd_mcp.tools.admin import fpd_manage_users
from fpd_mcp.tools.petitions import (
    fpd_search_petitions_balanced,
    fpd_search_petitions_by_application,
    fpd_search_petitions_by_art_unit,
    fpd_search_petitions_minimal,
)

from test_tools_misc import _FakeUserStore  # noqa: F401  (shared fake store)


# --------------------------------------------------------------------- F-E2


@pytest.fixture
def fake_user_store(monkeypatch):
    store = _FakeUserStore()
    monkeypatch.setattr(admin_module, "_get_user_store", lambda: store)
    return store


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "not-an-action"},
        {"action": "add", "email": "not-an-email"},
        {"action": "add", "email": "a@b.co", "role": "superuser"},
        {"action": "set_role", "email": "nobody@example.com", "role": "admin"},
        {"action": "deactivate", "email": "nobody@example.com"},
    ],
)
async def test_admin_errors_use_the_standard_envelope(fake_user_store, kwargs):
    """These five returned `{"error": "..."}` with no status_code and no
    success, so a caller keying off status_code got None."""
    result = await fpd_manage_users(**kwargs)

    assert result["success"] is False
    assert isinstance(result["status_code"], int)
    assert result["request_id"]


async def test_guidance_errors_do_not_leak_the_exception_text(monkeypatch):
    from fpd_mcp.tools import guidance as guidance_module

    def _boom(section):
        raise RuntimeError("secret internal detail /home/someone/key")

    monkeypatch.setattr(guidance_module, "get_guidance_section", _boom)

    result = await guidance_module.fpd_get_guidance(section="overview")

    assert isinstance(result, str)
    assert "secret internal detail" not in result
    assert "FPD_get_guidance" in result


# --------------------------------------------------------------------- F-E6


def test_only_flags_with_a_reader_are_declared():
    """An operator who sets a flag must get the behavior it names."""
    from fpd_mcp.config.feature_flags import FeatureFlags

    assert set(FeatureFlags().flags) == {
        "ocr_enabled", "mistral_ocr_enabled", "maintenance_mode",
    }


def test_maintenance_mode_registers_guidance_only(monkeypatch):
    """It used to log CRITICAL and change nothing."""
    from unittest.mock import MagicMock

    from fpd_mcp.config.feature_flags import feature_flags
    from fpd_mcp.tools import register_all

    monkeypatch.setitem(feature_flags.flags, "maintenance_mode", True)
    server = MagicMock()
    registered = []
    server.tool.side_effect = lambda *a, **kw: (
        registered.append(kw.get("name")) or (lambda fn: fn)
    )

    register_all(server)

    assert registered == ["FPD_get_guidance"]


# --------------------------------------------------------------------- F-X1


def test_an_unreadable_link_store_raises_rather_than_reading_as_expired(tmp_path):
    from fpd_mcp.proxy.secure_link_cache import (
        LinkCacheUnavailable,
        SecureLinkCache,
    )

    cache = SecureLinkCache(db_path=str(tmp_path / "links.db"))

    def _explode():
        raise OSError("database is locked")

    cache._connection = _explode

    with pytest.raises(LinkCacheUnavailable):
        cache.resolve_persistent_link("a" * 64)


async def test_an_unreadable_link_store_answers_503_not_404(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from fpd_mcp.proxy import secure_link_cache as cache_module
    from fpd_mcp.proxy.server import _handle_persistent_download

    class _Broken:
        def resolve_persistent_link(self, link_hash):
            raise cache_module.LinkCacheUnavailable("database is locked")

    monkeypatch.setattr(cache_module, "get_link_cache", lambda: _Broken())

    class _Request:
        client = type("C", (), {"host": "127.0.0.1"})()
        headers: dict = {}

    with pytest.raises(HTTPException) as excinfo:
        await _handle_persistent_download(_Request(), "a" * 64)

    assert excinfo.value.status_code == 503
    assert "not expired" in excinfo.value.detail


# ------------------------------------------------- testing-implementation §4

_SEARCH_TOOLS = {
    "minimal": (fpd_search_petitions_minimal, {"query": "*"}),
    "balanced": (fpd_search_petitions_balanced, {"query": "*"}),
    "by_art_unit": (fpd_search_petitions_by_art_unit, {"art_unit": "2128"}),
    "by_application": (
        fpd_search_petitions_by_application, {"application_number": "17896175"}
    ),
}


@pytest.mark.parametrize("name", list(_SEARCH_TOOLS), ids=list(_SEARCH_TOOLS))
async def test_all_search_tools_reject_a_zero_limit_the_same_way(mock_runtime, name):
    """D-5: two of the four raise ValidationError and two return
    format_error_response for the identical bad-limit condition. Both are
    covered individually, so the divergence read as intentional; this asserts
    the SHAPE is the same either way."""
    tool, kwargs = _SEARCH_TOOLS[name]

    result = await tool(limit=0, **kwargs)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["request_id"], "no correlation id on this path"
    assert "Limit must be between" in result["error"]


@pytest.mark.parametrize("name", list(_SEARCH_TOOLS), ids=list(_SEARCH_TOOLS))
async def test_all_search_tools_reject_a_negative_offset_the_same_way(
    mock_runtime, name
):
    tool, kwargs = _SEARCH_TOOLS[name]

    result = await tool(offset=-1, **kwargs)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["request_id"]
