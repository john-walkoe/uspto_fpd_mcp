"""ARCH-02 (review 2026-09-28): .env must load before anything reads settings.

`Settings()` (runtime.py, module scope) used to construct itself before
`.env` was ever loaded — the load lived inside `run_server()`'s function
BODY, which only runs after `main.py` has already finished importing (and
`main.py`'s own first substantive import, `from .runtime import (...)`,
is what constructs `Settings()`). `env_bootstrap.load_repo_env()` fixes the
ordering; these tests cover the function's own behavior (path resolution,
override semantics, idempotency, no upward walk) plus a static guard that
the two entry-point modules actually call it first, so a future edit that
reorders the imports fails loudly instead of silently regressing.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "fpd_mcp"


@pytest.fixture
def fresh_env_bootstrap(monkeypatch):
    """A freshly-imported env_bootstrap module with its `_loaded` latch
    reset, so each test observes a clean load_repo_env() call."""
    monkeypatch.delitem(sys.modules, "fpd_mcp.env_bootstrap", raising=False)
    module = importlib.import_module("fpd_mcp.env_bootstrap")
    yield module
    monkeypatch.delitem(sys.modules, "fpd_mcp.env_bootstrap", raising=False)


def test_loads_the_named_env_file(monkeypatch, tmp_path, fresh_env_bootstrap):
    env_file = tmp_path / "custom.env"
    env_file.write_text("FPD_ARCH02_TEST_MARKER=hit\n")
    monkeypatch.setenv("FPD_ENV_FILE", str(env_file))
    monkeypatch.delenv("FPD_ARCH02_TEST_MARKER", raising=False)

    fresh_env_bootstrap.load_repo_env()

    assert __import__("os").environ.get("FPD_ARCH02_TEST_MARKER") == "hit"


def test_an_already_set_os_var_wins_over_the_env_file(
    monkeypatch, tmp_path, fresh_env_bootstrap
):
    env_file = tmp_path / "custom.env"
    env_file.write_text("FPD_ARCH02_TEST_MARKER=from-dotenv\n")
    monkeypatch.setenv("FPD_ENV_FILE", str(env_file))
    monkeypatch.setenv("FPD_ARCH02_TEST_MARKER", "from-os")

    fresh_env_bootstrap.load_repo_env()

    assert __import__("os").environ.get("FPD_ARCH02_TEST_MARKER") == "from-os"


def test_missing_env_file_is_a_silent_no_op(monkeypatch, tmp_path, fresh_env_bootstrap):
    monkeypatch.setenv("FPD_ENV_FILE", str(tmp_path / "does-not-exist.env"))

    fresh_env_bootstrap.load_repo_env()  # must not raise


def test_load_repo_env_is_idempotent(monkeypatch, tmp_path, fresh_env_bootstrap):
    """A second call (e.g. main.py AND server_app.py both call it) must not
    re-read the file or clobber a value the process has since changed."""
    env_file = tmp_path / "custom.env"
    env_file.write_text("FPD_ARCH02_TEST_MARKER=first-load\n")
    monkeypatch.setenv("FPD_ENV_FILE", str(env_file))
    monkeypatch.delenv("FPD_ARCH02_TEST_MARKER", raising=False)

    fresh_env_bootstrap.load_repo_env()
    assert __import__("os").environ.get("FPD_ARCH02_TEST_MARKER") == "first-load"

    # Overwrite the file and the process env, then call again: neither the
    # second call re-reading the file nor override=True should apply here.
    env_file.write_text("FPD_ARCH02_TEST_MARKER=second-load\n")
    import os
    os.environ["FPD_ARCH02_TEST_MARKER"] = "changed-after-first-load"

    fresh_env_bootstrap.load_repo_env()

    assert os.environ.get("FPD_ARCH02_TEST_MARKER") == "changed-after-first-load"


def test_default_path_is_the_repo_root_env_not_an_ancestor(fresh_env_bootstrap):
    """Never walks above the repo (the bare load_dotenv() this replaced
    did, and could land on an unrelated ancestor .env)."""
    assert fresh_env_bootstrap._REPO_ROOT == REPO


# --------------------------------------------------------- ordering guards


def _text_before(source: str, needle_a: str, needle_b: str) -> bool:
    ia, ib = source.find(needle_a), source.find(needle_b)
    assert ia != -1, f"{needle_a!r} not found"
    assert ib != -1, f"{needle_b!r} not found"
    return ia < ib


def test_main_py_loads_env_before_importing_runtime():
    source = (SRC / "main.py").read_text()
    assert _text_before(source, "load_repo_env()", "from .runtime import")


def test_main_py_imports_env_bootstrap_before_any_other_fpd_mcp_import():
    source = (SRC / "main.py").read_text()
    imports = re.findall(r"^from \.\S* import|^from \.{2}\S* import", source, re.MULTILINE)
    assert imports, "no relative fpd_mcp imports found in main.py"
    assert imports[0].startswith("from .env_bootstrap import"), (
        f"first relative import in main.py must be env_bootstrap, got: {imports[0]!r}"
    )


def test_server_app_py_loads_env_before_fastmcp_compat():
    source = (SRC / "server_app.py").read_text()
    assert _text_before(source, "load_repo_env()", "_apply_fastmcp_compat()")


def test_env_bootstrap_module_imports_nothing_else_from_fpd_mcp():
    """load_repo_env must be reachable without triggering the settings
    bootstrap it exists to run ahead of — so this module imports no
    fpd_mcp sibling."""
    source = (SRC / "env_bootstrap.py").read_text()
    import_lines = re.findall(r"^\s*(?:import|from)\s+\S+.*$", source, re.MULTILINE)
    assert import_lines, "no import statements found"
    assert not any(
        line.lstrip().startswith(("from .", "from fpd_mcp")) for line in import_lines
    ), import_lines
