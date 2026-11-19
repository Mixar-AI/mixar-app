# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Forget add-ons Mixar used to bundle and enable on the user's behalf.

Earlier builds enabled the vendored KIRI 3DGS Render add-on and saved it in
the user's preferences. Splats are now Blender's built-in Gaussian splats and
the add-on is no longer shipped, so its preference entry would only make
every launch log a missing add-on. Remove the entry once, after startup.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

RETIRED_ADDONS = ("kiri_3dgs_render",)


def _forget_retired():
    try:
        import addon_utils
        import bpy

        enabled = bpy.context.preferences.addons
        for module in RETIRED_ADDONS:
            if enabled.get(module) is None:
                continue
            addon_utils.disable(module, default_set=True)
            logger.info("Removed retired add-on '%s' from preferences", module)
    except Exception:  # noqa: BLE001 - never fail startup over a stale entry
        logger.debug("Could not remove retired add-ons", exc_info=True)
    return None


def register() -> None:
    try:
        import bpy

        bpy.app.timers.register(_forget_retired, first_interval=1.0)
    except Exception:  # noqa: BLE001 - bpy always present in Blender
        pass


def unregister() -> None:
    try:
        import bpy

        if bpy.app.timers.is_registered(_forget_retired):
            bpy.app.timers.unregister(_forget_retired)
    except Exception:  # noqa: BLE001
        pass
