import datetime
import os
from google.cloud import storage
from google.auth import compute_engine, impersonated_credentials
import google.auth

class GCSUtils:
    def __init__(self):
        # 1. Get the default credentials (works both locally and on Cloud Run)
        self.credentials, self.project = google.auth.default()
        
        # 2. On Cloud Run, we use the IAM signBlob API via impersonation
        # This replaces the need for a physical private key file.
        target_principal = "shiftready-backend@shiftready-493812.iam.gserviceaccount.com"
        
        self.credentials = impersonated_credentials.Credentials(
            source_credentials=self.credentials,
            target_principal=target_principal,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        
        self.storage_client = storage.Client(credentials=self.credentials)

    def generate_upload_url(self, bucket_name: str, blob_name: str):
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # The library now uses the IAM signBlob service automatically
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