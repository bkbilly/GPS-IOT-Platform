"""
Geofence Routes
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends

from core.database import get_db
from core.auth import get_current_user, verify_device_access
from models import User
from models.schemas import GeofenceCreate, GeofenceResponse

router = APIRouter(prefix="/api/geofences", tags=["geofences"])


@router.get("")
async def get_geofences(
    device_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    Get geofences. If device_id is provided, the caller must have access to that device.
    Admins can see all geofences without filtering.
    """
    if device_id is not None and not current_user.is_admin:
        # Verify the user has access to this device
        db = get_db()
        user_devices = await db.get_user_devices(current_user.id)
        if not any(d.id == device_id for d in user_devices):
            raise HTTPException(status_code=403, detail="You do not have access to this device")

    db = get_db()
    return await db.get_geofences(device_id)


@router.post("", response_model=GeofenceResponse)
async def create_geofence(
    geofence: GeofenceCreate,
    current_user: User = Depends(get_current_user),
):
    """Create a geofence. If tied to a device, caller must have access to that device."""
    if geofence.device_id is not None and not current_user.is_admin:
        db = get_db()
        user_devices = await db.get_user_devices(current_user.id)
        if not any(d.id == geofence.device_id for d in user_devices):
            raise HTTPException(status_code=403, detail="You do not have access to this device")

    db = get_db()
    return await db.create_geofence(geofence.model_dump())
