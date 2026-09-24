# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shift+M → open Mixie.

``mixar.open_mixie`` opens the Agent island (restoring it from the resting
pill), switches it to the Agent tab and puts the caret in the message box so
the next keystrokes go to Mixie.

Shift+M replaces Blender's own binding. Plain Shift+M is bound in four
default keymaps — Object Mode and Outliner (Link to Collection), Pose and
Armature (Assign to Bone Collection) — and those region keymaps run before
the Window keymap, so the item is added to each of them as well as to
Window. Addon keymap items are placed ahead of the default ones in the same
keymap, so ours is the one that fires; and the operator always finishes, so
the key never falls through to the Blender item. Everything lives in the
ADDON keyconfig (the keyconfig-reload rule: a preset reload rebuilds the
default and user keyconfigs, never the addon one).
"""

import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)

# (keymap name, space_type) for every keymap that binds Shift+M, plus Window.
SHIFT_M_KEYMAPS = (
    ("Window", 'EMPTY'),
    ("Object Mode", 'EMPTY'),
    ("Outliner", 'OUTLINER'),
    ("Pose", 'EMPTY'),
    ("Armature", 'EMPTY'),
)
FOCUS_RETRY_SECONDS = 1.5
FOCUS_RETRY_INTERVAL = 0.05

_keymap_items: list = []


def _tabs_locked(wm) -> bool:
    """Sketch and Voice own the tab strip while they run (the island paints
    its other tabs as ``mixar.bubble_tab_locked``)."""
    return bool(getattr(wm, "mixar_mark_armed", False)
                or getattr(wm, "mixie_chat_voice_listening", False))


def _focus_composer_soon() -> None:
    """Put the caret in the island's message box once its window is laid
    out. Bounded: a pane or overlay that hides the composer simply wins."""
    deadline = time.monotonic() + FOCUS_RETRY_SECONDS

    def _try():
        if time.monotonic() > deadline:
            return None
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != 'AGENT_BUBBLE':
                    continue
                try:
                    with bpy.context.temp_override(window=window, area=area):
                        if 'FINISHED' in bpy.ops.mixie_chat.focus_composer():
                            return None
                except Exception as exc:  # noqa: BLE001 — retry until the deadline
                    _logger.debug("open_mixie: focus attempt failed: %s", exc)
        return FOCUS_RETRY_INTERVAL

    bpy.app.timers.register(_try, first_interval=FOCUS_RETRY_INTERVAL)


class MIXAR_OT_open_mixie(Operator):
    """Open Mixie, the agent chat, ready to type"""

    bl_idname = "mixar.open_mixie"
    bl_label = "Open Mixie"
    bl_description = "Open Mixie, the agent chat, ready to type (Shift M)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.window_manager is not None

    def execute(self, context):
        wm = context.window_manager
        try:
            bpy.ops.mixar.agent_bubble_open_window()
        except Exception as exc:  # noqa: BLE001 — still claim the key
            _logger.warning("open_mixie: could not open the island: %s", exc)
        if not _tabs_locked(wm):
            try:
                wm.mixar_bubble_tab = 'AGENT'
            except Exception as exc:  # noqa: BLE001
                _logger.debug("open_mixie: tab switch skipped: %s", exc)
        _focus_composer_soon()
        # Always FINISHED: a CANCELLED key would fall through to Blender's
        # own Shift+M item in the same keymap.
        return {'FINISHED'}


def _register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon if wm else None
    if kc is None:
        return 0.5   # addon keyconfig not up yet; retry
    _unregister_keymaps()
    for name, space_type in SHIFT_M_KEYMAPS:
        try:
            km = kc.keymaps.new(name=name, space_type=space_type)
            kmi = km.keymap_items.new(MIXAR_OT_open_mixie.bl_idname, 'M', 'PRESS',
                                      shift=True)
            _keymap_items.append((km, kmi))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("open_mixie: Shift+M bind in %s failed: %s", name, exc)
    return None


def _unregister_keymaps():
    for km, kmi in _keymap_items:
        try:
            km.keymap_items.remove(kmi)
        except (ValueError, ReferenceError):
            pass
    _keymap_items.clear()


classes = (MIXAR_OT_open_mixie,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if _register_keymaps() is not None:
        bpy.app.timers.register(_register_keymaps, first_interval=0.5)


def unregister():
    if bpy.app.timers.is_registered(_register_keymaps):
        bpy.app.timers.unregister(_register_keymaps)
    _unregister_keymaps()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
