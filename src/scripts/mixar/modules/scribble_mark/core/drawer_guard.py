# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Expose the frozen viewport while keeping the user's moodboard layout.

The Zen drawer is a separate overlapping region. A WINDOW draw handler
cannot paint above it, although the mark modal receives its coordinates.
Close it without animation for the freeze and restore its previous intent
on every exit. No moodboard items or View2D transforms are changed.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class DrawerGuard:
    def __init__(self):
        self._saved = None
        self._area_ptr = self._region_ptr = 0

    def suspend(self, context, window, area, region):
        if self._saved is not None:
            return True
        wm = context.window_manager
        if getattr(window.workspace, "name", "") != "Zen Mode":
            return True
        amount = getattr(wm, "mixar_moodboard_drawer_amount", 0.0)
        target = getattr(wm, "mixar_moodboard_drawer_target", 0)
        if not amount and not target:
            return True
        self._saved = (float(amount), int(target))
        self._area_ptr, self._region_ptr = area.as_pointer(), region.as_pointer()
        try:
            with context.temp_override(window=window, area=area, region=region):
                result = bpy.ops.view3d.moodboard_drawer_set(amount=0.0, target=0.0)
            if "FINISHED" not in result:
                raise RuntimeError("Moodboard drawer did not close")
            area.tag_redraw()
            return True
        except Exception as exc:  # A visible drawer would hide captured ink.
            logger.debug("Scribble: could not expose the viewport: %s", exc)
            self.restore(context)
            return False

    def restore(self, context):
        if self._saved is None:
            return
        from .freeze_session import resolve

        amount, target = self._saved
        self._saved = None
        window, area, region = resolve(context, self._area_ptr, self._region_ptr)
        try:
            if (window is not None and area is not None and region is not None
                    and window.workspace.name == "Zen Mode"):
                with context.temp_override(window=window, area=area, region=region):
                    result = bpy.ops.view3d.moodboard_drawer_set(
                        amount=amount, target=float(target))
                if "FINISHED" in result:
                    area.tag_redraw()
                    return
        except Exception as exc:
            logger.debug("Scribble: restoring drawer intent after layout change: %s", exc)
        # The owning area can disappear while drawing. Restore intent without
        # touching a stale region; the drawer clock settles it when Zen returns.
        wm = context.window_manager
        wm.mixar_moodboard_drawer_amount = amount
        wm.mixar_moodboard_drawer_target = target
