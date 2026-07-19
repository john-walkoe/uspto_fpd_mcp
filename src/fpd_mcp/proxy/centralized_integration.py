"""
Centralized proxy integration for FPD document registration with PFW.

This module handles registration of FPD petition documents with the
centralized USPTO PFW proxy for unified download infrastructure across
MCPs (persistent links, unified rate limiting, cross-MCP sharing).

The centralized proxy location is configured by:
1. CENTRALIZED_PROXY_URL — full base URL. Required whenever PFW is not on
   this host's localhost (Docker: http://pfw:8080; remote: an external
   HTTPS base such as the deployment's published PFW proxy).
2. CENTRALIZED_PROXY_PORT — legacy port-only config, resolved against
   localhost.
"""

import os
import re
from typing import Optional

import httpx

from ..shared.internal_auth import mcp_auth
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)


def get_centralized_base_url() -> Optional[str]:
    """
    Resolve the base URL of the PFW centralized proxy.

    Returns:
        Base URL string without trailing slash, or None if centralized
        proxying is not configured ("none"/unset).
    """
    url = os.getenv("CENTRALIZED_PROXY_URL", "").strip()
    if url and url.lower() != "none":
        if not re.match(r"^https?://", url):
            logger.warning(f"Invalid CENTRALIZED_PROXY_URL (must be http/https): {url}")
            return None
        return url.rstrip("/")

    port_env = os.getenv("CENTRALIZED_PROXY_PORT", "none").lower()
    if port_env == "none" or not port_env:
        return None
    try:
        return f"http://localhost:{int(port_env)}"
    except ValueError:
        logger.warning(f"Invalid CENTRALIZED_PROXY_PORT: {port_env}")
        return None


async def register_with_centralized_proxy(
    petition_id: str,
    document_identifier: str,
    download_url: str,
    application_number: Optional[str] = None,
    enhanced_filename: Optional[str] = None,
) -> Optional[str]:
    """
    Register an FPD petition document with the PFW centralized proxy.

    Args:
        petition_id: Petition decision record identifier (UUID)
        document_identifier: Document ID from documentBag
        download_url: USPTO API download URL for the PDF
        application_number: Application number if available
        enhanced_filename: Human-readable filename

    Returns:
        Browser-usable download URL returned by PFW (built from PFW's own
        PFW_PROXY_BASE_URL, so it is correct behind Docker/reverse proxies),
        or None if registration failed or is not configured.
    """
    centralized_base_url = get_centralized_base_url()
    if not centralized_base_url:
        logger.debug(
            "Centralized proxy not configured "
            "(set CENTRALIZED_PROXY_URL or CENTRALIZED_PROXY_PORT)"
        )
        return None

    try:
        # Scoped JWT — PFW validates expected_service="fpd-mcp" and that the
        # token metadata matches the registered document
        access_token = mcp_auth.create_document_access_token(
            petition_id=petition_id,
            document_identifier=document_identifier,
            application_number=application_number,
        )
    except Exception as e:
        logger.warning(f"Failed to generate access token: {type(e).__name__}")
        return None

    registration_url = f"{centralized_base_url}/register-fpd-document"
    payload = {
        "source": "fpd",
        "petition_id": petition_id,
        "document_identifier": document_identifier,
        "download_url": download_url,
        "access_token": access_token,
        "application_number": application_number,
        "enhanced_filename": enhanced_filename,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    logger.info(
        f"Attempting centralized registration: petition {petition_id}, "
        f"doc {document_identifier} to {centralized_base_url}"
    )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(registration_url, json=payload)

            if response.status_code == 200:
                pfw_url = response.json().get("download_url")
                if pfw_url:
                    # Never log the URL — persistent links are credentials
                    logger.info("✅ Centralized registration successful")
                    return pfw_url
                logger.warning("Registration succeeded but no download URL in response")
                return None

            # Status only — response bodies stay out of logs
            logger.warning(f"Centralized registration failed: HTTP {response.status_code}")
            return None

    except httpx.TimeoutException:
        logger.warning("Centralized proxy registration timed out (5s)")
        return None
    except httpx.ConnectError:
        logger.debug("Centralized proxy not available (connection refused)")
        return None
    except Exception as e:
        logger.warning(f"Centralized registration error: {type(e).__name__}")
        return None
