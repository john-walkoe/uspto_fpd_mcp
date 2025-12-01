"""Final Petition Decisions MCP Server

Environment Variables:
    USPTO_API_KEY: Required USPTO API key from https://data.uspto.gov/myodp/
    MISTRAL_API_KEY: Optional Mistral API key for OCR on scanned documents

    Proxy Configuration:
        ENABLE_PROXY_SERVER: Enable/disable proxy functionality (default: true)
        ENABLE_ALWAYS_ON_PROXY: Start proxy immediately vs on-demand (default: true)
        FPD_PROXY_PORT: Local proxy server port (default: 8081)
        CENTRALIZED_PROXY_PORT: Centralized PFW proxy port (auto-detected)

    API Configuration:
        USPTO_TIMEOUT: API request timeout in seconds (default: 30.0)
        USPTO_DOWNLOAD_TIMEOUT: Document download/OCR timeout in seconds (default: 60.0)
"""

import asyncio
import logging
import os
import re
import sys
from typing import Dict, List, Any, Optional
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from .api.fpd_client import FPDClient
from .api.field_constants import FPDFields, QueryFieldNames
from .config.field_manager import FieldManager
from .config.settings import Settings
from .config.tool_reflections import get_guidance_section
from .config import api_constants
from .shared.error_utils import (
    format_error_response,
    ValidationError,
    generate_request_id,
    async_tool_error_handler
)
from .shared.internal_auth import mcp_auth
from .proxy.server import generate_enhanced_filename
import httpx
import requests
from pathlib import Path
from datetime import datetime

# Configure comprehensive logging with rotation and security
from .config.log_config import setup_logging
from .util.secure_logger import get_secure_logger

log_manager = setup_logging()
logger = get_secure_logger(__name__)

# Initialize settings to load API keys from secure storage
settings = Settings()

mcp = FastMCP("fpd-mcp")
api_client = FPDClient(api_key=settings.uspto_api_key)

# Register all prompt templates AFTER mcp object is created
# This registers all 10 comprehensive prompt templates with the MCP server
from .prompts import register_prompts
register_prompts(mcp)

# Load field manager with graceful fallback
config_path = Path(__file__).parent.parent.parent / "field_configs.yaml"
try:
    field_manager = FieldManager(config_path)
except Exception as e:
    logger.error(f"Config loading error: {e}. Application will use defaults.")
    # The FieldManager already handles fallback internally, so this is extra protection
    field_manager = FieldManager(config_path)  # This will use defaults

# Global proxy server state
_proxy_server_running = False
_proxy_server_task = None


# =============================================================================
# Utility Functions
# =============================================================================

def get_local_proxy_port() -> int:
    """
    Safely parse local proxy port from environment variables.

    Checks FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic).
    Handles special value "none" which indicates no proxy configured.

    Returns:
        int: Proxy port number (default: 8081)
    """
    port_str = os.getenv('FPD_PROXY_PORT') or os.getenv('PROXY_PORT') or '8081'

    # Handle "none" sentinel value (case-insensitive)
    if port_str.lower() == 'none':
        return 8081

    try:
        return int(port_str)
    except ValueError:
        logger.warning(f"Invalid proxy port value '{port_str}', using default 8081")
        return 8081

# =============================================================================
# GLOBAL ASYNC EXCEPTION HANDLER
# =============================================================================

def handle_async_exception(loop, context):
    """
    Global handler for unhandled asyncio exceptions.

    Prevents silent failures in background tasks (e.g., proxy server crashes).
    Logs all unhandled exceptions with full tracebacks for debugging.

    Args:
        loop: Event loop where exception occurred
        context: Exception context dict with 'exception' and 'message' keys
    """
    exception = context.get("exception")
    message = context.get("message", "Unhandled exception in async task")

    if exception:
        logger.error(
            f"🔥 Unhandled async exception: {message}",
            exc_info=(type(exception), exception, exception.__traceback__)
        )
    else:
        logger.error(f"🔥 Unhandled async exception: {message}")

    # Re-raise critical exceptions
    if isinstance(exception, (KeyboardInterrupt, SystemExit)):
        logger.critical("Critical exception - shutting down")
        sys.exit(1)


def install_async_exception_handler():
    """
    Install global asyncio exception handler.

    Captures unhandled exceptions in background tasks that would otherwise
    fail silently. Must be called during server startup.
    """
    try:
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(handle_async_exception)
        logger.info("✅ Global asyncio exception handler installed")
    except RuntimeError:
        # No event loop yet - will be set when loop starts
        logger.debug("Event loop not ready - exception handler will be set on startup")


def validate_date_range(date_str: str) -> str:
    """Validate date string in YYYY-MM-DD format"""
    if not date_str:
        return None

    # Remove whitespace
    clean_date = date_str.strip()

    # If empty after stripping, return None
    if not clean_date:
        return None

    # Check format YYYY-MM-DD
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', clean_date):
        raise ValidationError("Date must be in YYYY-MM-DD format (e.g., '2024-01-01')", generate_request_id())

    # Validate actual date values
    try:
        datetime.strptime(clean_date, '%Y-%m-%d')
    except ValueError:
        raise ValidationError("Invalid date. Please check year, month, and day values.", generate_request_id())

    # Check reasonable date range (1990 to current year + 5)
    year = int(clean_date[:4])
    current_year = datetime.now().year
    if year < 1990 or year > current_year + 5:
        raise ValidationError(f"Date year must be between 1990 and {current_year + 5}", generate_request_id())

    return clean_date


def validate_string_param(param_name: str, param_value: str, max_length: int = 200) -> str:
    """Validate string parameter input"""
    if not param_value:
        return None

    # Trim whitespace
    clean_value = param_value.strip()

    if not clean_value:
        return None

    # Check length limits
    if len(clean_value) > max_length:
        raise ValidationError(f"{param_name} too long. Maximum {max_length} characters.", generate_request_id())

    # Check for suspicious characters that might indicate injection attempts
    if re.search(r'[<>"\'\\\\/\x00-\x1f]', clean_value):
        raise ValidationError(f"{param_name} contains invalid characters.", generate_request_id())

    return clean_value


def validate_application_number(app_number: str) -> str:
    """Validate and clean USPTO application number format"""
    if not app_number:
        return None

    # Remove whitespace and clean format
    clean_number = app_number.strip().replace("/", "").replace(" ", "")

    if not clean_number:
        return None

    # Basic length validation (USPTO application numbers are typically 8 digits)
    if len(clean_number) < 6 or len(clean_number) > 10:
        raise ValidationError("Application number should be 6-10 digits", generate_request_id())

    # Check if all characters are digits
    if not clean_number.isdigit():
        raise ValidationError("Application number should contain only digits", generate_request_id())

    return clean_number


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

    Returns:
        tuple: (final_query_string, convenience_parameters_used)
    """
    try:
        # Build query from convenience parameters
        query_parts = []
        convenience_params_used = {}

        # Include base query if provided
        if query and query.strip():
            query_parts.append(f"({query})")
            convenience_params_used["base_query"] = query

        # Add minimal tier convenience parameters
        if applicant_name:
            validated_name = validate_string_param("applicant_name", applicant_name)
            if validated_name:
                query_parts.append(f'{QueryFieldNames.APPLICANT_NAME}:"{validated_name}"')
                convenience_params_used["applicant_name"] = validated_name

        if application_number:
            validated_app = validate_application_number(application_number)
            if validated_app:
                query_parts.append(f"{QueryFieldNames.APPLICATION_NUMBER}:{validated_app}")
                convenience_params_used["application_number"] = validated_app

        if patent_number:
            validated_patent = validate_string_param("patent_number", patent_number, 15)
            if validated_patent:
                query_parts.append(f"{QueryFieldNames.PATENT_NUMBER}:{validated_patent}")
                convenience_params_used["patent_number"] = validated_patent

        if decision_type:
            validated_decision = validate_string_param("decision_type", decision_type, 50)
            if validated_decision:
                query_parts.append(f"{QueryFieldNames.DECISION_TYPE}:{validated_decision}")
                convenience_params_used["decision_type"] = validated_decision

        if deciding_office:
            validated_office = validate_string_param("deciding_office", deciding_office)
            if validated_office:
                query_parts.append(f'{FPDFields.FINAL_DECIDING_OFFICE_NAME}:"{validated_office}"')
                convenience_params_used["deciding_office"] = validated_office

        # Date range filters
        if petition_date_start or petition_date_end:
            start = validate_date_range(petition_date_start) if petition_date_start else "*"
            end = validate_date_range(petition_date_end) if petition_date_end else "*"
            if start != "*" or end != "*":
                query_parts.append(f"{QueryFieldNames.PETITION_MAIL_DATE}:[{start} TO {end}]")
                convenience_params_used["petition_date_range"] = f"{start} TO {end}"

        if decision_date_start or decision_date_end:
            start = validate_date_range(decision_date_start) if decision_date_start else "*"
            end = validate_date_range(decision_date_end) if decision_date_end else "*"
            if start != "*" or end != "*":
                query_parts.append(f"{QueryFieldNames.DECISION_DATE}:[{start} TO {end}]")
                convenience_params_used["decision_date_range"] = f"{start} TO {end}"

        # Add balanced tier additional parameters (only if allowed)
        if allow_balanced_params:
            if petition_type_code:
                validated_type = validate_string_param("petition_type_code", petition_type_code, 10)
                if validated_type:
                    query_parts.append(f"{FPDFields.DECISION_PETITION_TYPE_CODE}:{validated_type}")
                    convenience_params_used["petition_type_code"] = validated_type

            if art_unit:
                validated_art_unit = validate_string_param("art_unit", art_unit, 10)
                if validated_art_unit:
                    query_parts.append(f"{QueryFieldNames.ART_UNIT}:{validated_art_unit}")
                    convenience_params_used["art_unit"] = validated_art_unit

            if technology_center:
                validated_tc = validate_string_param("technology_center", technology_center, 10)
                if validated_tc:
                    query_parts.append(f"{QueryFieldNames.TECHNOLOGY_CENTER}:{validated_tc}")
                    convenience_params_used["technology_center"] = validated_tc

            if prosecution_status:
                validated_status = validate_string_param("prosecution_status", prosecution_status)
                if validated_status:
                    query_parts.append(f'{QueryFieldNames.PROSECUTION_STATUS}:"{validated_status}"')
                    convenience_params_used["prosecution_status"] = validated_status

            if entity_status:
                validated_entity = validate_string_param("entity_status", entity_status, 50)
                if validated_entity:
                    query_parts.append(f'{QueryFieldNames.BUSINESS_ENTITY}:"{validated_entity}"')
                    convenience_params_used["entity_status"] = validated_entity
        else:
            # Check if balanced-only parameters were provided but not allowed
            balanced_only_params = [petition_type_code, art_unit, technology_center, prosecution_status, entity_status]
            provided_balanced_params = [p for p in balanced_only_params if p is not None]
            if provided_balanced_params:
                raise ValidationError(
                    "Parameters petition_type_code, art_unit, technology_center, prosecution_status, "
                    "and entity_status are only available in fpd_search_petitions_balanced. "
                    "Use fpd_search_petitions_balanced for advanced filtering.",
                    generate_request_id()
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


@mcp.tool(name="Search_petitions_minimal")
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
    if len(final_query) > 2000:
        raise ValidationError("Combined query too long (max 2000 characters)", generate_request_id())

    # Get fields from field manager
    fields = field_manager.get_fields("petitions_minimal")

    # Search petitions
    result = await api_client.search_petitions(
        query=final_query,
        fields=fields,
        limit=limit,
        offset=offset
    )

    # Check for errors
    if "error" in result:
        return result

    # Filter response using field manager
    filtered_result = field_manager.filter_response(result, "petitions_minimal")

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


@mcp.tool(name="Search_petitions_balanced")
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
- patentNumber -> ptab_search_proceedings_minimal(patent_number=X)
- groupArtUnitNumber -> pfw_search_applications_minimal(art_unit=X, fields=[...])
- firstApplicantName -> Match parties across PFW/PTAB MCPs"""
    try:
        # Input validation
        if limit < 1 or limit > 50:
            return format_error_response("Limit must be between 1 and 50", 400)
        if offset < 0:
            return format_error_response("Offset must be non-negative", 400)

        # Build query from convenience parameters
        try:
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
        except ValueError as e:
            return format_error_response(str(e), 400)

        # Additional query length validation
        if len(final_query) > 2000:
            return format_error_response("Combined query too long (max 2000 characters)", 400)

        # Get fields from field manager
        fields = field_manager.get_fields("petitions_balanced")

        # Search petitions
        result = await api_client.search_petitions(
            query=final_query,
            fields=fields,
            limit=limit,
            offset=offset
        )

        # Check for errors
        if "error" in result:
            return result

        # Filter response using field manager
        filtered_result = field_manager.filter_response(result, "petitions_balanced")

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
                "ptab_challenges": "ptab_search_proceedings_minimal(patent_number=X) if patentNumber present",
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

    except ValueError as e:
        logger.warning(f"Validation error in balanced search: {str(e)}")
        return format_error_response(str(e), 400)
    except httpx.HTTPStatusError as e:
        logger.error(f"API error in balanced search: {e.response.status_code} - {e.response.text}")
        return format_error_response(f"API error: {e.response.text}", e.response.status_code)
    except httpx.TimeoutException as e:
        logger.error(f"API timeout in balanced search: {str(e)}")
        return format_error_response("Request timeout - please try again", 408)
    except Exception as e:
        logger.error(f"Unexpected error in balanced search: {str(e)}")
        return format_error_response(f"Internal error: {str(e)}", 500)


@mcp.tool(name="Search_petitions_by_art_unit")
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
    try:
        # Input validation
        if not art_unit or len(art_unit.strip()) == 0:
            return format_error_response("Art unit cannot be empty", 400)
        if limit < api_constants.MIN_SEARCH_LIMIT or limit > api_constants.MAX_SEARCH_LIMIT:
            return format_error_response(f"Limit must be between {api_constants.MIN_SEARCH_LIMIT} and {api_constants.MAX_SEARCH_LIMIT}", 400)
        if date_range:
            # Basic date range format validation
            parts = date_range.split(":")
            if len(parts) != 2:
                return format_error_response(
                    "Date range must be in format YYYY-MM-DD:YYYY-MM-DD", 400
                )

        # Use API client's search_by_art_unit method
        result = await api_client.search_by_art_unit(
            art_unit=art_unit,
            date_range=date_range,
            limit=limit
        )

        # Check for errors
        if "error" in result:
            return result

        # Filter response using balanced field set
        fields = field_manager.get_fields("petitions_balanced")
        filtered_result = field_manager.filter_response(result, "petitions_balanced")

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

    except ValueError as e:
        logger.warning(f"Validation error in art unit search: {str(e)}")
        return format_error_response(str(e), 400)
    except httpx.HTTPStatusError as e:
        logger.error(f"API error in art unit search: {e.response.status_code} - {e.response.text}")
        return format_error_response(f"API error: {e.response.text}", e.response.status_code)
    except httpx.TimeoutException as e:
        logger.error(f"API timeout in art unit search: {str(e)}")
        return format_error_response("Request timeout - please try again", 408)
    except Exception as e:
        logger.error(f"Unexpected error in art unit search: {str(e)}")
        return format_error_response(f"Internal error: {str(e)}", 500)


@mcp.tool(name="Search_petitions_by_application")
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
    try:
        # Input validation
        if not application_number or len(application_number.strip()) == 0:
            return format_error_response("Application number cannot be empty", 400)

        # Clean application number (remove spaces, slashes for query)
        clean_app_num = application_number.replace("/", "").replace(" ", "")

        # Use API client's search_by_application method
        result = await api_client.search_by_application(
            application_number=clean_app_num,
            include_documents=include_documents
        )

        # Check for errors
        if "error" in result:
            return result

        # Filter response using balanced field set (unless documents requested)
        if not include_documents:
            filtered_result = field_manager.filter_response(result, "petitions_balanced")
        else:
            # With documents, don't filter (user requested full data)
            filtered_result = result

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
                "step_4": "If patented, use ptab_search_proceedings_minimal to check PTAB challenges"
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

    except ValueError as e:
        logger.warning(f"Validation error in application search: {str(e)}")
        return format_error_response(str(e), 400)
    except httpx.HTTPStatusError as e:
        logger.error(f"API error in application search: {e.response.status_code} - {e.response.text}")
        return format_error_response(f"API error: {e.response.text}", e.response.status_code)
    except httpx.TimeoutException as e:
        logger.error(f"API timeout in application search: {str(e)}")
        return format_error_response("Request timeout - please try again", 408)
    except Exception as e:
        logger.error(f"Unexpected error in application search: {str(e)}")
        return format_error_response(f"Internal error: {str(e)}", 500)


@mcp.tool(name="Get_petition_details")
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
    try:
        # Input validation
        if not petition_id or len(petition_id.strip()) == 0:
            return format_error_response("Petition ID cannot be empty", 400)

        # Use API client's get_petition_by_id method
        result = await api_client.get_petition_by_id(
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

    except ValueError as e:
        logger.warning(f"Validation error in get petition details: {str(e)}")
        return format_error_response(str(e), 400)
    except httpx.HTTPStatusError as e:
        logger.error(f"API error in get petition details: {e.response.status_code} - {e.response.text}")
        return format_error_response(f"API error: {e.response.text}", e.response.status_code)
    except httpx.TimeoutException as e:
        logger.error(f"API timeout in get petition details: {str(e)}")
        return format_error_response("Request timeout - please try again", 408)
    except Exception as e:
        logger.error(f"Unexpected error in get petition details: {str(e)}")
        return format_error_response(f"Internal error: {str(e)}", 500)


@mcp.tool(name="FPD_get_document_download")
@async_tool_error_handler("document_download")
async def fpd_get_document_download(
    petition_id: str,
    document_identifier: str,
    proxy_port: Optional[int] = None,
    generate_persistent_link: bool = True
) -> Dict[str, Any]:
    """Generate browser-accessible download URL for petition documents (PDFs) via secure proxy.

**ALWAYS-ON PROXY (DEFAULT):** Proxy server starts with MCP - download links work immediately.

**Workflow:**
1. fpd_get_petition_details(petition_id='uuid', include_documents=True) → get documentBag
2. fpd_get_document_download(petition_id='uuid', document_identifier='ABC123') → get download link
3. Provide download link to user

**CRITICAL RESPONSE FORMAT - Always format with BOTH clickable link and raw URL:**
**📁 [Download {DocumentType} ({PageCount} pages)]({proxy_url})** | Raw URL: `{proxy_url}`

Why both formats?
- Clickable links work in Claude Desktop and most clients
- Raw URLs enable copy/paste in Msty and other clients where links aren't clickable

**Document types:**
- Petition document: Original petition filed with USPTO
- Decision document: Director's final decision
- Supporting exhibits: Declarations, prior art, technical documents

**Parameters:**
- petition_id: Petition UUID from search results
- document_identifier: Document identifier from documentBag
- proxy_port: Optional (defaults to FPD_PROXY_PORT env var or 8081)
- generate_persistent_link: Generate 7-day persistent link (default: True)
  - True: Attempts persistent link via USPTO PFW MCP (works across MCP restarts)
  - False: Session-based link (works while MCP running, no PFW required)"""
    try:
        # Input validation
        if not petition_id or len(petition_id.strip()) == 0:
            return format_error_response("Petition ID cannot be empty", 400)
        if not document_identifier or len(document_identifier.strip()) == 0:
            return format_error_response("Document identifier cannot be empty", 400)

        # Handle persistent link generation (requires PFW MCP)
        if generate_persistent_link:
            centralized_port = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()

            if centralized_port and centralized_port != 'none':
                # PFW centralized proxy detected - forward to PFW for persistent link
                try:
                    pfw_port = int(centralized_port)
                    logger.info(f"Generating persistent link via centralized USPTO PFW proxy (port {pfw_port})")

                    # Construct persistent link request to PFW proxy
                    # PFW proxy should have an endpoint for generating persistent links
                    # Format: POST http://localhost:8080/persistent-link
                    persistent_link_url = f"http://localhost:{pfw_port}/persistent-link"

                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            persistent_link_url,
                            json={
                                "source": "fpd",
                                "petition_id": petition_id,
                                "document_identifier": document_identifier,
                                "expires_days": 7
                            },
                            timeout=30.0
                        )

                        if response.status_code == 200:
                            result = response.json()
                            return {
                                "success": True,
                                "persistent_download_url": result.get("persistent_url"),
                                "expires_in_days": 7,
                                "note": "Generated via centralized USPTO PFW proxy - works across MCP restarts",
                                "ecosystem_integration": "Using PFW centralized database for persistent links"
                            }
                        else:
                            # PFW proxy doesn't support persistent links yet
                            logger.warning(f"PFW proxy persistent link generation failed: {response.status_code}")
                            # Fall through to immediate link with note

                except Exception as e:
                    logger.warning(f"Failed to generate persistent link via PFW: {e}")
                    # Fall through to immediate link with note

            # No centralized proxy or persistent link generation failed
            # Return helpful message encouraging PFW installation
            if not centralized_port:
                return {
                    "success": False,
                    "error": "Persistent links require USPTO PFW MCP for centralized database",
                    "suggestion": "Install USPTO PFW MCP for persistent links, or use immediate links (generate_persistent_link=false)",
                    "immediate_alternative": f"Call this tool with generate_persistent_link=false for session-based download link",
                    "pfw_benefits": [
                        "7-day persistent encrypted links (work across MCP restarts)",
                        "Centralized proxy server (unified rate limiting)",
                        "Cross-MCP document sharing and caching",
                        "Complete USPTO prosecution + petition workflow"
                    ],
                    "note": "FPD provides immediate downloads only - PFW provides persistent links + enhanced features",
                    "recommendation": "Install both USPTO FPD + PFW MCPs for complete patent lifecycle analysis"
                }
            else:
                # PFW is available but persistent link generation failed - fallback to immediate link
                logger.info("Persistent link generation not available, falling back to immediate link")

        # Enhanced proxy port detection with centralized proxy support
        if proxy_port is None:
            # Check if centralized proxy is available (and not "none")
            centralized_port = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()
            if centralized_port and centralized_port != 'none':
                proxy_port = int(centralized_port)
                logger.info(f"Using centralized USPTO proxy on port {proxy_port}")
            else:
                # Check FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
                proxy_port = get_local_proxy_port()
                logger.info(f"Using local FPD proxy on port {proxy_port}")

        # Start proxy server if not already running (unless using centralized proxy)
        centralized_port_check = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()
        if not centralized_port_check or centralized_port_check == 'none':
            await _ensure_proxy_server_running(proxy_port)
        else:
            # Centralized proxy is already running (managed by PFW MCP)
            logger.info("Using centralized proxy - no local proxy startup needed")

        # Construct proxy URL (port 8081 to avoid conflict with PFW proxy on 8080)
        proxy_url = f"http://localhost:{proxy_port}/download/{petition_id}/{document_identifier}"

        # Also construct direct API URL for reference
        direct_url = f"{api_client.base_url}/{petition_id}/documents/{document_identifier}"

        # Get petition details to find document metadata
        petition_result = await api_client.get_petition_by_id(petition_id, include_documents=True)

        if "error" in petition_result:
            return petition_result

        # Extract from nested structure
        petition_data = petition_result.get(FPDFields.PETITION_DECISION_DATA_BAG, [])
        if not petition_data:
            return format_error_response("Petition data not found", 404)

        # Get documentBag from first petition in array
        documents = petition_data[0].get(FPDFields.DOCUMENT_BAG, [])

        # Find document metadata
        document_metadata = None
        for doc in documents:
            if doc.get(FPDFields.DOCUMENT_IDENTIFIER) == document_identifier:
                document_metadata = doc
                break

        if not document_metadata:
            return format_error_response(
                f"Document {document_identifier} not found in petition {petition_id}", 404
            )

        # Track if centralized proxy registration succeeds
        centralized_registration_success = False

        # Register document with centralized proxy if using PFW
        # Check if CENTRALIZED_PROXY_PORT is set and not "none"
        centralized_port_env = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()
        if centralized_port_env and centralized_port_env != 'none':
            # Extract PDF download URL from document metadata
            download_options = document_metadata.get(FPDFields.DOWNLOAD_OPTION_BAG, [])
            pdf_download_url = None

            for option in download_options:
                if option.get(FPDFields.MIME_TYPE_IDENTIFIER) == 'PDF':
                    pdf_download_url = option.get(FPDFields.DOWNLOAD_URL)
                    break

            if pdf_download_url:
                # Extract metadata for enhanced filename generation
                petition_mail_date = petition_data[0].get(FPDFields.PETITION_MAIL_DATE)
                app_number = petition_data[0].get(FPDFields.APPLICATION_NUMBER_TEXT)
                patent_number = petition_data[0].get(FPDFields.PATENT_NUMBER)
                doc_description = document_metadata.get(FPDFields.DOCUMENT_CODE_DESCRIPTION_TEXT)
                doc_code = document_metadata.get(FPDFields.DOCUMENT_CODE)

                # Generate enhanced filename using local proxy logic
                enhanced_filename = generate_enhanced_filename(
                    petition_mail_date=petition_mail_date,
                    app_number=app_number,
                    patent_number=patent_number,
                    document_description=doc_description,
                    document_code=doc_code,
                    max_desc_length=40
                )

                logger.info(f"Generated enhanced filename for PFW registration: {enhanced_filename}")

                try:
                    # Register FPD document with PFW centralized proxy
                    # Use the already validated centralized_port_env variable
                    pfw_port = int(centralized_port_env)
                    register_url = f"http://localhost:{pfw_port}/register-fpd-document"

                    # Create secure token for document access
                    access_token = mcp_auth.create_document_access_token(
                        petition_id=petition_id,
                        document_identifier=document_identifier,
                        application_number=app_number
                    )

                    async with httpx.AsyncClient() as client:
                        response_reg = await client.post(
                            register_url,
                            json={
                                "source": "fpd",
                                "petition_id": petition_id,
                                "document_identifier": document_identifier,
                                "download_url": pdf_download_url,
                                "access_token": access_token,  # Secure token instead of raw API key
                                "application_number": app_number,
                                "enhanced_filename": enhanced_filename  # Professional filename for downloads
                            },
                            timeout=5.0
                        )

                        if response_reg.status_code == 200:
                            logger.info(f"✅ Successfully registered FPD document with centralized proxy")
                            centralized_registration_success = True
                        else:
                            logger.warning(
                                f"❌ Failed to register document with centralized proxy: HTTP {response_reg.status_code}"
                            )
                            try:
                                error_detail = response_reg.json()
                                logger.warning(f"   Registration error details: {error_detail}")
                            except Exception:
                                logger.warning(f"   Response body: {response_reg.text[:500]}")

                except Exception as e:
                    logger.warning(f"❌ Failed to register document with centralized proxy: {e}")

        # Implement fallback: if centralized registration failed, use local proxy
        # Only applies if we actually tried to use centralized proxy (not "none")
        centralized_port_check = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()
        if centralized_port_check and centralized_port_check != 'none' and not centralized_registration_success:
            logger.warning("⚠️  Centralized proxy registration failed - falling back to local FPD proxy")
            # Start local proxy as fallback
            local_proxy_port = get_local_proxy_port()
            await _ensure_proxy_server_running(local_proxy_port)
            # Update proxy URL to use local proxy
            proxy_url = f"http://localhost:{local_proxy_port}/download/{petition_id}/{document_identifier}"
            logger.info(f"🔄 Using local FPD proxy on port {local_proxy_port} for this download")

        # Determine proxy type for response metadata
        centralized_port_check = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()
        proxy_type = "centralized" if (centralized_port_check and centralized_port_check != 'none' and centralized_registration_success) else "local"
        proxy_port_used = proxy_port if proxy_type == "centralized" else get_local_proxy_port()

        # Build response with LLM guidance for clickable links
        response = {
            "success": True,
            "petition_id": petition_id,
            "document_identifier": document_identifier,
            "proxy_download_url": proxy_url,
            "direct_url": direct_url,
            "document_info": document_metadata,

            # Proxy information for debugging
            "proxy_info": {
                "type": proxy_type,
                "port": proxy_port_used,
                "status": "centralized_registered" if centralized_registration_success else "local_fallback"
            },

            # NEW: Explicit LLM guidance for proper response formatting
            "llm_response_guidance": {
                "critical_requirement": "ALWAYS provide BOTH clickable markdown link AND raw URL",
                "required_format": f"**📁 [Download {document_metadata.get('documentFileName', 'Document')} ({document_metadata.get('pageCount', 'N/A')} pages)]({proxy_url})** | Raw URL: `{proxy_url}`",
                "user_expectation": "User requested a download - they need immediate browser access to the PDF",
                "wrong_response": "Don't just show the raw URL or tool results",
                "correct_response": "Format as clickable markdown link with document description and page count PLUS raw URL for copy/paste",
                "explanation": "Clickable link works in Claude Desktop, raw URL enables copy/paste in Msty and other clients where links aren't clickable"
            },

            "access_instructions": {
                "method": "Proxy server download (recommended) or direct API access",
                "proxy_url": f"{proxy_url} - Click to download via secure proxy",
                "proxy_port": proxy_port_used,
                "proxy_note": f"Proxy handles USPTO API authentication ({proxy_type} proxy on port {proxy_port_used})",
                "rate_limit": "USPTO allows 5 downloads per 10 seconds",
                "file_type": "PDF document",
                "estimated_size": f"{document_metadata.get('pageCount', 'unknown')} pages"
            },

            "llm_guidance": {
                "next_steps": [
                    f"Present proxy download URL to user: ** [Download {document_metadata.get('documentFileName', 'Document')} ({document_metadata.get('pageCount', 'unknown')} pages)]({proxy_url})**",
                    "Proxy server is now running on port 8081 (started automatically)",
                    "User can click the link to download PDF directly through secure proxy",
                    "Proxy server handles USPTO API authentication automatically"
                ],
                "document_context": {
                    "petition_type": petition_data[0].get(FPDFields.DECISION_PETITION_TYPE_CODE_DESCRIPTION_TEXT, "Unknown"),
                    "decision_outcome": petition_data[0].get(FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT, "Unknown"),
                    "decision_date": petition_data[0].get(FPDFields.DECISION_DATE, "Unknown")
                }
            },

            # Critical UX reminder
            "ux_critical": "The user wants this PDF file - make the download link immediately clickable!",

            # Response validation hints
            "response_validation": {
                "check_for_markdown_link": "Response should contain [text](url) format",
                "check_for_clickable_emoji": "Should start with  emoji for visual recognition",
                "check_for_description": "Link text should describe the document type and page count",
                "success_pattern": f"** [Download {document_metadata.get('documentFileName', 'DocumentType')} ({document_metadata.get('pageCount', 'N')} pages)](http://localhost:{proxy_port}/download/...)**"
            }
        }

        return response

    except ValueError as e:
        logger.warning(f"Validation error in get document download: {str(e)}")
        return format_error_response(str(e), 400)
    except httpx.HTTPStatusError as e:
        logger.error(f"API error in get document download: {e.response.status_code} - {e.response.text}")
        return format_error_response(f"API error: {e.response.text}", e.response.status_code)
    except httpx.TimeoutException as e:
        logger.error(f"API timeout in get document download: {str(e)}")
        return format_error_response("Request timeout - please try again", 408)
    except Exception as e:
        logger.error(f"Unexpected error in get document download: {str(e)}")
        return format_error_response(f"Internal error: {str(e)}", 500)


@mcp.tool(name="FPD_get_document_content_with_mistral_ocr")
@async_tool_error_handler("document_content")
async def fpd_get_document_content(
    petition_id: str,
    document_identifier: str,
    auto_optimize: bool = True
) -> Dict[str, Any]:
    """Extract full text from USPTO petition documents with intelligent hybrid extraction (PyPDF2 first, Mistral OCR fallback).

PREREQUISITE: First use fpd_get_petition_details to get document_identifier from documentBag.
Auto-optimizes cost: free PyPDF2 for text-based PDFs, ~$0.001/page Mistral OCR only for scanned documents.
MISTRAL_API_KEY is optional - without it, only PyPDF2 extraction is available (works well for text-based PDFs).

USE CASES:
- Analyze petition legal arguments and Director's reasoning
- Extract petition issues, CFR rules cited, statutory references
- Detect patterns across multiple petitions (e.g., common denial reasons)
- Correlate petition text with PTAB challenge strategies
- Profile examiner behavior from supervisory review petitions

COST OPTIMIZATION:
- auto_optimize=True (default): Try free PyPDF2 first, fallback to Mistral OCR if needed (70% cost savings)
- auto_optimize=False: Use Mistral OCR directly (~$0.001/page)

Returns: extracted_content, extraction_method, processing_cost_usd, page_count

Example workflow:
1. fpd_get_petition_details(petition_id='0b71b685-...', include_documents=True)
2. fpd_get_document_content(petition_id='0b71b685-...', document_identifier='DSEN5APWPHOENIX')
3. Analyze extracted text for legal arguments, issues, and patterns

For document selection strategies and cost optimization, use FPD_get_guidance('cost')."""
    try:
        # Input validation
        if not petition_id or len(petition_id.strip()) == 0:
            return format_error_response("Petition ID cannot be empty", 400)
        if not document_identifier or len(document_identifier.strip()) == 0:
            return format_error_response("Document identifier cannot be empty", 400)

        # Enhanced proxy port detection with centralized proxy support
        centralized_port = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()
        if centralized_port and centralized_port != 'none':
            proxy_port = int(centralized_port)
            logger.info(f"Using centralized USPTO proxy on port {proxy_port} for extraction")
        else:
            # Check FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
            proxy_port = get_local_proxy_port()
            logger.info(f"Using local FPD proxy on port {proxy_port} for extraction")

        # Start proxy server if not already running (unless using centralized proxy)
        if not centralized_port or centralized_port == 'none':
            await _ensure_proxy_server_running(proxy_port)
            logger.info(f"Local proxy server ready on port {proxy_port} for document extraction")
        else:
            logger.info("Using centralized proxy for document extraction - no local proxy startup needed")

        # Use API client's hybrid extraction method
        result = await api_client.extract_document_content_hybrid(
            petition_id=petition_id,
            document_identifier=document_identifier,
            auto_optimize=auto_optimize
        )

        # Check for errors
        if "error" in result:
            return result

        # Add LLM guidance for text analysis
        result["llm_guidance"] = {
            "analysis_strategies": {
                "legal_argument_analysis": {
                    "description": "Analyze petition and decision text for legal reasoning",
                    "action": "Extract key arguments, Director's reasoning, legal citations"
                },
                "pattern_detection": {
                    "description": "Compare text across multiple petitions to find common themes",
                    "action": "Identify recurring denial reasons, successful argument patterns"
                },
                "cross_mcp_correlation": {
                    "description": "Correlate petition arguments with PTAB challenges",
                    "action": "Compare legal reasoning with PTAB IPR/PGR arguments"
                },
                "examiner_profiling": {
                    "description": "Analyze supervisory review petitions to profile examiner behavior",
                    "action": "Extract what examiner actions were challenged and Director's response"
                }
            },
            "extraction_quality": {
                "method": result.get("extraction_method", "Unknown"),
                "cost": f"${result.get('processing_cost_usd', 0):.4f}",
                "optimization": result.get("auto_optimization", "Unknown")
            },
            "next_steps": [
                "Analyze extracted content for key legal arguments",
                "Search for CFR citations (e.g., '37 CFR 1.137', '37 CFR 1.181')",
                "Identify petition outcome reasoning in decision text",
                "Cross-reference with PFW prosecution history for context",
                "Compare with PTAB challenge arguments if patent granted"
            ]
        }

        return result

    except ValueError as e:
        logger.warning(f"Validation error in extract document content: {str(e)}")
        return format_error_response(str(e), 400)
    except httpx.HTTPStatusError as e:
        logger.error(f"API error in extract document content: {e.response.status_code} - {e.response.text}")
        return format_error_response(f"API error: {e.response.text}", e.response.status_code)
    except httpx.TimeoutException as e:
        logger.error(f"API timeout in extract document content: {str(e)}")
        return format_error_response("Request timeout - please try again", 408)
    except Exception as e:
        logger.error(f"Unexpected error in extract document content: {str(e)}")
        return format_error_response(f"Internal error: {str(e)}", 500)


@mcp.tool(name="FPD_get_guidance")
async def fpd_get_guidance(section: str = "overview") -> str:
    """Get selective USPTO FPD guidance sections for context-efficient workflows.

🎯 QUICK REFERENCE - What section for your question?

🔍 "Find petitions by company/art unit" → tools
🚩 "Identify petition red flags" → red_flags
📄 "Download petition documents" → documents
🤝 "Correlate petitions with prosecution" → workflows_pfw
⚖️ "Analyze petition + PTAB patterns" → workflows_ptab
📊 "Citation quality + petition correlation" → workflows_citations
🏢 "Complete portfolio due diligence" → workflows_complete
📚 "Research CFR rules with Assistant" → workflows_assistant
🎯 "Ultra-minimal PFW + FPD workflows" → ultra_context
💰 "Reduce extraction costs" → cost

Available sections:
- overview: Available sections and MCP overview (default)
- workflows_pfw: FPD + PFW integration workflows
- workflows_ptab: FPD + PTAB integration workflows
- workflows_citations: FPD + Citations integration workflows
- workflows_complete: Four-MCP complete lifecycle analysis
- workflows_assistant: Pinecone Assistant + FPD research workflows
- tools: Tool catalog, progressive disclosure, parameters
- red_flags: Petition red flag indicators and CFR rules
- documents: Document extraction, downloads, proxy configuration
- ultra_context: PFW fields parameter + ultra-minimal workflows
- cost: Cost optimization for document extraction

Context Efficiency Benefits:
- 80-95% token reduction (2-8KB per section vs 62KB total)
- Targeted guidance for specific workflows
- Same comprehensive content organized for efficiency
- Consistent pattern with PFW MCP"""
    try:
        return get_guidance_section(section)
    except Exception as e:
        logger.error(f"Unexpected error in get guidance: {str(e)}")
        return f"Error: Internal error - {str(e)}"


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================
# All 10 comprehensive prompt templates have been moved to src/fpd_mcp/prompts/
# and are automatically registered via the `from . import prompts` statement above.
#
# Available prompts:
# - company_petition_risk_assessment_pfw
# - art_unit_quality_assessment
# - revival_petition_analysis
# - petition_document_research_package
# - complete_portfolio_due_diligence_pfw_ptab
# - litigation_research_setup_pfw
# - prosecution_quality_correlation_pfw
# - patent_vulnerability_assessment_ptab
# - petition_quality_with_citation_intelligence
# - examiner_dispute_citation_analysis
#
# See prompts/__init__.py for full documentation.
# =============================================================================


# =============================================================================
# PROXY SERVER HELPER FUNCTIONS
# =============================================================================

async def _ensure_proxy_server_running(port: int = 8081):
    """Ensure the proxy server is running (auto-start on first download)"""
    global _proxy_server_running, _proxy_server_task

    if not _proxy_server_running:
        logger.info(f"Starting HTTP proxy server on port {port}")

        # Wrap background task with exception handler
        async def safe_proxy_runner():
            try:
                await _run_proxy_server(port)
            except Exception as e:
                logger.error(f"Proxy server crashed: {e}", exc_info=True)
                global _proxy_server_running
                _proxy_server_running = False
                # Allow graceful degradation - main server continues without proxy

        _proxy_server_task = asyncio.create_task(safe_proxy_runner())
        _proxy_server_running = True
        # Give the server a moment to start
        await asyncio.sleep(0.5)
        logger.info(f"Proxy server started successfully on port {port}")


async def _run_proxy_server(port: int = 8081):
    """Run the FastAPI proxy server

    Uses API key from Settings (which may come from secure storage or environment variables)
    """
    try:
        import uvicorn
        from .proxy.server import create_proxy_app

        # Pass API key and port from Settings to proxy server
        # This allows proxy to work with secure storage (Windows DPAPI)
        app = create_proxy_app(api_key=settings.uspto_api_key, port=port)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False  # Reduce noise in logs
        )
        server = uvicorn.Server(config)
        logger.info(f"HTTP proxy server starting on http://127.0.0.1:{port}")
        await server.serve()

    except Exception as e:
        global _proxy_server_running
        _proxy_server_running = False
        logger.error(f"Proxy server failed: {e}")
        raise


async def run_hybrid_server(enable_always_on: bool = True, proxy_port: int = 8081):
    """Run both MCP server and HTTP proxy server concurrently

    Args:
        enable_always_on: If True, start proxy immediately (default). If False, use on-demand startup.
        proxy_port: Port for the HTTP proxy server (default: 8081)
    """
    try:
        global _proxy_server_running, _proxy_server_task

        # Start both servers concurrently
        logger.info("Starting hybrid FPD MCP + HTTP proxy server")

        # Run MCP server in a separate task
        mcp_task = asyncio.create_task(
            asyncio.to_thread(lambda: mcp.run(transport='stdio'))
        )

        # Start proxy server immediately if always-on mode is enabled
        if enable_always_on:
            logger.info(f"Always-on mode: Starting HTTP proxy server immediately on port {proxy_port}")
            _proxy_server_task = asyncio.create_task(_run_proxy_server(proxy_port))
            _proxy_server_running = True
            # Brief wait to ensure server starts cleanly
            await asyncio.sleep(0.5)
            logger.info(f"Proxy server started successfully on port {proxy_port}")
        else:
            # Legacy on-demand mode: proxy starts on first download request
            logger.info(f"On-demand mode: Proxy will start on first document request (port {proxy_port})")

        # Wait for MCP server to complete (it runs indefinitely)
        await mcp_task

    except KeyboardInterrupt:
        logger.info("Shutting down servers...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


def _detect_pfw_proxy() -> Optional[int]:
    """
    Detect if USPTO PFW MCP proxy is available for centralized document downloads

    Uses environment variable CENTRALIZED_PROXY_PORT for instant detection:
    - Not set or "none": Skip HTTP checks entirely (instant startup)
    - Set to valid port: Use that port directly
    - Fallback: HTTP probe with retry logic for race conditions

    Returns:
        Port number if PFW proxy is available, None otherwise
    """
    logger.info("🔍 Checking for centralized USPTO PFW MCP proxy...")

    import time
    import requests

    # INSTANT DETECTION: Check environment variable first
    # PFW MCP sets CENTRALIZED_PROXY_PORT when it starts its proxy server
    # If not set or set to sentinel value "none", PFW is not installed
    centralized_port_env = os.getenv("CENTRALIZED_PROXY_PORT", "none").lower()

    if centralized_port_env == "none":
        # PFW explicitly not installed - skip all HTTP checks (instant startup)
        logger.info("ℹ️  Standalone mode: Using local FPD proxy (always-on)")
        logger.info("   💡 Install USPTO PFW MCP for enhanced features:")
        logger.info("      - Persistent download links (7-day encrypted URLs)")
        logger.info("      - Centralized proxy (unified rate limiting)")
        logger.info("      - Cross-MCP document sharing and caching")
        logger.info("   📦 Get it at: https://github.com/johnwalkoe/patent_filewrapper_mcp")
        return None

    # If port is explicitly set, try it first
    if centralized_port_env.isdigit():
        explicit_port = int(centralized_port_env)
        try:
            response = requests.get(f"http://localhost:{explicit_port}/", timeout=0.3)
            if response.status_code == 200:
                logger.info("🎯 SUCCESS: Using centralized USPTO proxy ecosystem")
                logger.info(f"   ✅ Detected PFW proxy on port {explicit_port} (via CENTRALIZED_PROXY_PORT)")
                logger.info("   ✅ Persistent links available")
                logger.info("   ✅ Enhanced rate limiting")
                logger.info("   ✅ Cross-MCP document sharing")
                return explicit_port
        except Exception:
            logger.warning(f"   ⚠️  CENTRALIZED_PROXY_PORT={explicit_port} set but proxy not responding")

    # Optimized retry configuration for fast startup when PFW is not installed
    # - 2 attempts (down from 3) to reduce delay when PFW is absent
    # - 0.3s timeout (down from 1s) for faster localhost detection
    # - 0.5s retry delay (down from 1s) for quicker fallback
    # - Alternative ports only checked on final attempt
    max_retries = 2
    retry_delay = 0.5  # seconds
    timeout = 0.3  # seconds - localhost should respond instantly if present

    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"   Retry {attempt}/{max_retries-1} (waiting for PFW proxy to start)...")
            time.sleep(retry_delay)

        # Check if PFW proxy is running on port 8080 (primary port)
        try:
            pfw_port = 8080
            response = requests.get(f"http://localhost:{pfw_port}/", timeout=timeout)
            if response.status_code == 200:
                logger.info("🎯 SUCCESS: Using centralized USPTO proxy ecosystem")
                logger.info(f"   ✅ Detected PFW proxy on port {pfw_port}")
                logger.info("   ✅ Persistent links available")
                logger.info("   ✅ Enhanced rate limiting")
                logger.info("   ✅ Cross-MCP document sharing")
                return pfw_port
        except Exception:
            pass

        # Only check alternative ports on final attempt (to minimize startup delay)
        if attempt == max_retries - 1:
            for alt_port in [8079, 8082, 8083]:
                try:
                    response = requests.get(f"http://localhost:{alt_port}/", timeout=timeout)
                    if response.status_code == 200:
                        logger.info("🎯 SUCCESS: Using centralized USPTO proxy ecosystem")
                        logger.info(f"   ✅ Detected PFW proxy on port {alt_port}")
                        logger.info("   ✅ Persistent links available")
                        logger.info("   ✅ Enhanced rate limiting")
                        logger.info("   ✅ Cross-MCP document sharing")
                        return alt_port
                except Exception:
                    continue

    # All retry attempts exhausted - PFW not detected
    logger.info("ℹ️  Standalone mode: Using local FPD proxy (always-on)")
    logger.info("   💡 Install USPTO PFW MCP for enhanced features:")
    logger.info("      - Persistent download links (7-day encrypted URLs)")
    logger.info("      - Centralized proxy (unified rate limiting)")
    logger.info("      - Cross-MCP document sharing and caching")
    logger.info("   📦 Get it at: https://github.com/johnwalkoe/patent_filewrapper_mcp")
    return None


def run_server():
    """Run the MCP server with centralized proxy integration"""
    try:
        # Install global async exception handler FIRST
        install_async_exception_handler()

        logger.info("Starting Final Petition Decisions MCP server...")
        logger.info(f"Field config loaded from: {config_path}")

        # Check for centralized USPTO proxy (PFW MCP)
        pfw_proxy_port = _detect_pfw_proxy()

        logger.info("Available tools:")
        logger.info("  - fpd_search_petitions_minimal")
        logger.info("  - fpd_search_petitions_balanced")
        logger.info("  - fpd_search_petitions_by_art_unit")
        logger.info("  - fpd_search_petitions_by_application")
        logger.info("  - fpd_get_petition_details")
        logger.info("  - fpd_get_document_download (with auto-start proxy)")
        logger.info("  - fpd_get_document_content (hybrid PyPDF2 + Mistral OCR)")
        logger.info("  - FPD_get_guidance (sectioned guidance)")

        # Enhanced proxy configuration with PFW integration
        enable_proxy = os.getenv("ENABLE_PROXY_SERVER", "true").lower() == "true"
        enable_always_on = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"

        if enable_proxy:
            if pfw_proxy_port:
                # Use centralized PFW proxy for optimal ecosystem integration
                logger.info("🎯 Using centralized USPTO PFW MCP proxy for document downloads")
                logger.info(f"📄 All FPD document downloads will use port {pfw_proxy_port}")
                logger.info("🔗 This enables persistent links, enhanced security, and cross-MCP integration")

                # Store the centralized proxy port for download tools to use
                os.environ['CENTRALIZED_PROXY_PORT'] = str(pfw_proxy_port)

                # Run MCP server only (no local proxy needed)
                logger.info("Running FPD MCP server (centralized proxy handles downloads)")
                mcp.run()
            else:
                # Run hybrid server with local proxy (fallback mode)
                # Check FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
                default_port = get_local_proxy_port()
                logger.info("⚠️  Running in standalone mode - local proxy enabled")

                if enable_always_on:
                    logger.info(f"📄 Local proxy will start IMMEDIATELY on port {default_port} (always-on mode)")
                    logger.info("🚀 Download links will work instantly without delays")
                else:
                    logger.info(f"📄 Local proxy will start on-demand on port {default_port} (legacy mode)")
                    logger.info("⏱️  First download will trigger proxy startup (0.5s delay)")

                logger.info(f"💡 For enhanced features, install USPTO PFW MCP for centralized proxy")
                logger.info(f"🔧 To use a different port, set FPD_PROXY_PORT (or PROXY_PORT) environment variable")
                asyncio.run(run_hybrid_server(enable_always_on=enable_always_on, proxy_port=default_port))
        else:
            # Run MCP server only
            logger.info("Proxy server disabled via ENABLE_PROXY_SERVER=false")
            mcp.run()

    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise


def main():
    """Main entry point"""
    run_server()


if __name__ == "__main__":
    main()
