"""Live, incrementally-maintained spatial scene graph.

Keyed by object NAME (stable under deletion -- integer indices are not), so an
edit only touches edges incident to the changed objects. The expensive O(N^2)
pass runs only on the first build or when the scene's overall bounds shift
(which moves every distance threshold). Index projection to the compact triplet
form happens at serialization time.

Update flow (lazy):
  depsgraph handler -> note_updated()/note_membership_maybe_changed()  (cheap)
  agent query       -> refresh()  (recompute only what changed)        (lazy)
"""

import math
import time

from scene_graph.registry import NodeRegistry, world_box, aabb_gap, round_vec
from scene_graph.spatial_layer import SpatialLayer, PROXIMITY_FACTOR, REL_ON_TOP_OF

OBJECT_TYPES = ("MESH",)
DIAG_EPS = 0.01  # relative scene-diagonal change that forces a relation rebuild


class SceneGraphStore:
    def __init__(self):
        self.reset()

    def reset(self):
        self._boxes = {}        # name -> world box dict
        self._coll = {}         # name -> collection name
        self._relations = set()  # (subject_name, object_name, relation_id)
        self._incident = {}     # name -> set of relation tuples touching it
        self._scene_min = [0.0, 0.0, 0.0]
        self._scene_max = [0.0, 0.0, 0.0]
        self._diag = 0.0
        self.revision = 0
        self._built = False
        self._dirty_names = set()   # added/modified object names from the handler
        self._membership = True     # set-diff (add/delete) may be pending
        self.last_ms = 0.0
        self.last_mode = "none"

    # -- handler-facing (must stay cheap) -------------------------------------

    def note_updated(self, names):
        self._dirty_names.update(names)

    def note_membership_maybe_changed(self):
        self._membership = True

    def mark_full(self):
        self._built = False

    def has_pending(self):
        return (not self._built) or bool(self._dirty_names) or self._membership

    # -- query-facing (lazy heavy work) ---------------------------------------

    def refresh(self, scene=None):
        """Bring the graph up to date. Returns True if anything changed."""
        import bpy
        scene = scene or bpy.context.scene
        t0 = time.perf_counter()

        if not self._built:
            self._full_rebuild(scene)
            self._built = True
            self._membership = False
            self._dirty_names.clear()
            self.revision += 1
            self.last_mode = "full"
            self.last_ms = (time.perf_counter() - t0) * 1000.0
            return True

        added, deleted, modified = self._resolve_pending(scene)
        if not (added or deleted or modified):
            return False

        depsgraph = bpy.context.evaluated_depsgraph_get()
        coll_map = NodeRegistry._collection_map()

        for name in deleted:
            self._remove_node(name)

        touched = added | modified
        for name in touched:
            obj = scene.objects.get(name)
            if obj is None:           # vanished between notify and refresh
                self._remove_node(name)
                continue
            self._boxes[name] = world_box(obj, depsgraph)
            self._coll[name] = coll_map.get(name, "")
            self._incident.setdefault(name, set())

        old_diag = self._diag
        self._recompute_bounds()

        if old_diag > 0.0 and abs(self._diag - old_diag) > old_diag * DIAG_EPS:
            # Thresholds shifted scene-wide -> rebuild relations from current boxes.
            self._rebuild_relations()
            self.last_mode = "full(bounds)"
        else:
            for name in touched:
                if name in self._boxes:
                    self._recompute_node_relations(name)
            self.last_mode = "incremental"

        self.revision += 1
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        return True

    # -- serialization ---------------------------------------------------------

    def to_graph_dict(self):
        from scene_graph.builder import AXES_LEGEND, SCHEMA, VERSION
        names = sorted(self._boxes)
        idx = {n: i for i, n in enumerate(names)}
        nodes = [{
            "id": n,
            "c": round_vec(self._boxes[n]["centroid"]),
            "d": round_vec(self._boxes[n]["size"]),
            "coll": self._coll.get(n) or "(none)",
        } for n in names]
        relations = sorted([idx[s], idx[o], rid] for s, o, rid in self._relations)
        return {
            "schema": SCHEMA, "version": VERSION,
            "axes_legend": AXES_LEGEND,
            "scene_bounds": {"min": round_vec(self._scene_min),
                             "max": round_vec(self._scene_max),
                             "diagonal": round(self._diag, 4)},
            "node_count": len(nodes),
            "nodes": nodes,
            "layers": {"spatial": {
                "relation_types": SpatialLayer().legend(),
                "relations": relations,
            }},
        }

    # -- internals -------------------------------------------------------------

    def _resolve_pending(self, scene):
        if not self._dirty_names and not self._membership:
            return set(), set(), set()
        current = {o.name for o in scene.objects if o.type in OBJECT_TYPES}
        known = set(self._boxes)
        added = current - known
        deleted = known - current
        modified = (self._dirty_names & current) - added
        self._dirty_names = set()
        self._membership = False
        return added, deleted, modified

    def _full_rebuild(self, scene):
        reg = NodeRegistry.from_scene(scene, object_types=OBJECT_TYPES)
        self._boxes = {n.id: n.box for n in reg.nodes}
        self._coll = {n.id: n.collection for n in reg.nodes}
        self._scene_min = list(reg.scene_min)
        self._scene_max = list(reg.scene_max)
        self._diag = reg.scene_diagonal
        self._rebuild_relations()

    def _rebuild_relations(self):
        self._relations = set()
        self._incident = {n: set() for n in self._boxes}
        names = list(self._boxes)
        for i in range(len(names)):
            a = names[i]
            ba = self._boxes[a]
            for j in range(i + 1, len(names)):
                b = names[j]
                for tup in self._pair_relations(a, ba, b, self._boxes[b]):
                    self._add_relation(tup)

    def _recompute_node_relations(self, name):
        self._drop_incident(name)
        box = self._boxes[name]
        for other, obox in self._boxes.items():
            if other == name:
                continue
            for tup in self._pair_relations(name, box, other, obox):
                self._add_relation(tup)

    def _pair_relations(self, na, ba, nb, bb):
        rels = []
        support = SpatialLayer._support(ba, bb, self._diag)
        support_here = False
        if support == "a_on_b":
            rels.append((na, nb, REL_ON_TOP_OF)); support_here = True
        elif support == "b_on_a":
            rels.append((nb, na, REL_ON_TOP_OF)); support_here = True

        gap = aabb_gap(ba, bb)
        if self._diag > 0.0 and gap > self._diag * PROXIMITY_FACTOR:
            return rels  # not near -> directions suppressed
        for rid in SpatialLayer._directions(ba, bb, skip_z=support_here):
            rels.append((nb, na, rid))  # describe B relative to A
        return rels

    def _add_relation(self, tup):
        self._relations.add(tup)
        self._incident.setdefault(tup[0], set()).add(tup)
        self._incident.setdefault(tup[1], set()).add(tup)

    def _drop_incident(self, name):
        for tup in list(self._incident.get(name, ())):
            self._relations.discard(tup)
            self._incident.get(tup[0], set()).discard(tup)
            self._incident.get(tup[1], set()).discard(tup)
        self._incident[name] = set()

    def _remove_node(self, name):
        self._drop_incident(name)
        self._boxes.pop(name, None)
        self._coll.pop(name, None)
        self._incident.pop(name, None)

    def _recompute_bounds(self):
        if not self._boxes:
            self._scene_min = [0.0, 0.0, 0.0]
            self._scene_max = [0.0, 0.0, 0.0]
            self._diag = 0.0
            return
        boxes = self._boxes.values()
        self._scene_min = [min(b["min"][i] for b in boxes) for i in range(3)]
        self._scene_max = [max(b["max"][i] for b in boxes) for i in range(3)]
        self._diag = math.sqrt(sum((self._scene_max[i] - self._scene_min[i]) ** 2 for i in range(3)))


# Module-level singleton (mirrors Mixar's ConnectionManager singleton pattern).
STORE = SceneGraphStore()
