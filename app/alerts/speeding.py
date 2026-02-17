from .base import BaseAlert, AlertDefinition
from datetime import datetime
from models.schemas import AlertType, Severity

class SpeedingAlert(BaseAlert):

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key           = "speed_tolerance",
            alert_type    = AlertType.SPEEDING,
            label         = "Speed Limit Alert",
            description   = "Alert when speed exceeds this limit (verified after 30s of continuous speeding).",
            unit          = "km/h",
            default_value = 100,
            min_value     = 0,
            max_value     = 300,
            icon          = "⚡",
            severity      = Severity.WARNING,
            state_keys    = ["speeding_since", "speeding_alerted"],
        )

    async def check(self, position, device, state):
        limit = device.config.get("speed_tolerance")
        duration_threshold = device.config.get("speed_duration_seconds", 30)

        if limit is None or (position.speed or 0) <= limit:
            state.alert_states["speeding_since"] = None
            state.alert_states["speeding_alerted"] = False
            return None

        if state.alert_states.get("speeding_alerted"):
            return None

        since = state.alert_states.get("speeding_since")
        if not since:
            state.alert_states["speeding_since"] = position.device_time.isoformat()
            return None

        elapsed = (position.device_time.replace(tzinfo=None) -
                   datetime.fromisoformat(since).replace(tzinfo=None)).total_seconds()
        if elapsed >= duration_threshold:
            state.alert_states["speeding_alerted"] = True
            return {
                "type":           AlertType.SPEEDING,
                "severity":       Severity.WARNING,
                "message":        f"Speeding: {position.speed:.1f} km/h (Limit: {limit}).",
                "alert_metadata": {"config_key": "speed_tolerance"},
            }
        return None
