"""Tool registration package (SD-1/SOLID-1 god-module split).

Each module defines its tools as plain (envelope-wrapped) async functions and
exposes register(mcp); register_all preserves the historical registration
order: admin -> petitions (search/details) -> statistics -> documents ->
guidance.

register_all also wraps the FastMCP object in a thin registration proxy
(`_BoundedRegistrar`) so EVERY tool response passes through the shared
response-size guard (`shared/response_bounds.py`) on the way out — one
attach point instead of per-tool wiring. claude.ai replaces an oversized
tool result with a client-side truncation error the server never sees, so an
unguarded tool is an unrecoverable failure for the model; the guard trades
some records/fields for a usable response plus a recovery note. Responses
that already fit are returned byte-identically (no `_bounds` key at all).

F-D5 (design-pattern-implmentation): the proxy covers TOOLS only. Prompt
templates and the three `ui://fpd/` HTML resources are registered against
the raw FastMCP object in `server_app.build_server()` and do not pass
through the guard. That is low-impact today — the HTML views are static
constants and the ten prompts are gated off by default — but "every tool
response" is narrower than a reader will assume when prompts are enabled, so
it is stated here rather than left to be discovered.
"""

import functools
import inspect
import json
from typing import Any, Dict

from ..api.field_constants import FPDFields
from ..shared import response_bounds

from . import admin, documents, guidance, petitions, statistics


# ---------------------------------------------------------------------------
# Per-tool guard configuration
# ---------------------------------------------------------------------------
# Everything repo-specific lives HERE; shared/response_bounds.py stays
# repo-agnostic and byte-identical across the USPTO MCPs.

_PETITION_RECORDS_PATH = [FPDFields.PETITION_DECISION_DATA_BAG]
_DOCUMENT_BAG_PATH = [FPDFields.PETITION_DECISION_DATA_BAG, "*", FPDFields.DOCUMENT_BAG]

#: documentBag entries slimmed to what a follow-up call actually needs —
#: downloadOptionBag (the payload hog) is dropped because
#: FPD_get_document_download only needs a documentIdentifier.
_DOCUMENT_BAG_SPEC = {
    "path": _DOCUMENT_BAG_PATH,
    "keep_fields": petitions._DOC_SLIM_FIELDS,
    "min_items": petitions._DETAILS_MIN_DOCS,
    "label": FPDFields.DOCUMENT_BAG,
}

#: An EMPTY keep_fields means stage 1 skips these records entirely (see
#: shared/response_bounds.py::_stage_slim), which is what keeps every row's
#: `cite_as` link alive under the guard. If a field whitelist is ever added
#: here, `cite_as` has to be on it: a slimmed page still has to be citable.
_SEARCH_RECORDS_SPEC = {
    "path": _PETITION_RECORDS_PATH,
    "keep_fields": (),  # already field-filtered by FieldManager
    "min_items": 5,
    "label": FPDFields.PETITION_DECISION_DATA_BAG,
}

#: The paging block every search tool publishes (petitions._paging_envelope)
#: and the record list it counts. The guard rewrites that block when it drops
#: records, so a trimmed page reports what it carries: `returned` is the rows
#: kept, `next_offset` is offset + rows kept, `has_more` is true. Before this,
#: a 100-row page cut to 50 still said `returned: 100, next_offset: 100`, and
#: a caller paging by next_offset skipped rows 50-99 without being told
#: (FPD_Search_petitions_minimal(decision_type="DENIED", limit=100), 2026-09-11).
_SEARCH_PAGING = {"key": "paging", "path": _PETITION_RECORDS_PATH}

_SEARCH_NOTE_TEMPLATE = (
    "Response exceeded the client response-size limit, so fewer records were "
    "returned than requested. `paging.next_offset` points at the first record "
    "not returned: re-call {tool} with offset=<paging.next_offset> (and a "
    "smaller limit=) to retrieve the rest."
)

_DETAILS_NOTE = (
    "Response exceeded the client response-size limit. documentBag entries were "
    "slimmed to essential fields (and the bag truncated if still too large) so the "
    "payload survives instead of being replaced by an unrecoverable truncation "
    "error. Every documentIdentifier shown is usable with "
    "FPD_get_document_download(petition_id=..., document_identifier=...); re-call "
    "FPD_Get_petition_details(petition_id=..., include_documents=False) if you only "
    "need petition fields."
)

_CONTENT_NOTE = (
    "Extracted content exceeded the content-size limit. Re-call "
    "FPD_get_document_content_with_ocr(petition_id=..., "
    "document_identifier=..., char_offset=<_window.next_offset>) to continue "
    "from where this window ended."
)

#: Canonical `_bounds` sub-key -> this repo's pre-existing top-level key.
#: Kept for this release so consumers written against the old vocabulary
#: (documents_returned / documents_total / documents_note) keep working.
#: The statistics tools carry their breakdowns as lists of buckets. Under the
#: budget the guard halves each list toward its floor (the largest values
#: come first, so what is cut is the tail) and `_bounds` says so.
_STATISTICS_BAGS = (
    {"path": ["dimensions", "*", "buckets"], "keep_fields": (), "min_items": 5, "label": "dimension buckets"},
)
_DISMISSAL_BAGS = tuple(
    {"path": [key, "buckets"], "keep_fields": (), "min_items": 5, "label": key}
    for key in ("by_petition_type", "by_technology_center", "by_rule", "by_statute")
) + ({"path": ["sample"], "keep_fields": (), "min_items": 3, "label": "sample"},)

_STATISTICS_NOTE = (
    "Response exceeded the client response-size limit, so the longest bucket lists "
    "were cut to their largest values. Re-call with a smaller top_n= or fewer "
    "dimensions= to see a complete list."
)
_DISMISSAL_NOTE = (
    "Response exceeded the client response-size limit, so bucket lists and the sample "
    "were cut. Re-call FPD_get_dismissal_grounds with a smaller top_n= or sample_size=."
)
_TYPES_NOTE = (
    "Response exceeded the client response-size limit, so fewer types were listed. "
    "Re-call FPD_list_petition_types with search= or a smaller limit=."
)

_DOCUMENT_ALIASES = {
    "items_returned": "documents_returned",
    "items_total": "documents_total",
    "note": "documents_note",
}

_TOOL_BOUNDS: Dict[str, Dict[str, Any]] = {
    "FPD_Get_petition_details": {
        "bags": (_DOCUMENT_BAG_SPEC, _SEARCH_RECORDS_SPEC),
        "note": _DETAILS_NOTE,
        "aliases": _DOCUMENT_ALIASES,
    },
    "FPD_Search_petitions_minimal": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="FPD_Search_petitions_minimal"),
        "paging": _SEARCH_PAGING,
    },
    "FPD_Search_petitions_balanced": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="FPD_Search_petitions_balanced"),
        "paging": _SEARCH_PAGING,
    },
    "FPD_Search_petitions_by_art_unit": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="FPD_Search_petitions_by_art_unit"),
        "paging": _SEARCH_PAGING,
    },
    "FPD_Search_petitions_by_application": {
        "bags": (_DOCUMENT_BAG_SPEC, _SEARCH_RECORDS_SPEC),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="FPD_Search_petitions_by_application"),
        "aliases": _DOCUMENT_ALIASES,
        "paging": _SEARCH_PAGING,
    },
    "FPD_get_petition_statistics": {
        "bags": _STATISTICS_BAGS,
        "note": _STATISTICS_NOTE,
    },
    "FPD_get_dismissal_grounds": {
        "bags": _DISMISSAL_BAGS,
        "note": _DISMISSAL_NOTE,
    },
    "FPD_list_petition_types": {
        "bags": ({"path": ["types"], "keep_fields": (), "min_items": 10, "label": "types"},),
        "note": _TYPES_NOTE,
    },
    # The caller explicitly asked for document text, so the ceiling is the
    # higher content budget and the tool's own cursor (`_window`) has already
    # bounded it; this is the backstop against a pathological payload.
    "FPD_get_document_content_with_ocr": {
        "bags": (),
        "budget": "content",
        "note": _CONTENT_NOTE,
    },
}

#: Anything not listed above (downloads, guidance, admin) gets the plain
#: response budget with the largest-free-text-field fallback, so coverage is
#: 100% without per-tool wiring.
_DEFAULT_BOUNDS: Dict[str, Any] = {"bags": ()}


# ARCH-03 (review 2026-09-28, common fix D): a local
# `_reconcile_bounds_items_total` post-processor used to rewrite
# `_bounds.items_total` to `paging.total` after the shared guard ran,
# redefining what the canonical marker means (`items_total` = "items in the
# bag the guard was handed" in PTAB and PFW; FPD alone made it mean "size of
# the full result set"). Removed: `_bounds.items_total` now means the same
# thing across all three repos again. The full result-set count was never
# lost — every paged tool already publishes it as `paging.total`, unaffected
# by this change; read that field for "how many petitions matched", and
# `_bounds.items_total` for "how many of the configured bags' items survived
# the guard".


def _bound_result(result: Any, tool_name: str) -> Any:
    """Apply the shared guard to one tool result (dict or JSON string)."""
    config = dict(_TOOL_BOUNDS.get(tool_name) or _DEFAULT_BOUNDS)
    budget = config.pop("budget", "response")
    config.setdefault("text_fallback", True)
    config["limit"] = (
        response_bounds.content_char_budget()
        if budget == "content"
        else response_bounds.response_char_budget()
    )

    if isinstance(result, dict):
        return response_bounds.bound_structured_response(result, **config)

    if isinstance(result, str) and result.lstrip().startswith("{"):
        try:
            parsed = json.loads(result)
        except ValueError:
            return result
        if not isinstance(parsed, dict):
            return result
        bounded = response_bounds.bound_structured_response(parsed, **config)
        if response_bounds.BOUNDS_KEY not in bounded:
            return result  # no-op: hand back the original string byte-for-byte
        return json.dumps(bounded, default=str)

    return result


def _guard(fn, tool_name: str):
    """Wrap a tool function so its response passes through the guard.

    The signature is preserved (both via functools.wraps' ``__wrapped__`` and
    an explicit ``__signature__``) so FastMCP derives the same input schema
    it would from the unwrapped function.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return _bound_result(await fn(*args, **kwargs), tool_name)
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return _bound_result(fn(*args, **kwargs), tool_name)

    try:
        wrapper.__signature__ = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        pass
    return wrapper


class _BoundedRegistrar:
    """Thin proxy over the FastMCP object that guards every registered tool.

    Only ``.tool(...)`` is intercepted; every other attribute (resources,
    templates, custom routes, run) passes straight through to the real object.
    Handles both the decorator form (``@mcp.tool(name=...)``) and FPD's
    imperative form (``mcp.tool(name=...)(fn)``).
    """

    def __init__(self, mcp) -> None:
        self._mcp = mcp

    def __getattr__(self, name):
        return getattr(self._mcp, name)

    def tool(self, *args, **kwargs):
        if args and callable(args[0]):  # bare @mcp.tool usage
            fn = args[0]
            name = kwargs.get("name") or getattr(fn, "__name__", "")
            return self._mcp.tool(_guard(fn, name), *args[1:], **kwargs)

        decorator = self._mcp.tool(*args, **kwargs)

        def register_guarded(fn):
            name = kwargs.get("name") or getattr(fn, "__name__", "")
            return decorator(_guard(fn, name))

        return register_guarded


def register_all(mcp, auth_provider=None) -> None:
    bounded = _BoundedRegistrar(mcp)

    # F-E6: the maintenance kill switch is wired HERE, at registration time,
    # matching the FPD_ENABLE_* idiom the admin tool and the prompts already
    # use. It previously logged CRITICAL and changed nothing, so an operator
    # who set it during an incident got a scary line and a fully live server.
    # Guidance stays registered so a caller learns why the rest is missing.
    from ..config.feature_flags import feature_flags

    if feature_flags.is_enabled("maintenance_mode"):
        guidance.register(bounded)
        return

    admin.register(bounded, auth_provider)
    petitions.register(bounded)
    statistics.register(bounded)
    documents.register(bounded)
    guidance.register(bounded)
