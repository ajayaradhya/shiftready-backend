from enum import Enum


class SaleStatus(str, Enum):
    # Discovery
    PENDING_UPLOAD = "pending_upload"
    PROCESSING = "processing"

    # Review
    READY_FOR_REVIEW = "ready_for_review"
    PRICING_IN_PROGRESS = "pricing_in_progress"

    # Active
    LIVE = "live"
    PARTIALLY_SOLD = "partially_sold"

    # Conclusion
    EXPIRED = "expired"
    ARCHIVED = "archived"
    FAILED = "failed"
