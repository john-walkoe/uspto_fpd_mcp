"""Offline mocked tests for the 3-tier hybrid extraction pipeline
(services/document_extraction.py): pypdf tier success, pypdf-fails ->
Mistral tier (with M3 daily-cost accumulation), Mistral-disabled -> Docling
tier gate, and the all-tiers-fail error shape.

No network calls: the owning "client" (petition lookup + PDF download) and
the Mistral/Docling network boundaries are all mocked/stubbed.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from fpd_mcp.services import document_extraction as de_module
from fpd_mcp.services.document_extraction import DocumentExtractionService

_PETITION_ID = "e55bd36d-961f-511e-b72c-b4b1529d67ef"
_DOCUMENT_ID = "DOC1234567890AB"

_GOOD_TEXT = (
    "This petition decision was issued after careful review of the application "
    "history and the applicant's arguments regarding the abandonment. " * 3
)


def _make_fake_owning_client(pdf_bytes: bytes = b"%PDF-1.4 fake pdf content"):
    """A stand-in for FPDClient exposing only what DocumentExtractionService
    needs: get_petition_by_id() (document metadata) and
    _download_pdf_for_extraction() (byte-capped PDF fetch)."""
    from fpd_mcp.api.field_constants import FPDFields

    petition_payload = {
        FPDFields.PETITION_DECISION_DATA_BAG: [
            {
                FPDFields.DOCUMENT_BAG: [
                    {
                        FPDFields.DOCUMENT_IDENTIFIER: _DOCUMENT_ID,
                        FPDFields.DOCUMENT_CODE: "PET",
                        FPDFields.PAGE_COUNT: 3,
                        FPDFields.DOWNLOAD_OPTION_BAG: [
                            {
                                FPDFields.MIME_TYPE_IDENTIFIER: "PDF",
                                FPDFields.DOWNLOAD_URL: "https://api.uspto.gov/fake.pdf",
                            }
                        ],
                    }
                ]
            }
        ]
    }

    client = AsyncMock()
    client.get_petition_by_id.return_value = petition_payload
    client._download_pdf_for_extraction.return_value = pdf_bytes
    return client


@pytest.fixture(autouse=True)
def _reset_mistral_daily_cost_state():
    """M3 daily-spend state is a module-level global — reset around every
    test in this file so accumulation tests don't leak into each other."""
    de_module._mistral_daily_cost_state["date"] = None
    de_module._mistral_daily_cost_state["total"] = 0.0
    yield
    de_module._mistral_daily_cost_state["date"] = None
    de_module._mistral_daily_cost_state["total"] = 0.0


def _make_service(client=None) -> DocumentExtractionService:
    return DocumentExtractionService(
        client=client or _make_fake_owning_client(),
        download_timeout=5.0,
        connection_limits=httpx.Limits(),
    )


async def test_pypdf_tier_success(monkeypatch):
    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf", AsyncMock(return_value=(_GOOD_TEXT, False))
    )

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["success"] is True
    assert result["extraction_method"] == "pypdf"
    # Cost fields are internal-only accounting — never in the response.
    assert "processing_cost_usd" not in result
    assert "cost_breakdown" not in result
    assert result["extracted_content"] == _GOOD_TEXT


async def test_pypdf_fails_falls_back_to_mistral(monkeypatch):
    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf", AsyncMock(return_value=("garbled \x00\x01", False))
    )
    monkeypatch.setattr(
        service, "extract_with_mistral_ocr", AsyncMock(return_value=("mistral extracted text", 0.003))
    )

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["success"] is True
    assert result["extraction_method"].startswith("Mistral OCR")
    # Cost fields are internal-only accounting — never in the response.
    assert "processing_cost_usd" not in result
    assert "cost_breakdown" not in result
    assert result["extracted_content"] == "mistral extracted text"


async def test_mistral_ocr_cost_accumulates_daily_spend_state(monkeypatch):
    """Lower-level test of the M3 daily-spend accumulation itself: mocks the
    Mistral HTTP boundary (upload + OCR calls) but exercises the REAL
    extract_with_mistral_ocr()/_do_mistral_ocr_call(), so the actual
    _mistral_daily_spend_add() bookkeeping runs."""
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key-for-tests")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "file-123"})
        return httpx.Response(
            200,
            json={
                "usage_info": {"pages_processed": 3},
                "pages": [{"index": 0, "markdown": "page one text"}],
            },
        )

    mock_transport = httpx.MockTransport(handler)
    _real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        de_module.httpx, "AsyncClient",
        lambda *a, **kw: _real_async_client(transport=mock_transport),
    )

    service = _make_service()

    text, cost = await service.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=3)

    assert "page one text" in text
    assert cost == pytest.approx(3 * 0.001)
    assert de_module._mistral_daily_cost_state["total"] == pytest.approx(cost)


def _mistral_transport(monkeypatch, captured: dict, pages=None, pages_processed=3):
    """Mock the Mistral upload+OCR HTTP boundary and capture the OCR body."""
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "file-123"})
        captured["ocr_payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "usage_info": {"pages_processed": pages_processed},
                "pages": pages if pages is not None else [{"index": 0, "markdown": "page one text"}],
            },
        )

    mock_transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        de_module.httpx, "AsyncClient",
        lambda *a, **kw: real_async_client(transport=mock_transport),
    )


async def test_missing_page_count_never_sends_an_unbounded_ocr_request(monkeypatch):
    """The `else None` bug: a missing/zero pageCount used to send the ENTIRE
    document to the paid OCR tier. The request must always carry an explicit,
    bounded page range."""
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key-for-tests")
    captured: dict = {}
    _mistral_transport(monkeypatch, captured)

    service = _make_service()
    await service.extract_with_mistral_ocr(b"%PDF-1.4 not-a-real-pdf", page_count=0)

    pages = captured["ocr_payload"]["pages"]
    assert pages is not None
    assert isinstance(pages, list)
    assert pages == list(range(50))  # MISTRAL_OCR_MAX_PAGES default


async def test_ocr_page_cap_is_configurable(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key-for-tests")
    monkeypatch.setenv("MISTRAL_OCR_MAX_PAGES", "7")
    captured: dict = {}
    _mistral_transport(monkeypatch, captured)

    service = _make_service()
    await service.extract_with_mistral_ocr(b"%PDF-1.4 not-a-real-pdf", page_count=200)

    assert captured["ocr_payload"]["pages"] == list(range(7))


async def test_spend_precheck_uses_the_bounded_page_count(monkeypatch):
    """The pre-check used to estimate a missing page count at ONE page, so a
    50-page OCR sailed past a nearly-exhausted daily budget and only booked
    its real cost afterwards."""
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key-for-tests")
    # 0.01 USD == 10 pages. A 50-page estimate must not fit.
    monkeypatch.setenv("MISTRAL_OCR_DAILY_BUDGET_USD", "0.01")
    captured: dict = {}
    _mistral_transport(monkeypatch, captured)

    service = _make_service()
    with pytest.raises(ValueError, match="capacity limit reached"):
        await service.extract_with_mistral_ocr(b"%PDF-1.4 not-a-real-pdf", page_count=0)

    assert "ocr_payload" not in captured  # no paid call was made


async def test_blank_ocr_pages_keep_the_page_numbering_honest(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key-for-tests")
    captured: dict = {}
    _mistral_transport(
        monkeypatch,
        captured,
        pages=[
            {"index": 0, "markdown": "page one text"},
            {"index": 1, "markdown": "   \n  "},
            {"index": 2, "markdown": "page three text"},
        ],
    )

    service = _make_service()
    text, _cost = await service.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=3)

    assert "=== PAGE 1 ===" in text
    assert "=== PAGE 2 ===" in text  # the blank page leaves a visible gap
    assert "=== PAGE 3 ===" in text
    assert "[no text recovered from this page]" in text


async def test_page_capped_ocr_is_marked_as_truncated(monkeypatch):
    """The Mistral tier used to truncate with NO marker at all."""
    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf", AsyncMock(return_value=("garbled \x00\x01", False))
    )
    monkeypatch.setattr(
        service, "extract_with_mistral_ocr", AsyncMock(return_value=("ocr text", 0.05))
    )
    monkeypatch.setattr(
        de_module, "resolve_ocr_page_window", lambda pdf, count, max_pages=None: (50, 300)
    )

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["truncated"] is True
    assert "50 of 300" in result["truncation_note"]
    bounds = result["_bounds"]
    assert bounds["applied"] is True
    assert bounds["reason"] == "window"
    assert bounds["items_returned"] == 50
    assert bounds["items_total"] == 300
    # page_count must not assert completeness when pages were capped
    assert result["pages_extracted"] == 50
    assert result["page_count"] == 300


async def test_uncapped_ocr_has_no_truncation_marker(monkeypatch):
    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf", AsyncMock(return_value=("garbled \x00\x01", False))
    )
    monkeypatch.setattr(
        service, "extract_with_mistral_ocr", AsyncMock(return_value=("ocr text", 0.003))
    )

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert "truncated" not in result
    assert "_bounds" not in result


async def test_pypdf_partial_extraction_is_returned_and_marked():
    """A mid-extraction failure used to discard everything already extracted
    and report truncated=False — a partial result presented as complete."""
    class _ExplodingPage:
        def extract_text(self):
            raise RuntimeError("bad xref")

    class _GoodPage:
        def extract_text(self):
            return "real page text"

    class _FakeReader:
        def __init__(self, *_a, **_kw):
            self.pages = [_GoodPage(), _GoodPage(), _ExplodingPage()]

    import pypdf

    service = _make_service()
    original = pypdf.PdfReader
    pypdf.PdfReader = _FakeReader
    try:
        status: dict = {}
        text, truncated = await service.extract_with_pypdf(b"%PDF-1.4", status=status)
    finally:
        pypdf.PdfReader = original

    assert text.count("real page text") == 2  # partial content survives
    assert truncated is True
    assert "aborted after 2 page(s)" in status["extraction_error"]
    assert status["pages_extracted"] == 2


async def test_mistral_disabled_falls_back_to_docling(monkeypatch):
    monkeypatch.setitem(de_module.feature_flags.flags, "mistral_ocr_enabled", False)

    # is_available()/within_page_limit() are SYNC on the real DoclingClient —
    # a plain AsyncMock would make them return truthy (unawaited) coroutines
    # instead of booleans, so use MagicMock and only make .extract() async.
    fake_docling = MagicMock()
    fake_docling.is_available.return_value = True
    fake_docling.within_page_limit.return_value = True
    fake_docling.extract = AsyncMock(return_value="docling extracted text")

    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf", AsyncMock(return_value=("garbled \x00\x01", False))
    )
    monkeypatch.setattr(service, "_docling_client_factory", lambda: fake_docling)

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["success"] is True
    assert result["extraction_method"] == "Docling (docling-serve)"
    # Cost fields are internal-only accounting — never in the response.
    assert "processing_cost_usd" not in result
    assert "cost_breakdown" not in result
    assert result["extracted_content"] == "docling extracted text"


async def test_all_tiers_fail_returns_error_shape(monkeypatch):
    fake_docling = MagicMock()
    fake_docling.is_available.return_value = False  # DOCLING_SERVE_URL unset

    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf", AsyncMock(return_value=("garbled \x00\x01", False))
    )
    monkeypatch.setattr(
        service,
        "extract_with_mistral_ocr",
        AsyncMock(side_effect=ValueError("MISTRAL_API_KEY required for OCR extraction")),
    )
    monkeypatch.setattr(service, "_docling_client_factory", lambda: fake_docling)

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["success"] is False
    assert "error" in result
    assert result["status_code"] == 400


# --------------------------------------------------------------------- M-19


async def test_concurrent_extractions_cannot_both_pass_a_one_call_budget(monkeypatch):
    """M-19: the spend ceiling was a check-then-act.

    The lock was held only to READ the running total; the paid round trip
    ran outside it. Two concurrent extractions therefore both saw the same
    pre-call total and both were admitted against a budget with room for one.
    """
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key-for-tests")
    # Room for exactly one 3-page call (3 * $0.001), plus a hair.
    monkeypatch.setenv("MISTRAL_OCR_DAILY_BUDGET_USD", "0.0035")

    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "file-123"})
        # Hold the first OCR call open so the second one reaches the budget
        # gate while the first is still in flight — the exact interleaving
        # the check-then-act admitted.
        started.set()
        await release.wait()
        return httpx.Response(
            200,
            json={
                "usage_info": {"pages_processed": 3},
                "pages": [{"index": 0, "markdown": "page one text"}],
            },
        )

    mock_transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        de_module.httpx, "AsyncClient",
        lambda *a, **kw: real_async_client(transport=mock_transport),
    )

    service = _make_service()

    async def first():
        return await service.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=3)

    async def second():
        await started.wait()
        try:
            return await service.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=3)
        finally:
            release.set()

    results = await asyncio.gather(first(), second(), return_exceptions=True)

    refused = [
        r for r in results
        if isinstance(r, ValueError) and "capacity limit" in str(r)
    ]
    assert len(refused) == 1, results
    assert de_module._mistral_daily_cost_state["total"] == pytest.approx(0.003)


async def test_a_failed_ocr_call_gives_its_reservation_back(monkeypatch):
    """A reservation that is never spent must not consume the day's budget."""
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key-for-tests")
    monkeypatch.setenv("MISTRAL_OCR_DAILY_BUDGET_USD", "1.0")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream down"})

    mock_transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        de_module.httpx, "AsyncClient",
        lambda *a, **kw: real_async_client(transport=mock_transport),
    )

    service = _make_service()

    with pytest.raises(Exception):
        await service.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=3)

    assert de_module._mistral_daily_cost_state["total"] == pytest.approx(0.0)


async def test_an_unknown_page_count_does_not_reach_the_docling_tier(monkeypatch):
    """L-18: page_count 0 satisfied `0 <= DOCLING_MAX_PAGES`, so a document
    of entirely unknown size was admitted to the 300-second CPU tier."""
    from fpd_mcp.api.docling_client import DoclingClient

    monkeypatch.setenv("DOCLING_SERVE_URL", "http://docling.invalid")
    client = DoclingClient()

    assert client.within_page_limit(0) is False
    assert client.within_page_limit(-1) is False
    assert client.within_page_limit(10) is True
    assert client.within_page_limit(client.max_pages + 1) is False


def test_a_malformed_docling_page_cap_does_not_raise(monkeypatch):
    """F-D2: the constructor runs inside the extraction fallback, whose
    caller maps ValueError to a 400 "extraction failed" — a configuration
    error reported to the user as a bad request."""
    from fpd_mcp.api.docling_client import DoclingClient, _DEFAULT_MAX_PAGES

    monkeypatch.setenv("DOCLING_MAX_PAGES", "twenty-five")
    monkeypatch.setenv("DOCLING_TIMEOUT", "soon")

    client = DoclingClient()

    assert client.max_pages == _DEFAULT_MAX_PAGES
