import os
import datetime
from google.cloud import storage
from google.auth import impersonated_credentials
import google.auth

class GCSUtils:
    def __init__(self):
        # 1. Fetch config
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.target_sa = os.getenv("GCP_SERVICE_ACCOUNT")
        
        # 2. Setup persistent client
        source_creds, _ = google.auth.default()
        
        self.creds = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=self.target_sa,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        
        self.storage_client = storage.Client(
            project=self.project_id, 
            credentials=self.creds
        )

    def generate_upload_url(self, bucket_name: str, blob_name: str):
        """Reuses the existing storage_client for efficiency."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type="video/mp4",
            service_account_email=self.target_sa
        )