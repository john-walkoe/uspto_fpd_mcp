"""
Shared error handling utilities for consistent error responses across the application
"""

import os
from typing import Dict, Any, Optional, Callable
from functools import wraps
import uuid
from .log_sanitizer import LogSanitizer
from .unified_logging import get_logger

logger = get_logger(__name__)


def generate_request_id() -> str:
    """Generate a unique request ID for tracking"""
    return str(uuid.uuid4())[:8]


def _generic_message_for_production(
    message: str, status_code: int, safe_message: str
) -> str:
    """Map a status code to a generic, production-safe message.

    Falls back to `safe_message` (the already-sanitized message) when the
    status code has no override.

    F-E7: the two keyword branches that used to sit at the bottom of this
    ladder ("api"+"key" -> "Configuration error", "timeout" -> "Service
    temporarily unavailable") are gone. They inspected `message`, the
    PRE-sanitization string, and were unanchored substring tests applied at
    any status code, so a USPTO 400 whose body named a field called "key"
    came back as `{"error": "Configuration error", "status_code": 400}` and
    any message containing "timeout" read as a service outage even on a 404.
    Genericization is a status-code decision; prose is not load-bearing.

    The 404 branch is deliberately absent: tools/petitions.py's
    `_no_matches_to_empty` recognizes an empty USPTO result set by the 404
    message, so adding one here would turn every empty search into an error
    in production only. `message` is still taken so the signature is stable
    for callers and so a future status-code branch can log what it replaced.
    """
    if status_code == 401:
        return "Authentication required"
    elif status_code == 403:
        return "Access denied"
    elif status_code == 429:
        return "Rate limit exceeded"
    elif status_code >= 500:
        return "Internal server error occurred"
    return safe_message


def format_error_response(
    message: str,
    status_code: int = 500,
    request_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    include_details: Optional[bool] = None,
    authored: bool = False
) -> Dict[str, Any]:
    """
    Format error response in consistent structure with sensitive data filtering

    Args:
        message: Error message
        status_code: HTTP status code
        request_id: Request identifier for tracing (optional)
        context: Additional context for debugging (optional)
        include_details: Whether to include detailed error info (auto-detected from env if None)
        authored: True when `message` is server-written recovery text that
            carries no upstream detail. Such messages skip the production
            genericization (they are the answer, not a leak) but are still
            sanitized. Use only for constant strings written in this repo.

    Returns:
        Dict containing structured error response
    """
    # Determine if we should include detailed error information
    if include_details is None:
        environment = os.getenv("ENVIRONMENT", "production").lower()
        include_details = environment in ["development", "dev", "test"]

    # Always sanitize the message to remove sensitive data
    sanitizer = LogSanitizer()
    safe_message = sanitizer.sanitize_string(message)

    # In production, provide generic messages for certain error types
    if not include_details and not authored:
        safe_message = _generic_message_for_production(message, status_code, safe_message)

    response = {
        "error": safe_message,
        "status_code": status_code,
        "success": False
    }

    if request_id:
        response["request_id"] = request_id

    # Only include context in development/test environments
    if context and include_details:
        response["context"] = sanitizer.sanitize_for_json(context)

    return response


def is_upstream_server_error(response: Dict[str, Any]) -> bool:
    """True if `response` is an error envelope (see format_error_response)
    carrying a 5xx status_code — i.e. the upstream API itself is having
    problems, as opposed to a 4xx (404 not found, 401 auth, etc.) which
    reflects a genuine client-facing condition that must propagate
    unchanged. Used to gate fallback paths so they only engage for actual
    upstream outages.
    """
    if not isinstance(response, dict) or "error" not in response:
        return False
    status_code = response.get("status_code")
    return isinstance(status_code, int) and status_code >= 500


def document_not_located_response(
    petition_result: Dict[str, Any],
    petition_id: str,
    document_identifier: str,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Envelope for "the documentBag did not contain this document".

    F-X3: the client marks a petition whose documentBag could not be
    retrieved with `document_metadata_available: False` and a note saying
    explicitly that an absent bag does NOT mean the petition has no
    documents. Both the download tool and the extraction service then read an
    empty bag and answered 404 "not found in petition", contradicting the
    marker sitting in the object they were inspecting and ruling out the
    caller's correct next action (retry later).

    Returns 503 with an honest message when the marker says the metadata is
    merely unavailable, and the original 404 otherwise.
    """
    if petition_result.get("document_metadata_available") is False:
        return format_error_response(
            "Document metadata is temporarily unavailable for this petition "
            "(USPTO's petition-details documents endpoint is erroring "
            "upstream), so this server cannot tell whether document "
            f"{document_identifier} exists in petition {petition_id}. This is "
            "NOT a statement that the document is absent. Retry later.",
            503,
            request_id,
            authored=True,
        )
    return format_error_response(
        f"Document {document_identifier} not found in petition {petition_id}",
        404,
        request_id,
    )


def sanitize_error_message(message: str) -> str:
    """
    Sanitize error message to remove potentially sensitive information.

    Args:
        message: Original error message

    Returns:
        Sanitized error message safe for external consumption
    """
    sanitizer = LogSanitizer()
    return sanitizer.sanitize_string(message)


class FPDException(Exception):
    """Base exception for FPD application"""
    def __init__(self, message: str, status_code: int = 500, request_id: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(self.message)


class ValidationError(FPDException):
    """Validation error (400)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 400, request_id)


class NotFoundError(FPDException):
    """Resource not found error (404)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 404, request_id)


class RateLimitError(FPDException):
    """Rate limit exceeded error (429)

    F-S6 (solid-principles, Liskov): `retry_after` used to be a REQUIRED
    positional in the middle of the signature, while every sibling subclass
    narrows to `(message, request_id=None)`. Code constructing "some
    FPDException subclass" uniformly could not include this one, and the
    status mapper had to special-case the 429 branch. It is keyword-only with
    a default now, so the hierarchy is substitutable.
    """
    def __init__(self, message: str, request_id: Optional[str] = None,
                 *, retry_after: int = 60):
        super().__init__(message, 429, request_id)
        self.retry_after = retry_after


class AuthenticationError(FPDException):
    """Authentication error (401)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 401, request_id)


def _handle_runtime_error(tool_name: str, e: RuntimeError) -> Dict[str, Any]:
    """RuntimeError branch of async_tool_error_handler's wrapper, extracted
    verbatim (mechanical decomposition, no behavior change)."""
    error_msg = str(e)
    if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
        logger.error(f"Async lifecycle error in {tool_name}: {error_msg}")
        return format_error_response(
            "Operation failed due to async runtime issue. "
            "Try restarting the MCP server. "
            f"Technical details: {error_msg}",
            500
        )
    else:
        # Other RuntimeError - treat as unexpected error
        logger.error(f"Runtime error in {tool_name}: {error_msg}", exc_info=True)
        return format_error_response(f"Runtime error: {error_msg}", 500)


def _handle_generic_exception(tool_name: str, e: Exception) -> Dict[str, Any]:
    """Catch-all Exception branch of async_tool_error_handler's wrapper.

    F-S4 (solid-principles, Open/Closed): this dispatched on
    `type(e).__name__` string equality, so an httpx rename — or any subclass,
    since `type(e).__name__` is exact and ignores the hierarchy — silently
    degraded every HTTP error to a generic 500. httpx is a hard dependency of
    this package, so `isinstance` against the real classes is available; the
    string names are kept as a fallback only in case the import fails.
    """
    import httpx

    if isinstance(e, httpx.HTTPStatusError):
        error_type = "HTTPStatusError"
    elif isinstance(e, httpx.TimeoutException):
        error_type = "TimeoutException"
    else:
        error_type = type(e).__name__

    if error_type == "HTTPStatusError":
        # httpx.HTTPStatusError - preserve original status code
        status_code = getattr(e, "response", None)
        if status_code:
            status_code = getattr(status_code, "status_code", 502)
            response_text = getattr(getattr(e, "response", None), "text", str(e))
            logger.error(f"API error in {tool_name}: {status_code} - {response_text}")
            return format_error_response(f"API error: {response_text}", status_code)
        else:
            logger.error(f"API error in {tool_name}: {str(e)}")
            return format_error_response(f"API error: {str(e)}", 502)

    elif error_type == "TimeoutException":
        # httpx.TimeoutException - request timeout
        logger.error(f"API timeout in {tool_name}: {str(e)}")
        return format_error_response("Request timeout - please try again", 408)

    else:
        # Unexpected error - log with full traceback
        logger.error(f"Unexpected error in {tool_name}: {str(e)}", exc_info=True)
        return format_error_response(f"Internal error: {str(e)}", 500)


def async_tool_error_handler(tool_name: str):
    """
    Decorator for consistent async tool error handling.

    Eliminates duplicated try/except blocks across MCP tools by providing
    centralized error handling for common exception types.

    Handles:
    - ValidationError (400) - Custom validation errors
    - ValueError (400) - Legacy validation errors (should migrate to ValidationError)
    - httpx.HTTPStatusError - API errors with original status code
    - httpx.TimeoutException (408) - Request timeouts
    - Exception (500) - Unexpected errors with full logging

    Usage:
        @mcp.tool(name="My_Tool")
        @async_tool_error_handler("my_tool")
        async def my_tool(...) -> Dict[str, Any]:
            # Tool logic - no try/except needed
            if invalid:
                raise ValidationError("Invalid input", generate_request_id())
            return await api_client.do_something()

    Args:
        tool_name: Tool name for logging (e.g., "minimal_search")

    Returns:
        Decorator function that wraps async tool functions
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Dict[str, Any]:
            try:
                return await func(*args, **kwargs)

            except ValidationError as e:
                logger.warning(f"Validation error in {tool_name}: {str(e)}")
                return format_error_response(str(e), 400, e.request_id)

            except ValueError as e:
                # Legacy ValueError for validation - should migrate to ValidationError
                logger.warning(f"Validation error in {tool_name}: {str(e)}")
                return format_error_response(str(e), 400)

            except RuntimeError as e:
                # Catch async lifecycle errors specifically (fix for async lifecycle bug)
                return _handle_runtime_error(tool_name, e)

            except Exception as e:
                return _handle_generic_exception(tool_name, e)

        return wrapper
    return decorator
