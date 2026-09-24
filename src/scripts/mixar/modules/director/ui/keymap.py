# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GUI-stable shortcuts for the native Director viewport surface."""

import bpy


addon_keymaps = []

_OPERATOR_NAMES = (
    "director_capture_beat",
    "director_block_input",
    "director_navigate",
    "director_aerial",
    "director_aerial_exit",
    "director_place_camera",
    "director_scroll_cameras",
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

# The walk keys, inert until a walk is actually running.
#
# Cinema Mode used to hold a camera nudge on W/A/S/D/Q/E for the whole
# session, so the keys moved the shot camera at any moment and the mouse
# came with them. That is a mode the director never asked to be in. The keys
# belong to Blender's own walk navigation now, which the top strip's Walk
# chip starts, and outside a walk they do NOTHING here — they are absorbed
# rather than left to their native meanings, because those are worse on this
# surface: A selects everything, W cycles the active tool, Q opens the quick
# favourites pie, and E starts `UI_OT_eyedropper_depth`, a modal that grabs
# the pointer and then swallows the next key too (which is why Q used to
# look dead). S is guarded above already.
#
# Scoped to a 3D viewport's WINDOW region through the two keymaps below, and
# poll-gated on a directing session, so every key falls through untouched
# the moment the surface closes. While walk runs its modal consumes these
# before any keymap is consulted, so the guards never see them.
_WALK_KEYS = ('W', 'A', 'S', 'D', 'Q', 'E')

# Walking has NO keyboard shortcut, and that is deliberate.
#
# It is opened AND closed from the Walk chip in the Cinema top strip
# (`view3d_director_cinema_top.cc:walk_chip`) — the one switch, so neither
# Esc nor the right button stops it (`view3d_director_walk.cc`).
#
# Two keys were tried and both were somebody else's. `N` is the sidebar — one
# of the few shortcuts every Blender user has in their fingers. `Shift`+`` ` ``
# is what Blender binds `view3d.walk` to, which looked ideal until it turned
# out MIXAR already owns that key: `moodboard/ui/keymap.py` toggles the Zen
# drawer with it, and `agent_viewport_lock/constants.py` lists it for the same
# reason. A mode-specific action does not get to take a key the rest of the
# app is already using, so this one has a button instead.
#
# Before binding anything here, grep `src/scripts/mixar/**/ui/keymap.py` for
# the key: the app's own bindings are the ones a user notices breaking.


# The other key the Cinema Mode top strip advertises: O toggles the AERIAL
# view (`mixar.director_aerial`, `ui/operators/aerial_ops.py`) — the main
# viewport looks down on the scene and a click in the stage places the shot
# camera. It used to start the WASD walk; `mixar.director_navigate` stays
# registered for the top strip's Walk chip, the gate's Navigate button and
# the compact rail, it only lost this key. Blender's default keymap gives O to proportional editing in
# "Object Mode" (and to the per-mode equivalents), so the binding has to sit
# in that keymap to be reached at all; "3D View" covers the modes that do
# not bind it.
#
# Deliberately NOT registered in the global "User Interface" keymap the
# nudges need: `MIXAR_OT_director_aerial.poll` checks only that a session is
# directing — it has no area/region test — so a global binding would claim O
# app-wide for the whole session. Both keymaps here are dispatched only
# inside a 3D viewport's WINDOW region, which is the scoping the poll does
# not do itself. Outside Cinema Mode the poll fails and O falls through to
# its native meaning untouched.
_NAVIGATE_KEYMAPS = (
    ("Object Mode", ('EMPTY', 'WINDOW')),
    ("3D View", ('VIEW_3D', 'WINDOW')),
)

_WALK_KEYMAPS = (
    # "User Interface" FIRST and it is the one that matters: Blender
    # dispatches it ahead of every mode keymap, which is the only place that
    # beats `UI_OT_eyedropper_depth` (which owns E globally, and whose modal
    # then swallows the NEXT key too — that is why Q looked dead). It is a
    # GLOBAL keymap, so only `mixar.director_block_input` may be parked there
    # and only because its poll needs no region scoping to be safe: it does
    # nothing at all, in any context, and the poll limits even that to a
    # directing session.
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
    # dispatches, items keep the order they were REGISTERED in, so a guard
    # added after another addon item still loses its key to it.
    for keymap_name, (space_type, region_type) in _WALK_KEYMAPS:
        keymap = keyconfig.keymaps.new(
            name=keymap_name,
            space_type=space_type,
            region_type=region_type,
        )
        for key in _WALK_KEYS:
            item = keymap.keymap_items.new(
                "mixar.director_block_input",
                type=key,
                value='PRESS',
                head=True,
            )
            addon_keymaps.append((keymap, item))

    for keymap_name, (space_type, region_type) in _NAVIGATE_KEYMAPS:
        keymap = keyconfig.keymaps.new(
            name=keymap_name,
            space_type=space_type,
            region_type=region_type,
        )
        item = keymap.keymap_items.new(
            "mixar.director_aerial",
            type='O',
            value='PRESS',
            head=True,
        )
        addon_keymaps.append((keymap, item))

    # Insert Keyframe is I — the key every Blender user already reaches for,
    # and what the Cinema Mode top strip's keycap hint paints.
    #
    # It has to be registered in the SAME two keymaps the Aerial view uses,
    # for the same reason: Blender's default keymap binds I to
    # `anim.keyframe_insert` in "Object Mode", and View3D walks its WINDOW
    # handlers head to tail (mode keymaps -> "3D View Generic" -> "3D View"),
    # so an item parked only in "3D View" would never be asked. "Object Mode"
    # wins the key while the user is in Object Mode and "3D View" covers the
    # other modes. `MIXAR_OT_director_capture_beat.poll` scopes it to a live
    # directing session, so outside Cinema Mode I falls through to Blender's
    # own keyframe insert untouched.
    for keymap_name, (space_type, region_type) in _NAVIGATE_KEYMAPS:
        keymap = keyconfig.keymaps.new(
            name=keymap_name,
            space_type=space_type,
            region_type=region_type,
        )
        item = keymap.keymap_items.new(
            "mixar.director_capture_beat",
            type='I',
            value='PRESS',
            head=True,
        )
        addon_keymaps.append((keymap, item))

    keymap = keyconfig.keymaps.new(
        name="3D View",
        space_type='VIEW_3D',
        region_type='WINDOW',
    )

    # Camera placement by click: a plain LEFTMOUSE press over the aerial map
    # card, or anywhere in the stage while the AERIAL view is on, places the
    # shot camera (`MIXAR_OT_director_place_camera`, a native modal in
    # view3d_director_place_camera.cc — click or drag, one undo step). It is
    # a PRESS item in this same "3D View" keymap, at its head; the addon
    # keymap is prepended when Blender merges it into the keymap it
    # dispatches, so it is asked before the stock `view3d.select` items
    # (which sit on CLICK with left-click select anyway), and the active
    # tool's keymap — dispatched before "3D View" — binds only CLICK_DRAG for
    # the select and transform tools. The operator's POLL is what scopes it:
    # only over the map the painter published this frame, or inside the
    # stage in Aerial mode, so anywhere else the press falls through
    # untouched. No modifiers and `any=False`: Shift/Ctrl/Alt clicks keep
    # their meaning.
    item = keymap.keymap_items.new(
        "mixar.director_place_camera",
        type='LEFTMOUSE',
        value='PRESS',
        head=True,
    )
    addon_keymaps.append((keymap, item))

    # The wheel and the trackpad over the Cinema columns are NOT bound here.
    # The card is painted into the 3D viewport's own WINDOW region, so the
    # gesture has to beat `view3d.zoom` — past the mode keymaps, the active
    # tool's keymap and the UI layer — and a keymap item never did: two rounds
    # of widening the operator's poll did not make the list scroll, because
    # the poll was never being asked. It is a UI handler now
    # (`view3d_director_cinema_camera_scroll.cc`), which runs ahead of every
    # keymap. `mixar.director_scroll_cameras` stays registered as the
    # scriptable and QA-drivable entry point onto the same scroll, with no
    # key of its own: one gesture, one owner.

    # Esc leaves the aerial view. `mixar.director_aerial_exit` is a separate
    # operator whose poll passes ONLY while `navigation_mode == 'AERIAL'`, so
    # Esc can never enter the mode and keeps its meaning everywhere else.
    item = keymap.keymap_items.new(
        "mixar.director_aerial_exit",
        type='ESC',
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
