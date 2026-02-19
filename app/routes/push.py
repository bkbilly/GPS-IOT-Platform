"""
Push Notification API Routes
File location: app/routes/push.py   (create this new file)

Then register in app/main.py:
    from routes.push import router as push_router
    app.include_router(push_router)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.auth import get_current_user
from core.database import get_db
from core.push_notifications import get_push_service
from models import User

router = APIRouter(prefix="/api/users", tags=["push-notifications"])


# ── Pydantic schema for the subscription object sent by the browser ──

class PushKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscriptionPayload(BaseModel):
    endpoint: str
    keys: PushKeys
    expirationTime: Optional[int] = None


# ── Routes ────────────────────────────────────────────────────────

@router.post("/{user_id}/push-subscription")
async def save_push_subscription(
    user_id: int,
    payload: PushSubscriptionPayload,
    current_user: User = Depends(get_current_user),
):
    """
    Called by pwa.js after the user grants notification permission.
    Saves the browser's push subscription to the DB.
    User can only register their own subscription.
    """
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    push = get_push_service()
    await push.save_subscription(db, user_id, payload.dict())
    return {"status": "subscribed"}


@router.delete("/{user_id}/push-subscription")
async def remove_push_subscription(
    user_id: int,
    current_user: User = Depends(get_current_user),
):
    """Called by pwa.js when the user disables notifications."""
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    push = get_push_service()
    await push.remove_subscription(db, user_id)
    return {"status": "unsubscribed"}

