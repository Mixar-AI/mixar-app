# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Paint Module Bootstrap

Ensures paint module properties are registered before UI panels access them.
Uses direct file loading to bypass stub modules in sys.modules.
"""

import importlib.util
import sys
from pathlib import Path

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_paint_module = None


def _load_paint_module():
    """Load the paint module directly from file."""
    global _paint_module

    if _paint_module is not None:
        return _paint_module

    # Get path to paint/__init__.py
    bootstrap_dir = Path(__file__).parent
    paint_init = bootstrap_dir.parent / "modules" / "paint" / "__init__.py"

    if not paint_init.exists():
        raise FileNotFoundError(f"Paint module not found at {paint_init}")

    # Load module directly (bypasses stub in sys.modules)
    spec = importlib.util.spec_from_file_location(
        "mixar.modules.paint",
        paint_init,
        submodule_search_locations=[str(paint_init.parent)]
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "mixar.modules.paint"
    module.__path__ = [str(paint_init.parent)]

    # Replace stub in sys.modules with real module
    sys.modules["mixar.modules.paint"] = module
    spec.loader.exec_module(module)

    _paint_module = module
    return module


def register():
    """Register the paint module."""
    logger.debug("Paint module bootstrap: registering...")

    try:
        paint = _load_paint_module()
        paint.register()
        logger.debug("Paint module bootstrap: done")
    except Exception as e:
        logger.error("Paint module bootstrap: FAILED - %s", e, exc_info=True)


def unregister():
    """Unregister the paint module."""
    global _paint_module
    try:
        if _paint_module is not None:
            _paint_module.unregister()
        else:
            paint = sys.modules.get("mixar.modules.paint")
            if paint and hasattr(paint, 'unregister'):
                paint.unregister()
    except Exception as e:
        logger.error("Paint module bootstrap unregister failed: %s", e)
    finally:
        _paint_module = None
