
from pydantic import BaseModel, Field


class InventoryItem(BaseModel):
    id: str | None = None 
    name: str
    brand: str
    condition: str
    confidence: float
    
    # --- Year Tracking ---
    predicted_year_of_purchase: int
    actual_year_of_purchase: int | None = None
    
    # --- Price Tracking ---
    predicted_original_price: float # AI visual guess
    actual_original_price: float | None = None # User ground truth
    
    predicted_listing_price: float | None = None # AI market estimate
    actual_listing_price: float | None = None # Final live price
    pricing_reasoning: str | None = None

    # Human-readable (e.g., "00:45")
    timestamp_label: str | None = Field(None, description="Format MM:SS")
    # Machine-readable (e.g., 45.0)
    video_timestamp: float | None = None

    # --- Physical Attributes (For Relocation) ---
    dimensions: str | None = None
    material: str | None = None
    is_fragile: bool = False
    disassembly_required: bool = False

class RoomBundle(BaseModel):
    id: str | None = None
    bundle_name: str
    items: list[InventoryItem]