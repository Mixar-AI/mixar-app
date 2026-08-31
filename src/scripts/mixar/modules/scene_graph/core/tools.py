# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing tool surface for traversing the scene graph.

Every tool takes an explicit `scene` (mirrors SessionManager -- no implicit
bpy.context.scene), so it is per-scene by construction. run_tool() returns a
JSON-serializable dict, suitable for the agent's __RESULT__ convention.
TOOL_SPECS is ready to register in the backend tool registry.
"""

from .store import get_scene_graph
from .traversal import GraphView

# Cache one GraphView per scene pointer, keyed by the store revision, so
# repeated tool calls in a turn don't re-wrap the same graph.
_VIEW_CACHE = {}


def get_view(scene):
    sg = get_scene_graph(scene)
    graph = sg.graph(scene)
    key = scene.as_pointer()
    cached = _VIEW_CACHE.get(key)
    if cached is None or cached[0] != sg.revision:
        cached = (sg.revision, GraphView(graph))
        _VIEW_CACHE[key] = cached
    return cached[1]


TOOL_SPECS = [
    {"name": "get_graph",
     "description": "Fetch the entire scene graph as JSON (nodes + hierarchy edges). "
                    "Prefer the traversal tools for large scenes.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "scene_graph_summary",
     "description": "Overview of the scene's object hierarchy: object count, "
                    "the top-level roots (the meaningful units), and a type breakdown.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "roots",
     "description": "The top-level objects (the agent's entry point). Drill in with children/descendants.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "children",
     "description": "Direct children of an object in the Outliner hierarchy.",
     "parameters": {"type": "object",
                    "properties": {"object_name": {"type": "string"}},
                    "required": ["object_name"]}},
    {"name": "descendants",
     "description": "All descendants (the full subtree) of an object.",
     "parameters": {"type": "object",
                    "properties": {"object_name": {"type": "string"}},
                    "required": ["object_name"]}},
    {"name": "ancestors",
     "description": "The parent chain from an object up to its top-level root.",
     "parameters": {"type": "object",
                    "properties": {"object_name": {"type": "string"}},
                    "required": ["object_name"]}},
    {"name": "describe_object",
     "description": "An object's type, parent, children, root and collection.",
     "parameters": {"type": "object",
                    "properties": {"object_name": {"type": "string"}},
                    "required": ["object_name"]}},
]


def run_tool(scene, name, params=None):
    params = params or {}
    if name == "get_graph":
        return get_scene_graph(scene).graph(scene)
    view = get_view(scene)
    handler = {
        "scene_graph_summary": view.summary,
        "roots": view.roots,
        "children": view.children_of,
        "descendants": view.descendants,
        "ancestors": view.ancestors,
        "describe_object": view.describe,
    }.get(name)
    if handler is None:
        return {"error": f"unknown tool '{name}'", "available": [t["name"] for t in TOOL_SPECS]}
    try:
        return handler(**params)
    except TypeError as exc:
        return {"error": f"bad parameters for '{name}': {exc}"}
