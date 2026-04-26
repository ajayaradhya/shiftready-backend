import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from google.cloud import firestore
from app.models.schemas import SaleStatus

class FirestoreService:
    def __init__(self):
        # Automatically detects PROJECT_ID from environment in Cloud Run
        project_id = os.getenv("GCP_PROJECT_ID")
        self.db = firestore.AsyncClient(project=project_id)

    # --- USER OPERATIONS ---

    async def upsert_user(self, user_id: str, email: str, name: Optional[str] = None):
        """Ensures a user record exists in Firestore for profile metadata."""
        user_ref = self.db.collection("users").document(user_id)
        await user_ref.set({
            "email": email,
            "displayName": name,
            "lastLogin": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)

    # --- SALE EVENT: ROOT OPERATIONS ---

    async def create_sale_event(self, user_id: str, video_url: str) -> str:
        """Initializes a SaleEvent (The Parent document)."""
        doc_ref = self.db.collection("saleEvents").document()
        await doc_ref.set({
            "sellerId": user_id,
            "status": SaleStatus.PENDING_UPLOAD,
            "videoUrl": video_url,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "statusHistory": [{
                "status": SaleStatus.PENDING_UPLOAD,
                "timestamp": datetime.now()
            }]
        })
        return doc_ref.id

    async def get_sale_event(self, event_id: str):
        """Retrieves sale event metadata."""
        doc = await self.db.collection("saleEvents").document(event_id).get()
        return doc.to_dict() if doc.exists else None

    async def transition_sale_status(self, event_id: str, new_status: SaleStatus):
        """
        Centrally manages all state changes. 
        Maintains an audit trail in 'statusHistory' for 2026 compliance.
        """
        event_ref = self.db.collection("saleEvents").document(event_id)
        
        update_data = {
            "status": new_status,
            "lastTransitionAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "statusHistory": firestore.ArrayUnion([{
                "status": new_status,
                "timestamp": datetime.now()
            }])
        }
        
        await event_ref.update(update_data)
        return True

    async def update_sale_metadata(self, event_id: str, updates: dict):
        """General purpose metadata updates for the root sale event."""
        event_ref = self.db.collection("saleEvents").document(event_id)
        await event_ref.update({**updates, "updatedAt": firestore.SERVER_TIMESTAMP})

    async def list_all_sales(self, user_id: str):
        """Dashboard view: Minimal metadata for high-speed listing."""
        docs = self.db.collection("saleEvents") \
                      .where(filter=firestore.FieldFilter("sellerId", "==", user_id)) \
                      .order_by("createdAt", direction="DESCENDING").stream()
        
        return [{**d.to_dict(), "id": d.id} async for d in docs]

    # --- HIERARCHY: THE FULL SUMMARY ---

    async def get_full_event_summary(self, event_id: str):
        """
        Builds the complete JSON tree for the UI Review Cockpit.
        Recursively fetches Bundles -> Items.
        """
        event_ref = self.db.collection("saleEvents").document(event_id)
        event_doc = await event_ref.get()
        
        if not event_doc.exists:
            return None
            
        data = event_doc.to_dict()
        data["id"] = event_id
        data["bundles"] = []

        # Fetch Bundles
        bundles = event_ref.collection("bundles").stream()
        async for b in bundles:
            b_data = b.to_dict()
            b_data["id"] = b.id
            b_data["items"] = []
            
            # Fetch Items for this Bundle
            items = b.reference.collection("items").stream()
            async for i in items:
                i_data = i.to_dict()
                i_data["id"] = i.id
                b_data["items"].append(i_data)
                
            data["bundles"].append(b_data)
            
        return data

    # --- BUNDLE OPERATIONS ---

    async def add_bundle(self, event_id: str, bundle_name: str, suggested_price: float = 0.0) -> str:
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                             .collection("bundles").document()
        await bundle_ref.set({
            "name": bundle_name,
            "suggestedPrice": suggested_price,
            "isPublished": False,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        return bundle_ref.id

    async def update_bundle_metadata(self, event_id: str, bundle_id: str, updates: dict):
        await self.db.collection("saleEvents").document(event_id) \
               .collection("bundles").document(bundle_id).update(updates)

    async def delete_bundle(self, event_id: str, bundle_id: str):
        """Deletes a bundle and cleans up its internal items sub-collection."""
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id)
        
        # Manual sub-collection cleanup required by Firestore
        items = bundle_ref.collection("items").stream()
        async for item in items:
            await item.reference.delete()
            
        await bundle_ref.delete()
        return True

    # --- ITEM OPERATIONS ---

    async def add_item_to_bundle(self, event_id: str, bundle_id: str, item_data: dict):
        item_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id) \
                          .collection("items").document()
        await item_ref.set(item_data)
        return item_ref.id

    async def update_item_data(self, event_id: str, bundle_id: str, item_id: str, updates: dict):
        item_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id) \
                          .collection("items").document(item_id)
        await item_ref.update(updates)

    async def delete_item(self, event_id: str, bundle_id: str, item_id: str):
        """Removes an item and triggers a price recalculation for the bundle."""
        await self.db.collection("saleEvents").document(event_id) \
               .collection("bundles").document(bundle_id) \
               .collection("items").document(item_id).delete()
        
        await self.recalculate_bundle_total(event_id, bundle_id)
        return True

    async def get_item_standalone(self, event_id: str, bundle_id: str, item_id: str):
        """Deep link support: Fetch a single asset directly."""
        doc = await self.db.collection("saleEvents").document(event_id) \
                     .collection("bundles").document(bundle_id) \
                     .collection("items").document(item_id).get()
        return {**doc.to_dict(), "id": doc.id} if doc.exists else None

    # --- AGGREGATION & RECALCULATION ---

    async def recalculate_bundle_total(self, event_id: str, bundle_id: str):
        """Updates the aggregate bundle price based on all child items."""
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                             .collection("bundles").document(bundle_id)
        
        items = bundle_ref.collection("items").stream()
        total = 0
        async for i in items:
            total += i.to_dict().get("actual_listing_price", 0)
        
        await bundle_ref.update({
            "suggestedPrice": total,
            "updatedAt": firestore.SERVER_TIMESTAMP
        })
        return total

    # --- MARKETPLACE OPERATIONS ---

    async def get_active_inventory(self, suburb: Optional[str] = None, query: Optional[str] = None):
        """
        Marketplace Search: Fetches items from LIVE sales.
        Uses a Collection Group query to search 'items' across all sale events.
        Note: Requires a Firestore index on 'items' collection with 'status' or similar.
        """
        # For MVP/Fast retrieval, we first find LIVE sale events
        sales_query = self.db.collection("saleEvents").where(filter=firestore.FieldFilter("status", "==", SaleStatus.LIVE))
        
        if suburb:
            # Sydney-centric suburb filtering
            sales_query = sales_query.where(filter=firestore.FieldFilter("suburb", "==", suburb))
        
        live_sales = await sales_query.limit(20).get()

        if not live_sales:
            return []

        results = []
        for sale_doc in live_sales:
            event_id = sale_doc.id
            sale_data = sale_doc.to_dict()
            seller_id = sale_data.get("sellerId")
            
            # Fetch bundles for these sales
            bundles = await self.db.collection("saleEvents").document(event_id).collection("bundles").get()
            for b in bundles:
                b_data = b.to_dict()
                items = await b.reference.collection("items").get()
                for i in items:
                    item_data = i.to_dict()
                    # Basic keyword search on name/brand
                    if query and query.lower() not in item_data.get('name', '').lower() and \
                       query and query.lower() not in item_data.get('brand', '').lower():
                        continue
                        
                    results.append({
                        **item_data,
                        "id": i.id,
                        "bundleName": b_data.get("name"),
                        "eventId": event_id,
                        "sellerId": seller_id
                    })
        return results