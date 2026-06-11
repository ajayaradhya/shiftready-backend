"""
Realistic seed: users → sales/bundles/items → lifecycle states → conversations/offers/transactions.
Single idempotent script. Replaces seed_marketplace.py + seed_10_users.py.

Run AFTER wipe_all.py:
    python scripts/wipe_all.py --yes
    python scripts/seed_realistic.py
"""
import asyncio
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests as req
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from google.cloud import firestore, storage

from app.repos.bundle_repo import BundleRepo
from app.repos.conversation_repo import ConversationRepo
from app.repos.item_repo import ItemRepo
from app.repos.notification_repo import NotificationRepo
from app.repos.sale_repo import SaleRepo
from app.repos.transaction_repo import TransactionRepo
from app.services.inventory_lifecycle import InventoryLifecycleService

BUCKET = os.getenv("GCP_UPLOAD_BUCKET", "myrio-uploads-bucket")

# ── Users ─────────────────────────────────────────────────────────────────────

SELLER_AJAY = "IRnHCqwOkCcTagOqrilpaIpsCgB2"
SELLER_BOB = "PcxF9ZV1rtP2WQUXeLp7UUYHBCS2"
SELLER_CHLOE = "seedSellerChloe0000000000001"
SELLER_DAVE = "seedSellerDave00000000000001"
BUYER_EMMA = "seedBuyerEmma000000000000001"
BUYER_LIAM = "seedBuyerLiam000000000000001"
BUYER_SOFIA = "seedBuyerSofia00000000000001"
BUYER_MARCUS = "seedBuyerMarcus0000000000001"

USERS = [
    {
        "uid": SELLER_AJAY,
        "email": "be.el.ajay@gmail.com",
        "displayName": "Ajay B",
        "username": "ReadyShifter482",
        "suburb": "Surry Hills",
        "state": "NSW",
        "pincode": "2010",
        "phoneE164": "+61412340001",
        "phoneShareOptIn": True,
    },
    {
        "uid": SELLER_BOB,
        "email": "bob.harris@seedtest.com",
        "displayName": "Bob Harris",
        "username": "SwiftMover721",
        "suburb": "Newtown",
        "state": "NSW",
        "pincode": "2042",
        "phoneE164": "+61412340002",
        "phoneShareOptIn": True,
    },
    {
        "uid": SELLER_CHLOE,
        "email": "chloe.m@seedtest.com",
        "displayName": "Chloe M",
        "username": "CalmPacker334",
        "suburb": "Mosman",
        "state": "NSW",
        "pincode": "2088",
        "phoneE164": "+61412340003",
        "phoneShareOptIn": True,
    },
    {
        "uid": SELLER_DAVE,
        "email": "dave.p@seedtest.com",
        "displayName": "Dave P",
        "username": "BoldMover659",
        "suburb": "Paddington",
        "state": "NSW",
        "pincode": "2021",
        "phoneE164": "+61412340004",
        "phoneShareOptIn": False,
    },
    {
        "uid": BUYER_EMMA,
        "email": "emma.b@seedtest.com",
        "displayName": "Emma B",
        "username": "KindFinder892",
        "suburb": "Pyrmont",
        "state": "NSW",
        "pincode": "2009",
        "phoneE164": "+61412340005",
        "phoneShareOptIn": True,
    },
    {
        "uid": BUYER_LIAM,
        "email": "liam.k@seedtest.com",
        "displayName": "Liam K",
        "username": "WarmSeeker445",
        "suburb": "Glebe",
        "state": "NSW",
        "pincode": "2037",
        "phoneE164": "+61412340006",
        "phoneShareOptIn": True,
    },
    {
        "uid": BUYER_SOFIA,
        "email": "sofia.r@seedtest.com",
        "displayName": "Sofia R",
        "username": "NeatPicker217",
        "suburb": "Chatswood",
        "state": "NSW",
        "pincode": "2067",
        "phoneE164": "+61412340007",
        "phoneShareOptIn": True,
    },
    {
        "uid": BUYER_MARCUS,
        "email": "marcus.t@seedtest.com",
        "displayName": "Marcus T",
        "username": "QuickHandler583",
        "suburb": "Bondi",
        "state": "NSW",
        "pincode": "2026",
        "phoneE164": "+61412340008",
        "phoneShareOptIn": False,
    },
]

# ── Images ────────────────────────────────────────────────────────────────────

IMAGE_MAP = {
    "sofa": "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=1600&q=85",
    "coffee_table": "https://images.unsplash.com/photo-1530018607912-eff2daa1bac4?w=1600&q=85",
    # Arc floor lamp with brass finish — was previously a desk lamp
    "floor_lamp": "https://images.unsplash.com/photo-1513506003901-1e6a35c31e0c?w=1600&q=85",
    "dining_table": "https://images.unsplash.com/photo-1577140917170-285929fb55b7?w=1600&q=85",
    "microwave": "https://images.unsplash.com/photo-1574269909862-7e1d70bb8078?w=1600&q=85",
    # Blender on kitchen counter — was previously an ambiguous tool image
    "blender": "https://images.unsplash.com/photo-1585515320310-259814833e62?w=1600&q=85",
    "bed_frame": "https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?w=1600&q=85",
    "wardrobe": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=1600&q=85",
    "desk": "https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?w=1600&q=85",
    "office_chair": "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=1600&q=85",
    "bookshelf": "https://images.unsplash.com/photo-1507842217343-583bb7270b66?w=1600&q=85",
    "tv_unit": "https://images.unsplash.com/photo-1593784991095-a205069470b6?w=1600&q=85",
    # Outdoor dining table setting — was previously a living-room scene
    "outdoor_table": "https://images.unsplash.com/photo-1472224371017-08207f84aaae?w=1600&q=85",
    "armchair": "https://images.unsplash.com/photo-1567538096621-38d2284b23ff?w=1600&q=85",
    "sideboard": "https://images.unsplash.com/photo-1595515106969-1ce29566ff1c?w=1600&q=85",
    "corner_sofa": "https://images.unsplash.com/photo-1484101403633-562f891dc89a?w=1600&q=85",
}

_image_cache: dict[str, dict] = {}


def _resize(img_bytes: bytes, max_width: int) -> bytes:
    img = Image.open(io.BytesIO(img_bytes))
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    out = io.BytesIO()
    img = img.convert("RGB")
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def make_images(gcs: storage.Client, key: str, is_cover: bool = True) -> list[dict]:
    """Download Unsplash image, produce full/medium/thumb variants, upload to GCS."""
    if key in _image_cache:
        cached = _image_cache[key]
        img_id = str(uuid.uuid4())[:8]
        return [{
            "id": img_id,
            "gcs_path": cached["gcs_path"],
            "thumb_gcs_path": cached["thumb_gcs_path"],
            "medium_gcs_path": cached["medium_gcs_path"],
            "source": "frame_extract",
            "is_cover": is_cover,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }]

    url = IMAGE_MAP.get(key)
    if not url:
        print(f"  Warning: no URL for key {key}")
        return []

    print(f"  Downloading {key}...")
    try:
        resp = req.get(url, timeout=20)
        resp.raise_for_status()
        raw = resp.content
    except Exception as e:
        print(f"  Warning: download failed for {key}: {e}")
        return []

    bucket = gcs.bucket(BUCKET)

    def upload(variant: str, data: bytes) -> str:
        path = f"seed/items/{key}_{variant}.jpg"
        blob = bucket.blob(path)
        blob.upload_from_string(data, content_type="image/jpeg")
        return f"gs://{BUCKET}/{path}"

    full_path = upload("full", _resize(raw, 1600))
    medium_path = upload("medium", _resize(raw, 800))
    thumb_path = upload("thumb", _resize(raw, 320))

    _image_cache[key] = {
        "gcs_path": full_path,
        "medium_gcs_path": medium_path,
        "thumb_gcs_path": thumb_path,
    }
    print(f"  Uploaded {key} → full/medium/thumb")

    img_id = str(uuid.uuid4())[:8]
    return [{
        "id": img_id,
        "gcs_path": full_path,
        "thumb_gcs_path": thumb_path,
        "medium_gcs_path": medium_path,
        "source": "frame_extract",
        "is_cover": is_cover,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }]


def cover_image_from_images(images: list[dict]) -> dict | None:
    if not images:
        return None
    img = images[0]
    return {
        "gcs_path": img["gcs_path"],
        "thumb_gcs_path": img.get("thumb_gcs_path"),
        "source": "frame_extract",
        "uploaded_at": img["uploaded_at"],
    }


# ── Sales data ────────────────────────────────────────────────────────────────

now = datetime.now(timezone.utc)


def _ts(days_ago: int = 0) -> datetime:
    return now - timedelta(days=days_ago)


SALES_DEF = [
    # ── Sale 1: Ajay Surry Hills — LIVE ──────────────────────────────────────
    {
        "key": "ajay_surry",
        "seller": SELLER_AJAY,
        "title": "Surry Hills Moving Sale",
        "suburb": "Surry Hills",
        "state": "NSW",
        "pincode": "2010",
        "description": "Moving interstate! Quality furniture from our 2BR apartment. All items well-maintained, smoke-free home.",
        "street_address": "45 Crown St",
        "move_out_date": (now + timedelta(days=18)).strftime("%Y-%m-%d"),
        "status": "live",
        "capture_mode": "live",
        "bundles": [
            {
                "name": "Living Room",
                "items": [
                    {
                        "name": "3-Seater Velvet Sofa",
                        "brand": "Nick Scali",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 890.0,
                        "actual_original_price": 2200.0,
                        "actual_year_of_purchase": 2023,
                        "material": "Velvet",
                        "dimensions": "220 x 95 x 85 cm",
                        "colour": "Dusty Blue",
                        "is_fragile": False,
                        "disassembly_required": False,
                        "image_key": "sofa",
                    },
                    {
                        "name": "Marble Coffee Table",
                        "brand": "West Elm",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 320.0,
                        "actual_original_price": 750.0,
                        "actual_year_of_purchase": 2022,
                        "material": "Marble / Steel",
                        "dimensions": "120 x 60 x 42 cm",
                        "colour": "White Marble",
                        "is_fragile": True,
                        "image_key": "coffee_table",
                    },
                    {
                        "name": "Arc Floor Lamp",
                        "brand": "IKEA",
                        "condition": "Good",
                        "category": "decor",
                        "actual_listing_price": 75.0,
                        "actual_original_price": 149.0,
                        "actual_year_of_purchase": 2021,
                        "colour": "Brass",
                        "image_key": "floor_lamp",
                    },
                    {
                        "name": "TV Entertainment Unit",
                        "brand": "Freedom",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 280.0,
                        "actual_original_price": 699.0,
                        "actual_year_of_purchase": 2022,
                        "material": "Oak veneer",
                        "dimensions": "180 x 45 x 55 cm",
                        "colour": "Natural Oak",
                        "image_key": "tv_unit",
                    },
                ],
            },
            {
                "name": "Kitchen & Dining",
                "items": [
                    {
                        "name": "6-Seater Dining Table",
                        "brand": "Pottery Barn",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 650.0,
                        "actual_original_price": 1800.0,
                        "actual_year_of_purchase": 2023,
                        "material": "Solid Acacia",
                        "dimensions": "180 x 90 x 76 cm",
                        "colour": "Dark Walnut",
                        "disassembly_required": True,
                        "image_key": "dining_table",
                    },
                    {
                        "name": "Smeg Microwave",
                        "brand": "Smeg",
                        "condition": "Like New",
                        "category": "appliance",
                        "actual_listing_price": 180.0,
                        "actual_original_price": 399.0,
                        "actual_year_of_purchase": 2023,
                        "colour": "Cream",
                        "image_key": "microwave",
                    },
                    {
                        "name": "Vitamix Blender",
                        "brand": "Vitamix",
                        "condition": "Good",
                        "category": "appliance",
                        "actual_listing_price": 220.0,
                        "actual_original_price": 599.0,
                        "actual_year_of_purchase": 2021,
                        "colour": "Black",
                        "image_key": "blender",
                    },
                ],
            },
        ],
    },
    # ── Sale 2: Bob Newtown — LIVE (becomes PARTIALLY_SOLD after lifecycle) ───
    {
        "key": "bob_newtown",
        "seller": SELLER_BOB,
        "title": "Newtown Relocation — Everything Must Go",
        "suburb": "Newtown",
        "state": "NSW",
        "pincode": "2042",
        "description": "Relocating overseas. Quality bedroom and study furniture. Pick up only, flexible on price.",
        "street_address": "12 King St",
        "move_out_date": (now + timedelta(days=25)).strftime("%Y-%m-%d"),
        "status": "live",
        "capture_mode": "live",
        "bundles": [
            {
                "name": "Home Study",
                "items": [
                    {
                        "name": "Standing Desk (Electric)",
                        "brand": "Flexispot",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 480.0,
                        "actual_original_price": 899.0,
                        "actual_year_of_purchase": 2023,
                        "material": "Bamboo / Steel",
                        "dimensions": "160 x 70 cm",
                        "colour": "Bamboo Natural",
                        "image_key": "desk",
                    },
                    {
                        "name": "Ergonomic Office Chair",
                        "brand": "Herman Miller",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 550.0,
                        "actual_original_price": 1400.0,
                        "actual_year_of_purchase": 2021,
                        "colour": "Black",
                        "image_key": "office_chair",
                    },
                    {
                        "name": "Billy Bookcase (x2)",
                        "brand": "IKEA",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 90.0,
                        "actual_original_price": 199.0,
                        "actual_year_of_purchase": 2020,
                        "dimensions": "80 x 28 x 202 cm each",
                        "colour": "White",
                        "image_key": "bookshelf",
                    },
                ],
            },
            {
                "name": "Master Bedroom",
                "items": [
                    {
                        "name": "Queen Bed Frame + Headboard",
                        "brand": "Koala",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 750.0,
                        "actual_original_price": 1499.0,
                        "actual_year_of_purchase": 2024,
                        "material": "Fabric / Timber",
                        "dimensions": "203 x 153 x 115 cm",
                        "colour": "Slate Grey",
                        "disassembly_required": True,
                        "image_key": "bed_frame",
                    },
                    {
                        "name": "Double-door Wardrobe",
                        "brand": "IKEA PAX",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 200.0,
                        "actual_original_price": 450.0,
                        "actual_year_of_purchase": 2021,
                        "material": "MDF",
                        "dimensions": "100 x 58 x 236 cm",
                        "colour": "White",
                        "disassembly_required": True,
                        "image_key": "wardrobe",
                    },
                    {
                        "name": "Linen Armchair",
                        "brand": "Temple & Webster",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 195.0,
                        "actual_original_price": 499.0,
                        "actual_year_of_purchase": 2022,
                        "material": "Linen",
                        "colour": "Sand",
                        "image_key": "armchair",
                    },
                ],
            },
        ],
    },
    # ── Sale 3: Chloe Mosman — LIVE ───────────────────────────────────────────
    {
        "key": "chloe_mosman",
        "seller": SELLER_CHLOE,
        "title": "Mosman Downsizing — Designer Pieces",
        "suburb": "Mosman",
        "state": "NSW",
        "pincode": "2088",
        "description": "Moving to a smaller place. Beautiful designer furniture, all in excellent condition. Original receipts available.",
        "street_address": "22 Military Rd",
        "move_out_date": (now + timedelta(days=30)).strftime("%Y-%m-%d"),
        "status": "live",
        "capture_mode": "live",
        "bundles": [
            {
                "name": "Lounge",
                "items": [
                    {
                        "name": "L-Shape Corner Sofa",
                        "brand": "King Living",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 2200.0,
                        "actual_original_price": 5800.0,
                        "actual_year_of_purchase": 2023,
                        "material": "Performance Fabric",
                        "dimensions": "285 x 210 x 90 cm",
                        "colour": "Stone",
                        "image_key": "corner_sofa",
                    },
                    {
                        "name": "Timber Sideboard",
                        "brand": "Coco Republic",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 780.0,
                        "actual_original_price": 1999.0,
                        "actual_year_of_purchase": 2022,
                        "material": "Solid Teak",
                        "dimensions": "180 x 45 x 75 cm",
                        "colour": "Natural Teak",
                        "image_key": "sideboard",
                    },
                    {
                        "name": "Brass Arc Floor Lamp",
                        "brand": "Restoration Hardware",
                        "condition": "Good",
                        "category": "decor",
                        "actual_listing_price": 195.0,
                        "actual_original_price": 499.0,
                        "actual_year_of_purchase": 2022,
                        "colour": "Antique Brass",
                        "image_key": "floor_lamp",
                    },
                    {
                        "name": "Linen Club Armchair",
                        "brand": "Jardan",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 490.0,
                        "actual_original_price": 1299.0,
                        "actual_year_of_purchase": 2023,
                        "material": "Linen",
                        "colour": "Ivory",
                        "image_key": "armchair",
                    },
                ],
            },
            {
                "name": "Outdoor",
                "items": [
                    {
                        "name": "Teak Outdoor Dining Table",
                        "brand": "Barlow Tyrie",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 600.0,
                        "actual_original_price": 1800.0,
                        "actual_year_of_purchase": 2021,
                        "material": "Teak",
                        "dimensions": "200 x 100 cm",
                        "colour": "Teak",
                        "image_key": "outdoor_table",
                    },
                ],
            },
        ],
    },
    # ── Sale 4: Dave Paddington — LIVE ────────────────────────────────────────
    {
        "key": "dave_paddington",
        "seller": SELLER_DAVE,
        "title": "Paddington Apartment Clearance",
        "suburb": "Paddington",
        "state": "NSW",
        "pincode": "2021",
        "description": "Clearing out apartment before heading overseas. Good condition items, priced to sell fast.",
        "street_address": "9 Oxford St",
        "move_out_date": (now + timedelta(days=14)).strftime("%Y-%m-%d"),
        "status": "live",
        "capture_mode": "frames",
        "bundles": [
            {
                "name": "Bedroom",
                "items": [
                    {
                        "name": "King Bed Frame",
                        "brand": "Domayne",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 680.0,
                        "actual_original_price": 1299.0,
                        "actual_year_of_purchase": 2021,
                        "material": "Solid Timber",
                        "dimensions": "213 x 183 cm",
                        "colour": "Walnut",
                        "disassembly_required": True,
                        "image_key": "bed_frame",
                    },
                    {
                        "name": "Sliding Door Wardrobe",
                        "brand": "IKEA PAX",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 180.0,
                        "actual_original_price": 380.0,
                        "actual_year_of_purchase": 2020,
                        "material": "MDF",
                        "dimensions": "150 x 58 x 236 cm",
                        "colour": "White",
                        "disassembly_required": True,
                        "image_key": "wardrobe",
                    },
                ],
            },
            {
                "name": "Kitchen",
                "items": [
                    {
                        "name": "Panasonic Microwave",
                        "brand": "Panasonic",
                        "condition": "Good",
                        "category": "appliance",
                        "actual_listing_price": 150.0,
                        "actual_original_price": 299.0,
                        "actual_year_of_purchase": 2022,
                        "colour": "Silver",
                        "image_key": "microwave",
                    },
                    {
                        "name": "Breville Blender",
                        "brand": "Breville",
                        "condition": "Like New",
                        "category": "appliance",
                        "actual_listing_price": 200.0,
                        "actual_original_price": 399.0,
                        "actual_year_of_purchase": 2023,
                        "colour": "Stainless",
                        "image_key": "blender",
                    },
                    {
                        "name": "Timber Bookshelf",
                        "brand": "Scandi Living",
                        "condition": "Good",
                        "category": "furniture",
                        "actual_listing_price": 70.0,
                        "actual_original_price": 179.0,
                        "actual_year_of_purchase": 2021,
                        "colour": "Oak",
                        "image_key": "bookshelf",
                    },
                ],
            },
        ],
    },
    # ── Sale 5: Ajay Bondi — READY_FOR_REVIEW ────────────────────────────────
    {
        "key": "ajay_bondi_review",
        "seller": SELLER_AJAY,
        "title": "Bondi Designer Furniture",
        "suburb": "Bondi",
        "state": "NSW",
        "pincode": "2026",
        "description": "High-end designer pieces from a 3BR house downsizing. All receipts available.",
        "street_address": "88 Campbell Parade",
        "move_out_date": (now + timedelta(days=40)).strftime("%Y-%m-%d"),
        "status": "ready_for_review",
        "capture_mode": "live",
        "bundles": [
            {
                "name": "Lounge",
                "items": [
                    {
                        "name": "3-Seater Linen Sofa",
                        "brand": "Jardan",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 2800.0,
                        "actual_original_price": 6500.0,
                        "actual_year_of_purchase": 2023,
                        "material": "Linen",
                        "dimensions": "240 x 100 x 85 cm",
                        "colour": "Natural",
                        "image_key": "sofa",
                    },
                    {
                        "name": "Solid Teak Sideboard",
                        "brand": "Coco Republic",
                        "condition": "Like New",
                        "category": "furniture",
                        "actual_listing_price": 950.0,
                        "actual_original_price": 2499.0,
                        "actual_year_of_purchase": 2022,
                        "material": "Solid Teak",
                        "dimensions": "200 x 50 x 80 cm",
                        "colour": "Natural Teak",
                        "image_key": "sideboard",
                    },
                ],
            },
        ],
    },
    # ── Sale 6: Chloe Chatswood — PENDING_UPLOAD (draft) ─────────────────────
    {
        "key": "chloe_chatswood_draft",
        "seller": SELLER_CHLOE,
        "title": "Chatswood Unit Clearance",
        "suburb": "Chatswood",
        "state": "NSW",
        "pincode": "2067",
        "description": "",
        "street_address": "5 Victoria Ave",
        "move_out_date": (now + timedelta(days=50)).strftime("%Y-%m-%d"),
        "status": "pending_upload",
        "capture_mode": None,
        "bundles": [],
    },
]


# ── Phase 1: Seed users ───────────────────────────────────────────────────────

async def seed_users(db: firestore.AsyncClient) -> None:
    print("\n── Phase 1: Users ──")
    for u in USERS:
        uid = u["uid"]
        user_data = {
            "email": u["email"],
            "displayName": u["displayName"],
            "username": u["username"],
            "usernameLower": u["username"].lower(),
            "suburb": u["suburb"],
            "state": u["state"],
            "phoneE164": u["phoneE164"],
            "phoneShareOptIn": u["phoneShareOptIn"],
            "createdAt": now,
            "updatedAt": now,
        }
        await db.collection("users").document(uid).set(user_data)
        await db.collection("usernames").document(u["username"].lower()).set({"uid": uid})
        print(f"  User: {u['displayName']} ({uid[:16]}...)")
    print(f"  Created {len(USERS)} users")


# ── Phase 2: Seed sales / bundles / items ─────────────────────────────────────

async def seed_sales(
    db: firestore.AsyncClient,
    gcs: storage.Client,
) -> dict[str, dict]:
    """Returns {sale_key: {event_id, bundles: {bundle_name: {bundle_id, items: {item_name: item_id}}}}}"""
    print("\n── Phase 2: Sales / Bundles / Items ──")
    result: dict[str, dict] = {}

    for sale_def in SALES_DEF:
        sale_ref = db.collection("saleEvents").document()
        event_id = sale_ref.id
        sale_key = sale_def["key"]

        status = sale_def["status"]
        status_history = [{"status": "pending_upload", "timestamp": _ts(7)}]

        if status not in ("pending_upload",):
            status_history.append({"status": "processing", "timestamp": _ts(6)})
            status_history.append({"status": "ready_for_review", "timestamp": _ts(5)})
        if status in ("live", "partially_sold"):
            status_history.append({"status": "pricing_in_progress", "timestamp": _ts(4)})
            status_history.append({"status": "live", "timestamp": _ts(3)})

        sale_doc: dict = {
            "sellerId": sale_def["seller"],
            "status": status,
            "title": sale_def["title"],
            "suburb": sale_def["suburb"],
            "state": sale_def["state"],
            "pincode": sale_def["pincode"],
            "description": sale_def["description"],
            "streetAddress": sale_def["street_address"],
            "moveOutDate": sale_def["move_out_date"],
            "captureMode": sale_def["capture_mode"],
            "statusHistory": status_history,
            "createdAt": _ts(7),
            "updatedAt": now,
        }
        if status in ("live", "partially_sold"):
            sale_doc["publishedAt"] = _ts(3)

        sale_cover_set = False
        bundle_map: dict[str, dict] = {}

        for bundle_def in sale_def["bundles"]:
            b_ref = sale_ref.collection("bundles").document()
            bundle_id = b_ref.id
            bundle_items: list[dict] = bundle_def["items"]

            suggested_price = sum(
                i.get("actual_listing_price", 0) or 0 for i in bundle_items
            )
            await b_ref.set({
                "name": bundle_def["name"],
                "suggestedPrice": suggested_price,
                "isPublished": status in ("live", "partially_sold"),
                "sale_status": "available",
                "sold_count": 0,
                "total_count": len(bundle_items),
                "createdAt": _ts(6),
            })

            item_id_map: dict[str, str] = {}
            for item_def in bundle_items:
                image_key = item_def.pop("image_key", None)
                images = make_images(gcs, image_key) if image_key else []

                if not sale_cover_set and images:
                    sale_doc["coverImage"] = cover_image_from_images(images)
                    sale_cover_set = True

                price = item_def.get("actual_listing_price")
                i_ref = b_ref.collection("items").document()
                item_id = i_ref.id

                await i_ref.set({
                    **item_def,
                    "images": images,
                    "confidence": 0.92,
                    "timestamp_label": "",
                    "predicted_listing_price": price,
                    "predicted_original_price": item_def.get("actual_original_price"),
                    "predicted_year_of_purchase": item_def.get("actual_year_of_purchase"),
                    "pricing_reasoning": (
                        f"Priced at market value for {item_def.get('condition', '')} "
                        f"condition {item_def.get('brand', '')} item."
                    ),
                    "sale_status": "available",
                    "createdAt": _ts(5),
                })
                item_id_map[item_def["name"]] = item_id
                print(f"    Item: {item_def['name']} → ${price}")

            bundle_map[bundle_def["name"]] = {
                "bundle_id": bundle_id,
                "items": item_id_map,
            }
            print(f"  Bundle: {bundle_def['name']} ({bundle_id[:8]}...)")

        await sale_ref.set(sale_doc)
        result[sale_key] = {"event_id": event_id, "bundles": bundle_map}
        print(f"\nSale [{sale_key}] → {event_id} (status={status})")

    return result


# ── Phase 3: Lifecycle states ─────────────────────────────────────────────────

async def seed_lifecycle(
    db: firestore.AsyncClient,
    sales: dict[str, dict],
) -> None:
    print("\n── Phase 3: Lifecycle ──")

    bundle_repo = BundleRepo(db)
    item_repo = ItemRepo(db, bundle_repo)
    sale_repo = SaleRepo(db)
    tx_repo = TransactionRepo(db)
    lifecycle = InventoryLifecycleService(db, item_repo, bundle_repo, sale_repo, tx_repo)

    # Sale 2 (Bob Newtown): Mark "Queen Bed Frame + Headboard" as SOLD (cash sale by Marcus)
    s2 = sales["bob_newtown"]
    event_id = s2["event_id"]
    master_bundle = s2["bundles"]["Master Bedroom"]
    bundle_id = master_bundle["bundle_id"]
    bed_item_id = master_bundle["items"]["Queen Bed Frame + Headboard"]

    print(f"  Marking bed frame SOLD in sale {event_id[:8]}...")
    await lifecycle.mark_item_sold(
        event_id=event_id,
        bundle_id=bundle_id,
        item_id=bed_item_id,
        actor_uid=SELLER_BOB,
        final_price=700.0,
        buyer_uid=BUYER_MARCUS,
        buyer_label="Marcus T",
        payment_method="cash",
        notes="Sold day one. Buyer picked up same evening.",
    )
    print("  Bed frame → sold. Bob's sale → partially_sold.")


# ── Phase 4: Conversations / offers / transactions ────────────────────────────

async def seed_conversations(
    db: firestore.AsyncClient,
    sales: dict[str, dict],
) -> None:
    print("\n── Phase 4: Conversations ──")

    bundle_repo = BundleRepo(db)
    item_repo = ItemRepo(db, bundle_repo)
    sale_repo = SaleRepo(db)
    tx_repo = TransactionRepo(db)
    lifecycle = InventoryLifecycleService(db, item_repo, bundle_repo, sale_repo, tx_repo)
    conv_repo = ConversationRepo(db)

    # ── Conv 1: Emma (buyer) ↔ Ajay (seller) — sofa deal agreed ──────────────
    s1 = sales["ajay_surry"]
    event_id_s1 = s1["event_id"]
    lr_bundle = s1["bundles"]["Living Room"]
    sofa_item_id = lr_bundle["items"]["3-Seater Velvet Sofa"]
    sofa_bundle_id = lr_bundle["bundle_id"]

    print(f"  Conv 1: Emma ↔ Ajay (sofa, Sale {event_id_s1[:8]}...)")
    conv1_id, _ = await conv_repo.get_or_create_conversation(BUYER_EMMA, SELLER_AJAY)

    # Pin the sofa item
    pin_ref = {
        "kind": "item",
        "eventId": event_id_s1,
        "bundleId": sofa_bundle_id,
        "itemId": sofa_item_id,
    }
    pin_snapshot = {
        "name": "3-Seater Velvet Sofa",
        "brand": "Nick Scali",
        "price": 890.0,
        "condition": "Like New",
    }
    await conv_repo.set_pin(
        conv1_id, pin_ref, pin_snapshot,
        actor_uid=BUYER_EMMA, actor_username="KindFinder892",
    )

    await conv_repo.send_message(
        conv1_id, BUYER_EMMA,
        "Hi! Is the velvet sofa still available?",
    )
    await conv_repo.send_message(
        conv1_id, SELLER_AJAY,
        "Yes! Still available. It's in great condition, barely sat on.",
    )

    # Emma offers $750 (list $890)
    offer1, _ = await conv_repo.send_offer(
        conv1_id, BUYER_EMMA,
        amount=750.0,
        list_price=890.0,
        pin_target=pin_ref,
    )

    # Ajay counters $820
    counter1, _ = await conv_repo.counter_offer(
        conv1_id, offer1["id"],
        counter_uid=SELLER_AJAY,
        new_amount=820.0,
    )

    # Emma accepts $820
    accepted_offer, _, _ = await conv_repo.accept_offer(
        conv1_id, counter1["id"],
        acceptor_uid=BUYER_EMMA,
    )

    # Both share phone after deal
    await conv_repo.share_phone(conv1_id, SELLER_AJAY)
    await conv_repo.share_phone(conv1_id, BUYER_EMMA)

    # Reserve the sofa for Emma
    print(f"    Reserving sofa (item {sofa_item_id[:8]}...) for Emma...")
    await lifecycle.reserve_item(
        event_id=event_id_s1,
        bundle_id=sofa_bundle_id,
        item_id=sofa_item_id,
        buyer_uid=BUYER_EMMA,
        conversation_id=conv1_id,
        offer_id=accepted_offer["id"],
    )
    print("    Sofa → reserved.")

    # ── Conv 2: Liam (buyer) ↔ Bob (seller) — desk, pending offer ────────────
    s2 = sales["bob_newtown"]
    event_id_s2 = s2["event_id"]
    study_bundle = s2["bundles"]["Home Study"]
    desk_item_id = study_bundle["items"]["Standing Desk (Electric)"]
    desk_bundle_id = study_bundle["bundle_id"]

    print(f"  Conv 2: Liam ↔ Bob (desk, Sale {event_id_s2[:8]}...)")
    conv2_id, _ = await conv_repo.get_or_create_conversation(BUYER_LIAM, SELLER_BOB)

    desk_pin_ref = {
        "kind": "item",
        "eventId": event_id_s2,
        "bundleId": desk_bundle_id,
        "itemId": desk_item_id,
    }
    desk_pin_snapshot = {
        "name": "Standing Desk (Electric)",
        "brand": "Flexispot",
        "price": 480.0,
        "condition": "Like New",
    }
    await conv_repo.set_pin(
        conv2_id, desk_pin_ref, desk_pin_snapshot,
        actor_uid=BUYER_LIAM, actor_username="WarmSeeker445",
    )
    await conv_repo.send_message(
        conv2_id, BUYER_LIAM,
        "Hey, is the standing desk still available?",
    )
    await conv_repo.send_message(
        conv2_id, SELLER_BOB,
        "Hi Liam! Yes it is. Can pick up from Newtown, flexible on time.",
    )
    # Liam offers $400 — left pending, no counter/accept
    await conv_repo.send_offer(
        conv2_id, BUYER_LIAM,
        amount=400.0,
        list_price=480.0,
        pin_target=desk_pin_ref,
    )
    print("    Pending offer left open.")

    # ── Conv 3: Sofia (buyer) ↔ Chloe (seller) — sideboard, text only ────────
    s3 = sales["chloe_mosman"]
    print(f"  Conv 3: Sofia ↔ Chloe (sideboard, Sale {s3['event_id'][:8]}...)")
    conv3_id, _ = await conv_repo.get_or_create_conversation(BUYER_SOFIA, SELLER_CHLOE)
    await conv_repo.send_message(
        conv3_id, BUYER_SOFIA,
        "Hello! Is the timber sideboard still available?",
    )
    await conv_repo.send_message(
        conv3_id, SELLER_CHLOE,
        "Hi Sofia! Yes, it's a beautiful solid teak piece in excellent condition.",
    )
    await conv_repo.send_message(
        conv3_id, BUYER_SOFIA,
        "Lovely! Can I come view it this weekend?",
    )
    await conv_repo.send_message(
        conv3_id, SELLER_CHLOE,
        "Saturday works, any time after 10am!",
    )
    print("    Text-only thread seeded.")

    print(f"\n  Conversations: {conv1_id[:12]}... {conv2_id[:12]}... {conv3_id[:12]}...")


# ── Phase 5: Seed notifications ───────────────────────────────────────────────

async def seed_notifications(db: firestore.AsyncClient, sales: dict[str, dict]) -> None:
    """Write representative notifications so the bell feed is non-empty in dev."""
    print("\n── Phase 5: Notifications ──")
    notif_repo = NotificationRepo(db)

    s1 = sales["ajay_surry"]

    # Emma's accepted offer → notify Ajay (seller) that deal is agreed
    await notif_repo.create(
        SELLER_AJAY,
        "offer.accepted",
        "Offer accepted — 3-Seater Velvet Sofa",
        "@KindFinder892 accepted your $820 offer. Exchange contact details to arrange pickup.",
        "/messages",
    )

    # Bob replies to Ajay's enquiry about the standing desk
    await notif_repo.create(
        SELLER_AJAY,
        "message.new",
        "New message from @SwiftMover721",
        "Hi! Yes it is. Can pick up from Newtown, flexible on time.",
        "/market/messages",
    )

    # Emma (buyer) — offer accepted notification
    await notif_repo.create(
        BUYER_EMMA,
        "offer.accepted",
        "Deal agreed — 3-Seater Velvet Sofa",
        "Your offer of $820 was accepted by @ReadyShifter482. Check messages to arrange pickup.",
        "/market/messages",
    )

    # Liam (buyer) — seller replied to his enquiry
    await notif_repo.create(
        BUYER_LIAM,
        "message.new",
        "New message from @GreenMover303",
        "Hi Liam! Yes it is. Can pick up from Newtown, flexible on time.",
        "/market/messages",
    )

    # Ajay — sale is ready for review (sale.ready)
    await notif_repo.create(
        SELLER_AJAY,
        "sale.ready",
        "Bondi sale ready for review",
        "Your inventory has been priced and is ready to publish.",
        f"/seller-central/inventory/{s1['event_id']}",
    )

    print("  Created 5 notifications across Ajay, Emma, Liam")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    db = firestore.AsyncClient()
    gcs = storage.Client()

    await seed_users(db)
    sales = await seed_sales(db, gcs)
    await seed_lifecycle(db, sales)
    await seed_conversations(db, sales)
    await seed_notifications(db, sales)

    print("\nSeed complete!")
    print("\nSpot-check endpoints:")
    print("  GET /marketplace/landing")
    print("  GET /marketplace/search?postcode=2042")
    for key, s in sales.items():
        if "review" not in key and "draft" not in key:
            print(f"  GET /marketplace/sales/{s['event_id']}  ({key})")


if __name__ == "__main__":
    asyncio.run(main())
