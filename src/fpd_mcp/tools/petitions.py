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

from typing import Any, Dict, Optional

from fastmcp.apps import AppConfig

from ..api.field_constants import FPDFields, QueryFieldNames
from ..app_uris import SEARCH_URI
from ..config import api_constants
from ..runtime import get_fpd_service
from ..shared.response_bounds import bound_structured_response
from ..shared.error_utils import (
    ValidationError,
    async_tool_error_handler,
    format_error_response,
    generate_request_id,
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
    _DOC_SLIM_FIELDS (dropping downloadOptionBag — FPD_get_document_download
    needs only documentIdentifier), stage 2 halves the slimmed bag until it
    fits (floor _DETAILS_MIN_DOCS). Returns the payload untouched (no
    `_bounds` key, byte-identical) when it already fits.
    """
    return bound_structured_response(
        result,
        bags=_DETAILS_BAGS,
        note=_DETAILS_NOTE,
        aliases=_DETAILS_ALIASES,
    )


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
    `returned` counts the records the search produced; if the response-size
    guard later sheds records, its `_bounds.items_returned` is the authority.
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
    # Include base query if provided
    if query and query.strip():
        query_parts.append(f"({query})")
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
         QueryFieldNames.DECISION_TYPE, False),
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
    petition_type_code: Optional[str],
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
    # (param_name, value, field_name, max_length, quoted)
    specs = (
        ("petition_type_code", petition_type_code, FPDFields.DECISION_PETITION_TYPE_CODE, 10, False),
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
    petition_type_code: Optional[str],
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
    petition_type_code: Optional[str] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    prosecution_status: Optional[str] = None,
    entity_status: Optional[str] = None,
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
    decision_type: Optional[str] = None,          # "DENIED" | "GRANTED" | "DISMISSED" (overwhelmingly DENIED)
    deciding_office: Optional[str] = None,        # e.g., "OFFICE OF PETITIONS"

    # Date Ranges
    petition_date_start: Optional[str] = None,    # e.g., "2024-01-01" (YYYY-MM-DD)
    petition_date_end: Optional[str] = None,      # e.g., "2024-12-31" (YYYY-MM-DD)
    decision_date_start: Optional[str] = None,    # e.g., "2024-01-01" (YYYY-MM-DD)
    decision_date_end: Optional[str] = None       # e.g., "2024-12-31" (YYYY-MM-DD)
) -> Dict[str, Any]:
    """Ultra-fast discovery search for Final Petition Decisions (50-100 results).

**NEW: Minimal tier convenience parameters (9 total) - no query syntax needed!**

Use for: High-volume petition discovery, finding petitions by applicant, decision type, or date range.
Returns: 8 essential fields - petition ID, application number, patent number, applicant name,
decision type, petition mail date, decision date, deciding office.

**Coverage:** final petition decisions in publicly available applications and patents
filed in 2001 or later; the decisions data itself starts with 2022-and-later decisions,
backfilled incrementally monthly. A zero result for a petition decided before 2022 is
expected and does not mean no petition existed (see FPD_get_guidance section='coverage').

**Convenience Parameters:**
- `applicant_name`: Company/party name (e.g., 'Apple Inc.')
- `application_number`: Application number (e.g., '17414168')
- `patent_number`: Patent number if granted (e.g., '12252554')
- `decision_type`: Outcome — 'DENIED', 'GRANTED' or 'DISMISSED'. The public corpus is overwhelmingly DENIED; GRANTED and DISMISSED are rare but real, so a small result set for either is a real answer, not a broken filter. There is no filter-value validation, so a misspelling and a genuinely empty class both return zero — check the spelling before concluding a class is absent
- `deciding_office`: Office that decided (e.g., 'OFFICE OF PETITIONS')
- `petition_date_start/end`: Filing date range (YYYY-MM-DD)
- `decision_date_start/end`: Decision date range (YYYY-MM-DD)

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

    # Add query metadata
    filtered_result["query_info"] = {
        "final_query": final_query,
        "convenience_parameters_used": convenience_params_used,
        "tier": "minimal",
        "available_parameters": [
            "applicant_name", "application_number", "patent_number",
            "decision_type", "deciding_office",
            "petition_date_start", "petition_date_end",
            "decision_date_start", "decision_date_end"
        ]
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
        "red_flags": {
            "revival_petitions": "Look for ruleBag containing '37 CFR 1.137' (abandoned applications)",
            "examiner_disputes": "Look for ruleBag containing '37 CFR 1.181' (supervisory review)",
            "denied_petitions": "decisionTypeCodeDescriptionText: 'DENIED' indicates potential quality issues"
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
    petition_type_code: Optional[str] = None,     # e.g., "502" (revival), "551" (PTA correction)
    art_unit: Optional[str] = None,               # e.g., "2128", "3643"
    technology_center: Optional[str] = None,      # e.g., "3600", "1600" (four digits, as stored)

    # Status Filters
    prosecution_status: Optional[str] = None,     # e.g., "During examination", "Patented", "Abandoned"
    entity_status: Optional[str] = None           # e.g., "Small", "Micro", "Regular Undiscounted"
) -> Dict[str, Any]:
    """Balanced search for Final Petition Decisions with comprehensive fields (10-20 results).
Petitions, petition decisions, granted or dismissed, revival, unintentional delay, withdrawal of a holding of abandonment, supervisory review, waiver of a rule, PTA correction, 37 CFR 1.137 1.181 1.183.

**Balanced tier convenience parameters (14 total) - adds 5 advanced filters to minimal tier.**

Use for: Detailed petition analysis after minimal search, cross-referencing with PFW/PTAB data,
analyzing petition types and legal context.
Returns: 18 key fields including petition type, art unit, technology center, prosecution status,
legal issues, CFR rules cited, statutes cited, entity status, and invention title.

**Coverage:** final petition decisions in publicly available applications and patents
filed in 2001 or later; the decisions data itself starts with 2022-and-later decisions,
backfilled incrementally monthly. A zero result for a petition decided before 2022 is
expected and does not mean no petition existed (see FPD_get_guidance section='coverage').

**All Minimal Parameters (9) - same as FPD_Search_petitions_minimal:**
- `applicant_name`, `application_number`, `patent_number`
- `decision_type`, `deciding_office`
- `petition_date_start/end`, `decision_date_start/end`

**Additional Balanced Parameters (5):**
- `petition_type_code`: Petition type — see the verified code table below. It is
  NOT the CFR rule number: '181' and '182' are not type codes at all
- `art_unit`: Art unit number (e.g., '2128', '3643') - enables PFW cross-reference
- `technology_center`: Tech center, four digits as stored (e.g., '3600', '1600').
  A two-digit prefix such as '21' matches nothing — the value is not expanded
- `prosecution_status`: Status (e.g., 'During examination', 'Patented', 'Abandoned',
  'After payment of issue fee'). The value is the bare 'Patented', not 'Patented Case'
- `entity_status`: Entity type — 'Small', 'Micro' or 'Regular Undiscounted'.
  There is no 'Large' and no bare 'Undiscounted'

**Petition type codes (probed live 2026-08-30; the descriptions are USPTO's, typos included):**
| code | meaning |
|---|---|
| 501 | TO REVIVE AN ABANDONED APPLICATION - UNAVOIDABLE DELAY (37 CFR 1.137(a)) |
| 502 | REVIVE AN APPLICATION ABANDONED BY OPAP OR THE TC - UNINTENTIONALLY DELAYED REPLY (37 CFR 1.137(b)) |
| 503 | FOR SUSPENSION OR WAIVER OF A RULE (37 CFR 1.183) |
| 504 | TO INVOKE SUPERVISORY AUTHORITY RE - PATENT EXAMINING (37 CFR 1.181, incl. restriction under 1.144) |
| 519 / 520 | Rule 1.182 matters (name/order changes; matters not otherwise provided for) |
| 525 | TO WITHDRAW A HOLDING OF ABANDONMENT |
| 550 / 551 | CORRECTION OF PATENT TERM ADJUSTMENT VALUE (before issue / after issue) |

**551 IS NOT REVIVAL.** It is the PTA-correction code and it is the single
largest class in the corpus (714 records), so a search that means "revival" and
sends 551 silently returns hundreds of unrelated PTA corrections. Type codes are
also incomplete: a revival can arrive under several codes. The dependable route
to a CFR-defined petition class is a `ruleBag` clause through the raw `query`
parameter, which has no convenience parameter of its own.

**Examples:**
```python
# Revival petitions (37 CFR 1.137, unintentional delay) that were denied
FPD_Search_petitions_balanced(petition_type_code="502", decision_type="DENIED", limit=20)

# Every revival regardless of type code — the reliable route
FPD_Search_petitions_balanced(query='ruleBag:"37 CFR 1.137"', limit=20)

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
            "prosecution_status", "entity_status"
        ]
    }

    # Add enhanced usage guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Balanced Analysis -> Cross-MCP Integration -> Document Retrieval",
        "cross_mcp_workflows": {
            "pfw_prosecution": "PFW_search_applications_minimal with fields parameter for examiner/status context",
            "ptab_challenges": "PTAB_search_trials_minimal(patent_number=X) if patentNumber present",
            "art_unit_analysis": "FPD_Search_petitions_by_art_unit(art_unit=X) for pattern analysis"
        },
        "red_flags": {
            "revival_37cfr1137": "Application abandoned - revival petition filed",
            "dispute_37cfr1181": "Examiner conflict - supervisory review petition",
            "denied_petition": "Director denied - weak arguments or procedural errors"
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
    offset: int = 0
) -> Dict[str, Any]:
    """Search petitions by art unit number for examiner/art unit quality analysis.
Art unit, technology center, examiner behavior, group, unit number, quality analysis, petition patterns by art unit.

**Use for:** Art unit quality assessment, systematic petition patterns, examiner behavior analysis.
Returns balanced field set for cross-referencing with PFW examiner data and PTAB challenge rates.

**Coverage:** final petition decisions in publicly available applications and patents
filed in 2001 or later; the decisions data itself starts with 2022-and-later decisions,
backfilled incrementally monthly. A zero result for a petition decided before 2022 is
expected and does not mean no petition existed (see FPD_get_guidance section='coverage').

**Example:**
- FPD_Search_petitions_by_art_unit(art_unit="2128", limit=50)
- FPD_Search_petitions_by_art_unit(art_unit="2128", date_range="2020-01-01:2024-12-31")
- Second page: FPD_Search_petitions_by_art_unit(art_unit="2128", limit=50, offset=50)

**Analysis patterns:**
- High petition frequency → Difficult examiners or challenging technology
- Frequent revival petitions (37 CFR 1.137) → Docketing/procedural issues
- Examiner disputes (37 CFR 1.181) → Communication/quality problems
- Denied petitions → Weak prosecution practices

**Cross-MCP integration:**
- applicationNumberText → PFW_search_applications_minimal with fields parameter for examiner names
- Group petitions by examiner to identify individual patterns
- patentNumber → PTAB MCP to correlate petition history with challenge success

**Parameters:**
- art_unit: Art unit number, four digits as stored (e.g., "2128", "3643")
- date_range: Optional petitionMailDate range (format: "YYYY-MM-DD:YYYY-MM-DD").
  Filters on the date the petition was mailed, inclusive of both bounds
- limit: Maximum results (default 50, max 100 — a larger value is clamped, not
  rejected, and the response then carries `limit_clamped`)
- offset: Starting position for paging (default 0). The response's `paging`
  block reports returned/total/has_more/next_offset — feed next_offset back
  as offset to retrieve the remainder."""
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
        offset=offset
    ))

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

    _paging_envelope(filtered_result, limit_requested=limit, offset=offset)
    _stamp_limit_clamp(filtered_result, clamp_marker)

    # Add art unit analysis guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Art Unit Discovery -> Examiner Mapping -> PTAB Correlation",
        "analysis_patterns": {
            "high_frequency": "Many petitions → Difficult examiners/technology/systematic issues",
            "revival_clustering": "Multiple 37 CFR 1.137 → Docketing/procedural problems",
            "examiner_disputes": "Multiple 37 CFR 1.181 → Communication/quality issues",
            "ptab_correlation": "High petitions + high PTAB invalidation → Quality issues"
        },
        "next_steps": [
            "Use PFW_search_applications_minimal with fields parameter for examiner mapping",
            "Group petitions by examiner to identify individual patterns",
            "Check GRANTED/DENIED outcomes to assess Director overturn rates",
            "Cross-reference patentNumbers with PTAB for challenge correlation"
        ],
        "red_flags": {
            "high_denial_rate": "Weak prosecution practices",
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
    offset: int = 0
) -> Dict[str, Any]:
    """Get all petition decisions for a specific application number.
Petition history for one application or patent, did this case file a petition, by serial number, prosecution timeline cross-reference.

**Use for:** Complete petition history, red flag identification, cross-referencing with PFW prosecution timeline.

**Coverage:** final petition decisions in publicly available applications and patents
filed in 2001 or later; the decisions data itself starts with 2022-and-later decisions,
backfilled incrementally monthly. A zero result for a petition decided before 2022 is
expected and does not mean no petition existed (see FPD_get_guidance section='coverage').

**Examples:**
- Basic petition check: FPD_Search_petitions_by_application(application_number="17414168")
- With documents: FPD_Search_petitions_by_application(application_number="17414168", include_documents=True)

**Red flag analysis:**
- Multiple petitions → Difficult prosecution (missed deadlines, examiner conflicts)
- Revival petitions (37 CFR 1.137) → Application was abandoned
- Examiner disputes (37 CFR 1.181) → Contentious relationship with examiner
- Denied petitions → Unsuccessful arguments, potential prosecution quality issues

**Cross-MCP integration:**
1. Use PFW_search_applications_minimal with fields parameter for prosecution context
2. Compare petition dates with prosecution timeline: PFW_get_oa_rejections for the
   structured rejection map, PFW_get_oa_text for the examiner's actual words - one
   call each, no document bag and no OCR. Fall back to
   PFW_get_application_documents + PFW_get_document_content_with_ocr only for
   non-OA papers, office actions older than roughly 2008, or a PDF
3. Identify if petitions correlate with examiner changes or specific prosecution events
4. If patented, check PTAB for post-grant challenges

**Parameters:**
- application_number: USPTO application number, digits only (e.g., "17414168").
  Slashes and spaces are stripped, so "17/414168" also works; commas and
  letters are rejected, so "17/414,168" and "US17/414,168" return a 400.
  This is the APPLICATION serial, not a patent number. Patent numbers passed
  10,000,000 in mid-2018, so the two namespaces now collide at 8 digits, and
  this server does not resolve between them: an 8-digit granted patent number
  passed here returns an empty result that reads as "no petitions", which is
  wrong rather than empty. Map a patent number to its application first with
  the PFW MCP, PFW_search_applications_minimal(query='patentNumber:<n>')
- include_documents: Include documentBag on every returned petition (default
  False here, whereas FPD_Get_petition_details defaults it True — this is a
  page of records where the bag is identical on every one of them, that is a
  single record where the bag is the reason to call it). The FPD search
  endpoint serves no documentBag of its own, so the bag
  comes from the APPLICATION FILE WRAPPER — the same source
  FPD_Get_petition_details serves today, and labelled as such in
  `document_metadata_source`. It is the application's whole prosecution history
  (office actions, claims, IDS, ...), not only the petition papers, and it is
  identical on every petition of this application. Costs one extra USPTO call;
  leave it False for a plain petition-history check
- limit: Maximum petition records to return (default 100, max 100 — a larger
  value is clamped, not rejected, and the response then carries `limit_clamped`)
- offset: Starting position for paging (default 0). The response's `paging`
  block reports returned/total/has_more/next_offset — feed next_offset back
  as offset to retrieve the remainder."""
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
        offset=offset
    ))

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

    _paging_envelope(filtered_result, limit_requested=limit, offset=offset)
    _stamp_limit_clamp(filtered_result, clamp_marker)

    # An application with more petitions than one page: the documentBag path
    # in particular is large, so make the remainder explicitly reachable.
    if include_documents:
        filtered_result = _bound_details_response(filtered_result)

    # Add application-specific guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Application Petition Check -> Timeline Correlation -> Cross-MCP Analysis",
        "interpretation": {
            "no_petitions": {
                "meaning": (
                    "No final petition decisions in the covered dataset. Coverage floors apply: "
                    "applications filed 2001 or later, decisions data from 2022 and later "
                    "(monthly incremental). For prosecution that concluded before 2022 a zero "
                    "result says nothing about whether a petition was ever filed or decided."
                ),
                "caveat": (
                    "Do not read an empty result as clean prosecution on an older application; "
                    "a petition decided before the 2022 decisions floor is simply absent here. "
                    "Only for post-2022 activity does zero support a no-petition inference."
                )
            },
            "single_petition": {
                "meaning": "One-time issue requiring Director decision",
                "action": "Review petition type and outcome for context"
            },
            "multiple_petitions": {
                "meaning": "Multiple prosecution problems or complex case",
                "red_flag": "May indicate difficult prosecution, missed deadlines, or examiner conflicts",
                "action": "Use PFW to correlate petition dates with prosecution timeline"
            }
        },
        "cross_mcp_workflow": {
            "step_1": f"Use PFW_search_applications_minimal(query='applicationNumberText:{clean_app_num}', fields=[...]) for prosecution context",
            "step_2": "Compare petition dates with office action dates, RCE filings, examiner changes — use PFW_get_oa_rejections (structured rejection map) then PFW_get_oa_text (examiner's words, one call, no document bag or OCR); the document-bag + OCR path is the fallback for pre-2008 office actions, non-OA papers, or an actual PDF",
            "step_3": "Identify prosecution events that triggered petitions",
            "step_4": "If patented, use PTAB_search_trials_minimal to check PTAB challenges"
        },
        "petition_pattern_analysis": {
            "revival_only": "Application was abandoned and revived - check PFW for abandonment reason",
            "examiner_disputes": "37 CFR 1.181 petitions indicate examiner conflicts - may affect PTAB risk",
            "restriction_petitions": "37 CFR 1.182 petitions indicate claim scope issues",
            "denied_petitions": "DENIED outcomes suggest weak arguments or procedural problems"
        },
        "next_steps": [
            "Review petition types and outcomes to identify red flags",
            "Cross-reference with PFW prosecution timeline",
            "If multiple petitions, assess whether systematic or case-specific issues",
            "If granted, check PTAB for correlation between petition history and challenge success",
            "For PFW workflow guidance: PFW_get_guidance('workflows_fpd') for FPD+PFW integration strategies"
        ]
    }

    return filtered_result


@async_tool_error_handler("petition_details")
async def fpd_get_petition_details(
    petition_id: str,
    include_documents: bool = True
) -> Dict[str, Any]:
    """Get complete details for a specific petition by petition ID (UUID).
Full record for one petition, all fields, document list, documentBag, document identifiers, outcome and reasoning metadata.

**⚠️ CRITICAL: Proxy URLs in documentBag require proxy server to be running!**
**MANDATORY WORKFLOW when include_documents=True:**
1. Call FPD_Get_petition_details(petition_id=X, include_documents=True)
2. Call FPD_get_document_download(petition_id=X, document_identifier=DOC1) - starts proxy
3. NOW provide all document download links to user - proxy is ready

**Use for:** Deep dive into specific petition, document metadata access, full legal context review.

**Returns:**
- All petition fields (no filtering)
- Document metadata if include_documents=True (file names, page counts, identifiers)
- Full legal context (all issues, CFR rules, statutes cited)
- Complete timeline (petition filed → decision issued)

**What documentBag actually contains:** USPTO's petition-details
includeDocuments=true endpoint has been erroring upstream since at least
2026-07, so documentBag is currently served from the APPLICATION FILE WRAPPER
instead — the whole prosecution history (office actions, claims, specification,
IDS, 892/1449 forms, abandonment notices), not just the petition papers. The
substitution is labelled: check `document_metadata_source` before treating the
bag as petition-only, and expect to filter it. When the substitution itself
fails, `document_metadata_available` is false — an absent bag then means
"metadata unavailable", never "this petition has no documents".

**Document access:**
- Use documentIdentifier from documentBag with FPD_get_document_download for browser access

**Parameters:**
- petition_id: Petition decision record identifier (UUID from search results)
- include_documents: Include documentBag with file metadata (default True
  here, whereas FPD_Search_petitions_by_application defaults it False — the
  bag is the reason to call this tool, and there it would be one extra
  wrapper fetch per page for a value identical on every hit).
  A file wrapper can carry 50-100+ documents; oversized responses are
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
    result = await get_fpd_service().get_petition_details(
        petition_id=petition_id,
        include_documents=include_documents
    )

    # Check for errors
    if "error" in result:
        return result

    # Bound both paths for uniformity: include_documents=False is normally
    # small, but a petition with a very long issue/rule/statute bag can still
    # overshoot, and an unguarded overshoot is an unrecoverable client-side
    # truncation error. A response that already fits is returned untouched.
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
        "legal_analysis": {
            "cfr_rules": "Check ruleBag for CFR citations (e.g., 37 CFR 1.137, 1.181, 1.182)",
            "statutes": "Check statuteBag for statutory basis (e.g., 35 USC 134)",
            "issues": "Review petitionIssueConsideredTextBag for specific issues raised",
            "outcome_significance": {
                "GRANTED": "Director agreed with petitioner - examiner/office action modified",
                "DENIED": "Director upheld examiner/office - petition unsuccessful",
                "DISMISSED": "Petition withdrawn or moot - no substantive decision"
            }
        },
        "cross_mcp_context": {
            "prosecution_history": "Use applicationNumberText with PFW to see full prosecution timeline",
            "timeline_correlation": "Compare petitionMailDate with office action dates in PFW",
            "ptab_risk": "If DENIED petition + later patented, check PTAB for challenges",
            "examiner_analysis": "Get examiner name from PFW, check if pattern of petitions against this examiner"
        },
        "next_steps": [
            "Review decision outcome and legal basis (ruleBag, statuteBag)",
            "Use FPD_get_document_download to access petition/decision PDFs if needed",
            "Cross-reference with PFW prosecution timeline for context",
            "Assess red flag significance based on petition type and outcome"
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
