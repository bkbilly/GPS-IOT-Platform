"""
Alert Module Registry
Automatically discovers and registers all alert modules in this package.

To add a new alert type:
  1. Create a new .py file in this folder.
  2. Define a class that subclasses BaseAlert.
  3. That's it — it will be picked up automatically.
"""
import importlib
import pkgutil
import inspect
import logging
from pathlib import Path

from .base import BaseAlert, AlertDefinition

logger = logging.getLogger(__name__)

# key → alert class
ALERT_REGISTRY: dict[str, type[BaseAlert]] = {}

# key → AlertDefinition (for the /api/alerts/types endpoint)
ALERT_DEFINITIONS: dict[str, AlertDefinition] = {}

# Subset of definitions that are visible in the frontend dropdown (hidden=False)
ALERT_DEFINITIONS_PUBLIC: dict[str, AlertDefinition] = {}

# Auto-import every sibling module in this package
for _, module_name, _ in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if module_name == "base":
        continue
    try:
        module = importlib.import_module(f".{module_name}", package=__name__)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseAlert) and obj is not BaseAlert:
                defn = obj.definition()
                ALERT_REGISTRY[defn.key] = obj
                ALERT_DEFINITIONS[defn.key] = defn
                if not defn.hidden:
                    ALERT_DEFINITIONS_PUBLIC[defn.key] = defn
                logger.debug(f"Registered alert module: {defn.key} ({obj.__name__})")
    except Exception as e:
        logger.error(f"Failed to load alert module '{module_name}': {e}")