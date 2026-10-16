"""One end-to-end deadline per call (Wave 2 A.4 / A.5), ported from PTAB's
tests/test_ocr_deadline.py to FPD's layers.

Cloudflare cuts a proxied request at about 100 s. FPD_get_document_content_
with_ocr runs a chain (petition details with documents and the file-wrapper
fallback, the PDF download, pypdf, Mistral upload + OCR, Docling) and
FPD_Get_petition_details(include_documents=True) runs its first link; each
step used to budget itself. Now one Deadline (FPD_CONTENT_DEADLINE_SECONDS,
default 85 s) is bound when the tool starts, every USPTO attempt, the
download, every Mistral attempt and Docling take what is left of it, a retry
is taken only when its backoff leaves room for another attempt, and a spent
budget answers "Deadline exceeded".

Time is faked where it can be: the Deadline takes an injectable clock, and
asyncio.sleep is patched to advance that clock instead of waiting. USPTO and
Mistral are an httpx MockTransport. No network.
"""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

import fpd_mcp.shared.uspto_shared_rate_limiter as rate_limiter_module
from fpd_mcp.api.field_constants import FPDFields
from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.services.document_extraction import DocumentExtractionService
from fpd_mcp.util import deadline as deadline_module
from fpd_mcp.util.deadline import (
    Deadline,
    DeadlineExceeded,
    bind_deadline,
    current_deadline,
    deadline_exceeded_response,
    run_within_deadline,
)

_KEY = "test-key-not-a-real-credential"
_PETITION_ID = "e55bd36d-961f-511e-b72c-b4b1529d67ef"
_DOCUMENT_ID = "HY1J6ICXPXXIFW4"
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def _shared_rate_limiter_disabled(monkeypatch):
    monkeypatch.setattr(rate_limiter_module, "_singleton", None)
    monkeypatch.setattr(rate_limiter_module, "_singleton_checked", False)
    monkeypatch.delenv("USPTO_SHARED_RATE_LIMIT_DIR", raising=False)


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        fake.t += seconds

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    fake.slept = slept
    return fake


def _route_httpx_through(monkeypatch, handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _service():
    return FPDClient(api_key=_KEY)._extraction


class TestDeadline:
    def test_remaining_counts_down_and_never_goes_negative(self, clock):
        d = Deadline(85, clock=clock)
        clock.t += 80
        assert d.remaining() == pytest.approx(5)
        clock.t += 10
        assert d.remaining() == 0.0 and d.expired()

    @pytest.mark.parametrize("raw, expected", [
        ("", 85.0), ("60", 60.0), ("junk", 85.0), ("0", 85.0), ("-5", 85.0)])
    def test_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("FPD_CONTENT_DEADLINE_SECONDS", raw)
        assert deadline_module.content_deadline_seconds() == expected

    def test_binding_is_scoped_to_the_block(self, clock):
        d = Deadline(85, clock=clock)
        assert current_deadline() is None
        with bind_deadline(d):
            assert current_deadline() is d
        assert current_deadline() is None

    def test_the_envelope_reads_deadline_exceeded(self):
        result = deadline_exceeded_response("req-1")
        assert result["error"].startswith("Deadline exceeded")
        assert result["status_code"] == 408
        assert result["request_id"] == "req-1"
        assert deadline_module.is_deadline_exceeded(result)
        assert "$" not in result["error"]


class TestRunWithinDeadline:
    async def test_outside_a_bound_call_it_just_runs(self):
        async def step():
            return "done"

        assert await run_within_deadline(step) == "done"

    async def test_a_spent_budget_never_starts_the_step(self, clock):
        started = []

        def make():
            started.append(1)
            return asyncio.sleep(0)

        spent = Deadline(85, clock=clock)
        clock.t += 84
        with bind_deadline(spent), pytest.raises(DeadlineExceeded):
            await run_within_deadline(make)
        assert started == []

    async def test_a_hung_step_is_cut_at_the_deadline(self, monkeypatch):
        """Real (tiny) time here: the timeout has to fire on the event loop."""
        monkeypatch.setattr(deadline_module, "MIN_ATTEMPT_SECONDS", 0.01)

        with bind_deadline(Deadline(0.2)), pytest.raises(DeadlineExceeded):
            await run_within_deadline(lambda: asyncio.Event().wait())

    async def test_a_steps_own_timeout_error_is_not_relabelled(self, clock):
        async def step():
            raise TimeoutError("the shared limiter's own 30 s cap")

        with bind_deadline(Deadline(85, clock=clock)), pytest.raises(TimeoutError):
            await run_within_deadline(step)


class TestUsptoRetriesInsideTheDeadline:
    async def test_no_attempt_is_started_on_a_spent_deadline(self, clock, monkeypatch):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json={"count": 0})

        _route_httpx_through(monkeypatch, handler)
        client = FPDClient(api_key=_KEY)
        spent = Deadline(85, clock=clock)
        clock.t += 84

        with bind_deadline(spent):
            result = await client.search_petitions(query="*", limit=1)
        await client.aclose()

        assert calls == []
        assert result["error"].startswith("Deadline exceeded")
        assert result["status_code"] == 408

    async def test_a_5xx_retry_that_would_not_fit_is_not_taken(self, clock, monkeypatch):
        """Budget 4 s: the first backoff (~1.1-1.5 s) leaves room for one more
        attempt; the second (~2.1-2.5 s) would not, so the upstream status is
        the answer after two attempts instead of three."""
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503, json={"error": "down"})

        _route_httpx_through(monkeypatch, handler)
        client = FPDClient(api_key=_KEY)

        with bind_deadline(Deadline(4.0, clock=clock)):
            result = await client.get_petition_by_id(_PETITION_ID)
        await client.aclose()

        assert len(calls) == 2
        assert len(clock.slept) == 1
        assert result["status_code"] == 503

    async def test_a_spent_deadline_is_not_an_upstream_outage(self, clock, monkeypatch):
        _route_httpx_through(monkeypatch, lambda r: httpx.Response(200, json={}))
        client = FPDClient(api_key=_KEY)
        spent = Deadline(85, clock=clock)
        clock.t += 85

        with bind_deadline(spent):
            for _ in range(client.uspto_circuit_breaker.failure_threshold + 1):
                await client.search_petitions(query="*", limit=1)
        await client.aclose()

        assert client.uspto_circuit_breaker.get_state()["state"] == "closed"

    async def test_without_a_deadline_the_old_bounds_hold(self, clock, monkeypatch):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503, json={"error": "down"})

        _route_httpx_through(monkeypatch, handler)
        client = FPDClient(api_key=_KEY)

        await client.get_petition_by_id(_PETITION_ID)
        await client.aclose()

        assert len(calls) == FPDClient.RETRY_ATTEMPTS


class TestIncludeDocumentsChain:
    async def test_a_failing_details_call_is_not_followed_by_a_fallback_hop(
            self, clock, monkeypatch):
        """The details call 500s on every attempt (30 s of fake time each).
        Since the 2026-10 payload change there is no with-documents call to
        fall back from: includeDocuments is never sent (it now returns a
        corpus page), the 500 is the answer, and no wrapper fetch follows
        (that runs only for a petition record with an empty bag)."""
        urls = []

        def handler(request):
            urls.append(str(request.url))
            clock.t += 30
            return httpx.Response(500, json={"error": "upstream"})

        _route_httpx_through(monkeypatch, handler)
        client = FPDClient(api_key=_KEY)

        with bind_deadline(Deadline(85, clock=clock)):
            result = await client.get_petition_by_id(_PETITION_ID, include_documents=True)
        await client.aclose()

        assert result["status_code"] == 500
        assert "document_metadata_available" not in result
        assert len(urls) == FPDClient.RETRY_ATTEMPTS
        assert not any("includeDocuments" in u for u in urls)
        assert not any("/patent/applications/" in u for u in urls)

    async def test_a_spent_budget_at_the_wrapper_fetch_says_deadline_exceeded(
            self, clock, monkeypatch):
        def handler(request):
            if "/patent/applications/" not in request.url.path:
                clock.t += 85  # the details call (no bag of its own) spends it all
                return httpx.Response(200, json={
                    FPDFields.PETITION_DECISION_DATA_BAG: [
                        {FPDFields.PETITION_DECISION_RECORD_IDENTIFIER: _PETITION_ID,
                         FPDFields.APPLICATION_NUMBER_TEXT: "13408005"}]})
            raise AssertionError("the wrapper fetch must not be sent")

        _route_httpx_through(monkeypatch, handler)
        client = FPDClient(api_key=_KEY)

        with bind_deadline(Deadline(85, clock=clock)):
            result = await client.get_petition_by_id(_PETITION_ID, include_documents=True)
        await client.aclose()

        assert result["error"].startswith("Deadline exceeded")
        assert "document_metadata_available" not in result

    async def test_the_details_tool_binds_one_deadline_with_documents(
            self, mock_runtime, monkeypatch):
        from fpd_mcp.tools.petitions import fpd_get_petition_details

        monkeypatch.setenv("FPD_CONTENT_DEADLINE_SECONDS", "60")
        seen = {}

        async def fake_get(petition_id, include_documents=False):
            seen["deadline"] = current_deadline()
            return deadline_exceeded_response()

        mock_runtime.api_client.get_petition_by_id = fake_get

        result = await fpd_get_petition_details(petition_id=_PETITION_ID,
                                                include_documents=True)

        assert isinstance(seen["deadline"], Deadline)
        assert seen["deadline"].seconds == 60.0
        assert result["error"].startswith("Deadline exceeded")
        assert current_deadline() is None

    async def test_the_details_tool_without_documents_has_no_deadline(self, mock_runtime):
        from fpd_mcp.tools.petitions import fpd_get_petition_details

        seen = {}

        async def fake_get(petition_id, include_documents=False):
            seen["deadline"] = current_deadline()
            return {"error": "stop here", "status_code": 404}

        mock_runtime.api_client.get_petition_by_id = fake_get

        await fpd_get_petition_details(petition_id=_PETITION_ID, include_documents=False)

        assert seen["deadline"] is None

    async def test_the_details_tool_backstop_fires_on_a_step_that_never_checks(
            self, mock_runtime, monkeypatch):
        from fpd_mcp.tools.petitions import fpd_get_petition_details

        monkeypatch.setenv("FPD_CONTENT_DEADLINE_SECONDS", "0.2")

        async def never_returns(petition_id, include_documents=False):
            await asyncio.Event().wait()

        mock_runtime.api_client.get_petition_by_id = never_returns

        result = await fpd_get_petition_details(petition_id=_PETITION_ID,
                                                include_documents=True)

        assert result["status_code"] == 408
        assert result["error"].startswith("Deadline exceeded")


class TestMistralRetryInsideTheDeadline:
    async def test_a_429_is_retried_while_there_is_room(self, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429) if len(calls) == 1 else httpx.Response(200, json={})

        async with _client(handler) as client:
            with bind_deadline(Deadline(85, clock=clock)):
                response = await _service()._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 200
        assert len(calls) == 2

    async def test_a_5xx_retry_that_would_not_fit_is_not_taken(self, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)

        async with _client(handler) as client:
            with bind_deadline(Deadline(4.0, clock=clock)):
                response = await _service()._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 503
        assert len(calls) == 2
        assert len(clock.slept) == 1

    async def test_without_room_a_transport_failure_becomes_deadline_exceeded(self, clock):
        def handler(request):
            clock.t += 3.0  # the failed attempt itself used most of the budget
            raise httpx.ConnectError("reset")

        async with _client(handler) as client:
            with bind_deadline(Deadline(4.0, clock=clock)), pytest.raises(DeadlineExceeded):
                await _service()._post_with_retry(client, "https://x/files")

    async def test_no_attempt_is_started_on_a_spent_deadline(self, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json={})

        spent = Deadline(85, clock=clock)
        clock.t += 84.5
        async with _client(handler) as client:
            with bind_deadline(spent), pytest.raises(DeadlineExceeded):
                await _service()._post_with_retry(client, "https://x/ocr")

        assert calls == []

    async def test_a_hung_attempt_is_cut_at_the_deadline(self, monkeypatch):
        """Real (tiny) time here: the timeout has to fire on the event loop."""
        monkeypatch.setattr(deadline_module, "MIN_ATTEMPT_SECONDS", 0.01)

        class Hang(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=Hang()) as client:
            with bind_deadline(Deadline(0.2)), pytest.raises(DeadlineExceeded):
                await _service()._post_with_retry(client, "https://x/ocr")

    async def test_without_a_deadline_three_bounded_attempts(self, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)

        async with _client(handler) as client:
            response = await _service()._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 503
        assert len(calls) == DocumentExtractionService._MISTRAL_RETRY_ATTEMPTS

    async def test_a_transport_failure_is_retried_then_succeeds(self, clock):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                raise httpx.ConnectError("reset")
            return httpx.Response(200, json={"id": "file-1"})

        async with _client(handler) as client:
            response = await _service()._post_with_retry(client, "https://x/files")

        assert response.status_code == 200
        assert len(calls) == 2

    async def test_both_mistral_requests_retry(self, clock, monkeypatch):
        """The upload and the OCR request each take the retrying path."""
        seen = []

        def handler(request):
            seen.append(request.url.path)
            if seen.count(request.url.path) == 1:
                return httpx.Response(502)
            if request.url.path.endswith("/files"):
                return httpx.Response(200, json={"id": "file-1"})
            return httpx.Response(200, json={
                "pages": [{"index": 0, "markdown": "text"}],
                "usage_info": {"pages_processed": 1}})

        _route_httpx_through(monkeypatch, handler)

        text, _ = await _service()._do_mistral_ocr_call(
            b"%PDF-1.4", 1, "k" * 40, "https://api.mistral.ai/v1", "mistral-ocr-latest")

        assert "text" in text
        assert seen == ["/v1/files", "/v1/files", "/v1/ocr", "/v1/ocr"]

    async def test_a_spent_deadline_does_not_count_toward_the_ocr_breaker(self):
        service = _service()

        async def spent(*args):
            raise DeadlineExceeded("no time left")

        service._do_mistral_ocr_call = spent
        for _ in range(service.mistral_circuit_breaker.failure_threshold + 1):
            with pytest.raises(DeadlineExceeded):
                await service._ocr_through_breaker(b"%PDF", 1, "k", "u", "m")

        assert service.mistral_circuit_breaker.get_state()["state"] == "closed"


class TestEndToEnd:
    async def test_a_spent_budget_sends_no_uspto_request(self, clock, monkeypatch):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json={})

        _route_httpx_through(monkeypatch, handler)
        client = FPDClient(api_key=_KEY)
        spent = Deadline(85, clock=clock)
        clock.t += 85

        with bind_deadline(spent):
            result = await client.extract_document_content_hybrid(_PETITION_ID, _DOCUMENT_ID)
        await client.aclose()

        assert calls == []
        assert result["error"].startswith("Deadline exceeded")
        assert result["status_code"] == 408

    async def test_a_download_cut_by_the_deadline_is_reported_as_such(self, monkeypatch):
        client = FPDClient(api_key=_KEY)
        client.get_petition_by_id = AsyncMock(return_value={
            FPDFields.PETITION_DECISION_DATA_BAG: [{FPDFields.DOCUMENT_BAG: [{
                FPDFields.DOCUMENT_IDENTIFIER: _DOCUMENT_ID,
                FPDFields.PAGE_COUNT: 2,
                FPDFields.DOWNLOAD_OPTION_BAG: [{
                    FPDFields.MIME_TYPE_IDENTIFIER: "PDF",
                    FPDFields.DOWNLOAD_URL: "https://api.uspto.gov/x.pdf"}],
            }]}]})
        client._download_pdf_for_extraction = AsyncMock(
            side_effect=DeadlineExceeded("step ran past the deadline"))

        result = await client.extract_document_content_hybrid(_PETITION_ID, _DOCUMENT_ID)

        assert result["error"].startswith("Deadline exceeded")

    async def test_docling_is_skipped_when_the_budget_is_nearly_spent(self, clock):
        called = []

        class _Docling:
            max_pages = 25

            def is_available(self):
                return True

            def within_page_limit(self, n):
                return True

            async def extract(self, *a, **k):
                called.append(1)
                return "text"

        async def progress(*a):
            return None

        service = DocumentExtractionService(
            client=None, download_timeout=60.0, connection_limits=httpx.Limits(),
            docling_client_factory=_Docling)
        nearly_spent = Deadline(85, clock=clock)
        clock.t += 81

        with bind_deadline(nearly_spent), pytest.raises(DeadlineExceeded):
            await service._extract_with_docling_fallback(
                {}, b"%PDF", 3, _DOCUMENT_ID, "req", progress,
                DeadlineExceeded("mistral ran out"))

        assert called == []

    async def test_docling_runs_on_the_remainder(self, clock):
        class _Docling:
            max_pages = 25

            def is_available(self):
                return True

            def within_page_limit(self, n):
                return True

            async def extract(self, *a, **k):
                return "docling text"

        async def progress(*a):
            return None

        service = DocumentExtractionService(
            client=None, download_timeout=60.0, connection_limits=httpx.Limits(),
            docling_client_factory=_Docling)
        result = {}
        with bind_deadline(Deadline(85, clock=clock)):
            await service._extract_with_docling_fallback(
                result, b"%PDF", 3, _DOCUMENT_ID, "req", progress, ValueError("no key"))

        assert result["extracted_content"] == "docling text"

    async def test_the_content_tool_binds_one_deadline_for_the_whole_call(
            self, mock_runtime, monkeypatch):
        from fpd_mcp.tools.documents import fpd_get_document_content

        monkeypatch.setenv("FPD_CONTENT_DEADLINE_SECONDS", "60")
        seen = {}

        async def fake_extract(**kwargs):
            seen["deadline"] = current_deadline()
            return {"success": True, "extracted_content": "text " * 50,
                    "extraction_method": "pypdf"}

        mock_runtime.api_client.extract_document_content_hybrid = fake_extract

        result = await fpd_get_document_content(
            petition_id=_PETITION_ID, document_identifier=_DOCUMENT_ID)

        assert result["success"] is True
        assert isinstance(seen["deadline"], Deadline)
        assert seen["deadline"].seconds == 60.0
        assert 0 < seen["deadline"].remaining() <= 60.0
        assert current_deadline() is None
