from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.status import SaleStatus


# --- Sale Initialization ---

class SaleInitRequest(BaseModel):
    filename: str


class SaleInitResponse(BaseModel):
    event_id: str
    upload_url: str
    gcs_uri: str


class AppendInitResponse(BaseModel):
    upload_url: str
    gcs_uri: str


class AppendProcessRequest(BaseModel):
    gcs_uri: str


class CaptureInitResponse(BaseModel):
    event_id: str


class ProcessFramesResponse(BaseModel):
    event_id: str
    status: str


class CaptureFrameResponse(BaseModel):
    name: str
    brand: str
    predicted_original_price: float
    gcs_uri: str


class CaptureFinalizeRequest(BaseModel):
    gcs_uris: list[str]


class CapturedItemInput(BaseModel):
    temp_id: str
    name: str
    brand: str | None = None
    predicted_original_price: float | None = None
    gcs_uri: str


class CaptureFinalizeV2Request(BaseModel):
    items: list[CapturedItemInput]


class CaptureFinalizeV2Response(BaseModel):
    event_id: str
    status: str
    item_count: int


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


class BundleRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


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
    dimensions: str | None = None
    material: str | None = None
    is_fragile: bool = False
    disassembly_required: bool = False


class ItemCreateResponse(BaseModel):
    item_id: str


class ItemCategory(str, Enum):
    furniture = "furniture"
    appliance = "appliance"
    decor = "decor"
    electronics = "electronics"
    other = "other"


class ItemUpdate(BaseModel):
    """Strict schema for PATCH operations to avoid overwriting unrelated fields."""
    name: str | None = None
    brand: str | None = None
    actual_listing_price: float | None = None
    actual_original_price: float | None = None
    actual_year_of_purchase: int | None = None
    condition: str | None = None
    dimensions: str | None = None
    material: str | None = None
    is_fragile: bool | None = None
    disassembly_required: bool | None = None
    description: str | None = Field(default=None, max_length=500)
    category: ItemCategory | None = None
    quantity: int | None = Field(default=None, ge=1)


class ItemMoveRequest(BaseModel):
    to_bundle_id: str


class ImageReorderRequest(BaseModel):
    image_ids: list[str]


# --- Item Image Schemas ---

class ImageFileRequest(BaseModel):
    filename: str
    content_type: str = "image/jpeg"


class ImageUploadUrlsRequest(BaseModel):
    files: list[ImageFileRequest]


class ImageUploadUrlItem(BaseModel):
    image_id: str
    upload_url: str
    gcs_path: str


class ImageUploadUrlsResponse(BaseModel):
    urls: list[ImageUploadUrlItem]


class ImageConfirmItem(BaseModel):
    image_id: str
    gcs_path: str


class ImageConfirmRequest(BaseModel):
    images: list[ImageConfirmItem]


# --- Sale Update / Cover Schemas ---

class CoverImageData(BaseModel):
    id: str
    gcs_path: str
    source: str = "user_upload"


class SaleUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    move_out_date: str | None = None
    street_address: str | None = None
    suburb: str | None = None
    pincode: str | None = None
    state: str | None = None


class CoverUploadUrlResponse(BaseModel):
    image_id: str
    upload_url: str
    gcs_path: str


class CoverConfirmRequest(BaseModel):
    image_id: str
    gcs_path: str


class CoverFromItemRequest(BaseModel):
    bundle_id: str
    item_id: str
    image_id: str


# --- Video Replace Schemas ---

class VideoReplaceMode(str, Enum):
    WIPE = "wipe"
    APPEND = "append"


class VideoReplaceInitResponse(BaseModel):
    upload_url: str
    gcs_uri: str
    video_id: str


class VideoReplaceConfirmRequest(BaseModel):
    gcs_uri: str
    mode: VideoReplaceMode = VideoReplaceMode.WIPE
    video_id: str


# --- Generic Responses ---

class StatusResponse(BaseModel):
    """Generic single-field status response (e.g. deleted, updated, processing_started)."""
    status: str


# --- Response / Dashboard Schemas ---

class SaleStatusResponse(BaseModel):
    id: str
    status: SaleStatus
    sellerId: str
    suburb: str | None = None
    street_address: str | None = None
    pincode: str | None = None
    state: str | None = "NSW"
    createdAt: datetime
    itemCount: int = 0
    totalValue: float = 0.0
    preview_images: list[str] = []


# --- User / Username Schemas ---

class UserProfileResponse(BaseModel):
    id: str
    username: str
    usernameSetByUser: bool
    usernameChangedAt: datetime | None = None


class UsernameAvailableResponse(BaseModel):
    available: bool
    username: str


class UsernameUpdateRequest(BaseModel):
    username: str


class PublicUserResponse(BaseModel):
    username: str
    joinedAt: datetime | None = None


# --- Messaging Schemas ---

class MessageContext(BaseModel):
    saleEventId: str
    bundleId: str | None = None
    itemId: str | None = None


class SendMessageRequest(BaseModel):
    text: str
    context: MessageContext | None = None


class PinSnapshot(BaseModel):
    name: str | None = None
    imageUrl: str | None = None
    price: float | None = None
    rrp: float | None = None
    condition: str | None = None
    itemCount: int | None = None
    suburb: str | None = None


class SetPinRequest(BaseModel):
    kind: Literal["item", "bundle", "sale"] | None = None
    saleEventId: str | None = None
    bundleId: str | None = None
    itemId: str | None = None


class MessageResponse(BaseModel):
    id: str
    senderId: str
    text: str
    createdAt: str | None = None
    type: str = "text"
    subtype: str | None = None
    context: MessageContext | None = None
    pinSnapshot: PinSnapshot | None = None


class ConversationStartRequest(BaseModel):
    otherUserId: str
    initialMessage: str | None = None
    context: MessageContext | None = None


class ConversationStartResponse(BaseModel):
    conversationId: str
    created: bool


class ConversationSummaryResponse(BaseModel):
    id: str
    otherUserId: str | None = None
    otherUsername: str | None = None
    lastMessage: str | None = None
    lastMessageAt: str | None = None
    unreadCount: int = 0
    status: str = "active"
    updatedAt: str | None = None
    pinSnapshot: PinSnapshot | None = None


class MessagesListResponse(BaseModel):
    messages: list[MessageResponse]
    conversationId: str


class UnreadCountResponse(BaseModel):
    unreadCount: int


# --- Saved / Watchlist Schemas ---

class SavedSaleData(BaseModel):
    eventId: str
    suburb: str | None = None
    state: str | None = None
    itemCount: int = 0
    moveOutDate: str | None = None
    savedAt: datetime | None = None


class SavedItemData(BaseModel):
    itemId: str
    bundleId: str | None = None
    eventId: str | None = None
    name: str | None = None
    brand: str | None = None
    condition: str | None = None
    price: float | None = None
    suburb: str | None = None
    image_url: str | None = None
    savedAt: datetime | None = None


class SavedListResponse(BaseModel):
    saved_sales: list[SavedSaleData]
    saved_items: list[SavedItemData]


class SaveToggleResponse(BaseModel):
    saved: bool
