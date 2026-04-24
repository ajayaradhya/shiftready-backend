import os
from datetime import datetime
from typing import Optional
from google.cloud import firestore
from app.models.schemas import SaleStatus

class FirestoreService:
    def __init__(self):
        # Automatically detects PROJECT_ID from environment in Cloud Run
        project_id = os.getenv("GCP_PROJECT_ID")
        self.db = firestore.Client(project=project_id)

    # --- USER OPERATIONS ---

    def upsert_user(self, user_id: str, email: str, name: Optional[str] = None):
        """Ensures a user record exists in Firestore for profile metadata."""
        user_ref = self.db.collection("users").document(user_id)
        user_ref.set({
            "email": email,
            "displayName": name,
            "lastLogin": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)

    # --- SALE EVENT: ROOT OPERATIONS ---

    def create_sale_event(self, user_id: str, video_url: str) -> str:
        """Initializes a SaleEvent (The Parent document)."""
        doc_ref = self.db.collection("saleEvents").document()
        doc_ref.set({
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

    def get_sale_event(self, event_id: str):
        """Retrieves sale event metadata."""
        doc = self.db.collection("saleEvents").document(event_id).get()
        return doc.to_dict() if doc.exists else None

    def transition_sale_status(self, event_id: str, new_status: SaleStatus):
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
        
        event_ref.update(update_data)
        return True

    def update_sale_metadata(self, event_id: str, updates: dict):
        """General purpose metadata updates for the root sale event."""
        event_ref = self.db.collection("saleEvents").document(event_id)
        event_ref.update({**updates, "updatedAt": firestore.SERVER_TIMESTAMP})

    def list_all_sales(self, user_id: str):
        """Dashboard view: Minimal metadata for high-speed listing."""
        docs = self.db.collection("saleEvents") \
                      .where("sellerId", "==", user_id) \
                      .order_by("createdAt", direction="DESCENDING").stream()
        
        return [{**d.to_dict(), "id": d.id} for d in docs]

    # --- HIERARCHY: THE FULL SUMMARY ---

    def get_full_event_summary(self, event_id: str):
        """
        Builds the complete JSON tree for the UI Review Cockpit.
        Recursively fetches Bundles -> Items.
        """
        event_ref = self.db.collection("saleEvents").document(event_id)
        event_doc = event_ref.get()
        
        if not event_doc.exists:
            return None
            
        data = event_doc.to_dict()
        data["id"] = event_id
        data["bundles"] = []

        # Fetch Bundles
        bundles = event_ref.collection("bundles").stream()
        for b in bundles:
            b_data = b.to_dict()
            b_data["id"] = b.id
            b_data["items"] = []
            
            # Fetch Items for this Bundle
            items = b.reference.collection("items").stream()
            for i in items:
                i_data = i.to_dict()
                i_data["id"] = i.id
                b_data["items"].append(i_data)
                
            data["bundles"].append(b_data)
            
        return data

    # --- BUNDLE OPERATIONS ---

    def add_bundle(self, event_id: str, bundle_name: str, suggested_price: float = 0.0) -> str:
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                             .collection("bundles").document()
        bundle_ref.set({
            "name": bundle_name,
            "suggestedPrice": suggested_price,
            "isPublished": False,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        return bundle_ref.id

    def update_bundle_metadata(self, event_id: str, bundle_id: str, updates: dict):
        self.db.collection("saleEvents").document(event_id) \
               .collection("bundles").document(bundle_id).update(updates)

    def delete_bundle(self, event_id: str, bundle_id: str):
        """Deletes a bundle and cleans up its internal items sub-collection."""
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id)
        
        # Manual sub-collection cleanup required by Firestore
        items = bundle_ref.collection("items").stream()
        for item in items:
            item.reference.delete()
            
        bundle_ref.delete()
        return True

    # --- ITEM OPERATIONS ---

    def add_item_to_bundle(self, event_id: str, bundle_id: str, item_data: dict):
        item_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id) \
                          .collection("items").document()
        item_ref.set(item_data)
        return item_ref.id

    def update_item_data(self, event_id: str, bundle_id: str, item_id: str, updates: dict):
        item_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id) \
                          .collection("items").document(item_id)
        item_ref.update(updates)

    def delete_item(self, event_id: str, bundle_id: str, item_id: str):
        """Removes an item and triggers a price recalculation for the bundle."""
        self.db.collection("saleEvents").document(event_id) \
               .collection("bundles").document(bundle_id) \
               .collection("items").document(item_id).delete()
        
        self.recalculate_bundle_total(event_id, bundle_id)
        return True

    def get_item_standalone(self, event_id: str, bundle_id: str, item_id: str):
        """Deep link support: Fetch a single asset directly."""
        doc = self.db.collection("saleEvents").document(event_id) \
                     .collection("bundles").document(bundle_id) \
                     .collection("items").document(item_id).get()
        return {**doc.to_dict(), "id": doc.id} if doc.exists else None

    # --- AGGREGATION & RECALCULATION ---

    def recalculate_bundle_total(self, event_id: str, bundle_id: str):
        """Updates the aggregate bundle price based on all child items."""
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                             .collection("bundles").document(bundle_id)
        
        items = bundle_ref.collection("items").stream()
        total = sum(i.to_dict().get("actual_listing_price", 0) for i in items)
        
        bundle_ref.update({
            "suggestedPrice": total,
            "updatedAt": firestore.SERVER_TIMESTAMP
        })
        return total