# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure formatting helpers for the agent steps block.

No bpy imports — kept dependency-free so it is unit-testable outside Blender
and reusable by both the slot processor and the dev-data mock.
"""
from collections import Counter
from collections.abc import Iterable

# Kind -> (singular phrase, plural phrase). Declaration order here defines the
# left-to-right order of the rendered summary. Must match the kind enum order
# in chat_slot_types.MixieChatStepItem. First words are lowercase; the joined
# summary's leading character is capitalized in format_steps_summary so a
# standalone non-READ summary (e.g. "wrote 1 file") still reads correctly.
_KIND_PHRASES = [
    ("READ", "read {n} file", "read {n} files"),
    ("WRITE", "wrote {n} file", "wrote {n} files"),
    ("COMMAND", "ran {n} command", "ran {n} commands"),
    ("SEARCH", "ran {n} search", "ran {n} searches"),
    ("TOOL", "used {n} tool", "used {n} tools"),
]

_VALID_KINDS = {entry[0] for entry in _KIND_PHRASES}
_VALID_STATUS = {"PENDING", "RUNNING", "DONE", "FAILED"}


def format_steps_summary(kinds: Iterable[str]) -> str:
    """Build a human summary like "Read 2 files · ran 1 command".

    Args:
        kinds: iterable of kind identifier strings (e.g. "READ", "COMMAND").
            Unknown identifiers are ignored.

    Returns:
        Summary string, or "" when there are no recognized kinds.
    """
    counts = Counter(kinds)
    parts = []
    for kind, singular, plural in _KIND_PHRASES:
        n = counts.get(kind, 0)
        if n <= 0:
            continue
        phrase = (singular if n == 1 else plural).format(n=n)
        parts.append(phrase)
    result = " · ".join(parts)
    return result[:1].upper() + result[1:] if result else ""


def normalize_step_item(item_data: dict) -> dict:
    """Normalize one raw step dict into validated, enum-ready fields.

    Pure (no bpy) so it is unit-testable and shared by _apply_steps_slot and
    the dev-data mock. Coerces kind/status to valid uppercase identifiers
    (defaulting kind->TOOL, status->DONE) and replaces None/missing strings
    with "".

    Returns a dict with keys: item_id, kind, label, target, detail, status.
    """
    kind = (item_data.get("kind") or "tool").upper()
    if kind not in _VALID_KINDS:
        kind = "TOOL"
    status = (item_data.get("status") or "done").upper()
    if status not in _VALID_STATUS:
        status = "DONE"
    return {
        "item_id": item_data.get("id") or "",
        "kind": kind,
        "label": item_data.get("label") or "",
        "target": item_data.get("target") or "",
        "detail": item_data.get("detail") or "",
        "status": status,
    }


# Substring hints mapped to a step kind, checked in order against the tool
# name. First match wins; anything unmatched is a generic TOOL.
_KIND_HINTS = [
    ("READ", ("read", "get", "list", "inspect", "fetch")),
    ("SEARCH", ("search", "find", "query")),
    ("WRITE", ("write", "save", "export", "import")),
    ("COMMAND", ("execute", "run", "command", "script", "shell")),
]


def infer_step_kind(tool_name: str) -> str:
    """Infer a step kind ("READ"/"WRITE"/"COMMAND"/"SEARCH"/"TOOL") from a
    backend tool name like "get_object_list" or "execute_script"."""
    lowered = (tool_name or "").lower()
    for kind, hints in _KIND_HINTS:
        if any(hint in lowered for hint in hints):
            return kind
    return "TOOL"


def humanize_tool_name(tool_name: str) -> str:
    """Turn a snake_case tool name into a row label: "create_cube" -> "Create cube".

    The backend sends "unknown" when a script has no tool name — fall back to
    a neutral label rather than showing literal "Unknown" in the UI.
    """
    words = (tool_name or "").replace("_", " ").strip()
    if not words or words.lower() == "unknown":
        return "Tool call"
    return words[:1].upper() + words[1:]


def classify_script_action(script: str) -> str:
    """Infer the action a Blender script performs, for a precise row label when
    the backend sends no tool name.

    The agent executes generated Python, so the script body IS the action. This
    is a conservative keyword classifier — it only labels strong, distinctive
    NON-geometry actions (render / materials / camera / lighting / modifier).
    Scripts that create geometry return "" so the result counts label them
    ("Created N objects"), which avoids mislabelling a modeling script that
    happens to also assign a material.
    """
    s = (script or "").lower()
    if not s:
        return ""
    # Rendering is unmistakable and never modeling.
    if "ops.render.render" in s or "render.render(" in s or "render_still" in s:
        return "Rendered scene"
    # If the script builds geometry, it's modeling — let the counts label it.
    creates_geometry = any(k in s for k in (
        "primitive_", "ops.mesh.", "meshes.new", "bmesh", "curves.new",
        "metaballs.new", "object.add(", "objects.new(",
    ))
    if not creates_geometry:
        if any(k in s for k in (
                "data.materials", "material_slots", "node_tree", "principled",
                "data.images", "image_texture", ".uv_layers", "bsdf")):
            return "Applied materials"
        if any(k in s for k in (
                "data.cameras", "cameras.new", "camera_add", "scene.camera",
                ".lens", "track_to")):
            return "Set up camera"
        if any(k in s for k in (
                "data.lights", "lights.new", "light_add", "world.node_tree",
                "environment_texture", "type='sun'", "type='area'",
                "type='point'", "type='spot'")):
            return "Set up lighting"
        if "modifier_add" in s or "modifiers.new" in s:
            return "Added modifier"
        # Read-only query/inspection: reads scene data with no mutation. Many
        # "Ran a tool" rows are these ("Getting scene state…"). If a mutation
        # slips through, finish_step_on_bubble overrides this with the counts.
        mutates = any(k in s for k in (
            ".new(", "_add(", "delete", "remove(", ".append(", "ops.object",
            "ops.transform", "ops.import", "ops.export", "= bpy.data", "link("))
        reads = any(k in s for k in (
            "bpy.data", "context.scene", "context.view_layer", "context.object"))
        if reads and not mutates:
            return "Inspected scene"
    return ""




def _summarize_object_counts(created: int, modified: int, deleted: int) -> str:
    """A clean target summary like "12 created" / "3 created · 1 deleted".

    Replaces the old list of internal Blender object names so a tool row reads
    as an action result, not a dump of mesh names.
    """
    parts = []
    if created:
        parts.append(f"{created} created")
    if modified:
        parts.append(f"{modified} modified")
    if deleted:
        parts.append(f"{deleted} deleted")
    return " · ".join(parts)


def _object_names_detail(created: list, modified: list, deleted: list) -> str:
    """Expandable detail body: the object names grouped by action.

    Shown only when a tool row is expanded. Capped so a 200-object build does
    not produce an enormous block.
    """
    cap = 40

    def fmt(names: list, verb: str) -> str:
        if not names:
            return ""
        shown = names[:cap]
        line = f"{verb}: " + ", ".join(shown)
        if len(names) > cap:
            line += f" … (+{len(names) - cap} more)"
        return line

    parts = [p for p in (fmt(created, "Created"),
                         fmt(modified, "Modified"),
                         fmt(deleted, "Deleted")) if p]
    return "\n".join(parts)


def _result_label(created: int, modified: int, deleted: int):
    """Describe a finished tool by WHAT IT ACTUALLY DID, from the result counts.

    Returns (label, target). Self-consistent — a row never claims an action it
    didn't take (unlike labelling by the unrelated loader phase, where a
    "Rendering viewport" row could show created objects):
      - one operation  -> "Created 54 objects", target=""
      - mixed          -> "Updated scene", target="8 created · 1 modified · …"
      - nothing        -> "Ran a tool", target=""
    """
    active = [(n, v) for n, v in ((created, "Created"),
                                  (modified, "Modified"),
                                  (deleted, "Deleted")) if n]
    if not active:
        return "Ran a tool", ""
    if len(active) == 1:
        n, verb = active[0]
        return f"{verb} {n} object{'s' if n != 1 else ''}", ""
    return "Updated scene", _summarize_object_counts(created, modified, deleted)


def _refresh_summary(bubble) -> None:
    bubble.steps_summary = format_steps_summary(
        row.kind for row in bubble.step_items
    )


def begin_step_on_bubble(bubble, request_id: str, tool_name: str, script: str = "") -> None:
    """Append a RUNNING step row for a tool call that just started executing.

    Duck-typed like apply_steps_to_bubble — used by the live recorder when a
    `blender.execute_script` request begins on the main thread. The label
    prefers a real backend tool name, then the script-inferred action, then a
    generic placeholder the result counts will refine on finish.
    """
    was_empty = len(bubble.step_items) == 0
    row = bubble.step_items.add()
    row.item_id = request_id or ""
    row.kind = infer_step_kind(tool_name)
    label = humanize_tool_name(tool_name)
    if label == "Tool call":
        classified = classify_script_action(script)
        if classified:
            label = classified
    row.label = label
    row.target = ""
    row.detail = ""
    row.status = "RUNNING"
    if was_empty and hasattr(bubble, "steps_collapsed"):
        # Expanded by default so the per-tool notes appear progressively as the
        # agent works; the user can collapse via the header.
        bubble.steps_collapsed = False
    _refresh_summary(bubble)


def finish_step_on_bubble(bubble, request_id: str, result: dict) -> bool:
    """Complete the step row for `request_id` from an execution result dict.

    Fills status (DONE/FAILED), target (created/modified/deleted objects) and
    detail (script output, or the error on failure).

    Returns:
        True when a matching row was updated, False if no row has request_id.
    """
    # Scan newest-first: request ids are not globally unique (notification
    # scripts all share "notification"), so the most recent row wins.
    for i in range(len(bubble.step_items) - 1, -1, -1):
        row = bubble.step_items[i]
        if row.item_id != request_id:
            continue
        success = bool(result.get("success"))
        row.status = "DONE" if success else "FAILED"
        created = list(result.get("created_objects") or [])
        modified = list(result.get("modified_objects") or [])
        deleted = list(result.get("deleted_objects") or [])
        if success:
            nc, nm, nd = len(created), len(modified), len(deleted)
            label = getattr(row, "label", "")
            # An "Inspected scene" guess that actually changed objects was wrong
            # — fall back to the accurate count label.
            if label == "Inspected scene" and (nc or nm or nd):
                label = "Tool call"
            # Keep a meaningful label (real tool name or script-inferred action,
            # set at begin) and show the object counts beside it; only synthesize
            # a label from the counts when the row is still the generic
            # "Tool call".
            if label and label != "Tool call":
                row.target = _summarize_object_counts(nc, nm, nd)
            else:
                row.label, row.target = _result_label(nc, nm, nd)
            # Expandable detail: the actual object NAMES. NEVER the raw script
            # stdout — that is the "Blender create Mesh node Cube.099" log wall.
            row.detail = _object_names_detail(created, modified, deleted)
        else:
            row.label = "Failed"
            row.target = ""
            row.detail = (result.get("error") or "")[:500]
        return True
    return False


def apply_steps_to_bubble(bubble, steps_data: dict) -> None:
    """Full-replace a bubble's step rows + summary from a steps event dict.

    Pure of bpy — operates on any object exposing a `step_items` collection
    (with `.clear()` / `.add()` returning a settable item) and a writable
    `steps_summary`. Shared by the slot processor (real data) and tests.

    Args:
        bubble: duck-typed message with `step_items` and `steps_summary`.
        steps_data: dict with optional "summary" (str) and "items" (list of
            dicts: id, kind, label, target, detail, status).
    """
    items = steps_data.get("items") or []
    bubble.step_items.clear()

    applied_kinds = []
    for item_data in items:
        norm = normalize_step_item(item_data)
        row = bubble.step_items.add()
        row.item_id = norm["item_id"]
        row.kind = norm["kind"]
        row.label = norm["label"]
        row.target = norm["target"]
        row.detail = norm["detail"]
        row.status = norm["status"]
        applied_kinds.append(norm["kind"])

    explicit = steps_data.get("summary") or ""
    bubble.steps_summary = explicit if explicit else format_steps_summary(applied_kinds)
