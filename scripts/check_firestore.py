import os, asyncio, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from google.cloud import firestore

async def main():
    print("PROJECT:", os.getenv("GCP_PROJECT_ID"))
    print("BUCKET:", os.getenv("GCP_UPLOAD_BUCKET"))
    db = firestore.AsyncClient()
    users = await db.collection("users").limit(10).get()
    print("=== USERS ===")
    for u in users:
        d = u.to_dict()
        print(f"  {u.id}: {d.get('email','?')} / {d.get('username','?')}")
    sales = await db.collection("saleEvents").limit(10).get()
    print(f"=== SALES ({len(sales)}) ===")
    for s in sales:
        d = s.to_dict()
        print(f"  {s.id}: seller={d.get('sellerId','?')} status={d.get('status','?')} suburb={d.get('suburb','?')}")

asyncio.run(main())
