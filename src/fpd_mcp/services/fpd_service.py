"""
FPD Service - Main business logic service with dependency injection

This service encapsulates the core FPD functionality and manages dependencies
for API client, field manager, and other components. Implements dependency
injection pattern to improve testability and maintainability.

Phase 6B note: search_petitions_minimal/balanced previously carried a
CacheManager-backed response cache and StructuredLogger/PerformanceTimer
instrumentation that main.py's inline tool implementations never had — a
drift from the actual (never-cached, plain-logged) production behavior.
Per the Phase 6B wiring plan, that drift has been removed so this class is
now the single, behavior-preserving implementation the search/details tools
call into (moving the inline logic here rather than adopting the cache).
"""

from typing import Any, Dict, Optional
from ..api.fpd_client import FPDClient
from ..config.field_manager import FieldManager
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)


class FPDService:
    """Main service for Final Petition Decisions functionality with dependency injection"""

    def __init__(self, api_client: FPDClient, field_manager: FieldManager):
        """
        Initialize FPD service with injected dependencies

        Args:
            api_client: FPDClient instance for API communication
            field_manager: FieldManager instance for field configuration
        """
        self.api_client = api_client
        self.field_manager = field_manager
        logger.info("FPDService initialized with injected dependencies")

    async def _search(
        self, query: str, *, field_set: str, limit: int, offset: int
    ) -> Dict[str, Any]:
        """One search implementation; the tier is a parameter.

        F-D3 (design-pattern-implmentation): search_petitions_minimal and
        search_petitions_balanced were 35 duplicated lines differing only by
        the literal "petitions_minimal" / "petitions_balanced".
        """
        result = await self.api_client.search_petitions(
            query=query,
            fields=self.field_manager.get_fields(field_set),
            limit=limit,
            offset=offset,
        )
        if "error" in result:
            return result
        return self.field_manager.filter_response(result, field_set)

    async def search_petitions_minimal(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Minimal-tier petition search (8 fields, maximum context reduction)."""
        return await self._search(
            query, field_set="petitions_minimal", limit=limit, offset=offset
        )

    async def search_petitions_balanced(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Balanced-tier petition search (18 fields)."""
        return await self._search(
            query, field_set="petitions_balanced", limit=limit, offset=offset
        )

    async def search_by_art_unit(
        self,
        art_unit: str,
        date_range: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Search petitions by art unit

        Args:
            art_unit: Art unit number
            date_range: Optional date range filter
            limit: Number of results to return
            offset: Starting position, for paging past `limit`

        Returns:
            Search results for the art unit
        """
        result = await self.api_client.search_by_art_unit(
            art_unit=art_unit,
            date_range=date_range,
            limit=limit,
            offset=offset,
        )

        # Filter response using balanced field set
        if "error" not in result:
            result = self.field_manager.filter_response(result, "petitions_balanced")

        return result

    async def search_by_application(
        self,
        application_number: str,
        include_documents: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Search petitions by application number

        Args:
            application_number: Application number to search
            include_documents: Include documentBag in the response; when
                True the response is returned unfiltered (full data), matching
                the tool-level semantics (a caller who explicitly asked for
                documents gets the complete record, not the balanced subset).
            limit: Maximum number of petition records to return
            offset: Starting position, for paging past `limit`

        Returns:
            All petitions for the application

        D-3: the requested projection is resolved HERE, from the same
        `petitions_balanced` set in `field_configs.yaml` that this method
        already filters the response against. The client used to carry its own
        divergent 16-field literal, so this tool ignored the documented
        customization surface and asked USPTO for two fewer fields than the
        balanced set defines.
        """
        result = await self.api_client.search_by_application(
            application_number=application_number,
            include_documents=include_documents,
            limit=limit,
            offset=offset,
            fields=(
                None if include_documents
                else self.field_manager.get_fields("petitions_balanced")
            ),
        )

        # Filter response using balanced field set (unless documents requested)
        if "error" not in result:
            if include_documents:
                # No field projection here: filtering to the balanced set would
                # strip the documentBag the caller explicitly asked for. Say so
                # rather than letting context_info silently disappear on this
                # one path — its absence otherwise reads as "no filtering
                # information available".
                result["context_info"] = {
                    "fields_used": [],
                    "field_set": "unfiltered",
                    "original_field_count": None,
                    "filtered_field_count": None,
                    "context_reduction": "0%",
                    "note": (
                        "include_documents=True returns the full petition "
                        "record with its documentBag; no field set was "
                        "applied. Call without include_documents for the "
                        "petitions_balanced projection."
                    ),
                }
            else:
                result = self.field_manager.filter_response(result, "petitions_balanced")

        return result

    async def get_petition_details(
        self,
        petition_id: str,
        include_documents: bool = True
    ) -> Dict[str, Any]:
        """
        Get detailed petition information

        Args:
            petition_id: Petition UUID
            include_documents: Whether to include document bag

        Returns:
            Detailed petition information
        """
        return await self.api_client.get_petition_by_id(
            petition_id=petition_id,
            include_documents=include_documents
        )

    async def extract_document_content(
        self,
        petition_id: str,
        document_identifier: str,
        auto_optimize: bool = True
    ) -> Dict[str, Any]:
        """
        Extract text content from petition document

        Args:
            petition_id: Petition UUID
            document_identifier: Document identifier
            auto_optimize: Use hybrid extraction (pypdf + OCR fallback)

        Returns:
            Extracted document content
        """
        return await self.api_client.extract_document_content_hybrid(
            petition_id=petition_id,
            document_identifier=document_identifier,
            auto_optimize=auto_optimize
        )

    def get_context_settings(self) -> Dict[str, int]:
        """
        Get context management settings

        Returns:
            Context reduction settings
        """
        return self.field_manager.get_context_settings()

