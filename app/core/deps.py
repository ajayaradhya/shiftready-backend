"""
FastAPI dependency providers.

Each function returns the application-level singleton for its service.
Routers declare what they need via the Annotated type aliases; FastAPI
resolves them at request time without touching module-level globals.

Singletons are still created in services/__init__.py so that the
integration-test reinit_firestore fixture and existing mocks continue
to work without modification.
"""
from typing import Annotated

from fastapi import Depends

from app.services.firestore import FirestoreService
from app.services.gemini import GeminiProcessor
from app.services.messaging import MessagingService
from app.utils.gcs import GCSUtils


# --- provider functions ---

def get_firestore() -> FirestoreService:
    from app.services import firestore_svc
    return firestore_svc


def get_gemini() -> GeminiProcessor:
    from app.services import gemini_processor
    return gemini_processor


def get_gcs() -> GCSUtils:
    from app.services import gcs_utils
    return gcs_utils


def get_bucket() -> str:
    from app.services import BUCKET_NAME
    return BUCKET_NAME


def get_messaging() -> MessagingService:
    from app.services import messaging_svc
    return messaging_svc


# --- type aliases (use these in router signatures) ---

FirestoreDep = Annotated[FirestoreService, Depends(get_firestore)]
GeminiDep    = Annotated[GeminiProcessor,  Depends(get_gemini)]
GCSDep       = Annotated[GCSUtils,         Depends(get_gcs)]
BucketDep    = Annotated[str,              Depends(get_bucket)]
MessagingDep = Annotated[MessagingService, Depends(get_messaging)]
