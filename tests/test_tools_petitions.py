"""Tool-level tests for the 5 search/details tools in tools/petitions.py.

Each test calls the real tool function (not through FastMCP) with
`mock_runtime` patched, so `get_fpd_service()` returns a real FPDService
wrapping a mocked FPDClient. Asserts top-level response keys and that the
mocked client received the expected arguments.
"""

from fpd_mcp.tools.petitions import (
    fpd_get_petition_details,
    fpd_search_petitions_balanced,
    fpd_search_petitions_by_application,
    fpd_search_petitions_by_art_unit,
    fpd_search_petitions_minimal,
)

_PETITION_ID = "e55bd36d-961f-511e-b72c-b4b1529d67ef"


def _search_result(count=1):
    return {
        "petitionDecisionDataBag": [
            {
                "petitionDecisionRecordIdentifier": _PETITION_ID,
                "applicationNumberText": "17896175",
                "patentNumber": "11788453",
                "firstApplicantName": "TechCorp Inc.",
                "decisionTypeCodeDescriptionText": "DENIED",
                "petitionMailDate": "2024-01-01",
                "decisionDate": "2024-02-01",
                "finalDecidingOfficeName": "OFFICE OF PETITIONS",
            }
        ],
        "count": count,
    }


async def test_search_petitions_minimal_returns_expected_keys(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_minimal(applicant_name="TechCorp Inc.", limit=50)

    assert "error" not in result
    assert "petitionDecisionDataBag" in result
    assert "query_info" in result
    assert "llm_guidance" in result
    assert result["query_info"]["tier"] == "minimal"

    mock_runtime.api_client.search_petitions.assert_awaited_once()
    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert 'firstApplicantName:"TechCorp Inc."' in kwargs["query"]
    assert kwargs["limit"] == 50
    assert kwargs["offset"] == 0


async def test_search_petitions_minimal_propagates_error(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = {
        "error": "boom", "status_code": 500, "success": False,
    }

    result = await fpd_search_petitions_minimal(query="foo")

    assert result["error"] == "boom"


async def test_search_petitions_minimal_rejects_bad_limit(mock_runtime):
    result = await fpd_search_petitions_minimal(query="foo", limit=0)

    assert result["error"]
    assert result["status_code"] == 400
    mock_runtime.api_client.search_petitions.assert_not_awaited()


async def test_search_petitions_balanced_returns_expected_keys(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_balanced(art_unit="2128", petition_type_code="551", limit=20)

    assert "error" not in result
    assert "petitionDecisionDataBag" in result
    assert result["query_info"]["tier"] == "balanced"

    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert "groupArtUnitNumber:2128" in kwargs["query"]
    assert "decisionPetitionTypeCode:551" in kwargs["query"]
    assert kwargs["limit"] == 20


async def test_search_petitions_balanced_rejects_bad_offset(mock_runtime):
    result = await fpd_search_petitions_balanced(query="foo", offset=-1)

    assert result["error"] == "Offset must be non-negative"
    mock_runtime.api_client.search_petitions.assert_not_awaited()


async def test_search_petitions_by_art_unit_returns_expected_keys(mock_runtime):
    mock_runtime.api_client.search_by_art_unit.return_value = _search_result()

    result = await fpd_search_petitions_by_art_unit(art_unit="2128", date_range="2020-01-01:2024-12-31")

    assert "error" not in result
    assert "petitionDecisionDataBag" in result
    assert "llm_guidance" in result

    mock_runtime.api_client.search_by_art_unit.assert_awaited_once_with(
        art_unit="2128", date_range="2020-01-01:2024-12-31", limit=50
    )


async def test_search_petitions_by_art_unit_rejects_bad_date_range(mock_runtime):
    result = await fpd_search_petitions_by_art_unit(art_unit="2128", date_range="not-a-range")

    assert result["status_code"] == 400
    mock_runtime.api_client.search_by_art_unit.assert_not_awaited()


async def test_search_petitions_by_application_returns_expected_keys(mock_runtime):
    mock_runtime.api_client.search_by_application.return_value = _search_result()

    result = await fpd_search_petitions_by_application(application_number="17896175")

    assert "error" not in result
    assert "petitionDecisionDataBag" in result
    assert "llm_guidance" in result

    mock_runtime.api_client.search_by_application.assert_awaited_once_with(
        application_number="17896175", include_documents=False
    )


async def test_search_petitions_by_application_rejects_bad_number(mock_runtime):
    result = await fpd_search_petitions_by_application(application_number="abc")

    assert result["status_code"] == 400
    mock_runtime.api_client.search_by_application.assert_not_awaited()


async def test_get_petition_details_returns_expected_keys(mock_runtime):
    detail = {
        "petitionDecisionDataBag": [
            {
                "petitionDecisionRecordIdentifier": _PETITION_ID,
                "documentBag": [],
            }
        ]
    }
    mock_runtime.api_client.get_petition_by_id.return_value = detail

    result = await fpd_get_petition_details(petition_id=_PETITION_ID)

    assert "error" not in result
    assert "petitionDecisionDataBag" in result
    assert "llm_guidance" in result

    mock_runtime.api_client.get_petition_by_id.assert_awaited_once_with(
        petition_id=_PETITION_ID, include_documents=True
    )


async def test_get_petition_details_rejects_bad_uuid(mock_runtime):
    result = await fpd_get_petition_details(petition_id="not-a-uuid")

    assert result["status_code"] == 400
    mock_runtime.api_client.get_petition_by_id.assert_not_awaited()
