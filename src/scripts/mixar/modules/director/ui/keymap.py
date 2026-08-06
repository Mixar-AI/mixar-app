# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GUI-stable shortcuts for the native Director viewport surface."""

import bpy


addon_keymaps = []

_OPERATOR_NAMES = (
    "director_capture_beat",
    "director_block_input",
)

# Object-editing shortcuts absorbed while directing, each registered in the
# keymap Blender actually dispatches FIRST for that key. View3D walks its
# WINDOW-region handlers head to tail: mode keymaps ("Object Mode" owns the
# G/R/S transforms, the Alt clears, and X/Del delete), then "3D View
# Generic" (the N/T chrome toggles), and only then "3D View" — so a guard
# parked in "3D View" never sees a key the earlier keymaps bind. Addon items
# are PREPENDED when a keyconfig merges them into the final keymap, which is
# why a guard in the right keymap beats the native binding. All guards are
# poll-gated through ``mixar.director_block_input``, so every key falls
# through to its native meaning as soon as the Director surface closes.
# Transform keys reshape the set (the reported "scale is getting triggered"
# leak), the Alt-clears silently reset the shot camera, delete can take the
# camera with it, and the region toggles reopen chrome the calm surface
# deliberately hides.
_GUARDED_KEYS = (
    # keymap, (space_type, region_type), key, modifiers
    ("Object Mode", ('EMPTY', 'WINDOW'), 'G', {}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'R', {}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'S', {}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'G', {"alt": True}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'R', {"alt": True}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'S', {"alt": True}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'X', {}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'DEL', {}),
    ("Object Mode", ('EMPTY', 'WINDOW'), 'DEL', {"shift": True}),
    ("3D View Generic", ('VIEW_3D', 'WINDOW'), 'T', {}),
    ("3D View Generic", ('VIEW_3D', 'WINDOW'), 'N', {}),
    ("3D View", ('VIEW_3D', 'WINDOW'), 'S', {"shift": True}),
)


def _operators_ready() -> bool:
    for name in _OPERATOR_NAMES:
        try:
            getattr(bpy.ops.mixar, name).get_rna_type()
        except (AttributeError, KeyError, RuntimeError):
            return False
    return True


def _register_keymap():
    if addon_keymaps:
        return None

    wm = getattr(bpy.context, "window_manager", None)
    keyconfig = getattr(getattr(wm, "keyconfigs", None), "addon", None)
    if wm is None or keyconfig is None or not _operators_ready():
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
    for keymap_name, (space_type, region_type), key, modifiers in _GUARDED_KEYS:
        keymap = keyconfig.keymaps.new(
            name=keymap_name,
            space_type=space_type,
            region_type=region_type,
        )
        item = keymap.keymap_items.new(
            "mixar.director_block_input",
            type=key,
            value='PRESS',
            **modifiers,
        )
        addon_keymaps.append((keymap, item))
    return None


def register():
    """Register after the deferred Director operators become available."""
    retry = _register_keymap()
    if retry is not None and not bpy.app.timers.is_registered(_register_keymap):
        bpy.app.timers.register(_register_keymap, first_interval=retry)


def unregister():
    if bpy.app.timers.is_registered(_register_keymap):
        bpy.app.timers.unregister(_register_keymap)
    for keymap, item in addon_keymaps:
        keymap.keymap_items.remove(item)
    addon_keymaps.clear()
