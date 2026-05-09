import datetime
import os

import google.auth
from google.auth import impersonated_credentials
from google.cloud import storage


class GCSUtils:
    """Wraps GCS signed-URL generation using impersonated service-account credentials."""

    def __init__(self):
        self.project_id: str = os.getenv("GCP_PROJECT_ID", "")
        self.target_sa: str = os.getenv("GCP_SERVICE_ACCOUNT", "")

        source_creds, _ = google.auth.default()

        self.creds = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=self.target_sa,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

        self.storage_client = storage.Client(
            project=self.project_id,
            credentials=self.creds,
        )

    def generate_upload_url(self, bucket_name: str, blob_name: str) -> str:
        """Returns a v4 signed PUT URL valid for 15 minutes (video upload)."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type="video/mp4",
            service_account_email=self.target_sa,
        )

    def generate_download_url(self, bucket_name: str, blob_name: str, expires_in: int = 3600) -> str:
        """Returns a v4 signed GET URL for viewing a private GCS object."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=expires_in),
            method="GET",
            service_account_email=self.target_sa,
        )
