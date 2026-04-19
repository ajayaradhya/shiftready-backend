import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

# Internal Imports
from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.services.pricing import PricingEngine
from app.utils.gcs import generate_upload_url

app = FastAPI(title="ShiftReady API", version="1.0.0")

# Configuration
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "shiftready-493812")
BUCKET_NAME = os.getenv("UPLOAD_BUCKET", "shiftready-uploads-bucket")

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
    """
    Background worker to process video and update Firestore.
    Prevents the API from timing out during long AI processing.
    """
    try:
        # 1. Extraction via Gemini 1.5 Flash
        processor = GeminiProcessor(project_id=PROJECT_ID)
        bundles = processor.process_walkthrough(gcs_uri)

        # 2. Pricing & Storage
        firestore_svc = FirestoreService()
        
        for bundle in bundles:
            # Create Bundle Child Document
            bundle_id = firestore_svc.add_bundle(event_id, bundle.bundle_name, 0)
            total_bundle_price = 0
            
            for item in bundle.items:
                # Apply Sydney Resale Formula
                # For MVP: Assuming 1 year old (t=1)
                item.listing_price = PricingEngine.calculate_listing_price(
                    orig_price=item.original_price_estimate,
                    category="default", # Future improvement: category detection
                    condition=item.condition,
                    years=1.0
                )
                total_bundle_price += item.listing_price
                
                # Create Item Grandchild Document
                firestore_svc.add_item_to_bundle(event_id, bundle_id, item.dict())
            
            # Update the Bundle's aggregate price
            firestore_svc.update_bundle_price(event_id, bundle_id, total_bundle_price)

        # 3. Mark SaleEvent as Ready
        firestore_svc.update_sale_status(event_id, "ready_for_review")

    except Exception as e:
        print(f"Pipeline Error for {event_id}: {str(e)}")
        FirestoreService().update_sale_status(event_id, "failed")

# --- Endpoints ---

@app.get("/")
def health_check():
    return {"status": "online", "region": "australia-southeast1"}

@app.post("/sales/init", response_model=SaleInitResponse)
async def initialize_sale(payload: SaleInitRequest):
    """
    Step 1: Get a signed URL for the frontend and create Firestore record.
    """
    blob_name = f"uploads/{payload.user_id}/{payload.filename}"
    gcs_uri = f"gs://{BUCKET_NAME}/{blob_name}"

    try:
        # Generate the temporary permission URL (Signed URL)
        upload_url = generate_upload_url(BUCKET_NAME, blob_name)
        
        # Initialize Firestore structure
        firestore_svc = FirestoreService() # Create the instance
        event_id = firestore_svc.create_sale_event(payload.user_id, gcs_uri)
        
        return {
            "event_id": event_id,
            "upload_url": upload_url,
            "gcs_uri": gcs_uri
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sales/{event_id}/process")
async def start_processing(event_id: str, background_tasks: BackgroundTasks):
    """
    Step 2: Trigger the AI pipeline. 
    Frontend calls this AFTER the upload to GCS is successful.
    """
    # Verify the event exists
    event = FirestoreService.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")

    # Update status and hand off to background task
    FirestoreService().update_sale_status(event_id, "processing")
    background_tasks.add_task(run_ai_pipeline, event_id, event['videoUrl'])
    
    return {"status": "processing", "message": "Gemini 1.5 Flash has started analyzing your video."}

@app.get("/sales/{event_id}/status")
async def get_status(event_id: str):
    """
    Step 3: Polling endpoint for frontend to check if AI is done.
    """
    event = FirestoreService.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")
    
    return {"status": event.get("status", "unknown")}