from pydantic import BaseModel, Field


class SingleFrameResult(BaseModel):
    """Lightweight schema for per-frame live capture identification."""
    name: str = Field(description="Common descriptive name of the item (e.g. 'Armchair', 'Samsung TV')")
    brand: str = Field(description="Visible brand/manufacturer, or 'Unknown' if not determinable")
    predicted_original_price: float = Field(description="Estimated original retail price in AUD when new")


class PricingResult(BaseModel):
    """Structured output schema for a single priced item."""
    id: str = Field(description="The unique ID of the item provided in the input.")
    listing_price: float = Field(description="Suggested AUD listing price after urgency discount.")
    reasoning: str = Field(description="Short explanation including suburb demand.")


class PricingList(BaseModel):
    """Wrapper list returned by the pricing prompt."""
    results: list[PricingResult]
