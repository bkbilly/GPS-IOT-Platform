from typing import Optional

from .base import BaseAlert, AlertDefinition
from models.schemas import AlertType, Severity
from core.database import get_db


class GeofenceAlert(BaseAlert):
    """
    Geofence enter/exit alerts.

    Unlike threshold-based alerts, geofences have no single config key or
    UI threshold — they are managed through the geofences API separately.
    Returning None from definition() signals to the engine and frontend that
    this alert should NOT appear in the "Add System Alert" dropdown.
    """

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key           = "__geofence__",   # internal key, not shown in dropdown
            alert_type    = AlertType.GEOFENCE_ENTER,
            label         = "Geofence",
            description   = "Fires on geofence enter/exit events (managed via the Geofences tab).",
            unit          = "",
            default_value = 0,
            icon          = "📍",
            severity      = Severity.WARNING,
            state_keys    = [],
            hidden        = True,             # tells the frontend to skip this in the dropdown
        )

    async def check(self, position, device, state) -> Optional[dict]:
        # Geofences return multiple alerts, so we handle them differently.
        # The engine calls check() expecting at most one dict back.
        # For multi-result alerts, override check_many() instead.
        return None

    async def check_many(self, position, device, state) -> list:
        """Return one alert dict per geofence violation."""
        db = get_db()
        violations = await db.check_geofence_violations(
            device.id, position.latitude, position.longitude
        )
        alerts = []
        for v in violations:
            alert_type = (
                AlertType.GEOFENCE_ENTER
                if v["type"] == "enter"
                else AlertType.GEOFENCE_EXIT
            )
            alerts.append({
                "type":           alert_type,
                "severity":       Severity.WARNING,
                "message":        f"Geofence {'Entered' if v['type'] == 'enter' else 'Exited'}: {v['geofence_name']}",
                "alert_metadata": {"geofence_id": v.get("geofence_id"), "event": v["type"]},
            })
        return alerts