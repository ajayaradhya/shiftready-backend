import logging
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Internal Imports
from app.routers import sales

# Setup production-grade logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# --- App Initialization ---

start_time = time.time()

app = FastAPI(
    title="ShiftReady API",
    description="AI-native relocation inventory and pricing engine.",
    version="1.1.0"
)

# --- Middleware ---

# Standard origins for local development and future production URLs
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://shiftready-ui-12644234558.australia-southeast1.run.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Router Inclusion ---
# Versioning the API at /api/v1 ensures we can scale features 
# without breaking the current walkthrough flow.
app.include_router(sales.router, prefix="/api/v1", tags=["Inventory & Sales"])

# --- Base Endpoints ---

@app.get("/health")
async def health_check():
    """
    Service health check.
    Used by Cloud Run to determine container readiness.
    """
    return {
        "status": "operational",
        "version": "1.1.0",
        "timestamp": time.time(),
        "uptime_seconds": int(time.time() - start_time),
        "service": "shiftready-backend"
    }

if __name__ == "__main__":
    import uvicorn
    # Use 0.0.0.0 for Docker/Cloud Run compatibility
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)