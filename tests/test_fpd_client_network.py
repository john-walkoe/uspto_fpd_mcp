"""Offline mocked tests for FPDClient's network layer (api/fpd_client.py):
retry-on-5xx succeeding on the 2nd attempt, no-retry on 4xx, 429 being
retryable with a fixed >=5s delay, and the circuit-open -> stale-cache
fallback path.

httpx.AsyncClient is patched to route through httpx.MockTransport (the same
pattern already used in tests/test_security_hardening_phase23.py) so no real
network calls happen; asyncio.sleep is patched to a no-op so retry-delay
tests run instantly.
"""

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


async def _drive_breaker_open(monkeypatch, client, endpoint="down-endpoint"):
    """Open the USPTO breaker the way production would: by failing.

    These tests used to set `state = CircuitState.OPEN` by hand, so they
    passed while the transition that produces that state did not exist —
    `_execute_request_with_retries` returned an error ENVELOPE for every
    failure mode and `CircuitBreaker.call` only counts raises
    (error-handling-resilience F-E1).
    """
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "service unavailable"})

    _patch_async_client(monkeypatch, handler)

    for _ in range(client.uspto_circuit_breaker.failure_threshold):
        result = await client._make_request(endpoint, method="GET")
        # Each logical call still hands the caller the upstream envelope.
        assert result["status_code"] == 503


async def test_repeated_upstream_failures_open_the_circuit(monkeypatch):
    _patch_no_sleep(monkeypatch)
    client = FPDClient(api_key="test-key-1234567890")

    assert client.uspto_circuit_breaker.state == CircuitState.CLOSED
    await _drive_breaker_open(monkeypatch, client)
    assert client.uspto_circuit_breaker.state == CircuitState.OPEN


async def test_circuit_open_serves_stale_cache_fallback(monkeypatch):
    _patch_no_sleep(monkeypatch)
    client = FPDClient(api_key="test-key-1234567890")

    # Pre-populate the cache under the exact key _make_request would use.
    client.cache_manager.set("GET_some-endpoint", {"cached": "value", "count": 1})

    await _drive_breaker_open(monkeypatch, client)
    assert client.uspto_circuit_breaker.state == CircuitState.OPEN

    result = await client._make_request("some-endpoint", method="GET")

    assert result["_cached"] is True
    assert result["_circuit_open"] is True
    assert result["cached"] == "value"


async def test_circuit_open_with_no_cache_returns_503(monkeypatch):
    _patch_no_sleep(monkeypatch)
    client = FPDClient(api_key="test-key-1234567890")

    await _drive_breaker_open(monkeypatch, client)

    result = await client._make_request("uncached-endpoint", method="GET")

    assert result["status_code"] == 503


async def test_a_4xx_does_not_push_the_breaker_toward_open(monkeypatch):
    """A 404 is not an upstream health signal and must not be counted."""
    _patch_no_sleep(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    _patch_async_client(monkeypatch, handler)
    client = FPDClient(api_key="test-key-1234567890")

    for _ in range(client.uspto_circuit_breaker.failure_threshold + 2):
        result = await client._make_request("missing", method="GET")
        assert result["status_code"] == 404

    assert client.uspto_circuit_breaker.state == CircuitState.CLOSED
    assert client.uspto_circuit_breaker.failure_count == 0


# ---------------------------------------------------------------------------
# Evals-harness fixes (2026-08-30): the two client-layer defects the FPD eval
# suite pinned as known_fail. Both are exercised against a REAL FPDClient with
# only its two collaborator methods replaced, so the request shape the wire
# would carry is the thing under test.
# ---------------------------------------------------------------------------


def _offline_client(monkeypatch):
    """A real FPDClient that will never resolve a stored key or reach USPTO."""
    monkeypatch.setenv("USPTO_API_KEY", "a" * 30)
    return FPDClient(api_key="a" * 30)


async def test_art_unit_date_range_is_sent_as_range_filters(monkeypatch):
    """date_range 400'd upstream on the tool's OWN documented example.

    Probed live 2026-08-30: the `{field, valueFrom, valueTo}` object is right,
    but it must go in the body under `rangeFilters`. Sent under `filters` — as
    it was until this fix — USPTO answers HTTP 400 Bad Request with no
    detailedMessage, so every date_range call failed no matter how well-formed
    the caller's string was.
    """
    client = _offline_client(monkeypatch)
    seen = {}

    async def _fake_search(**kwargs):
        seen.update(kwargs)
        return {"petitionDecisionDataBag": [], "count": 0}

    client.search_petitions = _fake_search

    await client.search_by_art_unit(
        art_unit="3643", date_range="2015-01-01:2016-12-31", limit=3
    )

    assert seen["range_filters"] == [
        {
            "field": "petitionMailDate",
            "valueFrom": "2015-01-01",
            "valueTo": "2016-12-31",
        }
    ]
    assert seen.get("filters") is None


async def test_search_petitions_puts_range_filters_in_the_body(monkeypatch):
    client = _offline_client(monkeypatch)
    seen = {}

    async def _fake_request(endpoint, method="GET", **kwargs):
        seen.update(kwargs)
        return {"petitionDecisionDataBag": [], "count": 0}

    client._make_request = _fake_request
    range_filters = [
        {"field": "petitionMailDate", "valueFrom": "2015-01-01", "valueTo": "2016-12-31"}
    ]

    await client.search_petitions(query="groupArtUnitNumber:3643", range_filters=range_filters)

    assert seen["json"]["rangeFilters"] == range_filters
    assert "filters" not in seen["json"]


async def test_by_application_include_documents_attaches_a_document_bag(monkeypatch):
    """include_documents was documented, passed through, and dropped.

    The FPD search endpoint serves no documentBag of its own, so the bag now
    comes from the application file wrapper — the same source
    FPD_Get_petition_details serves today — and the substitution is labelled.
    """
    client = _offline_client(monkeypatch)
    wrapper_calls = []

    async def _fake_search(**kwargs):
        return {
            "petitionDecisionDataBag": [
                {"petitionDecisionRecordIdentifier": "p1"},
                {"petitionDecisionRecordIdentifier": "p2"},
            ],
            "count": 2,
        }

    async def _fake_wrapper(application_number):
        wrapper_calls.append(application_number)
        return {
            "documentBag": [
                {"documentIdentifier": "DOC-1", "documentCode": "CTNF"},
                {"documentIdentifier": "DOC-2", "documentCode": "PET"},
            ]
        }

    client.search_petitions = _fake_search
    client.get_application_documents = _fake_wrapper

    result = await client.search_by_application(
        application_number="15344896", include_documents=True
    )

    # One wrapper fetch covers the whole page: every petition here is on the
    # same application by construction.
    assert wrapper_calls == ["15344896"]
    for record in result["petitionDecisionDataBag"]:
        assert [d["documentIdentifier"] for d in record["documentBag"]] == [
            "DOC-1",
            "DOC-2",
        ]
    assert result["document_metadata_available"] is True
    assert result["document_metadata_source"] == "application_file_wrapper"
    assert "APPLICATION FILE WRAPPER" in result["document_metadata_note"]


async def test_by_application_marks_a_failed_document_fetch(monkeypatch):
    """An absent bag must never read as 'this petition has no documents'."""
    client = _offline_client(monkeypatch)

    async def _fake_search(**kwargs):
        return {
            "petitionDecisionDataBag": [{"petitionDecisionRecordIdentifier": "p1"}],
            "count": 1,
        }

    async def _fake_wrapper(application_number):
        return {"error": "boom", "status_code": 500, "success": False}

    client.search_petitions = _fake_search
    client.get_application_documents = _fake_wrapper

    result = await client.search_by_application(
        application_number="15344896", include_documents=True
    )

    assert result["document_metadata_available"] is False
    assert "documentBag" not in result["petitionDecisionDataBag"][0]


async def test_by_application_without_documents_makes_no_wrapper_call(monkeypatch):
    client = _offline_client(monkeypatch)
    wrapper_calls = []

    async def _fake_search(**kwargs):
        return {
            "petitionDecisionDataBag": [{"petitionDecisionRecordIdentifier": "p1"}],
            "count": 1,
        }

    async def _fake_wrapper(application_number):
        wrapper_calls.append(application_number)
        return {"documentBag": []}

    client.search_petitions = _fake_search
    client.get_application_documents = _fake_wrapper

    await client.search_by_application(application_number="15344896")

    assert wrapper_calls == []


# ------------------------------------------------------------------ F-R3/R7/R9


async def test_a_429_retry_waits_at_least_as_long_as_retry_after(monkeypatch):
    """F-R3: the header was parsed into a RateLimitError nobody read, and the
    retry loop used the fixed 5s cool-down regardless. A throttle asking for
    60s produced three rejected calls where one correct retry would have won.
    """
    sleep_calls = _patch_no_sleep(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "45"}, json={})

    _patch_async_client(monkeypatch, handler)
    client = FPDClient(api_key="test-key-1234567890")

    await client._make_request("throttled", method="GET")

    assert sleep_calls, "no retry was attempted"
    assert all(delay >= 45.0 for delay in sleep_calls), sleep_calls


async def test_a_429_without_retry_after_keeps_the_fixed_cool_down(monkeypatch):
    sleep_calls = _patch_no_sleep(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    _patch_async_client(monkeypatch, handler)
    client = FPDClient(api_key="test-key-1234567890")

    await client._make_request("throttled", method="GET")

    assert sleep_calls
    assert all(delay == client.RETRY_429_DELAY for delay in sleep_calls), sleep_calls


async def test_an_http_date_retry_after_falls_back_rather_than_guessing(monkeypatch):
    sleep_calls = _patch_no_sleep(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, json={}
        )

    _patch_async_client(monkeypatch, handler)
    client = FPDClient(api_key="test-key-1234567890")

    await client._make_request("throttled", method="GET")

    assert all(delay == client.RETRY_429_DELAY for delay in sleep_calls), sleep_calls


async def test_a_non_retryable_429_envelope_reports_retry_after(monkeypatch):
    """The caller is told how long the upstream asked for."""
    client = FPDClient(api_key="test-key-1234567890")
    response = httpx.Response(
        429,
        headers={"Retry-After": "45"},
        request=httpx.Request("GET", "https://api.uspto.gov/x"),
    )
    error = httpx.HTTPStatusError("429", request=response.request, response=response)

    envelope = client._map_http_status_error_response(error, "req-1")

    assert envelope["status_code"] == 429
    assert envelope["retry_after"] == 45


async def test_the_client_reuses_one_pooled_http_client(monkeypatch):
    """F-R7: a fresh AsyncClient was built and closed inside every send, so
    the configured pool and keepalive settings did nothing."""
    _patch_no_sleep(monkeypatch)
    built = {"n": 0}
    real_async_client = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"count": 0})

    mock_transport = httpx.MockTransport(handler)

    def _factory(*args, **kwargs):
        built["n"] += 1
        return real_async_client(transport=mock_transport)

    monkeypatch.setattr(fpd_client_module.httpx, "AsyncClient", _factory)
    client = FPDClient(api_key="test-key-1234567890")

    for _ in range(4):
        await client._make_request("some-endpoint", method="GET")

    assert built["n"] == 1
    await client.aclose()


def test_the_bulkhead_uses_its_declared_constant():
    """F-R9: MAX_CONCURRENT_REQUESTS was declared and never read; the real
    value was a literal three dozen lines away."""
    client = FPDClient(api_key="test-key-1234567890")

    assert client.uspto_semaphore._value == FPDClient.MAX_CONCURRENT_REQUESTS


async def test_half_open_admits_only_one_probe(monkeypatch):
    """F-R5: the lock was released before the wrapped call, so on transition
    to HALF_OPEN every waiting caller proceeded at once — the thundering herd
    the state exists to prevent."""
    import asyncio

    from fpd_mcp.shared.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerOpenError,
        CircuitState,
    )

    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0, name="probe")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = None

    in_flight = asyncio.Event()
    release = asyncio.Event()

    async def slow_probe():
        in_flight.set()
        await release.wait()
        return "ok"

    first = asyncio.create_task(breaker.call(slow_probe))
    await in_flight.wait()

    async def quick():  # pragma: no cover - must not run
        raise AssertionError("a second probe was admitted")

    with pytest.raises(CircuitBreakerOpenError) as excinfo:
        await breaker.call(quick)
    assert "HALF_OPEN" in str(excinfo.value)

    release.set()
    assert await first == "ok"
