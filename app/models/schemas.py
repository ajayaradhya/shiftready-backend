from enum import Enum

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# --- Constants for Defaults ---
CURRENT_YEAR = datetime.now().year

# --- Sale Initialization ---

class SaleInitRequest(BaseModel):
    filename: str

class SaleInitResponse(BaseModel):
    event_id: str
    upload_url: str
    gcs_uri: str

class SalePublishRequest(BaseModel):
    move_out_date: str

# --- Bundle Schemas ---

class BundleBase(BaseModel):
    name: str
    suggestedPrice: float = 0.0

class BundleCreateRequest(BaseModel):
    name: str

# --- Item Schemas ---

class ItemBase(BaseModel):
    name: str
    brand: Optional[str] = "Unknown"
    condition: str = "Good"
    actual_listing_price: float = 0.0
    actual_original_price: float = 0.0
    actual_year_of_purchase: Optional[int] = None
    timestamp_label: str = "Manual Entry"
    video_timestamp: float = 0.0
    confidence: float = 1.0

class ItemCreateRequest(BaseModel):
    """Used for adding manual assets the AI might have missed."""
    name: str
    brand: str = "Unknown"
    actual_listing_price: float = 0.0
    actual_original_price: float = 0.0
    actual_year_of_purchase: int = Field(default=CURRENT_YEAR)
    condition: str = "Good"
    confidence: float = 1.0  # Manual items are 100% verified by default
    timestamp_label: str = "Manual Entry"
    video_timestamp: int = 0

class ItemUpdate(BaseModel):
    """Strict schema for PATCH operations to avoid overwriting unrelated fields."""
    name: Optional[str] = None
    brand: Optional[str] = None
    actual_listing_price: Optional[float] = None
    actual_original_price: Optional[float] = None
    actual_year_of_purchase: Optional[int] = None
    condition: Optional[str] = None

# --- Response / Dashboard Schemas ---

class SaleStatus(str, Enum):
    # Discovery Phase
    PENDING_UPLOAD = "pending_upload"
    PROCESSING = "processing"          # Gemini capturing objects
    
    # Review Phase
    READY_FOR_REVIEW = "ready_for_review"
    PRICING_IN_PROGRESS = "pricing_in_progress" # Gemini analyzing Sydney market
    
    # Active Phase
    LIVE = "live"                      # Publicly buyable
    PARTIALLY_SOLD = "partially_sold"   # Some items marked sold
    
    # Conclusion Phase
    EXPIRED = "expired"                # Past move-out date
    ARCHIVED = "archived"              # Move complete, record-only
    FAILED = "failed"


class SaleStatusResponse(BaseModel):
    id: str
    status: SaleStatus
    sellerId: str
    createdAt: datetime
    itemCount: int = 0
    totalValue: float = 0.0
