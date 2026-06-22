# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Depsgraph watcher: marks the store dirty on every add/modify/delete.

Follows Mixar's handler->flag pattern. The handler does the cheapest possible
work -- record which object ids the depsgraph touched and raise a flag. All the
real recomputation is deferred to STORE.refresh(), which runs lazily when the
agent next queries the graph.

Standalone usage (scripts/dev): call register() once per session to attach the
handlers; call unregister() to detach. When this graduates into the addon, the
register()/unregister() pair moves into a bootstrap module.
"""

import bpy
from bpy.app.handlers import persistent

from scene_graph.store import STORE, OBJECT_TYPES

_BUSY = False


@persistent
def _on_depsgraph(scene, depsgraph):
    global _BUSY
    if _BUSY:
        return
    # Ignore updates that can't touch the spatial layer (e.g. material-only edits).
    try:
        if not depsgraph.id_type_updated('OBJECT'):
            return
    except Exception:
        pass
    names = [u.id.name for u in depsgraph.updates
             if isinstance(u.id, bpy.types.Object) and u.id.type in OBJECT_TYPES]
    if names:
        STORE.note_updated(names)
    # Add/delete is resolved lazily by a set-diff in refresh(); just flag it.
    STORE.note_membership_maybe_changed()


@persistent
def _on_load(*args):
    STORE.reset()


def register():
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    for handlers, fn in (
        (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
        (bpy.app.handlers.load_post, _on_load),
    ):
        if fn in handlers:
            handlers.remove(fn)
