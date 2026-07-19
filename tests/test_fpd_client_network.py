"""Offline mocked tests for FPDClient's network layer (api/fpd_client.py):
retry-on-5xx succeeding on the 2nd attempt, no-retry on 4xx, 429 being
retryable with a fixed >=5s delay, and the circuit-open -> stale-cache
fallback path.

httpx.AsyncClient is patched to route through httpx.MockTransport (the same
pattern already used in tests/test_security_hardening_phase23.py) so no real
network calls happen; asyncio.sleep is patched to a no-op so retry-delay
tests run instantly.
"""

import time

import httpx
import pytest

import fpd_mcp.api.fpd_client as fpd_client_module
import fpd_mcp.shared.uspto_shared_rate_limiter as rate_limiter_module
from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.shared.circuit_breaker import CircuitState


@pytest.fixture(autouse=True)
def _shared_rate_limiter_disabled(monkeypatch):
    """The shared rate limiter's `get_shared_limiter()` singleton is a
    process-wide global (tests/test_shared_rate_limiter.py exercises it
    directly) — reset it here regardless of test execution order, so these
    retry/circuit-breaker tests always see it disabled (env unset)."""
    monkeypatch.setattr(rate_limiter_module, "_singleton", None)
    monkeypatch.setattr(rate_limiter_module, "_singleton_checked", False)
    monkeypatch.delenv("USPTO_SHARED_RATE_LIMIT_DIR", raising=False)


def _patch_no_sleep(monkeypatch):
    """Replace asyncio.sleep with a no-op so retry backoff doesn't slow down
    the test suite; the real asyncio module is shared process-wide, but
    monkeypatch reverts this at teardown."""
    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(fpd_client_module.asyncio, "sleep", _fake_sleep)
    return sleep_calls


def _patch_async_client(monkeypatch, handler):
    """Route fpd_client's httpx.AsyncClient(...) calls through a MockTransport
    handler — same technique as TestOcrPathByteCapAndMagicBytes in
    tests/test_security_hardening_phase23.py."""
    _real_async_client = httpx.AsyncClient
    mock_transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        fpd_client_module.httpx, "AsyncClient",
        lambda *a, **kw: _real_async_client(transport=mock_transport),
    )


async def test_retry_on_5xx_succeeds_on_second_attempt(monkeypatch):
    sleep_calls = _patch_no_sleep(monkeypatch)
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(200, json={"results": [], "count": 0})

    _patch_async_client(monkeypatch, handler)

    client = FPDClient(api_key="test-key-1234567890")
    result = await client._make_request("search", method="POST", json={"q": "*"})

    assert call_count["n"] == 2
    assert result == {"results": [], "count": 0}
    assert len(sleep_calls) == 1  # one backoff sleep between attempt 1 and 2


async def test_4xx_is_not_retried(monkeypatch):
    _patch_no_sleep(monkeypatch)
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404, json={"error": "not found"})

    _patch_async_client(monkeypatch, handler)

    client = FPDClient(api_key="test-key-1234567890")
    result = await client._make_request("some-petition-id", method="GET")

    assert call_count["n"] == 1  # no retry on a 4xx
    assert result["status_code"] == 404


async def test_429_is_retried_with_fixed_delay_then_succeeds(monkeypatch):
    sleep_calls = _patch_no_sleep(monkeypatch)
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"results": [], "count": 0})

    _patch_async_client(monkeypatch, handler)

    client = FPDClient(api_key="test-key-1234567890")
    result = await client._make_request("search", method="POST", json={"q": "*"})

    assert call_count["n"] == 2
    assert result == {"results": [], "count": 0}
    assert len(sleep_calls) == 1
    assert sleep_calls[0] >= 5.0


async def test_circuit_open_serves_stale_cache_fallback(monkeypatch):
    client = FPDClient(api_key="test-key-1234567890")

    # Force the circuit breaker OPEN with a recent failure so
    # _should_attempt_reset() stays False (recovery_timeout=60s default).
    client.uspto_circuit_breaker.state = CircuitState.OPEN
    client.uspto_circuit_breaker.last_failure_time = time.time()

    # Pre-populate the cache under the exact key _make_request would use.
    client.cache_manager.set("GET_some-endpoint", {"cached": "value", "count": 1})

    result = await client._make_request("some-endpoint", method="GET")

    assert result["_cached"] is True
    assert result["_circuit_open"] is True
    assert result["cached"] == "value"


async def test_circuit_open_with_no_cache_returns_503(monkeypatch):
    client = FPDClient(api_key="test-key-1234567890")

    client.uspto_circuit_breaker.state = CircuitState.OPEN
    client.uspto_circuit_breaker.last_failure_time = time.time()

    result = await client._make_request("uncached-endpoint", method="GET")

    assert result["status_code"] == 503
