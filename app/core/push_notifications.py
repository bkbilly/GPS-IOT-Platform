"""
Push Notification Service (Web Push / VAPID)
File location: app/core/push_notifications.py

Sends browser push notifications when alerts are triggered.
Integrates with the existing AlertEngine._send_notification pipeline.

Setup:
    1. Install dependency:
           pip install pywebpush

    2. Generate VAPID keys (run once):
           npx web-push generate-vapid-keys
       OR (Python):
           python -c "
           from py_vapid import Vapid
           v = Vapid(); v.generate_keys()
           print('Public: ', v.public_key)
           print('Private:', v.private_key)
           "

    3. Add to your .env:
           VAPID_PRIVATE_KEY=<your_private_key>
           VAPID_PUBLIC_KEY=<your_public_key>
           VAPID_MAILTO=mailto:admin@yourdomain.com

    4. Copy VAPID_PUBLIC_KEY into /web/js/pwa.js  →  VAPID_PUBLIC_KEY constant.
"""

import json
import logging
import os
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models.models import Base
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_MAILTO      = os.getenv("VAPID_MAILTO", "mailto:admin@example.com")


# ── SQLAlchemy Model ──────────────────────────────────────────────

class PushSubscription(Base):
    """Stores browser Web Push subscription objects per user."""
    __tablename__ = "push_subscriptions"

    id:           Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id:      Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    subscription: Mapped[dict]     = mapped_column(JSONB, nullable=False)
    created_at:   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Service ───────────────────────────────────────────────────────

class PushNotificationService:
    """
    Sends Web Push notifications to subscribed browser/PWA clients.

    Usage inside AlertEngine._send_notification:

        push_service = get_push_service()
        await push_service.notify_user(
            db_service=db,
            user_id=user.id,
            alert_type="speed_alert",
            message="Vehicle exceeded 120 km/h",
            severity="high",
            device_name="Truck #1",
        )
    """

    def __init__(self):
        if not VAPID_PRIVATE_KEY:
            logger.warning("[Push] VAPID keys not configured — push notifications disabled")

    @property
    def _enabled(self) -> bool:
        return bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)

    # ── Public API ────────────────────────────────────────────────

    async def notify_user(
        self,
        db_service,           # DatabaseService instance from app/core/database.py
        user_id: int,
        alert_type: str,
        message: str,
        severity: str = "info",
        device_name: Optional[str] = None,
        alert_id: Optional[int] = None,
    ) -> bool:
        """Look up the user's subscription and send a push notification."""
        if not self._enabled:
            return False

        subscription = await self._get_subscription(db_service, user_id)
        if not subscription:
            return False

        return await self._send(
            subscription=subscription,
            alert_type=alert_type,
            message=message,
            severity=severity,
            device_name=device_name,
            alert_id=alert_id,
        )

    async def save_subscription(self, db_service, user_id: int, subscription: dict):
        """Upsert a browser push subscription for the given user."""
        async with db_service.get_session() as session:
            stmt = pg_insert(PushSubscription).values(
                user_id=user_id,
                subscription=subscription,
                updated_at=datetime.utcnow(),
            ).on_conflict_do_update(
                index_elements=["user_id"],
                set_={"subscription": subscription, "updated_at": datetime.utcnow()},
            )
            await session.execute(stmt)

    async def remove_subscription(self, db_service, user_id: int):
        """Remove a user's push subscription."""
        async with db_service.get_session() as session:
            await session.execute(
                delete(PushSubscription).where(PushSubscription.user_id == user_id)
            )

    # ── Internal ──────────────────────────────────────────────────

    async def _get_subscription(self, db_service, user_id: int) -> Optional[dict]:
        async with db_service.get_session() as session:
            result = await session.execute(
                select(PushSubscription).where(PushSubscription.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            return row.subscription if row else None

    async def _send(
        self,
        subscription: dict,
        alert_type: str,
        message: str,
        severity: str,
        device_name: Optional[str],
        alert_id: Optional[int],
    ) -> bool:
        try:
            from pywebpush import webpush, WebPushException
        except ImportError:
            logger.error("[Push] pywebpush not installed. Run: pip install pywebpush")
            return False

        severity_emoji = {"critical": "🚨", "high": "⚠️", "warning": "⚠️", "info": "ℹ️"}.get(severity, "🔔")
        title = f"{severity_emoji} {device_name + ': ' if device_name else ''}{alert_type.replace('_', ' ').title()}"

        payload = json.dumps({
            "title":    title,
            "body":     message,
            "severity": severity,
            "tag":      f"gps-alert-{alert_type}",
            "icon":     "/icons/icon-192.png",
            "badge":    "/icons/icon-192.png",
            "data":     {"url": "/gps-dashboard.html", "alert_id": alert_id},
        })

        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_MAILTO},
            )
            logger.info(f"[Push] Sent: {title}")
            return True

        except Exception as ex:
            response = getattr(ex, "response", None)
            if response and response.status_code == 410:
                logger.info("[Push] Subscription expired (410)")
            else:
                logger.error(f"[Push] Send failed: {ex}")
            return False


# ── Singleton ─────────────────────────────────────────────────────

_push_service: Optional[PushNotificationService] = None

def get_push_service() -> PushNotificationService:
    global _push_service
    if _push_service is None:
        _push_service = PushNotificationService()
    return _push_service
