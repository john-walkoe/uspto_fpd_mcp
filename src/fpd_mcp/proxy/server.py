"""
FastAPI HTTP server for secure petition document downloads

Provides browser-accessible download URLs while keeping USPTO API keys secure.
Uses configurable port (via FPD_PROXY_PORT or PROXY_PORT environment variables).
Default: 8081 to avoid conflicts with Patent File Wrapper MCP (port 8080).
"""
import asyncio
import ipaddress
import os
import re
import secrets as _secrets
import threading
import time
import uuid
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from ..api.fpd_client import FPDClient
from ..api.field_constants import FPDFields
from .rate_limiter import rate_limiter
from ..shared.error_utils import generate_request_id
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)

# Request size limit configuration
MAX_REQUEST_SIZE = 1024 * 1024  # 1MB limit

# Global client instance
api_client = None

# =============================================================================
# PROXY TOKEN AUTH (server-to-server endpoints only)
# =============================================================================
# The token protects machine-facing endpoints (/download/{petition_id}/... and
# /api/register-download; /api/recent-downloads accepts it for the full
# registry, or a per-registrant viewer key for own entries — H2). Browser-
# facing endpoints (persistent links, the downloads page) must NOT require
# it — browsers cannot send custom headers on navigation (Lessons 41/43).
# Callers in the same process import _get_proxy_token(); cross-process
# callers set PROXY_TOKEN on both sides (Lesson 40: never regenerate the
# token in a caller).

_PROXY_TOKEN: Optional[str] = None


def _get_proxy_token() -> str:
    """Return the proxy auth token (PROXY_TOKEN env or generated once)."""
    global _PROXY_TOKEN
    if _PROXY_TOKEN is None:
        _PROXY_TOKEN = os.getenv("PROXY_TOKEN") or _secrets.token_urlsafe(32)
    return _PROXY_TOKEN


class ProxyTokenDependency:
    """FastAPI dependency validating the X-Proxy-Token header."""

    async def __call__(self, request: Request) -> None:
        supplied = request.headers.get("X-Proxy-Token", "")
        if not _secrets.compare_digest(supplied, _get_proxy_token()):
            # Log the event only — never the presented token or the path
            logger.warning("Proxy token auth failed (X-Proxy-Token missing or mismatch)")
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid X-Proxy-Token header"
            )


_check_proxy_token = ProxyTokenDependency()

# =============================================================================
# RECENT DOWNLOADS REGISTRY (in-memory, for the downloads panel/page)
# =============================================================================

_MAX_RECENT_DOWNLOADS = 50
_recent_downloads: List[Dict[str, Any]] = []
_recent_downloads_lock = threading.Lock()

# Registry entries are scoped to the registrant's viewer key so one tenant
# cannot enumerate another tenant's live persistent-download links (each
# download_url is itself a bearer credential — H2). Only the SHA-256 of the
# key is stored; the raw key travels in the tool's own /downloads?s=... URL.
_VIEWER_KEY_FIELD = "viewer_key"
_VIEWER_HASH_FIELD = "_viewer_key_hash"


def _hash_viewer_key(viewer_key: str) -> str:
    import hashlib
    return hashlib.sha256(viewer_key.encode("utf-8")).hexdigest()


def register_recent_download(entry: Dict[str, Any]) -> str:
    """Add a download to the in-memory registry; returns its download_id."""
    download_id = entry.get("download_id") or uuid.uuid4().hex
    entry = {**entry, "download_id": download_id,
             "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    viewer_key = entry.pop(_VIEWER_KEY_FIELD, None)
    if viewer_key:
        entry[_VIEWER_HASH_FIELD] = _hash_viewer_key(str(viewer_key))
    with _recent_downloads_lock:
        _recent_downloads.insert(0, entry)
        del _recent_downloads[_MAX_RECENT_DOWNLOADS:]
    return download_id


def get_recent_downloads(viewer_key: Optional[str] = None,
                         include_all: bool = False) -> List[Dict[str, Any]]:
    """Return a snapshot of the registry scoped to one viewer key.

    include_all=True (proxy-token-authenticated callers only) returns every
    entry. Otherwise only entries registered under `viewer_key` are returned;
    no key means no entries. Internal hash fields are stripped either way.
    """
    if not include_all and not viewer_key:
        return []
    wanted = _hash_viewer_key(viewer_key) if viewer_key else None
    with _recent_downloads_lock:
        snapshot = list(_recent_downloads)
    results = []
    for entry in snapshot:
        if not include_all and entry.get(_VIEWER_HASH_FIELD) != wanted:
            continue
        results.append({k: v for k, v in entry.items() if k != _VIEWER_HASH_FIELD})
    return results


# Browser-facing downloads page (served at GET /downloads, no token — used as
# the URL-mode elicitation target). Its fetch of /api/recent-downloads passes
# the per-registrant viewer key from the page URL's ?s= param (H2: the route
# never serves the registry anonymously; the key scopes it to the caller's
# own entries).
_DOWNLOADS_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FPD Downloads</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 14px; background: #f8f9fa; color: #1a1a2e; }
.header { background: #1e4d5c; color: #fff; padding: 14px 20px; display: flex; align-items: center; gap: 12px; }
.header h1 { font-size: 17px; font-weight: 600; }
.header .count { background: #3d8ba3; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.tip { background: #fff9e6; border-bottom: 1px solid #ffe08a; padding: 7px 20px; font-size: 12px; color: #6b5000; }
.container { max-width: 860px; margin: 0 auto; padding: 16px 20px; }
.empty { text-align: center; padding: 50px 20px; color: #888; }
.card { background: #fff; border: 1px solid #d8e4e8; border-radius: 8px; margin-bottom: 10px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; transition: background 0.3s; }
.card.highlight { background: #e6f2f6; border-color: #3d8ba3; box-shadow: 0 0 0 2px rgba(61,139,163,0.35); }
.icon { width: 36px; height: 36px; border-radius: 6px; background: #e6f2f6; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.info { flex: 1; min-width: 0; }
.title { font-weight: 600; font-size: 13px; margin-bottom: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { font-size: 12px; color: #888; display: flex; gap: 10px; flex-wrap: wrap; }
.badge { background: #e6f2f6; color: #1e4d5c; border-radius: 3px; padding: 1px 6px; font-size: 11px; font-weight: 700; }
a.btn { background: #1e4d5c; color: #fff; border-radius: 5px; padding: 7px 14px; font-size: 13px; text-decoration: none; white-space: nowrap; }
a.btn:hover { background: #3d8ba3; }
.ts { font-size: 11px; color: #bbb; white-space: nowrap; }
#status { text-align: center; font-size: 12px; color: #999; padding: 8px; }
</style>
</head>
<body>
<div class="header"><h1>FPD Recent Downloads</h1><span class="count" id="count">0</span></div>
<div class="tip">Click <strong>Download PDF</strong> to save a document. Links stay valid for 7 days. This page refreshes automatically.</div>
<div class="container">
  <div class="empty" id="empty" style="display:none">No downloads yet — use <code>FPD_get_document_download</code> in Claude to generate links.</div>
  <div id="cards"></div>
  <div id="status"></div>
</div>
<script>
const params = new URLSearchParams(location.search);
const highlightId = params.get('highlight');
const viewerKey = params.get('s') || '';
let firstLoad = true;

function fmtTime(iso) {
  try {
    const d = new Date(iso); const mins = Math.floor((Date.now() - d) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    if (mins < 1440) return Math.floor(mins / 60) + 'h ago';
    return d.toLocaleDateString();
  } catch { return ''; }
}

async function load() {
  try {
    const resp = await fetch('/api/recent-downloads?s=' + encodeURIComponent(viewerKey));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const docs = (await resp.json()).downloads || [];
    document.getElementById('count').textContent = docs.length;
    document.getElementById('empty').style.display = docs.length ? 'none' : 'block';
    const cards = document.getElementById('cards');
    cards.innerHTML = '';
    docs.forEach(d => {
      const div = document.createElement('div');
      div.className = 'card' + (highlightId && d.download_id === highlightId ? ' highlight' : '');
      div.innerHTML = `
        <div class="icon">📋</div>
        <div class="info">
          <div class="title">${d.enhanced_filename || d.document_description || 'Document'}</div>
          <div class="meta"><span class="badge">petition</span><span>${d.petition_id || ''}</span><span>Doc ${d.document_identifier || ''}</span></div>
        </div>
        <span class="ts">${fmtTime(d.registered_at)}</span>
        <a class="btn" href="${d.download_url}">Download PDF</a>
      `;
      cards.appendChild(div);
    });
    if (firstLoad && highlightId) {
      document.querySelector('.card.highlight')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      firstLoad = false;
    }
    document.getElementById('status').textContent = '';
  } catch (e) {
    document.getElementById('status').textContent = 'Could not load downloads: ' + e.message;
  }
}

load();
setInterval(load, 5000);
</script>
</body>
</html>"""


def sanitize_description(description: str, max_length: int = 40) -> str:
    """
    Sanitize document description for filename.

    Args:
        description: Raw document description from API
        max_length: Maximum characters (default 40)

    Returns:
        Sanitized description safe for filenames
    """
    if not description:
        return "DOCUMENT"

    # Convert to uppercase
    clean = description.upper()

    # Replace spaces with underscores
    clean = clean.replace(' ', '_')

    # Remove special characters except underscore and hyphen
    clean = re.sub(r'[^A-Z0-9_-]', '', clean)

    # Truncate to max length
    clean = clean[:max_length]

    return clean


def generate_enhanced_filename(
    petition_mail_date: Optional[str],
    app_number: str,
    patent_number: Optional[str],
    document_description: str,
    document_code: str,
    max_desc_length: int = 40
) -> str:
    """
    Generate enhanced filename for FPD documents.

    Format: PET-{date}_APP-{app}_PAT-{patent}_{description}.pdf
    or:     PET-{date}_APP-{app}_{description}.pdf (if no patent)
    or:     APP-{app}_PAT-{patent}_{description}.pdf (if no petition date)

    Args:
        petition_mail_date: Petition filing date (YYYY-MM-DD format)
        app_number: Application number
        patent_number: Patent number (if granted, else None)
        document_description: Document description from API
        document_code: Document code (fallback)
        max_desc_length: Max chars for description (default 40)

    Returns:
        Safe filename for download
    """
    # Build filename components
    components = []

    # Add petition date if available (format: PET-YYYY-MM-DD)
    if petition_mail_date and petition_mail_date.strip():
        # Extract just the date portion (handles ISO format with time)
        date_part = petition_mail_date.split('T')[0] if 'T' in petition_mail_date else petition_mail_date
        components.append(f"PET-{date_part}")

    # Add application number (L23: routed through the same allowlist
    # sanitizer as the description field, instead of interpolating the
    # trusted-source value unsanitized)
    components.append(f"APP-{sanitize_description(app_number or 'UNKNOWN', 20)}")

    # Add patent number if available (L23: same sanitizer)
    if patent_number and patent_number.strip():
        components.append(f"PAT-{sanitize_description(patent_number, 20)}")

    # Sanitize description (use document_code as fallback)
    desc = document_description or document_code or "DOCUMENT"
    desc_clean = sanitize_description(desc, max_desc_length)
    components.append(desc_clean)

    # Join and add extension
    filename = "_".join(components) + ".pdf"

    return filename


async def _open_upstream_pdf_stream(download_url: str, api_key: str):
    """Open a USPTO PDF stream with the body verified as a PDF (L24).

    Prefetches the first chunk and checks the %PDF- magic bytes BEFORE any
    response headers go to the client, so a mislabeled upstream body (error
    page, HTML) becomes a clean 502 instead of being served as
    application/pdf. Returns an async generator that owns the connection.
    Raises httpx.HTTPStatusError on non-2xx, HTTPException(502) on non-PDF.
    """
    client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    response = None
    try:
        response = await client.send(
            client.build_request(
                "GET", download_url,
                headers={"X-API-KEY": api_key, "Accept": "application/pdf"},
            ),
            stream=True,
        )
        response.raise_for_status()
        iterator = response.aiter_bytes(chunk_size=8192)
        first_chunk = b""
        async for chunk in iterator:
            first_chunk = chunk
            break
        if not first_chunk.startswith(b"%PDF-"):
            logger.error("Upstream body failed %PDF- magic-byte check")
            raise HTTPException(status_code=502,
                                 detail="Upstream returned non-PDF content")
    except Exception:
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise

    async def stream_body():
        try:
            if first_chunk:
                yield first_chunk
            async for chunk in iterator:
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return stream_body()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Add security headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit request body size for security.

    Prevents DoS attacks via large request bodies.
    """

    def __init__(self, app, max_request_size: int = MAX_REQUEST_SIZE):
        super().__init__(app)
        self.max_request_size = max_request_size

    async def dispatch(self, request: Request, call_next):
        """Check request size and reject if too large"""
        # Get Content-Length header if present
        content_length = request.headers.get('content-length')

        if content_length:
            # L15: a non-numeric Content-Length must not crash the request
            # with an unhandled ValueError — treat it as a clean 400 instead.
            try:
                content_length = int(content_length)
            except ValueError:
                request_id = generate_request_id()
                logger.warning(f"[{request_id}] Non-numeric Content-Length header rejected")
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": True,
                        "message": "Invalid Content-Length header",
                        "request_id": request_id
                    }
                )
            if content_length > self.max_request_size:
                # Log security event
                client_ip = request.client.host if request.client else "unknown"
                request_id = generate_request_id()

                logger.warning(
                    f"[{request_id}] Request body too large: {content_length} bytes from {client_ip}"
                )

                return JSONResponse(
                    status_code=413,  # Payload Too Large
                    content={
                        "error": True,
                        "message": f"Request body too large. Maximum size: {self.max_request_size} bytes",
                        "content_length": content_length,
                        "max_allowed": self.max_request_size,
                        "request_id": request_id
                    }
                )

        return await call_next(request)


# L8: cleanup_expired_links() existed on SecureLinkCache but was never
# invoked anywhere — expired-link rows would accumulate indefinitely. Run it
# once a day via a background task tied to the proxy app's lifespan.
_LINK_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def _periodic_link_cleanup() -> None:
    from .secure_link_cache import get_link_cache

    while True:
        await asyncio.sleep(_LINK_CLEANUP_INTERVAL_SECONDS)
        try:
            removed = get_link_cache().cleanup_expired_links()
            if removed:
                logger.info(f"Periodic cleanup removed {removed} expired persistent link(s)")
        except Exception as e:
            logger.warning(f"Periodic link cleanup failed: {type(e).__name__}")


def create_lifespan(api_key: Optional[str] = None):
    """Create lifespan context manager with API key"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application lifespan"""
        global api_client
        cleanup_task = None
        try:
            # Use provided API key (from secure storage) or fall back to environment variable
            api_client = FPDClient(api_key=api_key) if api_key else FPDClient()
            logger.info("USPTO Final Petition Decisions API client initialized for proxy server")
            cleanup_task = asyncio.create_task(_periodic_link_cleanup())
            yield
        except Exception as e:
            logger.error(f"Failed to initialize USPTO API client: {e}")
            raise
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
    return lifespan


def _safe_parse_proxy_port() -> int:
    """Safely parse the proxy port, handling the 'none' sentinel value.

    Shared by create_proxy_app and run_proxy_cli (previously duplicated
    verbatim in both) — extracted with no behavior change.
    """
    port_str = os.getenv('FPD_PROXY_PORT') or os.getenv('PROXY_PORT') or '8081'
    if port_str.lower() == 'none':
        return 8081
    try:
        return int(port_str)
    except ValueError:
        return 8081


def _build_proxy_cors_origins() -> List[str]:
    """CORS origins for the proxy app: loopback dev defaults +
    CORS_EXTRA_ORIGIN entries (comma-separated, regex-validated per entry).
    Extracted from create_proxy_app verbatim (mechanical decomposition, no
    behavior change)."""
    cors_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",  # Patent File Wrapper MCP
        "http://127.0.0.1:8080"
    ]
    for _cors_entry in os.getenv("CORS_EXTRA_ORIGIN", "").split(","):
        _cors_entry = _cors_entry.strip()
        if not _cors_entry:
            continue
        if re.match(r"^https?://[A-Za-z0-9.\-]+(:[0-9]+)?$", _cors_entry):
            if _cors_entry not in cors_origins:
                cors_origins.append(_cors_entry)
                logger.info(f"CORS: added extra origin {_cors_entry}")
        else:
            logger.warning(f"Ignoring invalid CORS_EXTRA_ORIGIN entry: {_cors_entry}")
    return cors_origins


def _build_proxy_allowed_networks() -> List[Any]:
    """Parse PROXY_ALLOWED_IPS into ip_network objects (loopback is always
    allowed separately — see _is_ip_allowed). Extracted from
    create_proxy_app verbatim (mechanical decomposition, no behavior
    change)."""
    allowed_networks = []
    for entry in os.getenv("PROXY_ALLOWED_IPS", "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            allowed_networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning(f"Ignoring invalid PROXY_ALLOWED_IPS entry: {entry}")
    return allowed_networks


def _is_ip_allowed(client_ip: str, allowed_networks: List[Any]) -> bool:
    """IP allowlist check: loopback is always allowed, or an explicit
    PROXY_ALLOWED_IPS network match (see the M5 design note on
    create_proxy_app's ip_allowlist middleware — X-Forwarded-For is
    deliberately not trusted here). Extracted from create_proxy_app's
    ip_allowlist middleware verbatim (mechanical decomposition, no
    behavior change)."""
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        addr = None
    return addr is not None and (
        addr.is_loopback or any(addr in net for net in allowed_networks)
    )


def _require_proxy_api_client(log_message: Optional[str] = None) -> None:
    """Raise 503 if the module-level proxy `api_client` isn't initialized
    yet. Extracted from download_document / download_document_persistent
    (mechanical decomposition, no behavior change) — called with a log
    message at the two points in download_document that previously logged
    before raising, and without one at the point in
    download_document_persistent that previously raised silently."""
    if api_client is None:
        if log_message:
            logger.error(log_message)
        raise HTTPException(
            status_code=503,
            detail="Proxy server not ready - API client not initialized. Try again in a moment."
        )


def _proxy_rate_limit_response(client_ip: str) -> Optional[JSONResponse]:
    """429 JSONResponse if client_ip is currently rate-limited, else None.
    Extracted from download_document (mechanical decomposition, no
    behavior change)."""
    if rate_limiter.is_allowed(client_ip):
        return None
    import time
    remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))
    return JSONResponse(
        status_code=429,
        content={
            "error": True,
            "message": "Rate limit exceeded. USPTO allows 5 downloads per 10 seconds.",
            "retry_after": remaining_time,
            "remaining_requests": 0
        },
        headers={"Retry-After": str(int(remaining_time))}
    )


async def _resolve_proxy_document_and_pdf_url(petition_id: str, document_identifier: str):
    """Fetch petition + locate the target document and its PDF download
    option/URL for the direct proxy download route. Raises HTTPException on
    any failure. Extracted from download_document (mechanical
    decomposition, no behavior change).

    Returns (petition_data, target_doc, pdf_option, download_url).
    """
    _require_proxy_api_client("API client not initialized in proxy server - lifespan may not have completed")

    # Get petition data to find the specific document
    petition_result = await api_client.get_petition_by_id(
        petition_id,
        include_documents=True
    )

    if petition_result.get('error'):
        raise HTTPException(
            status_code=404,
            detail=petition_result.get('error', 'Petition not found')
        )

    # Extract from nested structure
    petition_data_bag = petition_result.get(FPDFields.PETITION_DECISION_DATA_BAG, [])
    if not petition_data_bag:
        raise HTTPException(
            status_code=404,
            detail='Petition data not found'
        )

    petition_data = petition_data_bag[0]
    documents = petition_data.get(FPDFields.DOCUMENT_BAG, [])

    # Find the target document
    target_doc = None
    for doc in documents:
        if doc.get(FPDFields.DOCUMENT_IDENTIFIER) == document_identifier:
            target_doc = doc
            break

    if not target_doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document with identifier '{document_identifier}' not found"
        )

    # Find PDF download option
    download_options = target_doc.get(FPDFields.DOWNLOAD_OPTION_BAG, [])
    pdf_option = None

    for option in download_options:
        if option.get(FPDFields.MIME_TYPE_IDENTIFIER) == 'PDF':
            pdf_option = option
            break

    if not pdf_option:
        raise HTTPException(
            status_code=404,
            detail="PDF not available for this document"
        )

    download_url = pdf_option.get(FPDFields.DOWNLOAD_URL)
    if not download_url:
        raise HTTPException(
            status_code=404,
            detail="Download URL not available"
        )

    return petition_data, target_doc, pdf_option, download_url


def _build_proxy_download_response_headers(
    petition_id: str,
    document_identifier: str,
    petition_data: Dict[str, Any],
    target_doc: Dict[str, Any],
    pdf_option: Dict[str, Any],
):
    """Build the enhanced filename + streaming response headers for the
    direct proxy download route. Extracted from download_document verbatim
    (mechanical decomposition, no behavior change).

    Returns (filename, response_headers, page_count).
    """
    # Get document metadata for response headers
    page_count = pdf_option.get(FPDFields.PAGE_TOTAL_QUANTITY, 0)

    # Extract petition details for enhanced filename
    app_number = petition_data.get(FPDFields.APPLICATION_NUMBER_TEXT)
    patent_number = petition_data.get(FPDFields.PATENT_NUMBER)

    # Extract petition mail date for filename
    petition_mail_date = petition_data.get(FPDFields.PETITION_MAIL_DATE)

    # Get document description (with fallback to document code)
    doc_description = target_doc.get(FPDFields.DOCUMENT_CODE_DESCRIPTION_TEXT)
    doc_code = target_doc.get(FPDFields.DOCUMENT_CODE)

    # Generate enhanced filename
    filename = generate_enhanced_filename(
        petition_mail_date=petition_mail_date,
        app_number=app_number,
        patent_number=patent_number,
        document_description=doc_description,
        document_code=doc_code,
        max_desc_length=40
    )

    # Set appropriate headers for PDF download
    response_headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Petition-ID": petition_id,
        "X-Document-Identifier": document_identifier,
        "X-Page-Count": str(page_count),
        "X-Enhanced-Filename": filename,
        "X-App-Number": app_number or "UNKNOWN",
        "X-Patent-Number": patent_number or "NONE"
    }

    return filename, response_headers, page_count


def _map_proxy_http_status_error(
    e: httpx.HTTPStatusError, petition_id: str, document_identifier: str
) -> HTTPException:
    """Map an httpx.HTTPStatusError from the USPTO API to the direct proxy
    download route's HTTPException. Extracted from download_document
    verbatim (mechanical decomposition, no behavior change)."""
    if e.response.status_code == 403:
        logger.error(f"USPTO API authentication failed for petition {petition_id}/{document_identifier}")
        return HTTPException(
            status_code=502,
            detail="Authentication failed with USPTO API"
        )
    else:
        # Status only — response bodies stay out of logs
        logger.error(f"USPTO API error {e.response.status_code}")
        return HTTPException(
            status_code=502,
            detail=f"USPTO API error: {e.response.status_code}"
        )


async def _handle_persistent_download(link_hash: str, request: Request):
    """Body of the browser-facing GET /download/persistent/{link_hash}
    route. Extracted from create_proxy_app (mechanical decomposition, no
    behavior change)."""
    import time as _time
    # M5: keyed on request.client.host (the raw ASGI peer address), same
    # loopback-only design note as the IP allowlist above — XFF is
    # deliberately not trusted, so this is only meaningful for direct
    # (non-reverse-proxied) callers.
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - _time.time()))
        return JSONResponse(
            status_code=429,
            content={
                "error": True,
                "message": "Rate limit exceeded. USPTO allows 5 downloads per 10 seconds.",
                "retry_after": remaining_time
            },
            headers={"Retry-After": str(int(remaining_time))}
        )

    from .secure_link_cache import get_link_cache
    link_data = get_link_cache().resolve_persistent_link(link_hash)
    if not link_data:
        raise HTTPException(
            status_code=404,
            detail="Download link not found or expired (links are valid for 7 days). "
                   "Generate a new link with FPD_get_document_download."
        )

    download_url = link_data.get("file_download_uri")
    filename = link_data.get("enhanced_filename") or "petition_document.pdf"

    if not download_url:
        raise HTTPException(
            status_code=404,
            detail="Stored download URL missing. Generate a new link with FPD_get_document_download."
        )

    _require_proxy_api_client()

    # Truncated hash only — the full hash is the credential (Lesson 43)
    logger.info(f"Streaming persistent download {link_hash[:8]}...: {filename}")

    try:
        pdf_stream = await _open_upstream_pdf_stream(download_url, api_client.api_key)
    except httpx.HTTPStatusError as e:
        logger.error(f"USPTO API error {e.response.status_code} on persistent download")
        raise HTTPException(status_code=502,
                             detail=f"USPTO API error: {e.response.status_code}")

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Enhanced-Filename": filename
        },
        background=BackgroundTask(
            lambda: logger.info(f"Persistent download completed: {filename}")
        )
    )


async def _handle_direct_download(petition_id: str, document_identifier: str, request: Request):
    """Body of the token-protected GET /download/{petition_id}/{document_identifier}
    route. Extracted from create_proxy_app (mechanical decomposition, no
    behavior change)."""
    try:
        # Get client IP for rate limiting
        client_ip = request.client.host if request.client else "unknown"

        # Apply rate limiting
        rate_limited_response = _proxy_rate_limit_response(client_ip)
        if rate_limited_response is not None:
            return rate_limited_response

        # Get petition details with documents
        logger.info(f"Proxying download for petition {petition_id}, doc {document_identifier}, IP {client_ip}")

        petition_data, target_doc, pdf_option, download_url = await _resolve_proxy_document_and_pdf_url(
            petition_id, document_identifier
        )

        filename, response_headers, page_count = _build_proxy_download_response_headers(
            petition_id, document_identifier, petition_data, target_doc, pdf_option
        )

        # Stream the PDF from USPTO API (magic-byte verified, L24)
        _require_proxy_api_client("API client became None during streaming - async lifecycle issue")
        pdf_stream = await _open_upstream_pdf_stream(download_url, api_client.api_key)

        logger.info(f"Streaming PDF: {filename} ({page_count} pages)")

        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers=response_headers,
            background=BackgroundTask(
                lambda: logger.info(f"Download completed: {filename}")
            )
        )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise _map_proxy_http_status_error(e, petition_id, document_identifier)
    except Exception as e:
        logger.error(f"Proxy download failed for petition {petition_id}/{document_identifier}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Download failed: {str(e)}"
        )


async def _handle_register_download(request: Request) -> Dict[str, Any]:
    """Body of the POST /api/register-download route. Extracted from
    create_proxy_app (mechanical decomposition, no behavior change).

    Reads the body via Request.json() directly — a `payload: dict`
    parameter would make FastAPI return 422 on schema mismatch, which
    httpx callers would not surface (Lesson 25).

    L19/L20: the parsed JSON is whitelisted and length-capped via
    RecentDownloadRegistration before it ever reaches the in-memory
    registry or the downloads page's template rendering.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object expected")
    try:
        from pydantic import ValidationError as _PydanticValidationError

        from .models import RecentDownloadRegistration

        validated = RecentDownloadRegistration.model_validate(payload)
    except _PydanticValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid registration payload: {e}")
    payload = validated.model_dump(exclude_none=True)
    download_id = register_recent_download(payload)
    return {"registered": True, "download_id": download_id}


def _handle_recent_downloads(request: Request) -> Dict[str, Any]:
    """Body of the GET /api/recent-downloads route. Extracted from
    create_proxy_app (mechanical decomposition, no behavior change).

    Each entry's download_url is a live bearer credential, so this never
    serves the full registry anonymously (H2): callers present either the
    machine-facing X-Proxy-Token (full registry) or the per-registrant
    viewer key `s` the tool embedded in the /downloads page URL (own
    entries only).
    """
    supplied_token = request.headers.get("X-Proxy-Token", "")
    if supplied_token and _secrets.compare_digest(supplied_token, _get_proxy_token()):
        return {"downloads": get_recent_downloads(include_all=True)}
    viewer_key = request.query_params.get("s", "")
    if not viewer_key:
        raise HTTPException(
            status_code=401,
            detail="Missing viewer key. Open the downloads page via the "
                   "link returned by FPD_get_document_download."
        )
    return {"downloads": get_recent_downloads(viewer_key=viewer_key)}


def create_proxy_app(api_key: Optional[str] = None, port: Optional[int] = None) -> FastAPI:
    """Create FastAPI application for petition document proxy

    Args:
        api_key: Optional USPTO API key (e.g., from secure storage).
                 If not provided, will attempt to load from USPTO_API_KEY environment variable.
        port: Optional port number for health check response.
              If not provided, reads from FPD_PROXY_PORT or PROXY_PORT environment variables.
    """
    app = FastAPI(
        title="USPTO Petition Document Proxy",
        description="Secure proxy for USPTO petition document downloads",
        version="1.0.0",
        lifespan=create_lifespan(api_key)
    )

    # Store port in app state for health check
    # Check FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
    app.state.port = port if port is not None else _safe_parse_proxy_port()

    # Add request size limit middleware (BEFORE other middleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_request_size=MAX_REQUEST_SIZE)

    # Add security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Add CORS middleware with strict origins. Defaults are loopback-only
    # dev origins (L14): non-localhost origins are never hardcoded — any
    # extension goes through CORS_EXTRA_ORIGIN, comma-separated and
    # regex-validated per entry (same pattern as main.py's HTTP-mode CORS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_proxy_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # IP allowlist: loopback always allowed; extend via PROXY_ALLOWED_IPS
    # (comma-separated IPs or CIDRs, e.g. Docker subnets - Lesson 32)
    #
    # M5 (design note, not a bug): this is a loopback-only design by intent.
    # `request.client.host` is the raw ASGI peer address; X-Forwarded-For is
    # deliberately NOT trusted here because it is trivially spoofable by any
    # direct caller (there is no trusted reverse proxy in front of this
    # service in the default deployment). If this proxy is ever fronted by
    # an actual reverse proxy, that proxy's own address must be added to
    # PROXY_ALLOWED_IPS and its (trusted) XFF header parsed explicitly —
    # do not simply start trusting the header from all callers.
    allowed_networks = _build_proxy_allowed_networks()

    @app.middleware("http")
    async def ip_allowlist(request: Request, call_next):
        client_ip = request.client.host if request.client else ""
        if not _is_ip_allowed(client_ip, allowed_networks):
            logger.warning(f"Rejected proxy request from non-allowlisted IP: {client_ip}")
            return JSONResponse(status_code=403, content={
                "error": True,
                "message": "Client IP not allowed. Configure PROXY_ALLOWED_IPS for non-local access."
            })
        return await call_next(request)

    @app.get("/")
    async def health_check():
        """Health check endpoint"""
        return {
            "status": "healthy",
            "service": "USPTO Petition Document Proxy",
            "port": app.state.port,
            "note": f"Runs on port {app.state.port} (configurable via FPD_PROXY_PORT or PROXY_PORT)"
        }

    # NOTE: this route MUST be registered before /download/{petition_id}/{doc}
    # below — FastAPI matches routes in registration order, and the
    # parameterized route would otherwise capture "persistent" as a
    # petition_id and demand the proxy token (verified live: 401 on click).
    @app.get("/download/persistent/{link_hash}")
    async def download_document_persistent(link_hash: str, request: Request):
        """
        Browser-facing persistent download endpoint.

        The 96-bit link hash IS the credential — this route must never carry
        the X-Proxy-Token dependency, because browsers cannot send custom
        headers on navigation (Lessons 41/43). The encrypted payload stores
        the resolved USPTO download URL, so no petition re-fetch is needed.
        """
        return await _handle_persistent_download(link_hash, request)

    @app.get("/download/{petition_id}/{document_identifier}", dependencies=[Depends(_check_proxy_token)])
    async def download_document(
        petition_id: str,
        document_identifier: str,
        request: Request
    ):
        """
        Proxy endpoint for downloading USPTO petition documents

        This endpoint handles authentication with the USPTO API and streams
        the PDF content directly to the browser, enabling direct downloads
        while keeping API keys secure.

        Args:
            petition_id: Petition decision record identifier (UUID)
            document_identifier: Document ID from documentBag
            request: FastAPI request object (for client IP)
        """
        return await _handle_direct_download(petition_id, document_identifier, request)

    @app.post("/api/register-download", dependencies=[Depends(_check_proxy_token)])
    async def api_register_download(request: Request):
        """Register a generated download for the recent-downloads panel/page.

        Reads the body via Request.json() directly — a `payload: dict`
        parameter would make FastAPI return 422 on schema mismatch, which
        httpx callers would not surface (Lesson 25).

        L19/L20: the parsed JSON is whitelisted and length-capped via
        RecentDownloadRegistration before it ever reaches the in-memory
        registry or the downloads page's template rendering — closes the
        "arbitrary JSON object, no schema" gap and, with it, the latent
        stored-XSS pattern (nothing outside the whitelist/cap set can reach
        the page).
        """
        return await _handle_register_download(request)

    @app.get("/api/recent-downloads")
    async def api_recent_downloads(request: Request):
        """Return the recent downloads registry (for the downloads panel/page).

        Each entry's download_url is a live bearer credential, so this
        endpoint never serves the full registry anonymously (H2): callers
        present either the machine-facing X-Proxy-Token (full registry) or
        the per-registrant viewer key `s` the tool embedded in the
        /downloads page URL (own entries only).
        """
        return _handle_recent_downloads(request)

    @app.get("/downloads")
    async def downloads_page():
        """Browser-facing downloads page — the URL-mode elicitation target.

        No token (browser navigation can't send headers); protected by the
        same localhost bind + IP allowlist as everything else. ?highlight=
        scrolls to and highlights a specific download_id.
        """
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_DOWNLOADS_PAGE_HTML)

    @app.get("/rate-limit/{client_ip}")
    async def check_rate_limit(client_ip: str):
        """Check rate limit status for a client IP"""
        return {
            "client_ip": client_ip,
            "remaining_requests": rate_limiter.get_remaining_requests(client_ip),
            "max_requests": rate_limiter.max_requests,
            "time_window": rate_limiter.time_window,
            "reset_time": rate_limiter.get_reset_time(client_ip)
        }

    return app


def run_proxy_cli():
    """CLI entry point for proxy server"""
    import uvicorn
    import sys

    # Check FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic), then default to 8081
    default_port = _safe_parse_proxy_port()
    port = default_port

    # Check for port argument (command line overrides environment variables)
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            logger.warning(f"Invalid port: {sys.argv[1]}, using default {default_port}")
            port = default_port

    logger.info(f"Starting USPTO Petition Document Proxy on port {port}...")
    logger.info(f"Health check: http://localhost:{port}/")
    logger.info(f"Port {port} (configurable via FPD_PROXY_PORT or PROXY_PORT environment variables)")

    uvicorn.run(
        "fpd_mcp.proxy.server:create_proxy_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="info",
        # access lines include request paths, and /download/persistent/{hash}
        # paths embed the link credential
        access_log=False
    )
