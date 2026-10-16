"""
USPTO Final Petition Decisions API Client

Client for accessing the USPTO Final Petition Decisions API via Open Data Portal.
Requires USPTO API key (same as Patent File Wrapper).
"""

import asyncio
import copy
import contextlib
import httpx
import math
import os
import random
from functools import wraps
from typing import Callable, Dict, Any, List, Optional, Tuple
from ..shared.error_utils import (
    format_error_response,
    generate_request_id,
    NotFoundError,
    RateLimitError,
    RateLimitedError,
    AuthenticationError,
)
from ..shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from ..shared.cache import CacheManager
from ..shared.uspto_shared_rate_limiter import (
    SharedLimiterTimeoutError,
    get_shared_limiter,
    note_429,
)
from ..config import api_constants
from ..shared.unified_logging import get_logger
from ..shared.uspto_hosts import USPTO_KEY_EVENT_HOOKS
from ..util.deadline import (
    MIN_ATTEMPT_SECONDS,
    DeadlineExceeded,
    current_deadline,
    deadline_exceeded_response,
    is_deadline_exceeded,
    room_for,
    run_within_deadline,
)
from ..services.document_extraction import (
    DocumentExtractionService,
    # Re-exported so existing tests that reach into this module directly
    # (e.g. `fpd_client_module._mistral_daily_cost_state`) keep working
    # unchanged — the M3 budget-tracking state/functions now live in
    # services/document_extraction.py alongside the extraction pipeline
    # they guard.
    _mistral_daily_cost_state,  # noqa: F401
    _mistral_daily_spend_reserve,  # noqa: F401
    _mistral_daily_spend_release,  # noqa: F401
    _mistral_daily_spend_settle,  # noqa: F401
    _mistral_daily_spend_add,  # noqa: F401
)
from .field_constants import FPDFields, QueryFieldNames
from .payload_compat import (
    FINAL_ONLY_CLAUSE,
    backfill_page_counts,
    normalize_response,
    upstream_fields,
)

logger = get_logger(__name__)

# M7: hard ceiling on the OCR-path PDF fetch, which (unlike the streaming
# download-proxy routes) previously buffered the full response in memory
# with no size check at all. Kept here (rather than moving to
# DocumentExtractionService with the rest of the extraction pipeline)
# because existing tests monkeypatch this constant via
# `fpd_client_module._MAX_PDF_BYTES` and expect the change to take live
# effect — that only works if the constant and the code reading it
# (`_download_pdf_for_extraction` below) live in the same module.
# M-18: lowered from 100 MB to a petition-realistic 25 MB. A petition
# decision plus its file-wrapper papers does not reach 25 MB; the old ceiling
# admitted a body two orders of magnitude larger than any real document into
# a buffer that then feeds an in-memory pypdf parse. Override with
# FPD_MAX_PDF_BYTES for an unusual corpus.
def _max_pdf_bytes_from_env() -> int:
    raw = os.getenv("FPD_MAX_PDF_BYTES", "")
    if not raw.strip():
        return 25 * 1024 * 1024
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning("Invalid FPD_MAX_PDF_BYTES; using 25MB")
        return 25 * 1024 * 1024


_MAX_PDF_BYTES = _max_pdf_bytes_from_env()

# M-18: bound how many extractions can hold a buffered PDF at once. The byte
# cap bounds ONE download; nothing bounded the number of concurrent ones, so
# the real memory ceiling was cap x in-flight calls.
_MAX_CONCURRENT_EXTRACTIONS = 3
_extraction_slots = asyncio.Semaphore(_MAX_CONCURRENT_EXTRACTIONS)


class UpstreamFailure(Exception):
    """A USPTO failure that has exhausted its retry budget, carried as an
    exception so `CircuitBreaker.call` counts it.

    The retry loop used to RETURN a `format_error_response` envelope for
    every failure mode, and the breaker only increments `failure_count` in
    its `except` block, so it recorded a success on every upstream outage and
    could never open (error-handling-resilience F-E1, reproduced with 36
    mocked 503s). `_make_request` unwraps this back into the same envelope,
    so no caller sees a behavior change beyond the breaker now working.

    Non-retryable 4xx deliberately still return normally: a 404 is not an
    upstream health signal.
    """

    def __init__(self, envelope: Dict[str, Any]):
        self.envelope = envelope
        super().__init__(str(envelope.get("error", "upstream failure")))


def _backfill_wrapper_page_counts(document_bag: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backfill the top-level pageCount field onto documentBag entries that
    carry it only inside downloadOptionBag's PDF option.

    Verified live 2026-07-10 for the application file-wrapper bag (without
    it the content tool reported page_count: 0), and true of the native FPD
    bag too since the 2026-10 payload change. Additive only; the logic lives
    in api/payload_compat.backfill_page_counts.
    """
    return backfill_page_counts(document_bag)


def _retry_after_seconds(exc: Exception, default: float = 0.0) -> float:
    """Seconds the upstream asked us to wait, from its Retry-After header.

    F-R3: this header was parsed in one place, stored on a RateLimitError
    nobody read, and ignored entirely by the retry loop. Only the
    delta-seconds form is honored; an HTTP-date Retry-After returns the
    default rather than guessing at clock skew.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return default
    try:
        return max(0.0, float(response.headers.get("Retry-After", default)))
    except (TypeError, ValueError):
        return default


# The 429 rule,
# shared by every ODP call site in this client. On a 429: note it on the
# shared key cooldown, then wait max(5 s, Retry-After) and send ONCE more,
# but only when that wait is at most RATE_LIMIT_ABSORB_CEILING_SECONDS and
# fits what is left of the call's time budget (util/deadline.py); otherwise
# answer with the rate-limit envelope and let the caller retry after
# `retry_after_seconds`. Never a second retry. 5 s is USPTO's own published
# floor ("no retry without at least a 5 s delay"), so absorbing a 429 with no
# Retry-After is not sleeping blind. The wait holds no shared slot and no
# bulkhead slot: _send_once released both when the response came back.
RATE_LIMIT_WAIT_FLOOR_SECONDS = 5.0
RATE_LIMIT_ABSORB_CEILING_SECONDS = 10.0

#: `rate_limit_source` values: USPTO's own 429 versus this deployment's
#: shared cross-process limiter refusing to wait any longer.
RATE_LIMIT_SOURCE_UPSTREAM = "uspto_api"
RATE_LIMIT_SOURCE_SHARED_LIMITER = "shared_uspto_limiter"


def retry_after_seconds(response) -> Optional[float]:
    """The Retry-After header as seconds, or None when absent or not a
    number (the HTTP-date form is not used by ODP and is treated as absent)."""
    raw = response.headers.get("Retry-After") if response is not None else None
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def planned_429_wait(
    retry_after: Optional[float], already_retried: bool, remaining_budget: float
) -> Optional[float]:
    """Seconds to wait before the single 429 retry, or None for "answer with
    the envelope now". Pure so the rule is testable without a network."""
    if already_retried:
        return None
    wait = max(RATE_LIMIT_WAIT_FLOOR_SECONDS, retry_after or 0.0)
    if wait > RATE_LIMIT_ABSORB_CEILING_SECONDS or wait > remaining_budget:
        return None
    return wait


def remaining_429_budget() -> float:
    """Seconds the running call can still spend on the single 429 wait and
    leave room for the retry itself (util/deadline.py); unbounded outside a
    call with a time budget."""
    deadline = current_deadline()
    if deadline is None:
        return math.inf
    return max(0.0, deadline.remaining() - MIN_ATTEMPT_SECONDS)


def rate_limited_envelope(
    retry_after: Optional[float],
    source: str,
    request_id: Optional[str] = None,
    response=None,
) -> Dict[str, Any]:
    """The structured answer to a call refused for pacing. `rate_limited`
    is the key a caller branches on; `retry_after_seconds` is always a
    number and never below USPTO's 5 s floor. `retry_after` (whole seconds)
    is the key the earlier 429 envelope carried and is kept in step."""
    wait = max(RATE_LIMIT_WAIT_FLOOR_SECONDS, retry_after or 0.0)
    if response is not None:
        try:
            detail = response.text
        except httpx.StreamError:  # a streamed body never read
            detail = ""
        envelope = format_error_response(f"API error: {detail}", 429, request_id)
    else:
        envelope = format_error_response(
            f"Rate limited. Retry this call once in {wait:.0f} seconds.",
            429,
            request_id,
            authored=True,
        )
    envelope["rate_limited"] = True
    envelope["retry_after"] = int(math.ceil(wait))
    envelope["retry_after_seconds"] = round(float(wait), 2)
    envelope["rate_limit_source"] = source
    return envelope


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
                # F-D4 / F-X5: this catch-all absorbs programming errors too
                # (an AttributeError in _attach_documents_to_search_hits used
                # to become "Internal server error occurred" with no traceback
                # anywhere), so it logs one.
                logger.error(
                    f"Error in {method_name}: {type(e).__name__}", exc_info=True
                )
                return format_error_response(str(e), 500, generate_request_id())
        return wrapper
    return decorator


class FPDClient:
    """Client for USPTO Final Petition Decisions API"""

    # Constants for better readability and maintainability.
    # MAX_SEARCH_LIMIT is deliberately the SAME value the tool layer
    # validates against (api_constants.MAX_SEARCH_LIMIT): a client ceiling
    # that differs from the tool ceiling clamps silently, so an envelope
    # could report a requested limit the request never actually used.
    DEFAULT_LIMIT = 25
    MAX_SEARCH_LIMIT = api_constants.MAX_SEARCH_LIMIT
    MAX_CONCURRENT_REQUESTS = 10

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier
    # The floor on the single 429 wait (USPTO's documented etiquette); the
    # rule itself is planned_429_wait / _absorb_429. The earlier
    # 30 s MAX_RETRY_AFTER_SECONDS sleep cap is gone: a Retry-After over the
    # 10 s absorb ceiling is answered with the envelope, not slept on.
    RETRY_429_DELAY = RATE_LIMIT_WAIT_FLOOR_SECONDS

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
            # F-E10: logged at DEBUG, so an operator whose secure store was
            # misconfigured saw nothing at INFO and the server silently ran
            # on whatever the environment happened to hold.
            logger.warning(
                f"USPTO API key resolution via secure storage failed "
                f"({type(e).__name__}); falling back to parameter/env var"
            )
            self.api_key = api_key or os.getenv("USPTO_API_KEY")

        if not self.api_key:
            raise ValueError("USPTO API key is required. Please provide via parameter, secure storage, or USPTO_API_KEY environment variable")

        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # F-R7: one pooled httpx client per FPDClient, built on first send.
        self._http_client: Optional[httpx.AsyncClient] = None

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
        # F-R9: MAX_CONCURRENT_REQUESTS was declared and then never read;
        # the real bulkhead was a literal 10 three dozen lines away.
        self.uspto_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)

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
            mapped_exc = RateLimitError(
                message, request_id,
                retry_after=int(_retry_after_seconds(e, default=60.0)),
            )
        elif status == 401:
            mapped_exc = AuthenticationError(message, request_id)
        else:
            return format_error_response(message, status, request_id)
        envelope = format_error_response(
            mapped_exc.message, mapped_exc.status_code, mapped_exc.request_id
        )
        # F-R3: the parsed wait was dropped on the floor. Tell the caller how
        # long the upstream asked for so it can back off too.
        if isinstance(mapped_exc, RateLimitError):
            envelope["retry_after"] = mapped_exc.retry_after
        return envelope

    def _build_retry_exhausted_response(
        self, last_exception: Optional[Exception], request_id: str
    ) -> Dict[str, Any]:
        """Build the terminal error response once all retry attempts are
        exhausted. Extracted from _make_request's retry loop verbatim.

        The caller RAISES this envelope inside `UpstreamFailure` rather than
        returning it: `CircuitBreaker.call` counts raised exceptions, so a
        returned envelope read as a success and the USPTO breaker could never
        open (error-handling-resilience F-E1)."""
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
        or None if the error is retryable (any 5xx). A 429 never reaches
        this: _on_http_status_error applies the 429 rule first. Extracted
        from _execute_request_with_retries's except block to keep its
        cyclomatic complexity under the ruff C901 gate."""
        status = e.response.status_code
        if status >= 500:
            return None
        # Don't retry authentication errors or other client errors (4xx)
        logger.error(f"[{request_id}] API error {status}")
        return self._map_http_status_error_response(e, request_id)

    def _compute_retry_delay(self, attempt: int, last_exception: Optional[Exception]) -> float:
        """Delay before the next retry attempt on a 5xx or a transport
        failure: exponential backoff + jitter. A 429 never comes through
        here since the rate-limit wave: its single wait is
        planned_429_wait's, applied by _absorb_429."""
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

        Inside a call with a time budget (util/deadline.py: the content tool,
        petition details with documents) the attempt, limiter wait included,
        runs only on what is left of it and raises DeadlineExceeded when cut.
        """
        limiter = get_shared_limiter()
        client = self._get_http_client()

        async def attempt() -> "httpx.Response":
            # S62: the bulkhead slot is held for the send only, never across
            # a retry wait, so a throttled request does not starve the rest.
            async with self.uspto_semaphore:
                if method.upper() == "POST":
                    send = client.post(url, headers=self.headers, **kwargs)
                else:
                    send = client.get(url, headers=self.headers, **kwargs)
                if limiter is not None:
                    async with limiter:
                        return await send
                return await send

        return await run_within_deadline(attempt)

    def _get_http_client(self) -> "httpx.AsyncClient":
        """The one httpx client this FPDClient sends through.

        F-R7: a fresh `httpx.AsyncClient` used to be created and closed inside
        every single send, so `self.connection_limits` — configured in
        __init__ and logged at startup as if it were a process-wide pool — was
        reset to an empty pool on every request and no connection was ever
        reused. Every USPTO call paid a fresh TCP + TLS handshake.

        Created lazily rather than in __init__ so the tests that patch
        `fpd_client_module.httpx.AsyncClient` before the first request still
        get their MockTransport.

        The key event hook (shared/uspto_hosts.py) strips the key off any
        non-uspto.gov hop: every petition search, details and file-wrapper
        request passes through here.
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.default_timeout,
                verify=True,
                limits=self.connection_limits,
                event_hooks=USPTO_KEY_EVENT_HOOKS,
            )
        return self._http_client

    async def aclose(self) -> None:
        """Close the pooled HTTP client. Safe to call more than once."""
        client, self._http_client = self._http_client, None
        if client is not None:
            try:
                await client.aclose()
            except Exception as e:  # pragma: no cover - shutdown path
                logger.debug(f"HTTP client close failed: {type(e).__name__}")

    async def _wait_before_retry(
        self, attempt: int, last_exception: Optional[Exception], request_id: str
    ) -> bool:
        """Sleep the retry delay and return True, or return False without
        sleeping when this was the last attempt, or when the call's time
        budget (util/deadline.py) would not leave room for another attempt
        after the wait: the last status is then the answer. Extracted from
        _execute_request_with_retries to keep it under the complexity gate."""
        if attempt >= self.RETRY_ATTEMPTS - 1:
            return False
        total_delay = self._compute_retry_delay(attempt, last_exception)
        if not room_for(total_delay):
            logger.warning(
                f"[{request_id}] Not retrying: a {total_delay:.2f}s wait would "
                "leave no room in the call's time budget"
            )
            return False
        logger.warning(
            f"[{request_id}] Request failed on attempt {attempt + 1}/{self.RETRY_ATTEMPTS}, "
            f"retrying in {total_delay:.2f}s: {str(last_exception)}"
        )
        await asyncio.sleep(total_delay)
        return True

    async def _absorb_429(
        self, response, already_retried: bool, request_id: str
    ) -> Optional[Dict[str, Any]]:
        """Apply the 429 rule to one 429 response: note it on the
        shared key cooldown, then either sleep the single allowed wait and
        return None (the caller sends once more) or return the rate-limit
        envelope. No shared slot and no bulkhead slot is held here: the send
        that saw the 429 released both when the response came back."""
        retry_after = retry_after_seconds(response)
        note_429(retry_after)
        wait = planned_429_wait(retry_after, already_retried, remaining_429_budget())
        if wait is None:
            logger.error(f"[{request_id}] API error 429, answering with the envelope")
            return rate_limited_envelope(
                retry_after, RATE_LIMIT_SOURCE_UPSTREAM, request_id, response=response
            )
        logger.warning(f"[{request_id}] API error 429, one retry in {wait:.0f}s")
        await asyncio.sleep(wait)
        return None

    async def _on_http_status_error(
        self, e: httpx.HTTPStatusError, retried_429: bool, request_id: str
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """One HTTPStatusError inside the attempt loop: (terminal envelope or
        None, send once more right now). A 429 goes through the 429 rule;
        any other 4xx is terminal; a 5xx is left to the backoff retry."""
        if e.response.status_code == 429:
            envelope = await self._absorb_429(e.response, retried_429, request_id)
            return envelope, envelope is None
        return self._http_status_error_terminal_response(e, request_id), False

    async def _execute_request_with_retries(
        self, method: str, url: str, request_id: str, **kwargs
    ) -> Dict[str, Any]:
        """Retry loop for a single logical request: up to RETRY_ATTEMPTS
        sends with exponential backoff on a 5xx, a timeout or a transport
        failure, the single 429 retry (which spends no attempt), and
        an immediate envelope on any other 4xx. Extracted out of
        _make_request so its branches are not counted toward _make_request's
        cyclomatic complexity.

        The shared limiter's refusal (SharedLimiterTimeoutError, a
        TimeoutError: no slot inside USPTO_SHARED_MAX_WAIT_SECONDS) is
        answered at once with the rate-limit envelope and never retried: a
        retry would only queue again behind the same backlog. Returned, not
        raised, so the circuit breaker does not read local pacing as an
        upstream outage.

        The USPTO bulkhead (uspto_semaphore) is taken per attempt inside
        _send_once, so the slot is free while the loop waits to retry (S62)."""
        last_exception = None
        retried_429 = False
        attempt = 0

        while attempt < self.RETRY_ATTEMPTS:
            try:
                response = await self._send_once(method, url, **kwargs)
                response.raise_for_status()
                logger.info(f"[{request_id}] Request successful on attempt {attempt + 1}")
                return response.json()

            except DeadlineExceeded:
                # The CALL's budget ran out (util/deadline.py), not the
                # upstream: returned like a 4xx, so the breaker does not
                # count it as an outage.
                logger.warning(f"[{request_id}] Stopped at the call's time budget")
                return deadline_exceeded_response(request_id)

            except SharedLimiterTimeoutError as e:
                logger.warning(f"[{request_id}] shared limiter refusal: {e}")
                return rate_limited_envelope(None, RATE_LIMIT_SOURCE_SHARED_LIMITER, request_id)

            except httpx.HTTPStatusError as e:
                terminal, send_again = await self._on_http_status_error(
                    e, retried_429, request_id
                )
                if terminal is not None:
                    return terminal
                if send_again:
                    retried_429 = True
                    continue  # the one 429 retry does not spend an attempt
                last_exception = e

            except Exception as e:
                # A timeout, a transport failure or anything unexpected:
                # retried with backoff; after the last attempt the exhausted
                # envelope below carries it (408 for a timeout, else 500).
                last_exception = e

            # Exponential backoff + jitter (see _compute_retry_delay), or
            # stop when this was the last attempt or the wait would not fit.
            if not await self._wait_before_retry(attempt, last_exception, request_id):
                break
            attempt += 1

        # All retries failed. RAISE so the circuit breaker records the
        # failure; _make_request converts it back into the same envelope.
        raise UpstreamFailure(
            self._build_retry_exhausted_response(last_exception, request_id)
        )

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
                # S61: a copy, never the object handed back to the caller.
                # get_petition_by_id trims the documentBag and the record list
                # of the result in place; caching the same object let that
                # trim hollow out the fallback a later caller would be served.
                self.cache_manager.set(cache_key, copy.deepcopy(result), **kwargs)
                logger.debug(f"[{request_id}] Cached response for {cache_key}")

            return result

        except UpstreamFailure as e:
            # An upstream failure the breaker has now counted. Hand back the
            # envelope the retry loop already built — the status mapping
            # (408 on timeout, the upstream status on a 5xx) is preserved.
            return e.envelope

        except Exception as e:
            return self._handle_circuit_breaker_error(e, method, endpoint, request_id, **kwargs)

    def _handle_circuit_breaker_error(
        self, e: Exception, method: str, endpoint: str, request_id: str, **kwargs
    ) -> Dict[str, Any]:
        """Cache-fallback handling for a circuit-breaker error raised around
        _execute_request."""
        logger.error(f"[{request_id}] Circuit breaker error: {str(e)}")

        # Try cache fallback when circuit is OPEN. Branching on the typed
        # error rather than the message: with the breaker actually counting
        # failures, real upstream exceptions now travel this path too.
        if isinstance(e, CircuitBreakerOpenError):
            logger.warning(f"[{request_id}] Circuit OPEN - attempting cache fallback")

            cache_key = f"{method}_{endpoint}"
            cached_result = self.cache_manager.get(cache_key, **kwargs)

            if cached_result:
                logger.info(f"[{request_id}] Serving stale cached response (circuit OPEN)")

                # Add metadata to indicate cached/degraded response
                # S61: a deep copy, so this caller's trims never reach the
                # cached original (a shallow copy shared the nested bags).
                cached_result = copy.deepcopy(cached_result)
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
        limit: int = 25,
        range_filters: Optional[List[Dict]] = None,
        facets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Search petition decisions using FPD API

        Args:
            facets: field names to count values on, sent as the body's
                `facets` list. The response then carries
                `facets: {field: [{value, count}, ...]}`, each list sorted by
                count descending and capped at 1,000 values upstream; a field
                the endpoint does not know comes back as an empty list, not an
                error (probed 2026-10-06, docs/PETITION-STATISTICS.md).
            query: Search query string (supports boolean operators, wildcards)
            filters: List of exact-match filter objects (`name` + `value` list)
            fields: Optional list of fields to retrieve for context reduction
            sort: Sort specification (e.g., "petitionMailDate asc")
            offset: Starting position
            limit: Maximum number of results (clamped to MAX_SEARCH_LIMIT)
            range_filters: List of `{field, valueFrom, valueTo}` objects, sent
                as the request body's `rangeFilters`. This is the ONLY body key
                the endpoint accepts a date/number range under — see
                search_by_art_unit.

        Returns:
            Dict containing search results
        """
        # Build request body. The clamp is the tool layer's MAX_SEARCH_LIMIT,
        # not a separate (larger) client-only ceiling: a client clamp that
        # silently differs from what the tools validate means an envelope can
        # report a limit the request never used. Clamping is logged.
        applied_limit = max(1, min(limit, self.MAX_SEARCH_LIMIT))
        if applied_limit != limit:
            logger.warning(
                f"Search limit {limit} clamped to {applied_limit} "
                f"(client ceiling MAX_SEARCH_LIMIT={self.MAX_SEARCH_LIMIT})"
            )
        body: Dict[str, Any] = {
            "pagination": {
                "limit": applied_limit,
                "offset": offset
            }
        }

        # Add query if provided
        if query:
            body["q"] = query

        # Add filters if provided
        if filters:
            body["filters"] = filters

        # Add range filters if provided (dates/numbers live under their own
        # body key upstream — `filters` rejects a valueFrom/valueTo object)
        if range_filters:
            body["rangeFilters"] = range_filters

        if facets:
            body["facets"] = list(facets)

        # Add fields if provided (for context reduction). A legacy outcome
        # name gets its 2026-10 name beside it (api/payload_compat.py).
        if fields:
            body["fields"] = upstream_fields(fields)

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

        # Use POST for search as per USPTO API spec. Records are normalised
        # to this server's representation (api/payload_compat.py).
        return normalize_response(
            await self._make_request("search", method="POST", json=body)
        )

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

        2026-10 payload change (probed live 2026-10-05, see
        docs/UPSTREAM-FPD-API-CHANGE-2026-10.md): the plain details call
        now carries the petition's own documentBag (the decision papers,
        with download options), so includeDocuments is NOT sent. Sending
        includeDocuments=true now answers 200 with the first page of the
        WHOLE corpus (count ~1.1 million, 25 unrelated records), which made
        every download and every details-with-documents call read some other
        petition's bag; before 2026-10 the same call answered HTTP 500.

        The response is narrowed to the record whose identifier is the one
        asked for, so an upstream that answers with a list can never hand
        back a different petition. include_documents=False drops the bag;
        include_documents=True keeps it, and only a petition whose own bag is
        empty falls back to the application file wrapper.
        """
        result = await self._make_request(f"{petition_id}", method="GET")
        if "error" in result:
            return result

        records = result.get(FPDFields.PETITION_DECISION_DATA_BAG)
        if isinstance(records, list) and records:
            matching = [
                r for r in records
                if isinstance(r, dict)
                and r.get(FPDFields.PETITION_DECISION_RECORD_IDENTIFIER) == petition_id
            ]
            if not matching:
                logger.warning(
                    "Petition-details response did not contain the requested "
                    f"petition ({len(records)} other record(s)); answering 404"
                )
                return format_error_response(
                    f"Petition {petition_id} not found (the upstream answer did "
                    "not contain this petition)",
                    404,
                    generate_request_id(),
                )
            result[FPDFields.PETITION_DECISION_DATA_BAG] = matching[:1]
            if isinstance(result.get("count"), int):
                result["count"] = 1

        normalize_response(result)

        records = result.get(FPDFields.PETITION_DECISION_DATA_BAG) or []
        if not include_documents:
            for record in records:
                if isinstance(record, dict):
                    record.pop(FPDFields.DOCUMENT_BAG, None)
            return result

        if records and isinstance(records[0], dict) and records[0].get(FPDFields.DOCUMENT_BAG):
            result["document_metadata_available"] = True
            result["document_metadata_source"] = "petition_record"
            result["document_metadata_note"] = (
                "documentBag is this petition's own document list as USPTO "
                "serves it on the petition record (the decision and any papers "
                "filed or issued with it), not the application's file wrapper."
            )
            return result

        return await self._petition_documents_via_wrapper_fallback(result)

    async def _petition_documents_via_wrapper_fallback(
        self, petition_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Reconstruct documentBag from the application file-wrapper
        documents endpoint for a petition whose own documentBag is empty or
        absent (see get_petition_by_id docstring). Degrades gracefully to the
        petition without a documentBag if the wrapper fetch itself fails.

        A degraded result is ALWAYS marked: an absent documentBag must never
        be indistinguishable from a petition that genuinely has no documents.
        No existing key is ever altered; only the additive
        document_metadata_* keys are set.
        """
        petition_data = petition_result.get(FPDFields.PETITION_DECISION_DATA_BAG, [])
        if not petition_data:
            return petition_result

        application_number = petition_data[0].get(FPDFields.APPLICATION_NUMBER_TEXT)
        if not application_number:
            return self._mark_document_metadata_unavailable(
                petition_result,
                "the petition record carries no documentBag and no application "
                "number to look documents up by",
            )

        wrapper_result = await self.get_application_documents(application_number)
        if is_deadline_exceeded(wrapper_result):
            # The call's time budget ran out, which says nothing about the
            # petition's documents: say so rather than "metadata unavailable".
            return wrapper_result
        if "error" in wrapper_result:
            logger.warning(
                "Document-bag wrapper fallback failed for application "
                f"{application_number}; returning petition details without documents"
            )
            return self._mark_document_metadata_unavailable(
                petition_result,
                "the petition record carries no documentBag and the application "
                "file-wrapper documents endpoint also failed",
            )

        petition_data[0][FPDFields.DOCUMENT_BAG] = _backfill_wrapper_page_counts(
            wrapper_result.get(FPDFields.DOCUMENT_BAG, [])
        )
        petition_result["document_metadata_available"] = True
        petition_result["document_metadata_source"] = "application_file_wrapper_fallback"
        petition_result["document_metadata_note"] = (
            "THIS documentBag IS THE APPLICATION'S FILE WRAPPER, NOT A "
            "PETITION BAG. USPTO served this petition record with no "
            "documentBag of its own, so the bag was reconstructed from the "
            "application file wrapper instead. It lists the WHOLE prosecution "
            "history of the application (office actions, claims, "
            "specification, IDS, 892/1449 forms, abandonment notices), not "
            "only the papers filed with or issued on this petition, and it "
            "would be identical on every petition of the same application. "
            "Filter it before describing it as this petition's documents: the "
            "petition papers are the PET/PETDEC/PPH.DECISION-style entries "
            "within it."
        )
        return petition_result

    @staticmethod
    def _mark_document_metadata_unavailable(
        result: Dict[str, Any], reason: str
    ) -> Dict[str, Any]:
        """Mark a petition-details response whose documentBag could not be
        retrieved, so an absent bag is never mistaken for 'no documents'."""
        result["document_metadata_available"] = False
        result["document_metadata_source"] = "unavailable"
        result["document_metadata_note"] = (
            "documentBag could NOT be retrieved for this petition "
            f"({reason}). An absent documentBag here means "
            "'metadata unavailable', NOT 'this petition has no documents'. "
            "Retry later, or use FPD_get_document_download with a "
            "documentIdentifier obtained elsewhere."
        )
        return result

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
        limit: int = 50,
        offset: int = 0,
        final_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Search petitions by art unit number

        Args:
            art_unit: Art unit number (e.g., "2128")
            date_range: Optional date range filter (e.g., "2020-01-01:2024-12-31")
            limit: Maximum number of results
            offset: Starting position, for paging past `limit`
            final_only: AND `finalPetitionDecisionIndicator:true` into the query

        Returns:
            Dict containing search results

        Date-range provenance (probed live 2026-08-30 against
        api.uspto.gov/api/v1/petition/decisions/search): the
        `{field, valueFrom, valueTo}` object is correct, but it must be sent
        under the body key `rangeFilters`. Sending it under `filters` — which
        is what this method did until 2026-08-30 — answers HTTP 400 Bad Request
        with no detailedMessage, so every date_range call failed regardless of
        how well-formed the caller's string was. Art unit 3643: 21 records
        unfiltered, 11 within 2015-01-01..2016-12-31.
        """
        # Build query
        query = f"{QueryFieldNames.ART_UNIT}:{art_unit}"
        if final_only:
            query = f"{query} AND {FINAL_ONLY_CLAUSE}"

        # Build range filters for date range if provided
        range_filters = []
        if date_range:
            # Parse date range
            parts = date_range.split(":")
            if len(parts) == 2:
                range_filters.append({
                    "field": FPDFields.PETITION_MAIL_DATE,
                    "valueFrom": parts[0],
                    "valueTo": parts[1]
                })

        return await self.search_petitions(
            query=query,
            range_filters=range_filters if range_filters else None,
            limit=limit,
            offset=offset,
        )

    @_client_method_error_handler("search_by_application")
    async def search_by_application(
        self,
        application_number: str,
        include_documents: bool = False,
        limit: int = 100,
        offset: int = 0,
        fields: Optional[List[str]] = None,
        final_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Search petitions for specific application number

        Args:
            application_number: USPTO application number
            include_documents: Whether to include document bag
            limit: Maximum number of results (was a hard-coded 100 with no
                paging at all, so an application with more petitions than
                that silently lost the remainder)
            offset: Starting position, for paging past `limit`
            fields: Field projection to request. `None` asks USPTO for the
                full record.
            final_only: AND `finalPetitionDecisionIndicator:true` into the query

        D-3 (code-duplication-detection): this method used to carry its own
        16-element field list, a fourth copy of the petition field sets that
        had already diverged from `petitions_balanced` in
        `field_configs.yaml` (it omitted businessEntityStatusCategory and
        inventionTitle). A customer who edited that YAML per CUSTOMIZATION.md
        changed what four tools returned and had no effect here. The client is
        now field-agnostic like every other method on it; `FPDService`, which
        is the layer that owns the `FieldManager`, resolves the set and passes
        it down.
        """
        # Build query
        query = f"{QueryFieldNames.APPLICATION_NUMBER}:{application_number}"
        if final_only:
            query = f"{query} AND {FINAL_ONLY_CLAUSE}"

        result = await self.search_petitions(
            query=query,
            fields=None if include_documents else fields,
            limit=limit,
            offset=offset,
        )

        if include_documents and "error" not in result:
            result = await self._attach_documents_to_search_hits(
                result, application_number
            )

        return result

    async def _attach_documents_to_search_hits(
        self, result: Dict[str, Any], application_number: str
    ) -> Dict[str, Any]:
        """Make sure every petition in a by-application search hit has a
        documentBag, and say where each bag came from.

        Since the 2026-10 payload change the search endpoint serves each
        petition's own documentBag natively (asking for the unfiltered record
        returns it), so normally nothing is fetched here and the result is
        labelled `document_metadata_source: "petition_record"`. Only records
        whose own bag is empty get the APPLICATION FILE WRAPPER grafted on,
        from ONE wrapper fetch for the page (every hit is on the same
        application by construction), and each grafted record is marked
        `document_bag_source: "application_file_wrapper"`. A failed wrapper
        fetch is labelled too, never left as an absent bag that reads as
        "this petition has no documents".
        """
        records = result.get(FPDFields.PETITION_DECISION_DATA_BAG)
        if not isinstance(records, list) or not records:
            return result

        bare = [
            record for record in records
            if isinstance(record, dict) and not record.get(FPDFields.DOCUMENT_BAG)
        ]
        if not bare:
            result["document_metadata_available"] = True
            result["document_metadata_source"] = "petition_record"
            result["document_metadata_note"] = (
                "Each documentBag is that petition's own document list as USPTO "
                "serves it on the petition record (the decision and any papers "
                "filed or issued with it), not the application's file wrapper."
            )
            return result

        wrapper_result = await self.get_application_documents(application_number)
        if "error" in wrapper_result:
            logger.warning(
                "Document-bag wrapper fetch failed for application "
                f"{application_number}; returning petitions without documents"
            )
            return self._mark_document_metadata_unavailable(
                result,
                "a petition record carried no documentBag and the application "
                "file-wrapper documents endpoint failed",
            )

        document_bag = _backfill_wrapper_page_counts(
            wrapper_result.get(FPDFields.DOCUMENT_BAG, [])
        )
        for record in bare:
            record[FPDFields.DOCUMENT_BAG] = document_bag
            record["document_bag_source"] = "application_file_wrapper"

        wrapper_note = (
            "THIS documentBag IS THE APPLICATION'S FILE WRAPPER, NOT A "
            "PETITION BAG, on every record marked document_bag_source: "
            "\"application_file_wrapper\". USPTO served those petition records "
            "with no documentBag of their own, so the bag was taken from the "
            "APPLICATION FILE WRAPPER: the application's whole prosecution "
            "history (office actions, claims, IDS, ...), not only the petition "
            "papers, identical on every such record. Filter it before "
            "describing it as one petition's documents."
        )
        result["document_metadata_available"] = True
        if len(bare) == len(records):
            result["document_metadata_source"] = "application_file_wrapper"
            result["document_metadata_note"] = wrapper_note
        else:
            result["document_metadata_source"] = "mixed"
            result["document_metadata_note"] = (
                "Records without a document_bag_source key carry their own "
                "petition documentBag. " + wrapper_note
            )
        return result

    async def _download_pdf_for_extraction(self, download_url: str) -> bytes:
        """Stream a PDF from the USPTO API with a running byte-count cap and
        verify the first chunk actually starts with the PDF magic number
        before trusting USPTO's self-reported mimeTypeIdentifier field
        (M7/L24). Extracted from extract_document_content_hybrid; kept on
        FPDClient (see module-level `_MAX_PDF_BYTES` comment) rather than
        moved into DocumentExtractionService.

        The `request` event hook drops `X-API-KEY` on any hop that is not
        https on uspto.gov (M-16): these URLs 302 to signed storage URLs and
        httpx strips only `Authorization` and `Cookie` across origins, so the
        shared ODP key was reaching the redirect target verbatim.

        M-18: held under `_extraction_slots` so the process-wide memory
        ceiling is `_MAX_PDF_BYTES x _MAX_CONCURRENT_EXTRACTIONS` rather than
        `_MAX_PDF_BYTES x however many calls are in flight`.

        the fetch goes through the shared cross-process ODP rate
        limiter (off unless USPTO_SHARED_RATE_LIMIT_DIR is set), the same one
        `_send_once` and the download proxy use. The slot is held for the
        whole body read, not just connection setup: the body IS the USPTO
        traffic (USPTO's burst=1 guidance).

        Inside the content tool the whole fetch, slot waits included, runs on
        what is left of the call's time budget (util/deadline.py) and raises
        DeadlineExceeded when cut.
        """
        return await run_within_deadline(
            lambda: self._download_pdf_capped(download_url)
        )

    async def _download_variant_for_extraction(self, download_url: str) -> bytes:
        """A free-text variant (.docx or xmlarchive) of a petition document,
        fetched exactly like the PDF in _download_pdf_for_extraction (key
        hooks, extraction slot, shared ODP limiter, byte cap, call deadline)
        but without the PDF magic-byte check, since it is not a PDF."""
        return await run_within_deadline(
            lambda: self._download_pdf_capped(download_url, require_pdf=False)
        )

    async def _download_pdf_capped(self, download_url: str, require_pdf: bool = True) -> bytes:
        """Body of _download_pdf_for_extraction: one capped fetch under the
        extraction slot and the shared ODP slot (_download_once), with the
        429 rule around it: a 429 is noted on the shared key, then
        fetched ONCE more after max(5 s, Retry-After) when that wait is at
        most 10 s and fits the call's budget, else RateLimitedError carrying
        the envelope. The wait holds neither slot. The shared limiter's
        refusal is RateLimitedError at once, no retry.
        ``require_pdf=False`` skips the magic-byte check (free-text variants)."""
        request_id = generate_request_id()
        retried_429 = False
        while True:
            try:
                return await self._download_once(download_url, require_pdf)
            except SharedLimiterTimeoutError as e:
                logger.warning(f"[{request_id}] shared limiter refusal on download: {e}")
                raise RateLimitedError(rate_limited_envelope(
                    None, RATE_LIMIT_SOURCE_SHARED_LIMITER, request_id
                )) from e
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 429:
                    raise
                envelope = await self._absorb_429(e.response, retried_429, request_id)
                if envelope is not None:
                    raise RateLimitedError(envelope) from e
                retried_429 = True

    async def _download_once(self, download_url: str, require_pdf: bool) -> bytes:
        """One fetch: extraction slot, then the shared ODP limiter slot, then
        the capped, magic-byte-checked stream. Both slots are released on
        return or on any exception."""
        limiter = get_shared_limiter()
        async with _extraction_slots, (
            limiter if limiter is not None else contextlib.nullcontext()
        ), httpx.AsyncClient(
            timeout=self.download_timeout,
            limits=self.connection_limits,
            follow_redirects=True,
            event_hooks=USPTO_KEY_EVENT_HOOKS
        ) as client:
            async with client.stream(
                "GET",
                download_url,
                headers={
                    "X-API-KEY": self.api_key,
                    "Accept": "application/pdf" if require_pdf else "*/*",
                }
            ) as pdf_response:
                pdf_response.raise_for_status()
                chunks: List[bytes] = []
                total_bytes = 0
                first_chunk = require_pdf
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
        """Determine if pypdf extraction is usable or if we need Mistral OCR."""
        return self._extraction.is_good_extraction(text)

    async def extract_with_pypdf(
        self,
        pdf_content: bytes,
        max_pages: int = 200,
        status: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, bool]:
        """Extract text using pypdf (free, fast, works for text-based PDFs).

        `status` is the optional out-dict for partial-extraction reporting —
        see DocumentExtractionService.extract_with_pypdf."""
        return await self._extraction.extract_with_pypdf(pdf_content, max_pages, status)

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
