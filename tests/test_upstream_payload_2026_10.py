"""The 2026-10 FPD payload change, against recorded samples of the new payload.

tests/fixtures/fpd_payload_2026_10.json was recorded live on 2026-10-05 (see
docs/UPSTREAM-FPD-API-CHANGE-2026-10.md). Each test pins one adapted path:
string type codes, as-written applicant names, the renamed decision field and
its filter, the native documentBag (details, search hits, download), and the
newest-first order.
"""

import copy
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import fpd_mcp.proxy.centralized_integration as centralized_integration
import fpd_mcp.proxy.secure_link_cache as secure_link_cache
import fpd_mcp.tools.documents as documents_module
from fpd_mcp import runtime
from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.api.payload_compat import (
    decision_type_clause,
    normalize_record,
    rewrite_legacy_query_fields,
    select_pdf_download,
    upstream_fields,
)
from fpd_mcp.services.fpd_service import FPDService
from fpd_mcp.tools.documents import fpd_get_document_download
from fpd_mcp.tools.petitions import (
    fpd_get_petition_details,
    fpd_search_petitions_balanced,
    fpd_search_petitions_by_application,
    fpd_search_petitions_by_art_unit,
    fpd_search_petitions_minimal,
)

_SAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "fpd_payload_2026_10.json").read_text()
)
_SEED_ID = "70a0101b-8dfc-546b-b5a6-aa7e786cbde3"
_SEED_DOC = "LU79EIOJBLUEX12"


def _sample(name):
    return copy.deepcopy(_SAMPLES[name])


@pytest.fixture
def live_shaped(monkeypatch, mock_runtime):
    """A REAL FPDClient whose network boundary (`_make_request`) answers
    from the recorded samples, wired into the runtime so the tools run the
    real client + service + field filter."""
    client = FPDClient(api_key="test-key-1234567890")
    calls = []
    answers = {}

    async def fake_make_request(endpoint, method="GET", base_url=None, **kwargs):
        calls.append({"endpoint": endpoint, "method": method, "base_url": base_url, **kwargs})
        answer = answers.get(endpoint)
        if callable(answer):
            answer = answer(kwargs)
        if answer is None:
            raise AssertionError(f"unexpected request to {endpoint}")
        return copy.deepcopy(answer)

    monkeypatch.setattr(client, "_make_request", fake_make_request)
    service = FPDService(client, mock_runtime.field_manager)
    monkeypatch.setattr(runtime, "api_client", client)
    monkeypatch.setattr(runtime, "fpd_service", service)
    return client, calls, answers


# --------------------------------------------------------------------------- #
# decisionPetitionTypeCode: a string upstream, an integer in our records
# --------------------------------------------------------------------------- #

async def test_string_type_code_is_served_as_an_integer(live_shaped):
    _, calls, answers = live_shaped
    answers["search"] = _sample("search_type_code_551")
    assert _SAMPLES["search_type_code_551"]["petitionDecisionDataBag"][0]["decisionPetitionTypeCode"] == "551"

    result = await fpd_search_petitions_balanced(petition_type_code="551", limit=2)

    assert result["petitionDecisionDataBag"][0]["decisionPetitionTypeCode"] == 551
    assert result["query_info"]["final_query"] == "decisionPetitionTypeCode:551"


async def test_an_integer_type_code_is_accepted_and_sent_as_its_digits(live_shaped):
    _, calls, answers = live_shaped
    answers["search"] = _sample("search_type_code_551")

    result = await fpd_search_petitions_balanced(petition_type_code=551, limit=2)

    assert "error" not in result
    assert calls[0]["json"]["q"] == "decisionPetitionTypeCode:551"


def test_normalize_record_leaves_a_non_numeric_type_code_alone():
    assert normalize_record({"decisionPetitionTypeCode": "PFMU"})["decisionPetitionTypeCode"] == "PFMU"
    assert normalize_record({"decisionPetitionTypeCode": 502})["decisionPetitionTypeCode"] == 502


# --------------------------------------------------------------------------- #
# firstApplicantName: stored as written; the filter goes out as typed
# --------------------------------------------------------------------------- #

async def test_applicant_name_is_served_as_written_and_sent_as_typed(live_shaped):
    _, calls, answers = live_shaped
    answers["search"] = _sample("search_applicant_apple_as_typed")

    result = await fpd_search_petitions_minimal(applicant_name="Apple Inc.", limit=3)

    assert calls[0]["json"]["q"] == 'firstApplicantName:"Apple Inc."'
    assert result["query_info"]["final_query"] == 'firstApplicantName:"Apple Inc."'
    # The record is NOT upper-cased by this server: it is USPTO's value.
    assert result["petitionDecisionDataBag"][0]["firstApplicantName"] == "Apple Inc."


# --------------------------------------------------------------------------- #
# Decision outcome: renamed field, analyzed text, exact letter code
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value,clause", [
    ("GRANTED", "decidedPetitionTypeCode:A"),
    ("granted", "decidedPetitionTypeCode:A"),
    ("GRANTED-IN-PART", "decidedPetitionTypeCode:B"),
    ("DENIED", "decidedPetitionTypeCode:C"),
    (" Dismissed ", "decidedPetitionTypeCode:D"),
    ("WITHDRAWN", 'decidedPetitionTypeCodeDescriptionText:"WITHDRAWN"'),
])
def test_decision_type_clause(value, clause):
    assert decision_type_clause(value) == clause


def test_the_recorded_facets_back_the_letter_code_mapping():
    facets = _SAMPLES["facets_decision_vocabulary"]["facets"]
    by_code = {f["value"]: f["count"] for f in facets["decidedPetitionTypeCode"]}
    by_text = {f["value"]: f["count"] for f in facets["decidedPetitionTypeCodeDescriptionText"]}
    for text, code in (("GRANTED", "A"), ("GRANTED-IN-PART", "B"), ("DENIED", "C"), ("DISMISSED", "D")):
        assert by_code[code] == by_text[text]


async def test_decision_filter_and_the_legacy_record_key(live_shaped):
    _, calls, answers = live_shaped
    answers["search"] = _sample("search_decided_denied")

    result = await fpd_search_petitions_minimal(decision_type="DENIED", limit=1)

    body = calls[0]["json"]
    assert body["q"] == "decidedPetitionTypeCode:C"
    # The projection asks for the new name beside the legacy one.
    assert "decisionTypeCodeDescriptionText" in body["fields"]
    assert "decidedPetitionTypeCodeDescriptionText" in body["fields"]
    # The minimal row carries the outcome under the key every consumer reads.
    record = result["petitionDecisionDataBag"][0]
    assert record["decisionTypeCodeDescriptionText"] == "DENIED"
    assert result["count"] == 7499


def test_a_raw_query_on_the_retired_outcome_field_is_pointed_at_the_new_one():
    assert (
        rewrite_legacy_query_fields('decisionTypeCodeDescriptionText:DENIED AND ruleBag:"37 CFR 1.137"')
        == 'decidedPetitionTypeCodeDescriptionText:DENIED AND ruleBag:"37 CFR 1.137"'
    )
    assert rewrite_legacy_query_fields("decisionTypeCode:C") == "decisionTypeCode:C"


def test_upstream_fields_adds_current_names_without_duplicates():
    assert upstream_fields(["a", "decisionTypeCodeDescriptionText", "decidedPetitionTypeCodeDescriptionText"]) == [
        "a", "decisionTypeCodeDescriptionText", "decidedPetitionTypeCodeDescriptionText",
    ]
    assert upstream_fields(None) is None


# --------------------------------------------------------------------------- #
# Details: native documentBag, includeDocuments never sent
# --------------------------------------------------------------------------- #

async def test_details_with_documents_serves_the_native_bag(live_shaped):
    client, calls, answers = live_shaped
    answers[_SEED_ID] = _sample("details_seed_petition")

    result = await client.get_petition_by_id(_SEED_ID, include_documents=True)

    assert len(calls) == 1
    assert not calls[0].get("params")  # includeDocuments is never sent
    record = result["petitionDecisionDataBag"][0]
    assert result["document_metadata_source"] == "petition_record"
    assert [d["documentIdentifier"] for d in record["documentBag"]] == [_SEED_DOC]
    assert record["documentBag"][0]["pageCount"] == 10  # backfilled
    assert "allSearchableFields" not in record and "ocrSearchText" not in record
    assert record["decisionPetitionTypeCode"] == 502
    assert record["decisionTypeCodeDescriptionText"] == "DENIED"


async def test_details_without_documents_drops_the_bag(live_shaped):
    _, _, answers = live_shaped
    answers[_SEED_ID] = _sample("details_seed_petition")

    result = await fpd_get_petition_details(petition_id=_SEED_ID, include_documents=False)

    record = result["petitionDecisionDataBag"][0]
    assert "documentBag" not in record
    assert "document_metadata_available" not in result
    assert record["ruleBag"] == ["37 CFR 1.137(a)"]
    # The 25,000-char index field is gone, so the cheap lane is cheap again.
    assert len(json.dumps(result)) < 6000


async def test_details_never_returns_some_other_petition(live_shaped):
    """includeDocuments=true now answers with a page of the WHOLE corpus.
    Whatever upstream sends, a record that is not the requested petition is
    never served as if it were."""
    client, _, answers = live_shaped
    corpus_page = _sample("details_with_includeDocuments_true")
    assert corpus_page["count"] > 1_000_000
    answers[_SEED_ID] = corpus_page

    result = await client.get_petition_by_id(_SEED_ID, include_documents=True)

    assert result["status_code"] == 404
    assert "not found" in result["error"]


async def test_details_picks_the_requested_record_out_of_a_list(live_shaped):
    client, _, answers = live_shaped
    page = _sample("details_with_includeDocuments_true")
    wanted = page["petitionDecisionDataBag"][1]["petitionDecisionRecordIdentifier"]
    answers[wanted] = page

    result = await client.get_petition_by_id(wanted, include_documents=True)

    assert result["count"] == 1
    assert [r["petitionDecisionRecordIdentifier"] for r in result["petitionDecisionDataBag"]] == [wanted]


async def test_details_tool_passes_a_404_through(live_shaped):
    _, _, answers = live_shaped
    zero = "00000000-0000-0000-0000-000000000000"
    answers[zero] = {
        "error": "API error: " + json.dumps(_SAMPLES["details_unknown_petition_404"]),
        "status_code": 404,
        "success": False,
    }

    result = await fpd_get_petition_details(petition_id=zero)

    assert result["status_code"] == 404
    assert "No matching records found" in result["error"]


async def test_details_under_the_response_budget_with_its_native_bag(live_shaped):
    _, _, answers = live_shaped
    answers[_SEED_ID] = _sample("details_seed_petition")

    result = await fpd_get_petition_details(petition_id=_SEED_ID, include_documents=True)

    assert "_bounds" not in result and "documents_note" not in result
    doc = result["petitionDecisionDataBag"][0]["documentBag"][0]
    assert "downloadOptionBag" not in doc  # still stripped (CR-59)
    assert doc["documentCode"] == "PETDEC"


# --------------------------------------------------------------------------- #
# Search hits: native bags, wrapper only for an empty one
# --------------------------------------------------------------------------- #

async def test_by_application_include_documents_uses_the_native_bags(live_shaped):
    _, calls, answers = live_shaped
    answers["search"] = _sample("search_application_15344896_unprojected")

    result = await fpd_search_petitions_by_application(
        application_number="15344896", include_documents=True
    )

    assert [c["endpoint"] for c in calls] == ["search"]  # no wrapper fetch
    assert result["document_metadata_source"] == "petition_record"
    assert result["count"] == 4
    assert all(r["documentBag"] for r in result["petitionDecisionDataBag"])
    assert not any("document_bag_source" in r for r in result["petitionDecisionDataBag"])


async def test_by_application_grafts_the_wrapper_only_onto_a_bare_record(live_shaped):
    client, calls, answers = live_shaped
    page = _sample("search_application_15344896_unprojected")
    page["petitionDecisionDataBag"][1].pop("documentBag")
    answers["search"] = page
    answers["15344896/documents"] = {"documentBag": [{"documentIdentifier": "WRAPPERDOC1"}]}

    result = await fpd_search_petitions_by_application(
        application_number="15344896", include_documents=True
    )

    records = result["petitionDecisionDataBag"]
    assert result["document_metadata_source"] == "mixed"
    assert records[1]["document_bag_source"] == "application_file_wrapper"
    assert records[1]["documentBag"][0]["documentIdentifier"] == "WRAPPERDOC1"
    assert records[0]["documentBag"][0]["documentIdentifier"] == _SEED_DOC
    assert "document_bag_source" not in records[0]
    assert calls[1]["base_url"] == client.applications_base_url


# --------------------------------------------------------------------------- #
# Download: an identifier from the native bag resolves
# --------------------------------------------------------------------------- #

class _FakeLinkCache:
    cache_duration = timedelta(days=1)
    max_uses = 25

    def __init__(self):
        self.calls = []

    def generate_persistent_link(self, **kwargs):
        self.calls.append(kwargs)
        return "http://localhost:8081/download/persistent/0123abcd"

    async def mint_persistent_link(self, **kwargs):
        return self.generate_persistent_link(**kwargs)


async def test_download_resolves_a_native_bag_identifier(live_shaped, monkeypatch):
    _, calls, answers = live_shaped
    answers[_SEED_ID] = _sample("details_seed_petition")
    cache = _FakeLinkCache()
    monkeypatch.setattr(centralized_integration, "get_centralized_base_url", lambda: None)
    monkeypatch.setattr(secure_link_cache, "get_link_cache", lambda: cache)
    monkeypatch.setattr(documents_module, "_ensure_proxy_server_running", AsyncMock())
    monkeypatch.setattr(documents_module, "_register_download_via_proxy", AsyncMock(return_value="r1"))

    result = await fpd_get_document_download(petition_id=_SEED_ID, document_identifier=_SEED_DOC)

    assert result["success"] is True
    assert result["page_count"] == 10
    assert result["enhanced_filename"] == "PET-2023-11-22_APP-15344896_PETITION_DECISION.pdf"
    assert result["document_context"]["decision_outcome"] == "DENIED"
    assert result["document_context"]["decision_date"] == "2024-03-22"
    assert cache.calls[0]["file_download_uri"] == (
        "https://api.uspto.gov/api/v1/download/applications/15344896/LU79EIOJBLUEX12.pdf"
    )
    assert len(calls) == 1 and not calls[0].get("params")


def test_select_pdf_download_prefers_the_documents_own_pdf():
    auto = _SAMPLES["details_with_includeDocuments_true"]["petitionDecisionDataBag"][0]["documentBag"][0]
    reordered = copy.deepcopy(auto)
    reordered["downloadOptionBag"].reverse()  # grantLetter.pdf first

    url, pages = select_pdf_download(reordered, "19632342")

    assert url.endswith("/MURVCF5Y121X250.pdf")
    assert pages == 1


def test_select_pdf_download_builds_the_documented_url_when_no_option_is_listed():
    url, pages = select_pdf_download({"documentIdentifier": "DOC9", "pageCount": 3}, "15344896")
    assert url == "https://api.uspto.gov/api/v1/download/applications/15344896/DOC9.pdf"
    assert pages == 3
    assert select_pdf_download({"documentIdentifier": "DOC9"}, None) == (None, 0)


# --------------------------------------------------------------------------- #
# Order: newest decision first, said in every search tool's description
# --------------------------------------------------------------------------- #

def test_the_recorded_default_order_is_newest_decision_first():
    records = _SAMPLES["search_art_unit_3643_default_order"]["petitionDecisionDataBag"]
    dates = [r["decisionDate"] for r in records]
    assert dates == sorted(dates, reverse=True)
    asc = _SAMPLES["search_art_unit_3643_sort_petitionMailDate_asc"]["petitionDecisionDataBag"]
    assert asc[0]["petitionMailDate"] < records[-1]["petitionMailDate"]


@pytest.mark.parametrize("tool", [
    fpd_search_petitions_minimal,
    fpd_search_petitions_balanced,
    fpd_search_petitions_by_art_unit,
    fpd_search_petitions_by_application,
])
def test_every_search_tool_says_the_order_is_newest_first(tool):
    assert "newest decision first (decisionDate descending)" in tool.__doc__


async def test_the_client_requests_no_sort_of_its_own(live_shaped):
    _, calls, answers = live_shaped
    answers["search"] = _sample("search_art_unit_3643_default_order")

    await fpd_search_petitions_by_art_unit(art_unit="3643", limit=2)

    assert "sort" not in calls[0]["json"]


def test_context_reduction_ignores_the_servers_own_alias_twin():
    """upstream_fields asks USPTO for the current decision name beside the
    legacy one; dropping that twin afterwards is not a reduction the caller
    asked for and must not be reported as one."""
    from pathlib import Path

    from fpd_mcp.api.field_constants import FPDFields
    from fpd_mcp.config.field_manager import FieldManager

    fm = FieldManager(Path(__file__).parent.parent / "field_configs.yaml")
    field_set = next(
        name for name in fm.get_predefined_sets()
        if FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT in fm.get_fields(name)
        and FPDFields.DECIDED_PETITION_TYPE_CODE_DESCRIPTION_TEXT not in fm.get_fields(name)
    )
    fields = fm.get_fields(field_set)
    # A record carrying exactly the configured fields plus the twin the
    # server itself requested.
    record = {f: "v" for f in fields}
    record[FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT] = "DENIED"
    record[FPDFields.DECIDED_PETITION_TYPE_CODE_DESCRIPTION_TEXT] = "DENIED"
    out = fm.filter_response({"petitionDecisionDataBag": [record], "count": 1}, field_set)
    assert out["context_info"]["context_reduction"] == "0%"
    assert out["context_info"]["original_field_count"] == out["context_info"]["filtered_field_count"]
