import os
import datetime
import google.auth
from google.cloud import storage
from google.auth import impersonated_credentials
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

class GCSUtils:
    def __init__(self):
        # Fetch from env with fallbacks
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.service_account = os.getenv("GCP_SERVICE_ACCOUNT")
        
        self.credentials, _ = google.auth.default()
        
        # Use impersonation if service account is defined
        if self.service_account:
            self.credentials = impersonated_credentials.Credentials(
                source_credentials=self.credentials,
                target_principal=self.service_account,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        
        self.storage_client = storage.Client(
            project=self.project_id, 
            credentials=self.credentials
        )

    def generate_upload_url(self, bucket_name: str, blob_name: str):
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type="video/mp4"
        )

# Helper function to be called by main.py
def generate_upload_url(bucket_name: str, blob_name: str):
    utils = GCSUtils()
    return utils.generate_upload_url(bucket_name, blob_name)