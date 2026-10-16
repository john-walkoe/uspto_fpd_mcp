"""Time budget and request cap on the two multi-call statistics tools
(2026-10-12 audit: RF-1/EH-1, S1 defense in depth, S46).

FPD_get_petition_statistics could make up to 21 sequential USPTO requests with
no deadline, so a slow upstream held the call far past claude.ai's ~100 s
cut. Both tools now run inside one Deadline (FPD_STATISTICS_DEADLINE_SECONDS,
default 60 s), the statistics tool makes at most MAX_UPSTREAM_REQUESTS, and
whatever did not fit is flagged in the response rather than dropped silently.
"""

import pytest

from fpd_mcp.tools import statistics as st
from fpd_mcp.util import deadline as deadline_module
from fpd_mcp.util.deadline import DEADLINE_EXCEEDED, current_deadline, deadline_exceeded_response

#: Outcome facet of a 1,000,000-record scope (the turnaround sample's total).
_FACET = {"decidedPetitionTypeCode": [{"value": "A", "count": 600_000}, {"value": "D", "count": 400_000}]}


def _page(count=100_000, **extra):
    return {"count": count, "facets": dict(_FACET), "petitionDecisionDataBag": [], **extra}


@pytest.fixture
def upstream(mock_runtime, monkeypatch):
    """search_petitions as a list of per-call behaviours; the last repeats."""
    st.clear_type_count_cache()
    seen = []

    def install(*behaviours):
        async def search_petitions(**kwargs):
            seen.append((kwargs, current_deadline()))
            index = min(len(seen) - 1, len(behaviours) - 1)
            behaviour = behaviours[index]
            return behaviour(kwargs) if callable(behaviour) else behaviour

        mock_runtime.api_client.search_petitions.side_effect = search_petitions
        return seen

    yield install
    st.clear_type_count_cache()


async def test_every_statistics_request_runs_inside_the_time_budget(upstream):
    seen = upstream(_page())
    result = await st.fpd_get_petition_statistics(petition_type_code="502", dimensions=[])

    assert result["success"] is True
    assert seen and all(d is not None for _, d in seen)
    assert seen[0][1].seconds == deadline_module.DEFAULT_STATISTICS_DEADLINE_SECONDS
    assert "partial" not in result


async def test_the_budget_follows_its_env_setting(upstream, monkeypatch):
    monkeypatch.setenv("FPD_STATISTICS_DEADLINE_SECONDS", "45")
    seen = upstream(_page())
    await st.fpd_get_dismissal_grounds(petition_type_code="502", sample_size=0)
    assert all(d.seconds == 45.0 for _, d in seen)


async def test_no_time_for_the_core_counts_is_an_authored_408(upstream, monkeypatch):
    # Under MIN_ATTEMPT_SECONDS of budget no USPTO request is started at all.
    monkeypatch.setenv("FPD_STATISTICS_DEADLINE_SECONDS", "1")
    seen = upstream(_page())
    result = await st.fpd_get_petition_statistics(petition_type_code="502")

    assert seen == []
    assert result["status_code"] == 408
    assert result["error"].startswith(DEADLINE_EXCEEDED)


async def test_a_deadline_during_the_years_returns_what_was_counted(upstream):
    # 4 outcome calls, 2 years, then the budget is spent.
    behaviours = [_page()] * 6 + [lambda kw: deadline_exceeded_response()]
    upstream(*behaviours)
    result = await st.fpd_get_petition_statistics(
        petition_type_code="502", dimensions=["petition_type", "year"],
    )

    assert result["success"] is True
    assert result["partial"] is True
    assert result["deadline_exceeded"] is True
    assert result["partial_reason"] == st.PARTIAL_TIME_BUDGET
    assert result["incomplete_sections"] == ["by_year"]
    by_year = result["by_year"]
    assert len(by_year["buckets"]) == 2
    assert by_year["complete"] is False
    assert len(by_year["years_not_counted"]) == 10
    assert result["outcomes"]["GRANTED"]["count"] == 100_000  # core counts intact


async def test_the_statistics_call_never_exceeds_its_request_cap(upstream):
    seen = upstream(_page())
    result = await st.fpd_get_petition_statistics(
        dimensions=["petition_type", "year"], turnaround_sample=500,
    )

    assert len(seen) == result["upstream_requests"] == st.MAX_UPSTREAM_REQUESTS
    assert result["partial"] is True
    assert result["partial_reason"] == st.PARTIAL_REQUEST_CAP
    assert result["incomplete_sections"] == ["turnaround"]
    turnaround = result["turnaround"]
    assert turnaround["sample_complete"] is False
    assert turnaround["records_sampled"] == 0
    assert "No USPTO request was left" in turnaround["note"]


async def test_the_cap_trims_years_newest_kept(upstream, monkeypatch):
    monkeypatch.setattr(st, "MAX_UPSTREAM_REQUESTS", 8)
    seen = upstream(_page())
    result = await st.fpd_get_petition_statistics(dimensions=["petition_type", "year"])

    assert len(seen) == 8
    by_year = result["by_year"]
    kept = [b["year"] for b in by_year["buckets"]]
    assert len(kept) == 4 and kept == sorted(kept, reverse=True)
    assert by_year["incomplete_reason"] == st.PARTIAL_REQUEST_CAP
    assert all(y < min(kept) for y in by_year["years_not_counted"])


async def test_the_cap_keeps_turnaround_blocks_evenly_spaced(upstream, monkeypatch):
    monkeypatch.setattr(st, "MAX_UPSTREAM_REQUESTS", 3)  # 1 core call + 2 blocks
    seen = upstream(_page(count=1_000_000))
    result = await st.fpd_get_petition_statistics(dimensions=[], turnaround_sample=500)

    offsets = [kw["offset"] for kw, _ in seen[1:]]
    assert offsets == [0, 500_000]
    assert result["turnaround"]["sample_complete"] is False
    assert "cut to 2" in result["turnaround"]["method"]


async def test_a_failed_turnaround_block_is_reported_not_called_even(upstream):
    """S46: a lost block used to leave 'evenly spaced offsets' in the method."""
    failure = {"error": "API error: boom", "status_code": 500, "success": False}
    upstream(_page(count=1_000_000), _page(count=1_000_000), failure, _page(count=1_000_000))
    result = await st.fpd_get_petition_statistics(dimensions=[], turnaround_sample=300)

    turnaround = result["turnaround"]
    assert turnaround["blocks_failed"] == 1
    assert turnaround["sample_complete"] is False
    assert "1 of 3 block(s) did not come back" in turnaround["method"]
    assert "indicative" in turnaround["method"]


async def test_a_whole_turnaround_sample_is_complete(upstream):
    upstream(_page(count=1_000_000))
    result = await st.fpd_get_petition_statistics(dimensions=[], turnaround_sample=200)
    assert result["turnaround"]["sample_complete"] is True
    assert "did not come back" not in result["turnaround"]["method"]


async def test_dismissal_grounds_flags_phrases_not_counted_in_time(upstream):
    upstream(_page(), _page(), _page(), lambda kw: deadline_exceeded_response())
    result = await st.fpd_get_dismissal_grounds(
        petition_type_code="502", sample_size=0,
        mention_phrases=["petition fee", "terminal disclaimer", "unintentional"],
    )

    assert result["success"] is True
    assert [m["phrase"] for m in result["mentions"]] == ["petition fee"]
    assert result["mentions_not_counted"] == ["terminal disclaimer", "unintentional"]
    assert result["partial"] is True and result["incomplete_sections"] == ["mentions"]


async def test_dismissal_grounds_without_its_core_counts_is_a_408(upstream):
    upstream(lambda kw: deadline_exceeded_response())
    result = await st.fpd_get_dismissal_grounds(petition_type_code="502")
    assert result["status_code"] == 408
    assert result["error"].startswith(DEADLINE_EXCEEDED)
