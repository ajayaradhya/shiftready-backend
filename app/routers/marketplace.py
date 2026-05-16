from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import FirestoreDep, GCSDep
from app.services.auth import get_optional_user, User

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])


@router.get("/sales")
async def list_live_sales(firestore: FirestoreDep):
    """List all LIVE sales — used by the landing page sales scroll."""
    return await firestore.list_live_sales()


@router.get("/search")
async def search_marketplace(
    firestore: FirestoreDep,
    gcs: GCSDep,
    q: str | None = Query(None, description="Search by item name or brand"),
    suburb: str | None = Query(None, description="Filter by Sydney suburb (e.g. Waterloo)"),
    user: User | None = Depends(get_optional_user),
):
    """
    The Primary Marketplace View.
    Shows nearby items (by suburb) and supports keyword search.
    """
    items = await firestore.get_active_inventory(suburb=suburb, query=q)

    # Mask sensitive data for anonymous users
    processed_items = []
    for item in items:
        is_owner = user and item.get("sellerId") == user.id

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

        processed_items.append({
            "id": item["id"],
            "name": item.get("name", "Unknown Item"),
            "brand": item.get("brand", "Generic"),
            "condition": item.get("condition", "Good"),
            "price": item.get("actual_listing_price"),
            "bundleName": item.get("bundleName"),
            "eventId": item.get("eventId"),
            "image_url": image_url,
            # Restricted details
            "metadata": {
                "year": item.get("actual_year_of_purchase") if user else None,
                "originalPrice": item.get("actual_original_price") if user else None,
                "confidence": item.get("confidence") if is_owner else None,
            },
        })

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

    seller_username = None
    seller_id = sale.get("sellerId")
    if seller_id:
        seller_doc = await firestore.get_user(seller_id)
        if seller_doc:
            seller_username = seller_doc.get("username")

    return {**sale, "sellerUsername": seller_username, "is_authenticated": user is not None}


@router.get("/items/{event_id}/{bundle_id}/{item_id}")
async def get_item_detail(
    event_id: str,
    bundle_id: str,
    item_id: str,
    firestore: FirestoreDep,
    user: User | None = Depends(get_optional_user),
):
    """Detailed view for a single item."""
    item = await firestore.get_item_standalone(event_id, bundle_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Public view — minimal fields for anonymous browsers
    response: dict = {
        "name": item.get("name"),
        "price": item.get("actual_listing_price"),
        "condition": item.get("condition"),
    }

    if user:
        # Extended data for authenticated users (pricing reasoning, exact purchase year)
        response.update({
            "brand": item.get("brand"),
            "purchase_year": item.get("actual_year_of_purchase") or item.get("predicted_year_of_purchase"),
            "reasoning": item.get("pricing_reasoning"),
            "seller_id": item.get("sellerId"),
        })

    return response
