import asyncio
import logging
import time
from datetime import datetime, timezone

from app.domain.status import SaleStatus
from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.services.jobs import trigger_frame_extraction
from app.services.notifier import notifier

logger = logging.getLogger(__name__)


async def run_extraction_pipeline(
    event_id: str,
    gcs_uri: str,
    firestore: FirestoreService,
    gemini: GeminiProcessor,
    max_retries: int = 2,
):
    """
    Stage 1: AI Vision Analysis.
    Extracts bundles and items from the GCS video walkthrough.
    Services are injected by the router so this function is testable in isolation.
    """
    start = time.perf_counter()
    logger.info(f"Starting extraction pipeline for event: {event_id}")

    try:
        await firestore.transition_sale_status(event_id, SaleStatus.PROCESSING)

        bundles, ai_metadata = None, {}
        for attempt in range(max_retries + 1):
            try:
                bundles, ai_metadata = await gemini.process_walkthrough(gcs_uri)
                if bundles:
                    break
                logger.warning(f"Extraction attempt {attempt + 1} returned no items for {event_id}.")
            except Exception as exc:
                if attempt == max_retries:
                    raise
                logger.warning(f"Extraction attempt {attempt + 1} failed for {event_id}: {exc}. Retrying…")
                await asyncio.sleep(2 ** attempt)

        if not bundles:
            raise ValueError("AI Extraction returned no items after all retries")

        for b in bundles:
            bundle_id = await firestore.add_bundle(event_id, b.bundle_name, 0)
            for item in b.items:
                item_data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
                await firestore.add_item_to_bundle(event_id, bundle_id, item_data)

        await firestore.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
        await firestore.update_sale_metadata(event_id, {"extractionMetadata": ai_metadata})
        await notifier.notify_event(event_id, {
            "status": SaleStatus.READY_FOR_REVIEW,
            "message": f"Extraction complete. Found {len(bundles)} bundles.",
        })

        logger.info(f"Extraction pipeline success | event={event_id} | {time.perf_counter() - start:.2f}s")

        try:
            await trigger_frame_extraction(event_id)
            logger.info(f"Frame extraction job triggered | event={event_id}")
        except Exception as exc:
            logger.error(f"Failed to trigger frame extraction | event={event_id} | error={str(exc)}")

    except Exception as exc:
        logger.exception(f"Extraction pipeline failed for event {event_id}")
        await firestore.transition_sale_status(event_id, SaleStatus.FAILED)
        await notifier.notify_event(event_id, {"status": SaleStatus.FAILED, "error": str(exc)})


async def run_frames_extraction_pipeline(
    event_id: str,
    gcs_uris: list[str],
    firestore: FirestoreService,
    gemini: GeminiProcessor,
):
    """
    Frames variant of Stage 1: analyzes user-confirmed JPEG frames instead of a video.
    """
    start = time.perf_counter()
    logger.info(f"Starting frames extraction pipeline for event: {event_id} ({len(gcs_uris)} frames)")

    try:
        await firestore.transition_sale_status(event_id, SaleStatus.PROCESSING)

        bundles, ai_metadata = await gemini.process_frames(gcs_uris)

        if not bundles:
            raise ValueError("Frames extraction returned no items")

        for b in bundles:
            bundle_id = await firestore.add_bundle(event_id, b.bundle_name, 0)
            for item in b.items:
                item_data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
                await firestore.add_item_to_bundle(event_id, bundle_id, item_data)

        await firestore.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
        await firestore.update_sale_metadata(event_id, {
            "extractionMetadata": ai_metadata,
            "captureMode": "frames",
        })
        await notifier.notify_event(event_id, {
            "status": SaleStatus.READY_FOR_REVIEW,
            "message": f"Frames extraction complete. Found {len(bundles)} bundle(s).",
        })

        logger.info(f"Frames pipeline success | event={event_id} | {time.perf_counter() - start:.2f}s")

    except Exception as exc:
        logger.exception(f"Frames pipeline failed for event {event_id}")
        await firestore.transition_sale_status(event_id, SaleStatus.FAILED)
        await notifier.notify_event(event_id, {"status": SaleStatus.FAILED, "error": str(exc)})


async def run_pricing_pipeline(
    event_id: str,
    firestore: FirestoreService,
    gemini: GeminiProcessor,
    max_retries: int = 2,
):
    """
    Stage 2: AI Pricing Analysis.
    Analyzes verified inventory against Sydney market trends.
    Services are injected by the router so this function is testable in isolation.
    """
    start = time.perf_counter()
    logger.info(f"Starting pricing pipeline for event: {event_id}")

    try:
        summary = await firestore.get_full_event_summary(event_id)
        move_out_date = summary.get("moveOutDate") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        context_items: list[dict] = []
        item_to_bundle: dict[str, str] = {}
        for bundle in summary["bundles"]:
            for item in bundle["items"]:
                item_to_bundle[item["id"]] = bundle["id"]
                context_items.append({
                    "id": item["id"],
                    "name": item["name"],
                    "brand": item["brand"],
                    "condition": item["condition"],
                    "original_price": item.get("actual_original_price") or item.get("predicted_original_price"),
                    "purchase_year": item.get("actual_year_of_purchase") or item.get("predicted_year_of_purchase"),
                })

        priced_results, ai_metadata = [], {}
        for attempt in range(max_retries + 1):
            try:
                priced_results, ai_metadata = await gemini.estimate_listing_prices(context_items, move_out_date)
                if priced_results:
                    break
                logger.warning(f"Pricing attempt {attempt + 1} returned no results for {event_id}.")
            except Exception as exc:
                if attempt == max_retries:
                    raise
                logger.warning(f"Pricing attempt {attempt + 1} failed for {event_id}: {exc}. Retrying…")
                await asyncio.sleep(2 ** attempt)

        if not priced_results:
            raise ValueError("AI Pricing returned no results after all retries")

        for p in priced_results:
            item_id = p.get("id")
            bundle_id = item_to_bundle.get(item_id)
            if bundle_id:
                await firestore.update_item_data(event_id, bundle_id, item_id, {
                    "predicted_listing_price": p.get("listing_price", 0),
                    "actual_listing_price": p.get("listing_price", 0),
                    "pricing_reasoning": p.get("reasoning", "Market adjustment based on Sydney demand."),
                })

        for bundle in summary["bundles"]:
            await firestore.recalculate_bundle_total(event_id, bundle["id"])

        await firestore.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
        await firestore.update_sale_metadata(event_id, {"pricingMetadata": ai_metadata})
        await notifier.notify_event(event_id, {
            "status": SaleStatus.READY_FOR_REVIEW,
            "message": "Pricing complete",
        })

        logger.info(f"Pricing pipeline success | event={event_id} | {time.perf_counter() - start:.2f}s")

    except Exception as exc:
        logger.exception(f"Pricing pipeline failed for event {event_id}")
        await firestore.transition_sale_status(event_id, SaleStatus.FAILED)
        await notifier.notify_event(event_id, {"status": SaleStatus.FAILED, "error": str(exc)})
