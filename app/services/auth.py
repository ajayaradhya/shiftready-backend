from fastapi import Depends, HTTPException, status, Header, Query
from pydantic import BaseModel
from typing import Optional
from app.services import firestore_svc

class User(BaseModel):
    id: str
    email: str

async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    token: Optional[str] = Query(None)
) -> User:
    """
    Dependency that extracts the user identity.
    2026 Strategy: Swap this mock with Firebase/Auth0 JWT validation.
    """
    user_id = x_user_id or token
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Auth header or token query param missing."
        )
    
    # In a real app, you'd fetch user details from a DB or token claims
    return User(id=user_id, email=f"{user_id}@shiftready.io")

async def validate_sale_owner(
    event_id: str, 
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Resource-level Authorization.
    Ensures the authenticated user is the 'sellerId' on the document.
    """
    event = firestore_svc.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")
    
    if event.get("sellerId") != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied: You do not own this sale.")
        
    return event