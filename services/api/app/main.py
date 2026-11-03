import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.routes import router as research_router
from app.api.sources import router as sources_router
from app.api.documents import router as documents_router
from app.api.evidence import router as evidence_router
from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.common import HealthResponse
from app.services.status_monitor import scheduled_monitor_loop
from app.core.rate_limit import SlidingWindowLimiter

settings = get_settings()
_request_limiter = SlidingWindowLimiter(settings.rate_limit_requests_per_minute)

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


@app.middleware("http")
async def abuse_rate_limit(request: Request, call_next):
    if settings.rate_limit_enabled and request.url.path not in {"/", "/api/v1/health", "/api/v1/ready"}:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        key = forwarded or (request.client.host if request.client else "unknown")
        allowed, retry_after = _request_limiter.check(key)
        if not allowed:
            return JSONResponse({"detail": "Too many requests. Please retry later."}, status_code=429, headers={"Retry-After": str(retry_after)})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def preserve_cors_on_errors(request: Request, call_next):
    """Ensure JSON 4xx/5xx responses retain CORS headers in serverless runtimes."""
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and origin in settings.allowed_origins:
        response.headers.setdefault("Access-Control-Allow-Origin", origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")
        response.headers.setdefault("Vary", "Origin")
    return response


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}


@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    # Process liveness. Use readiness checks separately for database/provider dependencies.
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@app.get("/api/v1/ready", tags=["system"])
def readiness(db: Session = Depends(get_db)) -> dict[str, object]:
    """Readiness check for traffic routing; unlike /health, it verifies database access."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Do not expose database URLs, SQL, or driver details in health responses.
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    return {
        "status": "ready",
        "service": settings.app_name,
        "version": settings.app_version,
        "dependencies": {"database": "ok"},
    }


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(research_router, prefix=settings.api_prefix)
app.include_router(sources_router, prefix=settings.api_prefix)
app.include_router(documents_router, prefix=settings.api_prefix)
app.include_router(evidence_router, prefix=settings.api_prefix)
