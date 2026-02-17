from typing import Optional

from .base import BaseAlert, AlertDefinition, AlertField
from models.schemas import AlertType, Severity
from core.database import get_db


class TowingAlert(BaseAlert):

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key        = "towing_threshold_meters",
            alert_type = AlertType.TOWING,
            label      = "Towing Alert",
            description= "Fires when the vehicle moves significantly while the ignition is off.",
            icon       = "🚨",
            severity   = Severity.CRITICAL,
            state_keys = ["towing_anchor_lat", "towing_anchor_lon", "towing_alerted"],
            fields     = [
                AlertField(
                    key       = "threshold_meters",
                    label     = "Movement Threshold",
                    unit      = "meters",
                    default   = 100,
                    min_value = 10,
                    max_value = 1000,
                    help_text = "Alert fires when the vehicle moves more than this distance from its parked position.",
                ),
                AlertField(
                    key        = "reset_on_ignition",
                    label      = "Reset anchor when ignition turns on",
                    field_type = "checkbox",
                    default    = True,
                    required   = False,
                    help_text  = "When enabled, the parked anchor is reset each time the ignition turns off.",
                ),
            ],
        )

    async def check(self, position, device, state, params: dict) -> Optional[dict]:
        threshold        = params.get("threshold_meters", 100)
        reset_on_ignition = params.get("reset_on_ignition", True)

        if position.ignition:
            if reset_on_ignition:
                state.alert_states.pop("towing_anchor_lat", None)
                state.alert_states.pop("towing_anchor_lon", None)
            state.alert_states["towing_alerted"] = False
            return None

        anchor_lat = state.alert_states.get("towing_anchor_lat")
        anchor_lon = state.alert_states.get("towing_anchor_lon")

        if anchor_lat is None:
            state.alert_states["towing_anchor_lat"] = position.latitude
            state.alert_states["towing_anchor_lon"] = position.longitude
            return None

        db = get_db()
        async with db.get_session() as session:
            dist_km = await db._calculate_distance(
                session,
                anchor_lat, anchor_lon,
                position.latitude, position.longitude,
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
