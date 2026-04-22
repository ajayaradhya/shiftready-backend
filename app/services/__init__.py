import os
from dotenv import load_dotenv

# Import the service classes
from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.utils.gcs import GCSUtils

load_dotenv()

# Configuration constants
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BUCKET_NAME = os.getenv("GCP_UPLOAD_BUCKET")

# --- GLOBAL SINGLETONS ---
# These are instantiated once at startup and shared across all routers
firestore_svc = FirestoreService()
gemini_processor = GeminiProcessor(project_id=PROJECT_ID)
gcs_utils = GCSUtils()

# Explicitly export for cleaner imports in routers
__all__ = ["firestore_svc", "gemini_processor", "gcs_utils", "BUCKET_NAME"]