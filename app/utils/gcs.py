import os
import datetime
from google.cloud import storage
from google.auth import impersonated_credentials
import google.auth

class GCSUtils:
    def __init__(self):
        # 1. Fetch from ENV (Configured in .env or Cloud Run trigger)
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.service_account = os.getenv("GCP_SERVICE_ACCOUNT")
        
        # 2. Get the base credentials (ADC)
        source_creds, _ = google.auth.default()
        
        # 3. Create impersonated credentials (The magic piece)
        # This acts as the 'Signer' by calling the IAM SignBlob API
        self.impersonated_creds = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=self.service_account,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        
        self.storage_client = storage.Client(
            project=self.project_id, 
            credentials=self.impersonated_creds
        )

    def generate_upload_url(self, bucket_name: str, blob_name: str):
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type="video/mp4",
            # Crucial: This tells the library to use the IAM service, not a local key
            service_account_email=self.service_account
        )

def generate_upload_url(bucket_name: str, blob_name: str):
    return GCSUtils().generate_upload_url(bucket_name, blob_name)