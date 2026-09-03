"""Caller identity + per-registrant viewer key (H2 support, PTAB port)."""

import os
from typing import Optional


def _oauth_mode() -> bool:
    """True when this process is running as an OAuth resource server."""
    return os.getenv("FPD_AUTH_MODE", "none").lower() == "oauth"


def get_authenticated_identity() -> Optional[str]:
    """Email/client_id of the authenticated caller, or None outside OAuth."""
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
        if token is not None:
            claims = getattr(token, "claims", None) or {}
            return claims.get("email") or getattr(token, "client_id", None)
    except Exception:
        # L-4: outside OAuth there is no token and a lookup failure is the
        # normal case, so it is swallowed. Under OAuth it is not: falling
        # back to the process-wide viewer key there would hand one tenant the
        # key that scopes every other tenant's downloads. Re-raised below.
        if _oauth_mode():
            raise
    return None


_PROCESS_VIEWER_KEY: Optional[str] = None


def get_viewer_key() -> str:
    """Per-registrant key scoping the recent-downloads registry (H2).

    Under OAuth, derived per authenticated identity so tenants sharing one
    HTTP process each see only their own downloads on /downloads and
    /api/recent-downloads. Under stdio/plain HTTP (single-operator), one
    random per-process key. Only its hash is stored by the proxy.
    """
    global _PROCESS_VIEWER_KEY
    if _PROCESS_VIEWER_KEY is None:
        import secrets
        _PROCESS_VIEWER_KEY = secrets.token_urlsafe(16)
    identity = get_authenticated_identity()
    if identity:
        import hashlib
        return hashlib.sha256(
            f"{_PROCESS_VIEWER_KEY}:{identity}".encode("utf-8")
        ).hexdigest()[:32]
    if _oauth_mode():
        # L-4: under OAuth an unidentified caller must not receive the
        # process-wide key. Every registry entry is scoped by the hash of
        # this value, so handing it out collapses tenant separation. A fresh
        # per-call key scopes the caller to their own (empty) view instead.
        import secrets
        return secrets.token_urlsafe(16)
    return _PROCESS_VIEWER_KEY
