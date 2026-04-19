from pydantic import BaseModel, Field
from typing import List, Optional

class InventoryItem(BaseModel):
    id: Optional[str] = None 
    name: str
    brand: str
    condition: str
    original_price: float
    estimated_year_of_purchase: int
    confidence: float
    listing_price: Optional[float] = None

class RoomBundle(BaseModel):
    id: Optional[str] = None
    bundle_name: str
    items: List[InventoryItem]