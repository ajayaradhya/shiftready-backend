import logging
import time
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import setup_logging
from app.core.middleware import register_middleware
from app.routers import sales, marketplace, users, messages, sold, notifications

setup_logging()
logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
        environment="production" if settings.gcp_project_id else "development",
    )
    logger.info("Sentry initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.services import firestore_svc

        await firestore_svc.db.collection("_warmup").limit(1).get()
        logger.info("Firestore connection pre-warmed")
    except Exception as exc:
        logger.warning("Firestore warmup skipped: %s", exc)
    yield


app = FastAPI(
    title="ShiftReady API",
    description="AI-native relocation inventory and pricing engine.",
    version=settings.api_version,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

register_middleware(app)

app.include_router(sales.router, prefix="/api/v1", tags=["Inventory & Sales"])
app.include_router(sold.router, prefix="/api/v1", tags=["Sold Lifecycle"])
app.include_router(marketplace.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")

_start_time = time.time()


@app.get("/")
async def root():
    return {"message": "ShiftReady API is live", "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health_check():
    firestore_ok = False
    try:
        from app.services import firestore_svc

        await firestore_svc.db.collection("_warmup").limit(1).get()
        firestore_ok = True
    except Exception:
        pass

    return {
        "status": "operational" if firestore_ok else "degraded",
        "version": settings.api_version,
        "timestamp": time.time(),
        "uptime_seconds": int(time.time() - _start_time),
        "service": "shiftready-backend",
        "checks": {
            "firestore": "ok" if firestore_ok else "error",
        },
    }


@app.get("/_ah/warmup")
async def warmup():
    """Cloud Run warmup handler."""
    from app.services import firestore_svc  # noqa: F401

    return {"status": "warm"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=(not settings.gcp_project_id),
    )
