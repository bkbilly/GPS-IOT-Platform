from typing import Optional

from .base import BaseAlert, AlertDefinition
from models.schemas import AlertType, Severity


class MaintenanceAlert(BaseAlert):
    """
    Maintenance due alert.

    Fires when the vehicle is within 100 km of an oil change or tire rotation
    interval. Configured via the device's maintenance config block, not via
    the standard alert threshold — so this alert is also hidden from the
    "Add System Alert" dropdown (it's always active when configured).
    """

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key           = "__maintenance__",
            alert_type    = AlertType.MAINTENANCE,
            label         = "Maintenance Due",
            description   = "Alert when a maintenance interval is approaching (configured in the General tab).",
            unit          = "",
            default_value = 0,
            icon          = "🔧",
            severity      = Severity.INFO,
            state_keys    = ["maint_oil_alerted", "maint_tire_alerted"],
            hidden        = True,   # managed via maintenance config, not alert rows
        )

    async def check(self, position, device, state) -> Optional[dict]:
        maintenance = device.config.get("maintenance", {})

        # --- Oil change ---
        oil_km = maintenance.get("oil_change_km")
        if oil_km:
            odometer = state.total_odometer or 0
            remaining = oil_km - (odometer % oil_km)
            if 0 < remaining <= 100:
                if not state.alert_states.get("maint_oil_alerted"):
                    state.alert_states["maint_oil_alerted"] = True
                    return {
                        "type":           AlertType.MAINTENANCE,
                        "severity":       Severity.INFO,
                        "message":        f"Maintenance: Oil change due in {int(remaining)} km.",
                        "alert_metadata": {"maintenance_type": "oil_change"},
                    }
            elif remaining > 100:
                # Reset so the alert can fire again next cycle
                state.alert_states["maint_oil_alerted"] = False

        # --- Tire rotation ---
        tire_km = maintenance.get("tire_rotation_km")
        if tire_km:
            odometer = state.total_odometer or 0
            remaining = tire_km - (odometer % tire_km)
            if 0 < remaining <= 100:
                if not state.alert_states.get("maint_tire_alerted"):
                    state.alert_states["maint_tire_alerted"] = True
                    return {
                        "type":           AlertType.MAINTENANCE,
                        "severity":       Severity.INFO,
                        "message":        f"Maintenance: Tire rotation due in {int(remaining)} km.",
                        "alert_metadata": {"maintenance_type": "tire_rotation"},
                    }
            elif remaining > 100:
                state.alert_states["maint_tire_alerted"] = False

        return None