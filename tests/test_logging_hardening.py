"""Tests for the content-minimization logging posture.

Covers the three guarantees:
1. The sink-level SanitizingFilter scrubs secrets/credentials from every
   record regardless of which logger emitted it (raw logging.getLogger
   included), message and traceback alike.
2. Extraction/search code paths log character counts, never content.
3. Auth-failure paths log an event but never the presented key/token.
"""

import io
import logging
import re
from pathlib import Path

import pytest

from fpd_mcp.shared.log_sanitizer import SanitizingFilter

SRC_DIR = Path(__file__).parent.parent / "src" / "fpd_mcp"

# 30 lowercase letters — matches the USPTO API key shape the sanitizer masks
PLANTED_SECRET = "abcdefghijklmnopqrstuvwxyzabcd"
PLANTED_LINK_HASH = "deadbeefdeadbeefdeadbeef"  # sha256[:24]-style hex
PLANTED_QUERY_URL = (
    "https://api.uspto.gov/api/v1/petition/decisions/search"
    "?q=firstApplicantName%3ASecretClientCo"
)


def _capture_logger(name: str):
    """Raw logging.getLogger wired to a StringIO handler with the sink filter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SanitizingFilter())
    raw_logger = logging.getLogger(name)
    raw_logger.setLevel(logging.DEBUG)
    raw_logger.handlers = [handler]
    raw_logger.propagate = False
    return raw_logger, stream


class TestSinkFilter:
    """SanitizingFilter must scrub records at the handler, not the call site."""

    def test_scrubs_secret_query_and_link_hash_from_raw_logger(self):
        raw_logger, stream = _capture_logger("test_raw_bypass")

        raw_logger.info(
            f"key={PLANTED_SECRET} url={PLANTED_QUERY_URL} "
            f"link=/download/persistent/{PLANTED_LINK_HASH}"
        )
        output = stream.getvalue()

        assert PLANTED_SECRET not in output
        assert "SecretClientCo" not in output
        assert PLANTED_LINK_HASH not in output
        assert "[LINK_HASH]" in output
        assert "[QUERY_REDACTED]" in output

    def test_scrubs_pfw_style_persistent_paths(self):
        """Centralized-mode URLs use PFW's /document/persistent/ prefix."""
        raw_logger, stream = _capture_logger("test_raw_pfw_path")
        raw_logger.info(f"pfw link=/document/persistent/{PLANTED_LINK_HASH}")
        output = stream.getvalue()
        assert PLANTED_LINK_HASH not in output
        assert "[LINK_HASH]" in output

    def test_scrubs_exception_tracebacks(self):
        # Handlers format exc_info AFTER filters run — the filter must
        # pre-render and sanitize the traceback text.
        raw_logger, stream = _capture_logger("test_raw_exc")

        try:
            raise RuntimeError(f"boom {PLANTED_QUERY_URL}")
        except RuntimeError:
            raw_logger.error("operation failed", exc_info=True)
        output = stream.getvalue()

        assert "operation failed" in output
        assert "RuntimeError" in output
        assert "SecretClientCo" not in output

    def test_setup_logging_attaches_filter_to_all_handlers(self, tmp_path, monkeypatch):
        from fpd_mcp.config import log_config

        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        security = logging.getLogger("security")
        saved_security = list(security.handlers)
        try:
            log_config.setup_logging()
            # Only assert on handlers setup_logging itself added — pytest's
            # log-capture handler also lives on the root logger
            added_root = [h for h in root.handlers if h not in saved_handlers]
            added_security = [h for h in security.handlers if h not in saved_security]
            assert added_root, "setup_logging added no root handlers"
            for handler in added_root + added_security:
                assert any(
                    isinstance(f, SanitizingFilter) for f in handler.filters
                ), f"handler {handler} missing SanitizingFilter"
        finally:
            for h in [h for h in root.handlers if h not in saved_handlers]:
                root.removeHandler(h)
                h.close()
            for h in saved_handlers:
                if h not in root.handlers:
                    root.addHandler(h)
            root.setLevel(saved_level)
            for h in [h for h in security.handlers if h not in saved_security]:
                security.removeHandler(h)
                h.close()


class TestNoContentInLogCalls:
    """No extraction/search path may interpolate raw content into a log."""

    # f-string interpolation of a raw content variable; {len(text)} does not match
    _CONTENT_INTERPOLATION = re.compile(
        r'logger\.\w+\([^)]*\{(extracted_content|extracted_text|pypdf_text|mistral_text'
        r'|docling_text|response\.text|query|final_query)\}'
    )

    @pytest.mark.parametrize("relative_path", [
        "api/fpd_client.py",
        "services/fpd_service.py",
        "main.py",
    ])
    def test_no_raw_content_interpolation_in_log_calls(self, relative_path):
        source = (SRC_DIR / relative_path).read_text(encoding="utf-8")
        matches = self._CONTENT_INTERPOLATION.findall(source)
        assert not matches, (
            f"{relative_path} logs raw content variable(s): {matches} — "
            "log character counts, never content"
        )


class TestAuthFailureLogging:
    """Auth failures log an event and never the presented credential."""

    @pytest.mark.asyncio
    async def test_proxy_token_failure_logs_event_not_token(self, caplog):
        from starlette.requests import Request
        from fastapi import HTTPException
        from fpd_mcp.proxy.server import ProxyTokenDependency

        presented = "totally-wrong-token-value-123456789"
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/download/some-petition/DOC123",
            "query_string": b"",
            "headers": [(b"x-proxy-token", presented.encode())],
            "client": ("127.0.0.1", 55555),
        }
        request = Request(scope)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(HTTPException) as exc_info:
                await ProxyTokenDependency()(request)

        assert exc_info.value.status_code == 401
        assert "Proxy token" in caplog.text
        assert presented not in caplog.text

    @pytest.mark.asyncio
    async def test_api_key_failure_logs_event_not_key(self, monkeypatch):
        from fpd_mcp.main import APIKeyAuthMiddleware

        monkeypatch.setenv("INTERNAL_AUTH_SECRET", "expected-secret-value")
        presented = "wrong-api-key-abcdef"
        sent = []

        # Capture directly on the module logger — FPD's secure-logger wrapper
        # does not reliably propagate into pytest's caplog handler
        stream = io.StringIO()
        capture = logging.StreamHandler(stream)
        capture.setLevel(logging.WARNING)
        module_logger = logging.getLogger("fpd_mcp.main")
        module_logger.addHandler(capture)

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            sent.append(message)

        async def inner_app(scope, receive, send):
            raise AssertionError("request must not reach the inner app")

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "query_string": b"",
            "headers": [(b"x-api-key", presented.encode())],
            "server": ("127.0.0.1", 8005),
            "scheme": "http",
        }

        try:
            await APIKeyAuthMiddleware(inner_app)(scope, receive, send)
        finally:
            module_logger.removeHandler(capture)

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 401
        output = stream.getvalue()
        assert "HTTP auth failed" in output
        assert presented not in output


# --------------------------------------------------------------- F-A4 / Q-6


class TestLoggingFacadesAreEquivalent:
    """The content-minimization posture must not depend on which import a
    module happened to pick.

    F-A4: `UnifiedLogger` scrubbed the message and `extra` but passed
    POSITIONAL format arguments through untouched, while
    `util/secure_logger.SecureLogger` sanitized them. That difference is the
    documented reason the two facades were never merged, and it meant the
    guarantee was enforced at two strengths across 24 modules.
    """

    _SECRET = "sk-live-abcdefghijklmnopqrstuvwxyz012345"

    def _capture(self, logger_factory, name):
        import io
        import logging

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        underlying = logging.getLogger(name)
        underlying.handlers = [handler]
        underlying.propagate = False
        underlying.setLevel(logging.DEBUG)

        logger = logger_factory(name)
        logger.warning("resolved key %s for caller", self._SECRET)
        handler.flush()
        underlying.handlers = []
        return stream.getvalue()

    def test_unified_logger_sanitizes_positional_arguments(self):
        from fpd_mcp.shared.unified_logging import get_logger

        output = self._capture(get_logger, "fpd_mcp.test.unified_args")

        assert self._SECRET not in output

    def test_secure_logger_sanitizes_positional_arguments(self):
        from fpd_mcp.util.secure_logger import get_secure_logger

        output = self._capture(get_secure_logger, "fpd_mcp.test.secure_args")

        assert self._SECRET not in output

    def test_the_consolidation_docstring_is_not_a_false_claim(self):
        """It asserted the five modules were eliminated; they were not."""
        from fpd_mcp.shared import unified_logging

        doc = unified_logging.__doc__ or ""
        assert "eliminating duplication across 5 separate logging modules" not in doc
        assert "consolidated the" in doc.replace("\n", " ")

    def test_the_auth_store_no_longer_uses_the_raw_stdlib_logger(self):
        import inspect

        from fpd_mcp.auth import store

        source = inspect.getsource(store)
        assert "logging.getLogger(__name__)" not in source
