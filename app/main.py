from datetime import datetime
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
from app.utils.gcs import GCSUtils

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
gcs_utils = None
current_year = datetime.now().year

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes all GCP clients once on startup."""
    global firestore_svc, gemini_processor, gcs_utils
    logger.info("Initializing Global GCP Services...")
    
    # 2. Initialize our custom services
    firestore_svc = FirestoreService()
    gemini_processor = GeminiProcessor(project_id=PROJECT_ID)
    gcs_utils = GCSUtils()
    
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
    """Initial extraction - Brands/Years only, no pricing yet."""
    try:
        bundles = gemini_processor.process_walkthrough(gcs_uri)
        for bundle in bundles:
            valid_items = [i for i in bundle.items if i.confidence >= 0.5]
            if not valid_items: continue

            bundle_id = firestore_svc.add_bundle(event_id, bundle.bundle_name, 0)
            for item in valid_items:
                # Note: listing_price starts as None/0
                firestore_svc.add_item_to_bundle(event_id, bundle_id, item.dict())

        firestore_svc.update_sale_status(event_id, "ready_for_review")
    except Exception as e:
        logger.error(f"Extraction Error: {str(e)}")
        firestore_svc.update_sale_status(event_id, "failed")

async def run_pricing_pipeline(event_id: str):
    """
    Refined pricing - uses Gemini 2.5 Flash as a market expert 
    to analyze human-verified facts.
    """
    try:
        logger.info(f"🧠 Starting Pricing Pipeline for {event_id}")
        
        # 1. Fetch the full summary (includes your Stage 2 edits)
        summary = firestore_svc.get_full_event_summary(event_id)
        
        # 2. Map data for the LLM (Prioritize User 'Actual' fields)
        context_items = []
        for bundle in summary['bundles']:
            for item in bundle['items']:
                context_items.append({
                    "id": item['id'],
                    "bundle_id": bundle['id'],
                    "name": item['name'],
                    "brand": item['brand'],
                    "condition": item['condition'],
                    # Fact: Use user input if available, else fallback to AI guess
                    "original_price": item.get('actual_original_price') or item.get('predicted_original_price'),
                    "purchase_year": item.get('actual_year_of_purchase') or item.get('predicted_year_of_purchase')
                })

        # 3. Call the Expert Pricing Method in gemini.py
        priced_results = gemini_processor.estimate_listing_prices(context_items)

        # 4. Batch update Firestore with suggested listing_prices
        for p in priced_results:
            firestore_svc.update_item_data(event_id, p['bundle_id'], p['id'], {
                "predicted_listing_price": p['listing_price'],
                "actual_listing_price": p['listing_price'] # Defaulting for user review
            })
            
        # 5. Refresh bundle totals (Sums up actual_listing_price)
        for bundle in summary['bundles']:
            firestore_svc.recalculate_bundle_total(event_id, bundle['id'])

        # 6. CRITICAL: Update status to break the polling loop
        firestore_svc.update_sale_status(event_id, "ready_for_review")
        logger.info(f"✅ Pricing Pipeline completed for {event_id}")

    except Exception as e:
        logger.error(f"❌ Pricing Pipeline Error: {str(e)}")
        firestore_svc.update_sale_status(event_id, "failed")

# --- Endpoints ---

@app.get("/")
def health_check():
    return {"status": "online", "region": REGION}

@app.post("/sales/init", response_model=SaleInitResponse)
async def initialize_sale(payload: SaleInitRequest):
    start_time = time.time()
    blob_name = f"uploads/{payload.user_id}/{payload.filename}"
    gcs_uri = f"gs://{BUCKET_NAME}/{blob_name}"

    try:
        # Use the global singleton instead of instantiating a new one
        upload_url = gcs_utils.generate_upload_url(BUCKET_NAME, blob_name)
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

@app.get("/sales/{event_id}/summary")
async def get_sale_summary(event_id: str):
    """Returns the full hierarchy of bundles and items for the Review UI."""
    summary = firestore_svc.get_full_event_summary(event_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")
    return summary

@app.patch("/sales/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def edit_item(event_id: str, bundle_id: str, item_id: str, updates: dict):
    """Allows user to override any field Gemini provided."""
    # When an item is edited, we might need to recalculate bundle totals
    # For now, we'll just update the item document
    firestore_svc.update_item_data(event_id, bundle_id, item_id, updates)
    return {"status": "updated"}

@app.post("/sales/{event_id}/publish")
async def publish_sale(event_id: str):
    # Before flipping status to live, we can do a final 'coalesce' 
    # to ensure every item has a price.
    summary = firestore_svc.get_full_event_summary(event_id)
    
    for bundle in summary['bundles']:
        for item in bundle['items']:
            if item.get('actual_listing_price') is None:
                # If for some reason Stage 3 was skipped, use a fallback
                fallback_price = item.get('predicted_listing_price') or 0
                firestore_svc.update_item_data(event_id, bundle['id'], item['id'], {
                    "actual_listing_price": fallback_price
                })

    firestore_svc.update_sale_status(event_id, "live")
    return {"status": "live", "message": "Sale is live with all priced items!"}

@app.post("/sales/{event_id}/estimate")
async def trigger_price_estimation(event_id: str, background_tasks: BackgroundTasks):
    """User-triggered action to get AI price estimates based on current edits."""
    firestore_svc.update_sale_status(event_id, "pricing_in_progress")
    background_tasks.add_task(run_pricing_pipeline, event_id)
    return {"message": "AI is analyzing Sydney market prices for your items..."}