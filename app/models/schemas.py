from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.domain.status import SaleStatus


# --- Sale Initialization ---

class SaleInitRequest(BaseModel):
    filename: str


class SaleInitResponse(BaseModel):
    event_id: str
    upload_url: str
    gcs_uri: str


class PriceEstimationRequest(BaseModel):
    move_out_date: str


class SalePublishRequest(BaseModel):
    move_out_date: str
    street_address: str
    suburb: str
    pincode: str
    state: str = "NSW"


# --- Bundle Schemas ---

class BundleCreateRequest(BaseModel):
    name: str


class BundleCreateResponse(BaseModel):
    bundle_id: str


# --- Item Schemas ---

class ItemCreateRequest(BaseModel):
    """Used for adding manual assets the AI might have missed."""
    name: str
    brand: str = "Unknown"
    actual_listing_price: float = 0.0
    actual_original_price: float = 0.0
    actual_year_of_purchase: int = Field(default_factory=lambda: datetime.now().year)
    condition: str = "Good"
    confidence: float = 1.0  # Manual items are 100% verified by default
    timestamp_label: str = "Manual Entry"
    video_timestamp: int = 0
    dimensions: Optional[str] = None
    material: Optional[str] = None
    is_fragile: bool = False
    disassembly_required: bool = False


class ItemCreateResponse(BaseModel):
    item_id: str


class ItemUpdate(BaseModel):
    """Strict schema for PATCH operations to avoid overwriting unrelated fields."""
    name: Optional[str] = None
    brand: Optional[str] = None
    actual_listing_price: Optional[float] = None
    actual_original_price: Optional[float] = None
    actual_year_of_purchase: Optional[int] = None
    condition: Optional[str] = None
    dimensions: Optional[str] = None
    material: Optional[str] = None
    is_fragile: Optional[bool] = None
    disassembly_required: Optional[bool] = None


# --- Generic Responses ---

class StatusResponse(BaseModel):
    """Generic single-field status response (e.g. deleted, updated, processing_started)."""
    status: str


# --- Response / Dashboard Schemas ---

class SaleStatusResponse(BaseModel):
    id: str
    status: SaleStatus
    sellerId: str
    suburb: Optional[str] = None
    street_address: Optional[str] = None
    pincode: Optional[str] = None
    state: Optional[str] = "NSW"
    createdAt: datetime
    itemCount: int = 0
    totalValue: float = 0.0
