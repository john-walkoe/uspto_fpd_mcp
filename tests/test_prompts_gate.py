"""Registration gate for the MCP prompt templates (FPD_manage_users parity).

All 10 prompts must be absent from the registered prompt set unless
FPD_ENABLE_PROMPTS=true (default off — the prompts disappear from
prompts/list on stdio and HTTP alike).

Registration happens at import time, so each state runs in a subprocess.
"""

import os
import subprocess
import sys

# T-5: the probe below reaches into mcp.local_provider._components, a FastMCP
# private. Necessary today (there is no public prompt-enumeration API on the
# server object) but it WILL break on a framework bump — this repo just went
# through a 3 -> 4 migration. Written against fastmcp 4.0.1; check this first
# when the prompts/list assertions start failing after an upgrade.
_PROBE = (
    "from fpd_mcp.main import mcp\n"
    "from fastmcp.prompts.base import Prompt\n"
    "names = [c.name for c in mcp.local_provider._components.values()"
    " if isinstance(c, Prompt)]\n"
    "print('COUNT', len(names))\n"
)


def _probe(extra_env: dict) -> int:
    env = {**os.environ}
    env.pop("FPD_ENABLE_PROMPTS", None)
    env.setdefault("USPTO_API_KEY", "x" * 30)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stdout.strip().splitlines()
    return int(lines[-1].split()[-1])


def test_prompts_absent_by_default():
    assert _probe({}) == 0


def test_prompts_absent_when_explicitly_false():
    assert _probe({"FPD_ENABLE_PROMPTS": "false"}) == 0


def test_prompts_registered_when_enabled():
    assert _probe({"FPD_ENABLE_PROMPTS": "true"}) == 10
