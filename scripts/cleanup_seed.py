"""Delete a specific sale event and all subcollections."""
import os, asyncio, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from google.cloud import firestore

EVENT_ID = "H8gWKCvFeuc7aMrllohm"

async def main():
    db = firestore.AsyncClient()
    event_ref = db.collection("saleEvents").document(EVENT_ID)
    async for bundle in event_ref.collection("bundles").stream():
        async for item in bundle.reference.collection("items").stream():
            await item.reference.delete()
        await bundle.reference.delete()
    await event_ref.delete()
    print(f"Deleted {EVENT_ID}")

asyncio.run(main())
