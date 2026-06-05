from app.core.config import settings
from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.services.messaging import MessagingService
from app.services.notifier import notifier
from app.services.push import PushService
from app.utils.gcs import GCSUtils

BUCKET_NAME = settings.gcp_upload_bucket

firestore_svc = FirestoreService()
gemini_processor = GeminiProcessor(project_id=settings.gcp_project_id)
gcs_utils = GCSUtils()
push_svc = PushService(firestore_svc.users)
messaging_svc = MessagingService(
    firestore_svc.conversations, notifier, firestore_svc.notifications, push_svc
)

__all__ = [
    "firestore_svc",
    "gemini_processor",
    "gcs_utils",
    "BUCKET_NAME",
    "messaging_svc",
    "push_svc",
]
