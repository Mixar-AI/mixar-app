"""Self-contained ObjectGraph (Outliner hierarchy) for Mixar.

This builds the structural BACKBONE only: every scene object is a node, and the
edges are the parent/child relationships from the Outliner (your `*_Root`
Empties and their descendants). The spatial layer (on_top_of / left_of / ...)
will be layered on top of these same nodes later -- it is intentionally NOT
emitted yet.

Encoding (consistent with how the spatial layer will be added):
  nodes        : every object -> {id, type, coll, root}
  layers.hierarchy.relations : triplets [parent_idx, child_idx, 1]  (parent_of)

No external imports: open in Mixar's Text Editor and Run Script (or paste into
the Python Console). It builds the graph, registers an auto-update watcher,
saves JSON, prints a summary. Query later via the bpy handle:
    import bpy
    bpy.mixar_sg.query("roots")
    bpy.mixar_sg.query("children",       {"object_name": "Cast_Iron_Mooring_Bollard_Root.003"})
    bpy.mixar_sg.query("describe_object", {"object_name": "Cast_Iron_Mooring_Bollard_Root.003"})
"""

import json
import os
import tempfile
import time
import types

import bpy
from bpy.app.handlers import persistent

# --------------------------------------------------------------------------- #
# Output: set to save JSON somewhere specific; "" auto-picks (.blend dir/temp).
# --------------------------------------------------------------------------- #
OUTPUT_PATH = ""

REL_PARENT_OF = 1
RELATION_TYPES = {REL_PARENT_OF: "parent_of"}


# --------------------------------------------------------------------------- #
# Hierarchy extraction
# --------------------------------------------------------------------------- #
def collection_map():
    """name -> first collection it belongs to."""
    m = {}
    for coll in bpy.data.collections:
        for obj in coll.objects:
            m.setdefault(obj.name, coll.name)
    return m


def build_hierarchy(scene):
    """Return (parent, meta): child name -> parent name (or None); name -> attrs."""
    objs = list(scene.objects)
    names = {o.name for o in objs}
    parent = {}
    for o in objs:
        p = o.parent
        parent[o.name] = p.name if (p is not None and p.name in names) else None

    def root_of(name):
        cur, guard = name, 0
        while parent.get(cur) and guard < 100000:
            cur, guard = parent[cur], guard + 1
        return cur

    coll = collection_map()
    meta = {o.name: {"type": o.type, "coll": coll.get(o.name, ""), "root": root_of(o.name)}
            for o in objs}
    return parent, meta


# --------------------------------------------------------------------------- #
# Store (lazy full rebuild -- hierarchy is cheap, no geometry needed)
# --------------------------------------------------------------------------- #
class SceneGraphStore:
    def __init__(self):
        self.reset()

    def reset(self):
        self._parent, self._meta = {}, {}
        self.revision, self._built, self._dirty = 0, False, True
        self.last_ms = 0.0

    def mark_dirty(self):
        self._dirty = True

    def mark_full(self):
        self._built = False
        self._dirty = True

    def refresh(self, scene=None):
        scene = scene or bpy.context.scene
        if self._built and not self._dirty:
            return False
        t0 = time.perf_counter()
        self._parent, self._meta = build_hierarchy(scene)
        self._built, self._dirty = True, False
        self.revision += 1
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        return True

    def to_graph_dict(self):
        names = sorted(self._meta)
        idx = {n: i for i, n in enumerate(names)}
        nodes = [{"id": n, "type": self._meta[n]["type"],
                  "coll": self._meta[n]["coll"] or "(none)",
                  "root": self._meta[n]["root"]} for n in names]
        relations = sorted([idx[p], idx[c], REL_PARENT_OF]
                           for c, p in self._parent.items() if p is not None)
        return {
            "schema": "mixar.scene_graph", "version": 5,
            "layers_present": ["hierarchy"],
            "node_count": len(nodes), "nodes": nodes,
            "layers": {"hierarchy": {
                "relation_types": {str(k): v for k, v in RELATION_TYPES.items()},
                "relations": relations}},
        }


STORE = SceneGraphStore()


# --------------------------------------------------------------------------- #
# Traversal (agent-facing): walk the hierarchy
# --------------------------------------------------------------------------- #
class GraphView:
    def __init__(self, graph):
        self.graph = graph
        self.nodes = graph["nodes"]
        self.idx = {n["id"]: i for i, n in enumerate(self.nodes)}
        self.children, self.parent = {}, {}
        for p, c, _t in graph["layers"]["hierarchy"]["relations"]:
            self.children.setdefault(p, []).append(c)
            self.parent[c] = p

    def roots(self):
        return {"roots": [n["id"] for i, n in enumerate(self.nodes) if i not in self.parent]}

    def summary(self):
        by_type = {}
        for n in self.nodes:
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        roots = [n["id"] for i, n in enumerate(self.nodes) if i not in self.parent]
        return {"object_count": len(self.nodes), "root_count": len(roots),
                "roots": roots, "by_type": by_type,
                "edge_count": len(self.graph["layers"]["hierarchy"]["relations"])}

    def children_of(self, object_name):
        i = self.idx.get(object_name)
        if i is None:
            return {"error": f"unknown object '{object_name}'"}
        return {"object": object_name,
                "children": [self.nodes[c]["id"] for c in self.children.get(i, [])]}

    def descendants(self, object_name):
        i = self.idx.get(object_name)
        if i is None:
            return {"error": f"unknown object '{object_name}'"}
        out, stack = [], list(self.children.get(i, []))
        while stack:
            c = stack.pop()
            out.append(self.nodes[c]["id"])
            stack.extend(self.children.get(c, []))
        return {"object": object_name, "descendant_count": len(out), "descendants": out}

    def ancestors(self, object_name):
        i = self.idx.get(object_name)
        if i is None:
            return {"error": f"unknown object '{object_name}'"}
        chain, cur = [], i
        while cur in self.parent:
            cur = self.parent[cur]
            chain.append(self.nodes[cur]["id"])
        return {"object": object_name, "ancestors": chain}

    def describe(self, object_name):
        i = self.idx.get(object_name)
        if i is None:
            return {"error": f"unknown object '{object_name}'"}
        node = self.nodes[i]
        kids = self.children.get(i, [])
        return {"object": object_name, "type": node["type"], "root": node["root"],
                "collection": node["coll"],
                "parent": self.nodes[self.parent[i]]["id"] if i in self.parent else None,
                "child_count": len(kids),
                "children": [self.nodes[c]["id"] for c in kids]}


_VIEW = {"view": None, "rev": None}


def get_view(rebuild=False):
    if rebuild:
        STORE.mark_full()
    STORE.refresh()
    if _VIEW["view"] is None or _VIEW["rev"] != STORE.revision:
        _VIEW["view"] = GraphView(STORE.to_graph_dict())
        _VIEW["rev"] = STORE.revision
    return _VIEW["view"]


def run_tool(name, params=None):
    v, p = get_view(), params or {}
    fn = {"scene_graph_summary": v.summary, "roots": v.roots,
          "children": v.children_of, "descendants": v.descendants,
          "ancestors": v.ancestors, "describe_object": v.describe}.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**p)
    except TypeError as e:
        return {"error": f"bad parameters for '{name}': {e}"}


# --------------------------------------------------------------------------- #
# Depsgraph watcher (auto-update on add/modify/delete)
# --------------------------------------------------------------------------- #
_TAG = "_mixar_sg"


@persistent
def _on_depsgraph(scene, depsgraph):
    try:
        if not depsgraph.id_type_updated('OBJECT'):
            return
    except Exception:
        pass
    STORE.mark_dirty()


@persistent
def _on_load(*args):
    STORE.reset()


_on_depsgraph._mixar_sg = True
_on_load._mixar_sg = True


def _purge(handler_list):
    for h in list(handler_list):
        if getattr(h, _TAG, False):
            handler_list.remove(h)


def register():
    _purge(bpy.app.handlers.depsgraph_update_post)
    _purge(bpy.app.handlers.load_post)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.handlers.load_post.append(_on_load)


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
def _out_path():
    if OUTPUT_PATH:
        return bpy.path.abspath(OUTPUT_PATH)
    base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else tempfile.gettempdir()
    return os.path.join(base, "scene_graph.json")


def main():
    register()
    STORE.mark_full()
    graph = get_view().graph

    path = _out_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    bpy.mixar_sg = types.SimpleNamespace(store=STORE, query=run_tool, view=get_view)

    print("=" * 70)
    print(f"ObjectGraph v{graph['version']}: {graph['node_count']} objects, "
          f"{len(graph['layers']['hierarchy']['relations'])} parent_of edges  "
          f"({STORE.last_ms:.1f} ms)")
    print(f"saved -> {path}")
    print("-" * 70)
    s = run_tool("scene_graph_summary")
    print(f"{s['root_count']} top-level roots, by_type={s['by_type']}")
    print("roots:", s["roots"])
    print("=" * 70)
    print("Query later:  import bpy; bpy.mixar_sg.query('children', {'object_name': '<root>'})")
    return graph


if __name__ == "__main__":
    main()
