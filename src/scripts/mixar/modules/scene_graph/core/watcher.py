# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Depsgraph + load handlers that keep the per-scene graph fresh.

Follows the Mixar handler pattern: the depsgraph handler does the cheapest
possible work -- mark the updated scene's graph dirty. The actual rebuild
happens lazily when a tool next queries that scene. Filtered to OBJECT updates
so material-only edits (and the store's own Scene-property write) don't dirty it.
"""

import bpy
from bpy.app.handlers import persistent

from .store import clear_registry, mark_scene_dirty


@persistent
def _on_depsgraph(scene, depsgraph):
    try:
        if not depsgraph.id_type_updated('OBJECT'):
            return
    except Exception:  # noqa: BLE001 - never break the depsgraph callback
        pass
    mark_scene_dirty(scene)


@persistent
def _on_load(*_args):
    clear_registry()


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
    (bpy.app.handlers.load_post, _on_load),
)


def register():
    for handler_list, fn in _HANDLERS:
        if fn not in handler_list:
            handler_list.append(fn)


def unregister():
    for handler_list, fn in _HANDLERS:
        if fn in handler_list:
            handler_list.remove(fn)
