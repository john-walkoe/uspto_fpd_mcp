"""Persistent-link lifetime: one day by default, PFW's shape (TTL days + max uses).

- FPD_LINK_TTL_DAYS (default 1, as PFW_LINK_TTL_DAYS) never resolves below
  1 day. It replaces the hard-coded 7-day constructor default.
- FPD_LINK_MAX_USES (default 25, PFW's PFW_LINK_MAX_USES default; 0 or below
  disables) bounds a leaked hash on a second axis.
- The served text (tool note, expires_in_days, 404 detail, both downloads
  pages) reads those settings instead of a hard-coded "7 days".
- A key file that cannot be READ is never replaced: replacing it made every
  stored link undecryptable, and undecryptable rows are deleted on resolve.

Temp-file SQLite only; no network.
"""

import os
from datetime import timedelta

import pytest

from fpd_mcp.proxy import secure_link_cache as slc
from fpd_mcp.proxy.secure_link_cache import SecureLinkCache

_PETITION_ID = "e55bd36d-961f-511e-b72c-b4b1529d67ef"
_DOC = dict(petition_id=_PETITION_ID, document_identifier="DOC1234567890AB",
            file_download_uri="https://api.uspto.gov/x.pdf", enhanced_filename="x.pdf")


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    root = tmp_path / "project-root"
    root.mkdir()
    monkeypatch.setattr(slc, "_PROJECT_ROOT", root)
    monkeypatch.setenv("FPD_LINK_CACHE_DIR", str(tmp_path / "data"))
    for name in ("FPD_LINK_TTL_DAYS", "FPD_LINK_MAX_USES"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _hash(url):
    return url.rsplit("/", 1)[-1]


class TestSettings:
    def test_defaults_match_pfw(self, data_dir):
        cache = SecureLinkCache(db_path=str(data_dir / "l.db"))

        assert cache.cache_duration == timedelta(days=1)
        assert cache.max_uses == 25
        assert slc.link_lifetime_text() == "1 day, up to 25 downloads"

    def test_the_ttl_is_configurable(self, data_dir, monkeypatch):
        monkeypatch.setenv("FPD_LINK_TTL_DAYS", "3")

        assert SecureLinkCache(db_path=str(data_dir / "l.db")).cache_duration == timedelta(days=3)

    @pytest.mark.parametrize("raw", ["0", "-3"])
    def test_the_ttl_never_drops_below_one_day(self, data_dir, monkeypatch, raw):
        monkeypatch.setenv("FPD_LINK_TTL_DAYS", raw)

        assert SecureLinkCache(db_path=str(data_dir / "l.db")).cache_duration == timedelta(days=1)

    def test_garbage_falls_back(self, data_dir, monkeypatch):
        monkeypatch.setenv("FPD_LINK_TTL_DAYS", "a week")
        monkeypatch.setenv("FPD_LINK_MAX_USES", "lots")
        cache = SecureLinkCache(db_path=str(data_dir / "l.db"))

        assert (cache.cache_duration.days, cache.max_uses) == (1, 25)

    def test_lifetime_text(self):
        assert slc.link_lifetime_text(2, 10) == "2 days, up to 10 downloads"
        assert slc.link_lifetime_text(1, 0) == "1 day"


class TestUseCeiling:
    def test_local_link_works_max_uses_times_then_is_removed(self, data_dir):
        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=2)
        link_hash = _hash(cache.generate_persistent_link(**_DOC))

        assert cache.resolve_persistent_link(link_hash)["access_count"] == 1
        assert cache.resolve_persistent_link(link_hash)["access_count"] == 2
        assert cache.resolve_persistent_link(link_hash) is None
        assert SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=0) \
            .resolve_persistent_link(link_hash) is None

    def test_zero_disables_the_ceiling(self, data_dir):
        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=0)
        link_hash = _hash(cache.generate_persistent_link(**_DOC))

        for _ in range(30):
            assert cache.resolve_persistent_link(link_hash) is not None

class TestUseCeilingUnderConcurrency:
    """S5 (2026-10-12 audit, July L21): the ceiling was read, compared and
    incremented separately, so parallel downloads could all pass it."""

    def test_parallel_local_resolves_never_pass_the_ceiling(self, data_dir):
        from concurrent.futures import ThreadPoolExecutor

        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=25)
        link_hash = _hash(cache.generate_persistent_link(**_DOC))

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: cache.resolve_persistent_link(link_hash), range(30)))

        served = [r for r in results if r is not None]
        assert len(served) == 25
        assert sorted(r["access_count"] for r in served) == list(range(1, 26))

class TestKeyFile:
    @pytest.mark.skipif(
        os.geteuid() == 0,
        reason="root reads a mode-000 file, so the permission failure cannot be produced",
    )
    def test_an_unreadable_key_is_not_replaced(self, data_dir):
        SecureLinkCache(db_path=str(data_dir / "a.db"))
        key_file = data_dir / "data" / ".fpd_proxy_encryption_key"
        original = key_file.read_bytes()
        key_file.chmod(0)
        try:
            with pytest.raises(OSError):
                SecureLinkCache(db_path=str(data_dir / "b.db"))
        finally:
            key_file.chmod(0o600)

        assert key_file.read_bytes() == original

    def test_a_new_key_file_is_private(self, data_dir):
        SecureLinkCache(db_path=str(data_dir / "a.db"))
        key_file = data_dir / "data" / ".fpd_proxy_encryption_key"

        assert key_file.stat().st_mode & 0o777 == 0o600


class TestServedText:
    async def test_the_local_tool_response_reads_the_setting(self, data_dir, monkeypatch):
        from fpd_mcp.proxy import centralized_integration
        from fpd_mcp.tools import documents as doc_tools

        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), cache_duration_days=3,
                                max_uses=5)

        async def _proxy_up(port):
            return True

        async def _no_registry(payload):
            return None

        monkeypatch.setattr(centralized_integration, "get_centralized_base_url", lambda: None)
        monkeypatch.setattr(doc_tools, "_ensure_proxy_server_running", _proxy_up)
        monkeypatch.setattr(doc_tools, "_register_download_via_proxy", _no_registry)
        monkeypatch.setattr(slc, "get_link_cache", lambda: cache)

        out = await doc_tools._deliver_download_link(
            _PETITION_ID, "DOC1234567890AB", [{}], {}, "https://api.uspto.gov/x.pdf",
            4)

        assert out["proxy_info"]["mode"] == "local"
        assert out["expires_in_days"] == 3
        assert "3 days, up to 5 downloads" in out["proxy_info"]["note"]

    async def test_the_centralized_response_names_pfw(self, monkeypatch):
        from fpd_mcp.proxy import centralized_integration
        from fpd_mcp.tools import documents as doc_tools

        async def _registered(**kwargs):
            return "https://pfw.example/document/persistent/abc"

        async def _no_registry(payload):
            return None

        monkeypatch.setattr(centralized_integration, "get_centralized_base_url",
                            lambda: "http://pfw:8080")
        monkeypatch.setattr(centralized_integration, "register_with_centralized_proxy",
                            _registered)
        monkeypatch.setattr(doc_tools, "_register_download_via_proxy", _no_registry)

        out = await doc_tools._deliver_download_link(
            _PETITION_ID, "DOC1234567890AB", [{}], {}, "https://api.uspto.gov/x.pdf",
            4)

        assert out["proxy_info"]["mode"] == "centralized"
        assert out["expires_in_days"] == 1
        assert "PFW_LINK_TTL_DAYS" in out["proxy_info"]["note"]

    async def test_the_downloads_pages_read_the_setting(self, monkeypatch):
        import httpx
        from httpx import ASGITransport

        from fpd_mcp.proxy.server import create_proxy_app
        from fpd_mcp.ui.views import DOWNLOADS_HTML

        monkeypatch.setenv("FPD_LINK_TTL_DAYS", "3")
        monkeypatch.setenv("FPD_LINK_MAX_USES", "0")
        app = create_proxy_app()
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test") as client:
            page = (await client.get("/downloads")).text
        panel = slc.render_link_lifetime(DOWNLOADS_HTML)

        for html in (page, panel):
            assert "Links stay valid for 3 days." in html
            assert slc.LINK_LIFETIME_PLACEHOLDER not in html

    def test_no_served_string_hard_codes_seven_days(self):
        from pathlib import Path

        root = Path(slc.__file__).resolve().parent.parent
        for rel in ("ui/views.py", "proxy/server.py", "tools/documents.py",
                    "config/tool_reflections.py", "server_bootstrap.py"):
            text = (root / rel).read_text(encoding="utf-8")
            assert "valid for 7 days" not in text, rel
            assert "7-day" not in text, rel
            assert '"expires_in_days": 7' not in text, rel
