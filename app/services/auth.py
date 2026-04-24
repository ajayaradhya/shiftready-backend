import os
import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, HTTPException, status, Header, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from app.services import firestore_svc

# Initialize Firebase Admin SDK
# In Cloud Run, it automatically uses the default service account credentials.
if not firebase_admin._apps:
    firebase_admin.initialize_app()

security = HTTPBearer(auto_error=False)

class User(BaseModel):
    id: str
    email: str
    name: Optional[str] = None

async def get_current_user(
    res: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None)
) -> User:
    """
    Verifies the Firebase ID Token (JWT) from Bearer header or Query param.
    """
    id_token = None
    if res:
        id_token = res.credentials
    elif token:
        id_token = token

    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token."
        )
    
    try:
        # Verify the JWT against Firebase's public keys
        decoded_token = auth.verify_id_token(id_token)
        user = User(
            id=decoded_token['uid'],
            email=decoded_token.get('email', ''),
            name=decoded_token.get('name')
        )
        # Synchronize user profile in Firestore background
        firestore_svc.upsert_user(user.id, user.email, user.name)
        return user
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}"
        )

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