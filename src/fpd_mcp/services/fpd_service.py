"""
FPD Service - Main business logic service with dependency injection

This service encapsulates the core FPD functionality and manages dependencies
for API client, field manager, and other components. Implements dependency
injection pattern to improve testability and maintainability.
"""

import logging
from typing import Dict, Any, Optional
from ..api.fpd_client import FPDClient
from ..config.field_manager import FieldManager
from ..shared.cache import CacheManager, cached_method
from ..shared.structured_logging import StructuredLogger, PerformanceTimer

logger = logging.getLogger(__name__)


class FPDService:
    """Main service for Final Petition Decisions functionality with dependency injection"""
    
    def __init__(self, api_client: FPDClient, field_manager: FieldManager, cache_manager: Optional[CacheManager] = None):
        """
        Initialize FPD service with injected dependencies
        
        Args:
            api_client: FPDClient instance for API communication
            field_manager: FieldManager instance for field configuration
            cache_manager: Optional cache manager for search results (defaults to 5min TTL)
        """
        self.api_client = api_client
        self.field_manager = field_manager
        self.cache_manager = cache_manager or CacheManager(maxsize=100, ttl=300)  # 5 minutes default
        self.structured_logger = StructuredLogger("fpd_service")
        logger.info("FPDService initialized with injected dependencies and caching")
    
    async def search_petitions_minimal(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Perform minimal petition search with context reduction and caching
        
        Args:
            query: Search query
            limit: Number of results to return
            offset: Offset for pagination
            
        Returns:
            Filtered search results
        """
        with PerformanceTimer(self.structured_logger, "search_petitions_minimal", {"query_length": len(query), "limit": limit, "offset": offset}):
            # Check cache first
            cache_key_args = (query, limit, offset)
            cached_result = self.cache_manager.get("search_petitions_minimal", *cache_key_args)
            if cached_result is not None:
                self.structured_logger.log_cache_event(
                    cache_key=str(hash(cache_key_args)),
                    hit=True,
                    method_name="search_petitions_minimal",
                    ttl_seconds=300
                )
                return cached_result
            
            # Log cache miss
            self.structured_logger.log_cache_event(
                cache_key=str(hash(cache_key_args)),
                hit=False,
                method_name="search_petitions_minimal"
            )
            
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
            
            # Cache successful results
            self.cache_manager.set("search_petitions_minimal", filtered_result, *cache_key_args)
            
            return filtered_result
    
    async def search_petitions_balanced(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Perform balanced petition search with more fields and caching
        
        Args:
            query: Search query
            limit: Number of results to return
            offset: Offset for pagination
            
        Returns:
            Filtered search results
        """
        # Check cache first
        cache_key_args = (query, limit, offset)
        cached_result = self.cache_manager.get("search_petitions_balanced", *cache_key_args)
        if cached_result is not None:
            logger.debug("Cache hit for balanced search")
            return cached_result
        
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
        
        # Cache successful results
        self.cache_manager.set("search_petitions_balanced", filtered_result, *cache_key_args)
        
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
        application_number: str
    ) -> Dict[str, Any]:
        """
        Search petitions by application number
        
        Args:
            application_number: Application number to search
            
        Returns:
            All petitions for the application
        """
        result = await self.api_client.search_by_application(application_number)
        
        # Filter response using balanced field set
        if "error" not in result:
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
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring
        
        Returns:
            Cache statistics including hit rate, size, etc.
        """
        return self.cache_manager.get_stats()
    
    def clear_cache(self) -> None:
        """Clear all cached search results"""
        self.cache_manager.clear()
        logger.info("FPDService cache cleared")