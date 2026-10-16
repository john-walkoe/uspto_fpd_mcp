"""Tests for the shared response-size guard (shared/response_bounds.py) and
its two attach points: the tools/__init__.py registration proxy and
FPD_Get_petition_details.

Hermetic: no network, no FastMCP server. The registration-proxy test drives a
stand-in `mcp` object that records what was registered.
"""

import json

import pytest

from fpd_mcp.shared.response_bounds import (
    BOUNDS_KEY,
    WINDOW_KEY,
    apply_text_window,
    bound_structured_response,
    bounds_config,
    content_char_budget,
    measure_chars,
    response_char_budget,
    window_text,
)

_BAG_PATH = ["records", "*", "documentBag"]


def _doc(i: int) -> dict:
    return {
        "documentIdentifier": f"DOC{i:04d}",
        "documentCode": "PET",
        "pageCount": 3,
        # The payload hog the guard is meant to shed.
        "downloadOptionBag": [
            {"mimeTypeIdentifier": "PDF", "downloadUrl": "https://api.uspto.gov/" + "x" * 200}
            for _ in range(3)
        ],
    }


def _payload(n_docs: int = 40) -> dict:
    return {"records": [{"id": "abc", "documentBag": [_doc(i) for i in range(n_docs)]}]}


def _spec(min_items: int = 10) -> dict:
    return {
        "path": _BAG_PATH,
        "keep_fields": ("documentIdentifier", "documentCode", "pageCount"),
        "min_items": min_items,
        "label": "documentBag",
    }


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def test_env_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("USPTO_MAX_RESPONSE_CHARS", raising=False)
    monkeypatch.delenv("USPTO_MAX_CONTENT_CHARS", raising=False)
    monkeypatch.delenv("USPTO_RESPONSE_BOUNDS_ENABLED", raising=False)
    assert response_char_budget() == 40_000
    assert content_char_budget() == 120_000
    assert bounds_config()["enabled"] is True

    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "12345")
    monkeypatch.setenv("USPTO_MAX_CONTENT_CHARS", "9999")
    monkeypatch.setenv("USPTO_RESPONSE_BOUNDS_ENABLED", "false")
    config = bounds_config()
    assert config["max_response_chars"] == 12345
    assert config["max_content_chars"] == 9999
    assert config["enabled"] is False

    # Garbage and non-positive values fall back to the defaults rather than
    # disabling the guard by accident.
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "not-a-number")
    assert response_char_budget() == 40_000
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "0")
    assert response_char_budget() == 40_000


# ---------------------------------------------------------------------------
# Guard 1: structured responses
# ---------------------------------------------------------------------------

def test_no_op_is_identity_and_byte_equal():
    payload = _payload(2)
    before = json.dumps(payload, default=str)

    result = bound_structured_response(payload, bags=(_spec(),), limit=1_000_000)

    assert result is payload  # same object, not a copy
    assert json.dumps(result, default=str) == before
    assert BOUNDS_KEY not in result


def test_disabled_guard_is_identity_even_when_oversized(monkeypatch):
    monkeypatch.setenv("USPTO_RESPONSE_BOUNDS_ENABLED", "0")
    payload = _payload(40)
    before = json.dumps(payload, default=str)

    result = bound_structured_response(payload, bags=(_spec(),), limit=500)

    assert result is payload
    assert json.dumps(result, default=str) == before
    assert BOUNDS_KEY not in result


def test_stage_1_slims_heavy_fields_only():
    payload = _payload(20)
    limit = 4_000
    assert measure_chars(payload) > limit

    result = bound_structured_response(payload, bags=(_spec(),), limit=limit, note="recover me")

    bounds = result[BOUNDS_KEY]
    assert bounds["stages"] == ["slimmed"]  # halving was not needed
    assert bounds["slimmed_fields"] == ["downloadOptionBag"]
    assert bounds["items_returned"] == bounds["items_total"] == 20
    assert bounds["note"] == "recover me"
    assert measure_chars(result) <= limit
    docs = result["records"][0]["documentBag"]
    assert all("downloadOptionBag" not in d for d in docs)
    assert docs[0]["documentIdentifier"] == "DOC0000"


def test_stage_2_halves_down_to_the_floor():
    payload = _payload(400)
    limit = 2_000

    result = bound_structured_response(payload, bags=(_spec(min_items=10),), limit=limit)

    bounds = result[BOUNDS_KEY]
    assert bounds["stages"] == ["slimmed", "truncated"]
    assert bounds["items_total"] == 400
    assert bounds["items_returned"] >= 10  # floor respected
    assert bounds["items_returned"] < 400
    assert len(result["records"][0]["documentBag"]) == bounds["items_returned"]


def test_floor_is_respected_even_when_it_cannot_fit():
    """The floor wins over the budget: dropping below it would leave the
    caller with nothing useful. The marker still tells the truth."""
    payload = _payload(40)

    result = bound_structured_response(payload, bags=(_spec(min_items=30),), limit=1_000)

    assert result[BOUNDS_KEY]["items_returned"] == 30


def test_marker_vocabulary_is_exact():
    result = bound_structured_response(_payload(400), bags=(_spec(),), limit=2_000)

    assert set(result[BOUNDS_KEY]) == {
        "applied",
        "reason",
        "size_chars",
        "size_limit",
        "stages",
        "slimmed_fields",
        "items_returned",
        "items_total",
        "note",
    }
    assert result[BOUNDS_KEY]["applied"] is True
    assert result[BOUNDS_KEY]["reason"] == "size"
    assert result[BOUNDS_KEY]["size_limit"] == 2_000
    assert result[BOUNDS_KEY]["size_chars"] == measure_chars(result)


def test_legacy_aliases_are_mirrored():
    aliases = {
        "items_returned": "documents_returned",
        "items_total": "documents_total",
        "note": "documents_note",
    }
    result = bound_structured_response(
        _payload(400), bags=(_spec(),), limit=2_000, note="use FPD_get_document_download", aliases=aliases
    )

    assert result["documents_total"] == 400
    assert result["documents_returned"] == result[BOUNDS_KEY]["items_returned"]
    assert result["documents_note"] == "use FPD_get_document_download"


def test_text_fallback_truncates_the_largest_string_with_a_marker():
    payload = {"extracted_content": "z" * 50_000, "meta": "small"}

    result = bound_structured_response(payload, bags=(), limit=5_000, text_fallback=True)

    assert measure_chars(result) <= 5_000
    assert result[BOUNDS_KEY]["stages"] == ["truncated"]
    assert "extracted_content" in result[BOUNDS_KEY]["note"]
    assert len(result["extracted_content"]) < 50_000


def test_oversized_with_nothing_to_shed_is_still_marked():
    payload = {"extracted_content": "z" * 50_000}

    result = bound_structured_response(payload, bags=(), limit=5_000, text_fallback=False)

    # Nothing could be dropped, but the caller is told the client may reject it.
    assert result[BOUNDS_KEY]["applied"] is True
    assert result[BOUNDS_KEY]["stages"] == []


# ---------------------------------------------------------------------------
# Guard 2: text windows
# ---------------------------------------------------------------------------

_PAGES = "\n\n".join(f"=== PAGE {i} ===\n{'abcde ' * 100}" for i in range(1, 21))


def test_window_text_no_op_when_everything_fits():
    result = window_text("short text", max_chars=1_000)

    assert result == {"text": "short text"}
    assert WINDOW_KEY not in result


def test_window_text_char_unit():
    text = "y" * 10_000

    result = window_text(text, offset=0, max_chars=1_000, note="next")

    window = result[WINDOW_KEY]
    assert window["unit"] == "char"
    assert window["offset"] == 0
    assert window["returned"] == 1_000
    assert window["total"] == 10_000
    assert window["has_more"] is True
    assert window["next_offset"] == 1_000
    assert window["note"] == "next"
    assert result["text"] == text[:1_000]


def test_window_text_page_edges_snap_to_page_boundaries():
    result = window_text(_PAGES, offset=0, max_chars=2_000)

    window = result[WINDOW_KEY]
    # `edges` records the snapping; `unit` names the counters, which are
    # characters whether or not the edges snapped (re-vendored from PTAB,
    # CR-D review 2026-09-28: FPD's `unit` used to read "page" directly
    # above four character counters).
    assert window["edges"] == "page"
    assert window["unit"] == "char"
    assert window["returned"] <= 2_000
    # The window ends exactly where a page marker begins.
    assert _PAGES[window["next_offset"]:].startswith("=== PAGE ")
    assert result["text"].startswith("=== PAGE 1 ===")


def test_window_text_single_oversized_page_degrades_to_char_edges():
    text = "=== PAGE 1 ===\n" + "q" * 5_000

    result = window_text(text, max_chars=1_000)

    assert result[WINDOW_KEY]["edges"] == "char"
    assert result[WINDOW_KEY]["unit"] == "char"
    assert result[WINDOW_KEY]["returned"] == 1_000


def test_window_unit_always_reports_characters():
    """The counters are characters in every case, and the label says so."""
    paged = window_text(_PAGES, offset=0, max_chars=2_000)[WINDOW_KEY]
    raw = window_text("y" * 10_000, max_chars=1_000)[WINDOW_KEY]

    assert paged["unit"] == raw["unit"] == "char"


def test_window_text_cursor_walks_the_whole_document():
    seen, offset, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 100
        result = window_text(_PAGES, offset=offset, max_chars=2_000)
        seen.append(result["text"])
        window = result.get(WINDOW_KEY)
        if not window or not window["has_more"]:
            break
        offset = window["next_offset"]

    # Pages are never split and nothing is lost.
    assert "".join(seen) == _PAGES


def test_window_text_offset_snaps_back_to_the_containing_page():
    first_page_len = _PAGES.index("=== PAGE 2 ===")

    result = window_text(_PAGES, offset=first_page_len - 5, max_chars=2_000)

    assert result[WINDOW_KEY]["offset"] == 0
    assert result["text"].startswith("=== PAGE 1 ===")


def test_window_text_single_oversized_page_degrades_to_char_unit():
    text = "=== PAGE 1 ===\n" + "q" * 5_000

    result = window_text(text, max_chars=1_000)

    assert result[WINDOW_KEY]["unit"] == "char"
    assert result[WINDOW_KEY]["returned"] == 1_000


def test_window_marker_vocabulary_is_exact():
    result = window_text("y" * 10_000, max_chars=1_000)

    assert set(result[WINDOW_KEY]) == {
        "unit",
        "edges",
        "offset",
        "returned",
        "total",
        "has_more",
        "next_offset",
        "note",
    }


def test_apply_text_window_attaches_markers_and_aliases():
    payload = {"extracted_content": "y" * 10_000}

    apply_text_window(
        payload,
        "extracted_content",
        max_chars=1_000,
        note="call again with char_offset",
        aliases={"applied": "truncated", "note": "truncation_note"},
    )

    assert payload[WINDOW_KEY]["has_more"] is True
    assert payload["truncated"] is True
    assert payload["truncation_note"] == "call again with char_offset"
    assert payload[BOUNDS_KEY]["reason"] == "window"


def test_apply_text_window_is_identity_when_it_fits():
    payload = {"extracted_content": "short"}
    before = json.dumps(payload)

    apply_text_window(payload, "extracted_content", max_chars=1_000)

    assert json.dumps(payload) == before
    assert WINDOW_KEY not in payload
    assert BOUNDS_KEY not in payload


# ---------------------------------------------------------------------------
# Attach point: the tools/__init__.py registration proxy
# ---------------------------------------------------------------------------

class _FakeMCP:
    """Records what a register() call would have registered."""

    def __init__(self):
        self.registered = {}

    def tool(self, *args, **kwargs):
        def decorator(fn):
            self.registered[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorator


async def test_registration_proxy_guards_every_tool_response():
    from fpd_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    bounded = _BoundedRegistrar(fake)

    async def big_tool(petition_id: str, include_documents: bool = True):
        return {"extracted": "z" * 200_000, "petition_id": petition_id}

    bounded.tool(name="FPD_Search_petitions_minimal")(big_tool)
    registered = fake.registered["FPD_Search_petitions_minimal"]

    # Signature is preserved, so FastMCP derives the same input schema.
    import inspect

    assert list(inspect.signature(registered).parameters) == ["petition_id", "include_documents"]

    result = await registered("abc")
    assert measure_chars(result) <= response_char_budget()
    assert result[BOUNDS_KEY]["applied"] is True


async def test_registration_proxy_is_byte_transparent_for_small_responses():
    from fpd_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def small_tool():
        return {"ok": True}

    _BoundedRegistrar(fake).tool(name="FPD_get_guidance")(small_tool)

    assert await fake.registered["FPD_get_guidance"]() == {"ok": True}


async def test_registration_proxy_passes_plain_strings_through():
    from fpd_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def guidance_tool(section: str = "overview"):
        return "# Markdown guidance\n\nnot JSON at all"

    _BoundedRegistrar(fake).tool(name="FPD_get_guidance")(guidance_tool)

    assert await fake.registered["FPD_get_guidance"]() == "# Markdown guidance\n\nnot JSON at all"


async def test_registration_proxy_guards_json_string_returns():
    from fpd_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def json_tool():
        return json.dumps({"extracted": "z" * 200_000})

    _BoundedRegistrar(fake).tool(name="FPD_Search_petitions_minimal")(json_tool)

    raw = await fake.registered["FPD_Search_petitions_minimal"]()
    assert isinstance(raw, str)
    parsed = json.loads(raw)
    assert parsed[BOUNDS_KEY]["applied"] is True
    assert len(raw) <= response_char_budget()


def test_registration_proxy_passes_other_attributes_through():
    from fpd_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    fake.custom_route = lambda *a, **k: "routed"

    assert _BoundedRegistrar(fake).custom_route() == "routed"


# ---------------------------------------------------------------------------
# Attach point: FPD_Get_petition_details
# ---------------------------------------------------------------------------

@pytest.fixture
def _big_petition():
    from fpd_mcp.api.field_constants import FPDFields

    return {
        FPDFields.PETITION_DECISION_DATA_BAG: [
            {
                FPDFields.PETITION_DECISION_RECORD_IDENTIFIER: "e55bd36d-961f-511e-b72c-b4b1529d67ef",
                FPDFields.DOCUMENT_BAG: [
                    {
                        FPDFields.DOCUMENT_IDENTIFIER: f"DOC{i:04d}",
                        FPDFields.DOCUMENT_CODE: "PET",
                        FPDFields.PAGE_COUNT: 4,
                        # CR-59/MCP-9 (review 2026-09-28): downloadOptionBag
                        # is now stripped unconditionally, BEFORE the size
                        # guard ever sees the response (see
                        # _strip_raw_document_urls), so it can no longer be
                        # the field that pushes this fixture over budget.
                        # A different heavy, non-keep_fields field does the
                        # same job of exercising stage-1 slimming.
                        FPDFields.DOWNLOAD_OPTION_BAG: [
                            {
                                FPDFields.MIME_TYPE_IDENTIFIER: "PDF",
                                FPDFields.DOWNLOAD_URL: "https://api.uspto.gov/" + "x" * 300,
                            }
                        ],
                        "legacyExaminerNotes": "z" * 300,
                    }
                    for i in range(120)
                ],
            }
        ]
    }


async def test_petition_details_guard_slims_and_keeps_legacy_keys(mock_runtime, _big_petition):
    from fpd_mcp.tools.petitions import fpd_get_petition_details

    mock_runtime.api_client.get_petition_by_id.return_value = _big_petition

    result = await fpd_get_petition_details(
        petition_id="e55bd36d-961f-511e-b72c-b4b1529d67ef", include_documents=True
    )

    assert measure_chars(result) <= response_char_budget()
    assert result[BOUNDS_KEY]["items_total"] == 120
    # Legacy marker keys stay alongside the new vocabulary.
    assert result["documents_total"] == 120
    assert result["documents_returned"] == result[BOUNDS_KEY]["items_returned"]
    assert isinstance(result["documents_note"], str)

    docs = result["petitionDecisionDataBag"][0]["documentBag"]
    assert all("downloadOptionBag" not in d for d in docs)
    assert all("documentIdentifier" in d for d in docs)


async def test_petition_details_small_response_has_no_bounds_key(mock_runtime):
    from fpd_mcp.tools.petitions import fpd_get_petition_details

    mock_runtime.api_client.get_petition_by_id.return_value = {
        "petitionDecisionDataBag": [{"petitionDecisionRecordIdentifier": "x", "documentBag": []}]
    }

    result = await fpd_get_petition_details(
        petition_id="e55bd36d-961f-511e-b72c-b4b1529d67ef", include_documents=True
    )

    assert BOUNDS_KEY not in result
    assert "documents_note" not in result


# ---------------------------------------------------------------------------
# _bounds.items_total vs paging.total (ARCH-03, review 2026-09-28)
# ---------------------------------------------------------------------------
# FPD used to rewrite `_bounds.items_total` to `paging.total` after the
# guard ran, redefining the canonical marker's meaning against PTAB and PFW
# (neither has an equivalent rewrite). Removed: `items_total` is the shared
# guard's own count (items in the bag(s) it was handed), same as every
# sibling repo; `paging.total`, unaffected by the guard, remains the place
# to read the full result-set size.

async def test_bounds_items_total_is_the_guards_own_count_not_paging_total():
    from fpd_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def paged_tool():
        return {
            "petitionDecisionDataBag": [
                {"id": i, "blob": "z" * 2_000} for i in range(50)
            ],
            "count": 53,
            "paging": {
                "limit_requested": 50,
                "limit_applied": 50,
                "offset": 0,
                "returned": 50,
                "total": 53,
                "has_more": True,
                "next_offset": 50,
            },
        }

    _BoundedRegistrar(fake).tool(name="FPD_Search_petitions_balanced")(paged_tool)

    result = await fake.registered["FPD_Search_petitions_balanced"]()

    bounds = result[BOUNDS_KEY]
    assert bounds["applied"] is True
    # paging.total (the full result set) is untouched by the guard...
    assert result["paging"]["total"] == 53
    # ...items_total is the page the guard was HANDED (50), and
    # items_returned is what it KEPT after trimming — same meaning as PTAB
    # and PFW, no longer mirrored from paging.total.
    kept = len(result["petitionDecisionDataBag"])
    assert bounds["items_total"] == 50
    assert bounds["items_returned"] == kept
    assert kept < 50
    assert result["paging"]["returned"] == kept
    assert result["paging"]["next_offset"] == kept
    assert result["paging"]["has_more"] is True


async def test_bounds_items_total_untouched_without_a_paging_block():
    """FPD_Get_petition_details has no paging envelope; the guard's own count
    stands, and the documents_total alias is not rewritten either."""
    from fpd_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def details_tool():
        return {
            "petitionDecisionDataBag": [
                {
                    "petitionDecisionRecordIdentifier": "x",
                    "documentBag": [
                        {"documentIdentifier": str(i), "downloadOptionBag": ["z" * 900]}
                        for i in range(80)
                    ],
                }
            ]
        }

    _BoundedRegistrar(fake).tool(name="FPD_Get_petition_details")(details_tool)

    result = await fake.registered["FPD_Get_petition_details"]()

    assert "paging" not in result
    # The guard's own count over the configured bags (80 documents + the 1
    # petition record), left exactly as it was, alias included.
    assert result[BOUNDS_KEY]["items_total"] == 81
    assert result["documents_total"] == 81


# ---------------------------------------------------------------------------
# Paging honesty: a trimmed page reports what it carries (2026-09-11). FPD_Search_petitions_minimal(decision_type="DENIED", limit=100)
# went over the budget, the guard kept 50 rows, and `paging` still said
# returned 100 / next_offset 100, so a caller paging by next_offset skipped
# rows 50-99 without being told.
# ---------------------------------------------------------------------------

_PAGING_SPEC = {"key": "paging", "path": ["rows"]}


def _page(offset: int, n: int, total: int, blob: int = 400) -> dict:
    has_more = offset + n < total
    return {
        "rows": [{"i": offset + k, "blob": "z" * blob} for k in range(n)],
        "paging": {
            "limit_requested": n,
            "limit_applied": n,
            "offset": offset,
            "returned": n,
            "total": total,
            "has_more": has_more,
            "next_offset": offset + n if has_more else None,
        },
    }


def _rows_spec(floor: int = 5) -> dict:
    return {"path": ["rows"], "keep_fields": (), "min_items": floor, "label": "rows"}


def test_trimmed_page_reports_the_rows_it_carries():
    payload = _page(offset=0, n=100, total=7481)

    result = bound_structured_response(
        payload, bags=(_rows_spec(),), limit=20_000, paging=_PAGING_SPEC
    )

    kept = len(result["rows"])
    assert 5 <= kept < 100
    assert result[BOUNDS_KEY]["items_returned"] == kept
    assert result["paging"]["returned"] == kept
    assert result["paging"]["next_offset"] == kept
    assert result["paging"]["has_more"] is True
    assert result["paging"]["total"] == 7481  # the result set, untouched
    assert result["paging"]["offset"] == 0
    assert result["paging"]["limit_applied"] == 100  # what upstream was asked for


def test_trimmed_page_cursor_is_offset_plus_kept():
    payload = _page(offset=300, n=100, total=7481)

    result = bound_structured_response(
        payload, bags=(_rows_spec(),), limit=20_000, paging=_PAGING_SPEC
    )

    kept = len(result["rows"])
    assert result["rows"][0]["i"] == 300  # the head of the page is what stays
    assert result["paging"]["next_offset"] == 300 + kept


def test_trimmed_last_page_gets_a_cursor_back():
    """A last page has has_more false and no cursor. Once the guard drops some
    of its rows there IS more to fetch, so both have to come back."""
    payload = _page(offset=7400, n=81, total=7481)
    assert payload["paging"]["has_more"] is False
    assert payload["paging"]["next_offset"] is None

    result = bound_structured_response(
        payload, bags=(_rows_spec(),), limit=15_000, paging=_PAGING_SPEC
    )

    kept = len(result["rows"])
    assert kept < 81
    assert result["paging"]["has_more"] is True
    assert result["paging"]["next_offset"] == 7400 + kept


def test_paging_without_a_cursor_keeps_next_offset():
    """`cursor: False` is for a tool with no offset parameter to follow: the
    count and has_more are corrected, next_offset is not invented."""
    payload = _page(offset=0, n=100, total=0)
    payload["paging"].update({"total": None, "has_more": False, "next_offset": None})

    result = bound_structured_response(
        payload,
        bags=(_rows_spec(),),
        limit=20_000,
        paging={"key": "paging", "path": ["rows"], "cursor": False},
    )

    kept = len(result["rows"])
    assert result["paging"]["returned"] == kept < 100
    assert result["paging"]["has_more"] is True
    assert result["paging"]["next_offset"] is None


def test_paging_untouched_when_nothing_was_dropped():
    # Fits: identity, no marker, paging exactly as built.
    small = _page(offset=0, n=3, total=10)
    before = json.dumps(small)
    assert bound_structured_response(
        small, bags=(_rows_spec(),), limit=1_000_000, paging=_PAGING_SPEC
    ) is small
    assert json.dumps(small) == before

    # Over budget but shed by slimming alone: every row survives, so the
    # cursor was already right and must not move.
    slimmable = {
        "rows": [{"i": k, "heavy": "z" * 500} for k in range(20)],
        "paging": {"offset": 0, "returned": 20, "total": 40, "has_more": True, "next_offset": 20},
    }
    result = bound_structured_response(
        slimmable,
        bags=({"path": ["rows"], "keep_fields": ("i",), "min_items": 5, "label": "rows"},),
        limit=5_000,
        paging=_PAGING_SPEC,
    )
    assert result[BOUNDS_KEY]["stages"] == ["slimmed"]
    assert result["paging"] == {
        "offset": 0, "returned": 20, "total": 40, "has_more": True, "next_offset": 20,
    }


def test_paging_untouched_without_a_paging_spec():
    """Back-compat: a caller that passes no spec gets the old behaviour."""
    payload = _page(offset=0, n=100, total=7481)

    result = bound_structured_response(payload, bags=(_rows_spec(),), limit=20_000)

    assert len(result["rows"]) < 100
    assert result["paging"]["returned"] == 100
    assert result["paging"]["next_offset"] == 100


def _fpd_page(offset: int, limit: int, corpus: list, total: int) -> dict:
    """A search-tool response over a synthetic corpus, shaped like
    petitions._paging_envelope builds it."""
    rows = corpus[offset:offset + limit]
    has_more = offset + len(rows) < total
    return {
        "petitionDecisionDataBag": [dict(r) for r in rows],
        "count": total,
        "paging": {
            "limit_requested": limit,
            "limit_applied": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_more": has_more,
            "next_offset": offset + len(rows) if has_more else None,
        },
    }


@pytest.mark.parametrize(
    "tool",
    [
        "FPD_Search_petitions_minimal",
        "FPD_Search_petitions_balanced",
        "FPD_Search_petitions_by_art_unit",
        "FPD_Search_petitions_by_application",
    ],
)
async def test_paging_by_next_offset_visits_every_row_exactly_once(tool, monkeypatch):
    """Walk a result set whose every page overflows the budget, through the
    real registrar wiring, feeding back only `paging.next_offset`."""
    from fpd_mcp.tools import _BoundedRegistrar

    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "12000")
    total = 437
    corpus = [
        {"petitionDecisionRecordIdentifier": f"p{k:04d}", "blob": "z" * (200 + (k % 7) * 40)}
        for k in range(total)
    ]

    fake = _FakeMCP()

    async def search(limit: int = 100, offset: int = 0):
        return _fpd_page(offset, limit, corpus, total)

    _BoundedRegistrar(fake).tool(name=tool)(search)
    registered = fake.registered[tool]

    seen: list = []
    offset, trimmed_pages = 0, 0
    for _ in range(total):  # a loop guard, never reached
        pre_trim_len = min(100, total - offset)
        page = await registered(limit=100, offset=offset)
        rows = page["petitionDecisionDataBag"]
        assert page["paging"]["returned"] == len(rows)
        assert page["paging"]["offset"] == offset
        if BOUNDS_KEY in page:
            trimmed_pages += 1
            # items_returned is what survived the guard; items_total is the
            # page it was handed BEFORE trimming (ARCH-03: no longer
            # rewritten to paging.total, which is the full result set).
            assert page[BOUNDS_KEY]["items_returned"] == len(rows)
            assert page[BOUNDS_KEY]["items_total"] == pre_trim_len
            assert page["paging"]["total"] == total
        seen.extend(r["petitionDecisionRecordIdentifier"] for r in rows)
        if not page["paging"]["has_more"]:
            assert page["paging"]["next_offset"] is None
            break
        assert page["paging"]["next_offset"] == offset + len(rows)
        offset = page["paging"]["next_offset"]

    assert trimmed_pages > 0  # the walk really did go through the guard
    assert seen == [r["petitionDecisionRecordIdentifier"] for r in corpus]
