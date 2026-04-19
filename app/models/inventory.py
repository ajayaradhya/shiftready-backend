from pydantic import BaseModel, Field

class InventoryItem(BaseModel):
    name: str = Field(description="Generic name of the item")
    brand: str = Field(description="Brand name if visible, else 'Unknown'")
    original_price: float = Field(description="Estimated original retail price in AUD")

class RoomBundle(BaseModel):
    bundle_name: str = Field(description="Name of the room bundle")
    items: list[InventoryItem] = Field(description="List of inventory items in the bundle")