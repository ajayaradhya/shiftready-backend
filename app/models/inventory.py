from pydantic import BaseModel, Field

class InventoryItem(BaseModel):
    name: str
    brand: str
    original_price: float = Field(description="Estimated original retail price in AUD")
    listing_price: float = Field(description="Suggested listing price in AUD")
    condition: str
    confidence: float

class RoomBundle(BaseModel):
    bundle_name: str = Field(description="Name of the room bundle")
    items: list[InventoryItem] = Field(description="List of inventory items in the bundle")