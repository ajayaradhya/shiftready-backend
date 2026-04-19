import os
import time
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel

# Internal Imports
from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.services.pricing import PricingEngine
from app.utils.gcs import generate_upload_url

# Setup logging to see exactly where the time goes
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BUCKET_NAME = os.getenv("GCP_UPLOAD_BUCKET")
REGION = os.getenv("GCP_REGION")

# --- Global Services (The Singleton Pattern) ---
# Initializing these outside the routes prevents expensive re-authentication
firestore_svc = None
gemini_processor = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown of global resources."""
    global firestore_svc, gemini_processor
    logger.info("Initializing Global GCP Services...")
    firestore_svc = FirestoreService()
    gemini_processor = GeminiProcessor(project_id=PROJECT_ID)
    yield
    logger.info("Shutting down resources...")

app = FastAPI(title="ShiftReady API", version="1.0.0", lifespan=lifespan)

# --- Request/Response Schemas ---

class SaleInitRequest(BaseModel):
    user_id: str
    filename: str

class SaleInitResponse(BaseModel):
    event_id: str
    upload_url: str
    gcs_uri: str

# --- Background Task ---

async def run_ai_pipeline(event_id: str, gcs_uri: str):
    """Background worker to process video and update Firestore."""
    try:
        logger.info(f"AI Pipeline started for event: {event_id}")
        
        # 1. Extraction via Gemini 1.5 Flash
        bundles = gemini_processor.process_walkthrough(gcs_uri)

        # 2. Pricing & Storage
        for bundle in bundles:
            bundle_id = firestore_svc.add_bundle(event_id, bundle.bundle_name, 0)
            total_bundle_price = 0
            
            for item in bundle.items:
                item.listing_price = PricingEngine.calculate_listing_price(
                    orig_price=item.original_price_estimate,
                    category="default",
                    condition=item.condition,
                    years=1.0
                )
                total_bundle_price += item.listing_price
                firestore_svc.add_item_to_bundle(event_id, bundle_id, item.dict())
            
            firestore_svc.update_bundle_price(event_id, bundle_id, total_bundle_price)

        firestore_svc.update_sale_status(event_id, "ready_for_review")
        logger.info(f"AI Pipeline completed successfully for event: {event_id}")

    except Exception as e:
        logger.error(f"Pipeline Error for {event_id}: {str(e)}")
        firestore_svc.update_sale_status(event_id, "failed")

# --- Endpoints ---

@app.get("/")
def health_check():
    return {"status": "online", "region": REGION}

@app.post("/sales/init", response_model=SaleInitResponse)
async def initialize_sale(payload: SaleInitRequest):
    """Step 1: Get a signed URL and create Firestore record."""
    start_time = time.time()
    blob_name = f"uploads/{payload.user_id}/{payload.filename}"
    gcs_uri = f"gs://{BUCKET_NAME}/{blob_name}"

    try:
        # 1. Generate Signed URL
        upload_url = generate_upload_url(BUCKET_NAME, blob_name)
        logger.info(f"Signed URL generated in {time.time() - start_time:.2f}s")
        
        # 2. Initialize Firestore record
        event_id = firestore_svc.create_sale_event(payload.user_id, gcs_uri)
        logger.info(f"Firestore record {event_id} created. Total time: {time.time() - start_time:.2f}s")
        
        return {
            "event_id": event_id,
            "upload_url": upload_url,
            "gcs_uri": gcs_uri
        }
    except Exception as e:
        logger.error(f"Init Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sales/{event_id}/process")
async def start_processing(event_id: str, background_tasks: BackgroundTasks):
    """Step 2: Trigger AI pipeline after upload."""
    event = firestore_svc.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")

    firestore_svc.update_sale_status(event_id, "processing")
    background_tasks.add_task(run_ai_pipeline, event_id, event['videoUrl'])
    
    return {"status": "processing", "message": "Gemini 1.5 Flash analysis triggered."}

@app.get("/sales/{event_id}/status")
async def get_status(event_id: str):
    """Step 3: Polling for status."""
    event = firestore_svc.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")
    
    return {"status": event.get("status", "unknown")}