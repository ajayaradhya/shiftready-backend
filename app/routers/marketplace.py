from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.services import firestore_svc
from app.services.auth import get_optional_user, User

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

@router.get("/search")
async def search_marketplace(
    q: Optional[str] = Query(None, description="Search by item name or brand"),
    suburb: Optional[str] = Query(None, description="Filter by Sydney suburb (e.g. Waterloo)"),
    user: Optional[User] = Depends(get_optional_user)
):
    """
    The Primary Marketplace View. 
    Shows nearby items (by suburb) and supports keyword search.
    """
    items = await firestore_svc.get_active_inventory(suburb=suburb, query=q)
    
    # Mask sensitive data for anonymous users
    processed_items = []
    for item in items:
        is_owner = user and item.get("sellerId") == user.id
        
        processed_items.append({
            "id": item["id"],
            "name": item.get("name", "Unknown Item"),
            "brand": item.get("brand", "Generic"),
            "condition": item.get("condition", "Good"),
            "price": item.get("actual_listing_price"),
            "bundleName": item.get("bundleName"),
            "eventId": item.get("eventId"),
            # Restricted details
            "metadata": {
                "year": item.get("actual_year_of_purchase") if user else None,
                "originalPrice": item.get("actual_original_price") if user else None,
                "confidence": item.get("confidence") if is_owner else None
            }
        })
    
    return {
        "count": len(processed_items),
        "items": processed_items,
        "is_authenticated": user is not None
    }

@router.get("/items/{event_id}/{bundle_id}/{item_id}")
async def get_item_detail(
    event_id: str, 
    bundle_id: str, 
    item_id: str, 
    user: Optional[User] = Depends(get_optional_user)
):
    """Detailed view for a single item."""
    item = await firestore_svc.get_item_standalone(event_id, bundle_id, item_id)
    if not item:
        return {"error": "Item not found"}

    # Public view logic
    response = {
        "name": item.get("name"),
        "price": item.get("actual_listing_price"),
        "condition": item.get("condition"),
    }

    if user:
        # Show premium data to logged-in users (e.g., pricing reasoning, exact purchase year)
        response.update({
            "brand": item.get("brand"),
            "purchase_year": item.get("actual_year_of_purchase") or item.get("predicted_year_of_purchase"),
            "reasoning": item.get("pricing_reasoning"),
            "seller_id": item.get("sellerId")
        })
    
    return response