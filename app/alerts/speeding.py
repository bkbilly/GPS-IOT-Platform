from datetime import datetime
from typing import Optional

from .base import BaseAlert, AlertDefinition, AlertField
from models.schemas import AlertType, Severity


class SpeedingAlert(BaseAlert):

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key        = "speed_tolerance",
            alert_type = AlertType.SPEEDING,
            label      = "Speed Limit Alert",
            description= "Fires when the vehicle exceeds the speed limit continuously for the configured duration.",
            icon       = "⚡",
            severity   = Severity.WARNING,
            state_keys = ["speeding_since", "speeding_alerted"],
            fields     = [
                AlertField(
                    key       = "speed_limit",
                    label     = "Speed Limit",
                    unit      = "km/h",
                    default   = 100,
                    min_value = 10,
                    max_value = 300,
                    help_text = "Alert fires when speed exceeds this value.",
                ),
                AlertField(
                    key       = "duration_seconds",
                    label     = "Confirmation Duration",
                    unit      = "seconds",
                    default   = 30,
                    min_value = 0,
                    max_value = 300,
                    help_text = "Speed must be exceeded for this long before the alert fires (avoids false positives).",
                ),
            ],
        )

    async def check(self, position, device, state, params: dict) -> Optional[dict]:
        limit    = params.get("speed_limit", 100)
        duration = params.get("duration_seconds", 30)

        if (position.speed or 0) <= limit:
            state.alert_states["speeding_since"]   = None
            state.alert_states["speeding_alerted"] = False
            return None

        if state.alert_states.get("speeding_alerted"):
            return None

        since = state.alert_states.get("speeding_since")
        if not since:
            state.alert_states["speeding_since"] = position.device_time.isoformat()
            return None

        elapsed = (
            position.device_time.replace(tzinfo=None)
            - datetime.fromisoformat(since).replace(tzinfo=None)
        ).total_seconds()

        if elapsed >= duration:
            state.alert_states["speeding_alerted"] = True
            return {
                "type":           AlertType.SPEEDING,
                "severity":       Severity.WARNING,
                "message":        f"Speeding: {position.speed:.1f} km/h (limit: {limit} km/h).",
                "alert_metadata": {"config_key": "speed_tolerance"},
            }
        return None
