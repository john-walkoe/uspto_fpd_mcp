"""Component health for the MCP surface's /health route.

L-23: `/health` was a static `PlainTextResponse("OK")`. It reported healthy
on a server whose USPTO client had never initialized, whose link-cache
database was unreadable, and whose download proxy thread had died — the three
failures an operator would want a probe to catch, since each leaves the tools
returning errors while the container looks fine to the orchestrator.

Every check is cheap, local and non-network: this runs on a load-balancer
probe interval, so it must never make an upstream call.
"""

from typing import Any, Dict, Tuple


def _check_api_client() -> Tuple[bool, str]:
    """The USPTO client resolves and holds a key."""
    try:
        from .runtime import get_api_client

        client = get_api_client()
    except Exception as exc:
        return False, f"api_client unavailable ({type(exc).__name__})"
    if not getattr(client, "api_key", None):
        return False, "api_client has no USPTO API key"
    return True, "ok"


def _check_link_cache() -> Tuple[bool, str]:
    """The persistent-link database is openable."""
    try:
        from .proxy.secure_link_cache import get_link_cache

        cache = get_link_cache()
        if cache is None:
            return False, "link cache unavailable"
    except Exception as exc:
        return False, f"link cache unavailable ({type(exc).__name__})"
    return True, "ok"


def _check_proxy() -> Tuple[bool, str]:
    """The download proxy is either disabled or believed to be running.

    A disabled proxy is a valid configuration, not a fault: the tools fall
    back to direct USPTO links.
    """
    import os

    if os.getenv("ENABLE_PROXY_SERVER", "true").lower() != "true":
        return True, "disabled"
    try:
        from . import server_bootstrap

        if server_bootstrap._proxy_server_running:
            return True, "ok"
        # HTTP transport starts the proxy in a daemon thread with its own
        # event loop (server_bootstrap run_http_server) and never sets the
        # STDIO-mode flag, so the flag alone reported "proxy not running"
        # against a proxy that was serving. The socket is the fact; the flag
        # is a cache of it. Deploy 2026-09-03 surfaced this as a 503 /health
        # on every HTTP container with a working proxy.
        if server_bootstrap._port_in_use(server_bootstrap.get_local_proxy_port()):
            return True, "listening"
        return False, "proxy not running"
    except Exception as exc:
        return False, f"proxy state unreadable ({type(exc).__name__})"


_CHECKS = {
    "api_client": _check_api_client,
    "link_cache": _check_link_cache,
    "download_proxy": _check_proxy,
}


def health_report() -> Tuple[bool, Dict[str, Any]]:
    """Run every check. Returns (healthy, {component: detail})."""
    components: Dict[str, Any] = {}
    healthy = True
    for name, check in _CHECKS.items():
        try:
            ok, detail = check()
        except Exception as exc:  # pragma: no cover - a check must never raise
            ok, detail = False, f"check failed ({type(exc).__name__})"
        components[name] = {"ok": ok, "detail": detail}
        healthy = healthy and ok
    return healthy, components


def health_response():
    """Starlette response: 200 with a component breakdown, or 503."""
    from starlette.responses import JSONResponse

    healthy, components = health_report()
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "components": components},
        status_code=200 if healthy else 503,
    )
