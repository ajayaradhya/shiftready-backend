from typing import List
from pydantic import BaseModel, Field


class PricingResult(BaseModel):
    """Structured output schema for a single priced item."""
    id: str = Field(description="The unique ID of the item provided in the input.")
    listing_price: float = Field(description="Suggested AUD listing price after urgency discount.")
    reasoning: str = Field(description="Short explanation including suburb demand.")


class PricingList(BaseModel):
    """Wrapper list returned by the pricing prompt."""
    results: List[PricingResult]
