"""
Push Notification API Routes
File location: app/routes/push.py   (create this new file)

Then register in app/main.py:
    from routes.push import router as push_router
    app.include_router(push_router)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.database import get_db
from core.push_notifications import get_push_service

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
async def save_push_subscription(user_id: int, payload: PushSubscriptionPayload):
    """
    Called by pwa.js after the user grants notification permission.
    Saves the browser's push subscription to the DB.
    """
    db = get_db()
    push = get_push_service()
    await push.save_subscription(db, user_id, payload.dict())
    return {"status": "subscribed"}


@router.delete("/{user_id}/push-subscription")
async def remove_push_subscription(user_id: int):
    """Called by pwa.js when the user disables notifications."""
    db = get_db()
    push = get_push_service()
    await push.remove_subscription(db, user_id)
    return {"status": "unsubscribed"}


# ══════════════════════════════════════════════════════════════════
# HOW TO HOOK INTO THE ALERT ENGINE
# ══════════════════════════════════════════════════════════════════
#
# In app/core/alert_engine.py, find _send_notification() and add
# the lines marked ← NEW at the very end of the try block:
#
#   async def _send_notification(self, user: User, device: Device, alert_data: Dict[str, Any]):
#       try:
#           ...existing Apprise logic (unchanged)...
#           if urls:
#               title = f"🚗 {device.name} - {alert_data['type'].value.upper()}"
#               loop = asyncio.get_event_loop()
#               await loop.run_in_executor(self.executor, self._send_apprise_notification, urls, title, alert_data['message'])
#
#           # ← NEW: also send a browser push notification
#           from core.push_notifications import get_push_service   # ← NEW
#           push = get_push_service()                               # ← NEW
#           await push.notify_user(                                 # ← NEW
#               db_service=get_db(),
#               user_id=user.id,
#               alert_type=alert_data['type'].value,
#               message=alert_data['message'],
#               severity=alert_data.get('severity', 'info'),
#               device_name=device.name,
#           )
#
#       except Exception as e:
#           logger.error(f"Notify error: {e}")
#
# ══════════════════════════════════════════════════════════════════
# DATABASE TABLE
# ══════════════════════════════════════════════════════════════════
#
# The PushSubscription model in push_notifications.py inherits from
# Base, so Base.metadata.create_all() in init_db() will create the
# table automatically — no extra migration needed.
#
# If you use Alembic:
#   alembic revision --autogenerate -m "add push_subscriptions"
#   alembic upgrade head
# ══════════════════════════════════════════════════════════════════