# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GUI-stable shortcuts for the native Director viewport surface."""

import bpy


addon_keymaps = []

_OPERATOR_NAMES = (
    "director_capture_beat",
    "director_block_input",
    "director_nudge_camera",
    "director_navigate",
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


# The camera motion the Cinema Mode strip advertises. These live in the SAME
# keymaps as the guards below, and are inserted at the HEAD so they are the
# first thing Blender tries for their key: "Object Mode" already binds A to
# select-all and owns the guarded S, and a nudge parked behind either would
# never run. Being first also makes the nudge its own guard — it consumes the
# key while directing, and outside Cinema Mode its poll fails and the key
# falls through to its native meaning untouched.
#
# `repeat=True` is what makes a HELD key keep moving: the operator fires again
# at the OS auto-repeat rate, and `core/camera_nudge` scales each step by the
# real elapsed time so the speed does not depend on that rate.
#
# Registered in both keymaps that can be dispatched first for these keys:
# "Object Mode" wins while the user is in Object Mode, and "3D View" covers
# the other modes (a Pose-mode S still reaches Blender's own scale first —
# see the module note in `nudge_ops.py`).
_NUDGE_KEYS = (
    ('W', "FORWARD"),
    ('S', "BACK"),
    ('A', "LEFT"),
    ('D', "RIGHT"),
    ('E', "UP"),
    ('Q', "DOWN"),
)

# The other key the Cinema Mode top strip advertises. Blender's default
# keymap gives O to proportional editing in "Object Mode" (and to the
# per-mode equivalents), so the binding has to sit in that keymap to be
# reached at all; "3D View" covers the modes that do not bind it.
#
# Deliberately NOT registered in the global "User Interface" keymap the
# nudges need: `MIXAR_OT_director_navigate.poll` checks only that a shot is
# being directed and is editable — it has no area/region test — so a global
# binding would claim O app-wide for the whole session. Both keymaps here are
# dispatched only inside a 3D viewport's WINDOW region, which is the scoping
# the poll does not do itself. Outside Cinema Mode the poll fails and O falls
# through to its native meaning untouched.
_NAVIGATE_KEYMAPS = (
    ("Object Mode", ('EMPTY', 'WINDOW')),
    ("3D View", ('VIEW_3D', 'WINDOW')),
)

_NUDGE_KEYMAPS = (
    # "User Interface" FIRST and it is the one that matters: Blender
    # dispatches it ahead of every mode keymap, which is the only place that
    # beats both `UI_OT_eyedropper_depth` (which owns E globally, and whose
    # modal then swallows the NEXT key too — that is why Q looked dead) and
    # our own `mixar.director_block_input` guard on S, which sat ahead of the
    # nudge in the merged Object Mode keymap no matter which registered
    # first: addon-vs-addon ordering does not follow registration order the
    # way addon-vs-default does. Being global is safe only because
    # `nudge_ops._in_cinema_viewport` scopes the poll to a directing session
    # inside a 3D viewport's WINDOW region — keep the two together.
    ("User Interface", ('EMPTY', 'WINDOW')),
    ("Object Mode", ('EMPTY', 'WINDOW')),
    ("3D View", ('VIEW_3D', 'WINDOW')),
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

    # Registered FIRST, on purpose. `head=True` only orders items inside the
    # addon keymap; when Blender merges the addon keyconfig into the one it
    # dispatches, items keep the order they were REGISTERED in, so a nudge
    # added after the guard below still lost S to it.
    for keymap_name, (space_type, region_type) in _NUDGE_KEYMAPS:
        keymap = keyconfig.keymaps.new(
            name=keymap_name,
            space_type=space_type,
            region_type=region_type,
        )
        for key, direction in _NUDGE_KEYS:
            item = keymap.keymap_items.new(
                "mixar.director_nudge_camera",
                type=key,
                value='PRESS',
                repeat=True,
                head=True,
            )
            item.properties.direction = direction
            addon_keymaps.append((keymap, item))

    for keymap_name, (space_type, region_type) in _NAVIGATE_KEYMAPS:
        keymap = keyconfig.keymaps.new(
            name=keymap_name,
            space_type=space_type,
            region_type=region_type,
        )
        item = keymap.keymap_items.new(
            "mixar.director_navigate",
            type='O',
            value='PRESS',
            head=True,
        )
        addon_keymaps.append((keymap, item))

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
