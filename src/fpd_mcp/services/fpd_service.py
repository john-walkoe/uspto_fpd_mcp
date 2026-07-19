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

    async def search_petitions_minimal(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Perform minimal petition search with context reduction

        Args:
            query: Search query
            limit: Number of results to return
            offset: Offset for pagination

        Returns:
            Filtered search results
        """
        # Get minimal field set
        fields = self.field_manager.get_fields("petitions_minimal")

        # Perform search
        result = await self.api_client.search_petitions(
            query=query,
            fields=fields,
            limit=limit,
            offset=offset
        )

        # Check for errors
        if "error" in result:
            return result

        # Filter response using field manager
        filtered_result = self.field_manager.filter_response(result, "petitions_minimal")

        return filtered_result

    async def search_petitions_balanced(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Perform balanced petition search with more fields

        Args:
            query: Search query
            limit: Number of results to return
            offset: Offset for pagination

        Returns:
            Filtered search results
        """
        # Get balanced field set
        fields = self.field_manager.get_fields("petitions_balanced")

        # Perform search
        result = await self.api_client.search_petitions(
            query=query,
            fields=fields,
            limit=limit,
            offset=offset
        )

        # Check for errors
        if "error" in result:
            return result

        # Filter response using field manager
        filtered_result = self.field_manager.filter_response(result, "petitions_balanced")

        return filtered_result

    async def search_by_art_unit(
        self,
        art_unit: str,
        date_range: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Search petitions by art unit

        Args:
            art_unit: Art unit number
            date_range: Optional date range filter
            limit: Number of results to return

        Returns:
            Search results for the art unit
        """
        result = await self.api_client.search_by_art_unit(
            art_unit=art_unit,
            date_range=date_range,
            limit=limit
        )

        # Filter response using balanced field set
        if "error" not in result:
            result = self.field_manager.filter_response(result, "petitions_balanced")

        return result

    async def search_by_application(
        self,
        application_number: str,
        include_documents: bool = False
    ) -> Dict[str, Any]:
        """
        Search petitions by application number

        Args:
            application_number: Application number to search
            include_documents: Include documentBag in the response; when
                True the response is returned unfiltered (full data), matching
                the tool-level semantics (a caller who explicitly asked for
                documents gets the complete record, not the balanced subset).

        Returns:
            All petitions for the application
        """
        result = await self.api_client.search_by_application(
            application_number=application_number,
            include_documents=include_documents,
        )

        # Filter response using balanced field set (unless documents requested)
        if "error" not in result and not include_documents:
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
            auto_optimize: Use hybrid extraction (PyPDF2 + OCR fallback)

        Returns:
            Extracted document content
        """
        return await self.api_client.extract_document_content_hybrid(
            petition_id=petition_id,
            document_identifier=document_identifier,
            auto_optimize=auto_optimize
        )

    def get_available_field_sets(self) -> Dict[str, Dict]:
        """
        Get all available field sets from field manager

        Returns:
            Dictionary of field sets and their configurations
        """
        return self.field_manager.get_predefined_sets()

    def get_context_settings(self) -> Dict[str, int]:
        """
        Get context management settings

        Returns:
            Context reduction settings
        """
        return self.field_manager.get_context_settings()

