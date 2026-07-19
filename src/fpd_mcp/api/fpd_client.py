"""
USPTO Final Petition Decisions API Client

Client for accessing the USPTO Final Petition Decisions API via Open Data Portal.
Requires USPTO API key (same as Patent File Wrapper).
"""

import asyncio
import httpx
import os
import random
from functools import wraps
from typing import Callable, Dict, Any, List, Optional, Tuple
from ..shared.error_utils import (
    format_error_response,
    generate_request_id,
    is_upstream_server_error,
    NotFoundError,
    RateLimitError,
    AuthenticationError,
)
from ..shared.circuit_breaker import CircuitBreaker
from ..shared.cache import CacheManager
from ..shared.uspto_shared_rate_limiter import get_shared_limiter
from ..config import api_constants
from ..shared.unified_logging import get_logger
from ..services.document_extraction import (
    DocumentExtractionService,
    # Re-exported so existing tests that reach into this module directly
    # (e.g. `fpd_client_module._mistral_daily_cost_state`) keep working
    # unchanged — the M3 budget-tracking state/functions now live in
    # services/document_extraction.py alongside the extraction pipeline
    # they guard.
    _mistral_daily_cost_state,  # noqa: F401
    _mistral_daily_spend_check,  # noqa: F401
    _mistral_daily_spend_add,  # noqa: F401
)
from .field_constants import FPDFields, QueryFieldNames

logger = get_logger(__name__)

# M7: hard ceiling on the OCR-path PDF fetch, which (unlike the streaming
# download-proxy routes) previously buffered the full response in memory
# with no size check at all. Kept here (rather than moving to
# DocumentExtractionService with the rest of the extraction pipeline)
# because existing tests monkeypatch this constant via
# `fpd_client_module._MAX_PDF_BYTES` and expect the change to take live
# effect — that only works if the constant and the code reading it
# (`_download_pdf_for_extraction` below) live in the same module.
_MAX_PDF_BYTES = 100 * 1024 * 1024  # 100MB


def _backfill_wrapper_page_counts(document_bag: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backfill the top-level pageCount field onto application file-wrapper
    documentBag entries (used as the get_petition_by_id fallback source —
    see _petition_documents_via_wrapper_fallback).

    FPD's own documentBag entries carry pageCount at the top level (read by
    services/document_extraction.py's hybrid-extraction resolver), but the
    wrapper's raw entries only carry the equivalent pageTotalQuantity nested
    under downloadOptionBag's PDF option — verified live 2026-07-10: without
    this, the content-extraction tool reports page_count: 0 for
    fallback-resolved documents. Additive only; every other field is passed
    through unchanged.
    """
    for doc in document_bag:
        if doc.get(FPDFields.PAGE_COUNT):
            continue
        for option in doc.get(FPDFields.DOWNLOAD_OPTION_BAG, []):
            if option.get(FPDFields.MIME_TYPE_IDENTIFIER) == "PDF":
                page_total = option.get(FPDFields.PAGE_TOTAL_QUANTITY)
                if page_total:
                    doc[FPDFields.PAGE_COUNT] = page_total
                break
    return document_bag


def _client_method_error_handler(method_name: str) -> Callable:
    """Decorator consolidating the 4 identical outer try/except blocks
    previously duplicated in search_petitions, get_petition_by_id,
    search_by_art_unit, and search_by_application: log the failure with the
    method name and return the same 500 error envelope.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {method_name}: {str(e)}")
                return format_error_response(str(e), 500, generate_request_id())
        return wrapper
    return decorator


class FPDClient:
    """Client for USPTO Final Petition Decisions API"""

    # Constants for better readability and maintainability
    DEFAULT_LIMIT = 25
    MAX_SEARCH_LIMIT = 1000
    MAX_CONCURRENT_REQUESTS = 10

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier
    RETRY_429_DELAY = 5.0  # Fixed cool-down for 429s (USPTO's documented etiquette)

    def __init__(self, api_key: Optional[str] = None):
        """Initialize FPD client with USPTO API key"""
        self.base_url = "https://api.uspto.gov/api/v1/petition/decisions"
        # Fallback host for the application file-wrapper documents endpoint
        # (used by get_application_documents when the petition-details
        # includeDocuments=true call 500s upstream — see get_petition_by_id).
        self.applications_base_url = "https://api.uspto.gov/api/v1/patent/applications"

        # Load API key with unified secure storage support. api_key is
        # always assigned before the resolution attempt (previously, if
        # get_uspto_api_key() raised before completing its assignment, the
        # `except: pass` swallowed it but left self.api_key never set at
        # all, so the `if not self.api_key:` check just below would raise
        # AttributeError instead of the intended ValueError).
        self.api_key = None
        try:
            from ..shared_secure_storage import get_uspto_api_key, resolve_api_key
            self.api_key = resolve_api_key(api_key, get_uspto_api_key, "USPTO_API_KEY")
        except Exception as e:
            logger.debug(f"USPTO API key resolution via secure storage failed ({type(e).__name__}); falling back to parameter/env var")
            self.api_key = api_key or os.getenv("USPTO_API_KEY")

        if not self.api_key:
            raise ValueError("USPTO API key is required. Please provide via parameter, secure storage, or USPTO_API_KEY environment variable")

        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Configurable timeouts from environment variables (with fallbacks)
        self.default_timeout = float(os.getenv("USPTO_TIMEOUT", "30.0"))
        self.download_timeout = float(os.getenv("USPTO_DOWNLOAD_TIMEOUT", "60.0"))
        logger.info(f"Timeout configuration: default={self.default_timeout}s, download={self.download_timeout}s")

        # Connection pool limits to prevent exhaustion under high load
        self.connection_limits = httpx.Limits(
            max_connections=api_constants.DEFAULT_MAX_CONNECTIONS,  # Total connections across all hosts
            max_keepalive_connections=api_constants.DEFAULT_MAX_KEEPALIVE_CONNECTIONS,  # Persistent connections to keep alive
            keepalive_expiry=api_constants.DEFAULT_KEEPALIVE_EXPIRY_SECONDS  # Idle timeout for keep-alive connections (seconds)
        )
        logger.info(f"Connection pool limits: max={self.connection_limits.max_connections}, "
                   f"keepalive={self.connection_limits.max_keepalive_connections}")

        # Service-specific semaphore for better resource isolation
        self.uspto_semaphore = asyncio.Semaphore(10)  # USPTO API requests

        # Circuit breaker for resilience
        self.uspto_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            name="USPTO_API"
        )

        # Cache manager for circuit breaker fallback
        self.cache_manager = CacheManager(
            maxsize=api_constants.DEFAULT_CACHE_SIZE,  # Cache up to 100 responses
            ttl=api_constants.DEFAULT_CACHE_TTL_SECONDS  # 10 minute TTL (longer than default for fallback purposes)
        )

        # Hybrid document-text-extraction pipeline (pypdf -> Mistral OCR ->
        # Docling), including the Mistral-tier semaphore/circuit breaker —
        # extracted to services/document_extraction.py (SOLID #3/#4).
        # `mistral_semaphore`/`mistral_circuit_breaker` properties below
        # delegate to it for back-compat.
        self._extraction = DocumentExtractionService(
            client=self,
            download_timeout=self.download_timeout,
            connection_limits=self.connection_limits,
        )

        logger.info("FPD client initialized with USPTO API key, semaphores, circuit breakers, and cache")

    @property
    def mistral_semaphore(self) -> asyncio.Semaphore:
        return self._extraction.mistral_semaphore

    @property
    def mistral_circuit_breaker(self) -> CircuitBreaker:
        return self._extraction.mistral_circuit_breaker

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get status of all circuit breakers for monitoring"""
        return {
            "uspto_api": self.uspto_circuit_breaker.get_state(),
            "mistral_ocr": self.mistral_circuit_breaker.get_state()
        }

    def _map_http_status_error_response(
        self, e: httpx.HTTPStatusError, request_id: str
    ) -> Dict[str, Any]:
        """Map a non-5xx (not retried) HTTPStatusError to the FPDException-
        based error envelope. Extracted from _make_request's retry loop
        (mechanical decomposition, no behavior change) — routes the
        404/429/401 shapes through their dedicated FPDException subclasses
        instead of building the response ad hoc (same envelope either way)."""
        status = e.response.status_code
        message = f"API error: {e.response.text}"
        if status == 404:
            mapped_exc = NotFoundError(message, request_id)
        elif status == 429:
            try:
                retry_after = int(e.response.headers.get("Retry-After", 60))
            except (TypeError, ValueError):
                retry_after = 60
            mapped_exc = RateLimitError(message, retry_after, request_id)
        elif status == 401:
            mapped_exc = AuthenticationError(message, request_id)
        else:
            return format_error_response(message, status, request_id)
        return format_error_response(
            mapped_exc.message, mapped_exc.status_code, mapped_exc.request_id
        )

    def _build_retry_exhausted_response(
        self, last_exception: Optional[Exception], request_id: str
    ) -> Dict[str, Any]:
        """Build the terminal error response once all retry attempts are
        exhausted. Extracted from _make_request's retry loop verbatim."""
        if isinstance(last_exception, httpx.TimeoutException):
            logger.error(f"[{request_id}] Request timeout after {self.RETRY_ATTEMPTS} attempts")
            return format_error_response("Request timeout - please try again", 408, request_id)
        elif isinstance(last_exception, httpx.HTTPStatusError):
            logger.error(
                f"[{request_id}] API error {last_exception.response.status_code} "
                f"after {self.RETRY_ATTEMPTS} attempts"
            )
            return format_error_response(
                f"API error: {last_exception.response.text}",
                last_exception.response.status_code,
                request_id
            )
        else:
            logger.error(f"[{request_id}] Request failed after {self.RETRY_ATTEMPTS} attempts: {str(last_exception)}")
            return format_error_response(f"Request failed: {str(last_exception)}", 500, request_id)

    def _http_status_error_terminal_response(
        self, e: httpx.HTTPStatusError, request_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return a terminal error response for a non-retryable 4xx status,
        or None if the error is retryable (429, or any 5xx). Extracted from
        _execute_request_with_retries's except block to keep its cyclomatic
        complexity under the ruff C901 gate (mechanical decomposition, no
        behavior change)."""
        status = e.response.status_code
        if status == 429 or status >= 500:
            return None
        # Don't retry authentication errors or other client errors (4xx)
        logger.error(f"[{request_id}] API error {status}")
        return self._map_http_status_error_response(e, request_id)

    def _compute_retry_delay(self, attempt: int, last_exception: Optional[Exception]) -> float:
        """Delay before the next retry attempt: a fixed cool-down for 429s
        (USPTO's documented etiquette), exponential backoff + jitter
        otherwise. Extracted from _execute_request_with_retries's retry loop
        to keep its cyclomatic complexity under the ruff C901 gate
        (mechanical decomposition, no behavior change)."""
        if isinstance(last_exception, httpx.HTTPStatusError) and last_exception.response.status_code == 429:
            return self.RETRY_429_DELAY
        delay = self.RETRY_DELAY * (self.RETRY_BACKOFF ** attempt)
        jitter = random.uniform(0.1, 0.5)
        return delay + jitter

    async def _send_once(self, method: str, url: str, **kwargs) -> "httpx.Response":
        """Perform exactly one HTTP send. Extracted out of
        _execute_request_with_retries into its own method (rather than a
        nested closure) so its branches are counted toward ITS OWN
        cyclomatic complexity instead of the retry loop's — mechanical
        decomposition, no behavior change.

        Shared cross-process rate limiter (token + concurrency slot), one
        acquire per ATTEMPT — off unless USPTO_SHARED_RATE_LIMIT_DIR is set.
        This is the single choke point around the actual outbound USPTO HTTP
        send.
        """
        limiter = get_shared_limiter()
        async with httpx.AsyncClient(timeout=self.default_timeout, verify=True, limits=self.connection_limits) as client:
            if method.upper() == "POST":
                send = client.post(url, headers=self.headers, **kwargs)
            else:
                send = client.get(url, headers=self.headers, **kwargs)
            if limiter is not None:
                async with limiter:
                    return await send
            return await send

    async def _execute_request_with_retries(
        self, method: str, url: str, request_id: str, **kwargs
    ) -> Dict[str, Any]:
        """Retry loop for a single logical request, bounded by the
        USPTO-specific semaphore. Extracted out of _make_request into its
        own method (rather than a nested closure) so its branches are no
        longer counted toward _make_request's cyclomatic complexity —
        mechanical decomposition, no behavior change."""
        async with self.uspto_semaphore:
            last_exception = None

            for attempt in range(self.RETRY_ATTEMPTS):
                try:
                    response = await self._send_once(method, url, **kwargs)
                    response.raise_for_status()
                    logger.info(f"[{request_id}] Request successful on attempt {attempt + 1}")
                    return response.json()

                except httpx.HTTPStatusError as e:
                    # 429 is retryable (fixed cool-down — see
                    # _compute_retry_delay) and so is any 5xx; other 4xx
                    # (auth errors, bad requests, etc.) are not.
                    terminal = self._http_status_error_terminal_response(e, request_id)
                    if terminal is not None:
                        return terminal
                    last_exception = e

                except httpx.TimeoutException as e:
                    last_exception = e

                except Exception as e:
                    # Don't retry unexpected errors on final attempt
                    if attempt == self.RETRY_ATTEMPTS - 1:
                        logger.error(f"[{request_id}] Request failed: {str(e)}")
                        return format_error_response(
                            f"Request failed: {str(e)}",
                            500,
                            request_id
                        )
                    last_exception = e

                # Calculate delay: fixed cool-down for 429s, exponential
                # backoff + jitter otherwise (see _compute_retry_delay).
                if attempt < self.RETRY_ATTEMPTS - 1:
                    total_delay = self._compute_retry_delay(attempt, last_exception)

                    logger.warning(
                        f"[{request_id}] Request failed on attempt {attempt + 1}/{self.RETRY_ATTEMPTS}, "
                        f"retrying in {total_delay:.2f}s: {str(last_exception)}"
                    )
                    await asyncio.sleep(total_delay)

            # All retries failed
            return self._build_retry_exhausted_response(last_exception, request_id)

    async def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        base_url: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make HTTP request to FPD API with rate limiting and retry logic.

        base_url: override the default petition-decisions host (used by
        get_application_documents to hit the applications-documents
        endpoint on the same api.uspto.gov host, through the same
        retry/circuit-breaker/shared-limiter plumbing).
        """
        resolved_base_url = base_url or self.base_url
        url = f"{resolved_base_url}/{endpoint.lstrip('/')}"
        request_id = generate_request_id()

        logger.info(f"[{request_id}] Starting {method} request to {endpoint}")

        # Execute through circuit breaker with cache fallback
        try:
            result = await self.uspto_circuit_breaker.call(
                self._execute_request_with_retries, method, url, request_id, **kwargs
            )

            # Cache successful responses for circuit breaker fallback
            if result and not result.get("error"):
                cache_key = f"{method}_{endpoint}"
                self.cache_manager.set(cache_key, result, **kwargs)
                logger.debug(f"[{request_id}] Cached response for {cache_key}")

            return result

        except Exception as e:
            return self._handle_circuit_breaker_error(e, method, endpoint, request_id, **kwargs)

    def _handle_circuit_breaker_error(
        self, e: Exception, method: str, endpoint: str, request_id: str, **kwargs
    ) -> Dict[str, Any]:
        """Cache-fallback handling for a circuit-breaker error raised around
        _execute_request. Extracted from _make_request verbatim (mechanical
        decomposition, no behavior change)."""
        logger.error(f"[{request_id}] Circuit breaker error: {str(e)}")

        # Try cache fallback when circuit is OPEN
        if "Circuit breaker" in str(e) and "OPEN" in str(e):
            logger.warning(f"[{request_id}] Circuit OPEN - attempting cache fallback")

            cache_key = f"{method}_{endpoint}"
            cached_result = self.cache_manager.get(cache_key, **kwargs)

            if cached_result:
                logger.info(f"[{request_id}] Serving stale cached response (circuit OPEN)")

                # Add metadata to indicate cached/degraded response
                cached_result = cached_result.copy()  # Don't modify original cached data
                cached_result["_cached"] = True
                cached_result["_circuit_open"] = True
                cached_result["_warning"] = "Serving cached data - USPTO API temporarily unavailable"
                cached_result["_cache_age_seconds"] = "unknown"  # Could track this if needed
                cached_result["request_id"] = request_id

                return cached_result
            else:
                logger.error(f"[{request_id}] No cached fallback available for {cache_key}")

        # No cache available - return error
        return format_error_response(
            f"Service temporarily unavailable: {str(e)}",
            503,
            request_id
        )

    @_client_method_error_handler("search_petitions")
    async def search_petitions(
        self,
        query: Optional[str] = None,
        filters: Optional[List[Dict]] = None,
        fields: Optional[List[str]] = None,
        sort: Optional[str] = None,
        offset: int = 0,
        limit: int = 25
    ) -> Dict[str, Any]:
        """
        Search petition decisions using FPD API

        Args:
            query: Search query string (supports boolean operators, wildcards)
            filters: List of filter objects with name and value
            fields: Optional list of fields to retrieve for context reduction
            sort: Sort specification (e.g., "petitionMailDate asc")
            offset: Starting position
            limit: Maximum number of results (max 1000)

        Returns:
            Dict containing search results
        """
        # Build request body
        body = {
            "pagination": {
                "limit": min(limit, self.MAX_SEARCH_LIMIT),
                "offset": offset
            }
        }

        # Add query if provided
        if query:
            body["q"] = query

        # Add filters if provided
        if filters:
            body["filters"] = filters

        # Add fields if provided (for context reduction)
        if fields:
            body["fields"] = fields

        # Add sort if provided
        if sort:
            # Parse sort string (e.g., "petitionMailDate asc")
            parts = sort.split()
            if len(parts) == 2:
                body["sort"] = [{
                    "field": parts[0],
                    "order": parts[1]
                }]

        # Content minimization: log the request SHAPE, never the query text
        # (search criteria are client work-product)
        logger.debug(
            f"Search request shape: query_chars={len(str(body.get('q', '')))}, "
            f"filters={len(body.get('filters', []) or [])}, "
            f"fields={len(body.get('fields', []) or [])}, "
            f"pagination={body.get('pagination')}"
        )

        # Use POST for search as per USPTO API spec
        return await self._make_request("search", method="POST", json=body)

    @_client_method_error_handler("get_petition_by_id")
    async def get_petition_by_id(
        self,
        petition_id: str,
        include_documents: bool = False
    ) -> Dict[str, Any]:
        """
        Get specific petition by UUID

        Args:
            petition_id: Petition decision record identifier (UUID)
            include_documents: Whether to include document bag

        Returns:
            Dict containing petition details

        Fallback (verified live 2026-07-10): USPTO's petition-details
        endpoint 500s upstream for includeDocuments=true (broken since at
        least 2026-07-04); `include_documents=False` works fine. When the
        with-documents call comes back as a 5xx-class error envelope, this
        transparently retries without documents and reconstructs documentBag
        from the application file-wrapper documents endpoint (FPD documentBag
        identifiers are also application file-wrapper document identifiers —
        verified live). Non-5xx errors (404/401/etc.) are returned unchanged.
        """
        # Build query parameters
        params = {}
        if include_documents:
            params["includeDocuments"] = "true"

        # Make GET request to specific petition endpoint
        result = await self._make_request(
            f"{petition_id}",
            method="GET",
            params=params
        )

        if include_documents and is_upstream_server_error(result):
            return await self._petition_documents_via_wrapper_fallback(petition_id)

        return result

    async def _petition_documents_via_wrapper_fallback(
        self, petition_id: str
    ) -> Dict[str, Any]:
        """Reconstruct documentBag from the application file-wrapper
        documents endpoint after the primary includeDocuments=true call
        failed upstream (see get_petition_by_id docstring). Degrades
        gracefully to the plain without-documents result (still correct,
        just without documentBag) if either the without-documents retry or
        the wrapper fetch itself also fails — only the additive
        document_metadata_source/document_metadata_note keys are withheld in
        that case, no existing key is ever altered.
        """
        without_docs = await self.get_petition_by_id(petition_id, include_documents=False)
        if "error" in without_docs:
            return without_docs

        petition_data = without_docs.get(FPDFields.PETITION_DECISION_DATA_BAG, [])
        if not petition_data:
            return without_docs

        application_number = petition_data[0].get(FPDFields.APPLICATION_NUMBER_TEXT)
        if not application_number:
            return without_docs

        wrapper_result = await self.get_application_documents(application_number)
        if "error" in wrapper_result:
            logger.warning(
                "Document-bag wrapper fallback also failed for application "
                f"{application_number}; returning petition details without documents"
            )
            return without_docs

        petition_data[0][FPDFields.DOCUMENT_BAG] = _backfill_wrapper_page_counts(
            wrapper_result.get(FPDFields.DOCUMENT_BAG, [])
        )
        without_docs["document_metadata_source"] = "application_file_wrapper_fallback"
        without_docs["document_metadata_note"] = (
            "USPTO's petition-details includeDocuments=true endpoint is "
            "currently erroring upstream; documentBag was reconstructed from "
            "the application file wrapper (the same underlying documents)."
        )
        return without_docs

    @_client_method_error_handler("get_application_documents")
    async def get_application_documents(self, application_number: str) -> Dict[str, Any]:
        """
        Fetch the application file-wrapper documentBag for an application
        number via the ODP applications-documents endpoint (same
        api.uspto.gov host and API key as petition decisions, routed through
        the same retry/circuit-breaker/shared-limiter plumbing). Used as the
        fallback source of document metadata when the petition-details
        includeDocuments=true call fails upstream — see get_petition_by_id.

        Args:
            application_number: USPTO application number

        Returns:
            Dict containing documentBag (and other applications-documents
            response fields), or an error envelope
        """
        return await self._make_request(
            f"{application_number}/documents",
            method="GET",
            base_url=self.applications_base_url,
        )

    @_client_method_error_handler("search_by_art_unit")
    async def search_by_art_unit(
        self,
        art_unit: str,
        date_range: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Search petitions by art unit number

        Args:
            art_unit: Art unit number (e.g., "2128")
            date_range: Optional date range filter (e.g., "2020-01-01:2024-12-31")
            limit: Maximum number of results

        Returns:
            Dict containing search results
        """
        # Build query
        query = f"{QueryFieldNames.ART_UNIT}:{art_unit}"

        # Build filters for date range if provided
        filters = []
        if date_range:
            # Parse date range
            parts = date_range.split(":")
            if len(parts) == 2:
                filters.append({
                    "field": FPDFields.PETITION_MAIL_DATE,
                    "valueFrom": parts[0],
                    "valueTo": parts[1]
                })

        return await self.search_petitions(
            query=query,
            filters=filters if filters else None,
            limit=limit
        )

    @_client_method_error_handler("search_by_application")
    async def search_by_application(
        self,
        application_number: str,
        include_documents: bool = False
    ) -> Dict[str, Any]:
        """
        Search petitions for specific application number

        Args:
            application_number: USPTO application number
            include_documents: Whether to include document bag

        Returns:
            Dict containing search results
        """
        # Build query
        query = f"{QueryFieldNames.APPLICATION_NUMBER}:{application_number}"

        # Build fields list
        fields = None
        if not include_documents:
            # Exclude documentBag for context reduction
            fields = [
                FPDFields.PETITION_DECISION_RECORD_IDENTIFIER,
                FPDFields.APPLICATION_NUMBER_TEXT,
                FPDFields.PATENT_NUMBER,
                FPDFields.FIRST_APPLICANT_NAME,
                FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT,
                FPDFields.PETITION_MAIL_DATE,
                FPDFields.DECISION_DATE,
                FPDFields.FINAL_DECIDING_OFFICE_NAME,
                FPDFields.DECISION_PETITION_TYPE_CODE,
                FPDFields.DECISION_PETITION_TYPE_CODE_DESCRIPTION_TEXT,
                FPDFields.GROUP_ART_UNIT_NUMBER,
                FPDFields.TECHNOLOGY_CENTER,
                FPDFields.PROSECUTION_STATUS_CODE_DESCRIPTION_TEXT,
                FPDFields.PETITION_ISSUE_CONSIDERED_TEXT_BAG,
                FPDFields.RULE_BAG,
                FPDFields.STATUTE_BAG
            ]

        return await self.search_petitions(
            query=query,
            fields=fields,
            limit=100
        )

    async def _download_pdf_for_extraction(self, download_url: str) -> bytes:
        """Stream a PDF from the USPTO API with a running byte-count cap and
        verify the first chunk actually starts with the PDF magic number
        before trusting USPTO's self-reported mimeTypeIdentifier field
        (M7/L24). Extracted from extract_document_content_hybrid; kept on
        FPDClient (see module-level `_MAX_PDF_BYTES` comment) rather than
        moved into DocumentExtractionService.
        """
        async with httpx.AsyncClient(
            timeout=self.download_timeout,
            limits=self.connection_limits,
            follow_redirects=True
        ) as client:
            async with client.stream(
                "GET",
                download_url,
                headers={"X-API-KEY": self.api_key, "Accept": "application/pdf"}
            ) as pdf_response:
                pdf_response.raise_for_status()
                chunks: List[bytes] = []
                total_bytes = 0
                first_chunk = True
                async for chunk in pdf_response.aiter_bytes(8192):
                    if first_chunk:
                        if not chunk.startswith(b"%PDF-"):
                            raise ValueError(
                                "Upstream did not return a PDF document"
                            )
                        first_chunk = False
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_PDF_BYTES:
                        raise ValueError(
                            f"Document exceeds the {_MAX_PDF_BYTES} byte "
                            "extraction limit"
                        )
                    chunks.append(chunk)
                pdf_content = b"".join(chunks)
        return pdf_content

    # ------------------------------------------------------------------
    # Hybrid document-text-extraction pipeline: thin delegating methods.
    # The pipeline itself (pypdf -> Mistral OCR -> Docling tiers, M3 budget
    # tracking, Mistral breaker/semaphore) now lives in
    # services/document_extraction.py (SOLID #3/#4). Public signatures are
    # UNCHANGED — tools and tests call these FPDClient methods directly.
    # ------------------------------------------------------------------

    def is_good_extraction(self, text: str) -> bool:
        """Determine if PyPDF2 extraction is usable or if we need Mistral OCR."""
        return self._extraction.is_good_extraction(text)

    async def extract_with_pypdf2(
        self, pdf_content: bytes, max_pages: int = 200
    ) -> Tuple[str, bool]:
        """Extract text using pypdf (free, fast, works for text-based PDFs)."""
        return await self._extraction.extract_with_pypdf2(pdf_content, max_pages)

    async def extract_with_mistral_ocr(self, pdf_content: bytes, page_count: int = 0) -> Tuple[str, float]:
        """Extract text using Mistral OCR API (no poppler/pdf2image required)."""
        return await self._extraction.extract_with_mistral_ocr(pdf_content, page_count)

    async def extract_document_content_hybrid(
        self,
        petition_id: str,
        document_identifier: str,
        auto_optimize: bool = True,
        progress_cb=None
    ) -> Dict[str, Any]:
        """Extract text from petition PDFs with hybrid approach (pypdf ->
        Mistral OCR -> Docling)."""
        return await self._extraction.extract_document_content_hybrid(
            petition_id, document_identifier, auto_optimize, progress_cb
        )
