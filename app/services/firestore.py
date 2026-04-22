from google.cloud import firestore
import os

class FirestoreService:
    def __init__(self):
        # Automatically detects PROJECT_ID from environment in Cloud Run
        project_id = os.getenv("GCP_PROJECT_ID")
        self.db = firestore.Client(project=project_id)

    def create_sale_event(self, user_id: str, video_url: str) -> str:
        """Initializes a SaleEvent (The Parent document)."""
        doc_ref = self.db.collection("saleEvents").document()
        doc_ref.set({
            "sellerId": user_id,
            "status": "pending_upload",
            "videoUrl": video_url,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        return doc_ref.id

    def get_sale_event(self, event_id: str):
        """Retrieves sale event metadata."""
        doc = self.db.collection("saleEvents").document(event_id).get()
        return doc.to_dict() if doc.exists else None

    def update_sale_status(self, event_id: str, status: str):
        """Updates the processing status (e.g., 'processing', 'ready', 'failed')."""
        self.db.collection("saleEvents").document(event_id).update({
            "status": status,
            "updatedAt": firestore.SERVER_TIMESTAMP
        })

    def add_bundle(self, event_id: str, bundle_name: str, suggested_price: float) -> str:
        """Adds a Bundle to a SaleEvent (The Child collection)."""
        bundle_ref = self.db.collection("saleEvents").document(event_id).collection("bundles").document()
        bundle_ref.set({
            "name": bundle_name,
            "suggestedPrice": suggested_price,
            "isPublished": False,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        return bundle_ref.id

    def add_item_to_bundle(self, event_id: str, bundle_id: str, item_data: dict):
        """Adds an Item to a Bundle (The Grandchild collection)."""
        item_ref = self.db.collection("saleEvents").document(event_id) \
                         .collection("bundles").document(bundle_id) \
                         .collection("items").document()
        item_ref.set(item_data)
        return item_ref.id

    def update_bundle_price(self, event_id: str, bundle_id: str, total_price: float):
        """Updates the aggregate price of a bundle after items are processed."""
        self.db.collection("saleEvents").document(event_id) \
               .collection("bundles").document(bundle_id).update({
                   "suggestedPrice": total_price
               })
        
    def get_full_event_summary(self, event_id: str):
        event_ref = self.db.collection("saleEvents").document(event_id)
        event_doc = event_ref.get()
        
        if not event_doc.exists:
            return None
            
        data = event_doc.to_dict()
        data["id"] = event_id
        data["bundles"] = []

        # Fetch sub-collections
        bundles = event_ref.collection("bundles").stream()
        for b in bundles:
            b_data = b.to_dict()
            b_data["id"] = b.id
            b_data["items"] = []
            
            items = b.reference.collection("items").stream()
            for i in items:
                i_data = i.to_dict()
                i_data["id"] = i.id
                b_data["items"].append(i_data)
                
            data["bundles"].append(b_data)
            
        return data

    def get_item(self, event_id: str, bundle_id: str, item_id: str):
        """Fetches a single item document."""
        doc = self.db.collection("saleEvents").document(event_id) \
                     .collection("bundles").document(bundle_id) \
                     .collection("items").document(item_id).get()
        return doc.to_dict() if doc.exists else None

    def recalculate_bundle_total(self, event_id: str, bundle_id: str):
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                            .collection("bundles").document(bundle_id)
        
        items = bundle_ref.collection("items").stream()
        # Logic: Sum the final price users will actually see
        total = sum(i.to_dict().get("actual_listing_price", 0) for i in items)
        
        bundle_ref.update({"suggestedPrice": total})
        return total

    def update_item_data(self, event_id, bundle_id, item_id, updates):
        """Updates specific fields of an item (e.g., brand, year, or listing_price)."""
        item_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id) \
                          .collection("items").document(item_id)
        item_ref.update(updates)

    def delete_bundle(self, event_id: str, bundle_id: str):
        """Deletes a bundle and all its nested items."""
        bundle_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id)
        
        # Firestore does not delete sub-collections automatically
        items = bundle_ref.collection("items").stream()
        for item in items:
            item.reference.delete()
            
        bundle_ref.delete()
        return True

    def delete_item(self, event_id: str, bundle_id: str, item_id: str):
        """Deletes a specific item and triggers bundle total recalculation."""
        item_ref = self.db.collection("saleEvents").document(event_id) \
                          .collection("bundles").document(bundle_id) \
                          .collection("items").document(item_id)
        item_ref.delete()
        # Recalculate bundle price now that an asset is gone
        self.recalculate_bundle_total(event_id, bundle_id)
        return True

    def update_bundle_metadata(self, event_id: str, bundle_id: str, updates: dict):
        """Updates bundle level data like name or publication status."""
        self.db.collection("saleEvents").document(event_id) \
               .collection("bundles").document(bundle_id).update(updates)
        
    def list_all_sales(self, user_id: str):
        """Dashboard view: Lists all sales for a user with minimal metadata."""
        docs = self.db.collection("saleEvents") \
                      .where("sellerId", "==", user_id) \
                      .order_by("createdAt", direction="DESCENDING").stream()
        sales = []
        for d in docs:
            data = d.to_dict()
            data["id"] = d.id
            sales.append(data)
        return sales

    def get_bundle(self, event_id: str, bundle_id: str):
        """Deep link: Fetch a specific bundle's metadata."""
        doc = self.db.collection("saleEvents").document(event_id) \
                     .collection("bundles").document(bundle_id).get()
        return {**doc.to_dict(), "id": doc.id} if doc.exists else None

    def get_item_standalone(self, event_id: str, bundle_id: str, item_id: str):
        """Deep link: Fetch a specific item directly."""
        doc = self.db.collection("saleEvents").document(event_id) \
                     .collection("bundles").document(bundle_id) \
                     .collection("items").document(item_id).get()
        return {**doc.to_dict(), "id": doc.id} if doc.exists else None