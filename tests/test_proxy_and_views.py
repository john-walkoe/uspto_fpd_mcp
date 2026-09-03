"""Tests for the persistent-link proxy machinery and MCP App views."""

import asyncio
import re
from pathlib import Path

import pytest

from fpd_mcp.proxy.secure_link_cache import SecureLinkCache
from fpd_mcp.proxy.server import register_recent_download, get_recent_downloads, _DOWNLOADS_PAGE_HTML
from fpd_mcp.ui import SEARCH_RESULTS_HTML, DOWNLOADS_HTML

SRC_DIR = Path(__file__).parent.parent / "src" / "fpd_mcp"


class TestSecureLinkCache:
    @pytest.fixture
    def cache(self, tmp_path):
        return SecureLinkCache(db_path=str(tmp_path / "test_links.db"))

    def test_roundtrip(self, cache):
        url = cache.generate_persistent_link(
            petition_id="e55bd36d-961f-511e-b72c-b4b1529d67ef",
            document_identifier="HY1J6ICXPXXIFW4",
            file_download_uri="https://api.uspto.gov/x/y.pdf",
            enhanced_filename="PET-TEST.pdf",
            base_url="http://localhost:8081",
        )
        assert "/download/persistent/" in url
        link_hash = url.rsplit("/", 1)[1]
        assert len(link_hash) == 24

        data = cache.resolve_persistent_link(link_hash)
        assert data["petition_id"] == "e55bd36d-961f-511e-b72c-b4b1529d67ef"
        assert data["document_identifier"] == "HY1J6ICXPXXIFW4"
        assert data["file_download_uri"] == "https://api.uspto.gov/x/y.pdf"
        assert data["enhanced_filename"] == "PET-TEST.pdf"
        assert data["access_count"] == 1

    def test_unknown_hash_returns_none(self, cache):
        assert cache.resolve_persistent_link("0" * 24) is None

    def test_expired_link_returns_none(self, tmp_path):
        cache = SecureLinkCache(cache_duration_days=-1, db_path=str(tmp_path / "exp.db"))
        url = cache.generate_persistent_link(
            petition_id="p", document_identifier="d",
            file_download_uri="https://api.uspto.gov/x.pdf",
            enhanced_filename="f.pdf",
        )
        assert cache.resolve_persistent_link(url.rsplit("/", 1)[1]) is None

    def test_base_url_used(self, cache):
        url = cache.generate_persistent_link(
            petition_id="p", document_identifier="d",
            file_download_uri="https://api.uspto.gov/x.pdf",
            enhanced_filename="f.pdf",
            base_url="https://fpd.example.com",
        )
        assert url.startswith("https://fpd.example.com/download/persistent/")


class TestRecentDownloadsRegistry:
    def test_register_and_list(self):
        entry_id = register_recent_download({
            "download_url": "http://localhost:8081/download/persistent/abc",
            "petition_id": "p1",
            "document_identifier": "d1",
            "enhanced_filename": "f.pdf",
        })
        assert entry_id
        downloads = get_recent_downloads(include_all=True)
        assert any(d["download_id"] == entry_id for d in downloads)
        entry = next(d for d in downloads if d["download_id"] == entry_id)
        assert entry["registered_at"]

    def test_no_key_returns_nothing(self):
        register_recent_download({
            "download_url": "http://localhost:8081/download/persistent/def",
            "petition_id": "p2",
        })
        assert get_recent_downloads() == []

    def test_viewer_key_scoping(self):
        entry_id = register_recent_download({
            "download_url": "http://localhost:8081/download/persistent/ghi",
            "petition_id": "p3",
            "viewer_key": "vk-registry-test",
        })
        # Wrong key -> entry invisible
        assert all(d["download_id"] != entry_id
                   for d in get_recent_downloads(viewer_key="wrong-key"))
        # Correct key -> own entry, internal hash never exposed
        downloads = get_recent_downloads(viewer_key="vk-registry-test")
        assert any(d["download_id"] == entry_id for d in downloads)
        assert all("_viewer_key_hash" not in d for d in downloads)


@pytest.mark.asyncio
class TestRecentDownloadsRoute:
    """H2: /api/recent-downloads returns live persistent-download
    credentials, so it never serves the registry anonymously — callers
    present the machine-facing X-Proxy-Token (full registry) or the
    per-registrant viewer key ?s= (own entries only). PTAB parity."""

    async def test_recent_downloads_viewer_key_flow(self):
        from httpx import AsyncClient, ASGITransport
        from fpd_mcp.proxy.server import create_proxy_app, _get_proxy_token

        app = create_proxy_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/register-download",
                json={
                    "download_url": "http://localhost:8081/download/persistent/xyz",
                    "petition_id": "p-route",
                    "document_identifier": "d-route",
                    "enhanced_filename": "FPD-TEST.pdf",
                    "viewer_key": "viewer-key-test-1",
                },
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            assert resp.status_code == 200
            download_id = resp.json()["download_id"]
            assert download_id

            # Anonymous listing is refused — entries hold live credentials
            resp = await client.get("/api/recent-downloads")
            assert resp.status_code == 401

            # Wrong viewer key -> no entries
            resp = await client.get("/api/recent-downloads",
                                    params={"s": "wrong-key"})
            assert resp.status_code == 200
            assert all(d["download_id"] != download_id
                       for d in resp.json()["downloads"])

            # Correct viewer key -> own entry, internal hash never exposed
            resp = await client.get("/api/recent-downloads",
                                    params={"s": "viewer-key-test-1"})
            assert resp.status_code == 200
            downloads = resp.json()["downloads"]
            assert any(d["download_id"] == download_id for d in downloads)
            assert all("_viewer_key_hash" not in d for d in downloads)

            # Proxy token -> full registry (machine-facing)
            resp = await client.get(
                "/api/recent-downloads",
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            assert resp.status_code == 200
            assert any(d["download_id"] == download_id
                       for d in resp.json()["downloads"])


class TestViews:
    def test_views_nonempty_and_light_scheme(self):
        for html in (SEARCH_RESULTS_HTML, DOWNLOADS_HTML, _DOWNLOADS_PAGE_HTML):
            assert len(html) > 2000
            assert "color-scheme: light" in html

    def test_ontoolresult_registered_before_connect(self):
        # Lesson: ontoolresult must be assigned before app.connect(), or the
        # initial tool result is dropped.
        for html in (SEARCH_RESULTS_HTML, DOWNLOADS_HTML):
            assert html.index("app.ontoolresult") < html.index("app.connect()")

    def test_views_use_open_link_for_buttons(self):
        # Lesson 24: iframe buttons must open URLs via app.openLink
        assert "app.openLink" in SEARCH_RESULTS_HTML
        assert "app.openLink" in DOWNLOADS_HTML

    def test_no_camelcase_resource_uri_in_main(self):
        source = (SRC_DIR / "main.py").read_text(encoding="utf-8")
        assert "resourceUri" not in source, "use snake_case resource_uri="

    @pytest.mark.asyncio
    async def test_resources_registered(self):
        from fpd_mcp import main
        resources = await main.mcp.list_resources()
        uris = {str(r.uri) for r in resources}
        assert "ui://fpd/search-results.html" in uris
        assert "ui://fpd/recent-downloads.html" in uris

    def test_google_patents_gate_regex_present(self):
        # Lesson 26: the Google Patents button must be gated on a US patent
        # number shape
        assert "(RE)?\\d{6,8}" in SEARCH_RESULTS_HTML


# ------------------------------------------ M-12 / L-10 / L-11: view hardening


class TestViewEscaping:
    """USPTO applicant names and invention titles reach innerHTML (M-12)."""

    @pytest.mark.parametrize(
        "html",
        [SEARCH_RESULTS_HTML, DOWNLOADS_HTML, _DOWNLOADS_PAGE_HTML],
        ids=["search", "downloads-app", "downloads-page"],
    )
    def test_every_view_defines_the_escape_helper(self, html):
        assert "function esc(s)" in html
        assert "'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'" in html

    @pytest.mark.parametrize(
        "field",
        ["p.applicant", "p.title", "p.decision", "p.petType", "p.office",
         "p.rules", "p.id", "p.appNum", "p.patentNum", "p.artUnit", "p.tc"],
    )
    def test_search_card_escapes_applicant_authored_fields(self, field):
        assert f"esc({field})" in SEARCH_RESULTS_HTML
        assert "${" + field + "}" not in SEARCH_RESULTS_HTML

    def test_search_card_escapes_title_attributes(self):
        # An unescaped quote in title="..." closes the attribute.
        for field in ("p.applicant", "p.title", "p.petType", "p.office", "p.rules"):
            assert f'title="${{esc({field})}}"' in SEARCH_RESULTS_HTML

    def test_filter_pill_escapes_its_label(self):
        assert "esc(label)" in SEARCH_RESULTS_HTML

    @pytest.mark.parametrize("field", ["doc.title", "doc.petition_id", "doc.proxy_url"])
    def test_downloads_app_escapes_document_fields(self, field):
        assert f"esc({field})" in DOWNLOADS_HTML
        assert "${" + field + "}" not in DOWNLOADS_HTML

    def test_proxy_downloads_page_escapes_the_registry(self):
        assert "esc(d.download_url)" in _DOWNLOADS_PAGE_HTML
        assert "${d.download_url}" not in _DOWNLOADS_PAGE_HTML


class TestDownloadsPageCSP:
    """L-11: the page could not run under its own default-src 'self'."""

    def test_policy_hashes_the_pages_inline_script(self):
        from fpd_mcp.proxy.server import _CONTENT_SECURITY_POLICY

        assert "script-src 'self' 'sha256-" in _CONTENT_SECURITY_POLICY
        # CSP is tightened, not dropped.
        assert "default-src 'self'" in _CONTENT_SECURITY_POLICY
        assert "object-src 'none'" in _CONTENT_SECURITY_POLICY
        assert "frame-ancestors 'none'" in _CONTENT_SECURITY_POLICY
        assert "script-src 'self' 'unsafe-inline'" not in _CONTENT_SECURITY_POLICY

    def test_hash_matches_the_script_actually_served(self):
        import base64
        import hashlib

        body = re.findall(
            r"<script[^>]*>(.*?)</script>", _DOWNLOADS_PAGE_HTML, re.DOTALL
        )
        assert len(body) == 1
        expected = base64.b64encode(
            hashlib.sha256(body[0].encode("utf-8")).digest()
        ).decode("ascii")

        from fpd_mcp.proxy.server import _CONTENT_SECURITY_POLICY

        assert f"'sha256-{expected}'" in _CONTENT_SECURITY_POLICY


class TestRecentDownloadUrlScheme:
    """L-10: the value is rendered as an anchor href."""

    def test_non_http_schemes_are_rejected(self):
        from pydantic import ValidationError

        from fpd_mcp.proxy.models import RecentDownloadRegistration

        base = dict(petition_id="p1", document_identifier="d1")
        for bad in ("javascript:alert(1)", "data:text/html,<script>x</script>",
                    "file:///etc/passwd", "/relative"):
            with pytest.raises(ValidationError):
                RecentDownloadRegistration(download_url=bad, **base)

    def test_http_and_https_are_accepted(self):
        from fpd_mcp.proxy.models import RecentDownloadRegistration

        base = dict(petition_id="p1", document_identifier="d1")
        for good in ("https://api.uspto.gov/x.pdf",
                     "http://127.0.0.1:8081/download/persistent/abc"):
            model = RecentDownloadRegistration(download_url=good, **base)
            assert model.download_url == good
