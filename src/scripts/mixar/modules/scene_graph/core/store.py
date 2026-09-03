# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-scene scene-graph store.

One SceneGraph per Blender scene, held in a runtime registry keyed by the
scene's pointer (so different scenes never share a graph). The serialized JSON
is mirrored onto the scene's SKIP_SAVE property so it is readable as per-scene
state and inspectable, but never written into the .blend.

The dirty flag lives only in this runtime registry -- never on the Scene -- so
the depsgraph handler that flips it never writes Scene data (no recursion).
"""

import json

from mixar.config.logging_config import get_logger

from ..constants import REL_PARENT_OF, RELATION_TYPES, SCENE_GRAPH_PROP, SCHEMA, VERSION
from .hierarchy import build_hierarchy

logger = get_logger(__name__)


class SceneGraph:
    """Lazily-rebuilt graph for a single scene."""

    def __init__(self):
        self.dirty = True
        self.revision = 0
        self._parent = {}
        self._meta = {}
        self._graph = None

    def mark_dirty(self):
        self.dirty = True

    def refresh(self, scene):
        """Rebuild from the scene if dirty. Returns True if rebuilt."""
        if not self.dirty and self._graph is not None:
            return False
        self._parent, self._meta = build_hierarchy(scene)
        self._graph = self._serialize()
        self.dirty = False
        self.revision += 1
        self._store_on_scene(scene)
        return True

    def graph(self, scene):
        self.refresh(scene)
        return self._graph

    def _serialize(self):
        names = sorted(self._meta)
        idx = {n: i for i, n in enumerate(names)}
        nodes = [{
            "id": n,
            "type": self._meta[n]["type"],
            "coll": self._meta[n]["coll"] or "(none)",
            "root": self._meta[n]["root"],
        } for n in names]
        relations = sorted(
            [idx[p], idx[c], REL_PARENT_OF]
            for c, p in self._parent.items() if p is not None
        )
        return {
            "schema": SCHEMA,
            "version": VERSION,
            "layers_present": ["hierarchy"],
            "node_count": len(nodes),
            "nodes": nodes,
            "layers": {"hierarchy": {
                "relation_types": {str(k): v for k, v in RELATION_TYPES.items()},
                "relations": relations,
            }},
        }

    def _store_on_scene(self, scene):
        # Updates the Scene id (not Object), so the OBJECT-filtered depsgraph
        # handler ignores this write -- no rebuild feedback loop.
        if hasattr(scene, SCENE_GRAPH_PROP):
            try:
                setattr(scene, SCENE_GRAPH_PROP, json.dumps(self._graph))
            except Exception as exc:  # noqa: BLE001 - never break a query
                logger.warning("scene_graph: could not store on scene: %s", exc)


# Runtime registry: scene pointer -> (scene name, SceneGraph). Cleared on
# file load. A deleted scene's address can be reused by a new scene, so the
# cached name is validated on every access and the entry rebuilt on mismatch.
_REGISTRY = {}


def get_scene_graph(scene) -> SceneGraph:
    key = scene.as_pointer()
    cached = _REGISTRY.get(key)
    if cached is not None and cached[0] != scene.name:
        # Pointer reused by a different scene -- the entry is stale.
        cached = None
    if cached is None:
        cached = (scene.name, SceneGraph())
        _REGISTRY[key] = cached
    return cached[1]


def mark_scene_dirty(scene):
    cached = _REGISTRY.get(scene.as_pointer())
    if cached is not None and cached[0] == scene.name:
        cached[1].mark_dirty()
    # If absent or stale, the first get_scene_graph() builds fresh anyway.


def clear_registry():
    _REGISTRY.clear()
