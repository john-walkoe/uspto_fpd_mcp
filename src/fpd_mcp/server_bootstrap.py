"""Server bootstrap: proxy lifecycle + transport entry points (SD-1 split).

Owns the background download-proxy task (start, supervision, health), PFW
centralized-proxy detection, and the stdio/HTTP entry points. The composed
server comes from server_app.get_server() — this module used to read
main.mcp through three function-local `from . import main` imports, which
made main <-> server_bootstrap a real import cycle (F-A1). Extracted from
main.py (mechanical decomposition, no behavior change).
"""

import asyncio
import os
import re
from typing import Any, Optional

from .middleware import (
    APIKeyAuthMiddleware,
    SecurityHeadersMiddleware,
    _StreamableHTTPProbeMiddleware,
)
from .runtime import config_path, settings
from .shared.body_limit import BodySizeLimitMiddleware
from .server_app import get_auth_provider, get_server
from .util.secure_logger import get_secure_logger

logger = get_secure_logger(__name__)

# Global proxy server state
_proxy_server_running = False
_proxy_server_task = None
_proxy_startup_lock = asyncio.Lock()  # Prevents concurrent proxy startup attempts


# =============================================================================
# Utility Functions
# =============================================================================

def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something is already listening on (host, port).

    F-A8: the same three-line socket probe was written verbatim in
    _ensure_proxy_server_running and run_hybrid_server. One helper, and a
    seam tests can patch (testing-implementation T-1).
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) == 0


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

    # F-E11: this used to call sys.exit(1), which raises SystemExit INSIDE
    # the loop's exception handler, where the loop swallows it. The process
    # did not exit and the "shutting down" line asserted something that had
    # not happened. Stopping the loop is what actually unwinds the server;
    # the caller's own exit path then runs.
    if isinstance(exception, (KeyboardInterrupt, SystemExit)):
        logger.critical("Critical exception - stopping the event loop")
        try:
            asyncio.get_running_loop().stop()
        except RuntimeError:
            logger.error("No running loop to stop; the process may hang")


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


# =============================================================================
# PROXY SERVER HELPER FUNCTIONS
# =============================================================================

async def _ensure_proxy_server_running(port: int = 8081):
    """
    Ensure the proxy server is running (auto-start on first download).

    This function is called when:
    - ENABLE_ALWAYS_ON_PROXY=false (on-demand mode)
    - Centralized proxy is unavailable
    - A document download is requested

    Thread-safe: Uses asyncio.Lock to prevent concurrent startup attempts.

    Args:
        port: Port number for proxy server (default: 8081)

    Returns:
        True if proxy is running (already running or successfully started)
    """
    global _proxy_server_running, _proxy_server_task

    # Fast path: already running (avoids lock acquisition overhead)
    if _proxy_server_running:
        return True

    # Use lock to prevent concurrent startup attempts
    async with _proxy_startup_lock:
        # Double-check after acquiring lock (another task may have started it)
        if _proxy_server_running:
            return True

        # If the port is already serving (HTTP mode starts the proxy in a
        # background thread that never sets _proxy_server_running; Claude
        # Desktop may also hold a copy), adopt it instead of double-binding.
        # Without this, uvicorn's bind failure calls sys.exit(1) and the
        # SystemExit takes down the whole MCP server mid tool-call. Mirrors
        # PFW's _ensure_proxy_server_running port check.
        if _port_in_use(port):
            logger.info(
                "Port %d already in use — skipping proxy server startup "
                "(another instance is running; MCP tools are still fully available)",
                port,
            )
            _proxy_server_running = True  # treat as running so tools work
            return True

        try:
            logger.info(f"📦 On-demand proxy startup: Starting local proxy on port {port}")

            # Wrap background task with exception handler
            async def safe_proxy_runner():
                try:
                    await _run_proxy_server(port)
                except asyncio.CancelledError:
                    raise
                except BaseException as e:
                    # BaseException, not Exception: uvicorn startup failure
                    # raises SystemExit, which must not kill the server.
                    logger.error(f"Proxy server crashed: {e}", exc_info=True)
                    global _proxy_server_running
                    _proxy_server_running = False

            _proxy_server_task = asyncio.create_task(safe_proxy_runner())
            # F-D7: the always-on path attached this callback and the
            # on-demand path did not, so an on-demand proxy that exited
            # cleanly-but-unexpectedly left _proxy_server_running stuck True —
            # exactly the failure _on_proxy_task_done's docstring describes.
            _proxy_server_task.add_done_callback(_on_proxy_task_done)
            _proxy_server_running = True

            # Brief wait to ensure server starts cleanly
            await asyncio.sleep(0.5)

            # Health check: Verify proxy is responding.
            # F-E5: this was a BLOCKING requests.get inside an async function,
            # held under _proxy_startup_lock, so it stalled the whole event
            # loop (in stdio hybrid mode that is the MCP server, the proxy and
            # every in-flight tool call) for up to a second. httpx is already
            # a dependency and has an async client.
            try:
                import httpx as _httpx

                async with _httpx.AsyncClient(timeout=1.0) as _probe_client:
                    response = await _probe_client.get(f"http://localhost:{port}/")
                if response.status_code == 200:
                    logger.info(f"✅ On-demand proxy started successfully on port {port}")
                    return True
                else:
                    logger.warning(f"Proxy started but returned status {response.status_code}")
                    return True  # Continue anyway - server task is running
            except Exception as e:
                logger.warning(f"Proxy started but health check failed: {e}")
                return True  # Continue anyway - server task is running

        except Exception as e:
            logger.error(f"❌ Failed to start on-demand proxy: {e}")
            _proxy_server_running = False
            return False

    return _proxy_server_running


def _on_proxy_task_done(task: "asyncio.Task") -> None:
    """Supervision hook for the always-on background proxy task.

    Without this, a proxy that dies after startup leaves
    _proxy_server_running stuck True and the failure invisible — tools keep
    emitting download URLs that no longer work. (PTAB's
    server_bootstrap._on_proxy_task_done pattern.)
    """
    global _proxy_server_running
    _proxy_server_running = False
    if task.cancelled():
        logger.info("Proxy server task cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"Proxy server task died: {type(exc).__name__}: {exc}")
    else:
        logger.warning("Proxy server task exited unexpectedly (no exception)")


async def _run_proxy_server(port: int = 8081, share_client: bool = True):
    """Run the FastAPI proxy server

    Uses API key from Settings (which may come from secure storage or
    environment variables).

    F-D1: `share_client` hands the proxy the process's existing FPDClient so
    the two paths share one bulkhead, one circuit breaker and one cache. It is
    only safe when the proxy runs in the SAME event loop as the MCP server —
    true on the stdio hybrid path, false in HTTP mode where the proxy gets its
    own loop in a background thread and the asyncio locks cannot cross.
    """
    try:
        import uvicorn
        from .proxy.server import create_proxy_app

        shared = None
        if share_client:
            from .runtime import get_api_client

            shared = get_api_client()
        else:
            logger.info(
                "Proxy runs in its own event loop: it builds a SECOND "
                "FPDClient, so the USPTO concurrency bulkhead and circuit "
                "breaker are per-loop, not per-process"
            )

        # Pass API key and port from Settings to proxy server
        # This allows proxy to work with secure storage (Windows DPAPI)
        app = create_proxy_app(
            api_key=settings.uspto_api_key, port=port, client=shared
        )
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

        mcp = get_server()

        # Start both servers concurrently
        logger.info("Starting hybrid FPD MCP + HTTP proxy server")

        # Run MCP server in a separate task
        mcp_task = asyncio.create_task(
            asyncio.to_thread(lambda: mcp.run(transport='stdio'))
        )

        # Start proxy server immediately if always-on mode is enabled
        if enable_always_on:
            if _port_in_use(proxy_port):
                logger.info(
                    "Port %d already in use — skipping proxy server startup "
                    "(another instance is running; MCP tools are still fully available)",
                    proxy_port,
                )
                _proxy_server_running = True  # treat as running so tools work
            else:
                logger.info(f"Always-on mode: Starting HTTP proxy server immediately on port {proxy_port}")
                _proxy_server_task = asyncio.create_task(_run_proxy_server(proxy_port))
                _proxy_server_task.add_done_callback(_on_proxy_task_done)
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


def _log_pfw_proxy_standalone_mode() -> None:
    """Shared log block for 'PFW proxy not detected' outcomes in
    _detect_pfw_proxy (the instant 'none' sentinel path and the
    retries-exhausted path both logged this identical block). Extracted
    verbatim (mechanical decomposition, no behavior change)."""
    logger.info("ℹ️  Standalone mode: Using local FPD proxy (always-on)")
    logger.info("   💡 Install USPTO PFW MCP for enhanced features:")
    logger.info("      - Persistent download links (7-day encrypted URLs)")
    logger.info("      - Centralized proxy (unified rate limiting)")
    logger.info("      - Cross-MCP document sharing and caching")
    logger.info("   📦 Get it at: https://github.com/john-walkoe/uspto_pfw_mcp")


def _log_pfw_proxy_detected(port: int, suffix: str = "") -> None:
    """Shared log block for a successfully-detected PFW proxy port.
    Extracted from _detect_pfw_proxy verbatim (mechanical decomposition, no
    behavior change)."""
    logger.info("🎯 SUCCESS: Using centralized USPTO proxy ecosystem")
    logger.info(f"   ✅ Detected PFW proxy on port {port}{suffix}")
    logger.info("   ✅ Persistent links available")
    logger.info("   ✅ Enhanced rate limiting")
    logger.info("   ✅ Cross-MCP document sharing")


def _try_explicit_centralized_port(centralized_port_env: str) -> Optional[int]:
    """CENTRALIZED_PROXY_PORT set to an explicit numeric port: try it first.
    Extracted from _detect_pfw_proxy (mechanical decomposition, no behavior
    change)."""
    if not centralized_port_env.isdigit():
        return None
    explicit_port = int(centralized_port_env)
    if _proxy_responds(explicit_port, 0.3):
        _log_pfw_proxy_detected(explicit_port, " (via CENTRALIZED_PROXY_PORT)")
        return explicit_port
    logger.warning(
        f"   CENTRALIZED_PROXY_PORT={explicit_port} set but proxy not responding"
    )
    return None


#: Ports probed for a sibling PFW centralized proxy: the primary first, the
#: alternatives only on the final attempt (to keep startup fast when PFW is
#: not installed).
PFW_PRIMARY_PROXY_PORT = 8080
PFW_ALTERNATIVE_PROXY_PORTS = (8079, 8082, 8083)


def _proxy_responds(port: int, timeout: float) -> bool:
    """True if something answers 200 on localhost:port.

    Extracted as the single seam this module's HTTP probing goes through
    (F-A8, testing-implementation T-1): the retry logic above it is pure
    logic once this is patchable.
    """
    import requests

    try:
        return requests.get(
            f"http://localhost:{port}/", timeout=timeout
        ).status_code == 200
    except Exception:
        return False


def _probe_pfw_proxy_ports(max_retries: int, retry_delay: float, timeout: float) -> Optional[int]:
    """Retry loop probing the primary PFW proxy port (8080), with
    alternative ports checked on the final attempt only (to minimize
    startup delay). Extracted from _detect_pfw_proxy (mechanical
    decomposition, no behavior change)."""
    import time

    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"   Retry {attempt}/{max_retries-1} (waiting for PFW proxy to start)...")
            # Startup-only, and this function is called from sync code
            # (_detect_pfw_proxy) before the loop exists, so a blocking sleep
            # is correct here — unlike the async health check above (F-E5).
            time.sleep(retry_delay)

        if _proxy_responds(PFW_PRIMARY_PROXY_PORT, timeout):
            _log_pfw_proxy_detected(PFW_PRIMARY_PROXY_PORT)
            return PFW_PRIMARY_PROXY_PORT

        # Only check alternative ports on final attempt (to minimize startup delay)
        if attempt == max_retries - 1:
            for alt_port in PFW_ALTERNATIVE_PROXY_PORTS:
                if _proxy_responds(alt_port, timeout):
                    _log_pfw_proxy_detected(alt_port)
                    return alt_port

    return None


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

    # INSTANT DETECTION: Check environment variable first
    # PFW MCP sets CENTRALIZED_PROXY_PORT when it starts its proxy server
    # If not set or set to sentinel value "none", PFW is not installed
    centralized_port_env = os.getenv("CENTRALIZED_PROXY_PORT", "none").lower()

    if centralized_port_env == "none":
        # PFW explicitly not installed - skip all HTTP checks (instant startup)
        _log_pfw_proxy_standalone_mode()
        return None

    # If port is explicitly set, try it first
    explicit_result = _try_explicit_centralized_port(centralized_port_env)
    if explicit_result is not None:
        return explicit_result

    # Optimized retry configuration for fast startup when PFW is not installed
    # - 2 attempts (down from 3) to reduce delay when PFW is absent
    # - 0.3s timeout (down from 1s) for faster localhost detection
    # - 0.5s retry delay (down from 1s) for quicker fallback
    # - Alternative ports only checked on final attempt
    probed_port = _probe_pfw_proxy_ports(max_retries=2, retry_delay=0.5, timeout=0.3)
    if probed_port is not None:
        return probed_port

    # All retry attempts exhausted - PFW not detected
    _log_pfw_proxy_standalone_mode()
    return None


def _build_cors_origins(port: int) -> list:
    """Build the HTTP-mode CORS origins list (localhost defaults +
    CORS_EXTRA_ORIGIN, comma-separated and regex-validated per entry).
    Extracted from run_server verbatim (mechanical decomposition, no
    behavior change)."""
    origins = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    extra_origins = os.getenv("CORS_EXTRA_ORIGIN", "")
    for o in extra_origins.split(","):
        o = o.strip()
        if not o:
            continue
        if not re.match(r"^https?://[a-zA-Z0-9.\-]+(:[0-9]+)?$", o):
            raise ValueError(f"CORS_EXTRA_ORIGIN must be a valid HTTP/HTTPS URL, got: {o}")
        origins.append(o)
        logger.info(f"CORS: added extra origin {o}")
    return origins


def _run_http_transport() -> None:
    """HTTP-mode server startup — Docker, reverse proxy, or claude.ai direct
    connector. Extracted from run_server verbatim (mechanical
    decomposition, no behavior change)."""
    mcp = get_server()
    _AUTH_PROVIDER = get_auth_provider()

    # Fail fast if INTERNAL_AUTH_SECRET is missing — open-access HTTP is a
    # misconfiguration. In STDIO mode this is fine (local process only).
    # In OAuth mode the surface is bearer-protected by FastMCP instead,
    # so the shared-secret guard (and this check) is skipped.
    if _AUTH_PROVIDER is None:
        from .shared_secure_storage import get_internal_auth_secret
        _auth_secret_check = get_internal_auth_secret() or os.environ.get("INTERNAL_AUTH_SECRET")
        if not _auth_secret_check:
            logger.error(
                "INTERNAL_AUTH_SECRET is required for HTTP transport mode. "
                "Set it as an environment variable or store it via the key management system. "
                "Refusing to start an unauthenticated HTTP server."
            )
            raise SystemExit(1)

    host = os.getenv("FASTMCP_HOST", "127.0.0.1")
    port = int(os.getenv("FASTMCP_PORT", "8000"))

    # Build CORS origins list
    origins = _build_cors_origins(port)

    try:
        from starlette.middleware.cors import CORSMiddleware
        import uvicorn
        # Middleware stack (outermost first): Probe → SecurityHeaders → APIKeyAuth → CORS → mcp app
        # Probe must be outermost — intercepts claude.ai format probes before auth runs.
        # Security headers wrap everything so they appear on 401 responses too.
        inner: Any = CORSMiddleware(
            mcp.http_app(stateless_http=settings.fastmcp_stateless_http),
            allow_origins=origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Accept", "Mcp-Session-Id"],
            expose_headers=["Mcp-Session-Id"],
        )
        # M-2: nothing capped a /mcp POST body. uvicorn/h11 bound the
        # request line and headers; the body was unbounded once authenticated.
        # FPD_MAX_MCP_BODY_BYTES (default 4 MB) is generous for a JSON-RPC
        # frame and finite, which the previous state was not.
        inner = BodySizeLimitMiddleware(
            inner,
            max_body_bytes=int(
                os.getenv("FPD_MAX_MCP_BODY_BYTES", str(4 * 1024 * 1024))
            ),
            error_body={"error": "Request body too large"},
        )
        if _AUTH_PROVIDER is not None:
            # OAuth mode: FastMCP's bearer middleware guards /mcp (401
            # + WWW-Authenticate — which already gives claude.ai's
            # format probe the 401 it needs, so the probe shim is
            # redundant), and the OAuth routes (/authorize, /token,
            # /register, /auth/*, /.well-known/*) must be reachable
            # without a shared secret. Headless clients present
            # FPD_AUTH_INTERNAL_TOKEN as bearer.
            logger.warning(
                "FPD_AUTH_MODE=oauth: x-api-key guard and probe shim "
                "disabled; the MCP surface is protected by bearer tokens."
            )
            app: Any = SecurityHeadersMiddleware(inner)
        else:
            app = _StreamableHTTPProbeMiddleware(
                SecurityHeadersMiddleware(APIKeyAuthMiddleware(inner))
            )
        # Start the download proxy in a background daemon thread (Lesson 35).
        # uvicorn.run() blocks, so the STDIO asyncio-task pattern never fires
        # here — the thread gets its own event loop via asyncio.run().
        _proxy_port_http = get_local_proxy_port()
        _enable_proxy_http = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"
        if _enable_proxy_http:
            import threading

            def _proxy_thread_target():
                # F-D1: separate thread, separate event loop — the shared
                # client's asyncio primitives cannot cross it.
                asyncio.run(_run_proxy_server(_proxy_port_http, share_client=False))
            _pt = threading.Thread(target=_proxy_thread_target, daemon=True, name="download-proxy")
            _pt.start()
            logger.info(f"Download proxy server starting on port {_proxy_port_http} (background thread)")
        logger.info(f"Starting HTTP transport on {host}:{port}")
        # access_log off: access lines include request paths, and
        # /download/persistent/{hash} paths embed the link credential
        uvicorn.run(app, host=host, port=port, access_log=False)
    except ImportError as e:
        raise ImportError(
            f"HTTP transport requires uvicorn and starlette: {e}. "
            "Run: uv add uvicorn starlette"
        )


def _run_stdio_transport() -> None:
    """STDIO-mode server startup — Claude Desktop / Claude Code. Extracted
    from run_server verbatim (mechanical decomposition, no behavior
    change)."""
    # Informational centralized-proxy detection (legacy port probing);
    # CENTRALIZED_PROXY_URL is resolved per-call in the download tool.
    pfw_proxy_port = _detect_pfw_proxy()
    if pfw_proxy_port:
        logger.info("🎯 Centralized USPTO PFW proxy detected — downloads register with PFW")
        os.environ['CENTRALIZED_PROXY_PORT'] = str(pfw_proxy_port)

    enable_proxy = os.getenv("ENABLE_PROXY_SERVER", "true").lower() == "true"
    enable_always_on = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"

    if enable_proxy:
        # The local proxy always runs in stdio mode: it serves local
        # persistent links, the recent-downloads registry, and the
        # /downloads page even when centralized registration is active.
        default_port = get_local_proxy_port()
        asyncio.run(run_hybrid_server(enable_always_on=enable_always_on, proxy_port=default_port))
    else:
        logger.info("Proxy server disabled via ENABLE_PROXY_SERVER=false")
        get_server().run()


# ==========================================
# SERVER ENTRY POINT
# ==========================================

def run_server():
    """
    Entry point for the fpd-mcp command.

    Transport is controlled by FASTMCP_TRANSPORT:
      FASTMCP_TRANSPORT=stdio  (default) — Claude Desktop / Claude Code compatible
      FASTMCP_TRANSPORT=http             — HTTP mode for Docker, reverse proxy, claude.ai

    HTTP mode environment variables:
      FASTMCP_HOST=0.0.0.0        Bind address (default: 127.0.0.1)
      FASTMCP_PORT=8005           Port (default: 8000; cluster convention: fpd=8005)
      CORS_EXTRA_ORIGIN=https://… Additional CORS origins beyond localhost (comma OK)
      INTERNAL_AUTH_SECRET        Required — X-API-KEY auth for all non-health requests

    STDIO mode environment variables:
      ENABLE_PROXY_SERVER=true    Enable the local download proxy (default: true)
      ENABLE_ALWAYS_ON_PROXY=true Start proxy at startup vs on-demand (default: true)
      FPD_PROXY_PORT=8081         Document proxy port (default: 8081)
    """
    try:
        # Install global async exception handler FIRST
        install_async_exception_handler()

        # F-A3: a .env is loaded HERE, at a deliberate entry point, rather
        # than as a side effect of importing proxy/server.py. Importing a
        # tool module used to be enough to read a .env found by walking up
        # from the package directory — outside the repo, with no log line.
        from .proxy.server import load_env_file

        load_env_file()

        logger.info("Starting Final Petition Decisions MCP server...")
        logger.info(f"Field config loaded from: {config_path.name}")

        transport = os.getenv("FASTMCP_TRANSPORT", "stdio")

        if transport == "http":
            # HTTP mode — for Docker, reverse proxy, or claude.ai direct connector
            _run_http_transport()
        else:
            # STDIO mode (default) — Claude Desktop / Claude Code
            _run_stdio_transport()

    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise


def main():
    """Main entry point"""
    run_server()


if __name__ == "__main__":
    main()
