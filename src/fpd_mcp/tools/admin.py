"""Registered-user management tool (fpd:admin scope in OAuth mode).

Registration-gated by FPD_ENABLE_USER_MANAGEMENT (default off — matches the
PFW/PTAB pattern / neo4j NEO4J_READ_ONLY approach). Extracted from main.py
(mechanical decomposition, no behavior change)."""

import os
from typing import Any, Dict

from fastmcp.apps import AppConfig

from ..app_uris import USER_MANAGEMENT_URI
from ..shared.error_utils import format_error_response
from ..util.secure_logger import get_secure_logger

logger = get_secure_logger(__name__)

# Registration gate for the FPD_manage_users admin tool (neo4j
# NEO4J_READ_ONLY pattern: filtered at registration time, so it never
# appears in tools/list when off). Default OFF: stdio doesn't need it (seed
# admins with scripts/manage_mcp_users.py), and outside OAuth mode it would
# be protected only by the shared INTERNAL_AUTH_SECRET. Prod OAuth compose
# must set FPD_ENABLE_USER_MANAGEMENT=true.
USER_MANAGEMENT_ENABLED = (
    os.getenv("FPD_ENABLE_USER_MANAGEMENT", "false").lower() == "true"
)

# Set by register(): the OAuth provider's user store is reused when present
_auth_provider = None

_EMAIL_RE = None  # compiled lazily


def _get_user_store():
    """User store for the management tool: reuse the auth provider's store in
    OAuth mode; otherwise open the configured SQLite path directly (stdio /
    plain-HTTP use, e.g. seeding before OAuth is switched on)."""
    if _auth_provider is not None:
        return _auth_provider._users
    from ..auth import AuthSettings
    from ..auth.store import McpUserStore

    return McpUserStore(AuthSettings.from_env().auth_db_path)


async def _execute_user_management_action(
    store, action: str, email: str, role: str, display_name: str, notes: str
):
    """Perform the add/set_role/activate/deactivate mutation for
    fpd_manage_users and return a confirmation message string, or an error
    dict. (action == "list" matches none of the branches below and falls
    through to "", unchanged from before.) Extracted from fpd_manage_users
    (mechanical decomposition, no behavior change)."""
    if action == "add":
        if role not in ("user", "admin"):
            return {"error": f"role must be 'user' or 'admin', got {role!r}"}
        await store.upsert_user(
            email,
            role=role,
            display_name=display_name or None,
            notes=notes or None,
        )
        return f"Added/updated {email} with role '{role}'."
    elif action == "set_role":
        if role not in ("user", "admin"):
            return {"error": f"role must be 'user' or 'admin', got {role!r}"}
        existing = await store.get_user(email)
        if existing is None:
            return {"error": f"no such user: {email}"}
        await store.upsert_user(email, role=role, active=existing["active"])
        return f"{email} role set to '{role}'."
    elif action in ("activate", "deactivate"):
        active = action == "activate"
        if not await store.set_active(email, active):
            return {"error": f"no such user: {email}"}
        return f"{email} is now {'active' if active else 'deactivated'}."
    return ""


def _serialize_user_management_response(
    action: str, message: str, users: list
) -> Dict[str, Any]:
    """Build the fpd_manage_users response envelope from the user rows.
    Extracted from fpd_manage_users verbatim (mechanical decomposition, no
    behavior change)."""
    return {
        "action": action,
        "message": message or f"{len(users)} registered user(s).",
        "users": [
            {
                "email": u["email"],
                "display_name": u["display_name"],
                "role": u["role"],
                "active": u["active"],
                "added_at": u["added_at"].isoformat() if u["added_at"] else None,
                "last_login_at": (
                    u["last_login_at"].isoformat() if u["last_login_at"] else None
                ),
                "last_login_idp": u["last_login_idp"],
                "notes": u["notes"],
            }
            for u in users
        ],
    }


async def fpd_manage_users(
    action: str = "list",
    email: str = "",
    role: str = "user",
    display_name: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """Manage the registered-user list for OAuth sign-in (ADMIN ONLY).

    Lists, adds, activates, deactivates, or changes the role of registered
    users. A user may sign in via Google / Microsoft only while their row is
    active; role 'admin' additionally grants this user-management tool.
    FPD reads the SHARED paid-tier user database hosted by PFW — changes
    here apply to PFW, PTAB, and FPD alike. Changes take effect at the
    user's next token refresh (up to 1 hour).

    Args:
        action: One of: list, add, set_role, activate, deactivate
        email: Target user email (required for all actions except list)
        role: 'user' or 'admin' (for add / set_role)
        display_name: Optional display name (for add)
        notes: Optional notes (for add)

    Returns:
        The full user table after the action, plus a confirmation message.
    """
    global _EMAIL_RE
    import re as _re

    if _EMAIL_RE is None:
        _EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    valid_actions = ("list", "add", "set_role", "activate", "deactivate")
    if action not in valid_actions:
        return {"error": f"action must be one of {valid_actions}, got {action!r}"}

    store = _get_user_store()
    message = ""
    try:
        if action != "list":
            email = email.strip().lower()
            if not _EMAIL_RE.match(email):
                return {"error": f"invalid email address: {email!r}"}

        result = await _execute_user_management_action(store, action, email, role, display_name, notes)
        if isinstance(result, dict):
            return result
        message = result

        users = await store.list_users()
        return _serialize_user_management_response(action, message, users)
    except Exception as e:
        logger.error("User management action failed: %s", type(e).__name__)
        # L18: route through format_error_response like every other tool so
        # the message is sanitized and generic in production, instead of a
        # raw dict carrying unsanitized str(e) regardless of environment.
        return format_error_response(f"User management failed: {e}", 500)


def register(mcp, auth_provider=None) -> None:
    """Register fpd_manage_users when the gate allows it."""
    global _auth_provider
    _auth_provider = auth_provider
    if USER_MANAGEMENT_ENABLED:
        mcp.tool(name="FPD_manage_users", app=AppConfig(resource_uri=USER_MANAGEMENT_URI), annotations={"defer_loading": True})(fpd_manage_users)
        if _auth_provider is None:
            # Enabled without OAuth: the only protection on this tool is the
            # transport itself (stdio) or the shared INTERNAL_AUTH_SECRET (HTTP
            # mode=none) — anyone holding that ecosystem-wide secret could
            # self-grant admin across PFW/PTAB/FPD via the shared user DB.
            logger.warning(
                "FPD_manage_users is ENABLED without OAuth per-identity gating "
                "(FPD_ENABLE_USER_MANAGEMENT=true, FPD_AUTH_MODE!=oauth). "
                "Recommended: leave it disabled and use scripts/manage_mcp_users.py."
            )
    else:
        logger.info(
            "FPD_manage_users not registered (FPD_ENABLE_USER_MANAGEMENT is off; "
            "default). Use scripts/manage_mcp_users.py for user administration."
        )
