"""HTTP-mode ASGI middleware for the MCP surface (module split, SD-1).

Stack order is composed in server_bootstrap._run_http_transport():
Probe -> SecurityHeaders -> APIKeyAuth -> CORS -> mcp app.
"""

import os

from .util.secure_logger import get_secure_logger

# Logger name pinned to "fpd_mcp.main" (not __name__) rather than
# "fpd_mcp.middleware": tests/test_logging_hardening.py attaches a handler
# directly to logging.getLogger("fpd_mcp.main") to assert the auth-failure
# warning is logged without leaking the presented key — Python's logger
# hierarchy would NOT propagate a "fpd_mcp.middleware" record to that
# handler (siblings, not ancestor/descendant), so keep the pre-Phase-6B
# logger identity here (log events unchanged).
logger = get_secure_logger("fpd_mcp.main")


def _log_authentication_failure(client_ip: str, reason: str) -> None:
    """Emit the typed authentication-failure event (M-23).

    Imported lazily and never allowed to raise: a security-log write must not
    be able to turn a 401 into a 500.
    """
    try:
        from .shared.security_logger import security_logger

        security_logger.log_authentication_failure(
            client_ip=client_ip, reason=reason
        )
    except Exception as audit_error:  # pragma: no cover - defensive
        logger.error(
            "Security event write failed: %s", type(audit_error).__name__
        )


def _matches_any_candidate(presented, candidates) -> bool:
    """Constant-time membership test against every rotation candidate.

    INTERNAL_AUTH_SECRET may be a comma-separated list (current secret
    first, then any secret still being retired) — a rotation overlap window
    instead of a synchronized four-service restart. Every candidate is
    compared, never short-circuited on the first match, so the timing does
    not reveal how many secrets are in the rotation window or which one (if
    any) validated. Delegates the per-candidate comparison to
    compare_credential, which is what makes this safe against a non-ASCII
    presented value (L-1).
    """
    from .shared.credentials import compare_credential

    matched = False
    for candidate in candidates:
        if compare_credential(presented, candidate):
            matched = True
    return matched


class APIKeyAuthMiddleware:
    """Validates X-API-KEY header on all non-health requests in HTTP mode.

    Checks against INTERNAL_AUTH_SECRET (the shared cross-MCP secret).
    Health endpoint is intentionally open for load balancer probes.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from starlette.requests import Request
        request = Request(scope, receive)
        if request.url.path == "/health":
            await self.app(scope, receive, send)
            return
        key = request.headers.get("x-api-key")
        from .shared_secure_storage import get_internal_auth_secret, split_secret_candidates
        expected_raw = (
            get_internal_auth_secret()
            or os.environ.get("INTERNAL_AUTH_SECRET")
        )
        candidates = split_secret_candidates(expected_raw)
        if not candidates:
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Server misconfigured: INTERNAL_AUTH_SECRET not set"}, status_code=500)
            await response(scope, receive, send)
            return
        # L-1: a non-ASCII header used to raise TypeError inside
        # compare_digest and turn this 401 into a 500 -- compare_credential
        # guards that per candidate. Every candidate is compared, never
        # short-circuited on the first match, so the timing does not reveal
        # how many secrets are in the rotation window (S-06, PT-14).
        if not _matches_any_candidate(key, candidates):
            # Log the event only — never the presented key or the path
            logger.warning("HTTP auth failed (x-api-key missing or mismatch)")
            # M-23: also emit the typed event so the rejection reaches
            # security.log, not just fpd_mcp.log. The prose line above stays:
            # it is the operational breadcrumb tests/test_logging_hardening.py
            # pins as key-free, and the two sinks have different retention.
            _log_authentication_failure(
                client_ip=(scope.get("client") or ("unknown",))[0],
                reason="x-api-key missing or mismatch",
            )
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Adds browser security headers to all HTTP responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        _SECURITY_HEADERS = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
            (
                b"content-security-policy",
                b"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
            ),
            # L16: match the proxy's equivalent SecurityHeadersMiddleware
            # (proxy/server.py), which already sets these two.
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        ]

        async def patched_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, patched_send)


class _StreamableHTTPProbeMiddleware:
    """Return 401 for MCP probe requests that lack the required Accept header.

    claude.ai's MCP client first probes /mcp (GET and POST — Lessons 30/39)
    with an older format that omits 'text/event-stream' from Accept.
    FastMCP's StreamableHTTP handler rejects those with 406, which puts
    claude.ai into a permanent "format-incompatible" state where it never
    indexes the server's tools. Returning 401 instead causes claude.ai to
    attempt OAuth discovery (404 — expected) and then fall back to an
    anonymous connection that completes the full MCP handshake.

    Must be the outermost middleware layer.
    """
    def __init__(self, inner_app):
        self.app = inner_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope.get("method", "")
            path = scope.get("path", "")
            headers = dict(scope.get("headers", []))
            accept = headers.get(b"accept", b"").decode()
            if (
                path == "/mcp"
                and method in ("POST", "GET")
                and "text/event-stream" not in accept
            ):
                from starlette.responses import JSONResponse
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
