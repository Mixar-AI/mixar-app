# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where a Blender power user finds Export to Moodboard.

The Director's own export lives on its viewport overlay, which a user who
animates cameras natively never opens. Two native menus carry it instead:

* **Render** (topbar) — always drawn, in BOTH Zen and Engine modes. This is
  the discovery surface: the first place an expert looks for "render an
  animation". It is never hidden, because a row nobody can find is the bug
  this feature exists to fix; a scene that cannot render yet opens the popup
  and is told why.
* **Timeline / Dope Sheet → View** — drawn only when the scene HAS a camera.
  Those headers are cramped and camera-irrelevant most of the time, so
  presence is gated there while the Render menu stays constant.

Both rows open one popup (`MIXAR_PT_camera_export`); the row itself only ever
opens it, so the reason and the fix live in one place.

Menu classes are resolved by NAME at register time and skipped when absent —
upstream renames a menu far more easily than it removes the feature, and a
missing one must cost a debug line, not a failed module import.
"""

import bpy

from mixar.config.logging_config import get_logger

from ...constants import CAMERA_EXPORT_LABEL, CAMERA_EXPORT_PANEL_ID
from ...core.camera_export import export_settings, scene_has_camera

logger = get_logger(__name__)

# Menus that always carry the row, and menus that carry it only when the
# scene has a camera to export.
ALWAYS_MENUS = ("TOPBAR_MT_render",)
CAMERA_GATED_MENUS = ("TIME_MT_view", "DOPESHEET_MT_view")


def _draw_row(layout, context) -> None:
    settings = export_settings(context.scene)
    if settings is not None and settings.render_is_running:
        percent = int(round(float(settings.render_progress) * 100))
        label = f"Exporting to Moodboard… {percent}%"
    else:
        label = f"{CAMERA_EXPORT_LABEL}…"
    layout.separator()
    props = layout.operator(
        "wm.call_panel", text=label, icon='RENDER_ANIMATION'
    )
    props.name = CAMERA_EXPORT_PANEL_ID
    # Kind selection is a multi-select and the popup doubles as the live
    # progress readout, so it must survive a click inside it.
    props.keep_open = True


def draw_render_menu(self, context) -> None:
    if getattr(context, "scene", None) is None:
        return
    _draw_row(self.layout, context)


def draw_animation_menu(self, context) -> None:
    scene = getattr(context, "scene", None)
    if scene is None or not scene_has_camera(scene):
        return
    _draw_row(self.layout, context)


_APPENDED: list[tuple[object, object]] = []


def _append(menu_name: str, draw) -> None:
    menu = getattr(bpy.types, menu_name, None)
    if menu is None:
        logger.debug("Camera export: %s is unavailable", menu_name)
        return
    menu.append(draw)
    _APPENDED.append((menu, draw))


def register() -> None:
    for name in ALWAYS_MENUS:
        _append(name, draw_render_menu)
    for name in CAMERA_GATED_MENUS:
        _append(name, draw_animation_menu)


def unregister() -> None:
    while _APPENDED:
        menu, draw = _APPENDED.pop()
        try:
            menu.remove(draw)
        except (AttributeError, ValueError):
            pass
