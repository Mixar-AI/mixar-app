# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read-only views/queries over a built scene graph.

These are the primitives the agent traverses (SayPlan collapse->expand): a
compact `summary` to orient, then per-object / per-relation drill-down that
renders triplets into natural-language edges (the form frozen LLMs reason best
over). Pure-Python and bpy-free, so it is unit-testable without Blender.
"""


def _phrase(name):
    return name.replace("_", " ")


class GraphView:
    def __init__(self, graph):
        self.graph = graph
        self.nodes = graph["nodes"]
        self.name_to_idx = {n["id"]: i for i, n in enumerate(self.nodes)}

    # -- internals -------------------------------------------------------------

    def _layer(self, layer):
        return self.graph.get("layers", {}).get(layer)

    @staticmethod
    def _name_to_id(relation_types):
        return {v: int(k) for k, v in relation_types.items()}

    # -- collapsed overview (the agent's entry point) --------------------------

    def summary(self, layer="spatial"):
        """Counts only -- cheap orientation before drilling in."""
        by_coll = {}
        for n in self.nodes:
            c = n.get("coll", "(none)")
            by_coll[c] = by_coll.get(c, 0) + 1

        rel_counts = {}
        L = self._layer(layer)
        if L:
            rt = L["relation_types"]
            for _s, _o, t in L["relations"]:
                name = rt[str(t)]
                rel_counts[name] = rel_counts.get(name, 0) + 1

        return {
            "object_count": len(self.nodes),
            "objects_by_collection": by_coll,
            "layers": list(self.graph.get("layers", {})),
            "relation_counts": {layer: rel_counts},
        }

    # -- per-object expansion (named edges) ------------------------------------

    def describe(self, object_name, layer="spatial"):
        idx = self.name_to_idx.get(object_name)
        if idx is None:
            return {"error": f"unknown object '{object_name}'"}
        L = self._layer(layer)
        if not L:
            return {"error": f"unknown layer '{layer}'"}
        rt = L["relation_types"]
        edges = []
        for s, o, t in L["relations"]:
            if s == idx:
                edges.append(f"{object_name} {_phrase(rt[str(t)])} {self.nodes[o]['id']}")
            elif o == idx:
                edges.append(f"{self.nodes[s]['id']} {_phrase(rt[str(t)])} {object_name}")
        return {"object": object_name, "layer": layer, "relations": edges}

    def neighbors(self, object_name, layer="spatial", relation=None):
        idx = self.name_to_idx.get(object_name)
        if idx is None:
            return {"error": f"unknown object '{object_name}'"}
        L = self._layer(layer)
        if not L:
            return {"error": f"unknown layer '{layer}'"}
        rt = L["relation_types"]
        rid = None
        if relation is not None:
            rid = self._name_to_id(rt).get(relation)
            if rid is None:
                return {"error": f"unknown relation '{relation}'", "available": list(rt.values())}
        out = []
        for s, o, t in L["relations"]:
            if rid is not None and t != rid:
                continue
            if s == idx:
                out.append({"relation": rt[str(t)], "object": self.nodes[o]["id"], "role": "subject"})
            elif o == idx:
                out.append({"relation": rt[str(t)], "object": self.nodes[s]["id"], "role": "object"})
        return {"object": object_name, "layer": layer, "neighbors": out}

    # -- per-relation lookup ---------------------------------------------------

    def find(self, relation, layer="spatial", object_name=None):
        L = self._layer(layer)
        if not L:
            return {"error": f"unknown layer '{layer}'"}
        rt = L["relation_types"]
        rid = self._name_to_id(rt).get(relation)
        if rid is None:
            return {"error": f"unknown relation '{relation}'", "available": list(rt.values())}
        anchor = self.name_to_idx.get(object_name) if object_name else None
        if object_name and anchor is None:
            return {"error": f"unknown object '{object_name}'"}
        matches = []
        for s, o, t in L["relations"]:
            if t != rid:
                continue
            if anchor is not None and anchor not in (s, o):
                continue
            matches.append(f"{self.nodes[s]['id']} {_phrase(relation)} {self.nodes[o]['id']}")
        return {"relation": relation, "layer": layer, "matches": matches}
