"""The composition root has no import cycle, and the entry points still work.

F-A1 (initial-software-design-analyis): `main.py` imported `server_bootstrap`
at module scope while `server_bootstrap` reached back with three function-local
`from . import main as _main` statements to read `main.mcp` and
`main._AUTH_PROVIDER`. That is a real cycle; it survived only because the three
imports were deferred, so an import added to the wrong side became a startup
ImportError rather than a lint failure. The shared state now lives in
`server_app.py`, which both modules import.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "fpd_mcp"


def _module_scope_imports(path: Path) -> set:
    """Package-relative module names imported at module scope (not in a def)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:  # module scope only
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 1:
            for alias in node.names:
                names.add(alias.name)
    return names


def test_main_and_server_bootstrap_are_not_a_cycle():
    main_imports = _module_scope_imports(SRC / "main.py")
    bootstrap_imports = _module_scope_imports(SRC / "server_bootstrap.py")

    assert "server_bootstrap" in main_imports  # entry-point re-exports
    assert "main" not in bootstrap_imports
    assert "server_app" in bootstrap_imports


def test_server_bootstrap_does_not_reach_back_into_main():
    """Not even lazily: the three deferred imports were the cycle."""
    tree = ast.parse((SRC / "server_bootstrap.py").read_text(encoding="utf-8"))

    reaches_back = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module is None
        and any(alias.name == "main" for alias in node.names)
    ]
    assert reaches_back == []


def test_server_app_does_not_import_the_tool_layer_at_module_scope():
    """tools/documents imports server_bootstrap, which imports server_app.

    Keeping the tool imports inside build_server() is what makes that safe.
    """
    assert "tools" not in _module_scope_imports(SRC / "server_app.py")


def test_importing_server_app_does_not_build_the_server():
    """build_server() is the seam: importing the module must stay cheap."""
    code = (
        "import fpd_mcp.server_app as sa\n"
        "assert sa._BUILT is False, 'importing server_app built the server'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env={**_env(), "USPTO_API_KEY": "placeholder-for-import-test"},
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


@pytest.mark.parametrize(
    "code",
    [
        # main-first, the console-script order (fpd-mcp = fpd_mcp.main:run_server)
        "import fpd_mcp.main as m; import fpd_mcp.server_app as sa;"
        " assert m.mcp is sa.get_server(); print('OK')",
        # bootstrap-first, the order that used to be an ImportError risk
        "import fpd_mcp.server_bootstrap as sb; import fpd_mcp.main as m;"
        " assert m.mcp is sb.get_server(); print('OK')",
        # python -m fpd_mcp.main
        "import fpd_mcp.__main__ as mm; assert callable(mm.main); print('OK')",
    ],
    ids=["main-first", "bootstrap-first", "dash-m"],
)
def test_entry_points_resolve_in_any_import_order(code):
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env={**_env(), "USPTO_API_KEY": "placeholder-for-import-test"},
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def _env() -> dict:
    import os

    env = dict(os.environ)
    env.pop("FPD_AUTH_MODE", None)
    env.pop("FASTMCP_TRANSPORT", None)
    return env
