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