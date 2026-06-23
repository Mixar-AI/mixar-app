# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Entry point: build the live spatial scene graph inside Mixar and exercise it.

Run THIS file from Mixar's Text Editor / Python console. It:
  1. registers the depsgraph watcher (so the graph auto-updates on edits),
  2. builds the layered graph (spatial layer) and reports build time,
  3. saves it to scene_graph.json (next to the .blend, else temp dir),
  4. prints the collapsed summary + a couple of demo tool calls.

After running once, edit the scene (move/add/delete objects) and call
  agent_tools.run_tool("scene_graph_summary")
again -- it refreshes incrementally and STORE.last_ms / STORE.last_mode show how
little work the update took.
"""

import json
import os
import sys
import tempfile

import bpy

# Make the sibling `scene_graph` package importable when run as a loose script.
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:  # __file__ may be undefined in some console contexts
    _txt = getattr(getattr(bpy.context, "space_data", None), "text", None)
    _HERE = os.path.dirname(bpy.path.abspath(_txt.filepath)) if _txt and _txt.filepath else os.getcwd()
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from scene_graph import agent_tools, watcher  # noqa: E402
from scene_graph.store import STORE  # noqa: E402


def _output_path():
    base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else tempfile.gettempdir()
    return os.path.join(base, "scene_graph.json")


def main():
    watcher.register()           # auto-update on every add/modify/delete
    STORE.mark_full()            # force a clean build for this run
    graph = agent_tools.get_view().graph

    path = _output_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    print("=" * 70)
    print(f"Built scene_graph v{graph['version']}: {graph['node_count']} objects, "
          f"{len(graph['layers']['spatial']['relations'])} spatial relations")
    print(f"Build: {STORE.last_ms:.1f} ms ({STORE.last_mode}) | watcher registered")
    print(f"Saved -> {path}")
    print("-" * 70)
    print("Tool: scene_graph_summary")
    print(json.dumps(agent_tools.run_tool("scene_graph_summary"), indent=2))

    # Demo a drill-down on the first object, if any.
    if graph["nodes"]:
        first = graph["nodes"][0]["id"]
        print("-" * 70)
        print(f"Tool: describe_object(object_name='{first}')")
        print(json.dumps(agent_tools.run_tool("describe_object", {"object_name": first}), indent=2))
        print("-" * 70)
        print("Tool: find_objects_in_relation(relation='on_top_of')")
        print(json.dumps(agent_tools.run_tool("find_objects_in_relation", {"relation": "on_top_of"}), indent=2))
    print("=" * 70)
    return graph


if __name__ == "__main__":
    main()
