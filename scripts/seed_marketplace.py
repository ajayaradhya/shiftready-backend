"""
Seed marketplace test data directly into production Firestore + GCS.
Creates 3 LIVE sales with realistic bundles, items, and images.
"""
import os
import sys
import uuid
import asyncio
import requests as req
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from google.cloud import firestore, storage

BUCKET = os.getenv("GCP_UPLOAD_BUCKET", "shiftready-uploads-bucket")

USER_AJAY = "IRnHCqwOkCcTagOqrilpaIpsCgB2"
USER_BOB = "PcxF9ZV1rtP2WQUXeLp7UUYHBCS2"

# Picsum image IDs that look like furniture/household items
IMAGE_MAP = {
    "sofa":          "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=800&q=80",
    "coffee_table":  "https://images.unsplash.com/photo-1530018607912-eff2daa1bac4?w=800&q=80",
    "floor_lamp":    "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=800&q=80",
    "dining_table":  "https://images.unsplash.com/photo-1577140917170-285929fb55b7?w=800&q=80",
    "microwave":     "https://images.unsplash.com/photo-1574269909862-7e1d70bb8078?w=800&q=80",
    "blender":       "https://images.unsplash.com/photo-1570222094114-d054a817e56b?w=800&q=80",
    "bed_frame":     "https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?w=800&q=80",
    "wardrobe":      "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800&q=80",
    "desk":          "https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?w=800&q=80",
    "office_chair":  "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=800&q=80",
    "bookshelf":     "https://images.unsplash.com/photo-1507842217343-583bb7270b66?w=800&q=80",
    "tv_unit":       "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=800&q=80",
    "outdoor_table": "https://images.unsplash.com/photo-1600210492493-0946911123ea?w=800&q=80",
    "armchair":      "https://images.unsplash.com/photo-1567538096621-38d2284b23ff?w=800&q=80",
    "sideboard":     "https://images.unsplash.com/photo-1595515106969-1ce29566ff1c?w=800&q=80",
}

uploaded_cache: dict[str, str] = {}


def upload_image(storage_client: storage.Client, key: str) -> str | None:
    if key in uploaded_cache:
        return uploaded_cache[key]
    url = IMAGE_MAP.get(key)
    if not url:
        return None
    try:
        print(f"  Downloading image: {key}...")
        resp = req.get(url, timeout=15)
        resp.raise_for_status()
        gcs_path = f"seed/items/{key}.jpg"
        bucket = storage_client.bucket(BUCKET)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(resp.content, content_type="image/jpeg")
        full_path = f"gs://{BUCKET}/{gcs_path}"
        uploaded_cache[key] = full_path
        print(f"  Uploaded -> {full_path}")
        return full_path
    except Exception as e:
        print(f"  Warning: could not upload {key}: {e}")
        return None


def make_image(gcs_path: str | None, is_cover: bool = True) -> list[dict]:
    if not gcs_path:
        return []
    return [{
        "id": str(uuid.uuid4())[:8],
        "gcs_path": gcs_path,
        "source": "frame_extract",
        "is_cover": is_cover,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }]


SALES_DATA = [
    {
        "seller": USER_AJAY,
        "title": "Surry Hills Moving Sale",
        "suburb": "Surry Hills",
        "state": "NSW",
        "description": "Moving interstate! Quality furniture from our 2BR apartment. All items well-maintained, smoke-free home.",
        "move_out_date": (datetime.now(timezone.utc) + timedelta(days=18)).strftime("%Y-%m-%d"),
        "street_address": "45 Crown St",
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
    {
        "seller": USER_BOB,
        "title": "Newtown Relocation — Everything Must Go",
        "suburb": "Newtown",
        "state": "NSW",
        "description": "Relocating overseas. Selling quality bedroom and study furniture. Pick up only, flexible on price.",
        "move_out_date": (datetime.now(timezone.utc) + timedelta(days=25)).strftime("%Y-%m-%d"),
        "street_address": "12 King St",
        "bundles": [
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
        ],
    },
    {
        "seller": USER_AJAY,
        "title": "Bondi Downsizing — Designer Pieces",
        "suburb": "Bondi",
        "state": "NSW",
        "description": "Downsizing from a 3BR house to an apartment. Beautiful designer furniture, all original receipts available.",
        "move_out_date": (datetime.now(timezone.utc) + timedelta(days=35)).strftime("%Y-%m-%d"),
        "street_address": "88 Campbell Parade",
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
                        "image_key": "sofa",
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
        ],
    },
]


async def seed(db: firestore.AsyncClient, gcs: storage.Client):
    now = datetime.now(timezone.utc)

    for sale_def in SALES_DATA:
        sale_ref = db.collection("saleEvents").document()
        event_id = sale_ref.id
        print(f"\nCreating sale: {sale_def['title']} ({event_id})")

        await sale_ref.set({
            "sellerId": sale_def["seller"],
            "status": "live",
            "title": sale_def["title"],
            "description": sale_def["description"],
            "suburb": sale_def["suburb"],
            "state": sale_def["state"],
            "streetAddress": sale_def["street_address"],
            "moveOutDate": sale_def["move_out_date"],
            "captureMode": "live",
            "publishedAt": now,
            "createdAt": now,
            "updatedAt": now,
            "statusHistory": [
                {"status": "pending_upload", "timestamp": now},
                {"status": "live", "timestamp": now},
            ],
        })

        for bundle_def in sale_def["bundles"]:
            b_ref = sale_ref.collection("bundles").document()
            await b_ref.set({
                "name": bundle_def["name"],
                "createdAt": now,
            })
            print(f"  Bundle: {bundle_def['name']} ({b_ref.id})")

            for item_def in bundle_def["items"]:
                image_key = item_def.pop("image_key", None)
                gcs_path = upload_image(gcs, image_key) if image_key else None
                images = make_image(gcs_path)

                i_ref = b_ref.collection("items").document()
                await i_ref.set({
                    **item_def,
                    "images": images,
                    "predicted_listing_price": item_def.get("actual_listing_price"),
                    "predicted_original_price": item_def.get("actual_original_price"),
                    "predicted_year_of_purchase": item_def.get("actual_year_of_purchase"),
                    "pricing_reasoning": f"Priced at market value for {item_def.get('condition')} condition {item_def.get('brand')} item.",
                    "sale_status": "available",
                    "createdAt": now,
                })
                print(f"    Item: {item_def['name']} -> ${item_def.get('actual_listing_price')}")

        print(f"  [OK] Sale created: {event_id}")

    print("\nSeed complete!")


async def main():
    db = firestore.AsyncClient()
    gcs = storage.Client()
    await seed(db, gcs)


if __name__ == "__main__":
    asyncio.run(main())
