from typing import Literal

from pydantic import BaseModel, Field


class SingleFrameResult(BaseModel):
    """Lightweight schema for per-frame live capture identification."""
    name: str = Field(description="Common descriptive name of the item (e.g. 'Armchair', 'Samsung TV')")
    brand: str = Field(description="Visible brand/manufacturer, or 'Unknown' if not determinable")
    predicted_original_price: float = Field(description="Estimated original retail price in AUD when new")
    confidence: Literal["high", "medium", "low"] = Field(
        description="Identification confidence: 'high' if item clearly visible and identified, 'medium' if category clear but model/brand uncertain, 'low' if image unclear, partially occluded, or multiple competing interpretations"
    )


class PricingResult(BaseModel):
    """Structured output schema for a single priced item."""
    id: str = Field(description="The unique ID of the item provided in the input.")
    listing_price: float = Field(description="Suggested AUD listing price after urgency discount.")
    reasoning: str = Field(description="Short explanation including suburb demand.")


class PricingList(BaseModel):
    """Wrapper list returned by the pricing prompt."""
    results: list[PricingResult]


class RefinementGrouping(BaseModel):
    """A room bundle assignment returned by the refinement prompt."""
    bundle_name: str = Field(description="Room name (e.g. 'Living Room', 'Bedroom', 'Kitchen')")
    item_indices: list[int] = Field(description="0-based indices into the input items array assigned to this bundle")


class RefinementResult(BaseModel):
    """Structured output from the capture refinement prompt."""
    bundles: list[RefinementGrouping]
