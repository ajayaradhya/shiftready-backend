import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import FirestoreDep, GCSDep
from app.models.schemas import (
    PhoneUpdateRequest,
    PublicUserResponse,
    SavedListResponse,
    StatusResponse,
    UserProfileResponse,
    UsernameAvailableResponse,
    UsernameUpdateRequest,
)
from app.services.auth import User, get_current_user
from app.utils.username import is_valid_username

_E164_RE = re.compile(r"^\+[1-9]\d{9,14}$")

router = APIRouter(prefix="/users", tags=["Users"])

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/me", response_model=UserProfileResponse)
async def get_me(current_user: CurrentUser, firestore: FirestoreDep):
    user_doc = await firestore.get_user(current_user.id)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User record not found")
    return UserProfileResponse(
        id=current_user.id,
        username=user_doc.get("username", ""),
        usernameSetByUser=user_doc.get("usernameSetByUser", False),
        usernameChangedAt=user_doc.get("usernameChangedAt"),
    )


@router.get("/username-available", response_model=UsernameAvailableResponse)
async def check_username(
    firestore: FirestoreDep,
    u: str = Query(..., min_length=3, max_length=20),
    current_user: User | None = Depends(get_current_user),
):
    if not is_valid_username(u):
        return UsernameAvailableResponse(available=False, username=u)
    available = await firestore.is_username_available(
        u, requesting_uid=current_user.id if current_user else None
    )
    return UsernameAvailableResponse(available=available, username=u)


@router.patch("/me/username", response_model=UserProfileResponse)
async def update_username(
    body: UsernameUpdateRequest,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    if not is_valid_username(body.username):
        raise HTTPException(
            status_code=422,
            detail="Username must be 3–20 chars, lowercase letters, digits, underscores only.",
        )
    try:
        await firestore.update_username(current_user.id, body.username)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    user_doc = await firestore.get_user(current_user.id)
    return UserProfileResponse(
        id=current_user.id,
        username=user_doc.get("username", ""),
        usernameSetByUser=user_doc.get("usernameSetByUser", False),
        usernameChangedAt=user_doc.get("usernameChangedAt"),
    )


@router.get("/by-username/{username}", response_model=PublicUserResponse)
async def get_public_user(username: str, firestore: FirestoreDep):
    user_doc = await firestore.get_user_by_username(username)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    return PublicUserResponse(
        username=user_doc.get("username", username),
        joinedAt=user_doc.get("createdAt"),
    )


@router.patch("/me/phone", response_model=StatusResponse)
async def update_phone(
    body: PhoneUpdateRequest,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    if not _E164_RE.match(body.phoneE164):
        raise HTTPException(
            status_code=422,
            detail="Phone must be E.164 format (e.g. +61412345678)",
        )
    await firestore.update_phone(current_user.id, body.phoneE164, body.shareOptIn)
    return StatusResponse(status="updated")


@router.get("/me/saved", response_model=SavedListResponse)
async def get_saved(current_user: CurrentUser, firestore: FirestoreDep, gcs: GCSDep):
    raw = await firestore.get_saved(current_user.id)

    processed_items = []
    for item in raw["saved_items"]:
        gcs_path = item.pop("gcs_path", None)
        image_url = None
        if gcs_path and gcs_path.startswith("gs://"):
            try:
                parts = gcs_path.replace("gs://", "").split("/", 1)
                image_url = gcs.generate_download_url(parts[0], parts[1])
            except Exception:
                pass
        item["image_url"] = image_url
        processed_items.append(item)

    return SavedListResponse(
        saved_sales=raw["saved_sales"],
        saved_items=processed_items,
    )
