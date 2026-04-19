from pydantic import BaseModel
from typing import List, Optional

class InventoryItem(BaseModel):
    name: str
    brand: str
    condition: str  # Like-New, Good, Visible Wear
    original_price_estimate: float
    listing_price: Optional[float] = None
    confidence: float

class RoomBundle(BaseModel):
    bundle_name: str
    items: List[InventoryItem]