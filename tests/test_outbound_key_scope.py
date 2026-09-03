"""The shared ODP key must not leave uspto.gov, and pypdf must not block the
event loop (fleet review 2026-09-03: M-16, M-17 / file-handling F-3, F-4)."""


import httpx
import pytest

import fpd_mcp.api.fpd_client as fpd_client_module
from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.services.document_extraction import DocumentExtractionService
from fpd_mcp.shared.uspto_hosts import is_uspto_url, strip_api_key_off_uspto


@pytest.mark.parametrize("url,expected", [
    ("https://api.uspto.gov/api/v1/patent/x", True),
    ("https://developer.uspto.gov/x", True),
    ("https://uspto.gov/x", True),
    ("http://api.uspto.gov/x", False),            # plaintext
    ("https://uspto.gov.evil.example/x", False),  # suffix confusion
    ("https://s3.amazonaws.com/signed", False),   # the real redirect target
])
def test_host_allowlist(url, expected):
    assert is_uspto_url(url) is expected


async def test_hook_strips_the_key_off_uspto():
    request = httpx.Request(
        "GET", "https://s3.amazonaws.com/signed",
        headers={"X-API-KEY": "secret", "Accept": "application/pdf"},
    )
    await strip_api_key_off_uspto(request)
    assert "x-api-key" not in request.headers
    assert request.headers["Accept"] == "application/pdf"


async def test_extraction_download_drops_the_key_on_a_cross_origin_redirect(
    monkeypatch,
):
    """httpx strips only Authorization and Cookie on an origin change, so the
    ODP key rode the 302 to signed storage verbatim."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("x-api-key")))
        if request.url.host == "api.uspto.gov":
            return httpx.Response(
                302, headers={"Location": "https://s3.example.com/signed.pdf"}
            )
        return httpx.Response(200, content=b"%PDF-1.4 body")

    real_async_client = httpx.AsyncClient

    def _mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(fpd_client_module.httpx, "AsyncClient", _mock_client)

    client = FPDClient(api_key="test-key-1234567890")
    body = await client._download_pdf_for_extraction("https://api.uspto.gov/x.pdf")

    assert body == b"%PDF-1.4 body"
    assert seen[0] == ("api.uspto.gov", "test-key-1234567890")
    assert seen[1] == ("s3.example.com", None)


async def test_pypdf_parsing_runs_off_the_event_loop(monkeypatch):
    """The parse is CPU-bound and untimed; it must not run on the loop."""
    import threading

    service = FPDClient(api_key="test-key-1234567890")._extraction
    main_thread = threading.get_ident()
    observed = {}

    def _fake_extract(pdf_content, max_pages, text_parts):
        observed["thread"] = threading.get_ident()
        text_parts.append("page one text")
        return False

    monkeypatch.setattr(
        DocumentExtractionService, "_extract_pypdf_pages", staticmethod(_fake_extract)
    )

    text, truncated = await service.extract_with_pypdf(b"%PDF-1.4", max_pages=200)

    assert text == "page one text"
    assert truncated is False
    assert observed["thread"] != main_thread
