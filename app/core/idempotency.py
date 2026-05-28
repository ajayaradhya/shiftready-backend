"""
Idempotency key deduplication backed by Firestore.
Collection: idempotency/{key}
TTL field:  expires_at — configure a Firestore TTL policy on this field (Phase 7).
"""

import logging
from datetime import datetime, timezone, timedelta

from google.cloud import firestore as fs

logger = logging.getLogger(__name__)

_TTL_HOURS = 24


async def get_cached(db, key: str) -> dict | None:
    """Return stored response dict if key exists and is not expired, else None."""
    try:
        doc = await db.collection("idempotency").document(key).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        expires_at = data.get("expires_at")
        if expires_at and expires_at < datetime.now(timezone.utc):
            return None
        return data.get("response")
    except Exception as exc:
        logger.warning("Idempotency cache read failed for key=%s: %s", key, exc)
        return None


async def store(db, key: str, response: dict) -> None:
    """Persist idempotency key with TTL."""
    try:
        await (
            db.collection("idempotency")
            .document(key)
            .set(
                {
                    "response": response,
                    "created_at": fs.SERVER_TIMESTAMP,
                    "expires_at": datetime.now(timezone.utc)
                    + timedelta(hours=_TTL_HOURS),
                }
            )
        )
    except Exception as exc:
        logger.warning("Idempotency cache write failed for key=%s: %s", key, exc)
