"""
Offline Detection Alert Module
Fires when a device has not been heard from for a configurable number of hours.

Unlike position-based alerts, this module is NOT called from process_position_alerts().
Instead, offline_detection_task() in alert_engine.py calls check_device() directly,
passing the device and its state.
"""
from datetime import datetime, timedelta
from typing import Optional

from .base import BaseAlert, AlertDefinition, AlertField
from models.schemas import AlertType, Severity


class OfflineAlert(BaseAlert):

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key         = "offline_detection",
            alert_type  = AlertType.OFFLINE,
            label       = "Offline Detection",
            description = "Fires when the device has not reported for a configurable number of hours.",
            icon        = "📴",
            severity    = Severity.WARNING,
            state_keys  = ["offline_alerted"],
            fields      = [
                AlertField(
                    key       = "timeout_hours",
                    label     = "Offline Timeout",
                    unit      = "hours",
                    default   = 24,
                    min_value = 1,
                    max_value = 720,
                    help_text = "Alert fires when no data is received for this many hours.",
                ),
            ],
        )

    async def check(self, position, device, state, params: dict) -> Optional[dict]:
        # This module is not triggered by incoming positions.
        # Use check_device() below instead.
        return None

    async def check_device(self, device, state, params: dict) -> Optional[dict]:
        timeout_hours = params.get("timeout_hours", 24)

        last_update = state.last_update
        if not last_update:
            return None

        elapsed = datetime.utcnow() - last_update.replace(tzinfo=None)

        if elapsed < timedelta(hours=timeout_hours):
            # Device is back — reset so the alert can fire again next time
            state.alert_states["offline_alerted"] = False
            return None

        if state.alert_states.get("offline_alerted"):
            return None

        state.alert_states["offline_alerted"] = True
        return {
            "type":     AlertType.OFFLINE,
            "severity": Severity.WARNING,
            "message":  f"Device offline for over {timeout_hours}h.",
            "alert_metadata": {
                "config_key":    "offline_detection",
                "timeout_hours": timeout_hours,
            },
        }
