# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing read surface for the operation history.

run_tool(scene, name, params) returns a JSON-serializable dict (the agent's __RESULT__
convention). TOOL_SPECS is ready to register in the backend tool registry. Per-session by
construction (resolved from the scene's persistent mixar_op_history_id). All output is capped.
"""

from ..constants import KIND_OPERATION, MAX_LIST_RESULTS
from . import store
from .scene_key import get_scene_history_id

TOOL_SPECS = [
    {"name": "operation_history_summary",
     "description": "Counts of recorded operations by source/kind/category, time range, and "
                    "the most recent operation labels. Call first to orient.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "list_operations",
     "description": "Recent operations (newest last), capped. By default returns only mutating "
                    "operations; set include_queries=true to also include the agent's read-only "
                    "tool calls. Filter by source ('AGENT'|'USER'), category, or since_seq.",
     "parameters": {"type": "object", "properties": {
         "limit": {"type": "integer"}, "include_queries": {"type": "boolean"},
         "source": {"type": "string"}, "category": {"type": "string"},
         "since_seq": {"type": "integer"}}}},
    {"name": "get_operation",
     "description": "One operation's full record including the saved script content (for agent "
                    "executions). Identify it by seq or id.",
     "parameters": {"type": "object", "properties": {
         "seq": {"type": "integer"}, "op_id": {"type": "string"}}}},
    {"name": "operations_for_object",
     "description": "All recorded operations that created/modified/deleted or affected a given object.",
     "parameters": {"type": "object", "properties": {"object_name": {"type": "string"}},
                    "required": ["object_name"]}},
]


def _session_id(scene) -> str:
    # History is keyed by the scene's persistent id (not the chat session), so the agent
    # reads the same log the capture service writes — including manual edits made before
    # any chat session existed.
    return get_scene_history_id(scene)


def _summary(scene):
    rows = store.read_operations(_session_id(scene), limit=0)
    by_source, by_kind, by_cat = {}, {}, {}
    for r in rows:
        by_source[r.get("source")] = by_source.get(r.get("source"), 0) + 1
        by_kind[r.get("kind")] = by_kind.get(r.get("kind"), 0) + 1
        by_cat[r.get("category")] = by_cat.get(r.get("category"), 0) + 1
    ts = [r.get("ts", 0) for r in rows]
    return {"total": len(rows), "by_source": by_source, "by_kind": by_kind,
            "by_category": by_cat, "first_ts": min(ts) if ts else None,
            "last_ts": max(ts) if ts else None,
            "recent_labels": [r.get("label", "") for r in rows[-10:]]}


def _list(scene, limit=MAX_LIST_RESULTS, include_queries=False, source=None,
          category=None, since_seq=None):
    kind = None if include_queries else KIND_OPERATION
    try:
        limit = min(int(limit), MAX_LIST_RESULTS)
    except Exception:
        limit = MAX_LIST_RESULTS
    rows = store.read_operations(_session_id(scene), limit=limit, source=source,
                                 kind=kind, category=category, since_seq=since_seq)
    return {"operations": rows, "count": len(rows)}


def _get(scene, seq=None, op_id=None):
    sid = _session_id(scene)
    for r in store.read_operations(sid, limit=0):
        if (seq is not None and r.get("seq") == seq) or (op_id is not None and r.get("id") == op_id):
            out = dict(r)
            out["script"] = store.read_script(sid, seq=r.get("seq"), op_id=r.get("id"))
            return out
    return {"error": "operation not found"}


def _for_object(scene, object_name=None):
    if not object_name:
        return {"error": "object_name required"}
    rows = store.read_operations(_session_id(scene), limit=MAX_LIST_RESULTS, object_name=object_name)
    return {"object": object_name, "operations": rows, "count": len(rows)}


def run_tool(scene, name, params=None):
    params = params or {}
    handler = {
        "operation_history_summary": lambda: _summary(scene),
        "list_operations": lambda: _list(scene, **params),
        "get_operation": lambda: _get(scene, **params),
        "operations_for_object": lambda: _for_object(scene, **params),
    }.get(name)
    if handler is None:
        return {"error": "unknown tool '{}'".format(name),
                "available": [t["name"] for t in TOOL_SPECS]}
    try:
        return handler()
    except TypeError as exc:
        return {"error": "bad parameters for '{}': {}".format(name, exc)}
