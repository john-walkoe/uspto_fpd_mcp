"""Petition statistics tools: aggregation math, scope composition, bounds and
the petition type table, replayed against facet responses recorded live on
2026-10-06 (tests/fixtures/fpd_facets_2026_10_06.json, docs/PETITION-STATISTICS.md).

The replay serves each FPDClient.search_petitions call from the recording by
its exact keyword arguments, so a change in the query a tool composes, the
facets it asks for or the pages it samples fails here as an unrecorded call.
"""

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.api.petition_types import (
    PETITION_TYPE_NAMES,
    petition_type_name,
    search_petition_types,
)
from fpd_mcp.services import petition_statistics as stats
from fpd_mcp.shared.error_utils import ValidationError
from fpd_mcp.tools import _bound_result
from fpd_mcp.tools import statistics as st

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "fpd_facets_2026_10_06.json").read_text()
)
_PROBES = _FIXTURE["facet_probes"]


def _calls(case):
    return [c for c in _FIXTURE["tool_calls"] if c["case"] == case]


def _key(kwargs):
    return json.dumps(
        {k: kwargs.get(k) for k in ("query", "fields", "limit", "offset", "facets")},
        sort_keys=True,
    )


@pytest.fixture
def replay(mock_runtime, monkeypatch):
    """Serve search_petitions from one recorded case; record what was asked."""
    monkeypatch.setattr(st, "_today", lambda: date(2026, 10, 7))
    st.clear_type_count_cache()

    def load(case):
        recorded = {_key(c["kwargs"]): c["result"] for c in _calls(case)}
        asked = []

        async def search_petitions(**kwargs):
            key = _key(kwargs)
            asked.append(key)
            assert key in recorded, f"unrecorded upstream call: {key}"
            return json.loads(json.dumps(recorded[key]))

        mock_runtime.api_client.search_petitions.side_effect = search_petitions
        return asked, recorded

    yield load
    st.clear_type_count_cache()


# ---------------------------------------------------------------------------
# Petition type table
# ---------------------------------------------------------------------------

def test_type_table_names_every_live_code_and_reconciles_with_the_name_facet():
    facets = _PROBES["type_code_and_name"]["response"]["facets"]
    codes = {b["value"]: b["count"] for b in facets["decisionPetitionTypeCode"]}
    names = {b["value"]: b["count"] for b in facets["decisionPetitionTypeCodeDescriptionText"]}

    assert len(PETITION_TYPE_NAMES) == 191
    assert set(codes) == {str(c) for c in PETITION_TYPE_NAMES}

    by_name = Counter()
    for code, count in codes.items():
        by_name[PETITION_TYPE_NAMES[int(code)]] += count
    assert dict(by_name) == names


def test_type_name_lookup_accepts_int_and_string_and_refuses_junk():
    assert petition_type_name(551) == "CORRECTION OF PATENT TERM ADJUSTMENT VALUE AFTER ISUE"
    assert petition_type_name(" 502 ").startswith("REVIVE AN APPLICATION ABANDONED BY OPAP")
    assert petition_type_name("abc") is None
    assert petition_type_name(9999) is None


def test_type_search_maps_plain_words_to_the_names():
    revival = {code for code, _ in search_petition_types("revival")}
    assert {501, 502, 562, 510, 271, 272} <= revival
    assert len(revival) == 12
    assert 551 not in revival

    pta = {code for code, _ in search_petition_types("PTA")}
    assert {547, 549, 550, 551, 554} == pta  # not 308 (PTAB) or 645 (Adaptation)

    assert search_petition_types("502") == [(502, PETITION_TYPE_NAMES[502])]
    assert search_petition_types("no such petition") == []
    assert len(search_petition_types("")) == 191


def test_type_search_names_the_examiner_dispute_class():
    # The class shares no word in USPTO's names; 515 and 613/614 stay out.
    for word in ("examiner dispute", "disputes", "examiner"):
        assert [c for c, _ in search_petition_types(word)] == [504, 609, 610, 611, 612, 615, 617]


def test_type_search_finds_the_extention_misspelling_both_ways():
    # Type 315's USPTO name spells it "EXTENTION".
    for word in ("extension of time", "extention"):
        assert {315, 620, 630, 710} <= {code for code, _ in search_petition_types(word)}


# ---------------------------------------------------------------------------
# Scope composition
# ---------------------------------------------------------------------------

def test_empty_scope_is_the_whole_corpus():
    query, used = stats.compose_scope()
    assert query == ""
    assert used == {"final_only": False}


def test_every_filter_composes_in_order():
    query, used = stats.compose_scope(
        query="machine learning",
        petition_type_code="501, 502,562",
        art_unit="371",
        technology_center="37",
        rule="37 CFR 1.137(a)",
        statute="35 USC 41",
        applicant_name="Apple Inc.",
        deciding_office="OFFICE OF PETITIONS",
        decision_type="dismissed",
        date_field="petitionMailDate",
        date_start="2020-01-01",
        date_end="2024-12-31",
        final_only=True,
    )
    assert query == (
        "(machine learning) AND decisionPetitionTypeCode:(501 OR 502 OR 562) AND "
        "groupArtUnitNumber:371* AND technologyCenter:37* AND "
        'ruleBag:"37 CFR 1.137(a)" AND statuteBag:"35 USC 41" AND '
        'firstApplicantName:"Apple Inc." AND finalDecidingOfficeName:"OFFICE OF PETITIONS" AND '
        "decidedPetitionTypeCode:D AND petitionMailDate:[2020-01-01 TO 2024-12-31] AND "
        "finalPetitionDecisionIndicator:true"
    )
    assert used["petition_type_code"] == [501, 502, 562]
    assert used["decision_type"] == "DISMISSED"
    assert used["date_range"] == {"field": "petitionMailDate", "start": "2020-01-01", "end": "2024-12-31"}


def test_scope_exact_values_and_single_code():
    query, _ = stats.compose_scope(petition_type_code=[502], art_unit="3711", technology_center="opap")
    assert query == "decisionPetitionTypeCode:502 AND groupArtUnitNumber:3711 AND technologyCenter:OPAP"


def test_scope_points_a_legacy_outcome_clause_at_the_new_field():
    query, _ = stats.compose_scope(query="decisionTypeCodeDescriptionText:DENIED")
    assert query == "(decidedPetitionTypeCodeDescriptionText:DENIED)"


@pytest.mark.parametrize("kwargs", [
    {"petition_type_code": "abc"},
    {"petition_type_code": list(range(500, 521))},
    {"art_unit": "37111"},
    {"art_unit": "37*"},
    {"technology_center": "370"},
    {"rule": 'x" OR *:*'},
    {"applicant_name": "Apple:*"},
    {"date_start": "2024-02-01", "date_end": "2024-01-01"},
    {"date_field": "filingDate", "date_start": "2024-01-01"},
    {"query": "x" * 1001},
])
def test_scope_refuses_bad_values(kwargs):
    with pytest.raises(ValidationError):
        stats.compose_scope(**kwargs)


# ---------------------------------------------------------------------------
# Aggregation math
# ---------------------------------------------------------------------------

def test_outcome_block_on_the_recorded_corpus_facet():
    response = _PROBES["corpus_outcomes"]["response"]
    counts = stats.outcome_counts(response["facets"]["decidedPetitionTypeCode"])
    block = stats.outcome_block(counts)

    assert block["total"] == response["count"] == 1113547
    assert counts == {"GRANTED": 880428, "GRANTED-IN-PART": 1863, "DENIED": 7497, "DISMISSED": 223759}
    assert block["outcomes"]["DISMISSED"]["share"] == round(223759 / 1113547, 4)
    assert block["rates"]["grant_rate"] == round(880428 / 1113547, 4)
    assert block["rates"]["grant_rate_incl_partial"] == round((880428 + 1863) / 1113547, 4)
    assert block["rates"]["grant_rate_excl_dismissed"] == round((880428 + 1863) / (1113547 - 223759), 4)


def test_rates_are_none_on_an_empty_scope():
    block = stats.outcome_block(stats.outcome_counts([]))
    assert block["total"] == 0
    assert set(block["rates"].values()) == {None}


def test_final_only_facet_is_all_denied():
    facets = _PROBES["final_only_with_query"]["response"]["facets"]
    counts = stats.outcome_counts(facets["decidedPetitionTypeCode"])
    assert counts["DENIED"] == _PROBES["final_only_with_query"]["response"]["count"]
    assert stats.rates(counts)["denial_rate"] == 1.0


def test_dimension_table_cross_tab_and_missing_values():
    per_outcome = {
        "GRANTED": [{"value": "3700", "count": 80}, {"value": "1600", "count": 10}],
        "DISMISSED": [{"value": "3700", "count": 20}, {"value": "2100", "count": 5}],
    }
    table = stats.dimension_table("technology_center", per_outcome, scope_total=130, top_n=2)

    assert table["complete"] is True
    assert table["distinct_values"] == 3
    assert table["records_without_value"] == 15
    assert [b["value"] for b in table["buckets"]] == ["3700", "1600"]
    top = table["buckets"][0]
    assert top["total"] == 100
    assert top["outcomes"] == {"GRANTED": 80, "GRANTED-IN-PART": 0, "DENIED": 0, "DISMISSED": 20}
    assert top["rates"]["dismissal_rate"] == 0.2
    assert "partial" not in top
    # 2 of 3 values shown: the table says so, so a reader does not take the
    # missing value (2100) for a zero.
    assert table["truncated_by_top_n"]["values_shown"] == 2
    assert table["truncated_by_top_n"]["distinct_values"] == 3
    full = stats.dimension_table("technology_center", per_outcome, scope_total=130, top_n=3)
    assert "truncated_by_top_n" not in full


def test_dimension_table_flags_values_lost_to_the_1000_cap():
    granted = [{"value": f"A{i:04d}", "count": 1000 - i} for i in range(stats.FACET_VALUE_CAP)]
    per_outcome = {"GRANTED": granted, "DISMISSED": [{"value": "ZZZZ", "count": 5000}]}
    table = stats.dimension_table("applicant", per_outcome, scope_total=10**6, top_n=3)

    assert table["complete"] is False
    assert table["distinct_values"] is None
    top = table["buckets"][0]
    assert top["value"] == "ZZZZ"
    assert top["partial"]["outcomes_unknown"] == ["GRANTED"]
    assert "values_are_as_written" in table


def test_petition_type_buckets_carry_names():
    table = stats.dimension_table(
        "petition_type", {"GRANTED": [{"value": "502", "count": 3}]}, scope_total=3, top_n=5
    )
    assert table["buckets"][0]["code"] == 502
    assert table["buckets"][0]["name"] == PETITION_TYPE_NAMES[502]


def test_year_windows():
    today = date(2026, 10, 7)
    windows, info = stats.year_windows(None, None, today)
    assert [w[0] for w in windows] == list(range(2026, 2014, -1))
    assert windows[0] == (2026, "2026-01-01", "2026-10-07")
    assert info["default_window"] is True

    windows, info = stats.year_windows("2023-03-15", "2025-06-30", today)
    assert windows == [
        (2025, "2025-01-01", "2025-06-30"),
        (2024, "2024-01-01", "2024-12-31"),
        (2023, "2023-03-15", "2023-12-31"),
    ]
    assert "default_window" not in info

    windows, info = stats.year_windows("2001-01-01", None, today)
    assert len(windows) == stats.MAX_YEARS
    assert info["years_omitted"] == {"from": 2001, "to": 2014}


def test_sample_pages():
    assert stats.sample_pages(0, 100) == []
    assert stats.sample_pages(150, 500) == [(0, 100), (100, 50)]
    assert stats.sample_pages(13600, 200) == [(0, 100), (6800, 100)]
    blocks = stats.sample_pages(1_000_000, 250)
    assert [limit for _, limit in blocks] == [100, 100, 50]
    assert blocks[1][0] == 333333
    assert all(offset + limit <= 1_000_000 for offset, limit in blocks)


def test_turnaround_stats_on_the_recorded_sample():
    pages = [c for c in _calls("stats_502") if c["kwargs"]["limit"] == 100]
    records = [r for c in pages for r in c["result"]["petitionDecisionDataBag"]]
    result = stats.turnaround_stats(records)

    days = sorted(
        (date.fromisoformat(r["decisionDate"]) - date.fromisoformat(r["petitionMailDate"])).days
        for r in records
    )
    assert result["days"]["n"] == len(days) == 200
    assert result["days"]["median"] == (days[99] + days[100]) / 2
    assert result["days"]["same_day"] == days.count(0)
    assert sum(v["n"] for v in result["by_outcome"].values()) == 200


def test_turnaround_excludes_missing_and_backwards_dates():
    result = stats.turnaround_stats([
        {"petitionMailDate": "2024-01-10", "decisionDate": "2024-01-01"},
        {"decisionDate": "2024-01-01"},
        {"petitionMailDate": "2024-01-01", "decisionDate": "2024-01-31", "decidedPetitionTypeCode": "D"},
    ])
    assert result["excluded"] == {"missing_a_date": 1, "decided_before_mail_date": 1}
    assert result["days"]["median"] == 30.0
    assert result["by_outcome"] == {"DISMISSED": result["days"]}


# ---------------------------------------------------------------------------
# Tool replay
# ---------------------------------------------------------------------------

async def test_statistics_replay_counts_crosstab_years_and_turnaround(replay):
    asked, recorded = replay("stats_502")
    result = await st.fpd_get_petition_statistics(
        petition_type_code="502", dimensions=["technology_center", "year"],
        date_start="2023-01-01", top_n=5, turnaround_sample=200,
    )

    assert sorted(asked) == sorted(recorded)  # every recorded call, each once
    assert result["upstream_requests"] == 10
    assert result["as_of"] == "2026-10-07"
    assert result["scope"]["final_query"] == "decisionPetitionTypeCode:502 AND decisionDate:[2023-01-01 TO *]"
    assert "final_only=False" in result["scope"]["population"]
    assert result["total"] == 13600
    assert result["outcomes"]["GRANTED"]["count"] == 10913
    assert result["outcomes"]["GRANTED-IN-PART"]["count"] == 0  # upstream 404 = zero
    assert result["outcomes"]["DENIED"]["count"] == 3
    assert result["outcomes"]["DISMISSED"]["count"] == 2684

    (tc,) = result["dimensions"]
    assert tc["dimension"] == "technology_center" and tc["complete"] is True
    assert len(tc["buckets"]) == 5
    assert tc["buckets"][0]["value"] == "3700"
    assert sum(b["total"] for b in tc["buckets"]) + tc["records_without_value"] <= result["total"]

    years = result["by_year"]["buckets"]
    assert [b["year"] for b in years] == [2026, 2025, 2024, 2023]
    assert sum(b["total"] for b in years) == result["total"]

    assert result["turnaround"]["records_sampled"] == 200
    assert "systematic cluster sample" in result["turnaround"]["method"]
    assert "dispositions" in result["provenance"]
    assert len(json.dumps(result)) < 40_000


async def test_statistics_without_dimensions_is_one_call(replay):
    asked, _ = replay("stats_corpus_turnaround")
    result = await st.fpd_get_petition_statistics(dimensions=[])
    assert len(asked) == 1
    assert result["total"] == 1113547
    assert result["scope"]["final_query"].startswith("(none")
    assert "dimensions" not in result


async def test_dismissal_grounds_replay(replay):
    asked, recorded = replay("dismissal_502")
    result = await st.fpd_get_dismissal_grounds(
        petition_type_code="502", sample_size=3, mention_phrases=["terminal disclaimer"], top_n=5,
    )

    assert sorted(asked) == sorted(recorded)
    assert result["upstream_requests"] == 3
    assert result["scope_total"] == 104273
    assert result["dismissed"] == {"count": 17572, "share_of_scope": round(17572 / 104273, 4)}
    (bucket,) = result["by_petition_type"]["buckets"]
    assert bucket["code"] == 502 and bucket["dismissal_rate_for_type"] == round(17572 / 104273, 4)
    assert result["by_rule"]["buckets"] == [] and "decision document" in result["by_rule"]["note"]

    assert len(result["sample"]) == 3
    for row in result["sample"]:
        assert row["cite_as"].startswith("[Petition decision ")
        assert row["read_with"].startswith("FPD_get_document_content_with_ocr(")
        assert row["documents"] and all("downloadOptionBag" not in d for d in row["documents"])
        assert row["petition_type_name"] == PETITION_TYPE_NAMES[502]
    assert "citation_note" in result

    (mention,) = result["mentions"]
    assert mention["phrase"] == "terminal disclaimer"
    assert mention["dismissed_decisions_mentioning"] == 9452
    assert "not a ground" in result["mentions_note"]


async def test_list_petition_types_replay_and_hour_cache(replay, mock_runtime):
    asked, _ = replay("list_revival")
    first = await st.fpd_list_petition_types(search="revival")
    assert first["cached"] is False
    assert first["types_total"] == 12
    assert first["types"][0]["code"] == 502
    assert first["types"][0]["count"] == 104273
    assert first["unnamed_codes"] == []

    second = await st.fpd_list_petition_types()
    assert len(asked) == 1  # served from the in-process cache
    assert second["cached"] is True
    assert second["types_total"] == 191
    assert second["types_shown"] == st.DEFAULT_LIST_LIMIT
    counts = [t["count"] for t in second["types"]]
    assert counts == sorted(counts, reverse=True)


async def test_list_petition_types_reports_an_unnamed_live_code(mock_runtime):
    st.clear_type_count_cache()
    mock_runtime.api_client.search_petitions.return_value = {
        "count": 3,
        "facets": {"decisionPetitionTypeCode": [{"value": "502", "count": 2}, {"value": "999", "count": 1}]},
        "petitionDecisionDataBag": [],
    }
    result = await st.fpd_list_petition_types()
    st.clear_type_count_cache()
    assert result["unnamed_codes"] == ["999"]
    assert result["types"][1] == {"code": 999, "name": None, "count": 1, "share": round(1 / 3, 4)}


@pytest.mark.parametrize("tool, kwargs", [
    (st.fpd_get_petition_statistics, {"dimensions": ["colour"]}),
    (st.fpd_get_petition_statistics, {"dimensions": ["petition_type", "art_unit", "year", "applicant", "rule"]}),
    (st.fpd_get_petition_statistics, {"top_n": 0}),
    (st.fpd_get_petition_statistics, {"turnaround_sample": 501}),
    (st.fpd_get_petition_statistics, {"decision_type": "WITHDRAWN"}),
    (st.fpd_get_dismissal_grounds, {"mention_phrases": ["a", "b", "c", "d", "e", "f"]}),
    (st.fpd_get_dismissal_grounds, {"mention_phrases": ['fee" OR *']}),
    (st.fpd_get_dismissal_grounds, {"sample_size": 26}),
    (st.fpd_list_petition_types, {"limit": 0}),
])
async def test_tools_reject_bad_arguments_with_a_400(mock_runtime, tool, kwargs):
    result = await tool(**kwargs)
    assert result["status_code"] == 400
    mock_runtime.api_client.search_petitions.assert_not_called()


async def test_upstream_error_envelope_passes_through(mock_runtime):
    envelope = {"error": "API error: boom", "status_code": 500, "success": False, "request_id": "r1"}
    mock_runtime.api_client.search_petitions.return_value = envelope
    result = await st.fpd_get_petition_statistics(petition_type_code="502")
    assert result == envelope


async def test_dimensions_accept_a_comma_string(mock_runtime):
    mock_runtime.api_client.search_petitions.return_value = {"count": 0, "facets": {}, "petitionDecisionDataBag": []}
    result = await st.fpd_get_petition_statistics(dimensions="art_unit, deciding_office")
    assert [t["dimension"] for t in result["dimensions"]] == ["art_unit", "deciding_office"]
    sent = mock_runtime.api_client.search_petitions.call_args.kwargs
    assert sent["facets"] == ["groupArtUnitNumber", "finalDecidingOfficeName"]
    assert sent["query"] == "decidedPetitionTypeCode:D"


async def test_lists_sent_as_json_strings_are_read_as_lists(mock_runtime):
    # claude.ai sent the documented list form as the string '["petition_type"]'
    # and the comma split refused it as one bad name (2026-10-07).
    mock_runtime.api_client.search_petitions.return_value = {"count": 0, "facets": {}, "petitionDecisionDataBag": []}
    result = await st.fpd_get_petition_statistics(dimensions='["art_unit", "year"]', petition_type_code="[501, 502]")
    assert result["success"] is True
    assert [t["dimension"] for t in result["dimensions"]][0] == "art_unit"
    assert "decisionPetitionTypeCode:(501 OR 502)" in result["scope"]["final_query"]


# ---------------------------------------------------------------------------
# Bounds and the client
# ---------------------------------------------------------------------------

def test_bucket_lists_are_trimmed_under_the_budget(monkeypatch):
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "2500")
    buckets = [{"value": f"{i:04d}", "total": i, "outcomes": {"GRANTED": i}, "rates": {"grant_rate": 1.0}}
               for i in range(50)]
    payload = {"success": True, "dimensions": [{"dimension": "art_unit", "buckets": list(buckets)}]}
    bounded = _bound_result(payload, "FPD_get_petition_statistics")

    assert bounded["_bounds"]["applied"] is True
    assert 5 <= len(bounded["dimensions"][0]["buckets"]) < 50
    assert bounded["dimensions"][0]["buckets"][0]["value"] == "0000"
    assert "top_n" in bounded["_bounds"]["note"]


def test_a_fitting_statistics_response_is_untouched():
    payload = {"success": True, "dimensions": [{"dimension": "art_unit", "buckets": [{"value": "1"}]}]}
    assert _bound_result(payload, "FPD_get_petition_statistics") is payload
    assert "_bounds" not in payload


async def test_client_sends_facets_in_the_body_only_when_asked(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "a" * 30)
    client = FPDClient(api_key="a" * 30)
    bodies = []

    async def _fake_request(endpoint, method="GET", **kwargs):
        bodies.append(kwargs["json"])
        return {"petitionDecisionDataBag": [], "count": 0, "facets": {"decidedPetitionTypeCode": []}}

    client._make_request = _fake_request
    result = await client.search_petitions(query="x", facets=["decidedPetitionTypeCode", "ruleBag"], limit=1)
    await client.search_petitions(query="x")

    assert bodies[0]["facets"] == ["decidedPetitionTypeCode", "ruleBag"]
    assert "facets" not in bodies[1]
    assert result["facets"] == {"decidedPetitionTypeCode": []}  # passed through untouched
