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


def clean_step_detail(output: str) -> str:
    """Strip protocol noise from script output before showing it as detail.

    Drops `__RESULT__{...}` lines (the script->backend result channel) and
    trailing whitespace; the remaining human-readable output is kept.
    """
    lines = [
        line for line in (output or "").splitlines()
        if not line.lstrip().startswith("__RESULT__")
    ]
    return "\n".join(lines).strip()


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


def _refresh_summary(bubble) -> None:
    bubble.steps_summary = format_steps_summary(
        row.kind for row in bubble.step_items
    )


def begin_step_on_bubble(bubble, request_id: str, tool_name: str) -> None:
    """Append a RUNNING step row for a tool call that just started executing.

    Duck-typed like apply_steps_to_bubble — used by the live recorder when a
    `blender.execute_script` request begins on the main thread.
    """
    # New tool block starts collapsed — a clean "▸ Used N tools" one-liner the
    # user can expand, instead of a wall of rows + logs (Cowork-style).
    was_empty = len(bubble.step_items) == 0
    row = bubble.step_items.add()
    row.item_id = request_id or ""
    row.kind = infer_step_kind(tool_name)
    row.label = humanize_tool_name(tool_name)
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
        # Collapsed row: a clean object COUNT (not internal mesh names).
        row.target = _summarize_object_counts(len(created), len(modified), len(deleted))
        # Expandable detail: the actual object NAMES (every row is independently
        # collapsible). NEVER the raw script stdout — that is the
        # "Blender create Mesh node Cube.099" log wall.
        if success:
            row.detail = _object_names_detail(created, modified, deleted)
        else:
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
