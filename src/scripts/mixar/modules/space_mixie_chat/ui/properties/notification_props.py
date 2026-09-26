# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent notification preferences.

``mixar_completion_sound`` mirrors the persisted ``completion_sound`` config
key and ``mixar_notifications_muted`` the ``notifications_muted`` key (see
``core/completion_sound.py``) so the picker can live in Edit > Preferences >
System. Both are SKIP_SAVE — per-user preferences whose truth is the config
overlay, not the .blend.

The sound options are backend-driven (``core/sound_catalog.py``): the enum
items are built dynamically from the cached catalog, so new sounds appear
without a client release. get/set map the stored config string to an enum
index because a dynamic-items enum has no static string default.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty

from ...core import sound_catalog
from ...core.completion_sound import (
    OFF,
    available_sounds,
    get_completion_sound,
    get_notifications_muted,
    set_completion_sound,
    set_notifications_muted,
)

# Keep a reference to the last items list Blender was handed: an EnumProperty
# with a callback that returns freshly-built strings crashes if those strings
# are garbage-collected while the enum is live.
_items_cache: list = []

# Revalidate the catalog on this cadence so dashboard edits (a new sound,
# a relabel) reach a running app without a restart. Matches the generation
# catalog's revalidation approach.
_REFRESH_INTERVAL_S = 300.0


def _sound_items(self, context):
    global _items_cache
    _items_cache = [
        (value, label,
         "Do not play a sound when an agent run finishes" if value == OFF
         else f"Play {label} when an agent run finishes")
        for value, label in available_sounds()
    ]
    return _items_cache


def _sound_get(self):
    stored = get_completion_sound()
    for index, item in enumerate(_items_cache or _sound_items(self, None)):
        if item[0] == stored:
            return index
    return 0


def _sound_set(self, value):
    items = _items_cache or _sound_items(self, None)
    if 0 <= value < len(items):
        set_completion_sound(items[value][0])


def _on_mute_change(self, _context) -> None:
    set_notifications_muted(self.mixar_notifications_muted)


def _revalidate_catalog() -> float:
    sound_catalog.refresh_async()
    return _REFRESH_INTERVAL_S


def register():
    bpy.types.WindowManager.mixar_completion_sound = EnumProperty(
        name="Task Completion Sound",
        description="Sound played when an agent run finishes",
        items=_sound_items,
        get=_sound_get,
        set=_sound_set,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixar_notifications_muted = BoolProperty(
        name="Mute Notifications",
        description="Silence all agent notifications, keeping your sound choice",
        default=get_notifications_muted(),
        options={'SKIP_SAVE'},
        update=_on_mute_change,
    )

    sound_catalog.initialize()
    if not bpy.app.timers.is_registered(_revalidate_catalog):
        # First tick ~2s after startup, then periodically.
        bpy.app.timers.register(_revalidate_catalog, first_interval=2.0)


def unregister():
    if bpy.app.timers.is_registered(_revalidate_catalog):
        bpy.app.timers.unregister(_revalidate_catalog)
    if hasattr(bpy.types.WindowManager, "mixar_completion_sound"):
        del bpy.types.WindowManager.mixar_completion_sound
    if hasattr(bpy.types.WindowManager, "mixar_notifications_muted"):
        del bpy.types.WindowManager.mixar_notifications_muted
