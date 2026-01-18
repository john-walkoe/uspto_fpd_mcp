"""
Health check system for monitoring application health

Provides comprehensive health checks for all system components including
API connectivity, circuit breaker status, cache health, and dependencies.
"""

import asyncio
import time
from typing import Dict, Any, List, Optional
from enum import Enum
from ..api.fpd_client import FPDClient
from ..config.field_manager import FieldManager
from ..shared.cache import CacheManager
from ..shared.structured_logging import StructuredLogger
from .unified_logging import get_logger

logger = get_logger(__name__)


class HealthStatus(Enum):
    """Health check status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheck:
    """Individual health check result"""

    def __init__(
        self,
        name: str,
        status: HealthStatus,
        message: str,
        response_time_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.status = status
        self.message = message
        self.response_time_ms = response_time_ms
        self.details = details or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert health check to dictionary"""
        result = {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp
        }

        if self.response_time_ms is not None:
            result["response_time_ms"] = self.response_time_ms

        if self.details:
            result["details"] = self.details

        return result


class HealthChecker:
    """Comprehensive health check system"""

    def __init__(
        self,
        api_client: Optional[FPDClient] = None,
        field_manager: Optional[FieldManager] = None,
        cache_manager: Optional[CacheManager] = None,
        structured_logger: Optional[StructuredLogger] = None
    ):
        """
        Initialize health checker

        Args:
            api_client: FPD API client for connectivity checks
            field_manager: Field manager for configuration checks
            cache_manager: Cache manager for cache health checks
            structured_logger: Structured logger for health events
        """
        self.api_client = api_client
        self.field_manager = field_manager
        self.cache_manager = cache_manager
        self.structured_logger = structured_logger or StructuredLogger("health_checker")

    async def check_api_connectivity(self) -> HealthCheck:
        """Check USPTO API connectivity"""
        start_time = time.time()

        try:
            if not self.api_client:
                return HealthCheck(
                    name="api_connectivity",
                    status=HealthStatus.UNHEALTHY,
                    message="API client not configured"
                )

            # Try a minimal API call to test connectivity
            result = await self.api_client.search_petitions(
                query="*",
                limit=1,
                offset=0
            )

            response_time_ms = (time.time() - start_time) * 1000

            if "error" in result:
                return HealthCheck(
                    name="api_connectivity",
                    status=HealthStatus.UNHEALTHY,
                    message=f"API error: {result.get('error', 'Unknown error')}",
                    response_time_ms=response_time_ms,
                    details={"error_details": result}
                )

            return HealthCheck(
                name="api_connectivity",
                status=HealthStatus.HEALTHY,
                message="API connectivity OK",
                response_time_ms=response_time_ms,
                details={"result_count": result.get("recordTotalQuantity", 0)}
            )

        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            return HealthCheck(
                name="api_connectivity",
                status=HealthStatus.UNHEALTHY,
                message=f"API connectivity failed: {str(e)}",
                response_time_ms=response_time_ms,
                details={"exception": str(e)}
            )

    def check_circuit_breakers(self) -> HealthCheck:
        """Check circuit breaker status"""
        try:
            if not self.api_client:
                return HealthCheck(
                    name="circuit_breakers",
                    status=HealthStatus.UNHEALTHY,
                    message="API client not configured"
                )

            breaker_status = self.api_client.get_circuit_breaker_status()

            # Check if any circuit breakers are open
            open_breakers = []
            degraded_breakers = []

            for breaker_name, status in breaker_status.items():
                if status["state"] == "open":
                    open_breakers.append(breaker_name)
                elif status["state"] == "half_open":
                    degraded_breakers.append(breaker_name)

            if open_breakers:
                return HealthCheck(
                    name="circuit_breakers",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Circuit breakers open: {', '.join(open_breakers)}",
                    details=breaker_status
                )
            elif degraded_breakers:
                return HealthCheck(
                    name="circuit_breakers",
                    status=HealthStatus.DEGRADED,
                    message=f"Circuit breakers in recovery: {', '.join(degraded_breakers)}",
                    details=breaker_status
                )
            else:
                return HealthCheck(
                    name="circuit_breakers",
                    status=HealthStatus.HEALTHY,
                    message="All circuit breakers closed",
                    details=breaker_status
                )

        except Exception as e:
            return HealthCheck(
                name="circuit_breakers",
                status=HealthStatus.UNHEALTHY,
                message=f"Circuit breaker check failed: {str(e)}",
                details={"exception": str(e)}
            )

    def check_cache_health(self) -> HealthCheck:
        """Check cache system health"""
        try:
            if not self.cache_manager:
                return HealthCheck(
                    name="cache",
                    status=HealthStatus.DEGRADED,
                    message="Cache manager not configured - caching disabled"
                )

            cache_stats = self.cache_manager.get_stats()

            # Determine health based on cache statistics
            if cache_stats.get("cache_type") == "TTLCache":
                current_size = cache_stats.get("current_size", 0)
                max_size = cache_stats.get("max_size", 100)
                utilization = (current_size / max_size) * 100 if max_size > 0 else 0

                if utilization > 90:
                    status = HealthStatus.DEGRADED
                    message = f"Cache near capacity: {utilization:.1f}% full"
                else:
                    status = HealthStatus.HEALTHY
                    message = f"Cache healthy: {utilization:.1f}% full"
            else:
                # SimpleCache
                valid_items = cache_stats.get("valid_items", 0)
                total_items = cache_stats.get("total_items", 0)

                if total_items > 0:
                    valid_ratio = (valid_items / total_items) * 100
                    if valid_ratio < 50:
                        status = HealthStatus.DEGRADED
                        message = f"Many expired items in cache: {valid_ratio:.1f}% valid"
                    else:
                        status = HealthStatus.HEALTHY
                        message = f"Cache healthy: {valid_ratio:.1f}% valid items"
                else:
                    status = HealthStatus.HEALTHY
                    message = "Cache empty but healthy"

            return HealthCheck(
                name="cache",
                status=status,
                message=message,
                details=cache_stats
            )

        except Exception as e:
            return HealthCheck(
                name="cache",
                status=HealthStatus.UNHEALTHY,
                message=f"Cache health check failed: {str(e)}",
                details={"exception": str(e)}
            )

    def check_configuration(self) -> HealthCheck:
        """Check configuration health"""
        try:
            if not self.field_manager:
                return HealthCheck(
                    name="configuration",
                    status=HealthStatus.UNHEALTHY,
                    message="Field manager not configured"
                )

            # Check if field sets are available
            field_sets = self.field_manager.get_predefined_sets()
            required_sets = ["petitions_minimal", "petitions_balanced"]

            missing_sets = []
            for required_set in required_sets:
                if required_set not in field_sets:
                    missing_sets.append(required_set)

            if missing_sets:
                return HealthCheck(
                    name="configuration",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Missing required field sets: {', '.join(missing_sets)}",
                    details={"available_sets": list(field_sets.keys())}
                )

            # Check field set completeness
            minimal_fields = field_sets["petitions_minimal"].get("fields", [])
            balanced_fields = field_sets["petitions_balanced"].get("fields", [])

            if len(minimal_fields) < 5:
                return HealthCheck(
                    name="configuration",
                    status=HealthStatus.DEGRADED,
                    message="Minimal field set has too few fields",
                    details={"minimal_field_count": len(minimal_fields)}
                )

            return HealthCheck(
                name="configuration",
                status=HealthStatus.HEALTHY,
                message="Configuration healthy",
                details={
                    "field_sets": len(field_sets),
                    "minimal_fields": len(minimal_fields),
                    "balanced_fields": len(balanced_fields)
                }
            )

        except Exception as e:
            return HealthCheck(
                name="configuration",
                status=HealthStatus.UNHEALTHY,
                message=f"Configuration check failed: {str(e)}",
                details={"exception": str(e)}
            )

    async def run_all_checks(self) -> Dict[str, Any]:
        """Run all health checks and return comprehensive status"""
        start_time = time.time()

        # Run all health checks
        checks = await asyncio.gather(
            self.check_api_connectivity(),
            asyncio.create_task(asyncio.coroutine(lambda: self.check_circuit_breakers)()),
            asyncio.create_task(asyncio.coroutine(lambda: self.check_cache_health)()),
            asyncio.create_task(asyncio.coroutine(lambda: self.check_configuration)()),
            return_exceptions=True
        )

        # Convert results to health checks
        health_checks = []
        for check in checks:
            if isinstance(check, HealthCheck):
                health_checks.append(check)
            elif isinstance(check, Exception):
                health_checks.append(HealthCheck(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check failed: {str(check)}"
                ))

        # Determine overall status
        overall_status = HealthStatus.HEALTHY
        unhealthy_count = 0
        degraded_count = 0

        for check in health_checks:
            if check.status == HealthStatus.UNHEALTHY:
                unhealthy_count += 1
                overall_status = HealthStatus.UNHEALTHY
            elif check.status == HealthStatus.DEGRADED:
                degraded_count += 1
                if overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED

        total_time_ms = (time.time() - start_time) * 1000

        result = {
            "status": overall_status.value,
            "timestamp": time.time(),
            "total_check_time_ms": total_time_ms,
            "summary": {
                "total_checks": len(health_checks),
                "healthy": len([c for c in health_checks if c.status == HealthStatus.HEALTHY]),
                "degraded": degraded_count,
                "unhealthy": unhealthy_count
            },
            "checks": [check.to_dict() for check in health_checks]
        }

        # Log health check result
        self.structured_logger.log_health_check(
            component="overall_system",
            status=overall_status.value,
            details=result["summary"],
            response_time_ms=total_time_ms
        )

        return result
