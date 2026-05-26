import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from google.cloud import firestore

FIXES = {
    "CkBizj0cd7jVlZExO5zd": "Pyrmont Clear-Out - Moving to Melbourne",
    "2cKYYqk29wPWMdCCrAf6": "Ultimo Student Clear-Out - Everything Must Go!",
    "5OfeLzS9cvLVtKo2GnMW": "Chatswood Downsizing - Quality Furniture, Reasonable Prices",
    "kftVIEMqcAXZdxFpUpR7": "Mosman Family Relocation Sale - Kids Stuff + Quality Furniture",
    "DAEeOASFUPlC8ngZOlD6": "Glebe Share House Clearout - 3 Years of Accumulated Stuff",
    "O6ak2guRtzmtFREQh7RH": "Rozelle Furniture Sale - Moving Into Fully Furnished Place",
    "CDgj4BU1ssJyF2tit0Zi": "Parramatta Family Sale - Upgrading Everything",
    "Bkc0cCuGREAmnZPO68Jp": "Paddington Consolidation Sale - Combining Households, Selling Doubles",
}

async def main():
    db = firestore.AsyncClient()
    for eid, title in FIXES.items():
        await db.collection("saleEvents").document(eid).update({"title": title})
        print(f"Fixed: {title[:60]}")

asyncio.run(main())
