import datetime
import os

import google.auth
from google.auth import impersonated_credentials
from google.oauth2 import service_account
from google.cloud import storage

from app.core.config import settings


class GCSUtils:
    """Wraps GCS signed-URL generation using service-account credentials."""

    def __init__(self):
        self.project_id: str = settings.gcp_project_id
        self.target_sa: str = settings.gcp_service_account
        sa_file: str = settings.google_application_credentials

        # Cloud Run (K_SERVICE set): use impersonation via workload identity.
        # Local (SA JSON available): load directly — impersonation requires IAM API access.
        if os.getenv("K_SERVICE") or not sa_file:
            source_creds, _ = google.auth.default()
            self.creds = impersonated_credentials.Credentials(
                source_credentials=source_creds,
                target_principal=self.target_sa,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self._use_impersonation = True
        else:
            self.creds = service_account.Credentials.from_service_account_file(
                sa_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self._use_impersonation = False

        self.storage_client = storage.Client(
            project=self.project_id,
            credentials=self.creds,
        )

    def generate_upload_url(self, bucket_name: str, blob_name: str) -> str:
        """Returns a v4 signed PUT URL valid for 15 minutes (video upload)."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        kwargs: dict = dict(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type="video/mp4",
        )
        if self._use_impersonation:
            kwargs["service_account_email"] = self.target_sa
        return blob.generate_signed_url(**kwargs)

    def generate_image_upload_url(
        self, bucket_name: str, blob_name: str, content_type: str = "image/jpeg"
    ) -> str:
        """Returns a v4 signed PUT URL for image uploads, valid for 15 minutes."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        kwargs: dict = dict(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="PUT",
            content_type=content_type,
        )
        if self._use_impersonation:
            kwargs["service_account_email"] = self.target_sa
        return blob.generate_signed_url(**kwargs)

    def delete_blob(self, bucket_name: str, blob_name: str) -> None:
        """Deletes a GCS object. No-ops silently if the blob does not exist."""
        from google.api_core.exceptions import NotFound

        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        try:
            blob.delete()
        except NotFound:
            pass

    def upload_bytes(
        self,
        bucket_name: str,
        blob_name: str,
        data: bytes,
        content_type: str = "image/jpeg",
    ) -> str:
        """Uploads raw bytes to GCS and returns the gs:// URI."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{bucket_name}/{blob_name}"

    def generate_download_url(
        self, bucket_name: str, blob_name: str, expires_in: int = 3600
    ) -> str:
        """Returns a v4 signed GET URL for viewing a private GCS object."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        kwargs: dict = dict(
            version="v4",
            expiration=datetime.timedelta(seconds=expires_in),
            method="GET",
        )
        if self._use_impersonation:
            kwargs["service_account_email"] = self.target_sa
        return blob.generate_signed_url(**kwargs)
