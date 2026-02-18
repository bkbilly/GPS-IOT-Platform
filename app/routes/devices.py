"""
Device Routes
CRUD and state operations for GPS devices.

Access rules:
  GET  /api/devices/all      → admin only
  GET  /api/devices          → returns caller's own devices (token-derived, not query param)
  POST /api/devices          → admin only
  GET  /api/devices/{id}     → must have device access
  PUT  /api/devices/{id}     → must have device access
  DELETE /api/devices/{id}   → admin only
  GET  /api/devices/{id}/state      → must have device access
  GET  /api/devices/{id}/statistics → must have device access
  GET  /api/devices/{id}/trips      → must have device access
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy import select, update

from core.database import get_db
from core.auth import get_current_user, require_admin, verify_device_access
from models import User, Device, DeviceState
from models.schemas import DeviceCreate, DeviceResponse, DeviceStateResponse, TripResponse

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("/all", response_model=List[DeviceResponse])
async def get_all_devices(admin: User = Depends(require_admin)):
    """Return every device in the system. Admin only."""
    db = get_db()
    async with db.get_session() as session:
        result = await session.execute(select(Device))
        return result.scalars().all()


@router.get("", response_model=List[DeviceResponse])
async def get_devices(current_user: User = Depends(get_current_user)):
    """Return devices belonging to the authenticated user. Admins see all."""
    db = get_db()
    if current_user.is_admin:
        async with db.get_session() as session:
            result = await session.execute(select(Device))
            return result.scalars().all()
    return await db.get_user_devices(current_user.id)


@router.post("", response_model=DeviceResponse)
async def create_device(
    device_data: DeviceCreate,
    assign_to: Optional[int] = Query(None, description="User ID to assign device to (admin only)"),
    current_user: User = Depends(get_current_user),
):
    """Create a new device. Admin only."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    db = get_db()
    existing = await db.get_device_by_imei(device_data.imei)
    if existing:
        raise HTTPException(status_code=400, detail="IMEI already exists")

    device = await db.create_device(device_data)
    target_user = assign_to if assign_to else current_user.id
    await db.add_device_to_user(target_user, device.id)
    return device


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: int,
    caller: User = Depends(verify_device_access),
):
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: int,
    device_data: DeviceCreate,
    new_odometer: Optional[float] = Query(None),
    caller: User = Depends(verify_device_access),
):
    db = get_db()
    device = await db.update_device(device_id, device_data)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if new_odometer is not None:
        async with db.get_session() as session:
            await session.execute(
                update(DeviceState)
                .where(DeviceState.device_id == device_id)
                .values(total_odometer=new_odometer)
            )
    return device


@router.delete("/{device_id}")
async def delete_device(device_id: int, admin: User = Depends(require_admin)):
    """Delete a device. Admin only."""
    db = get_db()
    success = await db.delete_device(device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "deleted"}


@router.get("/{device_id}/state", response_model=DeviceStateResponse)
async def get_device_state(
    device_id: int,
    caller: User = Depends(verify_device_access),
):
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device or not device.state:
        raise HTTPException(status_code=404, detail="Device state not found")
    return device.state


@router.get("/{device_id}/statistics")
async def get_device_statistics(
    device_id: int,
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    caller: User = Depends(verify_device_access),
):
    db = get_db()
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()
    return await db.get_device_statistics(device_id, start_date, end_date)


@router.get("/{device_id}/trips", response_model=List[TripResponse])
async def get_device_trips(
    device_id: int,
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    caller: User = Depends(verify_device_access),
):
    db = get_db()
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date:
        end_date = datetime.utcnow()
    return await db.get_device_trips(device_id, start_date, end_date)


@router.get("/{device_id}/command-support")
async def check_command_support(
    device_id: int,
    caller: User = Depends(verify_device_access),
):
    from protocols import ProtocolRegistry
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    decoder = ProtocolRegistry.get_decoder(device.protocol)
    if not decoder:
        return {"supports_commands": False, "available_commands": [], "protocol": device.protocol, "command_info": {}}

    available_commands = []
    command_info = {}
    if hasattr(decoder, "get_available_commands"):
        try:
            available_commands = decoder.get_available_commands()
            if hasattr(decoder, "get_command_info"):
                for cmd in available_commands:
                    command_info[cmd] = decoder.get_command_info(cmd)
        except Exception as e:
            pass
    else:
        for cmd_type in ["reset", "interval", "reboot", "custom"]:
            try:
                result = await decoder.encode_command(cmd_type, {})
                if result and len(result) > 0:
                    available_commands.append(cmd_type)
            except Exception:
                pass

    return {
        "supports_commands": len(available_commands) > 0,
        "available_commands": available_commands,
        "protocol": device.protocol,
        "command_info": command_info,
    }
