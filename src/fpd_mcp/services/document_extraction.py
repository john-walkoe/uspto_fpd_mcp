"""Document text-extraction pipeline, extracted from FPDClient (SOLID #3/#4).

Owns the 3-tier hybrid extraction pipeline (pypdf -> Mistral OCR -> Docling)
plus the M3 Mistral daily-spend budget tracking and the Mistral-tier
resilience wiring (circuit breaker + semaphore) that guards it. FPDClient no
longer needs to change when OCR-tier logic changes, and this pipeline
doesn't need FPDClient's full surface (search/petition-lookup methods).

FPDClient keeps thin delegating methods with UNCHANGED public signatures —
tools and existing tests call FPDClient methods directly, so there are zero
call-site changes. FPDClient constructs one DocumentExtractionService
instance (passing itself as the `client` — used for `get_petition_by_id` and
the shared PDF-download helper) and forwards to it.

Note: `_MAX_PDF_BYTES` and the byte-capped PDF download step deliberately
stay on FPDClient (see `FPDClient._download_pdf_for_extraction`) rather than
moving here — existing tests monkeypatch that constant via
`fpd_client_module._MAX_PDF_BYTES` and expect it to take live effect, which
only works if the constant and the code reading it live in the same module.
"""

import asyncio
import os
import threading
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

from ..api.docling_client import DoclingClient
from ..api.field_constants import FPDFields
from ..config import api_constants
from ..config.feature_flags import feature_flags
from ..shared.circuit_breaker import CircuitBreaker
from ..shared.error_utils import (
    document_not_located_response,
    format_error_response,
    generate_request_id,
)
from ..shared.response_bounds import BOUNDS_KEY as _BOUNDS_KEY
from ..shared.response_bounds import content_char_budget as _content_char_budget
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)

# M3: cumulative daily spend ceiling for billed Mistral OCR calls. State is
# process-local (module-level) — fine for this single-container deployment;
# it does not need to survive restarts or be shared across replicas. Resets
# whenever the UTC calendar date advances.
_MISTRAL_OCR_COST_PER_PAGE = 0.001  # $1 per 1000 pages
_mistral_daily_cost_lock = threading.Lock()
_mistral_daily_cost_state: Dict[str, Any] = {"date": None, "total": 0.0}


#: Default cost-control page cap per OCR'd document. Name matches the
#: sibling MCPs (PFW services/ocr_service.py, PTAB services/ocr_service.py)
#: so one env var configures the whole suite.
_DEFAULT_MISTRAL_OCR_MAX_PAGES = 50


def mistral_ocr_max_pages() -> int:
    """MISTRAL_OCR_MAX_PAGES — per-document OCR page cap (was a hard-coded
    50). Always >= 1; an unparseable value falls back to the default."""
    raw = os.getenv("MISTRAL_OCR_MAX_PAGES", str(_DEFAULT_MISTRAL_OCR_MAX_PAGES))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning("Invalid MISTRAL_OCR_MAX_PAGES; using default 50")
        return _DEFAULT_MISTRAL_OCR_MAX_PAGES


def _pdf_page_count(pdf_content: bytes) -> Optional[int]:
    """Best-effort local page count from the already-downloaded PDF bytes.
    Returns None when the bytes can't be parsed (encrypted/damaged/mocked)."""
    try:
        import pypdf

        return len(pypdf.PdfReader(BytesIO(pdf_content)).pages)
    except Exception as e:  # pragma: no cover - depends on the PDF
        logger.debug(f"Local page count unavailable ({type(e).__name__})")
        return None


def resolve_ocr_page_window(
    pdf_content: bytes, page_count: int, max_pages: Optional[int] = None
) -> Tuple[int, Optional[int]]:
    """Decide how many pages to send to the paid OCR tier.

    Returns (pages_to_request, total_pages_or_None).

    The USPTO document metadata's pageCount is missing/zero often enough that
    the wrapper-fallback backfill in api/fpd_client.py exists specifically to
    repair it. Before this helper, a missing page count sent `"pages": None`
    to Mistral — i.e. the ENTIRE document, unbounded and unbudgeted, on the
    one path where we knew the least about its size. Now the count is
    recovered locally from the PDF bytes and the request is always an
    explicit, bounded page range.
    """
    cap = max_pages if max_pages is not None else mistral_ocr_max_pages()
    total: Optional[int] = page_count if isinstance(page_count, int) and page_count > 0 else None
    if total is None:
        total = _pdf_page_count(pdf_content)
    if total is None:
        # Still unknown (encrypted/unparseable PDF): request the cap as an
        # explicit bounded range rather than the previous unbounded `None`.
        # The response's usage_info.pages_processed books the real cost
        # either way; the truncation markers below flag the unknown total.
        return cap, None
    return max(1, min(total, cap)), total


#: M-21: the ceiling used to default to 0 (unlimited), so the only control on
#: metered third-party spend was off out of the box. A finite default is the
#: safe direction: an operator who wants no ceiling can still set 0 explicitly.
_DEFAULT_MISTRAL_DAILY_BUDGET_USD = 5.0


def _mistral_daily_budget_usd() -> float:
    """MISTRAL_OCR_DAILY_BUDGET_USD — an explicit 0 means unlimited.

    Unset now means the default ceiling, not unlimited (M-21).
    """
    raw = os.getenv(
        "MISTRAL_OCR_DAILY_BUDGET_USD", str(_DEFAULT_MISTRAL_DAILY_BUDGET_USD)
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid MISTRAL_OCR_DAILY_BUDGET_USD; using the default ceiling"
        )
        return _DEFAULT_MISTRAL_DAILY_BUDGET_USD


def _mistral_daily_reset_if_needed_locked() -> None:
    today = datetime.now(timezone.utc).date()
    if _mistral_daily_cost_state["date"] != today:
        _mistral_daily_cost_state["date"] = today
        _mistral_daily_cost_state["total"] = 0.0


def _mistral_daily_spend_reserve(estimated_cost: float) -> Tuple[bool, float, float]:
    """Reserve `estimated_cost` against today's ceiling under the lock.

    Returns (allowed, current_total_before_reservation, budget). A budget of
    0 means unlimited and nothing is reserved.

    M-19: this was a check-then-act. The lock was taken to READ the running
    total, released, and the paid round trip then ran outside it, so N
    concurrent extractions each saw the same pre-call total and all N were
    admitted against a ceiling that only had room for one. The reservation is
    now taken inside the same critical section as the read, and settled or
    released afterwards (see _mistral_daily_spend_settle /
    _mistral_daily_spend_release).
    """
    budget = _mistral_daily_budget_usd()
    with _mistral_daily_cost_lock:
        _mistral_daily_reset_if_needed_locked()
        current_total = _mistral_daily_cost_state["total"]
        if budget <= 0:
            return True, current_total, budget
        if current_total + estimated_cost > budget:
            return False, current_total, budget
        _mistral_daily_cost_state["total"] = current_total + estimated_cost
        return True, current_total, budget


def _mistral_daily_spend_settle(reserved: float, actual: float) -> float:
    """Replace a reservation with the actual cost; returns the running total."""
    with _mistral_daily_cost_lock:
        _mistral_daily_reset_if_needed_locked()
        _mistral_daily_cost_state["total"] = max(
            0.0, _mistral_daily_cost_state["total"] - reserved + actual
        )
        return _mistral_daily_cost_state["total"]


def _mistral_daily_spend_release(reserved: float) -> float:
    """Give a reservation back when the paid call never happened."""
    return _mistral_daily_spend_settle(reserved, 0.0)


def _mistral_daily_spend_add(cost: float) -> float:
    """Accumulate an actual cost for today (UTC); returns the new running total."""
    with _mistral_daily_cost_lock:
        _mistral_daily_reset_if_needed_locked()
        _mistral_daily_cost_state["total"] += cost
        return _mistral_daily_cost_state["total"]


def _mark_pypdf_truncation(
    extraction_result: Dict[str, Any], truncated: bool, status: Dict[str, Any]
) -> None:
    """Attach the truncation markers for the free (pypdf) tier."""
    if status.get("extraction_error"):
        extraction_result["extraction_error"] = status["extraction_error"]
        extraction_result["pages_extracted"] = status.get("pages_extracted")
    if not truncated:
        return
    extraction_result["truncated"] = True
    if status.get("extraction_error"):
        extraction_result["truncation_note"] = status["extraction_error"]
    else:
        # M6: free-tier page cap (200) — note the truncation rather than
        # silently returning partial content.
        extraction_result["truncation_note"] = (
            "Document exceeds the 200-page cap on native text-layer "
            "(pypdf) extraction; only the first 200 pages were extracted."
        )
    extraction_result[_BOUNDS_KEY] = {
        "applied": True,
        "reason": "window",
        "size_chars": len(extraction_result.get("extracted_content") or ""),
        "size_limit": _content_char_budget(),
        "stages": ["truncated"],
        "slimmed_fields": [],
        "items_returned": status.get("pages_extracted"),
        "items_total": None,
        "note": extraction_result["truncation_note"],
    }


def _mark_ocr_page_cap(
    extraction_result: Dict[str, Any],
    text: str,
    pages_requested: int,
    total_pages: Optional[int],
) -> None:
    """Attach truncation markers when the paid OCR tier processed only part
    of a document.

    The Mistral tier used to truncate with NO marker at all (the pypdf tier
    marked correctly), so a page-capped OCR was indistinguishable from a
    complete extraction. `items_returned`/`items_total` count PAGES here;
    `items_total` is null when the document's true page count could not be
    determined (encrypted/unparseable PDF with no USPTO pageCount).
    """
    capped = total_pages is None or total_pages > pages_requested
    extraction_result["pages_extracted"] = pages_requested
    if total_pages:
        extraction_result["page_count"] = total_pages
    if not capped:
        return
    if total_pages:
        note = (
            f"Only the first {pages_requested} of {total_pages} pages were OCR'd "
            f"(MISTRAL_OCR_MAX_PAGES={mistral_ocr_max_pages()}); the extracted text "
            "is incomplete."
        )
    else:
        note = (
            f"The document's page count could not be determined, so OCR was capped "
            f"at {pages_requested} pages (MISTRAL_OCR_MAX_PAGES="
            f"{mistral_ocr_max_pages()}); the extracted text may be incomplete."
        )
    extraction_result["truncated"] = True
    extraction_result["truncation_note"] = note
    extraction_result[_BOUNDS_KEY] = {
        "applied": True,
        "reason": "window",
        "size_chars": len(text or ""),
        "size_limit": _content_char_budget(),
        "stages": ["truncated"],
        "slimmed_fields": [],
        "items_returned": pages_requested,
        "items_total": total_pages,
        "note": note,
    }


class DocumentExtractionService:
    """Hybrid (pypdf -> Mistral OCR -> Docling) document text extraction."""

    def __init__(
        self,
        client: Any,
        download_timeout: float,
        connection_limits: httpx.Limits,
        docling_client_factory: Callable[[], DoclingClient] = DoclingClient,
    ) -> None:
        # F-S8 (solid-principles, Interface Segregation): this service was
        # handed the entire FPDClient — a 20-method surface — to use exactly
        # two of its methods, one of them private
        # (`_download_pdf_for_extraction`), which the module docstring
        # already flagged as an encapsulation break kept for
        # test-monkeypatching reasons. It also made the ownership a cycle:
        # FPDClient owns this service, this service holds FPDClient.
        #
        # The two capabilities are named properties now. `client` stays the
        # constructor parameter and `self._client` stays the storage, so
        # instance-level monkeypatches on the client (which every test uses)
        # are still honored and no call site changed — but the DEPENDENCY is
        # stated as two callables rather than "whatever FPDClient has".
        self._client = client
        self.download_timeout = download_timeout
        self.connection_limits = connection_limits
        self._docling_client_factory = docling_client_factory

        # Mistral-tier resilience wiring, moved here with the code it
        # guards: a dedicated semaphore (more expensive than USPTO calls)
        # and circuit breaker.
        self.mistral_semaphore = asyncio.Semaphore(2)
        self.mistral_circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30,
            name="Mistral_OCR"
        )

    @property
    def _fetch_petition(self) -> Callable:
        """Capability 1: fetch a petition record by id (F-S8)."""
        return self._client.get_petition_by_id

    @property
    def _download_pdf(self) -> Callable:
        """Capability 2: byte-capped PDF fetch for the extraction pipeline.

        Lives on FPDClient rather than here because the tests monkeypatch
        `fpd_client_module._MAX_PDF_BYTES` and expect it to take live effect,
        which only works if the constant and its reader share a module.
        """
        return self._client._download_pdf_for_extraction

    def is_good_extraction(self, text: str) -> bool:
        """
        Determine if pypdf extraction is usable or if we need Mistral OCR.

        Returns False if:
        - Text is too short (< 100 chars)
        - Too many garbled characters
        - Too much whitespace
        - Insufficient word density
        """
        if len(text) < 100:
            return False

        # Check for garbled text
        garbled_count = sum(1 for c in text if not (c.isalnum() or c.isspace() or c in '.,;:!?-()[]{}'))
        if garbled_count / len(text) > 0.3:
            return False

        # Check word density
        words = text.split()
        if len(words) < 20:
            return False

        return True

    async def extract_with_pypdf(
        self,
        pdf_content: bytes,
        max_pages: int = 200,
        status: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, bool]:
        """
        Extract text using pypdf (free, fast, works for text-based PDFs).

        M6: migrated off the deprecated pypdf package to its maintained
        successor, pypdf (near-drop-in API). Also caps extraction at
        max_pages (default 200), mirroring the page caps already enforced
        on the paid/self-hosted OCR tiers (Mistral: MISTRAL_OCR_MAX_PAGES;
        Docling: DOCLING_MAX_PAGES) — previously this was the one tier with
        no upper bound at all.

        Args:
            status: optional out-dict. On a mid-extraction failure this
                records `extraction_error` (and `pages_extracted`) so the
                caller can report the partial result honestly instead of the
                failure being swallowed. Kept as an out-param rather than a
                third tuple element to preserve the (text, truncated)
                signature every existing caller and test relies on.

        Returns:
            Tuple of (extracted_text, truncated) — truncated is True when the
            document has more than max_pages and only the first max_pages
            were extracted, and ALSO when extraction aborted part-way and the
            returned text is partial.
        """
        text_parts: list = []
        try:
            # pypdf is fully synchronous and CPU-bound: parsing the xref and
            # extracting up to max_pages of a document that may run to
            # _MAX_PDF_BYTES blocked the event loop for the whole extraction,
            # stalling every other in-flight tool call (file-handling F-4).
            # `text_parts` is passed in so a mid-extraction failure still
            # returns the pages already recovered.
            truncated = await asyncio.to_thread(
                self._extract_pypdf_pages, pdf_content, max_pages, text_parts
            )
            return "\n\n".join(text_parts), truncated
        except Exception as e:
            # Previously this discarded whatever had already been extracted
            # and reported truncated=False — a partial extraction presented
            # as a complete one. Return what we have, marked.
            logger.warning(f"pypdf extraction failed after {len(text_parts)} page(s): {e}")
            partial = "\n\n".join(text_parts)
            if status is not None:
                status["extraction_error"] = (
                    f"pypdf extraction aborted after {len(text_parts)} page(s) "
                    f"({type(e).__name__}); any text above is partial."
                )
                status["pages_extracted"] = len(text_parts)
            return partial, bool(partial)

    @staticmethod
    def _extract_pypdf_pages(
        pdf_content: bytes, max_pages: int, text_parts: list
    ) -> bool:
        """Synchronous pypdf body, run in a worker thread by
        extract_with_pypdf. Appends each page's text to `text_parts` and
        returns whether the document was truncated at max_pages."""
        import pypdf

        pdf_reader = pypdf.PdfReader(BytesIO(pdf_content))

        total_pages = len(pdf_reader.pages)
        truncated = total_pages > max_pages
        pages_to_extract = pdf_reader.pages[:max_pages] if truncated else pdf_reader.pages

        for page in pages_to_extract:
            text_parts.append(page.extract_text())
        return truncated

    async def _do_mistral_ocr_call(
        self,
        pdf_content: bytes,
        page_count: int,
        mistral_api_key: str,
        mistral_base_url: str,
        mistral_ocr_model: str,
    ) -> Tuple[str, float]:
        """Upload + OCR round trip against the Mistral API. Extracted out of
        extract_with_mistral_ocr into its own method (rather than a nested
        closure) so its branches are no longer counted toward that method's
        cyclomatic complexity — mechanical decomposition, no behavior
        change."""
        # Step 1: Upload PDF file to Mistral
        mistral_headers = {
            "Authorization": f"Bearer {mistral_api_key}",
        }

        files = {
            "file": ("document.pdf", pdf_content, "application/pdf")
        }

        data = {
            "purpose": "ocr"
        }

        async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.connection_limits) as client:
            # Upload file
            upload_response = await client.post(
                f"{mistral_base_url}/files",
                headers=mistral_headers,
                files=files,
                data=data
            )
            upload_response.raise_for_status()
            upload_data = upload_response.json()
            file_id = upload_data.get("id")

            if not file_id:
                raise ValueError("Failed to upload file to Mistral OCR service")

            # Step 2: Process with OCR
            ocr_payload = {
                "model": mistral_ocr_model,
                "document": {
                    "type": "file",
                    "file_id": file_id
                },
                # ALWAYS an explicit, bounded page range. The previous
                # `... if page_count > 0 else None` sent the ENTIRE document
                # to the paid tier whenever the USPTO metadata's pageCount was
                # missing or zero — which demonstrably happens (that is why
                # api/fpd_client.py's wrapper-fallback backfills pageCount).
                # Callers resolve the window with resolve_ocr_page_window();
                # the bound is re-applied here so this method is safe on its
                # own terms too.
                "pages": list(range(max(1, min(page_count, mistral_ocr_max_pages())))),
                "include_image_base64": False  # Save tokens
            }

            # Operation-level timeout for OCR (2x download timeout for large PDFs)
            ocr_timeout = self.download_timeout * api_constants.OCR_TIMEOUT_MULTIPLIER
            try:
                async with asyncio.timeout(ocr_timeout):
                    ocr_response = await client.post(
                        f"{mistral_base_url}/ocr",
                        headers={
                            "Authorization": f"Bearer {mistral_api_key}",
                            "Content-Type": "application/json"
                        },
                        json=ocr_payload
                    )
                    ocr_response.raise_for_status()
                    ocr_data = ocr_response.json()
            except asyncio.TimeoutError:
                raise ValueError(f"OCR operation timed out after {ocr_timeout}s - PDF may be too large or complex")

            # Extract content from OCR response
            pages_processed = ocr_data.get("usage_info", {}).get("pages_processed", 0)
            estimated_cost = pages_processed * _MISTRAL_OCR_COST_PER_PAGE
            # M-19: the actual cost is settled against the reservation by the
            # caller (extract_with_mistral_ocr), not accumulated here. Booking
            # it in both places would double-charge the daily ceiling.

            # Combine all page content. The `=== PAGE N ===` header is
            # emitted for EVERY page, including ones OCR returned empty:
            # previously the header lived inside the non-blank branch, so a
            # page that produced no text vanished without a trace and the
            # surviving page numbers implied a complete document.
            extracted_content = []
            for page in ocr_data.get("pages", []):
                page_markdown = page.get("markdown", "")
                page_label = f"=== PAGE {page.get('index', 0) + 1} ==="
                if page_markdown.strip():
                    extracted_content.append(f"{page_label}\n{page_markdown}")
                else:
                    extracted_content.append(
                        f"{page_label}\n[no text recovered from this page]"
                    )

            full_content = "\n\n".join(extracted_content)

            logger.info(f"Mistral OCR extracted {pages_processed} pages, cost: ${estimated_cost:.4f}")

            return full_content, estimated_cost

    async def extract_with_mistral_ocr(self, pdf_content: bytes, page_count: int = 0) -> Tuple[str, float]:
        """
        Extract text using Mistral OCR API (no poppler/pdf2image required).
        Uses the same approach as Patent File Wrapper MCP.

        Args:
            pdf_content: PDF bytes
            page_count: Number of pages (for cost control). 0/missing is
                resolved locally from the PDF bytes — see
                resolve_ocr_page_window.

        Returns:
            Tuple of (extracted_text, cost_usd)
        """
        # Check feature flag
        if not feature_flags.is_enabled("mistral_ocr_enabled"):
            # Caller-visible string: engine identity stays out of served text
            # (the backend is swappable; see the OCR neutral-vocabulary rule).
            raise ValueError("OCR extraction is currently disabled")

        # Resolve the bounded page window BEFORE anything else: the spend
        # pre-check below and the OCR request itself must agree on how many
        # pages this call will actually bill for.
        pages_to_request, _total_pages = resolve_ocr_page_window(pdf_content, page_count)

        # M3: enforce the cumulative daily spend ceiling BEFORE making any
        # paid call (upload + OCR). Unset/0 budget = unlimited (unchanged
        # default behavior). The estimate uses the ACTUAL bounded page count:
        # it previously assumed 1 page whenever page_count was missing, so a
        # 50-page OCR sailed past a nearly-exhausted daily budget and only
        # booked its real cost afterwards.
        estimated_cost = pages_to_request * _MISTRAL_OCR_COST_PER_PAGE
        allowed, current_total, budget = _mistral_daily_spend_reserve(estimated_cost)
        if not allowed:
            # Server-side log keeps the full accounting detail; the raised
            # (user/model-visible) message is deliberately neutral — no
            # dollar figures, no budget mechanics.
            logger.warning(
                f"Mistral OCR daily budget exceeded: ${current_total:.4f} already spent "
                f"today (UTC), this call estimated at ~${estimated_cost:.4f}, "
                f"configured MISTRAL_OCR_DAILY_BUDGET_USD=${budget:.2f}"
            )
            raise ValueError(
                "OCR capacity limit reached; try again later."
            )

        # M-19: from here on the estimate is HELD against today's ceiling.
        # Every exit path must either settle it against the real cost or give
        # it back, or a failed call would permanently consume budget.
        settled = False
        try:
            # Get Mistral API key from unified secure storage first, then environment variable
            mistral_api_key = None
            try:
                from ..shared_secure_storage import get_mistral_api_key, resolve_api_key
                mistral_api_key = resolve_api_key(None, get_mistral_api_key, "MISTRAL_API_KEY")
            except Exception as e:
                # F-E10: see the matching note in api/fpd_client.py.
                logger.warning(
                    f"Mistral API key resolution via secure storage failed "
                    f"({type(e).__name__}); falling back to env var"
                )
                mistral_api_key = os.getenv("MISTRAL_API_KEY")

            if not mistral_api_key:
                raise ValueError("MISTRAL_API_KEY required for OCR extraction")

            mistral_base_url = "https://api.mistral.ai/v1"
            # Mistral OCR model slug. Default `mistral-ocr-latest` tracks Mistral's
            # current GA model (= OCR 4 as of 2026-06-23); pin a dated slug
            # (e.g. mistral-ocr-2503, mistral-ocr-4-0) via MISTRAL_OCR_MODEL.
            mistral_ocr_model = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

            # Resilience: bound concurrent Mistral OCR calls with the
            # service-specific semaphore and route the actual HTTP call
            # through the Mistral circuit breaker so repeated upstream
            # failures fail fast instead of piling up retries/timeouts.
            async with self.mistral_semaphore:
                text, actual_cost = await self.mistral_circuit_breaker.call(
                    self._do_mistral_ocr_call,
                    pdf_content, pages_to_request, mistral_api_key, mistral_base_url, mistral_ocr_model,
                )
            _mistral_daily_spend_settle(estimated_cost, actual_cost)
            settled = True
            return text, actual_cost

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Mistral API authentication failed - check MISTRAL_API_KEY")
            elif e.response.status_code == 402:
                raise ValueError("Mistral API payment required - insufficient credits")
            else:
                raise ValueError(f"Mistral API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            logger.error(f"Mistral OCR extraction failed: {e}")
            raise
        finally:
            if not settled:
                _mistral_daily_spend_release(estimated_cost)

    async def _resolve_document_for_hybrid_extraction(
        self, petition_id: str, document_identifier: str, request_id: str
    ) -> Dict[str, Any]:
        """Fetch petition details and locate the target document's metadata
        + direct USPTO PDF download URL.

        Returns either an error envelope (dict with "error", from
        get_petition_by_id or built here) or
        {"document_code", "page_count", "direct_download_url"}.
        """
        petition_data = await self._fetch_petition(petition_id, include_documents=True)

        if "error" in petition_data:
            return petition_data

        # Find document in documentBag - access it from the correct location
        petition_records = petition_data.get(FPDFields.PETITION_DECISION_DATA_BAG, [])
        if not petition_records:
            return format_error_response(
                f"Petition {petition_id} not found",
                404,
                request_id
            )

        document_bag = petition_records[0].get(FPDFields.DOCUMENT_BAG, [])
        document = None
        for doc in document_bag:
            if doc.get(FPDFields.DOCUMENT_IDENTIFIER) == document_identifier:
                document = doc
                break

        if not document:
            return document_not_located_response(
                petition_data, petition_id, document_identifier, request_id
            )

        # Get document metadata
        document_code = document.get(FPDFields.DOCUMENT_CODE, "UNKNOWN")
        page_count = document.get(FPDFields.PAGE_COUNT, 0)

        # Extract direct download URL from document metadata (for proxy registration)
        # The proxy needs this URL to fetch PDFs from USPTO API on behalf of users
        # Find the PDF download option in downloadOptionBag
        download_options = document.get(FPDFields.DOWNLOAD_OPTION_BAG, [])
        direct_download_url = None
        for option in download_options:
            if option.get(FPDFields.MIME_TYPE_IDENTIFIER) == 'PDF':
                direct_download_url = option.get(FPDFields.DOWNLOAD_URL)
                break

        if not direct_download_url:
            # Try getting download URL directly from document (still for proxy registration)
            direct_download_url = document.get(FPDFields.DOWNLOAD_URL, "")

        if not direct_download_url:
            return format_error_response(
                "PDF download URL not available for this document",
                404,
                request_id
            )

        return {
            "document_code": document_code,
            "page_count": page_count,
            "direct_download_url": direct_download_url,
        }

    async def _extract_with_docling_fallback(
        self,
        extraction_result: Dict[str, Any],
        pdf_content: bytes,
        page_count: int,
        document_identifier: str,
        request_id: str,
        progress_cb,
        mistral_error: Exception,
    ) -> None:
        """Tier 3: Docling (self-hosted), reached only when Mistral was
        unavailable/failed. Re-raises the ORIGINAL mistral_error when Docling
        isn't usable either (matches pre-decomposition behavior)."""
        docling = self._docling_client_factory()
        # L-18: the USPTO pageCount is missing often enough that the
        # wrapper-fallback backfill exists to repair it, and a missing count
        # arrives here as 0. Recover it from the PDF bytes before the gate so
        # "unknown" is not silently treated as "small".
        if not (isinstance(page_count, int) and page_count > 0):
            page_count = _pdf_page_count(pdf_content) or 0
        if docling.is_available() and docling.within_page_limit(page_count):
            await progress_cb(
                60,
                f"Running Docling OCR ({page_count} pages, "
                f"may take ~{page_count * 20}s)..."
            )
            docling_text = await docling.extract(
                pdf_content, filename=f"{document_identifier}.pdf"
            )
            logger.info(f"[{request_id}] Docling extraction successful ({len(docling_text)} chars)")
            await progress_cb(95, "Docling OCR complete")
            extraction_result.update({
                "extracted_content": docling_text,
                "extraction_method": "Docling (docling-serve)",
                "auto_optimization": "pypdf + Mistral unavailable - Docling used"
            })
        else:
            if docling.is_available():
                logger.info(
                    f"[{request_id}] Docling skipped: {page_count} pages exceeds "
                    f"DOCLING_MAX_PAGES={docling.max_pages}"
                )
            raise mistral_error

    async def _extract_auto_optimized(
        self,
        extraction_result: Dict[str, Any],
        pdf_content: bytes,
        page_count: int,
        document_identifier: str,
        request_id: str,
        progress_cb,
    ) -> None:
        """auto_optimize=True path: Tier 1 pypdf (free), else Tier 2 Mistral
        OCR (paid), else Tier 3 Docling (self-hosted). Mutates
        extraction_result in place."""
        # Tier 1: pypdf (free)
        logger.info(f"[{request_id}] Attempting pypdf extraction (free)")
        await progress_cb(40, "Trying pypdf text extraction (free)...")
        pypdf_status: Dict[str, Any] = {}
        pypdf_text, pypdf_truncated = await self.extract_with_pypdf(
            pdf_content, status=pypdf_status
        )

        if self.is_good_extraction(pypdf_text):
            # pypdf worked!
            logger.info(f"[{request_id}] pypdf extraction successful ({len(pypdf_text)} chars)")
            await progress_cb(95, "pypdf extraction complete")
            extraction_result.update({
                "extracted_content": pypdf_text,
                "extraction_method": "pypdf",
                "auto_optimization": "pypdf succeeded - no OCR needed"
            })
            _mark_pypdf_truncation(extraction_result, pypdf_truncated, pypdf_status)
            return

        # Tier 2: Mistral OCR (paid); Tier 3: Docling (self-hosted)
        logger.info(f"[{request_id}] pypdf extraction poor quality, falling back to OCR")
        await progress_cb(50, "Scanned document — running OCR...")
        mistral_error: Optional[Exception] = None
        pages_requested, total_pages = resolve_ocr_page_window(pdf_content, page_count)
        try:
            mistral_text, cost = await self.extract_with_mistral_ocr(pdf_content, pages_requested)
            logger.info(f"[{request_id}] Mistral OCR extraction successful ({len(mistral_text)} chars, ${cost:.4f})")
            await progress_cb(95, "Mistral OCR complete")
            extraction_result.update({
                "extracted_content": mistral_text,
                "extraction_method": "Mistral OCR (mistral-ocr-latest)",
                "auto_optimization": "pypdf failed - Mistral OCR used"
            })
            _mark_ocr_page_cap(extraction_result, mistral_text, pages_requested, total_pages)
            return
        except Exception as e:
            mistral_error = e
            logger.warning(
                f"[{request_id}] Mistral OCR unavailable/failed "
                f"({type(e).__name__}) - trying Docling"
            )

        await self._extract_with_docling_fallback(
            extraction_result, pdf_content, page_count, document_identifier,
            request_id, progress_cb, mistral_error
        )

    async def _extract_forced_mistral(
        self, extraction_result: Dict[str, Any], pdf_content: bytes, page_count: int, request_id: str
    ) -> None:
        """auto_optimize=False path: use Mistral OCR directly. Mutates
        extraction_result in place."""
        logger.info(f"[{request_id}] Using Mistral OCR directly (auto_optimize=False)")
        pages_requested, total_pages = resolve_ocr_page_window(pdf_content, page_count)
        mistral_text, cost = await self.extract_with_mistral_ocr(pdf_content, pages_requested)

        logger.info(f"[{request_id}] Mistral OCR extraction successful ({len(mistral_text)} chars, ${cost:.4f})")
        extraction_result.update({
            "extracted_content": mistral_text,
            "extraction_method": "Mistral OCR (mistral-ocr-latest)",
            "auto_optimization": "Disabled - Mistral OCR used directly"
        })
        _mark_ocr_page_cap(extraction_result, mistral_text, pages_requested, total_pages)

    @staticmethod
    def _format_extraction_value_error(e: ValueError, request_id: str) -> Dict[str, Any]:
        """Map a ValueError raised anywhere in the hybrid-extraction flow
        (missing/invalid Mistral key, auth/payment failures, OCR timeout,
        daily budget ceiling, feature flag off, upstream non-PDF/oversize
        response) to the dev-mode detail message + 400 envelope. Prod already
        genericizes via format_error_response's status/keyword overrides."""
        msg = str(e)
        logger.error(f"[{request_id}] Validation error: {msg}")
        if "MISTRAL_API_KEY required" in msg:
            detail = f"{msg}. pypdf extraction failed - document may be scanned. To enable OCR, configure MISTRAL_API_KEY."
        elif "authentication failed" in msg or "payment required" in msg or "Mistral API error" in msg:
            detail = f"Mistral OCR request failed: {msg}"
        elif "timed out" in msg:
            detail = f"Mistral OCR request timed out: {msg}"
        elif "capacity limit reached" in msg or "currently disabled" in msg:
            detail = msg
        elif "did not return a PDF" in msg or ("byte" in msg and "limit" in msg):
            detail = f"Document could not be extracted: {msg}"
        else:
            detail = msg
        return format_error_response(
            detail,
            400,
            request_id
        )

    async def extract_document_content_hybrid(
        self,
        petition_id: str,
        document_identifier: str,
        auto_optimize: bool = True,
        progress_cb=None
    ) -> Dict[str, Any]:
        """
        Extract text from petition PDFs with hybrid approach.

        Workflow:
        1. Fetch petition details to get document metadata
        2. Download PDF content directly from the USPTO API
        3. If auto_optimize=True (extraction chain, Lesson 19):
           a. Try pypdf extraction (free)
           b. If poor quality, fall back to Mistral OCR (paid)
           c. If Mistral unavailable/fails, fall back to Docling
              (self-hosted, free; documents <= DOCLING_MAX_PAGES only)
        4. If auto_optimize=False: Use Mistral OCR directly
        5. Return extracted text and extraction metadata

        Args:
            progress_cb: Optional async callable (percent: float, message: str)
                for progress notifications (framework-agnostic — Lesson 20).
        """
        request_id = generate_request_id()

        async def _progress(percent: float, message: str) -> None:
            if progress_cb:
                try:
                    await progress_cb(percent, message)
                except Exception:
                    pass  # progress is best-effort, never load-bearing

        # Check feature flags
        if not feature_flags.is_enabled("ocr_enabled"):
            logger.warning(f"[{request_id}] OCR feature disabled by feature flag")
            return format_error_response(
                "OCR feature is currently disabled",
                503,
                request_id
            )

        try:
            doc_info = await self._resolve_document_for_hybrid_extraction(
                petition_id, document_identifier, request_id
            )
            if "error" in doc_info:
                return doc_info

            document_code = doc_info["document_code"]
            page_count = doc_info["page_count"]
            direct_download_url = doc_info["direct_download_url"]

            # Download the PDF DIRECTLY from the USPTO API with our own key.
            # (Pre-migration this hopped through the download proxies, but the
            # proxy direct routes are now X-Proxy-Token protected and content
            # extraction never needed a browser-facing link in the first place.)
            await _progress(10, f"Downloading PDF ({page_count} pages)...")
            logger.info(f"[{request_id}] Downloading PDF for content extraction ({page_count} pages)")
            # M7/L24: the client's byte-capped, magic-byte-verified streaming
            # download helper (kept on FPDClient — see module docstring).
            pdf_content = await self._download_pdf(direct_download_url)
            logger.info(f"[{request_id}] Downloaded {len(pdf_content)} bytes")
            await _progress(30, "PDF downloaded — extracting text...")

            # Extract text based on auto_optimize setting
            extraction_result = {
                "success": True,
                "document_code": document_code,
                "page_count": page_count,
                "request_id": request_id
            }

            if auto_optimize:
                await self._extract_auto_optimized(
                    extraction_result, pdf_content, page_count,
                    document_identifier, request_id, _progress
                )
            else:
                await self._extract_forced_mistral(
                    extraction_result, pdf_content, page_count, request_id
                )

            return extraction_result

        except ValueError as e:
            return self._format_extraction_value_error(e, request_id)
        except Exception as e:
            logger.error(f"[{request_id}] Error extracting document content: {str(e)}")
            return format_error_response(
                f"Failed to extract document content: {str(e)}",
                500,
                request_id
            )
