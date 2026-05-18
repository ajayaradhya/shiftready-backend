from fastapi import HTTPException

EDITABLE_STATUSES = {"ready_for_review", "live", "partially_sold", "failed"}


def assert_editable(sale: dict, scope: str = "inventory") -> None:
    """Raise 409 if sale status doesn't allow edits in the given scope."""
    status = (sale.get("status") or "").lower()
    if status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Sale is '{status}'. Edits not allowed in this state.",
        )
