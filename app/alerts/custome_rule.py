"""
Custom Rule Alert Module
Handles user-defined rule-engine expressions as a proper alert module.
Each alert row stores: name (display), rule (condition), channels.
"""
import re
from typing import Optional

import rule_engine

from .base import BaseAlert, AlertDefinition, AlertField
from models.schemas import AlertType, Severity


class CustomRuleAlert(BaseAlert):

    # Per-instance rule cache so compiled rules aren't re-parsed every position
    _cache: dict = {}

    @classmethod
    def definition(cls) -> AlertDefinition:
        return AlertDefinition(
            key         = "__custom__",
            alert_type  = AlertType.CUSTOM,
            label       = "Custom Rule",
            description = "Fires when a user-defined rule expression evaluates to true.",
            icon        = "⚡",
            severity    = Severity.WARNING,
            hidden      = True,   # never shown in the "Add System Alert" dropdown
            state_keys  = [],     # keys are dynamic per rule
            fields      = [
                AlertField(
                    key        = "name",
                    label      = "Rule Name",
                    field_type = "text",
                    default    = "",
                    required   = True,
                    help_text  = "Human-readable name shown in alerts.",
                ),
                AlertField(
                    key        = "rule",
                    label      = "Condition",
                    field_type = "text",
                    default    = "",
                    required   = True,
                    help_text  = "Rule expression, e.g. 'speed > 80 and ignition'.",
                ),
            ],
        )

    async def check(self, position, device, state, params: dict) -> Optional[dict]:
        rule_str  = params.get("rule", "").strip()
        rule_name = params.get("name", "Custom Alert").strip()
        rule_ch   = params.get("channels", [])

        if not rule_str:
            return None

        # Debounce key based on rule string
        state_key = f"c_f_{re.sub(r'[^a-zA-Z0-9]', '', rule_str)}"

        ctx = {
            "speed":    position.speed or 0,
            "ignition": position.ignition,
            **(position.sensors or {}),
        }

        try:
            if rule_str not in CustomRuleAlert._cache:
                CustomRuleAlert._cache[rule_str] = rule_engine.Rule(rule_str)

            if CustomRuleAlert._cache[rule_str].matches(ctx):
                if not state.alert_states.get(state_key):
                    state.alert_states[state_key] = True
                    return {
                        "type":     AlertType.CUSTOM,
                        "severity": Severity.WARNING,
                        "message":  rule_name,
                        "alert_metadata": {
                            "rule_name":        rule_name,
                            "rule_condition":   rule_str,
                            "selected_channels": rule_ch,
                        },
                    }
            else:
                state.alert_states[state_key] = False

        except Exception:
            pass

        return None
