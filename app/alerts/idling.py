from datetime import datetime
from typing import Optional

from .base import BaseAlert, AlertDefinition
from models.schemas import AlertType, Severity


class IdlingAlert(BaseAlert):

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key           = "idle_timeout_minutes",
            alert_type    = AlertType.IDLING,
            label         = "Idle Timeout Alert",
            description   = "Alert when vehicle idles (ignition on, speed 0) longer than this duration.",
            unit          = "minutes",
            default_value = 10,
            min_value     = 1,
            max_value     = 120,
            icon          = "🅿️",
            severity      = Severity.INFO,
            state_keys    = ["idling_since", "idling_alerted"],
        )

    async def check(self, position, device, state) -> Optional[dict]:
        limit = device.config.get("idle_timeout_minutes")

        # Clear state if conditions not met
        if limit is None or not position.ignition or (position.speed or 0) > 1.5:
            state.alert_states["idling_since"] = None
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

        if elapsed_minutes >= limit:
            if not state.alert_states.get("idling_alerted"):
                state.alert_states["idling_alerted"] = True
                return {
                    "type":           AlertType.IDLING,
                    "severity":       Severity.INFO,
                    "message":        f"Idle Alert: Vehicle idling for {limit} min.",
                    "alert_metadata": {"config_key": "idle_timeout_minutes"},
                }

        return None
