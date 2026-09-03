"""Tests for the application-file-wrapper fallback path
(api/fpd_client.py's get_petition_by_id / get_application_documents), added
because USPTO's petition-details endpoint 500s upstream for
includeDocuments=true (verified live 2026-07-10, broken since at least
2026-07-04 — see tests/TEST_SUITE.md).

FPD documentBag identifiers are also application file-wrapper document
identifiers, so when the with-documents call comes back as a 5xx-class error
envelope, get_petition_by_id transparently retries without documents and
reconstructs documentBag from the application file-wrapper documents
endpoint (get_application_documents) — the wrapper's raw documentBag entries
already use the exact same field names FPD's own documentBag entries do
(documentIdentifier/documentCode/documentCodeDescriptionText/
downloadOptionBag[mimeTypeIdentifier/downloadUrl/pageTotalQuantity]), so no
field renaming is needed for downstream consumers.

Client-level tests mock only `_make_request` (the network boundary) on a
real FPDClient so the actual orchestration logic in get_petition_by_id /
_petition_documents_via_wrapper_fallback / get_application_documents runs for
real. Tool-level tests use the existing `mock_runtime` fixture (pure-mock
api_client) to confirm the fallback-produced shape passes through the tools
unchanged, matching the conventions in test_tools_petitions.py /
test_tools_documents.py.
"""

import copy

from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.tools.documents import _resolve_document_metadata
from fpd_mcp.tools.petitions import fpd_get_petition_details

_PETITION_ID = "e55bd36d-961f-511e-b72c-b4b1529d67ef"
_APP_NUMBER = "13408005"
_DOC_ID = "HY1J6ICXPXXIFW4"
_DOWNLOAD_URL = f"https://api.uspto.gov/api/v1/download/applications/{_APP_NUMBER}/{_DOC_ID}.pdf"

_UPSTREAM_500 = {
    "error": "API error: Internal Server Error",
    "status_code": 500,
    "success": False,
    "request_id": "abcd1234",
}


def _without_docs_result():
    """Fresh copy each call — the fallback mutates this dict in place, so a
    shared module-level constant would leak state between tests."""
    return {
        "petitionDecisionDataBag": [
            {
                "petitionDecisionRecordIdentifier": _PETITION_ID,
                "applicationNumberText": _APP_NUMBER,
                "patentNumber": "9999999",
                "decisionTypeCodeDescriptionText": "GRANTED",
            }
        ],
        "count": 1,
    }


def _wrapper_result():
    return {
        "count": 2,
        "documentBag": [
            {
                "documentIdentifier": _DOC_ID,
                "documentCode": "PPH.DECISION",
                "documentCodeDescriptionText": "Decision on Petition",
                "officialDate": "2020-01-02",
                "downloadOptionBag": [
                    {
                        "mimeTypeIdentifier": "PDF",
                        "downloadUrl": _DOWNLOAD_URL,
                        "pageTotalQuantity": 1,
                    }
                ],
            },
            {
                "documentIdentifier": "OTHERDOC123",
                "documentCode": "CTNF",
                "documentCodeDescriptionText": "Non-Final Rejection",
                "downloadOptionBag": [],
            },
        ],
    }


def _client() -> FPDClient:
    return FPDClient(api_key="test-key-1234567890")


# --------------------------------------------------------------------- #
# Client-level: real get_petition_by_id fallback orchestration
# --------------------------------------------------------------------- #

async def test_fallback_engages_on_upstream_500(monkeypatch):
    client = _client()
    calls = []

    async def fake_make_request(endpoint, method="GET", base_url=None, **kwargs):
        calls.append((endpoint, base_url, kwargs.get("params")))
        if base_url == client.applications_base_url:
            return _wrapper_result()
        if (kwargs.get("params") or {}).get("includeDocuments") == "true":
            return dict(_UPSTREAM_500)
        return _without_docs_result()

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    result = await client.get_petition_by_id(_PETITION_ID, include_documents=True)

    assert "error" not in result
    assert result["document_metadata_source"] == "application_file_wrapper_fallback"
    assert isinstance(result.get("document_metadata_note"), str) and result["document_metadata_note"]

    petition_record = result["petitionDecisionDataBag"][0]
    # Existing fields untouched
    assert petition_record["applicationNumberText"] == _APP_NUMBER
    assert petition_record["decisionTypeCodeDescriptionText"] == "GRANTED"
    # documentBag reconstructed from the wrapper and contains the target doc
    doc_ids = [d["documentIdentifier"] for d in petition_record["documentBag"]]
    assert _DOC_ID in doc_ids

    # pageCount backfilled from the PDF downloadOptionBag's pageTotalQuantity
    # (the wrapper's raw entries only carry pageTotalQuantity, not a
    # top-level pageCount — needed by document_extraction.py's OCR resolver)
    target_doc = next(d for d in petition_record["documentBag"] if d["documentIdentifier"] == _DOC_ID)
    assert target_doc["pageCount"] == 1
    # a doc with no PDF download option is left alone (no crash, no bogus 0)
    other_doc = next(d for d in petition_record["documentBag"] if d["documentIdentifier"] == "OTHERDOC123")
    assert "pageCount" not in other_doc

    # with-docs (500) -> without-docs -> wrapper documents
    assert len(calls) == 3
    assert calls[1][1] is None  # without-docs call uses the default (petition-decisions) host
    assert calls[2][1] == client.applications_base_url
    assert calls[2][0] == f"{_APP_NUMBER}/documents"


async def test_fallback_not_triggered_on_404(monkeypatch):
    client = _client()
    calls = []

    async def fake_make_request(endpoint, method="GET", base_url=None, **kwargs):
        calls.append(endpoint)
        return {"error": "API error: not found", "status_code": 404, "success": False}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    result = await client.get_petition_by_id(_PETITION_ID, include_documents=True)

    assert result["status_code"] == 404
    assert len(calls) == 1  # no retry-without-docs, no wrapper fetch


async def test_fallback_not_triggered_on_clean_success(monkeypatch):
    client = _client()
    calls = []
    success = {
        "petitionDecisionDataBag": [
            {"applicationNumberText": _APP_NUMBER, "documentBag": [{"documentIdentifier": _DOC_ID}]}
        ]
    }

    async def fake_make_request(endpoint, method="GET", base_url=None, **kwargs):
        calls.append(endpoint)
        return success

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    result = await client.get_petition_by_id(_PETITION_ID, include_documents=True)

    assert result is success
    assert "document_metadata_source" not in result
    assert len(calls) == 1


async def test_fallback_degrades_when_wrapper_fetch_also_fails(monkeypatch):
    client = _client()

    async def fake_make_request(endpoint, method="GET", base_url=None, **kwargs):
        if base_url == client.applications_base_url:
            return {"error": "API error: wrapper down", "status_code": 503, "success": False}
        if (kwargs.get("params") or {}).get("includeDocuments") == "true":
            return dict(_UPSTREAM_500)
        return _without_docs_result()

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    result = await client.get_petition_by_id(_PETITION_ID, include_documents=True)

    assert "error" not in result
    assert "documentBag" not in result["petitionDecisionDataBag"][0]
    # The degraded path is now MARKED: an absent documentBag must never be
    # mistaken for "this petition has no documents".
    assert result["document_metadata_available"] is False
    assert result["document_metadata_source"] == "unavailable"
    assert "could NOT be retrieved" in result["document_metadata_note"]


async def test_fallback_propagates_error_when_without_docs_also_fails(monkeypatch):
    client = _client()

    async def fake_make_request(endpoint, method="GET", base_url=None, **kwargs):
        if (kwargs.get("params") or {}).get("includeDocuments") == "true":
            return dict(_UPSTREAM_500)
        return {"error": "API error: not found", "status_code": 404, "success": False}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    result = await client.get_petition_by_id(_PETITION_ID, include_documents=True)

    assert result["status_code"] == 404


async def test_get_application_documents_uses_applications_host(monkeypatch):
    client = _client()
    captured = {}

    async def fake_make_request(endpoint, method="GET", base_url=None, **kwargs):
        captured["endpoint"] = endpoint
        captured["base_url"] = base_url
        return {"documentBag": []}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    result = await client.get_application_documents(_APP_NUMBER)

    assert captured["endpoint"] == f"{_APP_NUMBER}/documents"
    assert captured["base_url"] == "https://api.uspto.gov/api/v1/patent/applications"
    assert result == {"documentBag": []}


# --------------------------------------------------------------------- #
# _resolve_document_metadata: wrapper-shaped documentBag compatibility
# --------------------------------------------------------------------- #

def test_resolve_document_metadata_resolves_wrapper_shaped_bag():
    petition_result = copy.deepcopy(_without_docs_result())
    petition_result["petitionDecisionDataBag"][0]["documentBag"] = _wrapper_result()["documentBag"]
    petition_result["document_metadata_source"] = "application_file_wrapper_fallback"

    resolved = _resolve_document_metadata(petition_result, _PETITION_ID, _DOC_ID)

    assert "error" not in resolved
    assert resolved["pdf_download_url"] == _DOWNLOAD_URL
    assert resolved["page_count"] == 1
    assert resolved["document_metadata"]["documentIdentifier"] == _DOC_ID


def test_resolve_document_metadata_unmatched_identifier_still_errors():
    petition_result = copy.deepcopy(_without_docs_result())
    petition_result["petitionDecisionDataBag"][0]["documentBag"] = _wrapper_result()["documentBag"]

    resolved = _resolve_document_metadata(petition_result, _PETITION_ID, "NOT-A-REAL-DOC-ID")

    assert "error" in resolved
    assert resolved["status_code"] == 404


# --------------------------------------------------------------------- #
# F-X3: an empty bag on a petition marked document_metadata_available=False
# is "we could not look", not "the document is absent"
# --------------------------------------------------------------------- #

def test_download_reports_unavailable_metadata_as_503_not_404():
    petition_result = FPDClient._mark_document_metadata_unavailable(
        copy.deepcopy(_without_docs_result()),
        "the application file-wrapper documents endpoint also failed",
    )

    resolved = _resolve_document_metadata(petition_result, _PETITION_ID, _DOC_ID)

    assert resolved["status_code"] == 503
    assert "not found" not in resolved["error"].lower()
    assert "temporarily unavailable" in resolved["error"]


def _extraction_service(client):
    import httpx

    from fpd_mcp.services.document_extraction import DocumentExtractionService

    return DocumentExtractionService(
        client=client, download_timeout=5.0, connection_limits=httpx.Limits()
    )


async def test_extraction_reports_unavailable_metadata_as_503_not_404(monkeypatch):
    petition_result = FPDClient._mark_document_metadata_unavailable(
        copy.deepcopy(_without_docs_result()),
        "the application file-wrapper documents endpoint also failed",
    )

    class _Client:
        async def get_petition_by_id(self, petition_id, include_documents=True):
            return petition_result

    service = _extraction_service(_Client())
    resolved = await service._resolve_document_for_hybrid_extraction(
        _PETITION_ID, _DOC_ID, "req-1"
    )

    assert resolved["status_code"] == 503
    assert "not found" not in resolved["error"].lower()


async def test_extraction_still_404s_when_the_bag_was_actually_retrieved():
    petition_result = copy.deepcopy(_without_docs_result())
    petition_result["petitionDecisionDataBag"][0]["documentBag"] = (
        _wrapper_result()["documentBag"]
    )

    class _Client:
        async def get_petition_by_id(self, petition_id, include_documents=True):
            return petition_result

    service = _extraction_service(_Client())
    resolved = await service._resolve_document_for_hybrid_extraction(
        _PETITION_ID, "NOT-A-REAL-DOC-ID", "req-2"
    )

    assert resolved["status_code"] == 404


# --------------------------------------------------------------------- #
# Tool-level: FPD_Get_petition_details surfaces the fallback-produced shape
# unchanged (existing keys preserved, additive keys pass through)
# --------------------------------------------------------------------- #

async def test_get_petition_details_surfaces_fallback_metadata(mock_runtime):
    merged = copy.deepcopy(_without_docs_result())
    merged["petitionDecisionDataBag"][0]["documentBag"] = _wrapper_result()["documentBag"]
    merged["document_metadata_source"] = "application_file_wrapper_fallback"
    merged["document_metadata_note"] = "USPTO's includeDocuments=true endpoint is erroring upstream."
    mock_runtime.api_client.get_petition_by_id.return_value = merged

    result = await fpd_get_petition_details(petition_id=_PETITION_ID, include_documents=True)

    assert "error" not in result
    assert result["document_metadata_source"] == "application_file_wrapper_fallback"
    assert result["petitionDecisionDataBag"][0]["applicationNumberText"] == _APP_NUMBER
    doc_ids = [d["documentIdentifier"] for d in result["petitionDecisionDataBag"][0]["documentBag"]]
    assert _DOC_ID in doc_ids
    # Existing behavior (llm_guidance) untouched by the additive keys
    assert "llm_guidance" in result
