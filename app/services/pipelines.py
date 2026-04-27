import asyncio
import logging
import time
from datetime import datetime
from app.models.schemas import SaleStatus
from app.services import firestore_svc, gemini_processor
from app.services.notifier import notifier

logger = logging.getLogger(__name__)

async def run_extraction_pipeline(event_id: str, gcs_uri: str, max_retries: int = 2):
    """
    Stage 1: AI Vision Analysis.
    Extracts bundles and items from the GCS video walkthrough.
    Includes timing, structural logging, and retry logic.
    """
    start_time = time.perf_counter()
    logger.info(f"🏗️ Starting Extraction Pipeline for event: {event_id}")
    
    try:
        # 1. Update status to processing
        await firestore_svc.transition_sale_status(event_id, SaleStatus.PROCESSING)
        
        # 2. Call Gemini Vision with internal retry for transient errors
        bundles, ai_metadata = None, {}
        for attempt in range(max_retries + 1):
            try:
                bundles, ai_metadata = await gemini_processor.process_walkthrough(gcs_uri)
                if bundles: break
                logger.warning(f"⚠️ Extraction attempt {attempt + 1} returned no items for {event_id}. Retrying...")
            except Exception as e:
                if attempt == max_retries: raise
                logger.warning(f"⚠️ Extraction attempt {attempt + 1} failed for {event_id}: {e}. Retrying...")
                await asyncio.sleep(2 ** attempt) # Exponential backoff
        
        if not bundles:
            raise ValueError("AI Extraction failed to return any items after retries")

        # 3. Save results to Firestore hierarchy
        for b in bundles:
            bundle_id = await firestore_svc.add_bundle(event_id, b.bundle_name, 0)
            for item in b.items:
                # Convert Pydantic model to dict for Firestore
                item_data = item.model_dump() if hasattr(item, 'model_dump') else item.dict()
                await firestore_svc.add_item_to_bundle(event_id, bundle_id, item_data)
        
        # 4. Move to Review stage and log AI metadata
        await firestore_svc.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
        await firestore_svc.update_sale_metadata(event_id, {"extractionMetadata": ai_metadata})
        await notifier.notify_event(event_id, {
            "status": SaleStatus.READY_FOR_REVIEW, 
            "message": f"Extraction complete. Found {len(bundles)} bundles."
        })
        
        duration = time.perf_counter() - start_time
        logger.info(f"✅ Extraction Pipeline Success | Event: {event_id} | Time: {duration:.2f}s")

    except Exception as e:
        logger.exception(f"Extraction Pipeline Failed for event {event_id}")
        await firestore_svc.transition_sale_status(event_id, SaleStatus.FAILED)
        await notifier.notify_event(event_id, {"status": SaleStatus.FAILED, "error": str(e)})

async def run_pricing_pipeline(event_id: str, max_retries: int = 2):
    """
    Stage 2: AI Pricing Analysis.
    Analyzes verified inventory data against Sydney market trends.
    """
    start_time = time.perf_counter()
    logger.info(f"💰 Starting Pricing Pipeline for event: {event_id}")

    try:
        summary = await firestore_svc.get_full_event_summary(event_id)
        move_out_date = summary.get("moveOutDate") or datetime.now().strftime("%Y-%m-%d")

        context_items = []
        item_to_bundle_map = {}
        
        for bundle in summary['bundles']:
            for item in bundle['items']:
                item_to_bundle_map[item['id']] = bundle['id']
                context_items.append({
                    "id": item['id'],
                    "name": item['name'],
                    "brand": item['brand'],
                    "condition": item['condition'],
                    "original_price": item.get('actual_original_price') or item.get('predicted_original_price'),
                    "purchase_year": item.get('actual_year_of_purchase') or item.get('predicted_year_of_purchase')
                })

        # Call Gemini with retry logic
        priced_results, ai_metadata = [], {}
        for attempt in range(max_retries + 1):
            try:
                priced_results, ai_metadata = await gemini_processor.estimate_listing_prices(context_items, move_out_date)
                if priced_results: break
                logger.warning(f"⚠️ Pricing attempt {attempt + 1} returned no results for {event_id}. Retrying...")
            except Exception as e:
                if attempt == max_retries: raise
                logger.warning(f"⚠️ Pricing attempt {attempt + 1} failed for {event_id}: {e}. Retrying...")
                await asyncio.sleep(2 ** attempt)

        if not priced_results:
            raise ValueError("AI Pricing failed to generate results after retries")

        for p in priced_results:
            item_id = p.get('id')
            bundle_id = item_to_bundle_map.get(item_id)
            if bundle_id:
                await firestore_svc.update_item_data(event_id, bundle_id, item_id, {
                    "predicted_listing_price": p.get('listing_price', 0),
                    "actual_listing_price": p.get('listing_price', 0),
                    "pricing_reasoning": p.get('reasoning', 'Market adjustment based on Sydney demand.')
                })
        
        for bundle in summary['bundles']:
            await firestore_svc.recalculate_bundle_total(event_id, bundle['id'])

        await firestore_svc.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
        await firestore_svc.update_sale_metadata(event_id, {"pricingMetadata": ai_metadata})
        await notifier.notify_event(event_id, {"status": SaleStatus.READY_FOR_REVIEW, "message": "Pricing complete"})

        duration = time.perf_counter() - start_time
        logger.info(f"✅ Pricing Pipeline Success | Event: {event_id} | Time: {duration:.2f}s")

    except Exception as e:
        logger.exception(f"Pricing Pipeline Failed for event {event_id}")
        await firestore_svc.transition_sale_status(event_id, SaleStatus.FAILED)
        await notifier.notify_event(event_id, {"status": SaleStatus.FAILED, "error": str(e)})