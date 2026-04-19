import datetime
import os
from google.cloud import storage
from google.auth import compute_engine, impersonated_credentials
import google.auth

class GCSUtils:
    def __init__(self):
        self.credentials, self.project = google.auth.default()

        # If running locally (not on Cloud Run), impersonate the service account to allow signing
        if not os.getenv("K_SERVICE"): # K_SERVICE is set automatically by Cloud Run
            target_principal = "shiftready-backend@shiftready-493812.iam.gserviceaccount.com"
            self.credentials = impersonated_credentials.Credentials(
                source_credentials=self.credentials,
                target_principal=target_principal,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

        self.storage_client = storage.Client(credentials=self.credentials)

    def generate_upload_url(self, bucket_name: str, blob_name: str, expiration_minutes: int = 15):
        """
        Generates a v4 signed URL for uploading a file via HTTP PUT.
        """
        try:
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            url = blob.generate_signed_url(
                version="v4",
                # This specifies the link is valid for 15 minutes
                expiration=datetime.timedelta(minutes=expiration_minutes),
                # Method 'PUT' is standard for direct file uploads
                method="PUT",
                content_type="video/mp4",
            )
            return url
        except Exception as e:
            print(f"Error generating signed URL: {e}")
            raise e

# Helper function to be called by main.py
def generate_upload_url(bucket_name: str, blob_name: str):
    utils = GCSUtils()
    return utils.generate_upload_url(bucket_name, blob_name)