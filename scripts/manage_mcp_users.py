"""Manage the mcp_users registered-user list (OAuth authorization source).

  uv run python scripts/manage_mcp_users.py list
  uv run python scripts/manage_mcp_users.py add jane@firm.com --name "Jane Doe"
  uv run python scripts/manage_mcp_users.py add john@x.com --role admin
  uv run python scripts/manage_mcp_users.py set-role jane@firm.com admin
  uv run python scripts/manage_mcp_users.py deactivate jane@firm.com
  uv run python scripts/manage_mcp_users.py activate jane@firm.com

A user may connect an MCP client through the Google / Entra ID sign-in only
while their row is active; role 'admin' adds the fpd:admin scope (the
FPD_manage_users tool). Deactivation takes effect at the user's next
token refresh (access tokens live FPD_AUTH_ACCESS_TTL seconds, 1h).

The SQLite file is FPD_AUTH_DB_PATH (default data/mcp_auth.db). On the
deployment box run inside the container against the mounted DB:
`docker exec fpd-mcp python scripts/manage_mcp_users.py list`.
FPD reads the SHARED paid-tier user file hosted by PFW (same DB, all three servers).
This is the bootstrap surface — the first admin must be seeded here before
the FPD_manage_users MCP tool can be used.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _cli_actor() -> str:
    """Identify the operator running this script for the audit record."""
    try:
        who = getpass.getuser()
    except Exception:
        who = os.getenv("USER") or os.getenv("USERNAME") or "unknown"
    return f"cli:{who}"


def _audit(action: str, target: str, success: bool, role: str = None,
           detail: str = None) -> None:
    """Mirror tools/admin.py::_audit_user_management for the CLI (M-11).

    The mcp_users table is shared with PFW and PTAB, so a grant made here is
    a grant on three servers and needs the same record as one made through
    FPD_manage_users. Never raises: a failed audit write must not turn a
    successful grant into a CLI failure.
    """
    try:
        from fpd_mcp.shared.security_logger import security_logger

        security_logger.log_admin_action(
            actor=_cli_actor(),
            action=action,
            target=target,
            role=role,
            success=success,
            detail=detail,
        )
    except Exception as audit_error:  # pragma: no cover - defensive
        print(
            f"warning: admin audit write failed: {type(audit_error).__name__}",
            file=sys.stderr,
        )


async def run(args: argparse.Namespace) -> int:
    from fpd_mcp.auth.store import McpUserStore
    from fpd_mcp.config.log_config import setup_logging

    # Attach the security handler so CLI mutations land in security.log
    # next to the ones made through FPD_manage_users.
    setup_logging(os.getenv("LOG_LEVEL", "WARNING"))

    db_path = os.getenv("FPD_AUTH_DB_PATH", "data/mcp_auth.db")
    store = McpUserStore(db_path)

    if args.command == "list":
        users = await store.list_users()
        if not users:
            print("No registered users.")
            return 0
        fmt = "{:<38} {:<6} {:<8} {:<24} {}"
        print(fmt.format("EMAIL", "ROLE", "ACTIVE", "LAST LOGIN", "NAME"))
        for u in users:
            last = (
                f"{u['last_login_at']:%Y-%m-%d %H:%M} {u['last_login_idp'] or ''}"
                if u["last_login_at"]
                else "-"
            )
            print(fmt.format(
                u["email"], u["role"], str(u["active"]), last,
                u["display_name"] or "",
            ))
        return 0

    email = args.email.strip().lower()
    if args.command == "add":
        await store.upsert_user(
            email, role=args.role, display_name=args.name, notes=args.notes
        )
        _audit("add", email, True, role=args.role)
        print(f"added/updated {email} role={args.role}")
    elif args.command == "set-role":
        user = await store.get_user(email)
        if user is None:
            _audit("set_role", email, False, role=args.role, detail="no such user")
            print(f"no such user: {email}", file=sys.stderr)
            return 1
        await store.upsert_user(email, role=args.role, active=user["active"])
        _audit("set_role", email, True, role=args.role)
        print(f"{email} role -> {args.role}")
    elif args.command in ("activate", "deactivate"):
        active = args.command == "activate"
        if not await store.set_active(email, active):
            _audit(args.command, email, False, detail="no such user")
            print(f"no such user: {email}", file=sys.stderr)
            return 1
        _audit(args.command, email, True)
        print(f"{email} active -> {active}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    p_add = sub.add_parser("add")
    p_add.add_argument("email")
    p_add.add_argument("--role", choices=("user", "admin"), default="user")
    p_add.add_argument("--name", default=None, help="display name")
    p_add.add_argument("--notes", default=None)

    p_role = sub.add_parser("set-role")
    p_role.add_argument("email")
    p_role.add_argument("role", choices=("user", "admin"))

    for cmd in ("activate", "deactivate"):
        p = sub.add_parser(cmd)
        p.add_argument("email")

    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
