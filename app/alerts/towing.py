from typing import Optional

from .base import BaseAlert, AlertDefinition
from models.schemas import AlertType, Severity
from core.database import get_db


class TowingAlert(BaseAlert):

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key           = "towing_threshold_meters",
            alert_type    = AlertType.TOWING,
            label         = "Towing Alert",
            description   = "Alert when vehicle moves more than this distance from where ignition was turned OFF.",
            unit          = "meters",
            default_value = 100,
            min_value     = 10,
            max_value     = 1000,
            icon          = "🚨",
            severity      = Severity.CRITICAL,
            state_keys    = ["towing_anchor_lat", "towing_anchor_lon", "towing_alerted"],
        )

    async def check(self, position, device, state) -> Optional[dict]:
        threshold = device.config.get("towing_threshold_meters")
        if threshold is None:
            return None

        # While ignition is on, reset the anchor so it's always set on park
        if position.ignition:
            state.alert_states.pop("towing_anchor_lat", None)
            state.alert_states.pop("towing_anchor_lon", None)
            state.alert_states["towing_alerted"] = False
            return None

        anchor_lat = state.alert_states.get("towing_anchor_lat")
        anchor_lon = state.alert_states.get("towing_anchor_lon")

        # First position after ignition off — set anchor
        if anchor_lat is None:
            state.alert_states["towing_anchor_lat"] = position.latitude
            state.alert_states["towing_anchor_lon"] = position.longitude
            return None

        # Calculate distance from anchor
        db = get_db()
        async with db.get_session() as session:
            dist_km = await db._calculate_distance(
                session, anchor_lat, anchor_lon,
                position.latitude, position.longitude
            )
        dist_meters = dist_km * 1000

        if dist_meters > threshold and not state.alert_states.get("towing_alerted"):
            state.alert_states["towing_alerted"] = True
            return {
                "type":           AlertType.TOWING,
                "severity":       Severity.CRITICAL,
                "message":        f"Towing Alert: Vehicle moved {int(dist_meters)}m while parked.",
                "alert_metadata": {"config_key": "towing_threshold_meters"},
            }

        return None
