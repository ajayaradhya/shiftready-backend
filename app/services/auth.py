import os
from typing import Annotated

import firebase_admin
from firebase_admin import auth
from fastapi import Depends, HTTPException, status, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from starlette.requests import HTTPConnection

from app.core.config import settings
from app.core.deps import FirestoreDep

# Initialise Firebase Admin SDK once (uses default service account in Cloud Run)
if not firebase_admin._apps:
    firebase_admin.initialize_app()

security = HTTPBearer(auto_error=False)


class User(BaseModel):
    id: str
    email: str
    name: str | None = None
    username: str | None = None
    email_verified: bool = False


async def get_current_user(
    connection: HTTPConnection,
    firestore: FirestoreDep,
    token: str | None = Query(None),
) -> User:
    """
    Verifies the Firebase ID Token from Bearer header or ?token= query param.
    Compatible with both HTTP and WebSocket connections.
    """
    id_token: str | None = None

    auth_header = connection.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        id_token = auth_header.split(" ")[1]

    if not id_token and token:
        id_token = token

    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
        )

    # Dev-token bypass (requires ALLOW_DEV_TOKENS=true in .env AND K_SERVICE absent)
    if (
        settings.allow_dev_tokens
        and not os.getenv("K_SERVICE")
        and id_token.startswith("dev_")
    ):
        username = await firestore.upsert_user(
            id_token, f"{id_token}@myrio.test", "Dev User"
        )
        user = User(
            id=id_token,
            email=f"{id_token}@myrio.test",
            name="Dev User",
            username=username,
            email_verified=True,
        )
        return user

    try:
        decoded = await run_in_threadpool(auth.verify_id_token, id_token)
        username = await firestore.upsert_user(
            decoded["uid"], decoded.get("email", ""), decoded.get("name")
        )
        user = User(
            id=decoded["uid"],
            email=decoded.get("email", ""),
            name=decoded.get("name"),
            username=username,
            email_verified=decoded.get("email_verified", False),
        )
        return user
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        )


async def validate_sale_owner(
    event_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    firestore: FirestoreDep,
) -> dict:
    """Resource-level ownership check. Returns the event dict on success."""
    event = await firestore.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")
    if event.get("sellerId") != current_user.id:
        raise HTTPException(
            status_code=403, detail="Access denied: You do not own this sale."
        )
    return event


async def get_optional_user(
    connection: HTTPConnection,
    firestore: FirestoreDep,
    token: str | None = Query(None),
) -> User | None:
    """Allows anonymous browsing; returns None when no valid token is present."""
    try:
        return await get_current_user(connection, firestore, token)
    except HTTPException:
        return None


async def require_email_verified(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Blocks unverified email accounts from creating or publishing listings."""
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required. Please verify your email address before creating or publishing listings.",
        )
    return current_user
