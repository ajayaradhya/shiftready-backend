import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.deps import FirestoreDep, GCSDep
from app.models.schemas import SaveToggleResponse
from app.services.auth import get_current_user, get_optional_user, User

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

_CDN_CACHE = "public, max-age=30, s-maxage=120, stale-while-revalidate=300"


def _process_item(item: dict, gcs, user) -> dict:
    image_url = None
    images = item.get("images") or []
    cover = next((img for img in images if img.get("is_cover")), images[0] if images else None)
    if cover:
        gcs_path = cover.get("gcs_path")
        if gcs_path and gcs_path.startswith("gs://"):
            try:
                s = gcs_path.replace("gs://", "").split("/", 1)
                image_url = gcs.generate_download_url(s[0], s[1])
            except Exception:
                pass
    is_owner = user and item.get("sellerId") == user.id
    return {
        "id": item["id"],
        "name": item.get("name", "Unknown Item"),
        "brand": item.get("brand", "Generic"),
        "condition": item.get("condition", "Good"),
        "category": item.get("category"),
        "price": item.get("actual_listing_price"),
        "bundleName": item.get("bundleName"),
        "eventId": item.get("eventId"),
        "image_url": image_url,
        "metadata": {
            "year": item.get("actual_year_of_purchase") if user else None,
            "originalPrice": item.get("actual_original_price") if user else None,
            "confidence": item.get("confidence") if is_owner else None,
        },
    }


def _process_sale(sale_raw: dict, gcs) -> dict:
    sale = dict(sale_raw)
    signed: list[str] = []
    for path in sale.get("preview_images", []):
        if path.startswith("gs://"):
            try:
                parts = path.replace("gs://", "").split("/", 1)
                signed.append(gcs.generate_download_url(parts[0], parts[1]))
            except Exception:
                pass
    sale["preview_images"] = signed
    cover_gcs = sale.pop("cover_image_gcs", None)
    if cover_gcs and cover_gcs.startswith("gs://"):
        try:
            parts = cover_gcs.replace("gs://", "").split("/", 1)
            sale["cover_image_url"] = gcs.generate_download_url(parts[0], parts[1])
        except Exception:
            sale["cover_image_url"] = None
    else:
        sale["cover_image_url"] = None
    return sale

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/landing")
async def get_landing(
    firestore: FirestoreDep,
    gcs: GCSDep,
    response: Response,
    suburb: str | None = Query(None),
    postcode: str | None = Query(None, description="4-digit AU postcode"),
    user: User | None = Depends(get_optional_user),
):
    """Single-call landing endpoint: newest items + cheapest + active sales via asyncio.gather."""
    if not user:
        response.headers["Cache-Control"] = _CDN_CACHE

    items_newest, items_cheapest, sales_raw = await asyncio.gather(
        firestore.get_active_inventory(suburb=suburb, postcode=postcode, sort="newest"),
        firestore.get_active_inventory(suburb=suburb, postcode=postcode, sort="price_asc"),
        firestore.list_live_sales(),
    )

    return {
        "items": [_process_item(i, gcs, user) for i in items_newest],
        "cheapest": [_process_item(i, gcs, user) for i in items_cheapest],
        "active_sales": [_process_sale(s, gcs) for s in sales_raw],
    }


@router.get("/sales")
async def list_live_sales(firestore: FirestoreDep, gcs: GCSDep, response: Response, user: User | None = Depends(get_optional_user)):
    """List all LIVE sales — used by the landing page sales scroll."""
    if not user:
        response.headers["Cache-Control"] = _CDN_CACHE
    sales = await firestore.list_live_sales()
    return [_process_sale(s, gcs) for s in sales]


@router.get("/search")
async def search_marketplace(
    firestore: FirestoreDep,
    gcs: GCSDep,
    response: Response,
    q: str | None = Query(None, description="Search by item name or brand"),
    suburb: str | None = Query(None, description="Filter by Sydney suburb"),
    postcode: str | None = Query(None, description="Filter by 4-digit AU postcode (takes precedence over suburb)"),
    category: str | None = Query(None, description="furniture|appliance|electronics|decor|other"),
    condition: str | None = Query(None, description="New|Like New|Good|Fair"),
    min_price: float | None = Query(None, description="Minimum listing price"),
    max_price: float | None = Query(None, description="Maximum listing price"),
    sort: str | None = Query(None, description="newest|price_asc|price_desc"),
    user: User | None = Depends(get_optional_user),
):
    """
    The Primary Marketplace View.
    Shows nearby items (by suburb) and supports keyword/category/condition/price/sort filters.
    """
    if not user:
        response.headers["Cache-Control"] = _CDN_CACHE

    items = await firestore.get_active_inventory(
        suburb=suburb, postcode=postcode, query=q, category=category,
        condition=condition, min_price=min_price, max_price=max_price, sort=sort,
    )

    processed_items = [_process_item(i, gcs, user) for i in items]
    return {
        "count": len(processed_items),
        "items": processed_items,
        "is_authenticated": user is not None,
    }


@router.get("/sales/{event_id}")
async def get_public_sale(
    event_id: str,
    firestore: FirestoreDep,
    gcs: GCSDep,
    user: User | None = Depends(get_optional_user),
):
    """Public sale detail page — bundles + items for a single LIVE sale."""
    sale = await firestore.marketplace.get_public_sale(event_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    for bundle in sale.get("bundles", []):
        for item in bundle.get("items", []):
            gcs_path = item.pop("image_gcs_path", None)
            if gcs_path and gcs_path.startswith("gs://"):
                try:
                    s = gcs_path.replace("gs://", "").split("/", 1)
                    item["image_url"] = gcs.generate_download_url(s[0], s[1])
                except Exception:
                    item["image_url"] = None
            else:
                item["image_url"] = None

    seller_id = sale.get("sellerId")
    seller_doc, is_saved = await asyncio.gather(
        firestore.get_user(seller_id) if seller_id else asyncio.sleep(0, result=None),
        firestore.is_sale_saved(user.id, event_id) if user else asyncio.sleep(0, result=None),
    )

    seller_username = seller_doc.get("username") if seller_doc else None

    cover_gcs = sale.pop("cover_image_gcs", None)
    cover_image_url = None
    if cover_gcs and cover_gcs.startswith("gs://"):
        try:
            parts = cover_gcs.replace("gs://", "").split("/", 1)
            cover_image_url = gcs.generate_download_url(parts[0], parts[1])
        except Exception:
            pass

    return {
        **sale,
        "sellerUsername": seller_username,
        "is_authenticated": user is not None,
        "is_saved": is_saved,
        "cover_image_url": cover_image_url,
    }


@router.get("/items/{event_id}/{bundle_id}/{item_id}")
async def get_item_detail(
    event_id: str,
    bundle_id: str,
    item_id: str,
    firestore: FirestoreDep,
    gcs: GCSDep,
    user: User | None = Depends(get_optional_user),
):
    """Detailed view for a single item."""
    item = await firestore.get_item_standalone(event_id, bundle_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Generate cover image signed URL
    image_url = None
    images = item.get("images") or []
    cover = next((img for img in images if img.get("is_cover")), images[0] if images else None)
    if cover:
        gcs_path = cover.get("gcs_path")
        if gcs_path and gcs_path.startswith("gs://"):
            try:
                s = gcs_path.replace("gs://", "").split("/", 1)
                image_url = gcs.generate_download_url(s[0], s[1])
            except Exception:
                pass

    # Fetch bundle name, sale context, and saved status in parallel
    bundle_ref = firestore.db.collection("saleEvents").document(event_id).collection("bundles").document(bundle_id)
    sale_ref = firestore.db.collection("saleEvents").document(event_id)

    if user:
        bundle_doc, sale_doc, is_saved = await asyncio.gather(
            bundle_ref.get(),
            sale_ref.get(),
            firestore.is_item_saved(user.id, item_id),
        )
    else:
        bundle_doc, sale_doc = await asyncio.gather(bundle_ref.get(), sale_ref.get())
        is_saved = None

    bundle_data = bundle_doc.to_dict() if bundle_doc.exists else {}
    sale_data = sale_doc.to_dict() if sale_doc.exists else {}

    response: dict = {
        "name": item.get("name"),
        "brand": item.get("brand"),
        "condition": item.get("condition"),
        "price": item.get("actual_listing_price"),
        "original_price": item.get("actual_original_price") or item.get("predicted_original_price"),
        "year": item.get("actual_year_of_purchase") or item.get("predicted_year_of_purchase"),
        "image_url": image_url,
        "bundle_id": bundle_id,
        "bundle_name": bundle_data.get("name"),
        "suburb": sale_data.get("suburb"),
        "seller_id": sale_data.get("sellerId"),
        "is_saved": is_saved,
    }

    if user:
        response["pricing_reasoning"] = item.get("pricing_reasoning")

    return response


# --- Save / Watchlist endpoints ---

@router.post("/sales/{event_id}/save", response_model=SaveToggleResponse)
async def save_sale(
    event_id: str,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    sale = await firestore.get_sale_event(event_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    metadata = {
        "suburb": sale.get("suburb"),
        "state": sale.get("state"),
        "moveOutDate": sale.get("moveOutDate"),
        "itemCount": 0,
    }
    await firestore.save_sale(current_user.id, event_id, metadata)
    return SaveToggleResponse(saved=True)


@router.delete("/sales/{event_id}/save", response_model=SaveToggleResponse)
async def unsave_sale(
    event_id: str,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    await firestore.unsave_sale(current_user.id, event_id)
    return SaveToggleResponse(saved=False)


@router.post("/items/{event_id}/{bundle_id}/{item_id}/save", response_model=SaveToggleResponse)
async def save_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    item, sale = await asyncio.gather(
        firestore.get_item_standalone(event_id, bundle_id, item_id),
        firestore.get_sale_event(event_id),
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    images = item.get("images") or []
    cover = next((img for img in images if img.get("is_cover")), images[0] if images else None)
    gcs_path = cover.get("gcs_path") if cover else None

    metadata = {
        "bundleId": bundle_id,
        "eventId": event_id,
        "name": item.get("name"),
        "brand": item.get("brand"),
        "condition": item.get("condition"),
        "price": item.get("actual_listing_price"),
        "suburb": sale.get("suburb") if sale else None,
        "gcs_path": gcs_path,
    }
    await firestore.save_item(current_user.id, item_id, metadata)
    return SaveToggleResponse(saved=True)


@router.delete("/items/{event_id}/{bundle_id}/{item_id}/save", response_model=SaveToggleResponse)
async def unsave_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    await firestore.unsave_item(current_user.id, item_id)
    return SaveToggleResponse(saved=False)
