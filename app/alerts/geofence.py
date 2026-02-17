from typing import Optional

from .base import BaseAlert, AlertDefinition, AlertField
from models.schemas import AlertType, Severity
from core.database import get_db


class GeofenceAlert(BaseAlert):
    """
    Geofence enter/exit alert.

    Each alert row targets a specific geofence (selected by the user) and a
    specific event type (enter, exit, or both).  The frontend fetches available
    geofences from /api/geofences and populates the select field options.

    Because the field_type is "select" with a special `source` hint, the
    frontend knows to load options dynamically from the API rather than from
    the static definition.
    """

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key        = "geofence_alert",
            alert_type = AlertType.GEOFENCE_ENTER,   # actual type set at runtime
            label      = "Geofence Alert",
            description= "Fires when the vehicle enters or exits a specific geofence.",
            icon       = "📍",
            severity   = Severity.WARNING,
            state_keys = [],   # state is keyed dynamically per geofence id
            fields     = [
                AlertField(
                    key        = "geofence_id",
                    label      = "Geofence",
                    field_type = "select",
                    default    = None,
                    required   = True,
                    help_text  = "The geofence to monitor.",
                    options    = [],   # populated dynamically by the frontend via `source`
                    # Frontend reads this hint to fetch options from the API:
                    # options_source = "/api/geofences?device_id={device_id}"
                ),
                AlertField(
                    key        = "event_type",
                    label      = "Trigger On",
                    field_type = "select",
                    default    = "both",
                    required   = True,
                    options    = [
                        {"value": "enter", "label": "Enter only"},
                        {"value": "exit",  "label": "Exit only"},
                        {"value": "both",  "label": "Enter & Exit"},
                    ],
                    help_text  = "Which crossing direction triggers the alert.",
                ),
            ],
        )

    async def check(self, position, device, state, params: dict) -> Optional[dict]:
        # Handled entirely by check_many — this should not be called directly.
        return None

    async def check_many(self, position, device, state, params: dict) -> list:
        geofence_id = params.get("geofence_id")
        event_type  = params.get("event_type", "both")   # "enter" | "exit" | "both"

        db = get_db()
        violations = await db.check_geofence_violations(
            device.id, position.latitude, position.longitude
        )

        alerts = []
        for v in violations:
            # If this row targets a specific geofence, skip others
            if geofence_id and str(v.get("geofence_id")) != str(geofence_id):
                continue

            vtype = v["type"]   # "enter" or "exit"

            # Filter by the configured event type
            if event_type != "both" and vtype != event_type:
                continue

            # Per-geofence debounce key so each zone tracks independently
            debounce_key = f"geofence_{v['geofence_id']}_{vtype}"
            if state.alert_states.get(debounce_key):
                continue

            state.alert_states[debounce_key] = True

            alert_type = AlertType.GEOFENCE_ENTER if vtype == "enter" else AlertType.GEOFENCE_EXIT
            verb       = "Entered" if vtype == "enter" else "Exited"

            alerts.append({
                "type":           alert_type,
                "severity":       Severity.WARNING,
                "message":        f"Geofence {verb}: {v['geofence_name']}",
                "alert_metadata": {
                    "geofence_id":   v.get("geofence_id"),
                    "geofence_name": v["geofence_name"],
                    "event":         vtype,
                },
            })

        # Reset debounce for geofences no longer in violation
        active_ids = {f"{v['geofence_id']}_{v['type']}" for v in violations}
        for key in list(state.alert_states.keys()):
            if key.startswith("geofence_"):
                parts = key[len("geofence_"):]   # "{id}_{type}"
                if parts not in active_ids:
                    state.alert_states[key] = False

        return alerts
