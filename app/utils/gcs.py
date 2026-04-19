# app/utils/gcs.py
import os
import datetime
from google.cloud import storage
import google.auth
from google.auth import impersonated_credentials

class GCSUtils:
    _client = None  # Class-level cache (Singleton)

    def __init__(self):
        if GCSUtils._client is None:
            self._init_client()

    def _init_client(self):
        source_creds, project = google.auth.default()
        target_sa = os.getenv("GCP_SERVICE_ACCOUNT")
        
        # Only impersonate if we are local AND have a target SA
        if not os.getenv("K_SERVICE") and target_sa:
            print("Configuring Impersonated Credentials for local dev...")
            creds = impersonated_credentials.Credentials(
                source_credentials=source_creds,
                target_principal=target_sa,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            GCSUtils._client = storage.Client(credentials=creds, project=project)
        else:
            # On Cloud Run, use the built-in identity
            GCSUtils._client = storage.Client()

    def generate_upload_url(self, bucket_name: str, blob_name: str):
        bucket = GCSUtils._client.bucket(bucket_name)
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