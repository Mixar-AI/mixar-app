# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene snapshot registry for selection suggestions.

Same shape as the mention registry (space_mixie_chat/core/mention_registry.py):
one module-level singleton, a cheap dirty flag set from a depsgraph handler,
and lazy rebuild on query — selection polls never walk bpy.data unless the
scene actually changed. The heavy lifting (grouping maps) lives in the pure
SceneSnapshotIndex so it stays unit-testable.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from .keys import geometry_signature, name_stem
from .ladder import ObjectRecord, SceneSnapshotIndex

logger = get_logger(__name__)


def _root_name(obj):
    seen = set()
    while obj.parent is not None and obj.parent.name not in seen:
        seen.add(obj.name)
        obj = obj.parent
    return obj.name


def _topology_counts(obj):
    data = obj.data
    if obj.type == 'MESH' and data is not None:
        return (len(data.vertices), len(data.edges), len(data.polygons))
    if obj.type == 'CURVE' and data is not None:
        try:
            points = sum(
                len(s.bezier_points) + len(s.points) for s in data.splines
            )
            return (len(data.splines), points)
        except Exception:
            return ()
    return ()


def gather_records(view_layer):
    """Snapshot the view layer's selectable objects as ObjectRecords."""
    records = []
    for obj in view_layer.objects:
        try:
            if obj.hide_get(view_layer=view_layer) or obj.hide_select:
                continue
            materials = tuple(
                slot.material.name for slot in obj.material_slots if slot.material
            )
            records.append(
                ObjectRecord(
                    name=obj.name,
                    obj_type=obj.type,
                    root=_root_name(obj),
                    signature=geometry_signature(
                        obj.type, tuple(obj.dimensions), _topology_counts(obj)
                    ),
                    stem=name_stem(obj.name),
                    materials=materials,
                )
            )
        except Exception:
            logger.debug("selection assist: record gather failed for an object",
                         exc_info=True)
    return records


class SceneRegistry:
    """Lazily refreshed SceneSnapshotIndex (singleton, see REGISTRY below)."""

    def __init__(self):
        self._index = None
        self._view_layer_key = None
        self._dirty = True

    # -- handler-facing (must stay cheap) ----------------------------------

    def note_dirty(self):
        self._dirty = True

    # -- query-facing (lazy heavy work) -------------------------------------

    def index(self, view_layer):
        key = (getattr(view_layer, "name", None), id(view_layer))
        if self._dirty or self._index is None or key != self._view_layer_key:
            self._index = SceneSnapshotIndex(gather_records(view_layer))
            self._view_layer_key = key
            self._dirty = False
        return self._index


REGISTRY = SceneRegistry()


@persistent
def _on_depsgraph_update(scene, depsgraph=None):
    REGISTRY.note_dirty()


@persistent
def _on_load_post(_filepath=None):
    REGISTRY.note_dirty()


def register_handlers():
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister_handlers():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
