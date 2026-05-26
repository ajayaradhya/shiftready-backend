"""Fix mangled em-dash in sale titles."""
import os, asyncio, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from google.cloud import firestore

FIXES = {
    "rHpxeBhdzwxn7FLFju66": "Newtown Relocation - Everything Must Go",
    "rMxVVl9zFRqm5Bc6JUZE": "Bondi Downsizing - Designer Pieces",
}

async def main():
    db = firestore.AsyncClient()
    for eid, title in FIXES.items():
        await db.collection("saleEvents").document(eid).update({"title": title})
        print(f"Fixed: {eid} -> {title}")

asyncio.run(main())
