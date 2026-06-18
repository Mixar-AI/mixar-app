"""Convert the agent triplet graph into standard node-link JSON for visualizers.

The agent graph stores relations as compact integer triplets nested under
`layers.<name>.relations`. Graph viewers (D3, Gephi, networkx, cytoscape, etc.)
expect a top-level `edges`/`links` array of {source, target, label}. This
expands the triplets into that form, resolving indices back to object names.

Usage (plain python, no Blender needed):
    python3 scene_graph_to_nodelink.py /path/to/scene_graph.json
writes /path/to/scene_graph_nodelink.json
"""

import json
import os
import sys


def to_nodelink(graph):
    nodes = graph["nodes"]
    out_nodes = [{
        "id": n["id"],
        "x": n["c"][0], "y": n["c"][1], "z": n["c"][2],
        "collection": n.get("coll", "(none)"),
    } for n in nodes]

    edges = []
    for layer_name, layer in graph.get("layers", {}).items():
        rt = layer["relation_types"]
        for s, o, t in layer["relations"]:
            edges.append({
                "source": nodes[s]["id"],
                "target": nodes[o]["id"],
                "label": rt[str(t)],
                "layer": layer_name,
            })

    return {"directed": True, "nodes": out_nodes, "edges": edges, "links": edges}


def main(path):
    graph = json.load(open(path, encoding="utf-8"))
    nl = to_nodelink(graph)
    out = os.path.splitext(path)[0] + "_nodelink.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(nl, f, indent=2)
    print(f"{len(nl['nodes'])} nodes, {len(nl['edges'])} edges -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scene_graph.json")
