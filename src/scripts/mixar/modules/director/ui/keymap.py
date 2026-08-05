# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GUI-stable shortcuts for the native Director viewport surface."""

import bpy


addon_keymaps = []


def _capture_operator_ready() -> bool:
    try:
        bpy.ops.mixar.director_capture_beat.get_rna_type()
    except (AttributeError, KeyError, RuntimeError):
        return False
    return True


def _register_keymap():
    if addon_keymaps:
        return None

    wm = getattr(bpy.context, "window_manager", None)
    keyconfig = getattr(getattr(wm, "keyconfigs", None), "addon", None)
    if wm is None or keyconfig is None or not _capture_operator_ready():
        return 0.1

    keymap = keyconfig.keymaps.new(
        name="3D View",
        space_type='VIEW_3D',
        region_type='WINDOW',
    )
    item = keymap.keymap_items.new(
        "mixar.director_capture_beat",
        type='F',
        value='PRESS',
        head=True,
    )
    addon_keymaps.append((keymap, item))
    return None


def register():
    """Register after the deferred capture operator becomes available."""
    retry = _register_keymap()
    if retry is not None and not bpy.app.timers.is_registered(_register_keymap):
        bpy.app.timers.register(_register_keymap, first_interval=retry)


def unregister():
    if bpy.app.timers.is_registered(_register_keymap):
        bpy.app.timers.unregister(_register_keymap)
    for keymap, item in addon_keymaps:
        keymap.keymap_items.remove(item)
    addon_keymaps.clear()
