"""Tool-level tests for the 2 document tools in tools/documents.py.

fpd_get_document_download's success path exercises the local-proxy branch of
_deliver_download_link; the heavier network side effects (centralized proxy
probe, recent-downloads registration, URL elicitation) are stubbed out since
they are separate concerns covered by tests/test_proxy_and_views.py. ctx is
left at its default (None), which already short-circuits URL elicitation.
"""

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
    def generate_persistent_link(self, **kwargs):
        return "http://localhost:8081/download/persistent/fakehash"


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
        "extraction_method": "PyPDF2",
        "processing_cost_usd": 0.0,
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
