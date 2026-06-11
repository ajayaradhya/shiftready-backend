"""
Seed 8 new users + LIVE sales across Sydney.
Real-world personas: students, expats, downsizers, share-house dissolvers.
Heavy on grab-and-go items (<$50).
"""
import os, sys, uuid, asyncio, requests as req
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from google.cloud import firestore, storage

BUCKET = os.getenv("GCP_UPLOAD_BUCKET", "myrio-uploads-bucket")

# Already uploaded in previous seed - skip re-download
PRE_UPLOADED = {
    "sofa":          f"gs://{BUCKET}/seed/items/sofa.jpg",
    "coffee_table":  f"gs://{BUCKET}/seed/items/coffee_table.jpg",
    "floor_lamp":    f"gs://{BUCKET}/seed/items/floor_lamp.jpg",
    "dining_table":  f"gs://{BUCKET}/seed/items/dining_table.jpg",
    "microwave":     f"gs://{BUCKET}/seed/items/microwave.jpg",
    "blender":       f"gs://{BUCKET}/seed/items/blender.jpg",
    "bed_frame":     f"gs://{BUCKET}/seed/items/bed_frame.jpg",
    "wardrobe":      f"gs://{BUCKET}/seed/items/wardrobe.jpg",
    "desk":          f"gs://{BUCKET}/seed/items/desk.jpg",
    "office_chair":  f"gs://{BUCKET}/seed/items/office_chair.jpg",
    "bookshelf":     f"gs://{BUCKET}/seed/items/bookshelf.jpg",
    "outdoor_table": f"gs://{BUCKET}/seed/items/outdoor_table.jpg",
    "armchair":      f"gs://{BUCKET}/seed/items/armchair.jpg",
    "sideboard":     f"gs://{BUCKET}/seed/items/sideboard.jpg",
    "tv_unit":       f"gs://{BUCKET}/seed/items/tv_unit.jpg",
}

NEW_IMAGES = {
    "plant":        "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?w=800&q=80",
    "succulent":    "https://images.unsplash.com/photo-1459156212016-c812468e2115?w=800&q=80",
    "books":        "https://images.unsplash.com/photo-1481627834876-b7833e8f5570?w=800&q=80",
    "yoga_mat":     "https://images.unsplash.com/photo-1601925260368-ae2f83cf8b7f?w=800&q=80",
    "board_game":   "https://images.unsplash.com/photo-1611996575749-79a3a250f948?w=800&q=80",
    "throw_pillow": "https://images.unsplash.com/photo-1579656381226-5fc0f0100c3b?w=800&q=80",
    "coffee_mug":   "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=800&q=80",
    "speaker":      "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?w=800&q=80",
    "kettle":       "https://images.unsplash.com/photo-1585386959984-a4155224a1ad?w=800&q=80",
    "mirror":       "https://images.unsplash.com/photo-1507652313519-d4e9174996dd?w=800&q=80",
    "kids_toy":     "https://images.unsplash.com/photo-1566576912321-d58ddd7a6088?w=800&q=80",
    "art_print":    "https://images.unsplash.com/photo-1513519245088-0e12902e35ca?w=800&q=80",
    "rug":          "https://images.unsplash.com/photo-1600166898405-da9535204843?w=800&q=80",
    "fan":          "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800&q=80",
    "rice_cooker":  "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=800&q=80",
    "toaster":      "https://images.unsplash.com/photo-1584568694244-14fbdf83bd30?w=800&q=80",
    "kids_desk":    "https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?w=800&q=80",
    "dresser":      "https://images.unsplash.com/photo-1595515106969-1ce29566ff1c?w=800&q=80",
    "side_table":   "https://images.unsplash.com/photo-1530018607912-eff2daa1bac4?w=800&q=80",
    "vacuum":       "https://images.unsplash.com/photo-1558317374-067fb5f30001?w=800&q=80",
    "heater":       "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=800&q=80",
    "bike":         "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800&q=80",
    "lego":         "https://images.unsplash.com/photo-1566576912321-d58ddd7a6088?w=800&q=80",
}

upload_cache: dict[str, str] = {**PRE_UPLOADED}


def upload_image(gcs: storage.Client, key: str) -> str | None:
    if key in upload_cache:
        return upload_cache[key]
    url = NEW_IMAGES.get(key)
    if not url:
        return None
    try:
        print(f"    dl {key}...")
        resp = req.get(url, timeout=15)
        resp.raise_for_status()
        gcs_path = f"seed/items/{key}.jpg"
        bucket = gcs.bucket(BUCKET)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(resp.content, content_type="image/jpeg")
        full = f"gs://{BUCKET}/{gcs_path}"
        upload_cache[key] = full
        return full
    except Exception as e:
        print(f"    warn: {key} -> {e}")
        return None


def img(gcs: storage.Client, key: str) -> list[dict]:
    path = upload_image(gcs, key)
    if not path:
        return []
    return [{"id": str(uuid.uuid4())[:8], "gcs_path": path,
             "source": "frame_extract", "is_cover": True,
             "uploaded_at": datetime.now(timezone.utc).isoformat()}]


def dt_from_now(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


NOW = datetime.now(timezone.utc)

# 8 new seed users
USERS = [
    {"uid": "seed_sarah_chen_syd01",  "email": "sarah.chen@example.com",    "displayName": "Sarah Chen",      "username": "SarahC_Moves",    "suburb": "Pyrmont",     "state": "NSW"},
    {"uid": "seed_raj_patel_syd02",   "email": "raj.patel@example.com",     "displayName": "Raj Patel",       "username": "RajFromUltimo",   "suburb": "Ultimo",      "state": "NSW"},
    {"uid": "seed_emma_walsh_syd03",  "email": "emma.walsh@example.com",    "displayName": "Emma Walsh",      "username": "EmmaW_Downsizing","suburb": "Chatswood",   "state": "NSW"},
    {"uid": "seed_marcus_will_syd04", "email": "marcus.w@example.com",      "displayName": "Marcus Williams", "username": "MarcusExpat",     "suburb": "Mosman",      "state": "NSW"},
    {"uid": "seed_zoe_kim_syd05",     "email": "zoe.kim@example.com",       "displayName": "Zoe Kim",         "username": "ZoeK_Glebe",      "suburb": "Glebe",       "state": "NSW"},
    {"uid": "seed_jake_morr_syd06",   "email": "jake.morrison@example.com", "displayName": "Jake Morrison",   "username": "JakeMorrison",    "suburb": "Rozelle",     "state": "NSW"},
    {"uid": "seed_priya_shar_syd07",  "email": "priya.sharma@example.com",  "displayName": "Priya Sharma",    "username": "PriyaS_West",     "suburb": "Parramatta",  "state": "NSW"},
    {"uid": "seed_liam_obri_syd08",   "email": "liam.obrien@example.com",   "displayName": "Liam O'Brien",    "username": "LiamOB",          "suburb": "Paddington",  "state": "NSW"},
]

# ── Sales definitions ─────────────────────────────────────────────────────────
# Each dict: seller uid, sale metadata, bundles with items.
# Items with actual_listing_price < 50 = "grab and go" tier.

def sales_data(gcs: storage.Client) -> list[dict]:
    return [

    # ── 1. Sarah Chen · Pyrmont · IT professional moving to Melbourne ──────────
    {
        "seller": "seed_sarah_chen_syd01",
        "title": "Pyrmont Clear-Out — Moving to Melbourne",
        "suburb": "Pyrmont", "state": "NSW",
        "street_address": "12 Murray St",
        "description": "Got a new job in Melbourne — selling everything from my 1BR apartment. Well looked-after, smoke-free, pet-free home. Pick up only.",
        "move_out_date": dt_from_now(14),
        "bundles": [
            {
                "name": "Lounge",
                "items": [
                    {"name": "2-Seater Linen Sofa", "brand": "Temple & Webster", "condition": "Like New", "category": "furniture", "actual_listing_price": 580.0, "actual_original_price": 1299.0, "actual_year_of_purchase": 2023, "colour": "Sage Green", "material": "Linen", "image_key": "sofa"},
                    {"name": "Round Timber Coffee Table", "brand": "Kmart", "condition": "Good", "category": "furniture", "actual_listing_price": 55.0, "actual_original_price": 129.0, "actual_year_of_purchase": 2022, "image_key": "coffee_table"},
                    {"name": "Set of 2 Throw Pillows", "brand": "Kmart", "condition": "Like New", "category": "decor", "actual_listing_price": 18.0, "actual_original_price": 35.0, "actual_year_of_purchase": 2023, "colour": "Terracotta", "image_key": "throw_pillow"},
                    {"name": "Pothos Plant (hanging)", "brand": None, "condition": "Good", "category": "decor", "actual_listing_price": 12.0, "actual_original_price": 22.0, "actual_year_of_purchase": 2022, "image_key": "plant"},
                    {"name": "Monstera Deliciosa (large)", "brand": None, "condition": "Good", "category": "decor", "actual_listing_price": 35.0, "actual_original_price": 65.0, "actual_year_of_purchase": 2021, "image_key": "plant"},
                    {"name": "Art Print — Abstract Faces", "brand": "Society6", "condition": "Good", "category": "decor", "actual_listing_price": 22.0, "actual_original_price": 55.0, "actual_year_of_purchase": 2022, "image_key": "art_print"},
                ],
            },
            {
                "name": "Bedroom",
                "items": [
                    {"name": "Queen Bed Frame (timber slat)", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 190.0, "actual_original_price": 399.0, "actual_year_of_purchase": 2021, "colour": "White", "image_key": "bed_frame"},
                    {"name": "Bedside Table x2", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 40.0, "actual_original_price": 79.0, "actual_year_of_purchase": 2021, "image_key": "side_table"},
                    {"name": "Full-Length Mirror", "brand": "Kmart", "condition": "Good", "category": "decor", "actual_listing_price": 28.0, "actual_original_price": 49.0, "actual_year_of_purchase": 2022, "image_key": "mirror"},
                    {"name": "Lululemon Yoga Mat", "brand": "Lululemon", "condition": "Good", "category": "other", "actual_listing_price": 38.0, "actual_original_price": 89.0, "actual_year_of_purchase": 2022, "image_key": "yoga_mat"},
                ],
            },
            {
                "name": "Kitchen Grab Bag",
                "items": [
                    {"name": "Smeg Kettle", "brand": "Smeg", "condition": "Like New", "category": "appliance", "actual_listing_price": 45.0, "actual_original_price": 129.0, "actual_year_of_purchase": 2023, "colour": "Pastel Green", "image_key": "kettle"},
                    {"name": "Ceramic Coffee Mug Set x4", "brand": "T2", "condition": "Like New", "category": "other", "actual_listing_price": 20.0, "actual_original_price": 48.0, "actual_year_of_purchase": 2022, "image_key": "coffee_mug"},
                    {"name": "Vitamix Recipe Book", "brand": "Vitamix", "condition": "Like New", "category": "other", "actual_listing_price": 8.0, "actual_original_price": 25.0, "actual_year_of_purchase": 2021, "image_key": "books"},
                    {"name": "Bamboo Cutting Board Set x3", "brand": "Ecology", "condition": "Good", "category": "other", "actual_listing_price": 15.0, "actual_original_price": 39.0, "actual_year_of_purchase": 2022, "image_key": "rice_cooker"},
                    {"name": "Glass Food Container Set (8pc)", "brand": "Pyrex", "condition": "Good", "category": "other", "actual_listing_price": 22.0, "actual_original_price": 55.0, "actual_year_of_purchase": 2022, "image_key": "rice_cooker"},
                ],
            },
        ],
    },

    # ── 2. Raj Patel · Ultimo · Int'l student going back to India ─────────────
    {
        "seller": "seed_raj_patel_syd02",
        "title": "Ultimo Student Clear-Out — Everything Must Go!",
        "suburb": "Ultimo", "state": "NSW",
        "street_address": "88 Ultimo Rd",
        "description": "Finished my Masters at UTS! Flying back to India in 3 weeks — can't take anything. Priced to sell fast. Cash only, same-day pickup preferred.",
        "move_out_date": dt_from_now(20),
        "bundles": [
            {
                "name": "Study Setup",
                "items": [
                    {"name": "Standing Desk (Manual Crank)", "brand": "Officeworks", "condition": "Good", "category": "furniture", "actual_listing_price": 95.0, "actual_original_price": 249.0, "actual_year_of_purchase": 2022, "image_key": "desk"},
                    {"name": "Gaming/Study Chair", "brand": "Secretlab", "condition": "Good", "category": "furniture", "actual_listing_price": 180.0, "actual_original_price": 449.0, "actual_year_of_purchase": 2022, "image_key": "office_chair"},
                    {"name": "USB-C Hub 7-in-1", "brand": "Anker", "condition": "Like New", "category": "electronics", "actual_listing_price": 22.0, "actual_original_price": 59.0, "actual_year_of_purchase": 2023, "image_key": "speaker"},
                    {"name": "Desk Lamp (LED, adjustable)", "brand": "BenQ", "condition": "Good", "category": "electronics", "actual_listing_price": 35.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2022, "image_key": "floor_lamp"},
                    {"name": "Monitor Stand + Drawer", "brand": "Kmart", "condition": "Good", "category": "other", "actual_listing_price": 18.0, "actual_original_price": 39.0, "actual_year_of_purchase": 2022, "image_key": "side_table"},
                    {"name": "Engineering Textbooks x6", "brand": "Various", "condition": "Good", "category": "other", "actual_listing_price": 30.0, "actual_original_price": 280.0, "actual_year_of_purchase": 2021, "image_key": "books"},
                    {"name": "Whiteboard A3 (magnetic)", "brand": "Officeworks", "condition": "Good", "category": "other", "actual_listing_price": 12.0, "actual_original_price": 29.0, "actual_year_of_purchase": 2022, "image_key": "art_print"},
                ],
            },
            {
                "name": "Bedroom Essentials",
                "items": [
                    {"name": "Single Bed Frame (solid pine)", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 65.0, "actual_original_price": 159.0, "actual_year_of_purchase": 2021, "image_key": "bed_frame"},
                    {"name": "Mini Fridge 60L", "brand": "Mistral", "condition": "Good", "category": "appliance", "actual_listing_price": 85.0, "actual_original_price": 199.0, "actual_year_of_purchase": 2022, "image_key": "microwave"},
                    {"name": "Portable Fan (tower)", "brand": "Kogan", "condition": "Good", "category": "appliance", "actual_listing_price": 28.0, "actual_original_price": 69.0, "actual_year_of_purchase": 2022, "image_key": "fan"},
                    {"name": "Coat Hangers x30", "brand": "Kmart", "condition": "Good", "category": "other", "actual_listing_price": 6.0, "actual_original_price": 12.0, "actual_year_of_purchase": 2022, "image_key": "wardrobe"},
                    {"name": "Storage Boxes x4 (stackable)", "brand": "IKEA", "condition": "Good", "category": "other", "actual_listing_price": 14.0, "actual_original_price": 30.0, "actual_year_of_purchase": 2022, "image_key": "side_table"},
                ],
            },
            {
                "name": "Kitchen + Fun Stuff",
                "items": [
                    {"name": "Rice Cooker 1.8L", "brand": "Tiger", "condition": "Good", "category": "appliance", "actual_listing_price": 30.0, "actual_original_price": 89.0, "actual_year_of_purchase": 2022, "image_key": "rice_cooker"},
                    {"name": "2-Slice Toaster", "brand": "Breville", "condition": "Good", "category": "appliance", "actual_listing_price": 20.0, "actual_original_price": 59.0, "actual_year_of_purchase": 2022, "image_key": "toaster"},
                    {"name": "JBL Clip 4 Bluetooth Speaker", "brand": "JBL", "condition": "Good", "category": "electronics", "actual_listing_price": 38.0, "actual_original_price": 89.0, "actual_year_of_purchase": 2022, "image_key": "speaker"},
                    {"name": "Settlers of Catan + Expansion", "brand": "Catan Studio", "condition": "Good", "category": "other", "actual_listing_price": 28.0, "actual_original_price": 75.0, "actual_year_of_purchase": 2021, "image_key": "board_game"},
                    {"name": "Uno + Skip-Bo Card Games", "brand": "Mattel", "condition": "Good", "category": "other", "actual_listing_price": 8.0, "actual_original_price": 22.0, "actual_year_of_purchase": 2021, "image_key": "board_game"},
                    {"name": "Power Board (4-outlet + USB)", "brand": "Belkin", "condition": "Good", "category": "electronics", "actual_listing_price": 18.0, "actual_original_price": 45.0, "actual_year_of_purchase": 2022, "image_key": "speaker"},
                ],
            },
        ],
    },

    # ── 3. Emma Walsh · Chatswood · Retiring couple downsizing ────────────────
    {
        "seller": "seed_emma_walsh_syd03",
        "title": "Chatswood Downsizing — Quality Furniture, Reasonable Prices",
        "suburb": "Chatswood", "state": "NSW",
        "street_address": "23 Victor St",
        "description": "Moving to a smaller apartment after 20 years in our family home. Everything is high quality and well-maintained. Happy to negotiate on bundles.",
        "move_out_date": dt_from_now(30),
        "bundles": [
            {
                "name": "Formal Dining",
                "items": [
                    {"name": "8-Seater Timber Dining Table", "brand": "Coco Republic", "condition": "Excellent", "category": "furniture", "actual_listing_price": 850.0, "actual_original_price": 2400.0, "actual_year_of_purchase": 2019, "material": "Solid Oak", "image_key": "dining_table"},
                    {"name": "Upholstered Dining Chair x6", "brand": "Coco Republic", "condition": "Excellent", "category": "furniture", "actual_listing_price": 110.0, "actual_original_price": 350.0, "actual_year_of_purchase": 2019, "material": "Linen / Timber", "colour": "Cream", "image_key": "armchair"},
                    {"name": "Timber Sideboard (4 door)", "brand": "Nick Scali", "condition": "Excellent", "category": "furniture", "actual_listing_price": 520.0, "actual_original_price": 1499.0, "actual_year_of_purchase": 2018, "material": "American Oak", "image_key": "sideboard"},
                    {"name": "Art Books — Architecture & Design x8", "brand": "Phaidon / Taschen", "condition": "Like New", "category": "other", "actual_listing_price": 40.0, "actual_original_price": 320.0, "actual_year_of_purchase": 2015, "image_key": "books"},
                    {"name": "Crystal Vase Set x3", "brand": "Waterford", "condition": "Excellent", "category": "decor", "actual_listing_price": 45.0, "actual_original_price": 180.0, "actual_year_of_purchase": 2010, "image_key": "art_print"},
                ],
            },
            {
                "name": "Garden & Outdoor",
                "items": [
                    {"name": "Teak 4-Seater Outdoor Setting", "brand": "Barlow Tyrie", "condition": "Good", "category": "furniture", "actual_listing_price": 490.0, "actual_original_price": 1800.0, "actual_year_of_purchase": 2017, "material": "Teak", "image_key": "outdoor_table"},
                    {"name": "Large Terracotta Pots x4", "brand": None, "condition": "Good", "category": "decor", "actual_listing_price": 25.0, "actual_original_price": 80.0, "actual_year_of_purchase": 2018, "image_key": "plant"},
                    {"name": "Garden Hose 30m + Reel", "brand": "Pope", "condition": "Good", "category": "other", "actual_listing_price": 35.0, "actual_original_price": 110.0, "actual_year_of_purchase": 2020, "image_key": "fan"},
                    {"name": "Ficus Lyrata (Fiddle Leaf, 1.5m)", "brand": None, "condition": "Excellent", "category": "decor", "actual_listing_price": 42.0, "actual_original_price": 89.0, "actual_year_of_purchase": 2022, "image_key": "plant"},
                    {"name": "Herb Garden Kit (Basil, Rosemary, Thyme)", "brand": "Mr Fothergill's", "condition": "Good", "category": "other", "actual_listing_price": 10.0, "actual_original_price": 28.0, "actual_year_of_purchase": 2024, "image_key": "succulent"},
                ],
            },
        ],
    },

    # ── 4. Marcus Williams · Mosman · Expat family departing to UK ────────────
    {
        "seller": "seed_marcus_will_syd04",
        "title": "Mosman Family Relocation Sale — Kids Stuff + Quality Furniture",
        "suburb": "Mosman", "state": "NSW",
        "street_address": "7 Raglan St",
        "description": "Relocating back to the UK after 6 years in Sydney. Selling quality furniture, kids' items, and household goods. All proceeds going to shipping costs!",
        "move_out_date": dt_from_now(22),
        "bundles": [
            {
                "name": "Kids' Room",
                "items": [
                    {"name": "Timber Bunk Bed (full set)", "brand": "Pottery Barn Kids", "condition": "Good", "category": "furniture", "actual_listing_price": 340.0, "actual_original_price": 1200.0, "actual_year_of_purchase": 2020, "image_key": "bed_frame"},
                    {"name": "Kids' Study Desk + Hutch", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 85.0, "actual_original_price": 249.0, "actual_year_of_purchase": 2021, "image_key": "kids_desk"},
                    {"name": "Lego Classic Large Box 10698", "brand": "Lego", "condition": "Good", "category": "other", "actual_listing_price": 32.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2022, "image_key": "lego"},
                    {"name": "Lego Star Wars Sets x3", "brand": "Lego", "condition": "Good", "category": "other", "actual_listing_price": 45.0, "actual_original_price": 175.0, "actual_year_of_purchase": 2021, "image_key": "lego"},
                    {"name": "Children's Books x20 (mixed ages)", "brand": "Various", "condition": "Good", "category": "other", "actual_listing_price": 15.0, "actual_original_price": 180.0, "actual_year_of_purchase": 2019, "image_key": "books"},
                    {"name": "Kids' Art Supply Box", "brand": "Faber-Castell", "condition": "Good", "category": "other", "actual_listing_price": 18.0, "actual_original_price": 55.0, "actual_year_of_purchase": 2023, "image_key": "kids_toy"},
                    {"name": "Board Game Bundle x8 (Monopoly, Codenames, etc)", "brand": "Various", "condition": "Good", "category": "other", "actual_listing_price": 35.0, "actual_original_price": 200.0, "actual_year_of_purchase": 2020, "image_key": "board_game"},
                ],
            },
            {
                "name": "Master Bedroom",
                "items": [
                    {"name": "King Bed Frame + Storage", "brand": "Freedom", "condition": "Good", "category": "furniture", "actual_listing_price": 420.0, "actual_original_price": 1199.0, "actual_year_of_purchase": 2019, "image_key": "bed_frame"},
                    {"name": "6-Drawer Dresser", "brand": "Freedom", "condition": "Good", "category": "furniture", "actual_listing_price": 280.0, "actual_original_price": 799.0, "actual_year_of_purchase": 2019, "material": "Timber", "image_key": "dresser"},
                    {"name": "Oval Wall Mirror (large)", "brand": "Zanui", "condition": "Good", "category": "decor", "actual_listing_price": 38.0, "actual_original_price": 120.0, "actual_year_of_purchase": 2020, "image_key": "mirror"},
                    {"name": "Electric Blanket (King size)", "brand": "Sunbeam", "condition": "Like New", "category": "appliance", "actual_listing_price": 28.0, "actual_original_price": 89.0, "actual_year_of_purchase": 2023, "image_key": "heater"},
                ],
            },
            {
                "name": "Appliances + Extras",
                "items": [
                    {"name": "Dyson V11 Cordless Vacuum", "brand": "Dyson", "condition": "Good", "category": "appliance", "actual_listing_price": 280.0, "actual_original_price": 799.0, "actual_year_of_purchase": 2021, "image_key": "vacuum"},
                    {"name": "Nespresso Vertuo + 40 pods", "brand": "Nespresso", "condition": "Like New", "category": "appliance", "actual_listing_price": 95.0, "actual_original_price": 249.0, "actual_year_of_purchase": 2023, "image_key": "kettle"},
                    {"name": "Succulent Collection x6", "brand": None, "condition": "Good", "category": "decor", "actual_listing_price": 22.0, "actual_original_price": 60.0, "actual_year_of_purchase": 2023, "image_key": "succulent"},
                    {"name": "Indoor Plant — ZZ Plant (large)", "brand": None, "condition": "Excellent", "category": "decor", "actual_listing_price": 30.0, "actual_original_price": 65.0, "actual_year_of_purchase": 2022, "image_key": "plant"},
                    {"name": "Woven Storage Basket x3", "brand": "Kmart", "condition": "Like New", "category": "decor", "actual_listing_price": 15.0, "actual_original_price": 40.0, "actual_year_of_purchase": 2023, "image_key": "throw_pillow"},
                ],
            },
        ],
    },

    # ── 5. Zoe Kim · Glebe · Share house dissolving ───────────────────────────
    {
        "seller": "seed_zoe_kim_syd05",
        "title": "Glebe Share House Clearout — 3 Years of Accumulated Stuff",
        "suburb": "Glebe", "state": "NSW",
        "street_address": "44 Glebe Point Rd",
        "description": "Our share house of 3 years is dissolving — everyone is moving on! Heaps of great stuff at dirt-cheap prices. First in, best dressed. Pick up only.",
        "move_out_date": dt_from_now(10),
        "bundles": [
            {
                "name": "Lounge Room",
                "items": [
                    {"name": "3-Seater Fabric Sofa", "brand": "Freedom", "condition": "Fair", "category": "furniture", "actual_listing_price": 120.0, "actual_original_price": 899.0, "actual_year_of_purchase": 2019, "colour": "Charcoal", "image_key": "sofa"},
                    {"name": "Jute Floor Rug 200x300cm", "brand": "Kmart", "condition": "Good", "category": "decor", "actual_listing_price": 45.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2021, "image_key": "rug"},
                    {"name": "Random Throw Blankets x3", "brand": "Kmart", "condition": "Good", "category": "decor", "actual_listing_price": 12.0, "actual_original_price": 45.0, "actual_year_of_purchase": 2021, "image_key": "throw_pillow"},
                    {"name": "Scatter Cushions x6 (mix)", "brand": "Kmart / H&M", "condition": "Good", "category": "decor", "actual_listing_price": 20.0, "actual_original_price": 80.0, "actual_year_of_purchase": 2021, "image_key": "throw_pillow"},
                    {"name": "Candle Collection (10+ candles)", "brand": "Various", "condition": "Like New", "category": "decor", "actual_listing_price": 25.0, "actual_original_price": 120.0, "actual_year_of_purchase": 2022, "image_key": "coffee_mug"},
                    {"name": "Gallery Wall Prints x5 (framed)", "brand": "Kmart / Etsy", "condition": "Good", "category": "decor", "actual_listing_price": 30.0, "actual_original_price": 115.0, "actual_year_of_purchase": 2021, "image_key": "art_print"},
                    {"name": "Marble Effect Table Lamp", "brand": "Kmart", "condition": "Good", "category": "decor", "actual_listing_price": 15.0, "actual_original_price": 29.0, "actual_year_of_purchase": 2022, "image_key": "floor_lamp"},
                ],
            },
            {
                "name": "Kitchen Haul",
                "items": [
                    {"name": "Kitchen Utensil Set (8 piece)", "brand": "Maxwell & Williams", "condition": "Good", "category": "other", "actual_listing_price": 12.0, "actual_original_price": 35.0, "actual_year_of_purchase": 2021, "image_key": "rice_cooker"},
                    {"name": "Spice Rack + 16 Spices", "brand": "Kmart", "condition": "Good", "category": "other", "actual_listing_price": 18.0, "actual_original_price": 45.0, "actual_year_of_purchase": 2021, "image_key": "rice_cooker"},
                    {"name": "Cast Iron Frying Pan", "brand": "Lodge", "condition": "Good", "category": "other", "actual_listing_price": 28.0, "actual_original_price": 79.0, "actual_year_of_purchase": 2020, "image_key": "rice_cooker"},
                    {"name": "Tupperware / Meal Prep Containers x12", "brand": "Sistema", "condition": "Good", "category": "other", "actual_listing_price": 14.0, "actual_original_price": 40.0, "actual_year_of_purchase": 2021, "image_key": "rice_cooker"},
                    {"name": "Dish Drying Rack + Mat", "brand": "Joseph Joseph", "condition": "Good", "category": "other", "actual_listing_price": 16.0, "actual_original_price": 49.0, "actual_year_of_purchase": 2021, "image_key": "rice_cooker"},
                    {"name": "Instant Pot Duo 6L", "brand": "Instant Pot", "condition": "Good", "category": "appliance", "actual_listing_price": 65.0, "actual_original_price": 179.0, "actual_year_of_purchase": 2020, "image_key": "rice_cooker"},
                    {"name": "Air Fryer 4L", "brand": "Philips", "condition": "Good", "category": "appliance", "actual_listing_price": 55.0, "actual_original_price": 149.0, "actual_year_of_purchase": 2022, "image_key": "microwave"},
                ],
            },
            {
                "name": "Random Good Stuff",
                "items": [
                    {"name": "Yoga Mat + Block + Strap", "brand": "Lululemon", "condition": "Good", "category": "other", "actual_listing_price": 35.0, "actual_original_price": 110.0, "actual_year_of_purchase": 2021, "image_key": "yoga_mat"},
                    {"name": "Bookshelf — 5 Tier White", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 45.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2020, "image_key": "bookshelf"},
                    {"name": "Fiction Novel Box (30+ books)", "brand": "Various", "condition": "Good", "category": "other", "actual_listing_price": 20.0, "actual_original_price": 450.0, "actual_year_of_purchase": 2018, "image_key": "books"},
                    {"name": "Anker PowerCore 10000 Charger", "brand": "Anker", "condition": "Good", "category": "electronics", "actual_listing_price": 22.0, "actual_original_price": 49.0, "actual_year_of_purchase": 2022, "image_key": "speaker"},
                    {"name": "USB-C Cables x5 (assorted)", "brand": "Anker", "condition": "Good", "category": "electronics", "actual_listing_price": 10.0, "actual_original_price": 35.0, "actual_year_of_purchase": 2022, "image_key": "speaker"},
                ],
            },
        ],
    },

    # ── 6. Jake Morrison · Rozelle · Moving into furnished apartment ──────────
    {
        "seller": "seed_jake_morr_syd06",
        "title": "Rozelle Furniture Sale — Moving Into Fully Furnished Place",
        "suburb": "Rozelle", "state": "NSW",
        "street_address": "91 Victoria Rd",
        "description": "New apartment comes fully furnished so I'm selling everything. Great quality stuff — bought when I moved out of home 4 years ago. Must be gone by end of month.",
        "move_out_date": dt_from_now(28),
        "bundles": [
            {
                "name": "Lounge & Living",
                "items": [
                    {"name": "3-Seater Velvet Sofa", "brand": "Koala", "condition": "Good", "category": "furniture", "actual_listing_price": 620.0, "actual_original_price": 1499.0, "actual_year_of_purchase": 2021, "colour": "Midnight Blue", "image_key": "sofa"},
                    {"name": "Coffee Table (hairpin legs)", "brand": "Temple & Webster", "condition": "Like New", "category": "furniture", "actual_listing_price": 110.0, "actual_original_price": 299.0, "actual_year_of_purchase": 2022, "image_key": "coffee_table"},
                    {"name": "Floor Standing Bookshelf", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 40.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2020, "image_key": "bookshelf"},
                    {"name": "Indoor Plant Bundle (4 plants + pots)", "brand": None, "condition": "Good", "category": "decor", "actual_listing_price": 35.0, "actual_original_price": 90.0, "actual_year_of_purchase": 2022, "image_key": "plant"},
                    {"name": "Cushion Cover Set x4", "brand": "H&M Home", "condition": "Like New", "category": "decor", "actual_listing_price": 16.0, "actual_original_price": 45.0, "actual_year_of_purchase": 2023, "image_key": "throw_pillow"},
                ],
            },
            {
                "name": "Kitchen",
                "items": [
                    {"name": "Breville Barista Express", "brand": "Breville", "condition": "Good", "category": "appliance", "actual_listing_price": 380.0, "actual_original_price": 899.0, "actual_year_of_purchase": 2021, "image_key": "kettle"},
                    {"name": "KitchenAid Stand Mixer", "brand": "KitchenAid", "condition": "Like New", "category": "appliance", "actual_listing_price": 320.0, "actual_original_price": 699.0, "actual_year_of_purchase": 2022, "colour": "Matte Black", "image_key": "blender"},
                    {"name": "Russell Hobbs Toaster (4-slice)", "brand": "Russell Hobbs", "condition": "Good", "category": "appliance", "actual_listing_price": 28.0, "actual_original_price": 79.0, "actual_year_of_purchase": 2021, "image_key": "toaster"},
                    {"name": "Stainless Steel Kettle", "brand": "Russell Hobbs", "condition": "Good", "category": "appliance", "actual_listing_price": 18.0, "actual_original_price": 59.0, "actual_year_of_purchase": 2021, "image_key": "kettle"},
                    {"name": "Ceramic Spice Jar Set x6", "brand": "Maxwell & Williams", "condition": "Like New", "category": "other", "actual_listing_price": 15.0, "actual_original_price": 45.0, "actual_year_of_purchase": 2022, "image_key": "coffee_mug"},
                    {"name": "Reusable Shopping Bags x8", "brand": "Onya", "condition": "Good", "category": "other", "actual_listing_price": 8.0, "actual_original_price": 30.0, "actual_year_of_purchase": 2021, "image_key": "rice_cooker"},
                ],
            },
        ],
    },

    # ── 7. Priya Sharma · Parramatta · Family upgrading, selling old stuff ─────
    {
        "seller": "seed_priya_shar_syd07",
        "title": "Parramatta Family Sale — Upgrading Everything",
        "suburb": "Parramatta", "state": "NSW",
        "street_address": "15 Church St",
        "description": "We just renovated and bought all new furniture! Old stuff is still perfectly good — just doesn't match the new look. Great value for families setting up a home.",
        "move_out_date": dt_from_now(35),
        "bundles": [
            {
                "name": "Family Living Room",
                "items": [
                    {"name": "L-Shape Fabric Sofa (modular)", "brand": "Nick Scali", "condition": "Good", "category": "furniture", "actual_listing_price": 550.0, "actual_original_price": 2200.0, "actual_year_of_purchase": 2020, "colour": "Taupe", "image_key": "sofa"},
                    {"name": "TV Unit 2.1m (white gloss)", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 95.0, "actual_original_price": 299.0, "actual_year_of_purchase": 2019, "image_key": "tv_unit"},
                    {"name": "Wool Rug 200x290cm", "brand": "Bayliss", "condition": "Good", "category": "decor", "actual_listing_price": 85.0, "actual_original_price": 399.0, "actual_year_of_purchase": 2020, "image_key": "rug"},
                    {"name": "Throw Rugs x2 (knit, grey + white)", "brand": "Kmart", "condition": "Good", "category": "decor", "actual_listing_price": 14.0, "actual_original_price": 40.0, "actual_year_of_purchase": 2021, "image_key": "throw_pillow"},
                    {"name": "Scatter Cushions x4 (matching set)", "brand": "Adairs", "condition": "Like New", "category": "decor", "actual_listing_price": 22.0, "actual_original_price": 80.0, "actual_year_of_purchase": 2022, "image_key": "throw_pillow"},
                ],
            },
            {
                "name": "Kids' Room Extras",
                "items": [
                    {"name": "Kids' Backpacks x2 (school age)", "brand": "Smiggle", "condition": "Good", "category": "other", "actual_listing_price": 14.0, "actual_original_price": 60.0, "actual_year_of_purchase": 2023, "image_key": "kids_toy"},
                    {"name": "Lunch Box + Drink Bottle Set x2", "brand": "Yumbox", "condition": "Good", "category": "other", "actual_listing_price": 20.0, "actual_original_price": 65.0, "actual_year_of_purchase": 2023, "image_key": "kids_toy"},
                    {"name": "Kids' Art Table + 2 Chairs", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 55.0, "actual_original_price": 149.0, "actual_year_of_purchase": 2020, "image_key": "kids_desk"},
                    {"name": "Melissa & Doug Art Set", "brand": "Melissa & Doug", "condition": "Good", "category": "other", "actual_listing_price": 18.0, "actual_original_price": 55.0, "actual_year_of_purchase": 2022, "image_key": "kids_toy"},
                    {"name": "Children's Book Collection x25", "brand": "Various", "condition": "Good", "category": "other", "actual_listing_price": 20.0, "actual_original_price": 350.0, "actual_year_of_purchase": 2018, "image_key": "books"},
                ],
            },
            {
                "name": "Dining Room",
                "items": [
                    {"name": "6-Seater Dining Table (extendable)", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 210.0, "actual_original_price": 599.0, "actual_year_of_purchase": 2019, "image_key": "dining_table"},
                    {"name": "Dining Chairs x6 (solid timber)", "brand": "IKEA", "condition": "Good", "category": "furniture", "actual_listing_price": 28.0, "actual_original_price": 89.0, "actual_year_of_purchase": 2019, "image_key": "armchair"},
                    {"name": "Tupperware Full Set (sealed, complete)", "brand": "Tupperware", "condition": "Like New", "category": "other", "actual_listing_price": 35.0, "actual_original_price": 180.0, "actual_year_of_purchase": 2021, "image_key": "rice_cooker"},
                    {"name": "Coffee Table Books x5 (design / travel)", "brand": "Various", "condition": "Good", "category": "other", "actual_listing_price": 18.0, "actual_original_price": 120.0, "actual_year_of_purchase": 2019, "image_key": "books"},
                ],
            },
        ],
    },

    # ── 8. Liam O'Brien · Paddington · Couple combining households ────────────
    {
        "seller": "seed_liam_obri_syd08",
        "title": "Paddington Consolidation Sale — Combining Households, Selling Doubles",
        "suburb": "Paddington", "state": "NSW",
        "street_address": "66 Oxford St",
        "description": "Moving in with my partner — we now have TWO of everything. Selling the duplicates at below-market prices. Everything in excellent condition, recently purchased.",
        "move_out_date": dt_from_now(40),
        "bundles": [
            {
                "name": "Duplicate Furniture",
                "items": [
                    {"name": "Timber Desk (spare)", "brand": "IKEA", "condition": "Like New", "category": "furniture", "actual_listing_price": 80.0, "actual_original_price": 229.0, "actual_year_of_purchase": 2022, "image_key": "desk"},
                    {"name": "Ergonomic Office Chair (spare)", "brand": "Humanscale", "condition": "Like New", "category": "furniture", "actual_listing_price": 290.0, "actual_original_price": 899.0, "actual_year_of_purchase": 2022, "image_key": "office_chair"},
                    {"name": "Floor Lamp (spare)", "brand": "West Elm", "condition": "Like New", "category": "decor", "actual_listing_price": 55.0, "actual_original_price": 149.0, "actual_year_of_purchase": 2022, "image_key": "floor_lamp"},
                    {"name": "Bookshelf (spare)", "brand": "IKEA", "condition": "Like New", "category": "furniture", "actual_listing_price": 35.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2022, "image_key": "bookshelf"},
                    {"name": "Armchair (spare)", "brand": "Freedom", "condition": "Like New", "category": "furniture", "actual_listing_price": 180.0, "actual_original_price": 599.0, "actual_year_of_purchase": 2022, "colour": "Navy", "image_key": "armchair"},
                ],
            },
            {
                "name": "Duplicate Appliances + Smalls",
                "items": [
                    {"name": "Nespresso Essenza Mini (spare)", "brand": "Nespresso", "condition": "Like New", "category": "appliance", "actual_listing_price": 55.0, "actual_original_price": 149.0, "actual_year_of_purchase": 2023, "image_key": "kettle"},
                    {"name": "Dyson V8 Vacuum (spare)", "brand": "Dyson", "condition": "Like New", "category": "appliance", "actual_listing_price": 195.0, "actual_original_price": 599.0, "actual_year_of_purchase": 2022, "image_key": "vacuum"},
                    {"name": "Toaster 4-Slice (spare)", "brand": "Breville", "condition": "Like New", "category": "appliance", "actual_listing_price": 32.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2023, "image_key": "toaster"},
                    {"name": "Electric Kettle (spare)", "brand": "Smeg", "condition": "Like New", "category": "appliance", "actual_listing_price": 35.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2023, "colour": "Black", "image_key": "kettle"},
                    {"name": "Throw Pillows x4 (spare set)", "brand": "Adairs", "condition": "Like New", "category": "decor", "actual_listing_price": 24.0, "actual_original_price": 80.0, "actual_year_of_purchase": 2023, "image_key": "throw_pillow"},
                    {"name": "Plants x5 (assorted indoor)", "brand": None, "condition": "Excellent", "category": "decor", "actual_listing_price": 30.0, "actual_original_price": 90.0, "actual_year_of_purchase": 2023, "image_key": "plant"},
                    {"name": "Succulent Terrariums x3", "brand": None, "condition": "Excellent", "category": "decor", "actual_listing_price": 18.0, "actual_original_price": 55.0, "actual_year_of_purchase": 2023, "image_key": "succulent"},
                    {"name": "Fiction / Non-fiction Books x15", "brand": "Various", "condition": "Good", "category": "other", "actual_listing_price": 12.0, "actual_original_price": 300.0, "actual_year_of_purchase": 2020, "image_key": "books"},
                    {"name": "JBL Charge 5 Speaker (spare)", "brand": "JBL", "condition": "Like New", "category": "electronics", "actual_listing_price": 45.0, "actual_original_price": 189.0, "actual_year_of_purchase": 2023, "image_key": "speaker"},
                    {"name": "Yoga Mat Set (spare)", "brand": "Lululemon", "condition": "Like New", "category": "other", "actual_listing_price": 40.0, "actual_original_price": 89.0, "actual_year_of_purchase": 2023, "image_key": "yoga_mat"},
                ],
            },
        ],
    },

    ]  # end sales_data


async def seed(db: firestore.AsyncClient, gcs: storage.Client):
    # 1. Create user docs
    print("Creating users...")
    for u in USERS:
        user_ref = db.collection("users").document(u["uid"])
        await user_ref.set({
            "email": u["email"],
            "displayName": u["displayName"],
            "username": u["username"],
            "usernameLower": u["username"].lower(),
            "suburb": u["suburb"],
            "state": u["state"],
            "usernameSetByUser": True,
            "usernameChangedAt": None,
            "createdAt": NOW,
            "updatedAt": NOW,
        })
        uname_ref = db.collection("usernames").document(u["username"].lower())
        await uname_ref.set({"uid": u["uid"], "createdAt": NOW})
        print(f"  user: {u['displayName']} ({u['suburb']})")

    # 2. Create sales
    print("\nCreating sales...")
    for sale_def in sales_data(gcs):
        sale_ref = db.collection("saleEvents").document()
        event_id = sale_ref.id
        print(f"\nSale: {sale_def['title'][:55]} ({event_id})")

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
            "publishedAt": NOW,
            "createdAt": NOW,
            "updatedAt": NOW,
            "statusHistory": [
                {"status": "pending_upload", "timestamp": NOW},
                {"status": "live", "timestamp": NOW},
            ],
        })

        for bundle_def in sale_def["bundles"]:
            b_ref = sale_ref.collection("bundles").document()
            await b_ref.set({"name": bundle_def["name"], "createdAt": NOW})
            item_count = 0
            for item_def in bundle_def["items"]:
                image_key = item_def.pop("image_key", None)
                images = img(gcs, image_key) if image_key else []
                price = item_def.get("actual_listing_price", 0)
                i_ref = b_ref.collection("items").document()
                await i_ref.set({
                    **item_def,
                    "images": images,
                    "predicted_listing_price": price,
                    "predicted_original_price": item_def.get("actual_original_price"),
                    "predicted_year_of_purchase": item_def.get("actual_year_of_purchase"),
                    "pricing_reasoning": f"Priced at market rate for {item_def.get('condition','Good')} condition.",
                    "sale_status": "available",
                    "createdAt": NOW,
                })
                item_count += 1
            tag = "$" if bundle_def["items"] else ""
            print(f"  [{bundle_def['name']}] {item_count} items")

    print("\nSeed complete! Summary:")
    print(f"  {len(USERS)} new users")
    print(f"  {len(sales_data(gcs))} new LIVE sales")


async def main():
    db = firestore.AsyncClient()
    gcs = storage.Client()
    await seed(db, gcs)

if __name__ == "__main__":
    asyncio.run(main())
