"""The 2026-09-03 review's small-effort LOW findings.

L-1  a non-ASCII credential header raised TypeError inside the auth check,
     turning a 401 into a 500 at five sites
L-4  get_viewer_key fell back to the process-wide key when identity lookup
     failed, collapsing tenant separation under OAuth
L-6  database files inherited the umask while key files beside them are 0600
L-7  in-flight login transactions were pruned by TTL with no cap
L-12 the upstream date reached Content-Disposition unsanitized
L-19 offset had a lower bound and no upper bound
L-23 /health was a static string and reported healthy on a broken server
"""

import os
import stat

import pytest


# --------------------------------------------------------------------- L-1


@pytest.mark.parametrize(
    "supplied,expected,result",
    [
        ("secret", "secret", True),
        ("secret", "other", False),
        ("\xff", "secret", False),   # used to raise TypeError
        ("secret", "\xff", False),
        ("", "secret", False),
        (None, "secret", False),
        ("secret", None, False),
        ("café", "café", False),  # equal but non-ASCII: still refused
    ],
)
def test_compare_credential_never_raises(supplied, expected, result):
    from fpd_mcp.shared.credentials import compare_credential

    assert compare_credential(supplied, expected) is result


async def test_a_non_ascii_api_key_header_yields_401_not_500():
    from fpd_mcp.middleware import APIKeyAuthMiddleware

    async def inner(scope, receive, send):  # pragma: no cover - not reached
        raise AssertionError("request should have been rejected")

    os.environ["INTERNAL_AUTH_SECRET"] = "x" * 32
    try:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "client": ("203.0.113.30", 4000),
            "headers": [(b"x-api-key", "\xff".encode("latin-1"))],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
        }
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():  # pragma: no cover - body never read
            return {"type": "http.request"}

        await APIKeyAuthMiddleware(inner)(scope, receive, send)
    finally:
        os.environ.pop("INTERNAL_AUTH_SECRET", None)

    assert sent[0]["status"] == 401


async def test_a_non_ascii_proxy_token_yields_401_not_500():
    """Built as a raw ASGI scope: httpx refuses to send a non-ASCII header,
    but Starlette decodes the wire bytes with latin-1, which is how the
    TypeError reached compare_digest in production."""
    from fastapi import HTTPException
    from starlette.requests import Request

    from fpd_mcp.proxy.server import ProxyTokenDependency

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/register-download",
        "headers": [(b"x-proxy-token", bytes([0xFF]))],
        "query_string": b"",
        "client": ("203.0.113.31", 4000),
    }

    async def receive():  # pragma: no cover - body never read
        return {"type": "http.request"}

    with pytest.raises(HTTPException) as excinfo:
        await ProxyTokenDependency()(Request(scope, receive))

    assert excinfo.value.status_code == 401


# --------------------------------------------------------------------- L-4


def test_viewer_key_does_not_fall_open_to_the_process_key_under_oauth(monkeypatch):
    from fpd_mcp.util import identity

    monkeypatch.setenv("FPD_AUTH_MODE", "oauth")
    identity._PROCESS_VIEWER_KEY = None

    first = identity.get_viewer_key()
    second = identity.get_viewer_key()

    # Unidentified callers get a throwaway key each, never the shared one
    # that scopes every registry entry.
    assert first != second
    assert first != identity._PROCESS_VIEWER_KEY


def test_viewer_key_is_stable_outside_oauth(monkeypatch):
    from fpd_mcp.util import identity

    monkeypatch.delenv("FPD_AUTH_MODE", raising=False)
    identity._PROCESS_VIEWER_KEY = None

    assert identity.get_viewer_key() == identity.get_viewer_key()


# --------------------------------------------------------------------- L-6


def test_a_created_database_is_not_world_readable(tmp_path):
    from fpd_mcp.util.database import create_secure_connection

    db_path = tmp_path / "probe.db"
    conn = create_secure_connection(str(db_path))
    try:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.commit()
    finally:
        conn.close()

    mode = stat.S_IMODE(os.stat(db_path).st_mode)
    assert mode & 0o077 == 0, oct(mode)


# --------------------------------------------------------------------- L-7


def test_in_flight_login_transactions_are_capped():
    import time

    from fpd_mcp.auth import provider as provider_module

    class _Bare:
        _txns: dict = {}
        _prune_txns = provider_module.FpdAuthProvider._prune_txns

    bare = _Bare()
    bare._txns = {
        f"txn-{i}": {"created_at": time.time() + i}
        for i in range(provider_module._MAX_IN_FLIGHT_TXNS + 50)
    }

    bare._prune_txns()

    assert len(bare._txns) == provider_module._MAX_IN_FLIGHT_TXNS
    # The oldest were the ones dropped.
    assert "txn-0" not in bare._txns
    assert f"txn-{provider_module._MAX_IN_FLIGHT_TXNS + 49}" in bare._txns


# -------------------------------------------------------------------- L-12


def test_an_upstream_date_cannot_inject_into_content_disposition():
    from fpd_mcp.proxy.server import generate_enhanced_filename

    filename = generate_enhanced_filename(
        petition_mail_date='2020-01-02"; x="y',
        app_number="13408005",
        patent_number=None,
        document_description="Decision on Petition",
        document_code="PET.DEC",
    )

    assert '"' not in filename
    assert ";" not in filename
    assert "\r" not in filename and "\n" not in filename


# -------------------------------------------------------------------- L-19


@pytest.mark.parametrize("offset", [-1, 10_001, 10**12])
async def test_search_tools_reject_an_out_of_range_offset(mock_runtime, offset):
    from fpd_mcp.tools.petitions import fpd_search_petitions_minimal

    result = await fpd_search_petitions_minimal(query="*", offset=offset)

    assert result["status_code"] == 400
    mock_runtime.api_client.search_petitions.assert_not_awaited()


async def test_an_offset_at_the_ceiling_is_accepted(mock_runtime):
    from fpd_mcp.config import api_constants
    from fpd_mcp.tools.petitions import fpd_search_petitions_minimal

    mock_runtime.api_client.search_petitions.return_value = {
        "petitionDecisionDataBag": [], "count": 0
    }

    result = await fpd_search_petitions_minimal(
        query="*", offset=api_constants.MAX_SEARCH_OFFSET
    )

    assert "error" not in result


# -------------------------------------------------------------------- L-23


def test_health_reports_component_state_not_a_static_string():
    from fpd_mcp.health import health_report

    healthy, components = health_report()

    assert set(components) == {"api_client", "link_cache", "download_proxy"}
    for name, detail in components.items():
        assert "ok" in detail and "detail" in detail, name
    assert isinstance(healthy, bool)


def test_health_is_degraded_when_the_api_client_cannot_initialize(monkeypatch):
    from fpd_mcp import health as health_module

    monkeypatch.setitem(
        health_module._CHECKS, "api_client",
        lambda: (False, "api_client unavailable (ValueError)"),
    )

    healthy, components = health_module.health_report()

    assert healthy is False
    assert components["api_client"]["ok"] is False


def test_health_response_is_503_when_degraded(monkeypatch):
    from fpd_mcp import health as health_module

    monkeypatch.setitem(
        health_module._CHECKS, "link_cache", lambda: (False, "unreadable")
    )

    response = health_module.health_response()

    assert response.status_code == 503


def test_health_proxy_check_trusts_the_socket_when_the_flag_is_unset(monkeypatch):
    """HTTP transport runs the proxy in a daemon thread that never sets
    _proxy_server_running; the port probe must carry the check there."""
    from fpd_mcp import health as health_module
    from fpd_mcp import server_bootstrap

    monkeypatch.setenv("ENABLE_PROXY_SERVER", "true")
    monkeypatch.setattr(server_bootstrap, "_proxy_server_running", False)

    monkeypatch.setattr(server_bootstrap, "_port_in_use", lambda port, host="127.0.0.1": True)
    assert health_module._check_proxy() == (True, "listening")

    monkeypatch.setattr(server_bootstrap, "_port_in_use", lambda port, host="127.0.0.1": False)
    assert health_module._check_proxy() == (False, "proxy not running")

    monkeypatch.setattr(server_bootstrap, "_proxy_server_running", True)
    assert health_module._check_proxy() == (True, "ok")
