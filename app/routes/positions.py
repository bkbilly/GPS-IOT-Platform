"""
Position Routes
GPS position history endpoint.
"""
from fastapi import APIRouter, Depends

from core.database import get_db
from core.auth import verify_device_access
from models import User
from models.schemas import PositionHistoryRequest, PositionHistoryResponse, PositionGeoJSON

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.post("/history", response_model=PositionHistoryResponse)
async def get_position_history(
    request: PositionHistoryRequest,
    caller: User = Depends(verify_device_access),
):
    db = get_db()
    positions = await db.get_position_history(
        request.device_id, request.start_time, request.end_time,
        request.max_points, request.order
    )

    features = []
    total_distance = 0.0
    max_speed = 0.0

    for i, pos in enumerate(positions):
        if i > 0:
            prev = positions[i - 1]
            async with db.get_session() as session:
                distance_km = await db._calculate_distance(
                    session, prev.latitude, prev.longitude, pos.latitude, pos.longitude
                )
                total_distance += distance_km
        if pos.speed:
            max_speed = max(max_speed, pos.speed)

        features.append(PositionGeoJSON(
            type="Feature",
            geometry={"type": "Point", "coordinates": [pos.longitude, pos.latitude]},
            properties={
                "speed": pos.speed,
                "course": pos.course,
                "ignition": pos.ignition,
                "time": pos.device_time.isoformat(),
                "altitude": pos.altitude,
                "satellites": pos.satellites,
                "sensors": pos.sensors,
            },
        ))

    duration_minutes = 0
    if positions:
        t1 = positions[0].device_time
        t2 = positions[-1].device_time
        duration_minutes = int(abs((t2 - t1).total_seconds()) / 60)

    return PositionHistoryResponse(
        type="FeatureCollection",
        features=features,
        summary={
            "total_distance_km": round(total_distance, 2),
            "duration_minutes": duration_minutes,
            "max_speed": round(max_speed, 1),
        },
    )
