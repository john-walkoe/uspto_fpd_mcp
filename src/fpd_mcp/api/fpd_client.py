"""
USPTO Final Petition Decisions API Client

Client for accessing the USPTO Final Petition Decisions API via Open Data Portal.
Requires USPTO API key (same as Patent File Wrapper).
"""

import asyncio
import httpx
import json
import os
import random
import base64
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import quote
from ..shared.error_utils import format_error_response, generate_request_id
from ..shared.circuit_breaker import CircuitBreaker
from ..shared.cache import CacheManager
from ..config.feature_flags import feature_flags
from ..config import api_constants
from ..shared.unified_logging import get_logger
from .field_constants import FPDFields, QueryFieldNames

logger = get_logger(__name__)


class FPDClient:
    """Client for USPTO Final Petition Decisions API"""

    # Constants for better readability and maintainability
    DEFAULT_LIMIT = 25
    MAX_SEARCH_LIMIT = 1000
    MAX_CONCURRENT_REQUESTS = 10

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier

    def __init__(self, api_key: Optional[str] = None):
        """Initialize FPD client with USPTO API key"""
        self.base_url = "https://api.uspto.gov/api/v1/petition/decisions"

        # Load API key with unified secure storage support
        if api_key:
            self.api_key = api_key
        else:
            # Try unified secure storage first
            try:
                from ..shared_secure_storage import get_uspto_api_key
                self.api_key = get_uspto_api_key()
            except Exception:
                # Fall back to environment variable
                pass

            # If still no key, try environment variable
            if not self.api_key:
                self.api_key = os.getenv("USPTO_API_KEY")

        if not self.api_key:
            raise ValueError("USPTO API key is required. Please provide via parameter, secure storage, or USPTO_API_KEY environment variable")

        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Configurable timeouts from environment variables (with fallbacks)
        self.default_timeout = float(os.getenv("USPTO_TIMEOUT", "30.0"))
        self.download_timeout = float(os.getenv("USPTO_DOWNLOAD_TIMEOUT", "60.0"))
        logger.info(f"Timeout configuration: default={self.default_timeout}s, download={self.download_timeout}s")

        # Connection pool limits to prevent exhaustion under high load
        self.connection_limits = httpx.Limits(
            max_connections=api_constants.DEFAULT_MAX_CONNECTIONS,  # Total connections across all hosts
            max_keepalive_connections=api_constants.DEFAULT_MAX_KEEPALIVE_CONNECTIONS,  # Persistent connections to keep alive
            keepalive_expiry=api_constants.DEFAULT_KEEPALIVE_EXPIRY_SECONDS  # Idle timeout for keep-alive connections (seconds)
        )
        logger.info(f"Connection pool limits: max={self.connection_limits.max_connections}, "
                   f"keepalive={self.connection_limits.max_keepalive_connections}")

        # Service-specific semaphores for better resource isolation
        self.uspto_semaphore = asyncio.Semaphore(10)  # USPTO API requests
        self.mistral_semaphore = asyncio.Semaphore(2)  # Mistral OCR requests (more expensive)

        # Circuit breakers for resilience
        self.uspto_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            name="USPTO_API"
        )
        self.mistral_circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30,
            name="Mistral_OCR"
        )

        # Cache manager for circuit breaker fallback
        self.cache_manager = CacheManager(
            maxsize=api_constants.DEFAULT_CACHE_SIZE,  # Cache up to 100 responses
            ttl=api_constants.DEFAULT_CACHE_TTL_SECONDS  # 10 minute TTL (longer than default for fallback purposes)
        )

        logger.info("FPD client initialized with USPTO API key, semaphores, circuit breakers, and cache")

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get status of all circuit breakers for monitoring"""
        return {
            "uspto_api": self.uspto_circuit_breaker.get_state(),
            "mistral_ocr": self.mistral_circuit_breaker.get_state()
        }

    async def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        **kwargs
    ) -> Dict[str, Any]:
        """Make HTTP request to FPD API with rate limiting and retry logic"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_id = generate_request_id()

        logger.info(f"[{request_id}] Starting {method} request to {endpoint}")

        # Use circuit breaker and USPTO-specific semaphore
        async def _execute_request():
            async with self.uspto_semaphore:
                last_exception = None

                for attempt in range(self.RETRY_ATTEMPTS):
                    try:
                        async with httpx.AsyncClient(timeout=self.default_timeout, verify=True, limits=self.connection_limits) as client:
                            if method.upper() == "POST":
                                response = await client.post(url, headers=self.headers, **kwargs)
                            else:
                                response = await client.get(url, headers=self.headers, **kwargs)

                            response.raise_for_status()
                            logger.info(f"[{request_id}] Request successful on attempt {attempt + 1}")
                            return response.json()

                    except httpx.HTTPStatusError as e:
                        # Don't retry authentication errors or client errors (4xx)
                        if e.response.status_code < 500:
                            logger.error(f"[{request_id}] API error {e.response.status_code}: {e.response.text}")
                            return format_error_response(
                                f"API error: {e.response.text}",
                                e.response.status_code,
                                request_id
                            )
                        last_exception = e

                    except httpx.TimeoutException as e:
                        last_exception = e

                    except Exception as e:
                        # Don't retry unexpected errors on final attempt
                        if attempt == self.RETRY_ATTEMPTS - 1:
                            logger.error(f"[{request_id}] Request failed: {str(e)}")
                            return format_error_response(
                                f"Request failed: {str(e)}",
                                500,
                                request_id
                            )
                        last_exception = e

                    # Calculate delay with exponential backoff and jitter
                    if attempt < self.RETRY_ATTEMPTS - 1:
                        delay = self.RETRY_DELAY * (self.RETRY_BACKOFF ** attempt)
                        # Add jitter to prevent thundering herd
                        jitter = random.uniform(0.1, 0.5)
                        total_delay = delay + jitter

                        logger.warning(
                            f"[{request_id}] Request failed on attempt {attempt + 1}/{self.RETRY_ATTEMPTS}, "
                            f"retrying in {total_delay:.2f}s: {str(last_exception)}"
                        )
                        await asyncio.sleep(total_delay)

                # All retries failed
                if isinstance(last_exception, httpx.TimeoutException):
                    logger.error(f"[{request_id}] Request timeout after {self.RETRY_ATTEMPTS} attempts")
                    return format_error_response("Request timeout - please try again", 408, request_id)
                elif isinstance(last_exception, httpx.HTTPStatusError):
                    logger.error(
                        f"[{request_id}] API error {last_exception.response.status_code} "
                        f"after {self.RETRY_ATTEMPTS} attempts"
                    )
                    return format_error_response(
                        f"API error: {last_exception.response.text}",
                        last_exception.response.status_code,
                        request_id
                    )
                else:
                    logger.error(f"[{request_id}] Request failed after {self.RETRY_ATTEMPTS} attempts: {str(last_exception)}")
                    return format_error_response(f"Request failed: {str(last_exception)}", 500, request_id)

        # Execute through circuit breaker with cache fallback
        try:
            result = await self.uspto_circuit_breaker.call(_execute_request)

            # Cache successful responses for circuit breaker fallback
            if result and not result.get("error"):
                cache_key = f"{method}_{endpoint}"
                self.cache_manager.set(cache_key, result, **kwargs)
                logger.debug(f"[{request_id}] Cached response for {cache_key}")

            return result

        except Exception as e:
            logger.error(f"[{request_id}] Circuit breaker error: {str(e)}")

            # Try cache fallback when circuit is OPEN
            if "Circuit breaker" in str(e) and "OPEN" in str(e):
                logger.warning(f"[{request_id}] Circuit OPEN - attempting cache fallback")

                cache_key = f"{method}_{endpoint}"
                cached_result = self.cache_manager.get(cache_key, **kwargs)

                if cached_result:
                    logger.info(f"[{request_id}] Serving stale cached response (circuit OPEN)")

                    # Add metadata to indicate cached/degraded response
                    cached_result = cached_result.copy()  # Don't modify original cached data
                    cached_result["_cached"] = True
                    cached_result["_circuit_open"] = True
                    cached_result["_warning"] = "Serving cached data - USPTO API temporarily unavailable"
                    cached_result["_cache_age_seconds"] = "unknown"  # Could track this if needed
                    cached_result["request_id"] = request_id

                    return cached_result
                else:
                    logger.error(f"[{request_id}] No cached fallback available for {cache_key}")

            # No cache available - return error
            return format_error_response(
                f"Service temporarily unavailable: {str(e)}",
                503,
                request_id
            )

    async def search_petitions(
        self,
        query: Optional[str] = None,
        filters: Optional[List[Dict]] = None,
        fields: Optional[List[str]] = None,
        sort: Optional[str] = None,
        offset: int = 0,
        limit: int = 25
    ) -> Dict[str, Any]:
        """
        Search petition decisions using FPD API

        Args:
            query: Search query string (supports boolean operators, wildcards)
            filters: List of filter objects with name and value
            fields: Optional list of fields to retrieve for context reduction
            sort: Sort specification (e.g., "petitionMailDate asc")
            offset: Starting position
            limit: Maximum number of results (max 1000)

        Returns:
            Dict containing search results
        """
        try:
            # Build request body
            body = {
                "pagination": {
                    "limit": min(limit, self.MAX_SEARCH_LIMIT),
                    "offset": offset
                }
            }

            # Add query if provided
            if query:
                body["q"] = query

            # Add filters if provided
            if filters:
                body["filters"] = filters

            # Add fields if provided (for context reduction)
            if fields:
                body["fields"] = fields

            # Add sort if provided
            if sort:
                # Parse sort string (e.g., "petitionMailDate asc")
                parts = sort.split()
                if len(parts) == 2:
                    body["sort"] = [{
                        "field": parts[0],
                        "order": parts[1]
                    }]

            logger.debug(f"Search request body: {json.dumps(body, indent=2)}")

            # Use POST for search as per USPTO API spec
            return await self._make_request("search", method="POST", json=body)

        except Exception as e:
            logger.error(f"Error in search_petitions: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def get_petition_by_id(
        self,
        petition_id: str,
        include_documents: bool = False
    ) -> Dict[str, Any]:
        """
        Get specific petition by UUID

        Args:
            petition_id: Petition decision record identifier (UUID)
            include_documents: Whether to include document bag

        Returns:
            Dict containing petition details
        """
        try:
            # Build query parameters
            params = {}
            if include_documents:
                params["includeDocuments"] = "true"

            # Make GET request to specific petition endpoint
            return await self._make_request(
                f"{petition_id}",
                method="GET",
                params=params
            )

        except Exception as e:
            logger.error(f"Error in get_petition_by_id: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def search_by_art_unit(
        self,
        art_unit: str,
        date_range: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Search petitions by art unit number

        Args:
            art_unit: Art unit number (e.g., "2128")
            date_range: Optional date range filter (e.g., "2020-01-01:2024-12-31")
            limit: Maximum number of results

        Returns:
            Dict containing search results
        """
        try:
            # Build query
            query = f"{QueryFieldNames.ART_UNIT}:{art_unit}"

            # Build filters for date range if provided
            filters = []
            if date_range:
                # Parse date range
                parts = date_range.split(":")
                if len(parts) == 2:
                    filters.append({
                        "field": FPDFields.PETITION_MAIL_DATE,
                        "valueFrom": parts[0],
                        "valueTo": parts[1]
                    })

            return await self.search_petitions(
                query=query,
                filters=filters if filters else None,
                limit=limit
            )

        except Exception as e:
            logger.error(f"Error in search_by_art_unit: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def search_by_application(
        self,
        application_number: str,
        include_documents: bool = False
    ) -> Dict[str, Any]:
        """
        Search petitions for specific application number

        Args:
            application_number: USPTO application number
            include_documents: Whether to include document bag

        Returns:
            Dict containing search results
        """
        try:
            # Build query
            query = f"{QueryFieldNames.APPLICATION_NUMBER}:{application_number}"

            # Build fields list
            fields = None
            if not include_documents:
                # Exclude documentBag for context reduction
                fields = [
                    FPDFields.PETITION_DECISION_RECORD_IDENTIFIER,
                    FPDFields.APPLICATION_NUMBER_TEXT,
                    FPDFields.PATENT_NUMBER,
                    FPDFields.FIRST_APPLICANT_NAME,
                    FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT,
                    FPDFields.PETITION_MAIL_DATE,
                    FPDFields.DECISION_DATE,
                    FPDFields.FINAL_DECIDING_OFFICE_NAME,
                    FPDFields.DECISION_PETITION_TYPE_CODE,
                    FPDFields.DECISION_PETITION_TYPE_CODE_DESCRIPTION_TEXT,
                    FPDFields.GROUP_ART_UNIT_NUMBER,
                    FPDFields.TECHNOLOGY_CENTER,
                    FPDFields.PROSECUTION_STATUS_CODE_DESCRIPTION_TEXT,
                    FPDFields.PETITION_ISSUE_CONSIDERED_TEXT_BAG,
                    FPDFields.RULE_BAG,
                    FPDFields.STATUTE_BAG
                ]

            return await self.search_petitions(
                query=query,
                fields=fields,
                limit=100
            )

        except Exception as e:
            logger.error(f"Error in search_by_application: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    def is_good_extraction(self, text: str) -> bool:
        """
        Determine if PyPDF2 extraction is usable or if we need Mistral OCR.

        Returns False if:
        - Text is too short (< 100 chars)
        - Too many garbled characters
        - Too much whitespace
        - Insufficient word density
        """
        if len(text) < 100:
            return False

        # Check for garbled text
        garbled_count = sum(1 for c in text if not (c.isalnum() or c.isspace() or c in '.,;:!?-()[]{}'))
        if garbled_count / len(text) > 0.3:
            return False

        # Check word density
        words = text.split()
        if len(words) < 20:
            return False

        return True

    async def extract_with_pypdf2(self, pdf_content: bytes) -> str:
        """
        Extract text using PyPDF2 (free, fast, works for text-based PDFs).

        Returns:
            Extracted text or empty string if extraction fails
        """
        try:
            import PyPDF2

            pdf_file = BytesIO(pdf_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            text_parts = []
            for page in pdf_reader.pages:
                text_parts.append(page.extract_text())

            return "\n\n".join(text_parts)
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed: {e}")
            return ""

    async def extract_with_mistral_ocr(self, pdf_content: bytes, page_count: int = 0) -> Tuple[str, float]:
        """
        Extract text using Mistral OCR API (no poppler/pdf2image required).
        Uses the same approach as Patent File Wrapper MCP.

        Args:
            pdf_content: PDF bytes
            page_count: Number of pages (for cost control)

        Returns:
            Tuple of (extracted_text, cost_usd)
        """
        # Check feature flag
        if not feature_flags.is_enabled("mistral_ocr_enabled"):
            raise ValueError("Mistral OCR feature is currently disabled")

        # Get Mistral API key from unified secure storage first, then environment variable
        mistral_api_key = None
        try:
            from ..shared_secure_storage import get_mistral_api_key
            mistral_api_key = get_mistral_api_key()
        except Exception:
            # Fall back to environment variable if secure storage fails
            pass

        # If still no key, try environment variable
        if not mistral_api_key:
            mistral_api_key = os.getenv("MISTRAL_API_KEY")

        if not mistral_api_key:
            raise ValueError("MISTRAL_API_KEY required for OCR extraction")

        mistral_base_url = "https://api.mistral.ai/v1"

        try:
            # Step 1: Upload PDF file to Mistral
            mistral_headers = {
                "Authorization": f"Bearer {mistral_api_key}",
            }

            files = {
                "file": ("document.pdf", pdf_content, "application/pdf")
            }

            data = {
                "purpose": "ocr"
            }

            async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.connection_limits) as client:
                # Upload file
                upload_response = await client.post(
                    f"{mistral_base_url}/files",
                    headers=mistral_headers,
                    files=files,
                    data=data
                )
                upload_response.raise_for_status()
                upload_data = upload_response.json()
                file_id = upload_data.get("id")

                if not file_id:
                    raise ValueError("Failed to upload file to Mistral OCR service")

                # Step 2: Process with OCR
                ocr_payload = {
                    "model": "mistral-ocr-latest",
                    "document": {
                        "type": "file",
                        "file_id": file_id
                    },
                    "pages": list(range(min(page_count, 50))) if page_count > 0 else None,  # Limit to first 50 pages for cost control
                    "include_image_base64": False  # Save tokens
                }

                # Operation-level timeout for OCR (2x download timeout for large PDFs)
                ocr_timeout = self.download_timeout * api_constants.OCR_TIMEOUT_MULTIPLIER
                try:
                    async with asyncio.timeout(ocr_timeout):
                        ocr_response = await client.post(
                            f"{mistral_base_url}/ocr",
                            headers={
                                "Authorization": f"Bearer {mistral_api_key}",
                                "Content-Type": "application/json"
                            },
                            json=ocr_payload
                        )
                        ocr_response.raise_for_status()
                        ocr_data = ocr_response.json()
                except asyncio.TimeoutError:
                    raise ValueError(f"OCR operation timed out after {ocr_timeout}s - PDF may be too large or complex")

                # Extract content from OCR response
                pages_processed = ocr_data.get("usage_info", {}).get("pages_processed", 0)
                estimated_cost = pages_processed * 0.001  # $1 per 1000 pages

                # Combine all page content
                extracted_content = []
                for page in ocr_data.get("pages", []):
                    page_markdown = page.get("markdown", "")
                    if page_markdown.strip():
                        extracted_content.append(f"=== PAGE {page.get('index', 0) + 1} ===\n{page_markdown}")

                full_content = "\n\n".join(extracted_content)

                logger.info(f"Mistral OCR extracted {pages_processed} pages, cost: ${estimated_cost:.4f}")

                return full_content, estimated_cost

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Mistral API authentication failed - check MISTRAL_API_KEY")
            elif e.response.status_code == 402:
                raise ValueError("Mistral API payment required - insufficient credits")
            else:
                raise ValueError(f"Mistral API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            logger.error(f"Mistral OCR extraction failed: {e}")
            raise

    async def extract_document_content_hybrid(
        self,
        petition_id: str,
        document_identifier: str,
        auto_optimize: bool = True
    ) -> Dict[str, Any]:
        """
        Extract text from petition PDFs with hybrid approach.

        Workflow:
        1. Fetch petition details to get document metadata
        2. Download PDF content from proxy server
        3. If auto_optimize=True:
           a. Try PyPDF2 extraction (free)
           b. Check extraction quality
           c. If poor quality, fallback to Mistral OCR
        4. If auto_optimize=False: Use Mistral OCR directly
        5. Return extracted text with cost information
        """
        request_id = generate_request_id()

        # Check feature flags
        if not feature_flags.is_enabled("ocr_enabled"):
            logger.warning(f"[{request_id}] OCR feature disabled by feature flag")
            return format_error_response(
                "OCR feature is currently disabled",
                503,
                request_id
            )

        try:
            # Get petition details to verify document exists
            petition_data = await self.get_petition_by_id(petition_id, include_documents=True)

            if "error" in petition_data:
                return petition_data

            # Find document in documentBag - access it from the correct location
            petition_records = petition_data.get(FPDFields.PETITION_DECISION_DATA_BAG, [])
            if not petition_records:
                return format_error_response(
                    f"Petition {petition_id} not found",
                    404,
                    request_id
                )

            document_bag = petition_records[0].get(FPDFields.DOCUMENT_BAG, [])
            document = None
            for doc in document_bag:
                if doc.get(FPDFields.DOCUMENT_IDENTIFIER) == document_identifier:
                    document = doc
                    break

            if not document:
                return format_error_response(
                    f"Document {document_identifier} not found in petition {petition_id}",
                    404,
                    request_id
                )

            # Get document metadata
            document_code = document.get(FPDFields.DOCUMENT_CODE, "UNKNOWN")
            page_count = document.get(FPDFields.PAGE_COUNT, 0)

            # Extract direct download URL from document metadata (for proxy registration)
            # The proxy needs this URL to fetch PDFs from USPTO API on behalf of users
            # Find the PDF download option in downloadOptionBag
            download_options = document.get(FPDFields.DOWNLOAD_OPTION_BAG, [])
            direct_download_url = None
            for option in download_options:
                if option.get(FPDFields.MIME_TYPE_IDENTIFIER) == 'PDF':
                    direct_download_url = option.get(FPDFields.DOWNLOAD_URL)
                    break

            if not direct_download_url:
                # Try getting download URL directly from document (still for proxy registration)
                direct_download_url = document.get(FPDFields.DOWNLOAD_URL, "")

            # Download PDF from proxy server
            # Check for centralized proxy first, then local FPD proxy
            centralized_port = os.getenv('CENTRALIZED_PROXY_PORT', '').lower()
            pdf_content = None

            if centralized_port and centralized_port != 'none':
                # Convert to int for URL formatting
                proxy_port = int(centralized_port)
                logger.info(f"[{request_id}] Using centralized proxy on port {proxy_port}")

                # Register document with centralized proxy before downloading
                try:
                    from ..shared.internal_auth import mcp_auth
                    from ..proxy.server import generate_enhanced_filename

                    register_url = f"http://localhost:{proxy_port}/register-fpd-document"

                    # Extract metadata needed for token and filename generation
                    petition_mail_date = petition_records[0].get(FPDFields.PETITION_MAIL_DATE)
                    app_number = petition_records[0].get(FPDFields.APPLICATION_NUMBER_TEXT, "")
                    patent_number = petition_records[0].get(FPDFields.PATENT_NUMBER)
                    doc_description = document.get(FPDFields.DOCUMENT_CODE_DESCRIPTION_TEXT)

                    # Create JWT access token (TTL is 10 minutes, hardcoded in internal_auth.py)
                    access_token = mcp_auth.create_document_access_token(
                        petition_id=petition_id,
                        document_identifier=document_identifier,
                        application_number=app_number
                    )

                    # Generate enhanced filename using proper format
                    enhanced_filename = generate_enhanced_filename(
                        petition_mail_date=petition_mail_date,
                        app_number=app_number or "UNKNOWN",
                        patent_number=patent_number,
                        document_description=doc_description,
                        document_code=document_code,
                        max_desc_length=40
                    )

                    registration_data = {
                        "source": "fpd",  # Required by PFW proxy
                        "petition_id": petition_id,
                        "document_identifier": document_identifier,
                        "download_url": direct_download_url,
                        "access_token": access_token,
                        "application_number": app_number,
                        "enhanced_filename": enhanced_filename
                    }

                    # PFW validates JWT token in request body, no auth header needed
                    async with httpx.AsyncClient(timeout=30.0, limits=self.connection_limits) as reg_client:
                        response_reg = await reg_client.post(
                            register_url,
                            json=registration_data
                        )

                        if response_reg.status_code == 200:
                            logger.info(f"[{request_id}] Successfully registered FPD document with centralized proxy")
                        else:
                            logger.warning(f"[{request_id}] Failed to register document with centralized proxy: {response_reg.status_code}")

                except Exception as e:
                    logger.warning(f"[{request_id}] Failed to register document with centralized proxy: {e}")
                    # Continue anyway - will try download and may fail if not registered

                # Try downloading from centralized proxy
                download_url = f"http://localhost:{proxy_port}/download/{petition_id}/{document_identifier}"
                logger.info(f"[{request_id}] Attempting PDF download from centralized proxy: {download_url}")

                try:
                    async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.connection_limits) as client:
                        pdf_response = await client.get(download_url)
                        pdf_response.raise_for_status()
                        pdf_content = pdf_response.content
                        logger.info(f"[{request_id}] Downloaded {len(pdf_content)} bytes from centralized proxy")
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        # Centralized proxy doesn't have FPD routes yet - fallback to local FPD proxy
                        logger.warning(f"[{request_id}] Centralized proxy doesn't support FPD routes yet (404)")
                        logger.info(f"[{request_id}] Falling back to local FPD proxy")
                        pdf_content = None  # Will trigger fallback below
                    else:
                        # Other HTTP error - re-raise
                        raise
                except Exception as e:
                    # Network or other errors - log and fallback to local proxy
                    logger.warning(f"[{request_id}] Centralized proxy download failed: {e}")
                    logger.info(f"[{request_id}] Falling back to local FPD proxy")
                    pdf_content = None  # Will trigger fallback below

            # Use local FPD proxy if centralized proxy not configured or failed
            if pdf_content is None:
                # Check FPD_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
                # Handle 'none' sentinel value
                port_str = os.getenv("FPD_PROXY_PORT") or os.getenv("PROXY_PORT") or "8081"
                local_proxy_port = "8081" if port_str.lower() == "none" else port_str
                logger.info(f"[{request_id}] Using local FPD proxy on port {local_proxy_port}")

                download_url = f"http://localhost:{local_proxy_port}/download/{petition_id}/{document_identifier}"
                logger.info(f"[{request_id}] Downloading PDF from local FPD proxy: {download_url}")

                async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.connection_limits) as client:
                    pdf_response = await client.get(download_url)
                    pdf_response.raise_for_status()
                    pdf_content = pdf_response.content
                    logger.info(f"[{request_id}] Downloaded {len(pdf_content)} bytes from local FPD proxy")

            # Extract text based on auto_optimize setting
            extraction_result = {
                "success": True,
                "document_code": document_code,
                "page_count": page_count,
                "request_id": request_id
            }

            if auto_optimize:
                # Try PyPDF2 first
                logger.info(f"[{request_id}] Attempting PyPDF2 extraction (free)")
                pypdf_text = await self.extract_with_pypdf2(pdf_content)

                if self.is_good_extraction(pypdf_text):
                    # PyPDF2 worked!
                    logger.info(f"[{request_id}] PyPDF2 extraction successful ({len(pypdf_text)} chars)")
                    extraction_result.update({
                        "extracted_content": pypdf_text,
                        "extraction_method": "PyPDF2",
                        "processing_cost_usd": 0.0,
                        "cost_breakdown": "Free PyPDF2 extraction",
                        "auto_optimization": "PyPDF2 succeeded - no OCR needed"
                    })
                else:
                    # PyPDF2 failed - fallback to Mistral OCR
                    logger.info(f"[{request_id}] PyPDF2 extraction poor quality, falling back to Mistral OCR")
                    mistral_text, cost = await self.extract_with_mistral_ocr(pdf_content, page_count)

                    logger.info(f"[{request_id}] Mistral OCR extraction successful ({len(mistral_text)} chars, ${cost:.4f})")
                    extraction_result.update({
                        "extracted_content": mistral_text,
                        "extraction_method": "Mistral OCR (mistral-ocr-latest)",
                        "processing_cost_usd": round(cost, 4),
                        "cost_breakdown": f"${cost:.4f} for {page_count} pages at $0.001/page",
                        "auto_optimization": "PyPDF2 failed - Mistral OCR used"
                    })
            else:
                # Use Mistral OCR directly
                logger.info(f"[{request_id}] Using Mistral OCR directly (auto_optimize=False)")
                mistral_text, cost = await self.extract_with_mistral_ocr(pdf_content, page_count)

                logger.info(f"[{request_id}] Mistral OCR extraction successful ({len(mistral_text)} chars, ${cost:.4f})")
                extraction_result.update({
                    "extracted_content": mistral_text,
                    "extraction_method": "Mistral OCR (mistral-ocr-latest)",
                    "processing_cost_usd": round(cost, 4),
                    "cost_breakdown": f"${cost:.4f} for {page_count} pages at $0.001/page",
                    "auto_optimization": "Disabled - Mistral OCR used directly"
                })

            return extraction_result

        except ValueError as e:
            # MISTRAL_API_KEY missing or other validation error
            logger.error(f"[{request_id}] Validation error: {str(e)}")
            return format_error_response(
                f"{str(e)}. PyPDF2 extraction failed - document may be scanned. To enable OCR, configure MISTRAL_API_KEY.",
                400,
                request_id
            )
        except Exception as e:
            logger.error(f"[{request_id}] Error extracting document content: {str(e)}")
            return format_error_response(
                f"Failed to extract document content: {str(e)}",
                500,
                request_id
            )
