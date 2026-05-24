import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from app.domain.status import SaleStatus
from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.models.schemas import CapturedItemInput
from app.services.notifier import notifier

logger = logging.getLogger(__name__)


async def run_capture_refinement_pipeline(
    event_id: str,
    items: list[CapturedItemInput],
    firestore: FirestoreService,
    gemini: GeminiProcessor,
):
    """
    Phase 2 live-capture finalize pipeline.
    Items are pre-analyzed (name/brand/price/gcs_uri already extracted per-frame by Gemini).
    This pipeline groups them into room bundles via a single refinement call, writes to
    Firestore, then hands off to pricing.
    """
    start = time.perf_counter()
    logger.info(f"Starting capture refinement pipeline for event: {event_id} ({len(items)} items)")

    try:
        await firestore.transition_sale_status(event_id, SaleStatus.PROCESSING)

        # Build lightweight context for the refinement prompt (no images needed)
        items_context = [
            {"idx": i, "name": item.name, "brand": item.brand or "Unknown", "price": item.predicted_original_price}
            for i, item in enumerate(items)
        ]

        bundles_groupings, ai_metadata = await gemini.refine_captured_items(items_context)

        if not bundles_groupings:
            # Fallback: put everything in one bundle
            bundles_groupings = [{"bundle_name": "Captured Items", "item_indices": list(range(len(items)))}]

        now = datetime.now(timezone.utc).isoformat()
        seen_indices: set[int] = set()

        for grouping in bundles_groupings:
            bundle_name = grouping.get("bundle_name", "General")
            item_indices = grouping.get("item_indices", [])
            if not item_indices:
                continue

            bundle_id = await firestore.add_bundle(event_id, bundle_name, 0)

            for idx in item_indices:
                if idx < 0 or idx >= len(items) or idx in seen_indices:
                    continue
                seen_indices.add(idx)
                item = items[idx]
                item_data = {
                    "name": item.name,
                    "brand": item.brand or "Unknown",
                    "condition": "Good",
                    "predicted_original_price": item.predicted_original_price or 0,
                    "actual_original_price": 0,
                    "predicted_listing_price": 0,
                    "actual_listing_price": 0,
                    "predicted_year_of_purchase": None,
                    "actual_year_of_purchase": None,
                    "timestamp_label": "",
                    "dimensions": None,
                    "material": None,
                    "is_fragile": False,
                    "disassembly_required": False,
                    "confidence": 1.0,
                    "pricing_reasoning": None,
                    "images": [{
                        "id": str(uuid.uuid4()),
                        "gcs_path": item.gcs_uri,
                        "source": "frame_extract",
                        "is_cover": True,
                        "uploaded_at": now,
                    }],
                }
                await firestore.add_item_to_bundle(event_id, bundle_id, item_data)

        # Any items Gemini missed → dump into a catch-all bundle
        missed = [i for i in range(len(items)) if i not in seen_indices]
        if missed:
            bundle_id = await firestore.add_bundle(event_id, "General", 0)
            for idx in missed:
                item = items[idx]
                item_data = {
                    "name": item.name,
                    "brand": item.brand or "Unknown",
                    "condition": "Good",
                    "predicted_original_price": item.predicted_original_price or 0,
                    "actual_original_price": 0,
                    "predicted_listing_price": 0,
                    "actual_listing_price": 0,
                    "predicted_year_of_purchase": None,
                    "actual_year_of_purchase": None,
                    "timestamp_label": "",
                    "dimensions": None,
                    "material": None,
                    "is_fragile": False,
                    "disassembly_required": False,
                    "confidence": 1.0,
                    "pricing_reasoning": None,
                    "images": [{
                        "id": str(uuid.uuid4()),
                        "gcs_path": item.gcs_uri,
                        "source": "frame_extract",
                        "is_cover": True,
                        "uploaded_at": now,
                    }],
                }
                await firestore.add_item_to_bundle(event_id, bundle_id, item_data)

        await firestore.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
        await firestore.update_sale_metadata(event_id, {
            "refinementMetadata": ai_metadata,
            "captureMode": "live",
        })
        await notifier.notify_event(event_id, {
            "status": SaleStatus.READY_FOR_REVIEW,
            "message": f"Capture refinement complete. {len(items)} items organised into bundles.",
        })

        logger.info(f"Capture refinement pipeline success | event={event_id} | {time.perf_counter() - start:.2f}s")

        # Kick off pricing immediately
        await firestore.transition_sale_status(event_id, SaleStatus.PRICING_IN_PROGRESS)
        await run_pricing_pipeline(event_id, firestore, gemini)

    except Exception as exc:
        logger.exception(f"Capture refinement pipeline failed for event {event_id}")
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
