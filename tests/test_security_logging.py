"""security.log actually receives records, and mcp_users mutations audit.

Two findings from the 2026-09-03 review:

- H-2: `config/log_config.py` bound the security handler to logger `security`
  while the only producer emits on `fpd_mcp.security`. Those are siblings in
  the logger hierarchy, not ancestor and descendant, so the file was created,
  chmod'd 0600 and stayed empty forever.
- M-11: no audit record for any `mcp_users` mutation, on a table shared with
  PFW and PTAB.
"""

import logging

import pytest

import fpd_mcp.tools.admin as admin_module
from fpd_mcp.config.log_config import setup_logging
from fpd_mcp.shared.security_logger import security_logger
from fpd_mcp.tools.admin import fpd_manage_users

from test_tools_misc import _FakeUserStore  # noqa: F401  (shared fake store)


@pytest.fixture
def logging_to(tmp_path, monkeypatch):
    """Point setup_logging() at a temp dir and restore the handler graph.

    setup_logging() rebuilds the root logger, so the previous handlers are
    snapshotted and put back; otherwise every later test in the session logs
    into a deleted tmp directory.
    """
    root = logging.getLogger()
    sec = logging.getLogger("fpd_mcp.security")
    saved = (root.handlers[:], root.level, sec.handlers[:], sec.level, sec.propagate)

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    setup_logging("INFO")
    try:
        yield tmp_path
    finally:
        for handler in root.handlers[:] + sec.handlers[:]:
            handler.close()
        root.handlers[:], root.level = saved[0], saved[1]
        sec.handlers[:], sec.level, sec.propagate = saved[2], saved[3], saved[4]


def test_security_events_reach_security_log(logging_to):
    security_logger.log_authentication_failure(client_ip="1.2.3.4", reason="bad key")

    contents = (logging_to / "security.log").read_text()
    assert "authentication_failure" in contents


def test_security_events_do_not_land_in_the_application_log(logging_to):
    security_logger.log_authentication_failure(client_ip="1.2.3.4", reason="bad key")

    assert "authentication_failure" not in (logging_to / "fpd_mcp.log").read_text()


@pytest.fixture
def fake_user_store(monkeypatch):
    store = _FakeUserStore()
    monkeypatch.setattr(admin_module, "_get_user_store", lambda: store)
    return store


@pytest.mark.parametrize(
    "action,kwargs",
    [
        ("add", {"role": "admin"}),
        ("set_role", {"role": "admin"}),
        ("activate", {}),
        ("deactivate", {}),
    ],
)
async def test_every_mutation_is_audited(fake_user_store, logging_to, action, kwargs):
    await fpd_manage_users(action="add", email="alice@example.com", role="user")
    (logging_to / "security.log").write_text("")

    await fpd_manage_users(action=action, email="alice@example.com", **kwargs)

    contents = (logging_to / "security.log").read_text()
    assert "admin_action" in contents
    assert f'"action": "{action}"' in contents


async def test_list_is_not_audited(fake_user_store, logging_to):
    await fpd_manage_users(action="list")

    assert "admin_action" not in (logging_to / "security.log").read_text()


async def test_failed_mutation_is_audited_as_a_failure(fake_user_store, logging_to):
    result = await fpd_manage_users(action="deactivate", email="nobody@example.com")

    assert "error" in result
    contents = (logging_to / "security.log").read_text()
    assert "admin_action" in contents
    # The sanitizer renders values as strings on the way to the sink.
    assert '"success": "False"' in contents


async def test_api_key_rejection_reaches_the_security_log(logging_to):
    """M-23: middleware.py logged prose to fpd_mcp.log and nothing typed."""
    from fpd_mcp.middleware import APIKeyAuthMiddleware

    async def inner(scope, receive, send):  # pragma: no cover - not reached
        raise AssertionError("request should have been rejected")

    import os

    os.environ["INTERNAL_AUTH_SECRET"] = "x" * 32
    try:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "client": ("203.0.113.7", 4000),
            "headers": [(b"x-api-key", b"wrong")],
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
    contents = (logging_to / "security.log").read_text()
    assert "authentication_failure" in contents
    assert "x-api-key missing or mismatch" in contents
    assert "wrong" not in contents  # the presented key never reaches the sink


def test_proxy_rate_limit_rejection_reaches_the_security_log(logging_to):
    """M-23: proxy/rate_limiter.py logged prose only."""
    from fpd_mcp.proxy.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=1, time_window=10)
    assert limiter.is_allowed("203.0.113.8") is True
    assert limiter.is_allowed("203.0.113.8") is False

    contents = (logging_to / "security.log").read_text()
    assert "rate_limit_exceeded" in contents
    assert "proxy_download" in contents


def test_reading_the_limiter_does_not_create_a_bucket():
    """M-4: the defaultdict made every read insert a permanent entry."""
    from fpd_mcp.proxy.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=5, time_window=10)
    limiter.get_remaining_requests("203.0.113.10")
    limiter.get_reset_time("203.0.113.10")

    assert limiter.requests == {}


def test_idle_buckets_are_evicted_once_the_window_passes():
    """M-4: buckets were trimmed but never removed, so the map only grew."""
    from fpd_mcp.proxy.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=5, time_window=0)
    assert limiter.is_allowed("203.0.113.11") is True
    assert limiter.requests  # bucket exists while the request is in-window

    assert limiter.is_allowed("203.0.113.11") is True
    limiter.get_remaining_requests("203.0.113.11")
    assert limiter.requests == {}


async def test_oauth_rate_limit_rejections_are_logged(logging_to, monkeypatch):
    """M-23: neither OAuth limiter produced a security-log record."""
    from fpd_mcp.auth.provider import _FixedWindowRateLimiter, _RateLimitedASGIApp

    async def app(scope, receive, send):  # pragma: no cover - not reached
        raise AssertionError("request should have been rejected")

    limiter = _FixedWindowRateLimiter(max_requests=1, window_seconds=60.0)
    wrapped = _RateLimitedASGIApp(app, limiter)
    scope = {"type": "http", "client": ("203.0.113.9", 5000), "path": "/token"}

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover - body never read
        return {"type": "http.request"}

    assert limiter.allow("203.0.113.9") is True  # burn the single allowance
    await wrapped(scope, receive, send)

    assert sent[0]["status"] == 429
    contents = (logging_to / "security.log").read_text()
    assert "rate_limit_exceeded" in contents
    assert "/token" in contents
