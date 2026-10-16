"""Tool-level tests for the 2 document tools in tools/documents.py.

fpd_get_document_download's success path exercises the local-proxy branch of
_deliver_download_link; the heavier network side effects (centralized proxy
probe, recent-downloads registration) are stubbed out since they are separate
concerns covered by tests/test_proxy_and_views.py.
"""

from datetime import timedelta
from unittest.mock import AsyncMock

import fpd_mcp.proxy.centralized_integration as centralized_integration
import fpd_mcp.proxy.secure_link_cache as secure_link_cache
import fpd_mcp.tools.documents as documents_module
from fpd_mcp.tools.documents import fpd_get_document_content, fpd_get_document_download

_PETITION_ID = "e55bd36d-961f-511e-b72c-b4b1529d67ef"
_DOCUMENT_ID = "ABCD1234EFGH"


def _petition_with_document():
    return {
        "petitionDecisionDataBag": [
            {
                "petitionMailDate": "2024-01-01",
                "applicationNumberText": "17896175",
                "patentNumber": "11788453",
                "decisionPetitionTypeCodeDescriptionText": "Revival",
                "decisionTypeCodeDescriptionText": "DENIED",
                "decisionDate": "2024-02-01",
                "documentBag": [
                    {
                        "documentIdentifier": _DOCUMENT_ID,
                        "documentCode": "PET",
                        "documentCodeDescriptionText": "Petition",
                        "downloadOptionBag": [
                            {
                                "mimeTypeIdentifier": "PDF",
                                "downloadUrl": "https://api.uspto.gov/fake.pdf",
                                "pageTotalQuantity": 5,
                            }
                        ],
                    }
                ],
            }
        ]
    }


class _FakeLinkCache:
    cache_duration = timedelta(days=1)
    max_uses = 25

    def generate_persistent_link(self, **kwargs):
        return "http://localhost:8081/download/persistent/fakehash"

    async def mint_persistent_link(self, **kwargs):
        return self.generate_persistent_link(**kwargs)


async def test_get_document_download_success(mock_runtime, monkeypatch):
    mock_runtime.api_client.get_petition_by_id.return_value = _petition_with_document()

    monkeypatch.setattr(centralized_integration, "get_centralized_base_url", lambda: None)
    monkeypatch.setattr(secure_link_cache, "get_link_cache", lambda: _FakeLinkCache())
    monkeypatch.setattr(documents_module, "_ensure_proxy_server_running", AsyncMock())
    monkeypatch.setattr(
        documents_module, "_register_download_via_proxy", AsyncMock(return_value="reg-id-1")
    )

    result = await fpd_get_document_download(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID
    )

    assert result["success"] is True
    assert result["download_url"] == "http://localhost:8081/download/persistent/fakehash"
    assert result["petition_id"] == _PETITION_ID
    assert result["document_identifier"] == _DOCUMENT_ID
    assert result["proxy_info"]["mode"] == "local"

    mock_runtime.api_client.get_petition_by_id.assert_awaited_once_with(
        _PETITION_ID, include_documents=True
    )


async def test_get_document_download_document_not_found(mock_runtime):
    mock_runtime.api_client.get_petition_by_id.return_value = _petition_with_document()

    result = await fpd_get_document_download(
        petition_id=_PETITION_ID, document_identifier="ZZZZ9999YYYY"
    )

    assert result["status_code"] == 404


async def test_get_document_download_rejects_bad_petition_id(mock_runtime):
    result = await fpd_get_document_download(
        petition_id="not-a-uuid", document_identifier=_DOCUMENT_ID
    )

    assert result["status_code"] == 400
    mock_runtime.api_client.get_petition_by_id.assert_not_awaited()


async def test_get_document_download_propagates_petition_lookup_error(mock_runtime):
    mock_runtime.api_client.get_petition_by_id.return_value = {
        "error": "not found", "status_code": 404, "success": False,
    }

    result = await fpd_get_document_download(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID
    )

    assert result["error"] == "not found"


async def test_get_document_content_returns_expected_keys(mock_runtime):
    mock_runtime.api_client.extract_document_content_hybrid.return_value = {
        "success": True,
        "document_code": "PET",
        "page_count": 5,
        "extracted_content": "some petition text",
        "extraction_method": "pypdf",
    }

    result = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID
    )

    assert result["success"] is True
    assert result["extracted_content"] == "some petition text"
    assert "llm_guidance" in result

    mock_runtime.api_client.extract_document_content_hybrid.assert_awaited_once()
    _, kwargs = mock_runtime.api_client.extract_document_content_hybrid.call_args
    assert kwargs["petition_id"] == _PETITION_ID
    assert kwargs["document_identifier"] == _DOCUMENT_ID
    assert kwargs["auto_optimize"] is True


async def test_get_document_content_carries_cite_as_and_the_quoting_rule(mock_runtime):
    # A claude.ai run linked the wrong application and "fixed" the Office's
    # wording in a quoted decision (2026-10-07): the response now hands back
    # the verified link and says to quote exactly.
    mock_runtime.api_client.extract_document_content_hybrid.return_value = {
        "success": True,
        "document_code": "PETDEC",
        "page_count": 4,
        "extracted_content": "The petition under 37 CFR 1.137(a) is DISMISSED.",
        "extraction_method": "docx variant",
        "application_number": "16724244",
        "patent_number": None,
        "decision_date": "2026-10-02",
    }

    result = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID
    )

    assert result["cite_as"] == (
        "[Petition decision 2026-10-02, application 16/724,244]"
        "(https://patentcenter.uspto.gov/applications/16724244)"
    )
    assert "never correct" in result["quoting_rule"]
    assert "patent_number" not in result and "decision_date" not in result
    assert result["application_number"] == "16724244"


def _long_ocr_result(pages: int = 40, page_chars: int = 4_000):
    text = "\n\n".join(
        f"=== PAGE {i} ===\n" + ("word " * (page_chars // 5)) for i in range(1, pages + 1)
    )
    return {
        "success": True,
        "document_code": "PET",
        "page_count": pages,
        "extracted_content": text,
        "extraction_method": "Mistral OCR (mistral-ocr-latest)",
    }


async def test_get_document_content_windows_long_text_with_a_cursor(mock_runtime):
    full = _long_ocr_result()
    full_text = full["extracted_content"]
    mock_runtime.api_client.extract_document_content_hybrid.return_value = dict(full)

    result = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, max_chars=20_000
    )

    window = result["_window"]
    # CR-D (review 2026-09-28): re-vendored from PTAB — `edges` records the
    # `=== PAGE N ===` snapping; `unit` names the counters and is always
    # "char".
    assert window["edges"] == "page"
    assert window["unit"] == "char"
    assert window["offset"] == 0
    assert window["total"] == len(full_text)
    assert window["has_more"] is True
    assert window["returned"] <= 20_000
    assert result["extracted_content"] == full_text[: window["next_offset"]]
    # Legacy aliases kept alongside the new vocabulary.
    assert result["truncated"] is True
    assert "char_offset" in result["truncation_note"]


async def test_get_document_content_cursor_reaches_the_remainder(mock_runtime):
    full = _long_ocr_result()
    full_text = full["extracted_content"]
    mock_runtime.api_client.extract_document_content_hybrid.return_value = dict(full)

    first = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, max_chars=20_000
    )

    mock_runtime.api_client.extract_document_content_hybrid.return_value = dict(full)
    second = await fpd_get_document_content(
        petition_id=_PETITION_ID,
        document_identifier=_DOCUMENT_ID,
        char_offset=first["_window"]["next_offset"],
        max_chars=20_000,
    )

    assert second["_window"]["offset"] == first["_window"]["next_offset"]
    assert second["extracted_content"] == full_text[
        second["_window"]["offset"]:second["_window"]["next_offset"]
    ]


async def test_get_document_content_short_text_has_no_window(mock_runtime):
    mock_runtime.api_client.extract_document_content_hybrid.return_value = {
        "success": True,
        "extracted_content": "short petition text",
    }

    result = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID
    )

    assert "_window" not in result
    assert "truncated" not in result
    assert result["extracted_content"] == "short petition text"


async def test_get_document_content_rejects_bad_cursor_params(mock_runtime):
    bad_offset = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, char_offset=-1
    )
    bad_max = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, max_chars=0
    )

    assert bad_offset["status_code"] == 400
    assert bad_max["status_code"] == 400
    mock_runtime.api_client.extract_document_content_hybrid.assert_not_awaited()


async def test_get_document_content_rejects_bad_document_identifier(mock_runtime):
    result = await fpd_get_document_content(petition_id=_PETITION_ID, document_identifier="!!")

    assert result["status_code"] == 400
    mock_runtime.api_client.extract_document_content_hybrid.assert_not_awaited()


async def test_get_document_content_propagates_error(mock_runtime):
    mock_runtime.api_client.extract_document_content_hybrid.return_value = {
        "error": "extraction failed", "status_code": 400, "success": False,
    }

    result = await fpd_get_document_content(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID
    )

    assert result["error"] == "extraction failed"


# --------------------------------------------------------------------- F-X2


async def test_content_extraction_has_an_overall_deadline(mock_runtime, monkeypatch):
    """F-X2: one call could serially spend a petition fetch, a PDF download,
    a pypdf parse, a Mistral round trip and then Docling, with nothing
    budgeting the sum. Past a typical client timeout the caller saw a
    transport failure with no envelope, no request id and no recovery note.
    """
    import asyncio

    from fpd_mcp.tools import documents as documents_module

    # Re-pinned 2026-10-06 (Wave 2 A.5): the budget is now
    # FPD_CONTENT_DEADLINE_SECONDS (util/deadline.py, default 85, was
    # FPD_TOOL_DEADLINE_SECONDS=150) and the envelope leads with
    # "Deadline exceeded"; the 408 and the recovery text are unchanged.
    monkeypatch.setenv("FPD_CONTENT_DEADLINE_SECONDS", "1")

    async def never_returns(*args, **kwargs):
        await asyncio.sleep(30)

    mock_runtime.api_client.extract_document_content_hybrid = never_returns

    result = await documents_module.fpd_get_document_content(
        petition_id="e55bd36d-961f-511e-b72c-b4b1529d67ef",
        document_identifier="HY1J6ICXPXXIFW4",
    )

    assert result["status_code"] == 408
    assert result["error"].startswith("Deadline exceeded")
    assert "time budget" in result["error"]
    assert "FPD_get_document_download" in result["error"]


def test_an_unparseable_deadline_falls_back_to_the_default(monkeypatch):
    # Re-pinned 2026-10-06 (Wave 2 A.5): the parser moved to util/deadline.py
    # under the new variable name.
    from fpd_mcp.util.deadline import (
        DEFAULT_CONTENT_DEADLINE_SECONDS,
        content_deadline_seconds,
    )

    monkeypatch.setenv("FPD_CONTENT_DEADLINE_SECONDS", "soon")
    assert content_deadline_seconds() == DEFAULT_CONTENT_DEADLINE_SECONDS

    monkeypatch.setenv("FPD_CONTENT_DEADLINE_SECONDS", "30")
    assert content_deadline_seconds() == 30.0


async def test_a_caller_proxy_port_never_chooses_the_bind_port(mock_runtime, monkeypatch):
    """S4 (2026-10-12 audit): proxy_port used to decide which loopback port
    the server bound and which port the link named. It is now ignored, and
    the response says so."""
    mock_runtime.api_client.get_petition_by_id.return_value = _petition_with_document()
    ensure = AsyncMock()
    minted = {}

    class _RecordingLinkCache(_FakeLinkCache):
        async def mint_persistent_link(self, **kwargs):
            minted.update(kwargs)
            return self.generate_persistent_link(**kwargs)

    monkeypatch.delenv("FPD_PROXY_BASE_URL", raising=False)
    monkeypatch.setenv("FPD_PROXY_PORT", "8081")
    monkeypatch.setattr(centralized_integration, "get_centralized_base_url", lambda: None)
    monkeypatch.setattr(secure_link_cache, "get_link_cache", lambda: _RecordingLinkCache())
    monkeypatch.setattr(documents_module, "_ensure_proxy_server_running", ensure)
    monkeypatch.setattr(
        documents_module, "_register_download_via_proxy", AsyncMock(return_value=None)
    )

    result = await fpd_get_document_download(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, proxy_port=5001
    )

    assert result["success"] is True
    ensure.assert_awaited_once_with(8081)
    assert minted["base_url"] == "http://localhost:8081"
    assert "5001" in result["proxy_port_note"] and "ignored" in result["proxy_port_note"]


async def test_the_configured_proxy_port_needs_no_note(mock_runtime, monkeypatch):
    mock_runtime.api_client.get_petition_by_id.return_value = _petition_with_document()
    monkeypatch.setenv("FPD_PROXY_PORT", "8081")
    monkeypatch.setattr(centralized_integration, "get_centralized_base_url", lambda: None)
    monkeypatch.setattr(secure_link_cache, "get_link_cache", lambda: _FakeLinkCache())
    monkeypatch.setattr(documents_module, "_ensure_proxy_server_running", AsyncMock())
    monkeypatch.setattr(
        documents_module, "_register_download_via_proxy", AsyncMock(return_value=None)
    )

    result = await fpd_get_document_download(
        petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID, proxy_port=8081
    )

    assert result["success"] is True
    assert "proxy_port_note" not in result
