"""Load this repo's own .env before anything else reads settings.

ARCH-02 (review 2026-09-28): `Settings()` (and `AuthSettings.from_env()`,
and the admin/prompts registration gates read via `os.getenv(...)` at
import time — `tools/admin.py:26-28`, `server_app.py:107-109, 211-224`)
used to run BEFORE `.env` was ever loaded. `main.py`'s first substantive
import, `from .runtime import (...)`, constructs `runtime.py`'s
module-level `settings = Settings()` as a side effect of that import — and
that import happens while `main.py` itself is still being imported, long
before `run_server()` is ever CALLED. The old `.env` load
(`proxy/server.py:load_env_file`) ran inside `run_server()`'s function
BODY, which only executes after `main.py` has already finished importing
— so it always ran too late. OAuth mode, the admin tool gate, and the
downloads-panel security policy could therefore silently miss anything set
only in `.env`; only variables already exported in the parent shell (or
Docker's `env_file:`) were ever seen.

Call `load_repo_env()` as the very first statement in `main.py`, before any
other `fpd_mcp` import. Deliberately stdlib + python-dotenv only, with NO
imports of any other `fpd_mcp` submodule, so importing this module can
never itself trigger the settings bootstrap it exists to run ahead of.
"""
from __future__ import annotations

import os
from pathlib import Path

# src/fpd_mcp/env_bootstrap.py -> fpd_mcp/ -> src/ -> repo root (3 hops).
# Matches config/settings.py's own project_root computation (one directory
# deeper, one more hop) — see runtime.py's F-A6 note on keeping this single.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_loaded = False


def load_repo_env() -> None:
    """Load this repo's own `.env` exactly once. Idempotent, so it is safe
    to call again from a secondary entry point (the standalone proxy
    runner, a test) without double-loading or overriding an already-set
    variable.

    Never walks above the repo. Plain `load_dotenv()` searches upward from
    the caller's location and can land on an unrelated ancestor `.env`
    (for example a parent directory's `.env` holding keys for other
    projects, which this server would then pick up without anyone having
    configured them). `FPD_ENV_FILE` overrides the path explicitly;
    otherwise only this repo's own `.env` is ever considered, and a
    missing file is a silent no-op (there is nothing to load in Docker,
    where env vars arrive via `environment:`/`env_file:` instead).
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    explicit = os.getenv("FPD_ENV_FILE", "").strip()
    path = Path(explicit) if explicit else (_REPO_ROOT / ".env")
    if path.is_file():
        load_dotenv(dotenv_path=path, override=False)
