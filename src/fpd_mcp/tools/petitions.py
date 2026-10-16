"""Petition search + details tools (SD-1 god-module split).

FPD_Search_petitions_minimal/balanced/by_art_unit/by_application and
FPD_Get_petition_details, plus the convenience-query-building helpers they
share. Extracted from main.py (mechanical decomposition, no behavior
change) — the minimal/balanced/by_art_unit/by_application/details tools now
route through runtime.get_fpd_service() instead of duplicating the inline
API-call + field-filter logic (Phase 6B finding #1); FPDService's methods
were reconciled to reproduce the prior inline behavior exactly (see
services/fpd_service.py docstring), so response shape/errors are unchanged.
"""

import asyncio
from typing import Annotated, Any, Dict, Optional, Union

from fastmcp.apps import AppConfig
from pydantic import Field

from ..api.field_constants import FPDFields, QueryFieldNames
from ..api.payload_compat import (
    FINAL_ONLY_CLAUSE,
    decision_type_clause,
    rewrite_legacy_query_fields,
)
from ..app_uris import SEARCH_URI
from ..config import api_constants
from ..runtime import get_fpd_service
from ..services.petition_statistics import type_code_clause
from ..shared.response_bounds import bound_structured_response
from ..shared.error_utils import (
    ValidationError,
    async_tool_error_handler,
    format_error_response,
    generate_request_id,
)
from ..util.citations import attach_citations
from ..util.deadline import (
    Deadline,
    bind_deadline,
    content_deadline_seconds,
    deadline_exceeded_response,
)
from ..validators import (
    validate_application_number,
    validate_date_range,
    validate_petition_id,
    validate_string_param,
)

# Cap on the combined Lucene query string built by _build_convenience_query,
# checked in both fpd_search_petitions_minimal and fpd_search_petitions_balanced.
_MAX_COMBINED_QUERY_LENGTH = 2000

# The USPTO FPD API signals "zero matching records" with HTTP 404 rather than
# an empty result set, so every no-results query surfaced as an error.
# Applied to the search tools only — a 404 on a specific petition_id lookup
# remains a real error.
#
# Provenance: first observed in the staging smoke test 2026-08-16;
# re-verified live 2026-08-21 and again 2026-08-30 against api.uspto.gov.
_NO_MATCH_MARKER = "No matching records found"


def _offset_out_of_range_message(offset: int) -> Optional[str]:
    """Message for a rejected `offset`, or None when it is acceptable.

    L-19: the lower bound existed; the upper bound did not.
    """
    if offset < 0:
        return "Offset must be non-negative"
    if offset > api_constants.MAX_SEARCH_OFFSET:
        return (
            f"Offset must be {api_constants.MAX_SEARCH_OFFSET} or less. "
            "Narrow the query rather than paging past that point."
        )
    return None


def _no_matches_to_empty(result: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the upstream 404-means-empty envelope into an empty result set.

    The note deliberately carries NO census of the corpus. It used to assert
    "7,473 records, all DENIED (verified live 2026-08-21)" on every empty
    result — including queries where the corpus composition was irrelevant,
    such as a lookup on a nonexistent application. That string was frozen at
    the moment it was written and was already wrong by 2026-08-30 (7,481
    DENIED, plus GRANTED and DISMISSED records that do exist). A served
    string cannot re-verify itself, so it must not make a dated factual
    claim: the durable half is the 404-to-empty mapping.
    """
    if (
        isinstance(result, dict)
        and result.get("status_code") == 404
        and _NO_MATCH_MARKER in str(result.get("error", ""))
    ):
        return {
            FPDFields.PETITION_DECISION_DATA_BAG: [],
            "count": 0,
            "note": (
                "No matching records for this query (the USPTO FPD API reports "
                "an empty result set as HTTP 404). This is a genuine zero, not "
                "an error. Note that the server cannot distinguish a filter "
                "value that is merely absent from one that is misspelled — "
                "re-run without the narrowest filter to tell them apart."
            ),
        }
    return result


# The search ceiling CLAMPS rather than rejecting, matching the sibling PFW
# server (tools/search_tools.py::_clamp_search_limit). USPTO 400s a pagination
# limit above 100, so a tool-layer 400 on limit=150 spends the caller a turn to
# learn something the server already knew. `limit_clamped` is ABSENT when the
# clamp did not fire — the same absent-on-a-no-op rule as `_bounds`/`_window`.
# A limit below MIN_SEARCH_LIMIT is still a 400: there is no honest value to
# clamp it to.
def _clamp_search_limit(limit: int):
    """(limit_applied, clamp_marker_or_None) for the MAX_SEARCH_LIMIT ceiling."""
    ceiling = api_constants.MAX_SEARCH_LIMIT
    if limit <= ceiling:
        return limit, None
    return ceiling, {
        "limit_clamped": {
            "requested": limit,
            "applied": ceiling,
            "note": (
                f"limit={limit} is above the USPTO search ceiling of {ceiling}, so it "
                f"was CLAMPED to {ceiling} rather than rejected (USPTO answers a larger "
                "page limit with HTTP 400). `paging.limit_requested` carries the same "
                "requested value; page past the ceiling with offset=."
            ),
        }
    }


def _stamp_limit_clamp(result: Dict[str, Any], clamp_marker) -> Dict[str, Any]:
    """Merge a `_clamp_search_limit` marker into a tool response.

    A no-op when the clamp did not fire, and it touches nothing in an error
    envelope beyond the marker. `paging.limit_requested` is restored to what
    the CALLER asked for: the wire layer only ever saw the clamped value, so
    the envelope would otherwise report the clamped number as the request.
    """
    if clamp_marker and isinstance(result, dict):
        result.update(clamp_marker)
        paging = result.get("paging")
        if isinstance(paging, dict):
            paging["limit_requested"] = clamp_marker["limit_clamped"]["requested"]
    return result


# Soft ceiling for petition responses. Petitions can carry 100+ documents
# whose downloadOptionBag entries dominate the payload; a 58,726-char
# response blew claude.ai's tool-result cap, which replaces the whole payload
# with a harness error the server never sees (2026-08-16). Stay under the cap
# so the model always receives usable data plus recovery guidance instead of
# a truncation error.
#
# The mechanics now live in shared/response_bounds.py (vendored byte-identical
# across the USPTO MCPs); this module supplies only the FPD-specific bag
# config and keeps the pre-existing documents_* marker keys as aliases.
_DETAILS_MIN_DOCS = 10
_DOC_SLIM_FIELDS = (
    FPDFields.DOCUMENT_IDENTIFIER,
    FPDFields.DOCUMENT_CODE,
    FPDFields.DOCUMENT_CODE_DESCRIPTION_TEXT,
    FPDFields.DOCUMENT_FILE_NAME,
    FPDFields.PAGE_COUNT,
)
_DETAILS_BAGS = (
    {
        "path": [FPDFields.PETITION_DECISION_DATA_BAG, "*", FPDFields.DOCUMENT_BAG],
        "keep_fields": _DOC_SLIM_FIELDS,
        "min_items": _DETAILS_MIN_DOCS,
        "label": FPDFields.DOCUMENT_BAG,
    },
)
_DETAILS_ALIASES = {
    "items_returned": "documents_returned",
    "items_total": "documents_total",
    "note": "documents_note",
}
_DETAILS_NOTE = (
    "documentBag entries were slimmed to essential fields to stay under the "
    "client response-size limit (full metadata would have been replaced by an "
    "unrecoverable truncation error). Every documentIdentifier is usable with "
    "FPD_get_document_download(petition_id=..., document_identifier=...); "
    "re-call FPD_Get_petition_details(petition_id=..., include_documents=false) "
    "if you only need petition fields."
)


def _bound_details_response(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep a FPD_Get_petition_details response under the response budget.

    Delegates to the shared guard: stage 1 slims every documentBag entry to
    _DOC_SLIM_FIELDS, stage 2 halves the slimmed bag until it fits (floor
    _DETAILS_MIN_DOCS). Returns the payload untouched (no `_bounds` key,
    byte-identical) when it already fits. downloadOptionBag is already gone
    by the time this runs — _strip_raw_document_urls drops it unconditionally
    before this guard sees the response, not only when slimming for size.
    """
    return bound_structured_response(
        result,
        bags=_DETAILS_BAGS,
        note=_DETAILS_NOTE,
        aliases=_DETAILS_ALIASES,
    )


#: CR-59/MCP-9 (review 2026-09-28): downloadOptionBag.downloadUrl is a raw
#: api.uspto.gov URL that 401s without the server's own USPTO_API_KEY — it
#: was never usable by a user or browser. The size guard already drops
#: downloadOptionBag from documentBag entries WHEN it needs to slim an
#: oversized response (_DOC_SLIM_FIELDS, above), which hid the bug on any
#: petition small enough to fit under budget: the raw URL sailed through
#: untouched, and the docstring told the model to "provide all document
#: download links to user" straight from it — a dead link every time.
#: Strip it unconditionally so no response path can leak a URL that needs a
#: credential the caller doesn't have; FPD_get_document_download resolves
#: its own copy of this bag from a fresh upstream call and never reads the
#: one served here.
def _strip_raw_document_urls(result: Dict[str, Any]) -> Dict[str, Any]:
    """Drop downloadOptionBag from every documentBag entry in a petition
    details response, unconditionally (not only when the size guard slims).
    """
    records = result.get(FPDFields.PETITION_DECISION_DATA_BAG)
    if not isinstance(records, list):
        return result
    for record in records:
        if not isinstance(record, dict):
            continue
        documents = record.get(FPDFields.DOCUMENT_BAG)
        if not isinstance(documents, list):
            continue
        for doc in documents:
            if isinstance(doc, dict):
                doc.pop(FPDFields.DOWNLOAD_OPTION_BAG, None)
    return result


def _paging_envelope(
    result: Dict[str, Any],
    *,
    limit_requested: int,
    offset: int = 0,
) -> Dict[str, Any]:
    """Report the limit that was ACTUALLY applied, plus a paging cursor.

    The tool layer validates the limit and api/fpd_client.py clamps it to the
    same api_constants.MAX_SEARCH_LIMIT, so the two agree by construction —
    but reporting both makes any future drift visible instead of silent.
    `returned` counts the records the search produced. If the response-size
    guard later sheds records, it rewrites this block to match what it kept
    (`returned`, `has_more`, `next_offset = offset + returned`; see
    shared/response_bounds.py::_reconcile_paging), so the cursor never points
    past the last record the caller received.
    """
    if not isinstance(result, dict):
        return result
    records = result.get(FPDFields.PETITION_DECISION_DATA_BAG)
    returned = len(records) if isinstance(records, list) else 0
    total = result.get("count")
    if not isinstance(total, int):
        total = result.get("recordTotalQuantity")
    limit_applied = max(
        api_constants.MIN_SEARCH_LIMIT,
        min(limit_requested, api_constants.MAX_SEARCH_LIMIT),
    )
    has_more = isinstance(total, int) and (offset + returned) < total
    result["paging"] = {
        "limit_requested": limit_requested,
        "limit_applied": limit_applied,
        "offset": offset,
        "returned": returned,
        "total": total if isinstance(total, int) else None,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
    }
    return result


_FINAL_ONLY_DESCRIPTION = (
    "True restricts to the final petition decisions (the pre-2026-10 corpus: "
    "all DENIED, the ones with written reasoning); False (default) searches every "
    "decision since 2001 including ePetition auto-grants."
)

FinalOnly = Annotated[bool, Field(description=_FINAL_ONLY_DESCRIPTION)]


def _apply_date_range_param(
    query_parts: list,
    convenience_params_used: dict,
    result_key: str,
    field_name: str,
    date_start: Optional[str],
    date_end: Optional[str],
) -> None:
    """Append a `field:[start TO end]` clause if either bound was provided
    and at least one resolves to something other than a wildcard. Shared by
    the petition_date_range and decision_date_range convenience parameters
    (identical shape, different field). Extracted from
    _build_convenience_query verbatim (mechanical decomposition, no
    behavior change)."""
    if date_start or date_end:
        start = validate_date_range(date_start) if date_start else "*"
        end = validate_date_range(date_end) if date_end else "*"
        if start != "*" or end != "*":
            query_parts.append(f"{field_name}:[{start} TO {end}]")
            convenience_params_used[result_key] = f"{start} TO {end}"


def _apply_minimal_params(
    query_parts: list,
    convenience_params_used: dict,
    query: str,
    applicant_name: Optional[str],
    application_number: Optional[str],
    patent_number: Optional[str],
    decision_type: Optional[str],
    deciding_office: Optional[str],
    petition_date_start: Optional[str],
    petition_date_end: Optional[str],
    decision_date_start: Optional[str],
    decision_date_end: Optional[str],
) -> None:
    """Append the minimal-tier convenience-parameter query clauses (base
    query + the 9 minimal-tier convenience parameters), in the same order as
    before. Mutates query_parts / convenience_params_used in place.
    Table-driven for the 5 simple string/number fields — same
    validate_string_param/validate_application_number calls (name,
    max_length) and same quoting per field as before (mechanical
    decomposition, no behavior change)."""
    # Include base query if provided. A clause on the outcome field's
    # pre-2026-10 name is pointed at its new name: records still show the old
    # key (api/payload_compat.py), and USPTO answers the old one with a 404.
    if query and query.strip():
        query_parts.append(f"({rewrite_legacy_query_fields(query)})")
        convenience_params_used["base_query"] = query

    # (param_name, value, validator, field_name, quoted)
    simple_param_specs = (
        ("applicant_name", applicant_name,
         lambda v: validate_string_param("applicant_name", v),
         QueryFieldNames.APPLICANT_NAME, True),
        ("application_number", application_number,
         validate_application_number,
         QueryFieldNames.APPLICATION_NUMBER, False),
        ("patent_number", patent_number,
         lambda v: validate_string_param("patent_number", v, 15),
         QueryFieldNames.PATENT_NUMBER, False),
        ("decision_type", decision_type,
         lambda v: validate_string_param("decision_type", v, 50),
         None, False),
        ("deciding_office", deciding_office,
         lambda v: validate_string_param("deciding_office", v),
         FPDFields.FINAL_DECIDING_OFFICE_NAME, True),
    )
    for param_name, value, validator, field_name, quoted in simple_param_specs:
        if not value:
            continue
        validated = validator(value)
        if not validated:
            continue
        if field_name is None:
            # decision_type: the outcome text field is analyzed upstream
            # (GRANTED also matches GRANTED-IN-PART), so a known outcome goes
            # out on the exact letter code (api/payload_compat.py).
            clause = decision_type_clause(validated)
        else:
            clause = f'{field_name}:"{validated}"' if quoted else f"{field_name}:{validated}"
        query_parts.append(clause)
        convenience_params_used[param_name] = validated

    # Date range filters
    _apply_date_range_param(
        query_parts, convenience_params_used, "petition_date_range",
        QueryFieldNames.PETITION_MAIL_DATE, petition_date_start, petition_date_end
    )
    _apply_date_range_param(
        query_parts, convenience_params_used, "decision_date_range",
        QueryFieldNames.DECISION_DATE, decision_date_start, decision_date_end
    )


def _apply_balanced_params(
    query_parts: list,
    convenience_params_used: dict,
    petition_type_code: Optional[Union[str, int]],
    art_unit: Optional[str],
    technology_center: Optional[str],
    prosecution_status: Optional[str],
    entity_status: Optional[str],
) -> None:
    """Append the 5 balanced-tier-only convenience-parameter query clauses
    (only called when allow_balanced_params is True), in the same order as
    before. Mutates query_parts / convenience_params_used in place.
    Table-driven — same validate_string_param calls (name, max_length) and
    same quoting per field as before (mechanical decomposition, no behavior
    change)."""
    # A type code is accepted as an int, a string, a comma list ('501,502,562')
    # or a list, the same parser the statistics tools use; several codes go
    # out as one OR clause. Before 2026-10-07 a comma string was sent verbatim
    # and matched nothing, although the docstring showed it.
    if petition_type_code is not None and petition_type_code != "":
        parsed = type_code_clause(petition_type_code)
        if parsed is not None:
            codes, clause = parsed
            query_parts.append(clause)
            convenience_params_used["petition_type_code"] = ",".join(codes)
    # (param_name, value, field_name, max_length, quoted)
    specs = (
        ("art_unit", art_unit, QueryFieldNames.ART_UNIT, 10, False),
        ("technology_center", technology_center, QueryFieldNames.TECHNOLOGY_CENTER, 10, False),
        ("prosecution_status", prosecution_status, QueryFieldNames.PROSECUTION_STATUS, 200, True),
        ("entity_status", entity_status, QueryFieldNames.BUSINESS_ENTITY, 50, True),
    )
    for param_name, value, field_name, max_length, quoted in specs:
        if not value:
            continue
        validated = validate_string_param(param_name, value, max_length)
        if not validated:
            continue
        clause = f'{field_name}:"{validated}"' if quoted else f"{field_name}:{validated}"
        query_parts.append(clause)
        convenience_params_used[param_name] = validated


def _reject_balanced_only_params(
    petition_type_code: Optional[Union[str, int]],
    art_unit: Optional[str],
    technology_center: Optional[str],
    prosecution_status: Optional[str],
    entity_status: Optional[str],
) -> None:
    """Raise ValidationError if any balanced-tier-only parameter was
    provided while allow_balanced_params is False. Extracted from
    _build_convenience_query verbatim (mechanical decomposition, no
    behavior change)."""
    balanced_only_params = [petition_type_code, art_unit, technology_center, prosecution_status, entity_status]
    provided_balanced_params = [p for p in balanced_only_params if p is not None]
    if provided_balanced_params:
        raise ValidationError(
            "Parameters petition_type_code, art_unit, technology_center, prosecution_status, "
            "and entity_status are only available in FPD_Search_petitions_balanced. "
            "Use FPD_Search_petitions_balanced for advanced filtering.",
            generate_request_id()
        )


def _build_convenience_query(
    query: str = "",
    # Core Identity & Party
    applicant_name: Optional[str] = None,
    application_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    # Decision Filters
    decision_type: Optional[str] = None,
    deciding_office: Optional[str] = None,
    # Date Ranges
    petition_date_start: Optional[str] = None,
    petition_date_end: Optional[str] = None,
    decision_date_start: Optional[str] = None,
    decision_date_end: Optional[str] = None,
    # Balanced tier additional parameters
    petition_type_code: Optional[Union[str, int]] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    prosecution_status: Optional[str] = None,
    entity_status: Optional[str] = None,
    # Population filter (final decisions only)
    final_only: bool = False,
    # Control which parameters are allowed
    allow_balanced_params: bool = False
) -> tuple[str, dict]:
    """Build query string from convenience parameters

    Thin orchestrator over _apply_minimal_params / _apply_balanced_params /
    _reject_balanced_only_params — tier-gating semantics
    (allow_balanced_params) and every error message are unchanged from the
    pre-decomposition implementation.

    Returns:
        tuple: (final_query_string, convenience_parameters_used)
    """
    try:
        # Build query from convenience parameters
        query_parts = []
        convenience_params_used = {}

        _apply_minimal_params(
            query_parts, convenience_params_used,
            query, applicant_name, application_number, patent_number,
            decision_type, deciding_office,
            petition_date_start, petition_date_end,
            decision_date_start, decision_date_end,
        )

        # Add balanced tier additional parameters (only if allowed)
        if allow_balanced_params:
            _apply_balanced_params(
                query_parts, convenience_params_used,
                petition_type_code, art_unit, technology_center,
                prosecution_status, entity_status,
            )
        else:
            # Check if balanced-only parameters were provided but not allowed
            _reject_balanced_only_params(
                petition_type_code, art_unit, technology_center,
                prosecution_status, entity_status,
            )

        # final_only ANDs the indicator clause in like any other filter
        if final_only:
            query_parts.append(FINAL_ONLY_CLAUSE)
            convenience_params_used["final_only"] = True

        # Validate we have at least one search criterion
        if not query_parts:
            raise ValidationError(
                "Must provide either 'query' parameter or at least one convenience parameter",
                generate_request_id()
            )

        # Combine all query parts with AND
        final_query = " AND ".join(query_parts)

        return final_query, convenience_params_used

    except ValidationError:
        # Re-raise ValidationError as-is
        raise
    except Exception as e:
        raise ValidationError(f"Query building failed: {str(e)}", generate_request_id())


@async_tool_error_handler("minimal_search")
async def fpd_search_petitions_minimal(
    query: str = "",
    limit: int = 50,
    offset: int = 0,

    # NEW: Minimal tier convenience parameters (9 total)
    # Core Identity & Party
    applicant_name: Optional[str] = None,         # e.g., "Apple Inc.", "TechCorp"
    application_number: Optional[str] = None,     # e.g., "17414168"
    patent_number: Optional[str] = None,          # e.g., "12252554"

    # Decision Filters
    decision_type: Optional[str] = None,          # "GRANTED" | "GRANTED-IN-PART" | "DENIED" | "DISMISSED"
    deciding_office: Optional[str] = None,        # e.g., "OFFICE OF PETITIONS"

    # Date Ranges
    petition_date_start: Optional[str] = None,    # e.g., "2024-01-01" (YYYY-MM-DD)
    petition_date_end: Optional[str] = None,      # e.g., "2024-12-31" (YYYY-MM-DD)
    decision_date_start: Optional[str] = None,    # e.g., "2024-01-01" (YYYY-MM-DD)
    decision_date_end: Optional[str] = None,      # e.g., "2024-12-31" (YYYY-MM-DD)

    # Population filter
    final_only: FinalOnly = False
) -> Dict[str, Any]:
    """Ultra-fast discovery search for petition decisions (default 50 rows; a limit above about 50 on dense queries is clamped by the response bound).

**NEW: Minimal tier convenience parameters (9 total) - no query syntax needed!**

Use for: High-volume petition discovery, finding petitions by applicant, decision type, or date range.
Returns: 8 essential fields - petition ID, application number, patent number, applicant name,
decision type, petition mail date, decision date, deciding office.

**CITATIONS ARE LINKS:** every result carries `cite_as`, the verified public
link as a markdown autolink, e.g. "<https://patentcenter.uspto.gov/applications/12950321>".
This tier leaves out the label (the row already carries the decision date and
application number a label would repeat) to keep rows short;
the balanced, by_art_unit, by_application and details tools carry the labelled
form. Paste it after any sentence in an answer, a table or a memo that relies on
that decision. A bare application serial or a decision date with no link is not a
citation here: the reader has to be able to click through to a public record.
The target is Patent Center for the application, or Google Patents when the
record carries a patent number; there is no public per-decision URL, and a
persistent download link from FPD_get_document_download is a credential
addressed to the person who asked, never a citation.

**Order:** newest decision first (decisionDate descending). That is USPTO's
default since its 2026-10 payload change and this server does not re-sort, so
the first row of an unfiltered or broad search is a recent decision, not the
oldest one.

**Limit above about 50 on dense queries is clamped by the response bound.** The
tier keeps its eight fields, and 100 rows no longer fit the 40,000-character
response budget on a dense query (applicant names are populated on about half the rows),
so the size guard keeps about 50 rows and says so in `_bounds`, with an honest
`paging` block. No field is trimmed from a row. Page with `offset` (feed
`paging.next_offset` back) to reach the rest.

**Two populations:** Since USPTO's 2026-10 change this server searches every petition
decision since 2001 (about 1.1 million records, mostly GRANTED, ePetition
auto-grants included). The population it served before, the final petition
decisions (all DENIED, each with written reasoning), is `finalPetitionDecisionIndicator:true`.
`final_only=True` restricts to that older
population; the default, False, searches both. Set it True to read how the Office reasoned a
refusal, leave it False to count filings or to find grants.

**Coverage:** petition decisions of every outcome in publicly available applications
and patents filed in 2001 or later, decided from the early 2000s to date, added as
USPTO issues them. There is no 2022 floor any more (that described the pre-2026-10
dataset). A zero result is a real absence only after checking the identifier (an
application serial, not a patent number) and the filing-date floor: petitions in
applications filed before 2001 are out of scope (see FPD_get_guidance
section='coverage').

**Convenience Parameters:**
- `applicant_name`: Company/party name (e.g., 'Apple Inc.'). Filters on
  firstApplicantName, which is SPARSE: many records simply do not carry it (in a
  2026-09-03 sample it was absent on 47 of 53 revival records and on 98 of 100
  examiner-dispute records). A name filter therefore reaches only the records that
  happen to have the field, so a zero or a small result is inconclusive rather
  than a finding about that party. To cover a party properly, get its application
  serials from the PFW MCP and run FPD_Search_petitions_by_application on each.
  Absent, null and empty are the same case here: the API omits a field it has no
  value for rather than returning it as null
- `application_number`: Application number (e.g., '17414168')
- `patent_number`: Patent number if granted (e.g., '12252554')
- `decision_type`: Outcome — 'GRANTED', 'GRANTED-IN-PART', 'DENIED' or 'DISMISSED' (case does not matter). Matched exactly: 'GRANTED' does not include 'GRANTED-IN-PART'. Since USPTO's 2026-10 payload change the corpus holds every petition decision back to 2001, ePetition auto-grants included, so most records are GRANTED; the final decisions (`query='finalPetitionDecisionIndicator:true'`) are mostly DENIED. The record field is decisionTypeCodeDescriptionText (USPTO's own name is now decidedPetitionTypeCodeDescriptionText; both are served on details). There is no filter-value validation for other values, so a misspelling and a genuinely empty class both return zero — check the spelling before concluding a class is absent
- `deciding_office`: Office that decided (e.g., 'OFFICE OF PETITIONS')
- `petition_date_start/end`: Filing date range (YYYY-MM-DD)
- `decision_date_start/end`: Decision date range (YYYY-MM-DD)
- `final_only`: True restricts to the final petition decisions (the pre-2026-10 corpus: all DENIED, the ones with written reasoning); False (default) searches every decision since 2001 including ePetition auto-grants. Sent as `finalPetitionDecisionIndicator:true`, ANDed with the other filters

**Examples:**
```python
# Denied petitions for company
FPD_Search_petitions_minimal(applicant_name="TechCorp Inc.", decision_type="DENIED", limit=50)

# Hybrid: keywords + convenience
FPD_Search_petitions_minimal(query="machine learning", decision_type="DENIED", limit=50)
```

**Progressive Disclosure Workflow:**
1. Use THIS TOOL for discovery with minimal params (50-100 results)
2. Present top results to user for selection
3. Use FPD_Search_petitions_balanced for detailed analysis (10-20 selected)
   - Balanced tier adds: petition_type_code, art_unit, technology_center, prosecution_status, entity_status
4. Use FPD_Get_petition_details for complete petition data

**Cross-MCP Integration:**
- {QueryFieldNames.APPLICATION_NUMBER} -> Links to Patent File Wrapper MCP
- {QueryFieldNames.PATENT_NUMBER} -> Links to PTAB MCP for post-grant challenges
- Use balanced tier to get {QueryFieldNames.ART_UNIT} for PFW cross-reference"""
    # Input validation. A limit above the ceiling is CLAMPED, not rejected —
    # see _clamp_search_limit.
    if limit < api_constants.MIN_SEARCH_LIMIT:
        raise ValidationError(f"Limit must be between {api_constants.MIN_SEARCH_LIMIT} and {api_constants.MAX_SEARCH_LIMIT}", generate_request_id())
    limit, clamp_marker = _clamp_search_limit(limit)
    offset_error = _offset_out_of_range_message(offset)
    if offset_error:
        raise ValidationError(offset_error, generate_request_id())

    # Build query from convenience parameters
    final_query, convenience_params_used = _build_convenience_query(
        query=query,
        applicant_name=applicant_name,
        application_number=application_number,
        patent_number=patent_number,
        decision_type=decision_type,
        deciding_office=deciding_office,
        petition_date_start=petition_date_start,
        petition_date_end=petition_date_end,
        decision_date_start=decision_date_start,
        decision_date_end=decision_date_end,
        final_only=final_only,
        allow_balanced_params=False  # Minimal tier only
    )

    # Additional query length validation
    if len(final_query) > _MAX_COMBINED_QUERY_LENGTH:
        raise ValidationError(f"Combined query too long (max {_MAX_COMBINED_QUERY_LENGTH} characters)", generate_request_id())

    # Search petitions (routes through FPDService — see module docstring)
    filtered_result = _no_matches_to_empty(await get_fpd_service().search_petitions_minimal(
        query=final_query,
        limit=limit,
        offset=offset
    ))

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

    _paging_envelope(filtered_result, limit_requested=limit, offset=offset)
    _stamp_limit_clamp(filtered_result, clamp_marker)

    # CITATIONS ARE LINKS: every petition row leaves here with a `cite_as`
    # link to the public record it concerns, and the envelope says what to do
    # with it (util/citations.py). This is the 100-row tier, so the link is
    # the compact autolink: a labelled one put 100 rows past the response
    # budget (util/citations.py, THE COMPACT FORM).
    attach_citations(filtered_result, compact=True)

    # Add query metadata
    filtered_result["query_info"] = {
        "final_query": final_query,
        "convenience_parameters_used": convenience_params_used,
        "tier": "minimal",
        "available_parameters": [
            "applicant_name", "application_number", "patent_number",
            "decision_type", "deciding_office",
            "petition_date_start", "petition_date_end",
            "decision_date_start", "decision_date_end", "final_only"
        ],
        "final_only": final_only
    }

    # Add usage guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Discovery -> User Selection -> Balanced Analysis -> Cross-MCP Integration",
        "parameter_guidance": {
            "current_tier": "minimal (9 convenience parameters available)",
            "next_tier": "Use FPD_Search_petitions_balanced for 5 additional parameters: petition_type_code, art_unit, technology_center, prosecution_status, entity_status",
            "progressive_disclosure": "Start here for discovery, advance to balanced for analysis"
        },
        "next_steps": [
            "Present top results to user for selection",
            "Use FPD_Search_petitions_balanced for detailed analysis of selected petitions",
            "Use FPD_Search_petitions_by_application to get all petitions for specific application",
            "Cross-reference with PFW using applicationNumberText for prosecution history",
            "Cross-reference with PTAB using patentNumber for post-grant challenges"
        ],
        "classification": {
            "axis": (
                "Classify a petition by decisionPetitionTypeCodeDescriptionText and "
                "ruleBag, which say what was ASKED FOR, before reading "
                "decisionTypeCodeDescriptionText, which says only whether that "
                "request was granted."
            ),
            "denial_is_not_a_signal": (
                "DENIED is rare across all decisions and the ordinary outcome only "
                "among final decisions (finalPetitionDecisionIndicator true); most "
                "make-special and PPH petitions are GRANTED. Compare a denial against "
                "FPD_get_petition_statistics for the same petition_type_code. A denial carries NO quality signal on its own. Compare a "
                "denial only against the same petition type, never against the "
                "corpus as a whole, and read the decision document before "
                "characterizing it."
            )
        },
        "red_flags": {
            "revival_petitions": (
                "Petition types 501, 502, 562 (FPD_list_petition_types(search='revival') "
                "lists the class). Not ruleBag: it is populated only on the final "
                "decisions, so a ruleBag clause misses almost every revival"
            ),
            "examiner_disputes": (
                "Petition types 504 (Office of Petitions) and the technology-center "
                "codes 609, 610, 611, 612, 615, 617 (premature final, restriction, "
                "refusal to enter an amendment); report 274 (national stage) "
                "separately after reading it. Not 515, "
                "which is supervisory review of NON-examining matters (fees, filing "
                "formalities)"
            ),
            "denied_petitions": (
                "Not a red flag by itself. See llm_guidance.classification: the "
                "petition type and ruleBag carry the meaning, the decision value "
                "does not."
            )
        }
    }

    return filtered_result


@async_tool_error_handler("balanced_search")
async def fpd_search_petitions_balanced(
    query: str = "",
    limit: int = 10,
    offset: int = 0,

    # All 9 minimal tier parameters
    applicant_name: Optional[str] = None,
    application_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    decision_type: Optional[str] = None,
    deciding_office: Optional[str] = None,
    petition_date_start: Optional[str] = None,
    petition_date_end: Optional[str] = None,
    decision_date_start: Optional[str] = None,
    decision_date_end: Optional[str] = None,

    # NEW: Balanced tier additional parameters (5 more)
    # Petition Classification
    petition_type_code: Optional[Union[str, int]] = None,  # e.g., "502", 502, or "501,502,562" (several codes, ORed)
    art_unit: Optional[str] = None,               # e.g., "2128", "3643"
    technology_center: Optional[str] = None,      # e.g., "3600", "1600" (four digits, as stored)

    # Status Filters
    prosecution_status: Optional[str] = None,     # e.g., "During examination", "Patented", "Abandoned"
    entity_status: Optional[str] = None,          # e.g., "Small", "Micro", "Regular Undiscounted"

    # Population filter
    final_only: FinalOnly = False
) -> Dict[str, Any]:
    """Balanced search for Final Petition Decisions with comprehensive fields (10-20 results).
Petitions, petition decisions, granted or dismissed, revival, unintentional delay, withdrawal of a holding of abandonment, supervisory review, waiver of a rule, PTA correction, 37 CFR 1.137 1.181 1.183.

**Balanced tier convenience parameters (14 total) - adds 5 advanced filters to minimal tier.**

Use for: Detailed petition analysis after minimal search, cross-referencing with PFW/PTAB data,
analyzing petition types and legal context.
Returns: 18 key fields including petition type, art unit, technology center, prosecution status,
legal issues, CFR rules cited, statutes cited, entity status, and invention title.

**CITATIONS ARE LINKS:** every result carries `cite_as`, a ready-made markdown
link labelled with the decision date and the application, e.g.
"[Petition decision 2019-06-11, application 12/950,321](https://patentcenter.uspto.gov/applications/12950321)".
Paste it after any sentence in an answer, a table or a memo that relies on that
decision. A bare application serial or a decision date with no link is not a
citation here: the reader has to be able to click through to a public record.
The target is Patent Center for the application, or Google Patents when the
record carries a patent number; there is no public per-decision URL, and a
persistent download link from FPD_get_document_download is a credential
addressed to the person who asked, never a citation.

**Order:** newest decision first (decisionDate descending). That is USPTO's
default since its 2026-10 payload change and this server does not re-sort, so
the first row of an unfiltered or broad search is a recent decision, not the
oldest one.

**Two populations:** Since USPTO's 2026-10 change this server searches every petition
decision since 2001 (about 1.1 million records, mostly GRANTED, ePetition
auto-grants included). The population it served before, the final petition
decisions (all DENIED, each with written reasoning), is `finalPetitionDecisionIndicator:true`.
`final_only=True` restricts to that older
population; the default, False, searches both. Set it True to read how the Office reasoned a
refusal, leave it False to count filings or to find grants.

**Coverage:** petition decisions of every outcome in publicly available applications
and patents filed in 2001 or later, decided from the early 2000s to date, added as
USPTO issues them. There is no 2022 floor any more (that described the pre-2026-10
dataset). A zero result is a real absence only after checking the identifier (an
application serial, not a patent number) and the filing-date floor: petitions in
applications filed before 2001 are out of scope (see FPD_get_guidance
section='coverage').

**All Minimal Parameters (9) - same as FPD_Search_petitions_minimal:**
- `applicant_name` (filters on the SPARSE firstApplicantName field: many records
  do not carry it, so a zero result is inconclusive rather than a finding about
  that party. Absent, null and empty are the same case, and cross-referencing
  application serials from PFW is the reliable route to a party's petitions),
  `application_number`, `patent_number`
- `decision_type`, `deciding_office`
- `petition_date_start/end`, `decision_date_start/end`
- `final_only`: True restricts to the final petition decisions (the pre-2026-10 corpus: all DENIED, the ones with written reasoning); False (default) searches every decision since 2001 including ePetition auto-grants. Sent as `finalPetitionDecisionIndicator:true`, ANDed with the other filters

**Additional Balanced Parameters (5):**
- `petition_type_code`: Petition type: one code or a comma list ('501,502,562'),
  sent as one OR clause. See the class table below. It is NOT the CFR rule number:
  '181' and '182' are not type codes at all
- `art_unit`: Art unit number (e.g., '2128', '3643') - enables PFW cross-reference
- `technology_center`: Tech center, four digits as stored (e.g., '3600', '1600').
  A two-digit prefix such as '21' matches nothing — the value is not expanded
- `prosecution_status`: Status (e.g., 'During examination', 'Patented', 'Abandoned',
  'After payment of issue fee'). The value is the bare 'Patented', not 'Patented Case'
- `entity_status`: Entity type — 'Small', 'Micro' or 'Regular Undiscounted'.
  There is no 'Large' and no bare 'Undiscounted'

**Petition type codes, by class (names are USPTO's, typos included; the full live
table with counts is FPD_list_petition_types, which also turns 'revival' or 'PPH'
into codes):**
| class | codes |
|---|---|
| Revival, unintentional delay | 502 (OPAP/TC, no additional information required), 562 (additional information required), 510 (ODM), 272 (international), and related codes; FPD_list_petition_types(search='revival') lists all twelve |
| Revival, unavoidable delay | 501 (and 271 in national stage) |
| Examiner disputes (petitions against an examiner's action) | 504 (supervisory authority re patent examining), 609 (final restriction, 37 CFR 1.144), 610 (other 1.181), 611 (prematureness of final rejection), 612 and 617 (refusal to enter an amendment), 615 (affidavit sufficiency). Not 515 (supervisory review of NON-examining matters), not 613/614 (holdings of abandonment). Report 274 (national stage) apart |
| Holding of abandonment | 525, 529 (pre-exam), 613, 614 |
| Rule 1.182 / 1.183 | 519, 520 (1.182 matters); 503 (suspension or waiver of a rule, 1.183) |
| Acceleration (mostly granted) | 643 (Track One), 652 (PPH make-special), 601 (make special on age) |
| PTA correction | 550 (before issue), 551 (after issue) |

**THIS TABLE IS NOT EXHAUSTIVE.** USPTO publishes no vocabulary this server can
enumerate beyond the live list, so a code absent here is not a code that does not
exist: read FPD_list_petition_types before treating a class as complete.

**551 IS NOT REVIVAL.** It is the PTA-correction code, a large unrelated class, so a
search that means "revival" and sends 551 silently returns PTA corrections.

**Select a class by type code, not by `ruleBag`.** Since USPTO's 2026-10 change
`ruleBag` and `statuteBag` are populated only on the final decisions (and never on
DISMISSED records), so a `ruleBag:"37 CFR 1.137"` clause reaches only the few dozen
final denials and misses the rest of the revival class. On the whole corpus, name
the class by its type codes: FPD_list_petition_types(search='revival') returns them
(501, 502, 562 and the related abandonment codes), and `petition_type_code` takes
several at once. A `ruleBag` clause is still useful together with `final_only=True`,
to find written refusals that cite a rule across several type codes.

**Examples:**
```python
# Revival petitions (37 CFR 1.137, unintentional delay) that were denied
FPD_Search_petitions_balanced(petition_type_code="502", decision_type="DENIED", limit=20)

# Every revival: the class by its type codes (codes from FPD_list_petition_types)
FPD_Search_petitions_balanced(petition_type_code="501,502,562", limit=20)

# Written refusals that cite 37 CFR 1.137, whatever their type code
FPD_Search_petitions_balanced(query='ruleBag:"37 CFR 1.137"', final_only=True, limit=20)

# Complex combination for quality analysis
FPD_Search_petitions_balanced(
    art_unit="3643", petition_type_code="501",
    decision_type="DENIED", prosecution_status="During examination", limit=20
)
```

**Progressive Disclosure Workflow:**
1. Discovery: FPD_Search_petitions_minimal(decision_type='DENIED', limit=100)
2. User selects interesting petitions
3. Analysis: FPD_Search_petitions_balanced with advanced filters (art_unit, petition_type_code)
4. Cross-reference: Use art_unit with PFW, use patentNumber with PTAB

**Cross-MCP Integration:**
- applicationNumberText -> PFW_search_applications_minimal with fields parameter for targeted data
- patentNumber -> PTAB_search_trials_minimal(patent_number=X)
- groupArtUnitNumber -> PFW_search_applications_minimal(art_unit=X, fields=[...])
- firstApplicantName -> Match parties across PFW/PTAB MCPs"""
    # Input validation. The balanced ceiling is deliberately lower than the
    # minimal tier's (18 fields per record vs 8) — see
    # api_constants.MAX_BALANCED_SEARCH_LIMIT, which replaced the unexplained
    # hard-coded 50 here.
    if limit < api_constants.MIN_SEARCH_LIMIT or limit > api_constants.MAX_BALANCED_SEARCH_LIMIT:
        return format_error_response(
            f"Limit must be between {api_constants.MIN_SEARCH_LIMIT} and "
            f"{api_constants.MAX_BALANCED_SEARCH_LIMIT}",
            400,
            generate_request_id(),
        )
    offset_error = _offset_out_of_range_message(offset)
    if offset_error:
        return format_error_response(offset_error, 400, generate_request_id())

    # Build query from convenience parameters
    final_query, convenience_params_used = _build_convenience_query(
        query=query,
        applicant_name=applicant_name,
        application_number=application_number,
        patent_number=patent_number,
        decision_type=decision_type,
        deciding_office=deciding_office,
        petition_date_start=petition_date_start,
        petition_date_end=petition_date_end,
        decision_date_start=decision_date_start,
        decision_date_end=decision_date_end,
        petition_type_code=petition_type_code,
        art_unit=art_unit,
        technology_center=technology_center,
        prosecution_status=prosecution_status,
        entity_status=entity_status,
        final_only=final_only,
        allow_balanced_params=True  # Balanced tier allows all
    )

    # Additional query length validation
    if len(final_query) > _MAX_COMBINED_QUERY_LENGTH:
        return format_error_response(f"Combined query too long (max {_MAX_COMBINED_QUERY_LENGTH} characters)", 400, generate_request_id())

    # Search petitions (routes through FPDService — see module docstring)
    filtered_result = _no_matches_to_empty(await get_fpd_service().search_petitions_balanced(
        query=final_query,
        limit=limit,
        offset=offset
    ))

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

    _paging_envelope(filtered_result, limit_requested=limit, offset=offset)

    # CITATIONS ARE LINKS: every petition row leaves here with a `cite_as`
    # markdown link to the public record it concerns, and the envelope says
    # what to do with it (util/citations.py).
    attach_citations(filtered_result)

    # Add query metadata
    filtered_result["query_info"] = {
        "final_query": final_query,
        "convenience_parameters_used": convenience_params_used,
        "tier": "balanced",
        "available_parameters": [
            "applicant_name", "application_number", "patent_number",
            "decision_type", "deciding_office",
            "petition_date_start", "petition_date_end",
            "decision_date_start", "decision_date_end",
            "petition_type_code", "art_unit", "technology_center",
            "prosecution_status", "entity_status", "final_only"
        ],
        "final_only": final_only
    }

    # Add enhanced usage guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Balanced Analysis -> Cross-MCP Integration -> Document Retrieval",
        "cross_mcp_workflows": {
            "pfw_prosecution": "PFW_search_applications_minimal with fields parameter for examiner/status context",
            "ptab_challenges": "PTAB_search_trials_minimal(patent_number=X) if patentNumber present",
            "art_unit_analysis": "FPD_Search_petitions_by_art_unit(art_unit=X) for pattern analysis"
        },
        "classification": {
            "axis": (
                "decisionPetitionTypeCodeDescriptionText and ruleBag are the "
                "classification axis: they say what relief was requested. "
                "decisionTypeCodeDescriptionText says only whether it was granted."
            ),
            "denial_is_not_a_signal": (
                "DENIED is rare across all decisions and the ordinary outcome only "
                "among final decisions (finalPetitionDecisionIndicator true); most "
                "make-special and PPH petitions are GRANTED. Compare a denial against "
                "FPD_get_petition_statistics for the same petition_type_code. A denial carries NO quality signal on its own; "
                "compare it only within its own petition type and read the decision "
                "document before characterizing it."
            )
        },
        "red_flags": {
            "revival_37cfr1137": "Application abandoned - revival petition filed",
            "dispute_37cfr1181": "Examiner conflict - supervisory review petition",
            "denied_petition": (
                "Not a red flag by itself. See llm_guidance.classification: the "
                "petition type and ruleBag carry the meaning, the decision value "
                "does not."
            )
        },
        "next_steps": [
            "FPD_Get_petition_details for full details + documents",
            "Cross-reference applicationNumberText with PFW",
            "Cross-reference patentNumber with PTAB",
            "Use FPD_Search_petitions_by_art_unit for examiner patterns"
        ]
    }

    return filtered_result


@async_tool_error_handler("art_unit_search")
async def fpd_search_petitions_by_art_unit(
    art_unit: str,
    date_range: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    final_only: FinalOnly = False
) -> Dict[str, Any]:
    """Search petitions by art unit number for examiner/art unit quality analysis.
Art unit, technology center, examiner behavior, group, unit number, quality analysis, petition patterns by art unit.

**Use for:** Art unit quality assessment, systematic petition patterns, examiner behavior analysis.
Returns balanced field set for cross-referencing with PFW examiner data and PTAB challenge rates.

**CITATIONS ARE LINKS:** every result carries `cite_as`, a ready-made markdown
link labelled with the decision date and the application, e.g.
"[Petition decision 2019-06-11, application 12/950,321](https://patentcenter.uspto.gov/applications/12950321)".
Paste it after any sentence in an answer, a table or a memo that relies on that
decision. A bare application serial or a decision date with no link is not a
citation here: the reader has to be able to click through to a public record.
The target is Patent Center for the application, or Google Patents when the
record carries a patent number; there is no public per-decision URL, and a
persistent download link from FPD_get_document_download is a credential
addressed to the person who asked, never a citation.

**Order:** newest decision first (decisionDate descending). That is USPTO's
default since its 2026-10 payload change and this server does not re-sort, so
the first row of an unfiltered or broad search is a recent decision, not the
oldest one.

**Two populations:** Since USPTO's 2026-10 change this server searches every petition
decision since 2001 (about 1.1 million records, mostly GRANTED, ePetition
auto-grants included). The population it served before, the final petition
decisions (all DENIED, each with written reasoning), is `finalPetitionDecisionIndicator:true`.
`final_only=True` restricts to that older
population; the default, False, searches both. Set it True to read how the Office reasoned a
refusal, leave it False to count filings or to find grants.

**Coverage:** petition decisions of every outcome in publicly available applications
and patents filed in 2001 or later, decided from the early 2000s to date, added as
USPTO issues them. There is no 2022 floor any more (that described the pre-2026-10
dataset). A zero result is a real absence only after checking the identifier (an
application serial, not a patent number) and the filing-date floor: petitions in
applications filed before 2001 are out of scope (see FPD_get_guidance
section='coverage').

**Example:**
- FPD_Search_petitions_by_art_unit(art_unit="2128", limit=50)
- FPD_Search_petitions_by_art_unit(art_unit="2128", date_range="2020-01-01:2024-12-31")
- Second page: FPD_Search_petitions_by_art_unit(art_unit="2128", limit=50, offset=50)

**Analysis patterns:**
- Petition volume alone says little: most decisions are routine requests granted on
  filing (Track One, PPH and make-special, PTA corrections, attorney withdrawal).
  Count by petition type (FPD_get_petition_statistics(art_unit=...) does it in one call)
- Revival types (501, 502, 562 and related codes) → abandonments to look into
- Examiner disputes (types 504, 609, 610, 611, 612, 615, 617) → read the decisions
- Denied petitions → nothing on their own. DENIED is rare across all decisions and
  the ordinary outcome only among final decisions; most make-special and PPH
  petitions are GRANTED. Group by petition type (decisionPetitionTypeCodeDescriptionText) first,
  then read outcomes within a single type
- There is no threshold at which an art unit's petition rate becomes an outlier.
  Compute the same rate for two or three comparable art units in the same
  technology center and date window in the SAME session, or report raw counts and
  say no baseline was established

**Cross-MCP integration:**
- applicationNumberText → PFW_search_applications_minimal with fields parameter for examiner names
- Group petitions by examiner to identify individual patterns
- patentNumber → PTAB MCP to correlate petition history with challenge success

**Parameters:**
- art_unit: Art unit number, four digits as stored (e.g., "2128", "3643")
- date_range: Optional petitionMailDate range (format: "YYYY-MM-DD:YYYY-MM-DD").
  Filters on the date the petition was mailed, inclusive of both bounds
- limit: Maximum results (default 50, max 100 — a larger value is clamped, not
  rejected, and the response then carries `limit_clamped`). Rows that do
  not fit the response bound are cut and `_bounds` says so; page with offset
- offset: Starting position for paging (default 0). The response's `paging`
  block reports returned/total/has_more/next_offset — feed next_offset back
  as offset to retrieve the remainder.
- final_only: True restricts to the final petition decisions (the pre-2026-10 corpus: all DENIED, the ones with written reasoning); False (default) searches every decision since 2001 including ePetition auto-grants. Sent as `finalPetitionDecisionIndicator:true`, ANDed with the other filters"""
    # Input validation
    if not art_unit or len(art_unit.strip()) == 0:
        return format_error_response("Art unit cannot be empty", 400, generate_request_id())
    # M4: route through the same validator the minimal/balanced tools
    # use for this logical field, instead of a bare empty-check.
    try:
        art_unit = validate_string_param("art_unit", art_unit, 10)
    except ValidationError as e:
        return format_error_response(str(e), 400, e.request_id)
    if limit < api_constants.MIN_SEARCH_LIMIT:
        return format_error_response(f"Limit must be between {api_constants.MIN_SEARCH_LIMIT} and {api_constants.MAX_SEARCH_LIMIT}", 400, generate_request_id())
    limit, clamp_marker = _clamp_search_limit(limit)
    offset_error = _offset_out_of_range_message(offset)
    if offset_error:
        return format_error_response(offset_error, 400, generate_request_id())
    if date_range:
        # Basic date range format validation
        parts = date_range.split(":")
        if len(parts) != 2:
            return format_error_response(
                "Date range must be in format YYYY-MM-DD:YYYY-MM-DD",
                400,
                generate_request_id(),
            )

    # Search via FPDService (routes through the same api_client.search_by_art_unit
    # + balanced-field filter as before — see module docstring)
    filtered_result = _no_matches_to_empty(await get_fpd_service().search_by_art_unit(
        art_unit=art_unit,
        date_range=date_range,
        limit=limit,
        offset=offset,
        final_only=final_only,
    ))

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

    _paging_envelope(filtered_result, limit_requested=limit, offset=offset)
    _stamp_limit_clamp(filtered_result, clamp_marker)

    # CITATIONS ARE LINKS: every petition row leaves here with a `cite_as`
    # markdown link to the public record it concerns, and the envelope says
    # what to do with it (util/citations.py).
    attach_citations(filtered_result)

    # Add art unit analysis guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Art Unit Discovery -> Examiner Mapping -> PTAB Correlation",
        "analysis_patterns": {
            "volume": (
                "Petition volume alone is not a signal: most decisions are routine "
                "requests granted on filing. Count by petition type first "
                "(FPD_get_petition_statistics(art_unit=...))"
            ),
            "revival_clustering": "Revival types (501, 502, 562 and related codes) cluster → look at docketing",
            "examiner_disputes": "Types 504, 609, 610, 611, 612, 615, 617 (not 613/614, holdings of abandonment) (examiner-action petitions) → read the decisions",
            "ptab_correlation": "Compare PTAB outcomes only against contested petition types, never raw counts"
        },
        "classification": {
            "axis": (
                "Group this art unit's petitions by "
                "decisionPetitionTypeCodeDescriptionText and ruleBag before reading "
                "any outcome. Those fields say what was requested; "
                "decisionTypeCodeDescriptionText says only whether it was granted."
            ),
            "denial_is_not_a_signal": (
                "DENIED is rare across all decisions and the ordinary outcome only "
                "among final decisions (finalPetitionDecisionIndicator true); most "
                "make-special and PPH petitions are GRANTED. Compare a denial against "
                "FPD_get_petition_statistics for the same petition_type_code. A denial carries NO quality signal on its own, "
                "so an art unit whose petitions are all DENIED has shown nothing "
                "about its examination quality."
            ),
            "no_rate_threshold": (
                "There is no threshold at which a petition rate marks an art unit as "
                "an outlier. Establish a baseline in the same session by running the "
                "same calculation over two or three comparable art units in the same "
                "technology center and date window, or report the raw counts and say "
                "no baseline was established. Numerator and denominator must cover "
                "the same filing and decision-date population."
            )
        },
        "next_steps": [
            "Use PFW_search_applications_minimal with fields parameter for examiner mapping",
            "Group petitions by examiner to identify individual patterns",
            "Group by petition type and ruleBag, then read outcomes within one type",
            "Cross-reference patentNumbers with PTAB for challenge correlation"
        ],
        "red_flags": {
            "high_denial_rate": (
                "Not a red flag. See llm_guidance.classification: denial rates in "
                "this corpus are dominated by petition classes that are refused "
                "routinely."
            ),
            "multiple_examiners": "Art unit-wide problem",
            "temporal_clustering": "Process breakdown in specific periods"
        }
    }

    return filtered_result


@async_tool_error_handler("application_search")
async def fpd_search_petitions_by_application(
    application_number: str,
    include_documents: bool = False,
    limit: int = 100,
    offset: int = 0,
    final_only: FinalOnly = False
) -> Dict[str, Any]:
    """Get all petition decisions for a specific application number.
Petition history for one application or patent, did this case file a petition, by serial number, prosecution timeline cross-reference.

**Use for:** Complete petition history, red flag identification, cross-referencing with PFW prosecution timeline.

**CITATIONS ARE LINKS:** every result carries `cite_as`, a ready-made markdown
link labelled with the decision date and the application, e.g.
"[Petition decision 2019-06-11, application 12/950,321](https://patentcenter.uspto.gov/applications/12950321)".
Paste it after any sentence in an answer, a table or a memo that relies on that
decision. A bare application serial or a decision date with no link is not a
citation here: the reader has to be able to click through to a public record.
The target is Patent Center for the application, or Google Patents when the
record carries a patent number; there is no public per-decision URL, and a
persistent download link from FPD_get_document_download is a credential
addressed to the person who asked, never a citation.

**Order:** newest decision first (decisionDate descending). That is USPTO's
default since its 2026-10 payload change and this server does not re-sort, so
the first row of an unfiltered or broad search is a recent decision, not the
oldest one.

**Two populations:** Since USPTO's 2026-10 change this server searches every petition
decision since 2001 (about 1.1 million records, mostly GRANTED, ePetition
auto-grants included). The population it served before, the final petition
decisions (all DENIED, each with written reasoning), is `finalPetitionDecisionIndicator:true`.
`final_only=True` restricts to that older
population; the default, False, searches both. Set it True to read how the Office reasoned a
refusal, leave it False to count filings or to find grants.

**Coverage:** petition decisions of every outcome in publicly available applications
and patents filed in 2001 or later, decided from the early 2000s to date, added as
USPTO issues them. There is no 2022 floor any more (that described the pre-2026-10
dataset). A zero result is a real absence only after checking the identifier (an
application serial, not a patent number) and the filing-date floor: petitions in
applications filed before 2001 are out of scope (see FPD_get_guidance
section='coverage').

**Examples:**
- Basic petition check: FPD_Search_petitions_by_application(application_number="17414168")
- With documents: FPD_Search_petitions_by_application(application_number="17414168", include_documents=True)

**Reading the record:**
- A petition count is not a red flag: most petitions are routine requests granted on
  filing (Track One, PPH, make-special, PTA corrections, attorney withdrawal)
- Revival types (501, 502, 562 and related codes) → the application was abandoned
- Examiner disputes (types 504, 609, 610, 611, 612, 615, 617) → read the decision
- Denied petitions → nothing on their own. DENIED is the ordinary outcome only
  among final decisions; across all decisions most make-special and PPH petitions
  are GRANTED, so compare a denial against FPD_get_petition_statistics for the same
  petition_type_code

**Cross-MCP integration:**
1. Use PFW_search_applications_minimal with fields parameter for prosecution context
2. Compare petition dates with prosecution timeline: PFW_get_oa_rejections for the
   structured rejection map, PFW_get_oa_text for the examiner's actual words - one
   call each, no document bag and no OCR. Fall back to
   PFW_get_application_documents + PFW_get_document_content_with_ocr only for
   non-OA papers, office actions mailed before 2007-07-27, or a PDF
3. Identify if petitions correlate with examiner changes or specific prosecution events
4. If patented, check PTAB for post-grant challenges

**Parameters:**
- application_number: USPTO application number (e.g., "17414168"). The printed
  form "17/414,168" also works (slashes, commas and spaces are stripped);
  letters are rejected, so "US17/414,168" returns a 400.
  This is the APPLICATION serial, not a patent number. Patent numbers passed
  10,000,000 in mid-2018, so the two namespaces now collide at 8 digits, and
  this server does not resolve between them: an 8-digit granted patent number
  passed here returns an empty result that reads as "no petitions", which is
  wrong rather than empty. Map a patent number to its application first with
  the PFW MCP, PFW_search_applications_minimal(query='patentNumber:<n>')
- include_documents: Include documentBag on every returned petition (default
  False here, whereas FPD_Get_petition_details defaults it True). Since USPTO's
  2026-10 payload change each petition record carries its own documentBag (the
  decision and any papers filed or issued with it), labelled
  `document_metadata_source: "petition_record"`, at no extra USPTO call. A
  record that comes back with no bag of its own gets the APPLICATION'S FILE
  WRAPPER instead (one extra USPTO call per page), marked on that record with
  `document_bag_source: "application_file_wrapper"`: that is the whole
  prosecution history, not the petition's papers, so filter it before
  describing it as one petition's documents
- limit: Maximum petition records to return (default 100, max 100 — a larger
  value is clamped, not rejected, and the response then carries `limit_clamped`). Rows that do
  not fit the response bound are cut and `_bounds` says so; page with offset
- offset: Starting position for paging (default 0). The response's `paging`
  block reports returned/total/has_more/next_offset — feed next_offset back
  as offset to retrieve the remainder.
- final_only: True restricts to the final petition decisions (the pre-2026-10 corpus: all DENIED, the ones with written reasoning); False (default) searches every decision since 2001 including ePetition auto-grants. Sent as `finalPetitionDecisionIndicator:true`, ANDed with the other filters"""
    # Input validation
    if not application_number or len(application_number.strip()) == 0:
        return format_error_response("Application number cannot be empty", 400, generate_request_id())
    if limit < api_constants.MIN_SEARCH_LIMIT:
        return format_error_response(
            f"Limit must be between {api_constants.MIN_SEARCH_LIMIT} and "
            f"{api_constants.MAX_SEARCH_LIMIT}",
            400,
            generate_request_id(),
        )
    limit, clamp_marker = _clamp_search_limit(limit)
    offset_error = _offset_out_of_range_message(offset)
    if offset_error:
        return format_error_response(offset_error, 400, generate_request_id())

    # M4: route through the same validator the minimal/balanced tools use
    # for this logical field (digits-only, 6-10 chars) instead of a bare
    # empty-check + manual strip.
    try:
        clean_app_num = validate_application_number(application_number)
    except ValidationError as e:
        return format_error_response(str(e), 400, e.request_id)

    # Search via FPDService (routes through the same api_client.search_by_application
    # + conditional balanced-field filter as before — see module docstring)
    filtered_result = _no_matches_to_empty(await get_fpd_service().search_by_application(
        application_number=clean_app_num,
        include_documents=include_documents,
        limit=limit,
        offset=offset,
        final_only=final_only,
    ))

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

    _paging_envelope(filtered_result, limit_requested=limit, offset=offset)
    _stamp_limit_clamp(filtered_result, clamp_marker)

    # CITATIONS ARE LINKS: every petition row leaves here with a `cite_as`
    # markdown link to the public record it concerns, and the envelope says
    # what to do with it (util/citations.py).
    attach_citations(filtered_result)

    # An application with more petitions than one page: the documentBag path
    # in particular is large, so make the remainder explicitly reachable.
    if include_documents:
        # CR-59/MCP-9 (review 2026-09-28): the same raw, key-requiring
        # downloadUrl FPD_Get_petition_details now strips rides in on every
        # grafted documentBag here too; strip it before the size guard.
        filtered_result = _strip_raw_document_urls(filtered_result)
        filtered_result = _bound_details_response(filtered_result)

    # Add application-specific guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Application Petition Check -> Timeline Correlation -> Cross-MCP Analysis",
        "interpretation": {
            "no_petitions": {
                "meaning": (
                    "No petition decision of any outcome on this application. The "
                    "dataset covers applications filed 2001 or later and every "
                    "disposition decided from the early 2000s on, so for an in-scope "
                    "application a zero is a real result (a decision from the last few "
                    "days may not be loaded yet)."
                ),
                "caveat": (
                    "Check the identifier first: an 8-digit patent number passed as "
                    "application_number returns zero and is wrong, not empty. An "
                    "application filed before 2001 is out of scope, so zero says "
                    "nothing about it. With final_only=True a zero covers final "
                    "decisions only."
                )
            },
            "petitions_found": {
                "meaning": (
                    "Read each row's petition type (decisionPetitionTypeCodeDescriptionText) "
                    "before its outcome. Many petitions are routine requests granted on "
                    "filing (ePetition grants, make-special and PPH requests, PTA "
                    "corrections), so the count of petitions is not by itself a sign of "
                    "a troubled prosecution."
                ),
                "action": (
                    "Separate routine grants from contested matters (revival, "
                    "supervisory review, rule-1.182 and rule-1.183 relief, denials and "
                    "dismissals), then use PFW to correlate the contested ones with the "
                    "prosecution timeline."
                )
            }
        },
        "cross_mcp_workflow": {
            "step_1": f"Use PFW_search_applications_minimal(query='applicationNumberText:{clean_app_num}', fields=[...]) for prosecution context",
            "step_2": "Compare petition dates with office action dates, RCE filings, examiner changes — use PFW_get_oa_rejections (structured rejection map) then PFW_get_oa_text (examiner's words, one call, no document bag or OCR); the document-bag + OCR path is the fallback for office actions mailed before 2007-07-27, non-OA papers, or an actual PDF",
            "step_3": "Identify prosecution events that triggered petitions",
            "step_4": "If patented, use PTAB_search_trials_minimal to check PTAB challenges"
        },
        "classification": {
            "axis": (
                "decisionPetitionTypeCodeDescriptionText and ruleBag are the "
                "classification axis: they say what relief was requested. "
                "decisionTypeCodeDescriptionText says only whether it was granted."
            ),
            "denial_is_not_a_signal": (
                "DENIED is rare across all decisions and the ordinary outcome only "
                "among final decisions (finalPetitionDecisionIndicator true); most "
                "make-special and PPH petitions are GRANTED. Compare a denial against "
                "FPD_get_petition_statistics for the same petition_type_code. A denial on this application carries NO quality "
                "signal on its own; read the petition type, the ruleBag and the "
                "decision document before characterizing it."
            )
        },
        "petition_pattern_analysis": {
            "revival_only": "Application was abandoned and revived - check PFW for abandonment reason",
            "examiner_disputes": "Types 504, 609, 610, 611, 612, 615, 617 (not 613/614, holdings of abandonment) are petitions against an examiner's action; read them before characterizing the prosecution",
            "restriction_petitions": "Type 609 is review of a final restriction requirement (37 CFR 1.144): a claim-scope dispute",
            "denied_petitions": (
                "Not a pattern by itself. See llm_guidance.classification: the "
                "petition type and ruleBag carry the meaning, the decision value "
                "does not."
            )
        },
        "next_steps": [
            "Group petitions by type and ruleBag before reading any outcome",
            "Cross-reference with PFW prosecution timeline",
            "If multiple petitions, assess whether systematic or case-specific issues",
            "If granted, check PTAB for correlation between petition history and challenge success",
            "For PFW workflow guidance: PFW_get_guidance('workflows_fpd') for FPD+PFW integration strategies"
        ]
    }

    return filtered_result


@async_tool_error_handler("petition_details")
async def _petition_details_within_deadline(
    petition_id: str, include_documents: bool
) -> Dict[str, Any]:
    """The details fetch, on one end-to-end time budget when it carries
    documents (Wave 2 A.5).

    include_documents=True can be a chain: the petition-details call and,
    when the record carries no documentBag of its own, the application
    file-wrapper fetch, each with its own retries. One Deadline
    (FPD_CONTENT_DEADLINE_SECONDS, default 85 s, under Cloudflare's ~100 s
    cut) is shared by all of them (util/deadline.py) and a spent budget
    returns a "Deadline exceeded" envelope. Without documents it is one
    request and runs as before.
    """
    service = get_fpd_service()
    if not include_documents:
        return await service.get_petition_details(
            petition_id=petition_id, include_documents=False
        )
    deadline = Deadline(content_deadline_seconds())
    try:
        with bind_deadline(deadline):
            async with asyncio.timeout(deadline.seconds):
                return await service.get_petition_details(
                    petition_id=petition_id, include_documents=True
                )
    except TimeoutError:
        return deadline_exceeded_response(generate_request_id())


async def fpd_get_petition_details(
    petition_id: str,
    include_documents: bool = True
) -> Dict[str, Any]:
    """Get complete details for a specific petition by petition ID (UUID).
Full record for one petition, all fields, document list, documentBag, document identifiers, outcome and reasoning metadata.

**documentBag carries NO download URLs — it never did anything a browser or
user could use directly.** Each entry's raw USPTO `downloadUrl` requires this
server's own API key and is stripped from this response before it reaches
you, so there is nothing here to hand a user. **MANDATORY WORKFLOW when
include_documents=True:**
1. Call FPD_Get_petition_details(petition_id=X, include_documents=True) to
   get each document's documentIdentifier.
2. For EACH document a user wants, call
   FPD_get_document_download(petition_id=X, document_identifier=DOC1) —
   this is what actually produces a working link, and it must be called
   once per document; documentBag's own fields never do.
3. Provide ONLY the link FPD_get_document_download returned. Never construct
   or relay an api.uspto.gov URL yourself.

**Use for:** Deep dive into specific petition, document metadata access, full legal context review.

**Returns:**
- All petition fields (no filtering)
- Document metadata if include_documents=True (file names, page counts, identifiers)
- Full legal context (all issues, CFR rules, statutes cited)
- Complete timeline (petition filed → decision issued)

**What documentBag contains: the petition's own papers.** Since USPTO's 2026-10
payload change the petition record carries its own documentBag (the decision,
e.g. PETDEC 'Petition Decision' or PET.DEC.AUTO 'ePetition Grant Letter', and
any papers filed or issued with it), labelled `document_metadata_source:
"petition_record"`. Only when a record comes back with no bag of its own is the
APPLICATION'S FILE WRAPPER substituted (`document_metadata_source:
"application_file_wrapper_fallback"`, explained in `document_metadata_note`):
that bag is the whole prosecution history, not just this petition's papers, so
filter it to the PET/PETDEC-style entries before describing it as this
petition's documents. When the substitution itself fails,
`document_metadata_available` is false, and an absent bag then means "metadata
unavailable", never "this petition has no documents".

**Absent fields:** this API omits a field it has no value for rather than
returning it as null or as an empty string, nested objects included. An absent
key is therefore the same case as null or empty: normal sparsity, not a wrong
field name and not a data error. firstApplicantName in particular is frequently
missing (see FPD_get_guidance section='coverage'). If the sibling fields on the
same object came back populated, the path was right and this record has no value.

**CITATIONS ARE LINKS:** the petition carries `cite_as`, a ready-made markdown
link labelled with the decision date and the application, e.g.
"[Petition decision 2019-06-11, application 12/950,321](https://patentcenter.uspto.gov/applications/12950321)".
Paste it after any sentence in an answer, a table or a memo that relies on this
decision. A bare application serial or a decision date with no link is not a
citation here: the reader has to be able to click through to a public record.
The target is Patent Center for the application, or Google Patents when the
record carries a patent number; there is no public per-decision URL, and a
persistent download link from FPD_get_document_download is a credential
addressed to the person who asked, never a citation.

**Document access:**
- documentBag entries carry a documentIdentifier and no download URL. Pass
  it to FPD_get_document_download(petition_id=..., document_identifier=...)
  — one call per document — to get a working, browser-usable link.

**Parameters:**
- petition_id: Petition decision record identifier (UUID from search results)
- include_documents: Include documentBag with file metadata (default True
  here, whereas FPD_Search_petitions_by_application defaults it False — the
  bag is the reason to call this tool, and there it would be one extra
  wrapper fetch per page for a value identical on every hit).
  A petition's own bag is usually one to a few documents; a file-wrapper
  fallback bag can carry 50-100+, and oversized responses are
  automatically slimmed (and truncated if necessary) with a documents_note
  explaining what was dropped. Set False when you only need petition fields —
  document downloads never need the full bag, just a documentIdentifier."""
    # Input validation (M4: UUID-shaped, not just non-empty)
    if not petition_id or len(petition_id.strip()) == 0:
        return format_error_response("Petition ID cannot be empty", 400, generate_request_id())
    try:
        petition_id = validate_petition_id(petition_id)
    except ValidationError as e:
        return format_error_response(str(e), 400, e.request_id)

    # Get petition details via FPDService (exact api_client.get_petition_by_id
    # passthrough — see module docstring)
    result = await _petition_details_within_deadline(petition_id, include_documents)

    # Check for errors
    if "error" in result:
        return result

    # CR-59/MCP-9: never leak a raw api.uspto.gov URL that needs this
    # server's own API key — see _strip_raw_document_urls. Before the size
    # guard, which only drops downloadOptionBag when it has to slim; this
    # must run regardless of response size.
    _strip_raw_document_urls(result)

    # Bound both paths for uniformity: include_documents=False is normally
    # small, but a petition with a very long issue/rule/statute bag can still
    # overshoot, and an unguarded overshoot is an unrecoverable client-side
    # truncation error. A response that already fits is returned untouched.
    # CITATIONS ARE LINKS: the petition row carries a `cite_as` markdown link
    # to the public record it concerns, and the envelope says what to do with
    # it (util/citations.py). Attached BEFORE the size guard so the link is
    # measured with the payload rather than added after it was certified.
    attach_citations(result)

    result = _bound_details_response(result)

    # Add detailed guidance for petition analysis
    result["llm_guidance"] = {
        "workflow": "Petition Details -> Document Access -> Cross-MCP Context",
        "document_access": {
            "description": "Use documentIdentifier from documentBag to download PDFs",
            "example": "FPD_get_document_download(petition_id='{petition_id}', document_identifier='ABC123')",
            "typical_documents": [
                "Petition PDF - Original petition filed by applicant/agent",
                "Decision PDF - Director's decision (GRANTED/DENIED/DISMISSED)",
                "Supporting exhibits - Additional documents filed with petition"
            ]
        },
        "classification": {
            "axis": (
                "decisionPetitionTypeCodeDescriptionText and ruleBag are the "
                "classification axis: they say what relief this petition requested. "
                "decisionTypeCodeDescriptionText says only whether it was granted."
            ),
            "denial_is_not_a_signal": (
                "DENIED is rare across all decisions and the ordinary outcome only "
                "among final decisions (finalPetitionDecisionIndicator true); most "
                "make-special and PPH petitions are GRANTED. Compare a denial against "
                "FPD_get_petition_statistics for the same petition_type_code. A denial carries NO quality signal on its own; "
                "read the decision document and compare only within this petition's "
                "own type."
            )
        },
        "legal_analysis": {
            "cfr_rules": "Check ruleBag for CFR citations (e.g., 37 CFR 1.137, 1.181, 1.182)",
            "statutes": "Check statuteBag for statutory basis (e.g., 35 USC 134)",
            "issues": "Review petitionIssueConsideredTextBag for specific issues raised",
            "outcome_significance": {
                "GRANTED": "Director granted the relief requested",
                "DENIED": (
                    "Director did not grant the relief requested. This is the "
                    "ordinary outcome here and is not, on its own, a finding about "
                    "the petition's merits or the prosecution's quality"
                ),
                "DISMISSED": (
                    "Refused as filed, usually because something the rule requires was "
                    "missing or insufficient; a dismissal commonly leaves room for a "
                    "renewed petition, so it need not be the last word. The reason is "
                    "in the decision document only: DISMISSED records carry no ruleBag "
                    "or statuteBag, so read the decision rather than reporting the "
                    "legal basis as missing data"
                )
            }
        },
        "cross_mcp_context": {
            "prosecution_history": "Use applicationNumberText with PFW to see full prosecution timeline",
            "timeline_correlation": "Compare petitionMailDate with office action dates in PFW",
            "ptab_risk": "If DENIED petition + later patented, check PTAB for challenges",
            "examiner_analysis": "Get examiner name from PFW, check if pattern of petitions against this examiner"
        },
        "next_steps": [
            "Read the petition type and legal basis (ruleBag, statuteBag) before the outcome",
            "Use FPD_get_document_download to access petition/decision PDFs if needed",
            "Cross-reference with PFW prosecution timeline for context",
            "Judge the outcome only within this petition's own type, never against the corpus"
        ]
    }

    return result


def register(mcp) -> None:
    """Register the 5 search/details tools (names/schemas unchanged)."""
    mcp.tool(name="FPD_Search_petitions_minimal",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": False, "readOnlyHint": True})(fpd_search_petitions_minimal)
    mcp.tool(name="FPD_Search_petitions_balanced",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_search_petitions_balanced)
    mcp.tool(name="FPD_Search_petitions_by_art_unit",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_search_petitions_by_art_unit)
    mcp.tool(name="FPD_Search_petitions_by_application",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_search_petitions_by_application)
    mcp.tool(name="FPD_Get_petition_details",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_get_petition_details)
