# app/services/__init__.py
import os
from datetime import datetime
from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.utils.gcs import GCSUtils
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BUCKET_NAME = os.getenv("GCP_UPLOAD_BUCKET")
CURRENT_YEAR = datetime.now().year

# Initialize singletons here
firestore_svc = FirestoreService()
gemini_processor = GeminiProcessor(project_id=PROJECT_ID)
gcs_utils = GCSUtils()