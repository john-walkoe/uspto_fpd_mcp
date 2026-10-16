"""Tier 0 of FPD_get_document_content_with_ocr: the Word (.docx) and XML
(xmlarchive) versions USPTO serves beside a petition decision's PDF (live
since the 2026-10 payload change, probed 2026-10-07 on petition
190d9855-9216-58ae-b37d-c838d16f441e). Read first on the auto path; the PDF is
never downloaded when one of them yields text for the right application.

Offline: the owning client is an AsyncMock, the variants are built in memory.
"""

import io
import tarfile
import zipfile
from unittest.mock import AsyncMock

import httpx

from fpd_mcp.api.field_constants import FPDFields
from fpd_mcp.services.document_extraction import DocumentExtractionService
from fpd_mcp.util.deadline import DeadlineExceeded

_PETITION_ID = "190d9855-9216-58ae-b37d-c838d16f441e"
_DOCUMENT_ID = "MUR3U7ROX247X37"
_APP = "16724244"
_DOCX_URL = f"https://api.uspto.gov/api/v1/download/applications/{_APP}/{_DOCUMENT_ID}/files/decision.docx"
_XML_URL = f"https://api.uspto.gov/api/v1/download/applications/{_APP}/{_DOCUMENT_ID}/xmlarchive"
_PDF_URL = f"https://api.uspto.gov/api/v1/download/applications/{_APP}/{_DOCUMENT_ID}.pdf"

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(text: str, app_number: str = "16/724,244") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{_W}"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
        )
        zf.writestr(
            "docProps/custom.xml",
            '<Properties xmlns="x" xmlns:vt="y"><property name="FormattedApplicationNumber">'
            f"<vt:lpwstr>{app_number}</vt:lpwstr></property></Properties>",
        )
    return buf.getvalue()


def _xmlarchive(text: str, app_number: str = _APP) -> bytes:
    xml = (
        '<uspat:OutgoingDocument xmlns:uspat="urn:us:gov:doc:uspto:patent" '
        'xmlns:uscom="urn:us:gov:doc:uspto:common"><uspat:DocumentMetadata>'
        f'<uscom:ApplicationNumberText uscom:electronicText="{app_number}">x</uscom:ApplicationNumberText>'
        f"</uspat:DocumentMetadata><uscom:P>{text}</uscom:P></uspat:OutgoingDocument>"
    ).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(f"{app_number}/{_DOCUMENT_ID}/decision.xml")
        info.size = len(xml)
        tf.addfile(info, io.BytesIO(xml))
    return buf.getvalue()


def _client(variants: dict):
    """variants: url -> bytes, or an Exception instance to raise."""
    payload = {
        FPDFields.PETITION_DECISION_DATA_BAG: [{
            FPDFields.APPLICATION_NUMBER_TEXT: _APP,
            FPDFields.DOCUMENT_BAG: [{
                FPDFields.DOCUMENT_IDENTIFIER: _DOCUMENT_ID,
                FPDFields.DOCUMENT_CODE: "PETDEC",
                FPDFields.PAGE_COUNT: 4,
                FPDFields.DOWNLOAD_OPTION_BAG: [
                    {"mimeTypeIdentifier": "PDF", "downloadUrl": _PDF_URL, "pageTotalQuantity": 4},
                    {"mimeTypeIdentifier": "MS_WORD", "downloadUrl": _DOCX_URL},
                    {"mimeTypeIdentifier": "PNG", "downloadUrl": _PDF_URL + ".png"},
                    {"mimeTypeIdentifier": "XML", "downloadUrl": _XML_URL},
                ],
            }],
        }]
    }

    async def fetch_variant(url):
        value = variants[url]
        if isinstance(value, BaseException):
            raise value
        return value

    client = AsyncMock()
    client.get_petition_by_id.return_value = payload
    client._download_variant_for_extraction.side_effect = fetch_variant
    client._download_pdf_for_extraction.return_value = b"%PDF-1.4 fake"
    return client


def _service(client) -> DocumentExtractionService:
    return DocumentExtractionService(client=client, download_timeout=5.0, connection_limits=httpx.Limits())


async def test_docx_variant_is_read_and_the_pdf_is_never_downloaded():
    client = _client({_DOCX_URL: _docx("The petition is DISMISSED."), _XML_URL: _xmlarchive("unused")})
    result = await _service(client).extract_document_content_hybrid(_PETITION_ID, _DOCUMENT_ID)
    assert result["success"] is True
    assert result["extraction_method"] == "docx variant"
    assert "The petition is DISMISSED." in result["extracted_content"]
    assert result["application_number_verified"] is True
    assert result["free_text_variants"] == [{"variant": "docx", "outcome": "used"}]
    assert result["page_count"] == 4
    client._download_pdf_for_extraction.assert_not_called()


async def test_xmlarchive_is_tried_when_the_docx_fails():
    client = _client({
        _DOCX_URL: httpx.HTTPStatusError("404", request=None, response=None),
        _XML_URL: _xmlarchive("The petition is GRANTED."),
    })
    result = await _service(client).extract_document_content_hybrid(_PETITION_ID, _DOCUMENT_ID)
    assert result["extraction_method"] == "xmlarchive (USPTO XML)"
    assert "The petition is GRANTED." in result["extracted_content"]
    assert [a["outcome"] for a in result["free_text_variants"]] == ["failed", "used"]
    client._download_pdf_for_extraction.assert_not_called()


async def test_a_variant_naming_another_application_falls_through_to_the_pdf(monkeypatch):
    client = _client({
        _DOCX_URL: _docx("wrong file", app_number="90/020,162"),
        _XML_URL: _xmlarchive("wrong file", app_number="90020162"),
    })
    service = _service(client)

    async def fake_pypdf(pdf_content, max_pages=200, status=None):
        return "pdf text " * 50, False

    monkeypatch.setattr(service, "extract_with_pypdf", fake_pypdf)
    result = await service.extract_document_content_hybrid(_PETITION_ID, _DOCUMENT_ID)
    assert result["extraction_method"] == "pypdf"
    assert [a["outcome"] for a in result["free_text_variants"]] == ["rejected", "rejected"]
    client._download_pdf_for_extraction.assert_awaited_once()


async def test_auto_optimize_false_skips_the_variants(monkeypatch):
    client = _client({_DOCX_URL: _docx("unused")})
    service = _service(client)

    async def fake_ocr(pdf_content, pages_requested):
        return "ocr text"

    monkeypatch.setattr(service, "_run_mistral_ocr", fake_ocr)
    result = await service.extract_document_content_hybrid(_PETITION_ID, _DOCUMENT_ID, auto_optimize=False)
    assert result["extracted_content"] == "ocr text"
    assert "free_text_variants" not in result
    client._download_variant_for_extraction.assert_not_called()


async def test_a_spent_deadline_is_not_swallowed_as_a_variant_failure():
    client = _client({_DOCX_URL: DeadlineExceeded()})
    result = await _service(client).extract_document_content_hybrid(_PETITION_ID, _DOCUMENT_ID)
    assert result.get("error", "").startswith("Deadline exceeded")
    client._download_pdf_for_extraction.assert_not_called()
