# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Agent-facing tool surface for traversing the spatial scene graph.

The agent never ingests the whole graph -- it calls these tools to orient
(`scene_graph_summary`) then drill in (`describe_object`, `neighbors`,
`find_objects_in_relation`). TOOL_SPECS is ready to register in the backend
tool registry; run_tool() is the dispatch each tool's executor script calls.

The graph is held by the live STORE, which the depsgraph watcher keeps dirty.
get_view() lazily refreshes the store (incremental -- cost proportional to what
changed) and rebuilds the GraphView only when the store's revision advances, so
repeated tool calls in one turn are free.
"""

from scene_graph.store import STORE
from scene_graph.traversal import GraphView

_CACHE = {"view": None, "rev": None}


def get_view(rebuild=False):
    if rebuild:
        STORE.mark_full()
    STORE.refresh()
    if _CACHE["view"] is None or _CACHE["rev"] != STORE.revision:
        _CACHE["view"] = GraphView(STORE.to_graph_dict())
        _CACHE["rev"] = STORE.revision
    return _CACHE["view"]


def invalidate():
    STORE.mark_full()


TOOL_SPECS = [
    {
        "name": "scene_graph_summary",
        "description": "Collapsed overview of the spatial scene graph: object "
                       "counts per collection and counts per relation type. Call "
                       "this first to orient before drilling into specific objects.",
        "parameters": {
            "type": "object",
            "properties": {"layer": {"type": "string", "default": "spatial"}},
        },
    },
    {
        "name": "describe_object",
        "description": "All spatial relations involving one object, rendered as "
                       "natural-language edges (e.g. 'Cup on top of Table').",
        "parameters": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "layer": {"type": "string", "default": "spatial"},
            },
            "required": ["object_name"],
        },
    },
    {
        "name": "neighbors",
        "description": "Objects spatially related to the given object, optionally "
                       "filtered to one relation (e.g. on_top_of, left_of).",
        "parameters": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "relation": {"type": "string"},
                "layer": {"type": "string", "default": "spatial"},
            },
            "required": ["object_name"],
        },
    },
    {
        "name": "find_objects_in_relation",
        "description": "Find all object pairs in a given spatial relation "
                       "(on_top_of, left_of, right_of, in_front_of, behind, above, "
                       "below). Optionally anchor to one object.",
        "parameters": {
            "type": "object",
            "properties": {
                "relation": {"type": "string"},
                "object_name": {"type": "string"},
                "layer": {"type": "string", "default": "spatial"},
            },
            "required": ["relation"],
        },
    },
]

_DISPATCH = {
    "scene_graph_summary": lambda v, p: v.summary(**p),
    "describe_object": lambda v, p: v.describe(**p),
    "neighbors": lambda v, p: v.neighbors(**p),
    "find_objects_in_relation": lambda v, p: v.find(**p),
}


def run_tool(name, params=None, rebuild=False):
    """Dispatch a tool call. Returns a JSON-serializable dict (agent __RESULT__)."""
    handler = _DISPATCH.get(name)
    if handler is None:
        return {"error": f"unknown tool '{name}'", "available": list(_DISPATCH)}
    try:
        return handler(get_view(rebuild=rebuild), params or {})
    except TypeError as exc:
        return {"error": f"bad parameters for '{name}': {exc}"}
