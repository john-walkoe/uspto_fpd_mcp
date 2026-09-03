"""The startup path: proxy lifecycle, PFW discovery, client sharing.

T-1 (testing-implementation): `server_bootstrap.py` was the largest real
coverage gap in the repo at 7.1% of 239 statements. It holds the two
highest-complexity, deepest-nested functions in `src/` and the transport /
middleware assembly, and a failure here is a server that does not come up, or
one that comes up with the probe middleware misordered.

Also pinned here:
F-A8  the "is something on this port" probe was written verbatim twice, plus
      a third HTTP-probe variant for PFW discovery
F-D1  the proxy built a SECOND FPDClient, so the concurrency bulkhead, the
      circuit breaker and the fallback cache were split in half
F-D7  task supervision was attached on the always-on start path only
F-E5  the on-demand health check was a BLOCKING requests.get inside an async
      function, held under the startup lock
"""

import asyncio
import inspect

import pytest

from fpd_mcp import server_bootstrap


@pytest.fixture(autouse=True)
def _reset_proxy_state(monkeypatch):
    monkeypatch.setattr(server_bootstrap, "_proxy_server_running", False)
    monkeypatch.setattr(server_bootstrap, "_proxy_server_task", None)
    yield
    server_bootstrap._proxy_server_running = False
    server_bootstrap._proxy_server_task = None


# --------------------------------------------------------------------- F-A8


def test_port_probe_exists_once():
    """It was three lines of socket code written verbatim in two places."""
    source = inspect.getsource(server_bootstrap)

    assert source.count("connect_ex") == 1


def test_port_in_use_reports_a_free_port_as_free():
    # Port 0 is never bindable as a destination.
    assert server_bootstrap._port_in_use(0) is False


# --------------------------------------------------------------- PFW probing


@pytest.mark.parametrize(
    "open_ports,expected",
    [
        ({8080}, 8080),
        ({8080, 8079}, 8080),          # the primary wins
        ({8079}, 8079),                # alternatives on the final attempt
        ({8082}, 8082),
        ({8083}, 8083),
        (set(), None),
        ({9999}, None),                # an unrelated port is not adopted
    ],
)
def test_probe_pfw_proxy_ports_picks_the_expected_port(
    monkeypatch, open_ports, expected
):
    monkeypatch.setattr(
        server_bootstrap, "_proxy_responds",
        lambda port, timeout: port in open_ports,
    )

    result = server_bootstrap._probe_pfw_proxy_ports(
        max_retries=2, retry_delay=0, timeout=0.1
    )

    assert result == expected


def test_alternative_ports_are_only_probed_on_the_final_attempt(monkeypatch):
    """Probing them every round is the startup delay the comment warns about."""
    probed = []

    def _record(port, timeout):
        probed.append(port)
        return False

    monkeypatch.setattr(server_bootstrap, "_proxy_responds", _record)

    server_bootstrap._probe_pfw_proxy_ports(
        max_retries=3, retry_delay=0, timeout=0.1
    )

    assert probed.count(server_bootstrap.PFW_PRIMARY_PROXY_PORT) == 3
    for alt in server_bootstrap.PFW_ALTERNATIVE_PROXY_PORTS:
        assert probed.count(alt) == 1


def test_an_explicit_centralized_port_is_used_when_it_answers(monkeypatch):
    monkeypatch.setattr(
        server_bootstrap, "_proxy_responds", lambda port, timeout: port == 9100
    )

    assert server_bootstrap._try_explicit_centralized_port("9100") == 9100


def test_an_explicit_centralized_port_that_does_not_answer_is_refused(monkeypatch):
    monkeypatch.setattr(
        server_bootstrap, "_proxy_responds", lambda port, timeout: False
    )

    assert server_bootstrap._try_explicit_centralized_port("9100") is None


@pytest.mark.parametrize("value", ["none", "", "not-a-port", "80a"])
def test_a_non_numeric_centralized_port_is_ignored(monkeypatch, value):
    monkeypatch.setattr(
        server_bootstrap, "_proxy_responds",
        lambda port, timeout: pytest.fail("should not have probed"),
    )

    assert server_bootstrap._try_explicit_centralized_port(value) is None


def test_detect_pfw_proxy_skips_every_probe_when_pfw_is_absent(monkeypatch):
    """The `none` sentinel is what keeps stdio startup instant."""
    monkeypatch.setenv("CENTRALIZED_PROXY_PORT", "none")
    monkeypatch.setattr(
        server_bootstrap, "_proxy_responds",
        lambda port, timeout: pytest.fail("should not have probed"),
    )

    assert server_bootstrap._detect_pfw_proxy() is None


# ------------------------------------------------ on-demand proxy start (F-D7)


async def test_an_occupied_port_is_adopted_not_double_bound(monkeypatch):
    """Double-binding makes uvicorn call sys.exit(1), which takes the whole
    MCP server down mid tool-call."""
    monkeypatch.setattr(server_bootstrap, "_port_in_use", lambda port: True)

    async def _must_not_run(*args, **kwargs):  # pragma: no cover
        raise AssertionError("started a second server on an occupied port")

    monkeypatch.setattr(server_bootstrap, "_run_proxy_server", _must_not_run)

    assert await server_bootstrap._ensure_proxy_server_running(8081) is True
    assert server_bootstrap._proxy_server_running is True


async def test_the_fast_path_skips_the_lock_when_already_running(monkeypatch):
    monkeypatch.setattr(server_bootstrap, "_proxy_server_running", True)
    monkeypatch.setattr(
        server_bootstrap, "_port_in_use",
        lambda port: pytest.fail("should not have probed the port"),
    )

    assert await server_bootstrap._ensure_proxy_server_running(8081) is True


async def test_the_on_demand_path_supervises_its_task(monkeypatch):
    """F-D7: only the always-on path attached _on_proxy_task_done, so an
    on-demand proxy that exited left _proxy_server_running stuck True and
    the tools kept emitting URLs that no longer worked."""
    monkeypatch.setattr(server_bootstrap, "_port_in_use", lambda port: False)

    async def _exits_immediately(*args, **kwargs):
        return None

    monkeypatch.setattr(server_bootstrap, "_run_proxy_server", _exits_immediately)

    class _Response:
        status_code = 200

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return _Response()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _Client())

    await server_bootstrap._ensure_proxy_server_running(8081)
    task = server_bootstrap._proxy_server_task
    assert task is not None
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # The supervision callback ran and cleared the flag, so a later download
    # attempt starts the proxy again instead of trusting a dead one.
    assert server_bootstrap._proxy_server_running is False


def test_the_health_check_does_not_block_the_event_loop():
    """F-E5: it was `requests.get(...)` inside an async function, under the
    startup lock, so it stalled the MCP server, the proxy and every in-flight
    tool call for up to a second."""
    import ast

    tree = ast.parse(inspect.getsource(server_bootstrap._ensure_proxy_server_running))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "requests"
    ]
    assert calls == []
    assert "await _probe_client.get" in inspect.getsource(
        server_bootstrap._ensure_proxy_server_running
    )


# --------------------------------------------------------------------- F-D1


def test_the_in_loop_proxy_shares_the_process_client():
    """Two FPDClients meant two semaphores, two breakers and two caches."""
    signature = inspect.signature(server_bootstrap._run_proxy_server)

    assert signature.parameters["share_client"].default is True


def test_the_http_thread_proxy_does_not_share_the_client():
    """Its event loop is a different one; the asyncio locks cannot cross."""
    source = inspect.getsource(server_bootstrap._run_http_transport)

    assert "share_client=False" in source


async def test_create_proxy_app_accepts_an_injected_client():
    from fpd_mcp.proxy.server import create_proxy_app

    signature = inspect.signature(create_proxy_app)

    assert "client" in signature.parameters
    assert signature.parameters["client"].default is None


# ------------------------------------------------------------ CORS assembly


@pytest.mark.parametrize("value", ["not-a-url", "ftp://x", "https://a b"])
def test_a_malformed_cors_origin_is_rejected(monkeypatch, value):
    monkeypatch.setenv("CORS_EXTRA_ORIGIN", value)

    with pytest.raises(ValueError):
        server_bootstrap._build_cors_origins(8005)


def test_a_valid_cors_origin_is_added(monkeypatch):
    monkeypatch.setenv("CORS_EXTRA_ORIGIN", "https://fpd.example.com")

    origins = server_bootstrap._build_cors_origins(8005)

    assert "https://fpd.example.com" in origins


def test_loopback_origins_are_always_present(monkeypatch):
    monkeypatch.delenv("CORS_EXTRA_ORIGIN", raising=False)

    origins = server_bootstrap._build_cors_origins(8005)

    assert any("127.0.0.1" in o or "localhost" in o for o in origins)


# ------------------------------------------------------- proxy port parsing


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"FPD_PROXY_PORT": "9001"}, 9001),
        ({"PROXY_PORT": "9002"}, 9002),
        ({"FPD_PROXY_PORT": "9001", "PROXY_PORT": "9002"}, 9001),
        ({"FPD_PROXY_PORT": "not-a-port"}, 8081),
        ({}, 8081),
    ],
)
def test_get_local_proxy_port(monkeypatch, env, expected):
    monkeypatch.delenv("FPD_PROXY_PORT", raising=False)
    monkeypatch.delenv("PROXY_PORT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    assert server_bootstrap.get_local_proxy_port() == expected
