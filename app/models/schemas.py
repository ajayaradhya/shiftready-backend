from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.status import SaleStatus


# --- Sale Initialization ---

class CaptureInitResponse(BaseModel):
    event_id: str


class CaptureFrameResponse(BaseModel):
    name: str
    brand: str
    predicted_original_price: float
    gcs_uri: str


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


class BundleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    bundle_discount_percent: float | None = Field(default=None, ge=0, le=100)


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
    dimensions: str | None = None
    material: str | None = None
    is_fragile: bool = False
    disassembly_required: bool = False
    description: str | None = None
    category: str | None = None
    quantity: int | None = None


class ItemCreateResponse(BaseModel):
    item_id: str


class ItemCategory(str, Enum):
    furniture = "furniture"
    appliance = "appliance"
    electronics = "electronics"
    decor = "decor"
    clothing = "clothing"
    books_media = "books_media"
    sports_fitness = "sports_fitness"
    garden_outdoor = "garden_outdoor"
    kitchen_dining = "kitchen_dining"
    baby_kids = "baby_kids"
    tools_hardware = "tools_hardware"
    toys_games = "toys_games"
    lighting = "lighting"
    storage = "storage"
    other = "other"


class ItemUpdate(BaseModel):
    """Strict schema for PATCH operations to avoid overwriting unrelated fields."""
    name: str | None = None
    brand: str | None = None
    actual_listing_price: float | None = None
    predicted_listing_price: float | None = None
    actual_original_price: float | None = None
    actual_year_of_purchase: int | None = None
    condition: str | None = None
    dimensions: str | None = None
    material: str | None = None
    is_fragile: bool | None = None
    disassembly_required: bool | None = None
    description: str | None = Field(default=None, max_length=500)
    pricing_reasoning: str | None = Field(default=None, max_length=1000)
    category: ItemCategory | None = None
    quantity: int | None = Field(default=None, ge=1)


class ItemMoveRequest(BaseModel):
    to_bundle_id: str


class ItemRepriceResponse(BaseModel):
    predicted_listing_price: float
    actual_listing_price: float
    pricing_reasoning: str


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
    title: str | None = None


# --- User / Username Schemas ---

class UserProfileResponse(BaseModel):
    id: str
    username: str
    usernameSetByUser: bool
    usernameChangedAt: datetime | None = None


class NotifPrefs(BaseModel):
    msg: bool = True
    offer: bool = True
    counter: bool = True
    deal: bool = True
    ready: bool = True
    viewed: bool = False
    buy_msg: bool = True
    buy_offer: bool = True
    price_drop: bool = False


class SellerPrefs(BaseModel):
    paymentMethods: list[str] = ["cash", "bank", "payid"]
    pickupDays: list[str] = ["Weekdays", "Weekends"]
    pickupTimes: list[str] = ["Afternoon (12–5)"]
    minOfferPercent: int = 70


class PrivacyPrefs(BaseModel):
    messagingFilter: str = "anyone"
    profileVisible: bool = True


class UserSettingsResponse(BaseModel):
    id: str
    username: str
    usernameSetByUser: bool
    usernameChangedAt: datetime | None = None
    displayName: str | None = None
    bio: str | None = None
    phoneE164: str | None = None
    phoneShareOptIn: bool = True
    suburb: str | None = None
    state: str | None = None
    joinedAt: datetime | None = None
    notifPrefs: NotifPrefs = NotifPrefs()
    sellerPrefs: SellerPrefs = SellerPrefs()
    privacyPrefs: PrivacyPrefs = PrivacyPrefs()


class ProfileUpdateRequest(BaseModel):
    displayName: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=240)


class LocationUpdateRequest(BaseModel):
    suburb: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=10)


class NotificationsUpdateRequest(BaseModel):
    prefs: NotifPrefs


class PreferencesUpdateRequest(BaseModel):
    prefs: SellerPrefs


class PrivacyUpdateRequest(BaseModel):
    prefs: PrivacyPrefs


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


class PinRef(BaseModel):
    kind: Literal["item", "bundle", "sale"]
    saleEventId: str
    bundleId: str | None = None
    itemId: str | None = None


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


class OfferPayload(BaseModel):
    offerId: str
    amount: float
    currency: str = "AUD"
    listPrice: float | None = None
    parentOfferId: str | None = None
    status: Literal["pending", "countered", "accepted", "withdrawn"]
    pinTarget: PinRef | None = None


class SendOfferRequest(BaseModel):
    amount: float
    parentOfferId: str | None = None


class CounterOfferRequest(BaseModel):
    amount: float


class OfferResponse(BaseModel):
    offerId: str
    amount: float
    currency: str = "AUD"
    listPrice: float | None = None
    parentOfferId: str | None = None
    status: str
    senderUid: str
    createdAt: str | None = None
    updatedAt: str | None = None


class MessageResponse(BaseModel):
    id: str
    senderId: str
    text: str
    createdAt: str | None = None
    type: str = "text"
    subtype: str | None = None
    context: MessageContext | None = None
    pinSnapshot: PinSnapshot | None = None
    offerPayload: OfferPayload | None = None


class ConversationStartRequest(BaseModel):
    otherUserId: str
    initialMessage: str | None = None
    context: MessageContext | None = None


class ConversationStartResponse(BaseModel):
    conversationId: str
    created: bool


class PhoneUpdateRequest(BaseModel):
    phoneE164: str
    shareOptIn: bool = True


class PhoneRevealResponse(BaseModel):
    phoneE164: str


class ConversationSummaryResponse(BaseModel):
    id: str
    otherUserId: str | None = None
    otherUsername: str | None = None
    lastMessage: str | None = None
    lastMessageAt: str | None = None
    unreadCount: int = 0
    status: str = "active"
    updatedAt: str | None = None
    pin: PinRef | None = None
    pinSnapshot: PinSnapshot | None = None
    activeOfferId: str | None = None
    dealStatus: str = "none"
    phoneSharedByMe: bool = False
    phoneRevealAvailable: bool = False
    otherLastSeenAt: str | None = None
    otherVerified: bool = False


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


# --- Sold Lifecycle Schemas ---

class MarkSoldRequest(BaseModel):
    final_price: float | None = None
    buyer_uid: str | None = None
    buyer_label: str | None = None
    conversation_id: str | None = None
    offer_id: str | None = None
    payment_method: str | None = None
    notes: str | None = Field(default=None, max_length=500)


class MarkBundleSoldRequest(BaseModel):
    scope: Literal["bundle_as_unit", "all_items"] = "bundle_as_unit"
    final_price: float | None = None
    buyer_uid: str | None = None
    buyer_label: str | None = None
    conversation_id: str | None = None
    payment_method: str | None = None
    notes: str | None = Field(default=None, max_length=500)


class MarkSaleSoldRequest(BaseModel):
    final_price: float | None = None
    buyer_uid: str | None = None
    buyer_label: str | None = None
    payment_method: str | None = None
    notes: str | None = Field(default=None, max_length=500)


class WithdrawRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class TransactionResponse(BaseModel):
    id: str
    type: str
    granularity: str
    amount: float | None = None
    paymentMethod: str | None = None
    buyerUid: str | None = None
    buyerLabel: str | None = None
    sellerUid: str | None = None
    actorUid: str | None = None
    notes: str | None = None
    bundleId: str | None = None
    itemId: str | None = None
    createdAt: datetime | None = None
