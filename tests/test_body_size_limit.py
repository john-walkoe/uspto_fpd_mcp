"""Request bodies are bounded on both HTTP surfaces, declared or not.

M-2: nothing capped a `/mcp` POST body.
M-3: the download proxy's RequestSizeLimitMiddleware read Content-Length and
trusted it, so a chunked request passed the 1 MB cap entirely.
M-22: log files lost their 0600 permission on rollover.
"""

import logging
import os
import stat

import pytest
from httpx import ASGITransport, AsyncClient

from fpd_mcp.shared.body_limit import BodySizeLimitMiddleware


async def _ok_app(scope, receive, send):
    """Reads the whole body, then answers 200 — the shape being defended."""
    body = b""
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        body += message.get("body", b"") or b""
        if not message.get("more_body"):
            break
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({"type": "http.response.body", "body": str(len(body)).encode()})


def _wrapped(max_bytes=100):
    return BodySizeLimitMiddleware(_ok_app, max_body_bytes=max_bytes)


async def test_a_body_within_the_cap_passes():
    async with AsyncClient(
        transport=ASGITransport(app=_wrapped()), base_url="http://test"
    ) as client:
        resp = await client.post("/", content=b"a" * 50)

    assert resp.status_code == 200
    assert resp.text == "50"


async def test_an_oversized_declared_body_is_rejected_before_it_is_read():
    async with AsyncClient(
        transport=ASGITransport(app=_wrapped()), base_url="http://test"
    ) as client:
        resp = await client.post("/", content=b"a" * 500)

    assert resp.status_code == 413


async def test_an_oversized_chunked_body_is_rejected_too():
    """M-3: no Content-Length, so the declared-length check cannot fire."""

    async def chunks():
        for _ in range(10):
            yield b"a" * 50

    async with AsyncClient(
        transport=ASGITransport(app=_wrapped()), base_url="http://test"
    ) as client:
        resp = await client.post("/", content=chunks())

    assert resp.status_code == 413


async def test_a_lying_content_length_does_not_get_past_the_cap():
    """A caller declaring 10 bytes and sending 500 is counted, not trusted."""

    async def app(scope, receive, send):
        await _ok_app(scope, receive, send)

    wrapped = BodySizeLimitMiddleware(app, max_body_bytes=100)
    sent = []

    async def send(message):
        sent.append(message)

    body_chunks = [
        {"type": "http.request", "body": b"a" * 500, "more_body": False},
    ]

    async def receive():
        return body_chunks.pop(0)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", b"10")],
        "client": ("203.0.113.20", 5000),
    }
    await wrapped(scope, receive, send)

    assert sent[0]["status"] == 413


async def test_the_proxy_app_caps_a_chunked_upload():
    """An authenticated caller streaming a chunked body used to bypass the
    1 MB cap entirely, because nothing declared a Content-Length."""
    from fpd_mcp.proxy.server import (
        MAX_REQUEST_SIZE,
        _get_proxy_token,
        create_proxy_app,
    )

    async def chunks():
        for _ in range(MAX_REQUEST_SIZE // 1024 + 8):
            yield b"a" * 1024

    app = create_proxy_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/register-download",
            content=chunks(),
            headers={"X-Proxy-Token": _get_proxy_token()},
        )

    assert resp.status_code == 413


def test_log_files_keep_0600_across_a_rollover(tmp_path, monkeypatch):
    """M-22: chmod ran once at startup; rollover created a fresh 0644 file."""
    from fpd_mcp.config.log_config import setup_logging

    root = logging.getLogger()
    sec = logging.getLogger("fpd_mcp.security")
    saved = (root.handlers[:], root.level, sec.handlers[:], sec.level, sec.propagate)

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("FPD_LOG_MAX_BYTES", "1024")
    monkeypatch.setenv("FPD_LOG_BACKUP_COUNT", "2")
    try:
        setup_logging("INFO")
        logger = logging.getLogger("fpd_mcp.rollover_probe")
        for index in range(200):
            logger.warning("padding line %d %s", index, "x" * 60)

        rotated = sorted(tmp_path.glob("fpd_mcp.log*"))
        assert len(rotated) > 1, "the test did not actually roll the log over"
        for path in rotated:
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, path
    finally:
        for handler in root.handlers[:] + sec.handlers[:]:
            handler.close()
        root.handlers[:], root.level = saved[0], saved[1]
        sec.handlers[:], sec.level, sec.propagate = saved[2], saved[3], saved[4]


@pytest.mark.parametrize("declared", [b"not-a-number", b""])
async def test_a_malformed_content_length_is_not_turned_into_a_413(declared):
    """That condition belongs to the proxy's own L15 400 response."""
    async with AsyncClient(
        transport=ASGITransport(app=_wrapped()), base_url="http://test"
    ) as client:
        resp = await client.request(
            "POST", "/", content=b"a" * 10,
            headers={"content-length": declared.decode() or "0"},
        )

    assert resp.status_code != 413
