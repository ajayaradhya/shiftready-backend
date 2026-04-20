from datetime import date

from pydantic import BaseModel, Field
from typing import List, Optional

from pydantic import BaseModel, Field
from typing import List, Optional

class InventoryItem(BaseModel):
    id: Optional[str] = None 
    name: str
    brand: str
    condition: str
    confidence: float
    
    # --- Year Tracking ---
    predicted_year_of_purchase: int
    actual_year_of_purchase: Optional[int] = None
    
    # --- Price Tracking ---
    predicted_original_price: float # AI visual guess
    actual_original_price: Optional[float] = None # User ground truth
    
    predicted_listing_price: Optional[float] = None # AI market estimate
    actual_listing_price: Optional[float] = None # Final live price


class RoomBundle(BaseModel):
    id: Optional[str] = None
    bundle_name: str
    items: List[InventoryItem]