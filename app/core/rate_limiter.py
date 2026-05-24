"""Redis-backed sliding window rate limiter."""
from __future__ import annotations

import time

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status


class RateLimiter:
    """Sliding window rate limiter using Redis sorted sets.

    Usage as FastAPI dependency:
        limiter = RateLimiter(max_requests=100, window_seconds=60)

        @app.get("/endpoint")
        async def endpoint(request: Request, redis: Redis = Depends(get_redis)):
            await limiter.check(request, redis)
            ...
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def _get_key(self, request: Request) -> str:
        """Generate rate limit key from request context."""
        # Use user_id if authenticated, otherwise IP
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"ratelimit:user:{user_id}"
        # Fall back to IP
        client_ip = request.client.host if request.client else "unknown"
        return f"ratelimit:ip:{client_ip}"

    async def check(self, request: Request, redis: aioredis.Redis) -> None:
        """Check rate limit. Raises 429 if exceeded."""
        key = self._get_key(request)
        now = time.time()
        window_start = now - self.window_seconds

        pipe = redis.pipeline()
        # Remove old entries outside the window
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current entries
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {f"{now}:{id(request)}": now})
        # Set TTL on the key
        pipe.expire(key, self.window_seconds + 1)
        results = await pipe.execute()

        current_count = results[1]
        if current_count >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )


# Pre-configured limiters for common use cases
default_limiter = RateLimiter(max_requests=1000, window_seconds=60)  # Authenticated
auth_limiter = RateLimiter(max_requests=10, window_seconds=60)  # Auth endpoints (login, register)
unauthenticated_limiter = RateLimiter(max_requests=100, window_seconds=60)  # Public endpoints
