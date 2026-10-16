"""Document download + content-extraction tools (SD-1 god-module split).

FPD_get_document_download / FPD_get_document_content_with_ocr, plus
the viewer_key / proxy-registration helpers they share.
Extracted from main.py (mechanical decomposition, no behavior change).
"""

import asyncio
import os
from typing import Any, Dict, Optional

import httpx
from fastmcp import Context
from fastmcp.apps import AppConfig

from ..api.field_constants import FPDFields
from ..api.payload_compat import select_pdf_download
from ..app_uris import DOWNLOADS_URI
from ..proxy.server import generate_enhanced_filename
from ..runtime import get_api_client
from ..server_bootstrap import _ensure_proxy_server_running, get_local_proxy_port
from ..shared.error_utils import (
    ValidationError,
    async_tool_error_handler,
    document_not_located_response,
    format_error_response,
)
from ..shared.injection_scan import (
    RETRIEVED_TEXT_NOTE,
    _WARNING_NOTE,
    scan_text,
)
from ..shared.response_bounds import apply_text_window, content_char_budget
from ..util.deadline import (
    Deadline,
    bind_deadline,
    content_deadline_seconds,
    deadline_exceeded_response,
)
from ..util.identity import get_viewer_key
from ..util.secure_logger import get_secure_logger
from ..util.citations import petition_cite_as
from ..validators import validate_document_identifier, validate_petition_id

#: A claude.ai run "fixed a wording slip" in a quoted decision that had none
#: (2026-10-07). The provenance note says documents are verbatim; this says
#: what to do about it.
QUOTING_RULE = (
    "Quote extracted_content exactly as returned: never correct, smooth or "
    "modernize the Office's wording, spelling or grammar, even where it looks "
    "like a slip. Mark any omission with an ellipsis and say what was left out. "
    "Cite the decision with cite_as."
)

logger = get_secure_logger(__name__)

#: Recovery text embedded in `_window.note` — names the exact tool and
#: parameter that fetches the remainder.
_CONTENT_WINDOW_NOTE = (
    "Only part of the extracted text is shown. Re-call "
    "FPD_get_document_content_with_ocr(petition_id='{petition_id}', "
    "document_identifier='{document_identifier}', char_offset=<_window.next_offset>) "
    "to continue from where this window ended; raise max_chars to widen it."
)

#: Canonical marker sub-key -> this repo's pre-existing top-level key, kept
#: alongside `_window` for this release.
_CONTENT_WINDOW_ALIASES = {"applied": "truncated", "note": "truncation_note"}


def _resolve_document_metadata(
    petition_result: Dict[str, Any], petition_id: str, document_identifier: str
) -> Dict[str, Any]:
    """Locate the target document and its PDF download option within a
    get_petition_by_id(include_documents=True) result.

    Returns either an error envelope (dict with "error", from
    format_error_response) or
    {"petition_data", "document_metadata", "pdf_download_url", "page_count"}.
    Extracted from fpd_get_document_download (mechanical decomposition, no
    behavior change).
    """
    petition_data = petition_result.get(FPDFields.PETITION_DECISION_DATA_BAG, [])
    if not petition_data:
        return format_error_response("Petition data not found", 404)

    documents = petition_data[0].get(FPDFields.DOCUMENT_BAG, [])
    document_metadata = None
    for doc in documents:
        if doc.get(FPDFields.DOCUMENT_IDENTIFIER) == document_identifier:
            document_metadata = doc
            break

    if not document_metadata:
        return document_not_located_response(
            petition_result, petition_id, document_identifier
        )

    # Resolve the USPTO PDF download URL from the document metadata. A
    # native (2026-10) bag can list more than one PDF option; the document's
    # own <id>.pdf wins (api/payload_compat.select_pdf_download).
    pdf_download_url, page_count = select_pdf_download(
        document_metadata, petition_data[0].get(FPDFields.APPLICATION_NUMBER_TEXT)
    )
    if not pdf_download_url:
        return format_error_response("PDF not available for this document", 404)

    return {
        "petition_data": petition_data,
        "document_metadata": document_metadata,
        "pdf_download_url": pdf_download_url,
        "page_count": page_count,
    }


async def _register_download_via_proxy(payload: Dict[str, Any]) -> Optional[str]:
    """Register a download with the local proxy's recent-downloads registry.

    Best effort — returns the download_id or None. Imports the proxy token
    (never regenerates it — Lesson 40).
    """
    try:
        from ..proxy.server import _get_proxy_token

        local_port = get_local_proxy_port()
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                f"http://localhost:{local_port}/api/register-download",
                json=payload,
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            resp.raise_for_status()
            return resp.json().get("download_id")
    except Exception as e:
        logger.debug(f"Recent-downloads registration skipped: {type(e).__name__}")
        return None


async def _deliver_download_link(
    petition_id: str,
    document_identifier: str,
    petition_data: list,
    document_metadata: Dict[str, Any],
    pdf_download_url: str,
    page_count: int,
) -> Dict[str, Any]:
    """Resolve a (centralized or local) proxy download link, register it
    with the recent-downloads registry, and build the tool response.
    Extracted from fpd_get_document_download (mechanical decomposition, no
    behavior change) — the viewer_key logic lives here since it only makes
    sense once a download link exists.
    """
    # Metadata for the enhanced filename
    petition_mail_date = petition_data[0].get(FPDFields.PETITION_MAIL_DATE)
    app_number = petition_data[0].get(FPDFields.APPLICATION_NUMBER_TEXT)
    patent_number = petition_data[0].get(FPDFields.PATENT_NUMBER)
    doc_description = document_metadata.get(FPDFields.DOCUMENT_CODE_DESCRIPTION_TEXT)
    doc_code = document_metadata.get(FPDFields.DOCUMENT_CODE)

    enhanced_filename = generate_enhanced_filename(
        petition_mail_date=petition_mail_date,
        app_number=app_number,
        patent_number=patent_number,
        document_description=doc_description,
        document_code=doc_code,
        max_desc_length=40
    )

    # Mode 1: centralized PFW proxy (CENTRALIZED_PROXY_URL full base URL —
    # e.g. the deployment's published PFW — wins over legacy CENTRALIZED_PROXY_PORT).
    # PFW returns a browser-usable persistent URL built from its own
    # PFW_PROXY_BASE_URL, so it is correct behind Docker/reverse proxies.
    from ..proxy.centralized_integration import (
        get_centralized_base_url,
        register_with_centralized_proxy,
    )

    from ..proxy.secure_link_cache import (
        CENTRALIZED_LINK_LIFETIME_TEXT,
        CENTRALIZED_LINK_TTL_DAYS,
        get_link_cache,
        link_lifetime_text,
    )

    final_url = None
    proxy_mode = "local"
    expires_in_days = CENTRALIZED_LINK_TTL_DAYS
    lifetime_text = CENTRALIZED_LINK_LIFETIME_TEXT
    if get_centralized_base_url():
        final_url = await register_with_centralized_proxy(
            petition_id=petition_id,
            document_identifier=document_identifier,
            download_url=pdf_download_url,
            application_number=app_number,
            enhanced_filename=enhanced_filename,
        )
        if final_url:
            proxy_mode = "centralized"
        else:
            logger.warning("⚠️  Centralized registration failed - falling back to local FPD proxy")

    # Mode 2: local FPD proxy with an encrypted persistent link
    # (FPD_LINK_TTL_DAYS / FPD_LINK_MAX_USES, 1 day / 25 downloads by default).
    # The hash in the URL is the credential — no auth header needed
    # (Lesson 43), so browser navigation works.
    if final_url is None:
        # S4 (2026-10-12 audit): the bind port is operator configuration
        # (FPD_PROXY_PORT), never a caller's argument.
        local_port = get_local_proxy_port()
        await _ensure_proxy_server_running(local_port)

        proxy_base = (
            os.getenv("FPD_PROXY_BASE_URL", "").strip().rstrip("/")
            or f"http://localhost:{local_port}"
        )
        link_cache = get_link_cache()
        final_url = await link_cache.mint_persistent_link(
            petition_id=petition_id,
            document_identifier=document_identifier,
            file_download_uri=pdf_download_url,
            enhanced_filename=enhanced_filename,
            base_url=proxy_base,
        )
        proxy_mode = "local"
        expires_in_days = link_cache.cache_duration.days
        lifetime_text = link_lifetime_text(link_cache.cache_duration.days,
                                           link_cache.max_uses)

    # Register with the recent-downloads panel/page (best effort).
    # viewer_key scopes the registry entry to this caller (H2) — the
    # proxy stores only its hash.
    viewer_key = get_viewer_key()
    download_registry_id = await _register_download_via_proxy({
        "download_url": final_url,
        "petition_id": petition_id,
        "document_identifier": document_identifier,
        "document_description": doc_description or doc_code,
        "enhanced_filename": enhanced_filename,
        "page_count": page_count,
        "application_number": app_number,
        "proxy_mode": proxy_mode,
        "viewer_key": viewer_key,
    })

    return {
        "success": True,
        "petition_id": petition_id,
        "document_identifier": document_identifier,
        "download_url": final_url,
        # Backwards-compatible alias (pre-migration key name)
        "proxy_download_url": final_url,
        "enhanced_filename": enhanced_filename,
        "page_count": page_count,
        "expires_in_days": expires_in_days,
        "download_id": download_registry_id,
        "downloads_page_opened": False,

        "proxy_info": {
            "mode": proxy_mode,
            "note": (
                "Unified download through PFW centralized proxy (persistent links, "
                "enhanced rate limiting, cross-MCP sharing; link lifetime "
                f"{lifetime_text})"
                if proxy_mode == "centralized"
                else f"Local FPD proxy persistent link (valid {lifetime_text}, "
                "survives proxy restarts)"
            ),
        },

        "document_context": {
            "petition_type": petition_data[0].get(FPDFields.DECISION_PETITION_TYPE_CODE_DESCRIPTION_TEXT, "Unknown"),
            "decision_outcome": petition_data[0].get(FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT, "Unknown"),
            "decision_date": petition_data[0].get(FPDFields.DECISION_DATE, "Unknown")
        },

        "llm_response_guidance": {
            "format": f"**📁 [Download {doc_description or 'Document'} ({page_count} pages)]({final_url})** | Raw URL: `{final_url}`",
            "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
        },
    }


@async_tool_error_handler("document_download")
async def fpd_get_document_download(
    petition_id: str,
    document_identifier: str,
    proxy_port: Optional[int] = None,
    generate_persistent_link: bool = True,
    ctx: Context = None
) -> Dict[str, Any]:
    """Generate browser-accessible download URL for petition documents (PDFs) via secure proxy.
Download, PDF, file, link, URL, save, open in a browser, get a copy of a petition or decision.

**ALWAYS-ON PROXY (DEFAULT):** Proxy server starts with MCP - download links work immediately.

**Workflow:**
1. FPD_Get_petition_details(petition_id='uuid', include_documents=True) → get documentBag
   (or FPD_Search_petitions_by_application(..., include_documents=True))
2. FPD_get_document_download(petition_id='uuid', document_identifier='ABC123') → get download link
   (any documentIdentifier from that bag works: the petition's own papers, or a
   file-wrapper fallback entry for a petition served without a bag)
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
- proxy_port: Accepted for backwards compatibility only. The proxy runs on the
  port the operator configured (FPD_PROXY_PORT, default 8081); a different value
  is ignored and `proxy_port_note` says so.
- generate_persistent_link: Deprecated — links are ALWAYS persistent now
  (encrypted links valid for 1 day, up to 25 downloads, by default: via the
  PFW centralized proxy when configured (PFW_LINK_TTL_DAYS /
  PFW_LINK_MAX_USES), otherwise via the local FPD proxy (FPD_LINK_TTL_DAYS /
  FPD_LINK_MAX_USES); `expires_in_days` reports it). The parameter is accepted for
  backwards compatibility and ignored."""
    # Input validation (M4: shape-checked, not just non-empty)
    if not petition_id or len(petition_id.strip()) == 0:
        return format_error_response("Petition ID cannot be empty", 400)
    if not document_identifier or len(document_identifier.strip()) == 0:
        return format_error_response("Document identifier cannot be empty", 400)
    try:
        petition_id = validate_petition_id(petition_id)
        document_identifier = validate_document_identifier(document_identifier)
    except ValidationError as e:
        return format_error_response(str(e), 400, e.request_id)

    # Ensure API client is initialized (protects against async lifecycle issues)
    api_client = get_api_client()

    # Resolve petition + document metadata (needed in every mode)
    petition_result = await api_client.get_petition_by_id(petition_id, include_documents=True)
    if "error" in petition_result:
        return petition_result

    resolved = _resolve_document_metadata(petition_result, petition_id, document_identifier)
    if "error" in resolved:
        return resolved

    result = await _deliver_download_link(
        petition_id=petition_id,
        document_identifier=document_identifier,
        petition_data=resolved["petition_data"],
        document_metadata=resolved["document_metadata"],
        pdf_download_url=resolved["pdf_download_url"],
        page_count=resolved["page_count"],
    )
    note = _ignored_proxy_port_note(proxy_port)
    if note and isinstance(result, dict) and result.get("success"):
        result["proxy_port_note"] = note
    return result


def _ignored_proxy_port_note(proxy_port: Any) -> Optional[str]:
    """S4: the note for a caller-supplied proxy_port that differs from the
    configured one (the value is never used to bind or to build a link)."""
    if proxy_port is None:
        return None
    configured = get_local_proxy_port()
    if proxy_port == configured:
        return None
    return (
        f"proxy_port={proxy_port!r} was ignored: the download proxy runs on the port "
        f"this server is configured with ({configured}). The parameter is kept only "
        "so older calls do not fail."
    )


def _validate_content_params(
    petition_id: str,
    document_identifier: str,
    char_offset: int,
    max_chars: Optional[int],
) -> Optional[Dict[str, Any]]:
    """Return an error envelope for the first invalid parameter, else None.
    The identifier validators are re-run by the caller so their normalized
    values are the ones actually used."""
    if not petition_id or len(petition_id.strip()) == 0:
        return format_error_response("Petition ID cannot be empty", 400)
    if not document_identifier or len(document_identifier.strip()) == 0:
        return format_error_response("Document identifier cannot be empty", 400)
    if char_offset < 0:
        return format_error_response("char_offset must be non-negative", 400)
    if max_chars is not None and max_chars < 1:
        return format_error_response("max_chars must be at least 1", 400)
    try:
        validate_petition_id(petition_id)
        validate_document_identifier(document_identifier)
    except ValidationError as e:
        return format_error_response(str(e), 400, e.request_id)
    return None


def _window_extracted_content(
    result: Dict[str, Any],
    petition_id: str,
    document_identifier: str,
    char_offset: int,
    max_chars: Optional[int],
) -> None:
    """Put a cursor over the extracted text.

    The caller explicitly asked for document text, so the ceiling is the
    higher CONTENT budget — the guard is against pathological size, and the
    cursor makes the remainder REACHABLE instead of lost. A document that
    already fits is left untouched (no `_window` key). The injection scan
    deliberately runs on the FULL text before this, so a later window's
    content is flagged up front.
    """
    prior_truncation_note = result.get("truncation_note")
    apply_text_window(
        result,
        "extracted_content",
        offset=char_offset,
        max_chars=min(max_chars, content_char_budget()) if max_chars else None,
        note=_CONTENT_WINDOW_NOTE.format(
            petition_id=petition_id, document_identifier=document_identifier
        ),
        aliases=_CONTENT_WINDOW_ALIASES,
    )
    if prior_truncation_note and result.get("truncation_note") != prior_truncation_note:
        # An OCR page cap AND a text window both applied — report both.
        result["truncation_note"] = f"{prior_truncation_note} {result['truncation_note']}"


@async_tool_error_handler("document_content")
async def fpd_get_document_content(
    petition_id: str,
    document_identifier: str,
    auto_optimize: bool = True,
    char_offset: int = 0,
    max_chars: Optional[int] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """Extract full text from USPTO petition documents with intelligent hybrid extraction (Word/XML version -> pypdf -> OCR -> Docling).
Read, extract, text, contents, full document, OCR, quote the petition, the decision, or the Office's reasoning.

PREREQUISITE: a document_identifier, from FPD_Get_petition_details (documentBag) or from the decision
samples FPD_get_dismissal_grounds returns (each carries a ready read_with call).
Auto-optimizes extraction: the Word (.docx) or XML version when USPTO serves one beside the PDF (petition
decisions usually have both; exact text, no PDF download), else fast direct pypdf text extraction for
text-based PDFs, OCR only for scanned documents.
MISTRAL_API_KEY is optional - without it, scanned documents fall back to Docling
(self-hosted) when DOCLING_SERVE_URL is configured and the document is
<= DOCLING_MAX_PAGES (default 25 - petition decisions are usually short).

USE CASES:
- Analyze petition legal arguments and Director's reasoning
- Extract petition issues, CFR rules cited, statutory references
- Detect patterns across multiple petitions (e.g., common denial reasons)
- Correlate petition text with PTAB challenge strategies
- Profile examiner behavior from supervisory review petitions

EXTRACTION MODES:
- auto_optimize=True (default): Word/XML version first, then pypdf, OCR only when the document is scanned
- auto_optimize=False: Use OCR directly (slower; highest fidelity for scanned documents)

Returns: extracted_content, extraction_method, page_count; free_text_variants lists the Word/XML versions tried;
cite_as is the decision's verified link (cite with it, never build one); quoting_rule: quote extracted_content
exactly, never correct the Office's wording

LARGE DOCUMENTS - CURSOR:
- char_offset (default 0): where to start reading in the extracted text
- max_chars (default USPTO_MAX_CONTENT_CHARS, 120,000): window size
When the text is longer than the window, the response carries a `_window`
block: {unit, offset, returned, total, has_more, next_offset}. Pass
`_window.next_offset` back as char_offset to read the next window - nothing
is lost, it is paged. Windows snap to `=== PAGE N ===` boundaries when the
OCR tier emitted them (unit='page'), otherwise they are raw character slices
(unit='char').

Example workflow:
1. FPD_Get_petition_details(petition_id='0b71b685-...', include_documents=True)
2. FPD_get_document_content_with_ocr(petition_id='0b71b685-...', document_identifier='DSEN5APWPHOENIX')
3. Analyze extracted text for legal arguments, issues, and patterns
4. If _window.has_more: re-call with char_offset=_window.next_offset

For document selection and extraction-tier strategies, use FPD_get_guidance('extraction')."""
    # Input validation (M4: shape-checked, not just non-empty)
    invalid = _validate_content_params(
        petition_id, document_identifier, char_offset, max_chars
    )
    if invalid is not None:
        return invalid
    petition_id = validate_petition_id(petition_id)
    document_identifier = validate_document_identifier(document_identifier)

    # Ensure API client is initialized (protects against async lifecycle issues)
    # (Content extraction downloads directly from the USPTO API — no proxy hop.)
    api_client = get_api_client()

    # Progress notifications (best-effort; clients without progress support
    # just skip them — never load-bearing)
    async def _progress(percent: float, message: str) -> None:
        if ctx is not None:
            try:
                await ctx.report_progress(progress=percent, total=100, message=message)
            except Exception:
                pass

    # F-X2 / Wave 2 A.5: one end-to-end deadline over the whole tool call
    # (FPD_CONTENT_DEADLINE_SECONDS, default 85 s, under Cloudflare's ~100 s
    # cut). Serially this can spend a petition fetch with the file-wrapper
    # fallback, a PDF download, a pypdf parse, a Mistral upload + OCR with
    # retries and then Docling. Every one of those steps takes what is left
    # of the one budget (util/deadline.py) and a spent budget comes back as
    # a "Deadline exceeded" envelope; the asyncio.timeout is the backstop for
    # a step that does not check (the pypdf parse).
    deadline = Deadline(content_deadline_seconds())
    try:
        with bind_deadline(deadline):
            async with asyncio.timeout(deadline.seconds):
                result = await api_client.extract_document_content_hybrid(
                    petition_id=petition_id,
                    document_identifier=document_identifier,
                    auto_optimize=auto_optimize,
                    progress_cb=_progress
                )
    except TimeoutError:
        logger.warning(
            "Content extraction exceeded the %ss call deadline", deadline.seconds
        )
        return deadline_exceeded_response()

    # Check for errors
    if "error" in result:
        return result

    # Provenance posture: extracted/OCR text is quoted data, not
    # instructions. The note is always attached; the detection-only scan
    # annotates injection-shaped content by kind label (never matched text
    # — content-minimization) and the `injection_scan` key is ABSENT when
    # the text is clean. Nothing is ever stripped or rewritten.
    result["provenance_note"] = RETRIEVED_TEXT_NOTE
    # CITATIONS ARE LINKS: the same verified link the search and details tools
    # carry, built from the petition's own record. Without it a model built
    # one by hand and linked the wrong application (claude.ai, 2026-10-07).
    cite = petition_cite_as(
        result.pop("decision_date", None),
        result.get("application_number"),
        result.pop("patent_number", None),
    )
    if cite:
        result["cite_as"] = cite
    result["quoting_rule"] = QUOTING_RULE
    extracted = result.get("extracted_content")
    kinds = scan_text(extracted) if isinstance(extracted, str) else []
    if kinds:
        result["injection_scan"] = {
            "flagged": [
                {
                    "petition_id": petition_id,
                    "document_identifier": document_identifier,
                    "kinds": kinds,
                }
            ],
            "note": _WARNING_NOTE,
        }

    _window_extracted_content(
        result, petition_id, document_identifier, char_offset, max_chars
    )

    # Add LLM guidance for text analysis
    result["llm_guidance"] = {
        "analysis_strategies": {
            "legal_argument_analysis": {
                "description": "Analyze petition and decision text for legal reasoning",
                "action": "Extract key arguments, Director's reasoning, legal citations"
            },
            "pattern_detection": {
                "description": "Compare text across multiple petitions to find common themes",
                "action": "Compare decisions of ONE petition type: the grounds of dismissals or denials, what granted petitions supplied"
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
            "optimization": result.get("auto_optimization", "Unknown")
        },
        "next_steps": [
            "Analyze extracted content for key legal arguments",
            "Search for CFR citations (e.g., '37 CFR 1.137', '37 CFR 1.181')",
            "Identify petition outcome reasoning in decision text",
            "Cross-reference with PFW prosecution history for context",
            "If the application issued as a patent, check PTAB for challenges"
        ]
    }

    return result


def register(mcp) -> None:
    """Register the 2 document tools (names/schemas unchanged)."""
    mcp.tool(name="FPD_get_document_download",
             app=AppConfig(resource_uri=DOWNLOADS_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_get_document_download)
    mcp.tool(name="FPD_get_document_content_with_ocr",
             annotations={"defer_loading": True, "readOnlyHint": True})(fpd_get_document_content)
