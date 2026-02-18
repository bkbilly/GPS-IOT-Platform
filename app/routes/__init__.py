"""
Routes Package
Automatically discovers and registers all APIRouter modules in this directory.

To add a new group of endpoints:
  1. Create a new .py file in this folder.
  2. Define a module-level `router = APIRouter(...)`.
  3. That's it — it will be picked up automatically on next startup.
"""
import pkgutil
import importlib
import logging
import traceback
from pathlib import Path
from fastapi import APIRouter

logger = logging.getLogger(__name__)

ROUTE_REGISTRY: list[APIRouter] = []

for _, module_name, _ in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if module_name == "base":
        continue
    try:
        module = importlib.import_module(f".{module_name}", package=__name__)
        if hasattr(module, "router"):
            ROUTE_REGISTRY.append(module.router)
            logger.info(f"Registered router: {module_name}")
        else:
            logger.warning(f"Route module '{module_name}' has no `router` attribute — skipped")
    except Exception as e:
        # Log the full traceback so missing methods/imports are immediately visible
        logger.error(
            f"Failed to load route module '{module_name}': {e}\n{traceback.format_exc()}"
        )

if not ROUTE_REGISTRY:
    logger.error("No routers were registered! Check for import errors in the routes/ package.")