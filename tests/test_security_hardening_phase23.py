"""Tests for the Phase 2 (Medium) + Phase 3 (Low) audit-remediation pass.

Covers: M2 (Lucene allowlist), M3 (Mistral OCR daily spend ceiling), M4
(petition_id/document_identifier shape validation), M6 (pypdf migration +
free-tier page cap), M7/L24 (OCR-path byte cap + PDF magic-byte check),
L15 (Content-Length int-parse guard), L16 (security headers), L19/L20
(register-download schema), L23 (filename sanitizer for app/patent number).

M1/L3/L5 (auth provider changes) are covered in tests/test_auth_provider.py.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from io import BytesIO

import pytest

from fpd_mcp.api.fpd_client import FPDClient
from fpd_mcp.api import fpd_client as fpd_client_module


def _make_blank_pdf(num_pages: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


# --------------------------------------------------------------------- M2


class TestValidateStringParamAllowlist:
    """main.py's validate_string_param() switched from a denylist to an
    allowlist so Lucene metacharacters can't reshape the upstream query."""

    def _validate(self, name: str, value: str):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import validate_string_param

        return validate_string_param(name, value)

    def test_legit_company_name_with_ampersand_unaffected(self):
        assert self._validate("applicant_name", "Johnson & Johnson") == "Johnson & Johnson"

    def test_legit_name_with_apostrophe_and_hyphen_unaffected(self):
        assert self._validate("applicant_name", "O'Brien-Smith") == "O'Brien-Smith"

    def test_legit_name_with_comma_and_period_unaffected(self):
        assert self._validate("applicant_name", "Acme, Inc.") == "Acme, Inc."

    def test_lucene_injection_attempt_rejected(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.shared.error_utils import ValidationError

        with pytest.raises(ValidationError):
            self._validate("applicant_name", 'x" OR petitionerName:*')

    @pytest.mark.parametrize("bad_char", [":", "(", ")", "[", "]", "*", "?", "~", "^", '"'])
    def test_individual_lucene_metacharacters_rejected(self, bad_char):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.shared.error_utils import ValidationError

        with pytest.raises(ValidationError):
            self._validate("deciding_office", f"foo{bad_char}bar")


# --------------------------------------------------------------------- M4


class TestIdentifierValidation:
    """petition_id (UUID-shaped) and document_identifier (alnum code) are
    now shape-checked, not just non-empty."""

    def _funcs(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import validate_petition_id, validate_document_identifier

        return validate_petition_id, validate_document_identifier

    def test_real_uuid_anchor_accepted(self):
        validate_petition_id, _ = self._funcs()
        assert (
            validate_petition_id("e55bd36d-961f-511e-b72c-b4b1529d67ef")
            == "e55bd36d-961f-511e-b72c-b4b1529d67ef"
        )

    def test_path_traversal_petition_id_rejected(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.shared.error_utils import ValidationError

        validate_petition_id, _ = self._funcs()
        with pytest.raises(ValidationError):
            validate_petition_id("../search")

    def test_real_document_identifier_anchor_accepted(self):
        _, validate_document_identifier = self._funcs()
        assert validate_document_identifier("HY1J6ICXPXXIFW4") == "HY1J6ICXPXXIFW4"

    def test_document_identifier_with_slash_rejected(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.shared.error_utils import ValidationError

        _, validate_document_identifier = self._funcs()
        with pytest.raises(ValidationError):
            validate_document_identifier("AB/../CD")

    def test_document_identifier_too_short_rejected(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.shared.error_utils import ValidationError

        _, validate_document_identifier = self._funcs()
        with pytest.raises(ValidationError):
            validate_document_identifier("AB12")

    @pytest.mark.asyncio
    async def test_get_petition_details_tool_rejects_bad_petition_id(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import fpd_get_petition_details

        result = await fpd_get_petition_details(petition_id="../search")
        assert result["status_code"] == 400

    @pytest.mark.asyncio
    async def test_get_document_download_tool_rejects_bad_document_identifier(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import fpd_get_document_download

        result = await fpd_get_document_download(
            petition_id="e55bd36d-961f-511e-b72c-b4b1529d67ef",
            document_identifier="x",
        )
        assert result["status_code"] == 400


# --------------------------------------------------------------------- M4 (art_unit / application_number)


class TestByArtUnitAndByApplicationValidation:
    @pytest.mark.asyncio
    async def test_by_art_unit_rejects_lucene_injection(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import fpd_search_petitions_by_art_unit

        result = await fpd_search_petitions_by_art_unit(art_unit="2128) OR foo:*")
        assert result["status_code"] == 400

    @pytest.mark.asyncio
    async def test_by_application_rejects_non_digit_application_number(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import fpd_search_petitions_by_application

        result = await fpd_search_petitions_by_application(application_number="17ABC175")
        assert result["status_code"] == 400


# --------------------------------------------------------------------- M3


class TestMistralDailySpendCeiling:
    def setup_method(self):
        # Isolate from any prior test's accumulated state in this process.
        fpd_client_module._mistral_daily_cost_state["date"] = None
        fpd_client_module._mistral_daily_cost_state["total"] = 0.0

    def test_unset_budget_is_unlimited(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_OCR_DAILY_BUDGET_USD", raising=False)
        allowed, _current, budget = fpd_client_module._mistral_daily_spend_check(1000.0)
        assert allowed is True
        assert budget == 0.0

    def test_zero_budget_is_unlimited(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_OCR_DAILY_BUDGET_USD", "0")
        allowed, _current, _budget = fpd_client_module._mistral_daily_spend_check(1000.0)
        assert allowed is True

    def test_small_budget_blocks_once_exceeded(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_OCR_DAILY_BUDGET_USD", "0.001")
        fpd_client_module._mistral_daily_spend_add(0.0009)
        allowed, current, budget = fpd_client_module._mistral_daily_spend_check(0.001)
        assert allowed is False
        assert current == pytest.approx(0.0009)
        assert budget == pytest.approx(0.001)

    def test_spend_resets_on_utc_day_change(self):
        fpd_client_module._mistral_daily_cost_state["date"] = dt.date(2000, 1, 1)
        fpd_client_module._mistral_daily_cost_state["total"] = 999.0
        allowed, current, _budget = fpd_client_module._mistral_daily_spend_check(0.001)
        assert current == 0.0
        assert allowed is True

    @pytest.mark.asyncio
    async def test_extract_with_mistral_ocr_blocks_before_any_network_call(self, monkeypatch):
        """A tiny budget must reject the call with a clear error naming the
        env var, before any upload/OCR HTTP call is attempted."""
        monkeypatch.setenv("MISTRAL_OCR_DAILY_BUDGET_USD", "0.0000001")
        monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key")

        client = FPDClient(api_key="uspto-test-key")
        with pytest.raises(ValueError, match="MISTRAL_OCR_DAILY_BUDGET_USD"):
            await client.extract_with_mistral_ocr(b"%PDF-1.4 fake content", page_count=1)


# --------------------------------------------------------------------- M6


class TestPypdfMigrationAndPageCap:
    @pytest.mark.asyncio
    async def test_extract_with_pypdf2_uses_pypdf_and_returns_tuple(self):
        client = FPDClient(api_key="k")
        pdf_bytes = _make_blank_pdf(3)
        text, truncated = await client.extract_with_pypdf2(pdf_bytes, max_pages=10)
        assert isinstance(text, str)
        assert truncated is False

    @pytest.mark.asyncio
    async def test_extract_with_pypdf2_truncates_over_cap(self):
        client = FPDClient(api_key="k")
        pdf_bytes = _make_blank_pdf(5)
        _text, truncated = await client.extract_with_pypdf2(pdf_bytes, max_pages=2)
        assert truncated is True

    @pytest.mark.asyncio
    async def test_extract_with_pypdf2_default_cap_is_200(self):
        client = FPDClient(api_key="k")
        pdf_bytes = _make_blank_pdf(3)
        _text, truncated = await client.extract_with_pypdf2(pdf_bytes)
        assert truncated is False


# --------------------------------------------------------------------- M7 / L24


class TestOcrPathByteCapAndMagicBytes:
    """extract_document_content_hybrid's PDF fetch now streams with a byte
    cap and verifies the %PDF- magic number before trusting the response."""

    def _petition_payload(self, download_url: str):
        from fpd_mcp.api.field_constants import FPDFields

        return {
            FPDFields.PETITION_DECISION_DATA_BAG: [
                {
                    FPDFields.DOCUMENT_BAG: [
                        {
                            FPDFields.DOCUMENT_IDENTIFIER: "DOC1234567890AB",
                            FPDFields.DOCUMENT_CODE: "PET",
                            FPDFields.PAGE_COUNT: 1,
                            FPDFields.DOWNLOAD_OPTION_BAG: [
                                {
                                    FPDFields.MIME_TYPE_IDENTIFIER: "PDF",
                                    FPDFields.DOWNLOAD_URL: download_url,
                                }
                            ],
                        }
                    ]
                }
            ]
        }

    def _patch_streaming_client(self, monkeypatch, content: bytes):
        import httpx as httpx_mod

        # Capture the REAL AsyncClient before patching — fpd_client_module.httpx
        # IS the same module object as httpx_mod, so patching its AsyncClient
        # attribute in place would otherwise make _FakeAsyncClient.__init__
        # recurse into itself.
        _real_async_client = httpx_mod.AsyncClient

        async def handler(request):
            return httpx_mod.Response(200, content=content)

        mock_transport = httpx_mod.MockTransport(handler)

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self._inner = _real_async_client(transport=mock_transport)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                await self._inner.aclose()

            def stream(self, method, url, **kwargs):
                return self._inner.stream(method, url, **kwargs)

        monkeypatch.setattr(fpd_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    @pytest.mark.asyncio
    async def test_non_pdf_response_rejected(self, monkeypatch):
        client = FPDClient(api_key="k")
        download_url = "https://api.uspto.gov/fake.pdf"

        async def fake_get_petition_by_id(petition_id, include_documents=False):
            return self._petition_payload(download_url)

        monkeypatch.setattr(client, "get_petition_by_id", fake_get_petition_by_id)
        self._patch_streaming_client(monkeypatch, b"<html>not a pdf</html>")

        result = await client.extract_document_content_hybrid(
            petition_id="e55bd36d-961f-511e-b72c-b4b1529d67ef",
            document_identifier="DOC1234567890AB",
        )
        # format_error_response genericizes messages in production mode, so
        # assert on the status code (the ValueError itself is asserted more
        # precisely in TestMistralDailySpendCeiling-style direct-call tests).
        assert result.get("status_code") == 400

    @pytest.mark.asyncio
    async def test_oversized_pdf_rejected(self, monkeypatch):
        client = FPDClient(api_key="k")
        download_url = "https://api.uspto.gov/fake.pdf"

        async def fake_get_petition_by_id(petition_id, include_documents=False):
            return self._petition_payload(download_url)

        monkeypatch.setattr(client, "get_petition_by_id", fake_get_petition_by_id)
        monkeypatch.setattr(fpd_client_module, "_MAX_PDF_BYTES", 10)
        self._patch_streaming_client(monkeypatch, b"%PDF-1.4 " + b"x" * 100)

        result = await client.extract_document_content_hybrid(
            petition_id="e55bd36d-961f-511e-b72c-b4b1529d67ef",
            document_identifier="DOC1234567890AB",
        )
        assert result.get("status_code") == 400


# --------------------------------------------------------------------- L15


class TestContentLengthIntGuard:
    @pytest.mark.asyncio
    async def test_non_numeric_content_length_returns_clean_400(self):
        from httpx import AsyncClient, ASGITransport
        from fpd_mcp.proxy.server import create_proxy_app

        app = create_proxy_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/", headers={"content-length": "not-a-number"})
            assert resp.status_code == 400


# --------------------------------------------------------------------- L16


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_main_security_headers_include_referrer_and_permissions_policy(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from httpx import AsyncClient, ASGITransport
        from fastmcp import FastMCP
        from fpd_mcp.main import SecurityHeadersMiddleware

        inner = FastMCP("headers-test")

        @inner.custom_route("/health", methods=["GET"])
        async def health(request):
            from starlette.responses import PlainTextResponse

            return PlainTextResponse("OK")

        app = SecurityHeadersMiddleware(inner.http_app())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
            assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
            assert "camera=()" in resp.headers.get("permissions-policy", "")


# --------------------------------------------------------------------- L19/L20


class TestRegisterDownloadSchema:
    @pytest.mark.asyncio
    async def test_register_download_drops_unexpected_fields(self):
        from httpx import AsyncClient, ASGITransport
        from fpd_mcp.proxy.server import create_proxy_app, _get_proxy_token

        app = create_proxy_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/register-download",
                json={
                    "download_url": "http://localhost:8081/download/persistent/abc",
                    "petition_id": "p-schema",
                    "document_identifier": "d-schema",
                    "unexpected_field": "should be dropped",
                    "enhanced_filename": "FPD-TEST.pdf",
                },
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            assert resp.status_code == 200
            download_id = resp.json()["download_id"]

            listing = await client.get(
                "/api/recent-downloads",
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            entry = next(
                d for d in listing.json()["downloads"] if d["download_id"] == download_id
            )
            assert "unexpected_field" not in entry
            assert entry["enhanced_filename"] == "FPD-TEST.pdf"

    @pytest.mark.asyncio
    async def test_register_download_missing_required_field_rejected(self):
        from httpx import AsyncClient, ASGITransport
        from fpd_mcp.proxy.server import create_proxy_app, _get_proxy_token

        app = create_proxy_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/register-download",
                json={"download_url": "http://localhost:8081/download/persistent/abc"},
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_register_download_overlong_field_rejected(self):
        from httpx import AsyncClient, ASGITransport
        from fpd_mcp.proxy.server import create_proxy_app, _get_proxy_token

        app = create_proxy_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/register-download",
                json={
                    "download_url": "http://localhost:8081/download/persistent/abc",
                    "petition_id": "p-schema",
                    "document_identifier": "d-schema",
                    "enhanced_filename": "x" * 500,  # over the 255-char cap
                },
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            assert resp.status_code == 400


# --------------------------------------------------------------------- L23


class TestFilenameSanitizer:
    def test_app_and_patent_number_routed_through_sanitizer(self):
        from fpd_mcp.proxy.server import generate_enhanced_filename

        filename = generate_enhanced_filename(
            petition_mail_date="2024-01-01",
            app_number="17,896/175",
            patent_number="11,788,453",
            document_description="Petition",
            document_code="PET",
        )
        # Commas and slashes are stripped by sanitize_description; only
        # allowlisted [A-Z0-9_-] characters may survive into the filename.
        assert "," not in filename
        assert "/" not in filename
        assert "APP-17896175" in filename
        assert "PAT-11788453" in filename


# --------------------------------------------------------------------- Phase 4, item 2 (exception-flow bug)


class TestValidationErrorReturns400NotValueError500:
    """ValidationError extends FPDException, NOT ValueError. Tools that used
    to wrap their bodies in a local `except ValueError` (which never matches
    ValidationError) let it fall through to a local `except Exception` and
    return a 500. After deleting those duplicated inner try/except blocks,
    async_tool_error_handler's own `except ValidationError` (checked before
    its `except ValueError`) is the only handler and correctly returns 400.
    """

    @pytest.mark.asyncio
    async def test_balanced_search_lucene_metacharacter_returns_400_not_500(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import fpd_search_petitions_balanced

        # _build_convenience_query raises ValidationError (M2 allowlist) for
        # this applicant_name; it must surface as 400, not a generic 500.
        result = await fpd_search_petitions_balanced(applicant_name="foo(bar")
        assert result["status_code"] == 400

    @pytest.mark.asyncio
    async def test_balanced_search_no_criteria_returns_400_not_500(self):
        import os

        os.environ.setdefault("USPTO_API_KEY", "x" * 30)
        from fpd_mcp.main import fpd_search_petitions_balanced

        # _build_convenience_query raises ValidationError when no query
        # parameter/criteria are provided at all.
        result = await fpd_search_petitions_balanced()
        assert result["status_code"] == 400


# --------------------------------------------------------------------- Phase 4, item 3 (circuit breaker + semaphore wiring)


class TestMistralCircuitBreakerAndSemaphoreWiring:
    """mistral_circuit_breaker and mistral_semaphore were constructed in
    FPDClient.__init__ but never used anywhere — dead resilience code.
    extract_with_mistral_ocr's upload+OCR HTTP call now runs through both.
    """

    def _patch_failing_mistral_client(self, monkeypatch):
        import httpx as httpx_mod

        _real_async_client = httpx_mod.AsyncClient

        async def handler(request):
            return httpx_mod.Response(500, content=b"upstream error")

        mock_transport = httpx_mod.MockTransport(handler)

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self._inner = _real_async_client(transport=mock_transport)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                await self._inner.aclose()

            async def post(self, url, **kwargs):
                return await self._inner.post(url, **kwargs)

        monkeypatch.setattr(fpd_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    @pytest.mark.asyncio
    async def test_breaker_opens_after_threshold_failures(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_OCR_DAILY_BUDGET_USD", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key")
        self._patch_failing_mistral_client(monkeypatch)

        from fpd_mcp.shared.circuit_breaker import CircuitState

        client = FPDClient(api_key="uspto-test-key")
        assert client.mistral_circuit_breaker.state == CircuitState.CLOSED

        # Every real (network) failure surfaces as ValueError, per
        # extract_with_mistral_ocr's httpx.HTTPStatusError -> ValueError
        # translation.
        for _ in range(client.mistral_circuit_breaker.failure_threshold):
            with pytest.raises(ValueError):
                await client.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=1)

        assert client.mistral_circuit_breaker.state == CircuitState.OPEN

        # Once OPEN, the breaker fails fast without attempting another HTTP
        # call — a plain "Circuit breaker ... OPEN" Exception, not the
        # ValueError the real network failures raised above.
        with pytest.raises(Exception, match="Circuit breaker") as exc_info:
            await client.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=1)
        assert not isinstance(exc_info.value, ValueError)

    @pytest.mark.asyncio
    async def test_semaphore_bounds_concurrent_mistral_calls(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_OCR_DAILY_BUDGET_USD", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key")

        import httpx as httpx_mod

        _real_async_client = httpx_mod.AsyncClient

        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def handler(request):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1
            if request.url.path.endswith("/files"):
                return httpx_mod.Response(200, json={"id": "file123"})
            return httpx_mod.Response(
                200, json={"usage_info": {"pages_processed": 1}, "pages": []}
            )

        mock_transport = httpx_mod.MockTransport(handler)

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self._inner = _real_async_client(transport=mock_transport)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                await self._inner.aclose()

            async def post(self, url, **kwargs):
                return await self._inner.post(url, **kwargs)

        monkeypatch.setattr(fpd_client_module.httpx, "AsyncClient", _FakeAsyncClient)

        client = FPDClient(api_key="uspto-test-key")

        # mistral_semaphore is Semaphore(2) — 4 concurrent calls must never
        # let more than 2 upload/OCR HTTP calls run at the same instant.
        await asyncio.gather(
            *[
                client.extract_with_mistral_ocr(b"%PDF-1.4 fake", page_count=1)
                for _ in range(4)
            ]
        )

        assert max_in_flight <= 2
