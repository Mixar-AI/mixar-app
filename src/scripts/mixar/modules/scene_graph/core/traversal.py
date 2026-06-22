# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only traversal over a built hierarchy graph.

Pure-Python (no bpy): operates on the serialized graph dict, so it is
unit-testable. These are the primitives the agent walks -- start at `roots`,
then drill via `children` / `descendants` (SayPlan collapse->expand).
"""


class GraphView:
    def __init__(self, graph):
        self.graph = graph
        self.nodes = graph["nodes"]
        self.idx = {n["id"]: i for i, n in enumerate(self.nodes)}
        self.children = {}
        self.parent = {}
        for p, c, _t in graph["layers"]["hierarchy"]["relations"]:
            self.children.setdefault(p, []).append(c)
            self.parent[c] = p

    def _root_indices(self):
        return [i for i in range(len(self.nodes)) if i not in self.parent]

    def roots(self):
        return {"roots": [self.nodes[i]["id"] for i in self._root_indices()]}

    def summary(self):
        by_type = {}
        for n in self.nodes:
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        roots = [self.nodes[i]["id"] for i in self._root_indices()]
        return {
            "object_count": len(self.nodes),
            "root_count": len(roots),
            "roots": roots,
            "by_type": by_type,
            "edge_count": len(self.graph["layers"]["hierarchy"]["relations"]),
        }

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
        return {
            "object": object_name,
            "type": node["type"],
            "root": node["root"],
            "collection": node["coll"],
            "parent": self.nodes[self.parent[i]]["id"] if i in self.parent else None,
            "child_count": len(kids),
            "children": [self.nodes[c]["id"] for c in kids],
        }
