# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Properties for selection assist.

``Scene.mixar_suggested_outline`` is the Python -> C++ ghost-outline bridge:
the overlay engine (overlay_instance.cc) reads it every sync and draws the
named objects with the "suggested" outline category. SKIP_SAVE — transient
UI state, never persisted. HIDDEN — not user-facing.

``WindowManager.mixar_selection_assist_enabled`` is the session on/off
switch (WindowManager: no .blend persistence, resets to on each launch).
"""

import bpy

from ...constants import ENABLE_PROP, GHOST_PROP


def register():
    setattr(
        bpy.types.Scene,
        GHOST_PROP,
        bpy.props.StringProperty(
            name="Suggested Outline Objects",
            description="Internal: objects ghost-outlined as selection suggestions",
            default="",
            options={'HIDDEN', 'SKIP_SAVE'},
        ),
    )
    setattr(
        bpy.types.WindowManager,
        ENABLE_PROP,
        bpy.props.BoolProperty(
            name="Selection Suggestions",
            description="Suggest expanding the selection to matching parts",
            default=True,
        ),
    )


def unregister():
    for owner, prop in ((bpy.types.Scene, GHOST_PROP),
                        (bpy.types.WindowManager, ENABLE_PROP)):
        try:
            delattr(owner, prop)
        except Exception:
            pass
