"""
Reusable Error Handling Decorators

This module provides decorators for consistent error handling across the codebase,
eliminating repetitive try/except boilerplate.

Fixes Code Duplication:
- Eliminates ~100 lines of repeated try/except patterns
- Consolidates error handling logic from:
  * secure_storage.py
  * shared_secure_storage.py
  * config/field_manager.py
  * api/fpd_client.py

Benefits:
- Consistent error handling behavior
- Reduced boilerplate code
- Easier to modify error handling globally
- Automatic logging of errors
- Type hints for better IDE support

Usage:
    from fpd_mcp.shared.error_decorators import safe_operation, safe_async_operation

    # Synchronous function
    @safe_operation(default_return=False, operation_name="store_api_key")
    def store_key(key: str) -> bool:
        # Your implementation (no try/except needed)
        save_to_file(key)
        return True

    # Async function
    @safe_async_operation(default_return=None, log_error=True)
    async def fetch_data(url: str) -> Optional[dict]:
        # Your implementation
        response = await httpx.get(url)
        return response.json()

    # With custom error handler
    @safe_operation(default_return=[], error_handler=lambda e: print(f"Error: {e}"))
    def get_items() -> List[str]:
        return load_items_from_db()
"""

import logging
from functools import wraps
from typing import Any, Callable, Optional, TypeVar
from .unified_logging import get_logger


# Type variables for better type hints
T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])


def safe_operation(
    default_return: Any = None,
    log_error: bool = True,
    operation_name: Optional[str] = None,
    error_handler: Optional[Callable[[Exception], None]] = None,
    exceptions: tuple = (Exception,)
) -> Callable[[F], F]:
    """
    Decorator for safe synchronous operations with consistent error handling.

    Args:
        default_return: Value to return on error (default: None)
        log_error: Whether to log errors (default: True)
        operation_name: Custom operation name for logging (default: function name)
        error_handler: Optional custom error handler function
        exceptions: Tuple of exceptions to catch (default: (Exception,))

    Returns:
        Decorated function that catches exceptions and returns default_return

    Example:
        >>> @safe_operation(default_return=False, operation_name="save_config")
        ... def save_configuration(config: dict) -> bool:
        ...     write_to_file(config)
        ...     return True
        >>>
        >>> # If write_to_file() raises an exception:
        >>> # - Error is logged: "save_config failed: <error>"
        >>> # - Function returns False
        >>> result = save_configuration({"key": "value"})
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                # Get logger for the function's module
                logger = get_logger(func.__module__)

                # Use custom operation name or function name
                name = operation_name or func.__name__

                # Log error if requested
                if log_error:
                    logger.error(f"{name} failed: {e}", exc_info=True)

                # Call custom error handler if provided
                if error_handler:
                    try:
                        error_handler(e)
                    except Exception as handler_error:
                        logger.error(f"Error handler failed: {handler_error}")

                # Return default value
                return default_return

        return wrapper  # type: ignore

    return decorator


def safe_async_operation(
    default_return: Any = None,
    log_error: bool = True,
    operation_name: Optional[str] = None,
    error_handler: Optional[Callable[[Exception], None]] = None,
    exceptions: tuple = (Exception,)
) -> Callable[[F], F]:
    """
    Decorator for safe asynchronous operations with consistent error handling.

    Args:
        default_return: Value to return on error (default: None)
        log_error: Whether to log errors (default: True)
        operation_name: Custom operation name for logging (default: function name)
        error_handler: Optional custom error handler function
        exceptions: Tuple of exceptions to catch (default: (Exception,))

    Returns:
        Decorated async function that catches exceptions and returns default_return

    Example:
        >>> @safe_async_operation(default_return={}, operation_name="fetch_user")
        ... async def get_user(user_id: int) -> dict:
        ...     response = await api.get(f"/users/{user_id}")
        ...     return response.json()
        >>>
        >>> # If api.get() raises an exception:
        >>> # - Error is logged: "fetch_user failed: <error>"
        >>> # - Function returns {}
        >>> user = await get_user(123)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except exceptions as e:
                # Get logger for the function's module
                logger = get_logger(func.__module__)

                # Use custom operation name or function name
                name = operation_name or func.__name__

                # Log error if requested
                if log_error:
                    logger.error(f"{name} failed: {e}", exc_info=True)

                # Call custom error handler if provided
                if error_handler:
                    try:
                        error_handler(e)
                    except Exception as handler_error:
                        logger.error(f"Error handler failed: {handler_error}")

                # Return default value
                return default_return

        return wrapper  # type: ignore

    return decorator


def retry_on_failure(
    max_attempts: int = 3,
    exceptions: tuple = (Exception,),
    delay_seconds: float = 0,
    backoff_factor: float = 1.0,
    log_retries: bool = True
) -> Callable[[F], F]:
    """
    Decorator to retry function on failure with optional exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (default: 3)
        exceptions: Tuple of exceptions to catch and retry (default: (Exception,))
        delay_seconds: Initial delay between retries in seconds (default: 0)
        backoff_factor: Multiplier for delay on each retry (default: 1.0 = constant)
        log_retries: Whether to log retry attempts (default: True)

    Returns:
        Decorated function that retries on failure

    Example:
        >>> @retry_on_failure(max_attempts=3, delay_seconds=1, backoff_factor=2)
        ... def unreliable_api_call(url: str) -> dict:
        ...     response = requests.get(url)
        ...     return response.json()
        >>>
        >>> # Will retry up to 3 times with delays: 1s, 2s, 4s
        >>> data = unreliable_api_call("https://api.example.com/data")
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time

            logger = get_logger(func.__module__)
            current_delay = delay_seconds

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        # Last attempt failed - re-raise exception
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise

                    # Log retry attempt
                    if log_retries:
                        logger.warning(
                            f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )

                    # Wait before retrying
                    if current_delay > 0:
                        time.sleep(current_delay)

                    # Apply backoff factor for next retry
                    current_delay *= backoff_factor

            # Should never reach here, but satisfy type checker
            return None  # type: ignore

        return wrapper  # type: ignore

    return decorator


def retry_async_on_failure(
    max_attempts: int = 3,
    exceptions: tuple = (Exception,),
    delay_seconds: float = 0,
    backoff_factor: float = 1.0,
    log_retries: bool = True
) -> Callable[[F], F]:
    """
    Decorator to retry async function on failure with optional exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (default: 3)
        exceptions: Tuple of exceptions to catch and retry (default: (Exception,))
        delay_seconds: Initial delay between retries in seconds (default: 0)
        backoff_factor: Multiplier for delay on each retry (default: 1.0 = constant)
        log_retries: Whether to log retry attempts (default: True)

    Returns:
        Decorated async function that retries on failure

    Example:
        >>> @retry_async_on_failure(max_attempts=3, delay_seconds=0.5, backoff_factor=2)
        ... async def fetch_with_retry(url: str) -> dict:
        ...     async with httpx.AsyncClient() as client:
        ...         response = await client.get(url)
        ...         return response.json()
        >>>
        >>> # Will retry up to 3 times with delays: 0.5s, 1s, 2s
        >>> data = await fetch_with_retry("https://api.example.com/data")
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import asyncio

            logger = get_logger(func.__module__)
            current_delay = delay_seconds

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        # Last attempt failed - re-raise exception
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise

                    # Log retry attempt
                    if log_retries:
                        logger.warning(
                            f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )

                    # Wait before retrying
                    if current_delay > 0:
                        await asyncio.sleep(current_delay)

                    # Apply backoff factor for next retry
                    current_delay *= backoff_factor

            # Should never reach here, but satisfy type checker
            return None  # type: ignore

        return wrapper  # type: ignore

    return decorator


def suppress_errors(
    exceptions: tuple = (Exception,),
    log_error: bool = False
) -> Callable[[F], F]:
    """
    Decorator to suppress specific exceptions without returning a value.

    Useful for cleanup operations or non-critical functions where failures
    should be silently ignored.

    Args:
        exceptions: Tuple of exceptions to suppress (default: (Exception,))
        log_error: Whether to log suppressed errors (default: False)

    Returns:
        Decorated function that suppresses specified exceptions

    Example:
        >>> @suppress_errors(exceptions=(FileNotFoundError,), log_error=True)
        ... def cleanup_temp_file(path: str) -> None:
        ...     os.remove(path)
        >>>
        >>> # If file doesn't exist, error is logged but not raised
        >>> cleanup_temp_file("/tmp/nonexistent.txt")
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                if log_error:
                    logger = get_logger(func.__module__)
                    logger.debug(f"{func.__name__} suppressed error: {e}")
                return None

        return wrapper  # type: ignore

    return decorator
