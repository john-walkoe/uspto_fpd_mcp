"""
Logging utilities for USPTO Final Petition Decisions MCP.

Provides secure request/response logging with API key sanitization.
"""

import httpx
import logging
import json
from typing import Dict, Any

logger = logging.getLogger('fpd_mcp.logging_transport')


class LoggingTransport(httpx.AsyncBaseTransport):
    """
    Custom HTTP transport that logs all requests and responses.

    Automatically sanitizes sensitive headers (API keys) to prevent exposure in logs.
    Useful for debugging API integration issues while maintaining security.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport):
        """
        Initialize logging transport wrapper.

        Args:
            transport: The underlying HTTP transport to wrap
        """
        self.transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """
        Handle HTTP request with logging.

        Args:
            request: The HTTP request to process

        Returns:
            The HTTP response from the underlying transport
        """
        # Log the request
        logger.debug(f"REQUEST: {request.method} {request.url}")

        # Sanitize headers to prevent API key exposure
        headers_copy = dict(request.headers)
        self._sanitize_headers(headers_copy)
        logger.debug(f"REQUEST HEADERS: {headers_copy}")

        # Log request body
        self._log_request_body(request)

        # Get the response
        response = await self.transport.handle_async_request(request)

        # Log the response
        logger.debug(f"RESPONSE: {response.status_code} from {request.url}")

        # Sanitize response headers as well
        response_headers_copy = dict(response.headers)
        self._sanitize_headers(response_headers_copy)
        logger.debug(f"RESPONSE HEADERS: {response_headers_copy}")

        return response

    def _sanitize_headers(self, headers: Dict[str, Any]) -> None:
        """
        Remove sensitive headers from dictionary in-place.

        Args:
            headers: Dictionary of HTTP headers to sanitize
        """
        sensitive_keys = [
            'X-API-KEY', 'x-api-key',
            'Authorization', 'authorization',
            'API-KEY', 'api-key'
        ]
        for key in sensitive_keys:
            headers.pop(key, None)

    def _log_request_body(self, request: httpx.Request) -> None:
        """
        Log request body with JSON pretty-printing if possible.

        Args:
            request: The HTTP request containing the body to log
        """
        try:
            if request.content:
                body = request.content
                try:
                    # Decode bytes to string
                    if isinstance(body, bytes):
                        body = body.decode('utf-8')

                    # Try to parse and pretty-print JSON
                    try:
                        json_body = json.loads(body)
                        logger.debug(f"REQUEST BODY:\n{json.dumps(json_body, indent=2)}")
                    except (json.JSONDecodeError, TypeError):
                        logger.debug(f"REQUEST BODY: {body}")
                except Exception as e:
                    logger.debug(f"REQUEST BODY (raw): {body}")
        except Exception as e:
            logger.debug(f"Error logging request body: {e}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the FPD MCP.

    Args:
        name: Logger name (typically module name)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(f'fpd_mcp.{name}')


def sanitize_api_key_in_message(message: str, api_key: str) -> str:
    """
    Replace API key in message with masked version for safe logging.

    Args:
        message: The message that may contain the API key
        api_key: The API key to mask

    Returns:
        Message with API key replaced by "***KEY_MASKED***"
    """
    if api_key and api_key in message:
        return message.replace(api_key, "***KEY_MASKED***")
    return message


def log_api_call(
    logger_instance: logging.Logger,
    endpoint: str,
    method: str = "POST",
    params: Dict[str, Any] = None,
    status_code: int = None,
    error: str = None
) -> None:
    """
    Log API call details in a structured format.

    Args:
        logger_instance: Logger to use
        endpoint: API endpoint called
        method: HTTP method used
        params: Request parameters (will be sanitized)
        status_code: Response status code (if available)
        error: Error message (if applicable)
    """
    log_data = {
        "method": method,
        "endpoint": endpoint,
    }

    if params:
        # Sanitize params before logging
        safe_params = params.copy()
        safe_params.pop('api_key', None)
        safe_params.pop('apiKey', None)
        log_data["params"] = safe_params

    if status_code:
        log_data["status_code"] = status_code

    if error:
        log_data["error"] = error
        logger_instance.error(f"API Call Failed: {json.dumps(log_data, indent=2)}")
    else:
        logger_instance.info(f"API Call: {json.dumps(log_data)}")
