import time

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import register_middleware
from fastapi.middleware.cors import CORSMiddleware
from app.routers import sales, marketplace, users, messages, sold

setup_logging()

app = FastAPI(
    title="ShiftReady API",
    description="AI-native relocation inventory and pricing engine.",
    version=settings.api_version,
)

origins = [
    "https://shiftready-ui-12644234558.australia-southeast1.run.app",
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000", # TODO: Remove in prod
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

register_middleware(app)

app.include_router(sales.router, prefix="/api/v1", tags=["Inventory & Sales"])
app.include_router(sold.router, prefix="/api/v1", tags=["Sold Lifecycle"])
app.include_router(marketplace.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")

_start_time = time.time()


@app.get("/")
async def root():
    return {"message": "ShiftReady API is live", "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health_check():
    return {
        "status": "operational",
        "version": settings.api_version,
        "timestamp": time.time(),
        "uptime_seconds": int(time.time() - _start_time),
        "service": "shiftready-backend",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=(not settings.gcp_project_id),
    )
