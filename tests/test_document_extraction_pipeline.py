"""Offline mocked tests for the 3-tier hybrid extraction pipeline
(services/document_extraction.py): pypdf tier success, pypdf-fails ->
Mistral tier (with M3 daily-cost accumulation), Mistral-disabled -> Docling
tier gate, and the all-tiers-fail error shape.

No network calls: the owning "client" (petition lookup + PDF download) and
the Mistral/Docling network boundaries are all mocked/stubbed.
"""

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
        service, "extract_with_pypdf2", AsyncMock(return_value=(_GOOD_TEXT, False))
    )

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["success"] is True
    assert result["extraction_method"] == "PyPDF2"
    assert result["processing_cost_usd"] == 0.0
    assert result["extracted_content"] == _GOOD_TEXT


async def test_pypdf_fails_falls_back_to_mistral_with_cost(monkeypatch):
    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf2", AsyncMock(return_value=("garbled \x00\x01", False))
    )
    monkeypatch.setattr(
        service, "extract_with_mistral_ocr", AsyncMock(return_value=("mistral extracted text", 0.003))
    )

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["success"] is True
    assert result["extraction_method"].startswith("Mistral OCR")
    assert result["processing_cost_usd"] == pytest.approx(0.003)
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
        service, "extract_with_pypdf2", AsyncMock(return_value=("garbled \x00\x01", False))
    )
    monkeypatch.setattr(service, "_docling_client_factory", lambda: fake_docling)

    result = await service.extract_document_content_hybrid(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, auto_optimize=True
    )

    assert result["success"] is True
    assert result["extraction_method"] == "Docling (docling-serve)"
    assert result["processing_cost_usd"] == 0.0
    assert result["extracted_content"] == "docling extracted text"


async def test_all_tiers_fail_returns_error_shape(monkeypatch):
    fake_docling = MagicMock()
    fake_docling.is_available.return_value = False  # DOCLING_SERVE_URL unset

    service = _make_service()
    monkeypatch.setattr(
        service, "extract_with_pypdf2", AsyncMock(return_value=("garbled \x00\x01", False))
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
