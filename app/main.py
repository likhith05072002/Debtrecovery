from __future__ import annotations

import logging
import logging.config
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import get_settings
from app.api.v1.router import api_router
from app.monitoring.health import router as health_router
from app.monitoring.metrics import setup_metrics

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            "datefmt": "%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "loggers": {
        "app": {"level": "DEBUG", "handlers": ["console"], "propagate": False},
    },
    "root": {"level": "WARNING", "handlers": ["console"]},
})

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="DebtCollector AI Voice Agent",
        description="Production-grade AI-powered debt collection voice agent",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # CORS — restrict in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Prometheus metrics endpoint
    if settings.prometheus_enabled:
        setup_metrics(app)

    # Routers
    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(api_router, prefix="/api/v1")

    # WebSocket routes
    from app.api.websocket.media_stream import router as ws_router
    from app.api.websocket.human_stream import router as human_ws_router
    app.include_router(ws_router)
    app.include_router(human_ws_router)

    # Serve the React SPA from /app — must come after all API routes
    _static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    if os.path.isdir(_static_dir):
        app.mount("/app", StaticFiles(directory=_static_dir, html=True), name="spa-assets")

        @app.get("/app/{full_path:path}", include_in_schema=False)
        async def serve_spa(_full_path: str) -> FileResponse:
            return FileResponse(os.path.join(_static_dir, "index.html"))

    @app.on_event("startup")
    async def startup() -> None:
        from app.models.database.base import engine, Base
        import app.models.database  # noqa: F401 — registers all ORM models
        # Tables managed by Alembic in production; auto-create in dev only
        if not settings.is_production:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        logger.info("DebtCollector API started [env=%s]", settings.app_env)

    @app.on_event("shutdown")
    async def shutdown() -> None:
        from app.models.database.base import engine
        await engine.dispose()
        logger.info("DebtCollector API shut down")

    return app


app = create_app()
