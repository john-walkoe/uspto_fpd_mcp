"""
FastAPI HTTP server for secure petition document downloads

Provides browser-accessible download URLs while keeping USPTO API keys secure.
Uses configurable port (via FPD_PROXY_PORT or PROXY_PORT environment variables).
Default: 8081 to avoid conflicts with Patent File Wrapper MCP (port 8080).
"""
import re
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
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

    # Add application number
    components.append(f"APP-{app_number or 'UNKNOWN'}")

    # Add patent number if available
    if patent_number and patent_number.strip():
        components.append(f"PAT-{patent_number}")

    # Sanitize description (use document_code as fallback)
    desc = document_description or document_code or "DOCUMENT"
    desc_clean = sanitize_description(desc, max_desc_length)
    components.append(desc_clean)

    # Join and add extension
    filename = "_".join(components) + ".pdf"

    return filename


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
            content_length = int(content_length)
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


def create_lifespan(api_key: Optional[str] = None):
    """Create lifespan context manager with API key"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application lifespan"""
        global api_client
        try:
            # Use provided API key (from secure storage) or fall back to environment variable
            api_client = FPDClient(api_key=api_key) if api_key else FPDClient()
            logger.info("USPTO Final Petition Decisions API client initialized for proxy server")
            yield
        except Exception as e:
            logger.error(f"Failed to initialize USPTO API client: {e}")
            raise
    return lifespan


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
    import os

    def safe_parse_port() -> int:
        """Safely parse proxy port, handling 'none' sentinel value"""
        port_str = os.getenv('FPD_PROXY_PORT') or os.getenv('PROXY_PORT') or '8081'
        if port_str.lower() == 'none':
            return 8081
        try:
            return int(port_str)
        except ValueError:
            return 8081

    app.state.port = port if port is not None else safe_parse_port()

    # Add request size limit middleware (BEFORE other middleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_request_size=MAX_REQUEST_SIZE)

    # Add security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Add CORS middleware with strict origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8080",  # Patent File Wrapper MCP
            "http://127.0.0.1:8080"
        ],
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def health_check():
        """Health check endpoint"""
        return {
            "status": "healthy",
            "service": "USPTO Petition Document Proxy",
            "port": app.state.port,
            "note": f"Runs on port {app.state.port} (configurable via FPD_PROXY_PORT or PROXY_PORT)"
        }

    @app.get("/download/{petition_id}/{document_identifier}")
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
        try:
            # Get client IP for rate limiting
            client_ip = request.client.host if request.client else "unknown"

            # Apply rate limiting
            if not rate_limiter.is_allowed(client_ip):
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

            # Get petition details with documents
            logger.info(f"Proxying download for petition {petition_id}, doc {document_identifier}, IP {client_ip}")

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

            # Get document metadata for response headers
            doc_filename = target_doc.get(FPDFields.DOCUMENT_FILE_NAME, 'petition_document.pdf')
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

            # Stream the PDF from USPTO API
            async def stream_pdf():
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    # Use the API client's headers (includes X-API-KEY)
                    headers = {
                        "X-API-KEY": api_client.api_key,
                        "Accept": "application/pdf"
                    }
                    async with client.stream("GET", download_url, headers=headers) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            yield chunk

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

            logger.info(f"Streaming PDF: {filename} ({page_count} pages)")

            return StreamingResponse(
                stream_pdf(),
                media_type="application/pdf",
                headers=response_headers,
                background=BackgroundTask(
                    lambda: logger.info(f"Download completed: {filename}")
                )
            )

        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.error(f"USPTO API authentication failed for petition {petition_id}/{document_identifier}")
                raise HTTPException(
                    status_code=502,
                    detail="Authentication failed with USPTO API"
                )
            else:
                logger.error(f"USPTO API error {e.response.status_code}: {e.response.text}")
                raise HTTPException(
                    status_code=502,
                    detail=f"USPTO API error: {e.response.status_code}"
                )
        except Exception as e:
            logger.error(f"Proxy download failed for petition {petition_id}/{document_identifier}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Download failed: {str(e)}"
            )

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
    import os

    def safe_parse_port() -> int:
        """Safely parse proxy port, handling 'none' sentinel value"""
        port_str = os.getenv('FPD_PROXY_PORT') or os.getenv('PROXY_PORT') or '8081'
        if port_str.lower() == 'none':
            return 8081
        try:
            return int(port_str)
        except ValueError:
            return 8081

    # Check FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic), then default to 8081
    default_port = safe_parse_port()
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
        log_level="info"
    )
