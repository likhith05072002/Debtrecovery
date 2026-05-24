"""Health check endpoints for load balancer and container orchestration."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/live")
async def liveness():
    """Kubernetes/ECS liveness probe — always returns 200 if process is alive."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/ready")
async def readiness():
    """
    Readiness probe — checks database and Redis connectivity.
    Returns 503 if any dependency is unavailable.
    """
    checks: dict[str, str] = {}
    overall_ok = True

    # Check PostgreSQL
    try:
        from app.models.database.base import engine
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"
        overall_ok = False

    # Check Redis
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        r = aioredis.from_url(get_settings().redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        overall_ok = False

    status_code = 200 if overall_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if overall_ok else "not_ready", "checks": checks},
    )
