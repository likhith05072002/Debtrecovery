"""Exponential backoff retry decorator using tenacity."""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable, Type

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 0.5,
    max_wait: float = 10.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator: retry with exponential backoff on specified exceptions."""
    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            retry=retry_if_exception_type(exceptions),
            reraise=True,
        )
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)
        return wrapper
    return decorator
