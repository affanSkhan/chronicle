import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.routes import router as research_router
from app.api.sources import router as sources_router
from app.api.documents import router as documents_router
from app.api.evidence import router as evidence_router
from app.core.config import get_settings
from app.schemas.common import HealthResponse
from app.services.status_monitor import scheduled_monitor_loop

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor_task = None
    if settings.enable_scheduled_monitoring:
        monitor_task = asyncio.create_task(scheduled_monitor_loop(), name="chronicle-source-monitor")
    try:
        yield
    finally:
        if monitor_task is not None:
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Temporal evidence intelligence for scientific research.",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}


@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    # Process liveness. Use readiness checks separately for database/provider dependencies.
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(research_router, prefix=settings.api_prefix)
app.include_router(sources_router, prefix=settings.api_prefix)
app.include_router(documents_router, prefix=settings.api_prefix)
app.include_router(evidence_router, prefix=settings.api_prefix)
