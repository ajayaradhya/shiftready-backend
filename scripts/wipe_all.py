"""
Destructive full Firestore reset.
Wipes: saleEvents (+ subcollections), conversations (+ subcollections),
       users (+ notifications subcollection), usernames.

REQUIRES --yes flag. Prints GCP_PROJECT_ID and waits 3 s before proceeding.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from google.cloud import firestore


async def wipe(db: firestore.AsyncClient) -> None:
    counts: dict[str, int] = {
        "sales": 0,
        "bundles": 0,
        "items": 0,
        "transactions": 0,
        "conversations": 0,
        "messages": 0,
        "offers": 0,
        "users": 0,
        "notifications": 0,
        "usernames": 0,
    }

    # ── saleEvents ───────────────────────────────────────────────────────────
    print("Wiping saleEvents...")
    async for sale in db.collection("saleEvents").stream():
        event_ref = sale.reference
        async for tx in event_ref.collection("transactions").stream():
            await tx.reference.delete()
            counts["transactions"] += 1
        async for bundle in event_ref.collection("bundles").stream():
            async for item in bundle.reference.collection("items").stream():
                await item.reference.delete()
                counts["items"] += 1
            await bundle.reference.delete()
            counts["bundles"] += 1
        await event_ref.delete()
        counts["sales"] += 1
        print(f"  Deleted sale {sale.id}")

    # ── conversations ─────────────────────────────────────────────────────────
    print("Wiping conversations...")
    async for conv in db.collection("conversations").stream():
        conv_ref = conv.reference
        async for msg in conv_ref.collection("messages").stream():
            await msg.reference.delete()
            counts["messages"] += 1
        async for offer in conv_ref.collection("offers").stream():
            await offer.reference.delete()
            counts["offers"] += 1
        await conv_ref.delete()
        counts["conversations"] += 1

    # ── users + notifications subcollection ───────────────────────────────────
    print("Wiping users...")
    async for user_doc in db.collection("users").stream():
        async for notif in user_doc.reference.collection("notifications").stream():
            await notif.reference.delete()
            counts["notifications"] += 1
        await user_doc.reference.delete()
        counts["users"] += 1

    # ── usernames ─────────────────────────────────────────────────────────────
    print("Wiping usernames...")
    async for doc in db.collection("usernames").stream():
        await doc.reference.delete()
        counts["usernames"] += 1

    print("\nDeleted:")
    for k, v in counts.items():
        if v:
            print(f"  {k}: {v}")


async def main() -> None:
    project = os.getenv("GCP_PROJECT_ID", "(not set)")
    if "--yes" not in sys.argv:
        print(f"Target project: {project}")
        print("Abort: pass --yes to confirm destructive wipe.")
        sys.exit(1)

    print(f"Wiping project: {project}")
    print("Starting in 3 seconds... Ctrl+C to abort")
    await asyncio.sleep(3)

    db = firestore.AsyncClient()
    await wipe(db)
    print("\nWipe complete.")


if __name__ == "__main__":
    asyncio.run(main())
