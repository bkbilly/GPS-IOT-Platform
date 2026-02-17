from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AlertDefinition:
    """Everything the frontend and backend need to know about this alert type."""

    # --- Identity ---
    key: str                        # config key, e.g. "speed_tolerance"
    alert_type: object              # AlertType enum value

    # --- Frontend UI ---
    label: str                      # "Speed Limit Alert"
    description: str                # shown in tooltip/help text
    unit: str                       # "km/h", "minutes", etc.
    default_value: float            # default threshold value
    min_value: float = 0
    max_value: float = 9999
    icon: str = "🔔"

    # --- Severity / DB ---
    severity: object = "warning"    # Severity enum value

    # --- State keys this alert uses in alert_states ---
    state_keys: list = field(default_factory=list)

    # --- If True, this alert is NOT shown in the frontend "Add Alert" dropdown.
    #     Use for alerts managed outside the threshold system (geofences, maintenance). ---
    hidden: bool = False


class BaseAlert(ABC):
    """
    Base class for all alert modules.

    The engine will:
      1. Call definition() to get UI/DB metadata.
      2. Check the alert schedule via _is_alert_active() — modules do NOT do this.
      3. Call check() for single-result alerts.
      4. Call check_many() for alerts that can return multiple results (e.g. geofences).

    Subclasses must implement check(). Override check_many() only when a single
    position evaluation can produce more than one alert event.
    """

    @classmethod
    @abstractmethod
    def definition(cls) -> AlertDefinition:
        """Return static metadata for this alert type."""
        ...

    @abstractmethod
    async def check(self, position, device, state) -> Optional[dict]:
        """
        Evaluate the alert condition for a single incoming position.

        Returns an alert_data dict if the alert should fire, None otherwise.
        Schedule-active checking is already done by the engine before this is called.
        """
        ...

    async def check_many(self, position, device, state) -> list:
        """
        Override this for alerts that can produce multiple events per position
        (e.g. multiple geofence violations at once).

        The default implementation delegates to check() and wraps the result.
        """
        result = await self.check(position, device, state)
        return [result] if result else []
