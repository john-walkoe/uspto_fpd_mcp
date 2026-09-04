"""Tool registration package (SD-1/SOLID-1 god-module split).

Each module defines its tools as plain (envelope-wrapped) async functions and
exposes register(mcp); register_all preserves the historical registration
order: admin -> petitions (search/details) -> documents -> guidance.

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

from . import admin, documents, guidance, petitions


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

_SEARCH_RECORDS_SPEC = {
    "path": _PETITION_RECORDS_PATH,
    "keep_fields": (),  # already field-filtered by FieldManager
    "min_items": 5,
    "label": FPDFields.PETITION_DECISION_DATA_BAG,
}

_SEARCH_NOTE_TEMPLATE = (
    "Response exceeded the client response-size limit, so fewer records were "
    "returned than requested. Re-call {tool} with a smaller limit= (and page "
    "with offset=) to retrieve the rest."
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
    },
    "FPD_Search_petitions_balanced": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="FPD_Search_petitions_balanced"),
    },
    "FPD_Search_petitions_by_art_unit": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="FPD_Search_petitions_by_art_unit"),
    },
    "FPD_Search_petitions_by_application": {
        "bags": (_DOCUMENT_BAG_SPEC, _SEARCH_RECORDS_SPEC),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="FPD_Search_petitions_by_application"),
        "aliases": _DOCUMENT_ALIASES,
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


def _reconcile_bounds_items_total(payload: Any) -> Any:
    """Make `_bounds.items_total` report the same figure as `paging.total`.

    The shared guard counts `items_total` from the bags PRESENT IN THE
    RESPONSE it was handed, which on a search page is the page, not the
    result set. Observed 2026-09-03 on
    FPD_Search_petitions_balanced(query='ruleBag:"37 CFR 1.137"', limit=50):
    `paging.total` said 53 (the real number of matching petitions) while
    `_bounds.items_total` said 50 (the page the guard was given). Two
    authoritative-looking totals disagreeing by three records is exactly the
    kind of thing a reader resolves the wrong way, and a reader told to check
    `_bounds` before saying "only N exist" would have said 50.

    Where the response carries a paging block that knows the true total, that
    figure wins and `_bounds` reports it, so the marker reads "returned N of
    total M" with M the same number `paging` gives. `items_returned` is left
    alone: it still counts the records this response actually carries, which
    is the one thing `paging.returned` cannot know after the guard sheds rows.

    The legacy `documents_total` alias is deliberately NOT re-mirrored. It
    describes the documentBag, not the petition result set, so it keeps the
    guard's own count.

    Runs on every tool result, not only guarded ones: `_bounds` can also be
    attached earlier by petitions._bound_details_response, in which case the
    guard here is a no-op and would never see the marker.
    """
    if not isinstance(payload, dict):
        return payload
    bounds = payload.get(response_bounds.BOUNDS_KEY)
    paging = payload.get("paging")
    if not isinstance(bounds, dict) or not isinstance(paging, dict):
        return payload
    total = paging.get("total")
    if isinstance(total, int) and bounds.get("items_total") != total:
        bounds["items_total"] = total
    return payload


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
        return _reconcile_bounds_items_total(
            response_bounds.bound_structured_response(result, **config)
        )

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
        return json.dumps(_reconcile_bounds_items_total(bounded), default=str)

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
    documents.register(bounded)
    guidance.register(bounded)
