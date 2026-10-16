"""Tool-level tests for the 5 search/details tools in tools/petitions.py.

Each test calls the real tool function (not through FastMCP) with
`mock_runtime` patched, so `get_fpd_service()` returns a real FPDService
wrapping a mocked FPDClient. Asserts top-level response keys and that the
mocked client received the expected arguments.
"""

from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.config import api_constants
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
        art_unit="2128", date_range="2020-01-01:2024-12-31", limit=50, offset=0,
        final_only=False,
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
    assert result["paging"]["limit_requested"] == 100

    # D-3: the projection now comes from field_configs.yaml's
    # petitions_balanced set rather than a literal frozen in the client.
    mock_runtime.api_client.search_by_application.assert_awaited_once_with(
        application_number="17896175", include_documents=False, limit=100,
        offset=0,
        fields=mock_runtime.field_manager.get_fields("petitions_balanced"),
        final_only=False,
    )


def _many_records(n, count):
    record = _search_result()["petitionDecisionDataBag"][0]
    return {"petitionDecisionDataBag": [dict(record) for _ in range(n)], "count": count}


async def test_search_petitions_by_application_pages(mock_runtime):
    """search_by_application used to hard-code limit=100 with no paging at
    all, so an application with more petitions silently lost the remainder."""
    mock_runtime.api_client.search_by_application.return_value = _many_records(100, 250)

    result = await fpd_search_petitions_by_application(
        application_number="17896175", limit=100, offset=0
    )

    paging = result["paging"]
    assert paging["limit_requested"] == 100
    assert paging["limit_applied"] == 100
    assert paging["returned"] == 100
    assert paging["total"] == 250
    assert paging["has_more"] is True
    assert paging["next_offset"] == 100

    # D-3: the projection now comes from field_configs.yaml's
    # petitions_balanced set rather than a literal frozen in the client.
    mock_runtime.api_client.search_by_application.assert_awaited_once_with(
        application_number="17896175", include_documents=False, limit=100,
        offset=0,
        fields=mock_runtime.field_manager.get_fields("petitions_balanced"),
        final_only=False,
    )


async def test_search_petitions_by_application_last_page_has_no_more(mock_runtime):
    mock_runtime.api_client.search_by_application.return_value = _many_records(50, 250)

    result = await fpd_search_petitions_by_application(
        application_number="17896175", limit=100, offset=200
    )

    assert result["paging"]["has_more"] is False
    assert result["paging"]["next_offset"] is None


async def test_search_petitions_by_application_rejects_bad_limit(mock_runtime):
    too_small = await fpd_search_petitions_by_application(
        application_number="17896175", limit=0
    )
    negative_offset = await fpd_search_petitions_by_application(
        application_number="17896175", offset=-1
    )

    assert too_small["status_code"] == 400
    assert negative_offset["status_code"] == 400
    mock_runtime.api_client.search_by_application.assert_not_awaited()


async def test_search_tools_report_the_limit_actually_applied(mock_runtime):
    """Every search envelope reports limit_applied next to limit_requested,
    so a client-layer clamp can never differ silently."""
    mock_runtime.api_client.search_petitions.return_value = _search_result(count=1)

    minimal = await fpd_search_petitions_minimal(query="test", limit=100)
    assert minimal["paging"]["limit_applied"] == 100

    balanced = await fpd_search_petitions_balanced(query="test", limit=50)
    assert balanced["paging"]["limit_applied"] == 50

    # The balanced tier's ceiling is lower on purpose (18 fields per record).
    rejected = await fpd_search_petitions_balanced(query="test", limit=51)
    assert rejected["status_code"] == 400


# --- Fix 5: the MAX_SEARCH_LIMIT ceiling clamps, it does not reject ---------
# USPTO 400s a pagination limit above 100, so the tool layer answering 400 on
# limit=150 spent the caller a turn to learn what the server already knew.


async def test_over_ceiling_limit_is_clamped_not_rejected(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result(count=1)

    result = await fpd_search_petitions_minimal(query="test", limit=200)

    assert "error" not in result
    assert result["limit_clamped"] == {
        "requested": 200,
        "applied": api_constants.MAX_SEARCH_LIMIT,
        "note": result["limit_clamped"]["note"],
    }
    # paging.limit_requested reports what the CALLER asked for, not the clamp.
    assert result["paging"]["limit_requested"] == 200
    assert result["paging"]["limit_applied"] == api_constants.MAX_SEARCH_LIMIT
    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert kwargs["limit"] == api_constants.MAX_SEARCH_LIMIT


async def test_limit_clamped_marker_is_absent_on_a_no_op(mock_runtime):
    """Same absent-on-a-no-op rule as `_bounds` / `_window`."""
    mock_runtime.api_client.search_petitions.return_value = _search_result(count=1)

    result = await fpd_search_petitions_minimal(query="test", limit=10)

    assert "limit_clamped" not in result


async def test_over_ceiling_limit_clamps_on_the_other_two_tools(mock_runtime):
    mock_runtime.api_client.search_by_art_unit.return_value = _search_result()
    mock_runtime.api_client.search_by_application.return_value = _search_result()

    art_unit = await fpd_search_petitions_by_art_unit(art_unit="2128", limit=201)
    by_app = await fpd_search_petitions_by_application(
        application_number="17896175", limit=201
    )

    for result in (art_unit, by_app):
        assert "error" not in result
        assert result["limit_clamped"]["applied"] == api_constants.MAX_SEARCH_LIMIT
        assert result["paging"]["limit_requested"] == 201


async def test_max_search_limit_is_the_upstream_ceiling():
    """The advertised ceiling must be the one USPTO actually honours (100).

    Probed live 2026-08-30: limit=200 answers HTTP 400 "Requested page limit
    exceeds allowed limit 100". A drift back to 200 makes the whole 101..200
    band a guaranteed wasted round trip again.
    """
    assert api_constants.MAX_SEARCH_LIMIT == 100
    assert FPDClient.MAX_SEARCH_LIMIT == api_constants.MAX_SEARCH_LIMIT


# --- Fix 3: by_art_unit's pagination cursor is followable -------------------


async def test_by_art_unit_accepts_the_offset_it_advertises(mock_runtime):
    """It published has_more/next_offset while having no offset parameter, so
    an agent following the cursor either tripped pydantic or silently
    re-fetched page one."""
    mock_runtime.api_client.search_by_art_unit.return_value = _search_result(count=21)

    result = await fpd_search_petitions_by_art_unit(art_unit="3643", limit=1, offset=2)

    assert result["paging"]["offset"] == 2
    assert result["paging"]["has_more"] is True
    assert result["paging"]["next_offset"] == 3
    mock_runtime.api_client.search_by_art_unit.assert_awaited_once_with(
        art_unit="3643", date_range=None, limit=1, offset=2,
        final_only=False,
    )


async def test_by_art_unit_rejects_a_negative_offset(mock_runtime):
    result = await fpd_search_petitions_by_art_unit(art_unit="3643", offset=-1)

    assert result["status_code"] == 400
    mock_runtime.api_client.search_by_art_unit.assert_not_awaited()


# --- Fix 4: include_documents on by_application is no longer a no-op --------
# The wire half (where the documentBag actually comes from) lives in
# tests/test_fpd_client_network.py; this is the tool-layer half.


async def test_by_application_with_documents_publishes_context_info(mock_runtime):
    """context_info used to vanish on this one path, which reads as 'no
    filtering information available' rather than 'no filtering applied'."""
    mock_runtime.api_client.search_by_application.return_value = {
        **_search_result(),
        "petitionDecisionDataBag": [
            {"petitionDecisionRecordIdentifier": _PETITION_ID, "documentBag": []}
        ],
    }

    result = await fpd_search_petitions_by_application(
        application_number="15344896", include_documents=True
    )

    assert result["context_info"]["field_set"] == "unfiltered"
    assert "documentBag" in result["petitionDecisionDataBag"][0]


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


# --------------------------- CR-59/MCP-9: no raw download URL ever leaks out


async def test_get_petition_details_strips_the_raw_download_url(mock_runtime):
    """downloadOptionBag.downloadUrl is a raw api.uspto.gov URL that 401s
    without the server's own API key — it must never reach the model, even
    on a small response the size guard never touches."""
    mock_runtime.api_client.get_petition_by_id.return_value = {
        "petitionDecisionDataBag": [
            {
                "petitionDecisionRecordIdentifier": _PETITION_ID,
                "documentBag": [
                    {
                        "documentIdentifier": "DOC1",
                        "documentCode": "PET",
                        "downloadOptionBag": [
                            {
                                "mimeTypeIdentifier": "PDF",
                                "downloadUrl": "https://api.uspto.gov/api/v1/petition/DOC1/download",
                                "pageTotalQuantity": 3,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = await fpd_get_petition_details(petition_id=_PETITION_ID)

    doc = result["petitionDecisionDataBag"][0]["documentBag"][0]
    assert "downloadOptionBag" not in doc
    assert "downloadUrl" not in str(result)  # no raw URL survives anywhere
    # The follow-up path (documentIdentifier) is untouched.
    assert doc["documentIdentifier"] == "DOC1"


async def test_get_petition_details_docstring_never_tells_the_model_to_relay_documentbag_urls():
    doc = fpd_get_petition_details.__doc__

    assert "provide all document download links to user" not in doc.lower()
    assert "stripped from this response" in doc
    assert "FPD_get_document_download" in doc


async def test_by_application_honors_the_documented_customization_surface(
    mock_runtime, tmp_path
):
    """D-3: FPD_Search_petitions_by_application ignored field_configs.yaml.

    The client carried its own 16-field literal, already divergent from
    petitions_balanced (it omitted businessEntityStatusCategory and
    inventionTitle), so a customer editing the YAML per CUSTOMIZATION.md
    changed four tools and not this one.
    """
    from fpd_mcp.api.field_constants import FPDFields

    mock_runtime.api_client.search_by_application.return_value = _search_result()

    await fpd_search_petitions_by_application(application_number="17896175")

    sent = mock_runtime.api_client.search_by_application.await_args.kwargs["fields"]
    configured = mock_runtime.field_manager.get_fields("petitions_balanced")
    assert sent == configured
    # The two fields the frozen literal had dropped
    assert FPDFields.BUSINESS_ENTITY_STATUS_CATEGORY in sent
    assert FPDFields.INVENTION_TITLE in sent


async def test_by_application_with_documents_requests_no_projection(mock_runtime):
    """A caller who asked for the documentBag must not get a field filter
    that would strip it."""
    mock_runtime.api_client.search_by_application.return_value = _search_result()

    await fpd_search_petitions_by_application(
        application_number="17896175", include_documents=True
    )

    assert mock_runtime.api_client.search_by_application.await_args.kwargs["fields"] is None


# ---------------------------------------------------------------------------
# Decision framing (QA ledger 2026-09-03, tester report B7 finding F1)
# ---------------------------------------------------------------------------
# The served llm_guidance used to assert that DENIED "indicates potential
# quality issues" / "weak arguments or procedural errors" / "weak prosecution
# practices". The corpus is overwhelmingly DENIED and routine make-special/PPH
# requests are refused as a matter of course, so that framing primed every
# reader toward the wrong inference on nearly every call. The classification
# axis is decisionPetitionTypeCodeDescriptionText + ruleBag.

_QUALITY_INFERENCE_PHRASES = (
    "indicates potential quality issues",
    "weak arguments or procedural errors",
    "weak arguments or procedural problems",
    "weak prosecution practices",
)


def _guidance_text(result):
    import json

    return json.dumps(result["llm_guidance"])


def _assert_denial_framing(result):
    text = _guidance_text(result)
    lowered = text.lower()
    for phrase in _QUALITY_INFERENCE_PHRASES:
        assert phrase not in lowered, f"guidance still asserts {phrase!r}"
    classification = result["llm_guidance"]["classification"]
    assert "decisionPetitionTypeCodeDescriptionText" in classification["axis"]
    assert "ruleBag" in classification["axis"]
    assert "no quality signal on its own" in classification["denial_is_not_a_signal"].lower()


async def test_minimal_guidance_does_not_frame_denial_as_a_quality_flag(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_minimal(applicant_name="Apple")

    _assert_denial_framing(result)


async def test_balanced_guidance_does_not_frame_denial_as_a_quality_flag(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_balanced(applicant_name="Apple", limit=10)

    _assert_denial_framing(result)


async def test_by_art_unit_guidance_does_not_frame_denial_as_a_quality_flag(mock_runtime):
    mock_runtime.api_client.search_by_art_unit.return_value = _search_result()

    result = await fpd_search_petitions_by_art_unit(art_unit="2128")

    _assert_denial_framing(result)
    # And no invented rate threshold: a baseline must be computed, not assumed.
    no_threshold = result["llm_guidance"]["classification"]["no_rate_threshold"]
    assert "no threshold" in no_threshold.lower()
    assert "%" not in no_threshold


async def test_by_application_guidance_does_not_frame_denial_as_a_quality_flag(mock_runtime):
    mock_runtime.api_client.search_by_application.return_value = _search_result()

    result = await fpd_search_petitions_by_application(application_number="17896175")

    _assert_denial_framing(result)


async def test_details_guidance_does_not_frame_denial_as_a_quality_flag(mock_runtime):
    mock_runtime.api_client.get_petition_by_id.return_value = {
        "petitionDecisionDataBag": [
            {"petitionDecisionRecordIdentifier": _PETITION_ID, "documentBag": []}
        ]
    }

    result = await fpd_get_petition_details(petition_id=_PETITION_ID)

    _assert_denial_framing(result)
    denied = result["llm_guidance"]["legal_analysis"]["outcome_significance"]["DENIED"]
    assert "ordinary outcome" in denied


# ---------------------------------------------------------------------------
# Petition type table (QA ledger 2026-09-03)
# ---------------------------------------------------------------------------
# 562 and 529 are live on 37 CFR 1.137 records but were missing from the served
# table, so a reader who treated it as exhaustive concluded that a 562 revival
# was not a revival.

def test_balanced_docstring_lists_the_live_revival_type_codes():
    doc = fpd_search_petitions_balanced.__doc__

    # Since 2026-10-07 the table is grouped by class and points at
    # FPD_list_petition_types for USPTO's full names; 562 and 529 stay named.
    assert "562 (additional information required)" in doc
    assert "529 (pre-exam)" in doc
    assert "FPD_list_petition_types(search='revival')" in doc
    # The examiner-dispute class, code by code (a claude.ai run read "609-612"
    # as a range and pulled in 614, a holding of abandonment).
    assert "611 (prematureness of final rejection)" in doc
    assert "Not 515" in doc and "not 613/614" in doc
    assert "not recorded here" not in doc


def test_balanced_docstring_says_the_type_table_is_not_exhaustive():
    doc = fpd_search_petitions_balanced.__doc__

    assert "THIS TABLE IS NOT EXHAUSTIVE" in doc
    # Reversed 2026-10-07: ruleBag is populated only on the final decisions,
    # so ruleBag:"37 CFR 1.137" reached 55 records against about 108,000
    # revival decisions under types 501/502/562 (facet counts that day).
    assert "Select a class by type code, not by `ruleBag`" in doc
    assert "Filter on `ruleBag`, not on a type code" not in doc


def test_field_constants_provenance_lists_the_live_revival_type_codes():
    from fpd_mcp.api import field_constants

    provenance = field_constants.__doc__
    assert "562" in provenance
    assert "529" in provenance
    assert "To Withdraw A Holding of Abandonment in Pre-Exam Status" in provenance
    assert "not exhaustive" in provenance


# ---------------------------------------------------------------------------
# Coverage wording (QA ledger 2026-09-03)
# ---------------------------------------------------------------------------
# "the decisions data itself starts with 2022-and-later decisions" read as a
# cutoff. It is a completeness floor: art unit 2128's three petitions were
# decided in 2011, 2014 and 2015, and records as early as 2003 are present.

def test_every_search_tool_states_coverage_without_a_2022_floor():
    for fn in (
        fpd_search_petitions_minimal,
        fpd_search_petitions_balanced,
        fpd_search_petitions_by_art_unit,
        fpd_search_petitions_by_application,
    ):
        doc = fn.__doc__
        assert "There is no 2022 floor any more" in doc, fn.__name__
        assert "COMPLETENESS FLOOR" not in doc, fn.__name__
        assert "filed in 2001 or later" in doc, fn.__name__


async def test_by_application_zero_result_guidance_is_a_floor_not_a_cutoff(mock_runtime):
    mock_runtime.api_client.search_by_application.return_value = {
        "petitionDecisionDataBag": [], "count": 0,
    }

    result = await fpd_search_petitions_by_application(application_number="17896175")

    meaning = result["llm_guidance"]["interpretation"]["no_petitions"]["meaning"]
    caveat = result["llm_guidance"]["interpretation"]["no_petitions"]["caveat"]
    assert "every disposition" in meaning
    assert "2022" not in meaning + caveat
    # The identifier check comes first: a patent number passed as an
    # application serial is the wrong-not-empty zero.
    assert "patent number" in caveat
    assert "before 2001" in caveat


# ---------------------------------------------------------------------------
# firstApplicantName sparsity (QA ledger 2026-09-03, B7 finding F3)
# ---------------------------------------------------------------------------
# Measured 2026-09-03: absent on 47 of 53 revival records and 98 of 100
# examiner-dispute records, so an applicant_name filter reaches only the
# minority of records carrying the field.

def test_applicant_name_parameter_documents_the_field_sparsity():
    minimal = fpd_search_petitions_minimal.__doc__
    assert "SPARSE" in minimal
    assert "47 of 53" in minimal
    assert "98 of 100" in minimal
    assert "inconclusive" in minimal
    assert "FPD_Search_petitions_by_application" in minimal

    balanced = fpd_search_petitions_balanced.__doc__
    assert "SPARSE firstApplicantName" in balanced


def test_details_docstring_treats_an_absent_field_as_null_or_empty():
    doc = fpd_get_petition_details.__doc__
    assert "**Absent fields:**" in doc
    assert "same case as null or empty" in doc


def test_details_docstring_names_the_native_bag_and_the_wrapper_fallback():
    doc = fpd_get_petition_details.__doc__

    assert "the petition's own papers" in doc
    assert '"petition_record"' in doc
    assert "application_file_wrapper_fallback" in doc
    assert "whole prosecution history" in doc


def test_by_application_include_documents_names_the_native_and_wrapper_bags():
    doc = fpd_search_petitions_by_application.__doc__

    assert '"petition_record"' in doc
    assert "APPLICATION'S FILE\n  WRAPPER" in doc


# ---------------------------------------------------------------------------
# final_only: the two populations (USPTO 2026-10 corpus change)
# ---------------------------------------------------------------------------

_FINAL_CLAUSE = "finalPetitionDecisionIndicator:true"


async def test_minimal_final_only_sends_the_indicator_clause(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_minimal(
        applicant_name="TechCorp Inc.", final_only=True
    )

    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert kwargs["query"] == f'firstApplicantName:"TechCorp Inc." AND {_FINAL_CLAUSE}'
    assert result["query_info"]["final_only"] is True
    assert result["query_info"]["convenience_parameters_used"]["final_only"] is True


async def test_minimal_final_only_alone_is_a_valid_search(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    await fpd_search_petitions_minimal(final_only=True)

    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert kwargs["query"] == _FINAL_CLAUSE


async def test_minimal_default_sends_no_indicator_clause(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_minimal(applicant_name="TechCorp Inc.")

    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert "finalPetitionDecisionIndicator" not in kwargs["query"]
    assert result["query_info"]["final_only"] is False
    assert "final_only" not in result["query_info"]["convenience_parameters_used"]


async def test_balanced_final_only_sends_the_indicator_clause(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_balanced(
        decision_type="DENIED", art_unit="2128", final_only=True
    )

    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert kwargs["query"].endswith(f" AND {_FINAL_CLAUSE}")
    assert "decidedPetitionTypeCode:C" in kwargs["query"]
    assert result["query_info"]["final_only"] is True


async def test_balanced_default_sends_no_indicator_clause(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = _search_result()

    result = await fpd_search_petitions_balanced(art_unit="2128")

    _, kwargs = mock_runtime.api_client.search_petitions.call_args
    assert "finalPetitionDecisionIndicator" not in kwargs["query"]
    assert result["query_info"]["final_only"] is False


async def test_by_art_unit_passes_final_only_to_the_client(mock_runtime):
    mock_runtime.api_client.search_by_art_unit.return_value = _search_result()

    await fpd_search_petitions_by_art_unit(art_unit="2128", final_only=True)

    _, kwargs = mock_runtime.api_client.search_by_art_unit.call_args
    assert kwargs["final_only"] is True


async def test_by_application_passes_final_only_to_the_client(mock_runtime):
    mock_runtime.api_client.search_by_application.return_value = _search_result()

    await fpd_search_petitions_by_application(
        application_number="17896175", final_only=True
    )

    _, kwargs = mock_runtime.api_client.search_by_application.call_args
    assert kwargs["final_only"] is True


async def _client_query(monkeypatch, method, **kwargs):
    monkeypatch.setenv("USPTO_API_KEY", "a" * 30)
    client = FPDClient(api_key="a" * 30)
    seen = {}

    async def _fake_search(**kw):
        seen.update(kw)
        return {"petitionDecisionDataBag": [], "count": 0}

    client.search_petitions = _fake_search
    await getattr(client, method)(**kwargs)
    return seen["query"]


async def test_client_art_unit_final_only_composes_the_clause(monkeypatch):
    on = await _client_query(
        monkeypatch, "search_by_art_unit", art_unit="2128", final_only=True
    )
    off = await _client_query(monkeypatch, "search_by_art_unit", art_unit="2128")

    assert on == f"groupArtUnitNumber:2128 AND {_FINAL_CLAUSE}"
    assert "finalPetitionDecisionIndicator" not in off


async def test_client_application_final_only_composes_the_clause(monkeypatch):
    on = await _client_query(
        monkeypatch, "search_by_application",
        application_number="17896175", final_only=True,
    )
    off = await _client_query(
        monkeypatch, "search_by_application", application_number="17896175"
    )

    assert on == f"applicationNumberText:17896175 AND {_FINAL_CLAUSE}"
    assert "finalPetitionDecisionIndicator" not in off


def test_every_search_tool_documents_final_only_and_the_two_populations():
    for tool in (
        fpd_search_petitions_minimal,
        fpd_search_petitions_balanced,
        fpd_search_petitions_by_art_unit,
        fpd_search_petitions_by_application,
    ):
        doc = tool.__doc__
        assert "**Two populations:**" in doc, tool.__name__
        assert "finalPetitionDecisionIndicator:true" in doc, tool.__name__
        assert "final_only" in doc, tool.__name__
        # No dated census in a served string: it cannot re-verify itself.
        assert "7,499" not in doc and "7,497" not in doc, tool.__name__


def test_minimal_docstring_states_the_dense_query_limit_clamp():
    doc = fpd_search_petitions_minimal.__doc__

    assert "limit above about 50 on dense queries is clamped by the response bound" in doc
    assert "`_bounds`" in doc
    assert "offset" in doc


def test_guidance_states_two_populations_and_the_clamp():
    from fpd_mcp.config.tool_reflections import get_guidance_section

    overview = get_guidance_section("overview")

    assert "## Two populations" in overview
    assert "final_only" in overview
    assert "7,499" not in overview and "7,497" not in overview
    assert "limit above about 50 on a dense query is clamped by the response bound" in overview
    assert "`_bounds` says so" in overview
    assert "—" not in overview.split("## Two populations")[1].split("## Available Tools Summary")[0]
