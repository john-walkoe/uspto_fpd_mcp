"""Pure-ASGI request body cap, counted as the body is consumed.

Closes two findings with one implementation:

- M-2: nothing capped a `/mcp` POST body. uvicorn/h11 bound the request LINE
  and headers, not the body, so an authenticated caller could stream an
  arbitrarily large JSON-RPC frame into the MCP surface.
- M-3: the download proxy's `RequestSizeLimitMiddleware` read
  `Content-Length` and trusted it. A chunked request carries no
  `Content-Length` at all, so it passed the 1 MB cap entirely.

Both halves are handled here: the declared length is rejected before the body
is read (cheap), and the bytes are then counted on the receive channel so an
undeclared or lying length cannot get past the same limit.

Written as raw ASGI rather than a Starlette `BaseHTTPMiddleware` because
`BaseHTTPMiddleware` buffers the body to hand a `Request` to `dispatch`,
which is the very thing being defended against.
"""

import json
from typing import Any, Callable, Dict, Optional


class BodySizeLimitMiddleware:
    """Reject request bodies over `max_body_bytes` with HTTP 413.

    Args:
        app: the ASGI app to wrap.
        max_body_bytes: cap in bytes.
        error_body: JSON payload for the 413. Defaults to a minimal envelope;
            the download proxy passes its own shape so its two existing
            middleware rejections keep one format.
        on_reject: optional callback (client_ip, declared_or_counted_bytes)
            for logging. Never allowed to change the response.
    """

    def __init__(
        self,
        app,
        max_body_bytes: int,
        error_body: Optional[Dict[str, Any]] = None,
        on_reject: Optional[Callable[[Optional[str], int], None]] = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.error_body = error_body or {
            "error": "Request body too large",
            "max_allowed": max_body_bytes,
        }
        self.on_reject = on_reject

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_body_bytes:
                    await self._reject(scope, send, int(declared))
                    return
            except ValueError:
                # A malformed Content-Length is the proxy's own L15 case and
                # is handled by the layer that owns that response shape; do
                # not turn it into a 413 here.
                pass

        counted = 0
        rejected = False

        async def counting_receive():
            nonlocal counted, rejected
            message = await receive()
            if message["type"] == "http.request":
                counted += len(message.get("body", b"") or b"")
                if counted > self.max_body_bytes and not rejected:
                    # Answer immediately, then hand the app a disconnect so it
                    # unwinds. Waiting until the app returned did not work: a
                    # handler that treats a disconnect as end-of-body responds
                    # 200 first, and the response has already started.
                    rejected = True
                    await self._reject(scope, send, counted)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            # Everything the app tries to send after the 413 is dropped; the
            # response is already complete.
            if not rejected:
                await send(message)

        await self.app(scope, counting_receive, guarded_send)

    async def _reject(self, scope, send, size: int) -> None:
        if self.on_reject is not None:
            try:
                client = scope.get("client")
                self.on_reject(client[0] if client else None, size)
            except Exception:
                pass
        payload = json.dumps(self.error_body).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": payload})
