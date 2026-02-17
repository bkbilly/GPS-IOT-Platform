from datetime import datetime
from typing import Optional

from .base import BaseAlert, AlertDefinition, AlertField
from models.schemas import AlertType, Severity


class IdlingAlert(BaseAlert):

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key        = "idle_timeout_minutes",
            alert_type = AlertType.IDLING,
            label      = "Idle Timeout Alert",
            description= "Fires when the vehicle idles (ignition on, speed ~0) longer than the configured duration.",
            icon       = "🅿️",
            severity   = Severity.INFO,
            state_keys = ["idling_since", "idling_alerted"],
            fields     = [
                AlertField(
                    key       = "timeout_minutes",
                    label     = "Idle Timeout",
                    unit      = "minutes",
                    default   = 10,
                    min_value = 1,
                    max_value = 120,
                    help_text = "Alert fires after the vehicle has been stationary for this duration.",
                ),
                AlertField(
                    key        = "speed_threshold",
                    label      = "Speed Threshold",
                    unit       = "km/h",
                    default    = 2,
                    min_value  = 0,
                    max_value  = 10,
                    required   = False,
                    help_text  = "Maximum speed considered 'idle'. Increase slightly for GPS noise tolerance.",
                ),
            ],
        )

    async def check(self, position, device, state, params: dict) -> Optional[dict]:
        timeout   = params.get("timeout_minutes", 10)
        max_speed = params.get("speed_threshold", 2)

        if not position.ignition or (position.speed or 0) > max_speed:
            state.alert_states["idling_since"]   = None
            state.alert_states["idling_alerted"] = False
            return None

        since = state.alert_states.get("idling_since")
        if not since:
            state.alert_states["idling_since"] = position.device_time.isoformat()
            return None

        elapsed_minutes = (
            position.device_time.replace(tzinfo=None)
            - datetime.fromisoformat(since).replace(tzinfo=None)
        ).total_seconds() / 60

        if elapsed_minutes >= timeout and not state.alert_states.get("idling_alerted"):
            state.alert_states["idling_alerted"] = True
            return {
                "type":           AlertType.IDLING,
                "severity":       Severity.INFO,
                "message":        f"Idle Alert: Vehicle idling for {int(elapsed_minutes)} min.",
                "alert_metadata": {"config_key": "idle_timeout_minutes"},
            }
        return None
