from datetime import datetime
import os
import time
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
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

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,           # Allow your Next.js app
    allow_credentials=True,          # Allow cookies/auth headers
    allow_methods=["*"],             # Allow all HTTP methods (GET, POST, PATCH, etc.)
    allow_headers=["*"],             # Allow all headers
)

# --- Request/Response Schemas ---

class SaleInitRequest(BaseModel):
    user_id: str
    filename: str

class SaleInitResponse(BaseModel):
    event_id: str
    upload_url: str
    gcs_uri: str

class SalePublishRequest(BaseModel):
    move_out_date: str

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
    Refined pricing - uses Gemini 3.1 Flash Lite as a market expert 
    to analyze human-verified facts and Sydney market trends.
    """
    try:
        logger.info(f"🧠 Starting Pricing Pipeline for {event_id}")
        
        # 1. Fetch the full summary (includes your Stage 2 edits)
        summary = firestore_svc.get_full_event_summary(event_id)
        
        # Determine move-out date from summary or default to today
        move_out_date = summary.get("moveOutDate")
        if not move_out_date:
            move_out_date = datetime.now().strftime("%Y-%m-%d")

        # 2. Map data for the LLM & Create local Ground Truth Index
        # We store the bundle_id locally so we don't rely on the AI to return it.
        item_to_bundle_map = {}
        context_items = []
        
        for bundle in summary['bundles']:
            for item in bundle['items']:
                # Save the mapping: item_id -> bundle_id
                item_to_bundle_map[item['id']] = bundle['id']
                
                context_items.append({
                    "id": item['id'],
                    "name": item['name'],
                    "brand": item['brand'],
                    "condition": item['condition'],
                    # Prioritize user 'actual' fields over initial AI guesses
                    "original_price": item.get('actual_original_price') or item.get('predicted_original_price'),
                    "purchase_year": item.get('actual_year_of_purchase') or item.get('predicted_year_of_purchase')
                })

        # 3. Call the Expert Pricing Method in gemini.py
        # Now passing the move_out_date for urgency-based pricing logic
        priced_results = gemini_processor.estimate_listing_prices(context_items, move_out_date)

        # 4. Update Firestore using our deterministic local map
        for p in priced_results:
            item_id = p.get('id')
            bundle_id = item_to_bundle_map.get(item_id)
            
            if bundle_id:
                # We update the item with the new AI-suggested listing price and reasoning
                firestore_svc.update_item_data(event_id, bundle_id, item_id, {
                    "predicted_listing_price": p.get('listing_price', 0),
                    "actual_listing_price": p.get('listing_price', 0), # Defaulting for user review
                    "pricing_reasoning": p.get('reasoning', 'Market adjustment')
                })
            else:
                logger.warning(f"⚠️ AI returned unknown item ID: {item_id}")
            
        # 5. Refresh bundle totals (Sums up actual_listing_price)
        for bundle in summary['bundles']:
            firestore_svc.recalculate_bundle_total(event_id, bundle['id'])

        # 6. CRITICAL: Update status to break the UI polling loop
        firestore_svc.update_sale_status(event_id, "ready_for_review")
        logger.info(f"✅ Pricing Pipeline completed for {event_id}")

    except Exception as e:
        logger.error(f"❌ Pricing Pipeline Error: {str(e)}")
        firestore_svc.update_sale_status(event_id, "failed")

# --- Endpoints ---

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

@app.patch("/sales/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def edit_item(event_id: str, bundle_id: str, item_id: str, updates: dict):
    """Allows user to override any field Gemini provided."""
    # When an item is edited, we might need to recalculate bundle totals
    # For now, we'll just update the item document
    firestore_svc.update_item_data(event_id, bundle_id, item_id, updates)
    return {"status": "updated"}

@app.post("/sales/{event_id}/publish")
async def publish_sale(event_id: str, payload: SalePublishRequest):
    """
    Finalizes the sale, anchors it to a move-out date, and ensures 
    all items have an 'actual_listing_price' for the live listing.
    """
    # 1. Fetch current state
    summary = firestore_svc.get_full_event_summary(event_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Sale Event not found")

    # 2. Coalesce prices (Ensure no item goes live with a 'None' price)
    for bundle in summary['bundles']:
        for item in bundle['items']:
            if item.get('actual_listing_price') is None:
                # Use AI's expert estimate as the fallback
                fallback_price = item.get('predicted_listing_price') or 0
                firestore_svc.update_item_data(event_id, bundle['id'], item['id'], {
                    "actual_listing_price": fallback_price
                })

    # 3. Update parent document with move_out_date and 'live' status
    # We use a dict update here to include the new metadata
    live_updates = {
        "status": "live",
        "moveOutDate": payload.move_out_date,
        "publishedAt": datetime.now() 
    }
    
    # Update the parent saleEvents document
    firestore_svc.db.collection("saleEvents").document(event_id).update(live_updates)

    logger.info(f"🚀 Sale {event_id} is now LIVE. Move-out set for {payload.move_out_date}")
    
    return {
        "status": "live", 
        "message": f"Sale is live! Items must be sold by {payload.move_out_date}.",
        "move_out_date": payload.move_out_date
    }

@app.post("/sales/{event_id}/estimate")
async def trigger_price_estimation(event_id: str, background_tasks: BackgroundTasks):
    """User-triggered action to get AI price estimates."""
    firestore_svc.update_sale_status(event_id, "pricing_in_progress")
    background_tasks.add_task(run_pricing_pipeline, event_id)
    return {
        "status": "pricing_in_progress", 
        "message": "AI is analyzing Sydney market prices..."
    }

@app.get("/sales/{event_id}/summary")
async def get_sale_summary(event_id: str):
    """Returns the full hierarchy with a transformed Signed URL and price fallbacks."""
    summary = firestore_svc.get_full_event_summary(event_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    # 1. Transform the gs:// URI into a temporary HTTPS Signed URL for the web player
    gcs_uri = summary.get("videoUrl")
    if gcs_uri and gcs_uri.startswith("gs://"):
        try:
            stripped_uri = gcs_uri.replace("gs://", "")
            bucket_name, blob_name = stripped_uri.split("/", 1)
            
            # This uses the impersonated credentials you configured in GCSUtils
            summary["videoUrl"] = gcs_utils.generate_download_url(bucket_name, blob_name)
            logger.info(f"✅ Signed URL Generated for event {event_id}")
        except Exception as e:
            logger.error(f"❌ Failed to generate signed URL: {str(e)}")
            summary["videoUrl"] = "" # Fallback to prevent UI crash

    # 2. Ensure price fallbacks are handled so UI fields aren't empty
    for bundle in summary.get('bundles', []):
        for item in bundle.get('items', []):
            # If actual is null, the UI should show predicted
            if item.get("actual_original_price") is None:
                item["actual_original_price"] = item.get("predicted_original_price")
            if item.get("actual_listing_price") is None:
                item["actual_listing_price"] = item.get("predicted_listing_price")

    return summary