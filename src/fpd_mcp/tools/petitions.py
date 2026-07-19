"""Petition search + details tools (SD-1 god-module split).

Search_petitions_minimal/balanced/by_art_unit/by_application and
Get_petition_details, plus the convenience-query-building helpers they
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
            "and entity_status are only available in fpd_search_petitions_balanced. "
            "Use fpd_search_petitions_balanced for advanced filtering.",
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
    application_number: Optional[str] = None,     # e.g., "17896175"
    patent_number: Optional[str] = None,          # e.g., "11788453"

    # Decision Filters
    decision_type: Optional[str] = None,          # e.g., "GRANTED", "DENIED", "DISMISSED"
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

**Convenience Parameters:**
- `applicant_name`: Company/party name (e.g., 'Apple Inc.')
- `application_number`: Application number (e.g., '17896175')
- `patent_number`: Patent number if granted (e.g., '11788453')
- `decision_type`: Outcome (e.g., 'GRANTED', 'DENIED', 'DISMISSED')
- `deciding_office`: Office that decided (e.g., 'OFFICE OF PETITIONS')
- `petition_date_start/end`: Filing date range (YYYY-MM-DD)
- `decision_date_start/end`: Decision date range (YYYY-MM-DD)

**Examples:**
```python
# Denied petitions for company
fpd_search_petitions_minimal(applicant_name="TechCorp Inc.", decision_type="DENIED", limit=50)

# Hybrid: keywords + convenience
fpd_search_petitions_minimal(query="machine learning", decision_type="DENIED", limit=50)
```

**Progressive Disclosure Workflow:**
1. Use THIS TOOL for discovery with minimal params (50-100 results)
2. Present top results to user for selection
3. Use fpd_search_petitions_balanced for detailed analysis (10-20 selected)
   - Balanced tier adds: petition_type_code, art_unit, technology_center, prosecution_status, entity_status
4. Use fpd_get_petition_details for complete petition data

**Cross-MCP Integration:**
- {QueryFieldNames.APPLICATION_NUMBER} -> Links to Patent File Wrapper MCP
- {QueryFieldNames.PATENT_NUMBER} -> Links to PTAB MCP for post-grant challenges
- Use balanced tier to get {QueryFieldNames.ART_UNIT} for PFW cross-reference"""
    # Input validation
    if limit < api_constants.MIN_SEARCH_LIMIT or limit > api_constants.MAX_SEARCH_LIMIT:
        raise ValidationError(f"Limit must be between {api_constants.MIN_SEARCH_LIMIT} and {api_constants.MAX_SEARCH_LIMIT}", generate_request_id())
    if offset < 0:
        raise ValidationError("Offset must be non-negative", generate_request_id())

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
    filtered_result = await get_fpd_service().search_petitions_minimal(
        query=final_query,
        limit=limit,
        offset=offset
    )

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

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
            "next_tier": "Use fpd_search_petitions_balanced for 5 additional parameters: petition_type_code, art_unit, technology_center, prosecution_status, entity_status",
            "progressive_disclosure": "Start here for discovery, advance to balanced for analysis"
        },
        "next_steps": [
            "Present top results to user for selection",
            "Use fpd_search_petitions_balanced for detailed analysis of selected petitions",
            "Use fpd_search_petitions_by_application to get all petitions for specific application",
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
    petition_type_code: Optional[str] = None,     # e.g., "551" (revival), "182" (restriction)
    art_unit: Optional[str] = None,               # e.g., "2128", "3600"
    technology_center: Optional[str] = None,      # e.g., "21", "2100"

    # Status Filters
    prosecution_status: Optional[str] = None,     # e.g., "During examination", "Patented Case"
    entity_status: Optional[str] = None           # e.g., "Small", "Large", "Undiscounted"
) -> Dict[str, Any]:
    """Balanced search for Final Petition Decisions with comprehensive fields (10-20 results).

**Balanced tier convenience parameters (14 total) - adds 5 advanced filters to minimal tier.**

Use for: Detailed petition analysis after minimal search, cross-referencing with PFW/PTAB data,
analyzing petition types and legal context.
Returns: 18 key fields including petition type, art unit, technology center, prosecution status,
legal issues, CFR rules cited, statutes cited, entity status, and invention title.

**All Minimal Parameters (9) - same as Search_petitions_minimal:**
- `applicant_name`, `application_number`, `patent_number`
- `decision_type`, `deciding_office`
- `petition_date_start/end`, `decision_date_start/end`

**Additional Balanced Parameters (5):**
- `petition_type_code`: Petition type (e.g., '551' = revival, '182' = restriction)
- `art_unit`: Art unit number (e.g., '2128') - enables PFW cross-reference
- `technology_center`: Tech center (e.g., '21', '2100')
- `prosecution_status`: Status (e.g., 'During examination', 'Patented Case')
- `entity_status`: Entity type (e.g., 'Small', 'Large', 'Undiscounted')

**Examples:**
```python
# Revival petitions (type 551) that were denied
fpd_search_petitions_balanced(petition_type_code="551", decision_type="DENIED", limit=20)

# Complex combination for quality analysis
fpd_search_petitions_balanced(
    art_unit="2128", petition_type_code="551",
    decision_type="DENIED", prosecution_status="During examination", limit=20
)
```

**Progressive Disclosure Workflow:**
1. Discovery: fpd_search_petitions_minimal(decision_type='DENIED', limit=100)
2. User selects interesting petitions
3. Analysis: fpd_search_petitions_balanced with advanced filters (art_unit, petition_type_code)
4. Cross-reference: Use art_unit with PFW, use patentNumber with PTAB

**Cross-MCP Integration:**
- applicationNumberText -> pfw_search_applications_minimal with fields parameter for targeted data
- patentNumber -> search_trials_minimal(patent_number=X)
- groupArtUnitNumber -> pfw_search_applications_minimal(art_unit=X, fields=[...])
- firstApplicantName -> Match parties across PFW/PTAB MCPs"""
    # Input validation
    if limit < 1 or limit > 50:
        return format_error_response("Limit must be between 1 and 50", 400)
    if offset < 0:
        return format_error_response("Offset must be non-negative", 400)

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
        return format_error_response(f"Combined query too long (max {_MAX_COMBINED_QUERY_LENGTH} characters)", 400)

    # Search petitions (routes through FPDService — see module docstring)
    filtered_result = await get_fpd_service().search_petitions_balanced(
        query=final_query,
        limit=limit,
        offset=offset
    )

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

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
            "pfw_prosecution": "pfw_search_applications_minimal with fields parameter for examiner/status context",
            "ptab_challenges": "search_trials_minimal(patent_number=X) if patentNumber present",
            "art_unit_analysis": "fpd_search_petitions_by_art_unit(art_unit=X) for pattern analysis"
        },
        "red_flags": {
            "revival_37cfr1137": "Application abandoned - revival petition filed",
            "dispute_37cfr1181": "Examiner conflict - supervisory review petition",
            "denied_petition": "Director denied - weak arguments or procedural errors"
        },
        "next_steps": [
            "fpd_get_petition_details for full details + documents",
            "Cross-reference applicationNumberText with PFW",
            "Cross-reference patentNumber with PTAB",
            "Use fpd_search_petitions_by_art_unit for examiner patterns"
        ]
    }

    return filtered_result


@async_tool_error_handler("art_unit_search")
async def fpd_search_petitions_by_art_unit(
    art_unit: str,
    date_range: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Search petitions by art unit number for examiner/art unit quality analysis.

**Use for:** Art unit quality assessment, systematic petition patterns, examiner behavior analysis.
Returns balanced field set for cross-referencing with PFW examiner data and PTAB challenge rates.

**Example:**
- fpd_search_petitions_by_art_unit(art_unit="2128", limit=50)
- fpd_search_petitions_by_art_unit(art_unit="2128", date_range="2020-01-01:2024-12-31")

**Analysis patterns:**
- High petition frequency → Difficult examiners or challenging technology
- Frequent revival petitions (37 CFR 1.137) → Docketing/procedural issues
- Examiner disputes (37 CFR 1.181) → Communication/quality problems
- Denied petitions → Weak prosecution practices

**Cross-MCP integration:**
- applicationNumberText → pfw_search_applications_minimal with fields parameter for examiner names
- Group petitions by examiner to identify individual patterns
- patentNumber → PTAB MCP to correlate petition history with challenge success

**Parameters:**
- art_unit: Art unit number (e.g., "2128", "3600")
- date_range: Optional date range (format: "YYYY-MM-DD:YYYY-MM-DD")
- limit: Maximum results (default 50, max 200)"""
    # Input validation
    if not art_unit or len(art_unit.strip()) == 0:
        return format_error_response("Art unit cannot be empty", 400)
    # M4: route through the same validator the minimal/balanced tools
    # use for this logical field, instead of a bare empty-check.
    try:
        art_unit = validate_string_param("art_unit", art_unit, 10)
    except ValidationError as e:
        return format_error_response(str(e), 400, e.request_id)
    if limit < api_constants.MIN_SEARCH_LIMIT or limit > api_constants.MAX_SEARCH_LIMIT:
        return format_error_response(f"Limit must be between {api_constants.MIN_SEARCH_LIMIT} and {api_constants.MAX_SEARCH_LIMIT}", 400)
    if date_range:
        # Basic date range format validation
        parts = date_range.split(":")
        if len(parts) != 2:
            return format_error_response(
                "Date range must be in format YYYY-MM-DD:YYYY-MM-DD", 400
            )

    # Search via FPDService (routes through the same api_client.search_by_art_unit
    # + balanced-field filter as before — see module docstring)
    filtered_result = await get_fpd_service().search_by_art_unit(
        art_unit=art_unit,
        date_range=date_range,
        limit=limit
    )

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

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
            "Use pfw_search_applications_minimal with fields parameter for examiner mapping",
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
    include_documents: bool = False
) -> Dict[str, Any]:
    """Get all petition decisions for a specific application number.

**Use for:** Complete petition history, red flag identification, cross-referencing with PFW prosecution timeline.

**Examples:**
- Basic petition check: fpd_search_petitions_by_application(application_number="17896175")
- With documents: fpd_search_petitions_by_application(application_number="17896175", include_documents=True)

**Red flag analysis:**
- Multiple petitions → Difficult prosecution (missed deadlines, examiner conflicts)
- Revival petitions (37 CFR 1.137) → Application was abandoned
- Examiner disputes (37 CFR 1.181) → Contentious relationship with examiner
- Denied petitions → Unsuccessful arguments, potential prosecution quality issues

**Cross-MCP integration:**
1. Use pfw_search_applications_minimal with fields parameter for prosecution context
2. Compare petition dates with prosecution timeline (office actions, RCEs)
3. Identify if petitions correlate with examiner changes or specific prosecution events
4. If patented, check PTAB for post-grant challenges

**Parameters:**
- application_number: USPTO application number (e.g., "17896175", "15/123,456")
- include_documents: Include documentBag in response (default False)"""
    # Input validation
    if not application_number or len(application_number.strip()) == 0:
        return format_error_response("Application number cannot be empty", 400)

    # M4: route through the same validator the minimal/balanced tools use
    # for this logical field (digits-only, 6-10 chars) instead of a bare
    # empty-check + manual strip.
    try:
        clean_app_num = validate_application_number(application_number)
    except ValidationError as e:
        return format_error_response(str(e), 400, e.request_id)

    # Search via FPDService (routes through the same api_client.search_by_application
    # + conditional balanced-field filter as before — see module docstring)
    filtered_result = await get_fpd_service().search_by_application(
        application_number=clean_app_num,
        include_documents=include_documents
    )

    # Check for errors
    if "error" in filtered_result:
        return filtered_result

    # Add application-specific guidance
    filtered_result["llm_guidance"] = {
        "workflow": "Application Petition Check -> Timeline Correlation -> Cross-MCP Analysis",
        "interpretation": {
            "no_petitions": {
                "meaning": "Normal prosecution without Director intervention",
                "quality_signal": "Positive - no major procedural issues"
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
            "step_1": f"Use pfw_search_applications_minimal(query='applicationNumberText:{clean_app_num}', fields=[...]) for prosecution context",
            "step_2": "Compare petition dates with office action dates, RCE filings, examiner changes",
            "step_3": "Identify prosecution events that triggered petitions",
            "step_4": "If patented, use search_trials_minimal to check PTAB challenges"
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
            "For PFW workflow guidance: pfw_get_guidance('workflows_fpd') for FPD+PFW integration strategies"
        ]
    }

    return filtered_result


@async_tool_error_handler("petition_details")
async def fpd_get_petition_details(
    petition_id: str,
    include_documents: bool = True
) -> Dict[str, Any]:
    """Get complete details for a specific petition by petition ID (UUID).

**⚠️ CRITICAL: Proxy URLs in documentBag require proxy server to be running!**
**MANDATORY WORKFLOW when include_documents=True:**
1. Call fpd_get_petition_details(petition_id=X, include_documents=True)
2. Call fpd_get_document_download(petition_id=X, document_identifier=DOC1) - starts proxy
3. NOW provide all document download links to user - proxy is ready

**Use for:** Deep dive into specific petition, document metadata access, full legal context review.

**Returns:**
- All petition fields (no filtering)
- Document metadata if include_documents=True (file names, page counts, identifiers)
- Full legal context (all issues, CFR rules, statutes cited)
- Complete timeline (petition filed → decision issued)

**Document access:**
- Use documentIdentifier from documentBag with fpd_get_document_download for browser access
- Typical documents: Petition PDF, Decision PDF, supporting exhibits

**Parameters:**
- petition_id: Petition decision record identifier (UUID from search results)
- include_documents: Include documentBag with file metadata (default True)"""
    # Input validation (M4: UUID-shaped, not just non-empty)
    if not petition_id or len(petition_id.strip()) == 0:
        return format_error_response("Petition ID cannot be empty", 400)
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

    # Add detailed guidance for petition analysis
    result["llm_guidance"] = {
        "workflow": "Petition Details -> Document Access -> Cross-MCP Context",
        "document_access": {
            "description": "Use documentIdentifier from documentBag to download PDFs",
            "example": "fpd_get_document_download(petition_id='{petition_id}', document_identifier='ABC123')",
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
            "Use fpd_get_document_download to access petition/decision PDFs if needed",
            "Cross-reference with PFW prosecution timeline for context",
            "Assess red flag significance based on petition type and outcome"
        ]
    }

    return result


def register(mcp) -> None:
    """Register the 5 search/details tools (names/schemas unchanged)."""
    mcp.tool(name="Search_petitions_minimal",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": False, "readOnlyHint": True})(fpd_search_petitions_minimal)
    mcp.tool(name="Search_petitions_balanced",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_search_petitions_balanced)
    mcp.tool(name="Search_petitions_by_art_unit",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_search_petitions_by_art_unit)
    mcp.tool(name="Search_petitions_by_application",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_search_petitions_by_application)
    mcp.tool(name="Get_petition_details",
             app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_get_petition_details)
