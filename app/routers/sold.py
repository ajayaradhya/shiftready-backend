from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import FirestoreDep
from app.domain.status import SaleStatus
from app.models.schemas import (
    MarkBundleSoldRequest,
    MarkSaleSoldRequest,
    MarkSoldRequest,
    StatusResponse,
    TransactionResponse,
    WithdrawRequest,
)
from app.services.auth import User, get_current_user, validate_sale_owner

router = APIRouter(prefix="/sales")

ACTIVE_STATUSES = {SaleStatus.LIVE, SaleStatus.PARTIALLY_SOLD}


def _assert_sale_active(event: dict) -> None:
    if event.get("status") not in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Sale must be live or partially_sold to perform this action",
        )


# ── Item endpoints ───────────────────────────────────────────────────────────


@router.post(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/mark-sold",
    response_model=StatusResponse,
)
async def mark_item_sold(
    event_id: str,
    bundle_id: str,
    item_id: str,
    payload: MarkSoldRequest,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    _assert_sale_active(event)
    try:
        await firestore.lifecycle.mark_item_sold(
            event_id,
            bundle_id,
            item_id,
            actor_uid=current_user.id,
            final_price=payload.final_price,
            buyer_uid=payload.buyer_uid,
            buyer_label=payload.buyer_label,
            conversation_id=payload.conversation_id,
            offer_id=payload.offer_id,
            payment_method=payload.payment_method,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "sold"}


@router.post(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/withdraw",
    response_model=StatusResponse,
)
async def withdraw_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    payload: WithdrawRequest,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    _assert_sale_active(event)
    try:
        await firestore.lifecycle.withdraw_item(
            event_id,
            bundle_id,
            item_id,
            actor_uid=current_user.id,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "withdrawn"}


@router.post(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/release-reservation",
    response_model=StatusResponse,
)
async def release_item_reservation(
    event_id: str,
    bundle_id: str,
    item_id: str,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    try:
        await firestore.lifecycle.release_reservation(
            event_id,
            bundle_id,
            item_id,
            actor_uid=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "released"}


@router.post(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/relist",
    response_model=StatusResponse,
)
async def relist_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    try:
        await firestore.lifecycle.relist_item(
            event_id,
            bundle_id,
            item_id,
            actor_uid=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "available"}


# ── Bundle endpoints ─────────────────────────────────────────────────────────


@router.post(
    "/{event_id}/bundles/{bundle_id}/mark-sold",
    response_model=StatusResponse,
)
async def mark_bundle_sold(
    event_id: str,
    bundle_id: str,
    payload: MarkBundleSoldRequest,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    _assert_sale_active(event)
    try:
        await firestore.lifecycle.mark_bundle_sold(
            event_id,
            bundle_id,
            actor_uid=current_user.id,
            scope=payload.scope,
            final_price=payload.final_price,
            buyer_uid=payload.buyer_uid,
            buyer_label=payload.buyer_label,
            conversation_id=payload.conversation_id,
            payment_method=payload.payment_method,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "sold"}


@router.post(
    "/{event_id}/bundles/{bundle_id}/withdraw",
    response_model=StatusResponse,
)
async def withdraw_bundle(
    event_id: str,
    bundle_id: str,
    payload: WithdrawRequest,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    _assert_sale_active(event)
    try:
        await firestore.lifecycle.withdraw_bundle(
            event_id,
            bundle_id,
            actor_uid=current_user.id,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "withdrawn"}


# ── Sale endpoints ────────────────────────────────────────────────────────────


@router.post("/{event_id}/mark-sold", response_model=StatusResponse)
async def mark_sale_sold(
    event_id: str,
    payload: MarkSaleSoldRequest,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    _assert_sale_active(event)
    try:
        await firestore.lifecycle.mark_sale_sold(
            event_id,
            actor_uid=current_user.id,
            final_price=payload.final_price,
            buyer_uid=payload.buyer_uid,
            buyer_label=payload.buyer_label,
            payment_method=payload.payment_method,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "sold"}


@router.post("/{event_id}/withdraw", response_model=StatusResponse)
async def withdraw_sale(
    event_id: str,
    payload: WithdrawRequest,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    event: dict = Depends(validate_sale_owner),
):
    _assert_sale_active(event)
    try:
        await firestore.lifecycle.withdraw_sale(
            event_id,
            actor_uid=current_user.id,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "withdrawn"}


# ── Transactions ─────────────────────────────────────────────────────────────


@router.get("/{event_id}/transactions", response_model=list[TransactionResponse])
async def list_transactions(
    event_id: str,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    return await firestore.transactions.list_transactions(event_id)
