# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure formatting helpers for the agent steps block.

No bpy imports — kept dependency-free so it is unit-testable outside Blender
and reusable by both the slot processor and the dev-data mock.
"""
from collections.abc import Iterable

# Step kinds, in the enum order of chat_slot_types.MixieChatStepItem (the C++
# side reads that enum as an int index to pick the row glyph).
_VALID_KINDS = {"READ", "WRITE", "COMMAND", "SEARCH", "TOOL"}
_VALID_STATUS = {"PENDING", "RUNNING", "DONE", "FAILED"}


def format_steps_summary(kinds: Iterable[str], image_count: int = 0) -> str:
    """Build the collapsed header, e.g. "5 tools called".

    Deliberately NOT a per-kind breakdown ("Read 2 files · ran 1 command"):
    the agent's tools are Blender scripts, not files and shells, and the
    breakdown read as noise. The expanded rows carry the specifics. Images
    are NOT counted here: they have their own "Viewed N images" block under
    the steps (mixie_chat_steps.cc), with its own collapse state.

    Args:
        kinds: iterable of kind identifier strings (e.g. "READ", "COMMAND").
            Unknown identifiers are ignored; the count is what matters.
        image_count: accepted for compatibility; not shown.

    Returns:
        Summary string, or "" when there are no recognized kinds.
    """
    del image_count
    n = sum(1 for kind in kinds if kind in _VALID_KINDS)
    if n <= 0:
        return ""
    return f"{n} tool{'s' if n != 1 else ''} called"


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
    label = item_data.get("label") or ""
    # Inspection is an observation. execute_script otherwise lands on COMMAND
    # and the native row paints the filled act glyph — a highlighted button.
    if label == "Inspected scene":
        kind = "READ"
    return {
        "item_id": item_data.get("id") or "",
        "kind": kind,
        "label": label,
        "target": item_data.get("target") or "",
        "detail": item_data.get("detail") or "",
        "status": status,
    }


# Substring hints mapped to a step kind, checked in order against the tool
# name. First match wins; anything unmatched is a generic TOOL. The UI reduces
# kinds to two glyphs — ○ observed (READ/SEARCH) vs ■ acted (everything else)
# — so observation tools must be caught here or they render as actions:
# scene_overview, render_viewport, critique_scene, poll_generation, the
# operation-history queries.
_KIND_HINTS = [
    ("READ", ("read", "get", "list", "inspect", "fetch", "overview", "view",
              "critique", "describe", "poll", "status", "history")),
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


# Friendly, past-tense labels for the backend tools the user should be able
# to recognise. The RAW tool name is never shown: an unknown name falls back
# to the script classifier and then to the generic "Tool call" the result
# counts refine on finish. Keep this table small and human — it is UI copy.
_TOOL_LABELS = {
    "render_viewport": "Captured viewport",
    "render_viewport_final": "Rendered final image",
    "render_final": "Rendered final image",
    "render_multiview": "Captured views",
    "inspect_mesh_seams": "Inspected seams",
    "inspect_uv_map": "Inspected UV layout",
    "inspect_geometry": "Measured geometry",
    "inspect_spatial_constraints": "Checked placement",
    "correct_spatial_placement": "Corrected placement",
    "import_terrain_asset": "Imported asset",
    "list_terrain_assets": "Browsed asset library",
    "place_camera": "Placed camera",
    "scene_overview": "Inspected scene",
    "critique_scene": "Reviewed the scene",
}

# Tools whose row is a capture: the tile(s) under the row ARE the result, so
# the finish pass never overwrites the label with object counts.
CAPTURE_TOOLS = frozenset({
    "render_viewport", "render_viewport_final", "render_final",
    "render_multiview", "inspect_mesh_seams", "inspect_uv_map",
})


def humanize_tool_name(tool_name: str) -> str:
    """Row label for a backend tool name — a friendly phrase, never the name.

    "render_viewport" -> "Captured viewport". Names not in the table (the
    backend sends "unknown" when a script has no tool name and
    "execute_bpy_script" for generated scripts) fall back to the generic
    label so the script classifier / result counts label the row by what
    it actually did.
    """
    key = (tool_name or "").strip().lower()
    return _TOOL_LABELS.get(key, "Tool call")


def is_internal_step(tool_name: str, request_id: str = "") -> bool:
    """True for executions the steps block must not show.

    Contract with the backend (see execute_script_on_instance): a tool_name
    starting with "_" marks an internal execution — verification snapshots,
    generation-wait polling, lane plumbing, telemetry. Notification pushes
    (request_id "notification") are backend bookkeeping too, never user steps.
    """
    if (tool_name or "").startswith("_"):
        return True
    return (request_id or "") == "notification"


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
    # UV work is unmistakable too, and it edits with bmesh / ops.mesh (which
    # the geometry guard below would otherwise catch): the rows are how the
    # user follows a UV pass — "Marked seams" -> "Unwrapped mesh" -> "Packed
    # UV islands". Checked in pipeline order so a script doing all three is
    # labelled by its last stage.
    if "pack_islands" in s or "uv.pack" in s:
        return "Packed UV islands"
    if "uv.unwrap" in s or "uv.smart_project" in s or "unwrap(" in s:
        return "Unwrapped mesh"
    if "mark_seam" in s or "seam = true" in s or ".seam=true" in s:
        return "Marked seams"
    # If the script builds geometry, it's modeling — let the counts label it.
    creates_geometry = any(k in s for k in (
        "primitive_", "ops.mesh.", "meshes.new", "bmesh", "curves.new",
        "metaballs.new", "object.add(", "objects.new(",
    ))
    if not creates_geometry:
        # Read-only query/inspection FIRST: a script that only READS scene data
        # must never earn an action label — verification snapshots mention
        # material_slots/uv_layers/data.lights and were mislabelled "Applied
        # materials"/"Set up lighting" on every prompt. Many "Ran a tool" rows
        # are these ("Getting scene state…"). If a mutation slips through,
        # finish_step_on_bubble overrides this with the counts.
        mutates = any(k in s for k in (
            ".new(", "_add(", "delete", "remove(", ".append(", "ops.object",
            "ops.transform", "ops.import", "ops.export", "= bpy.data", "link("))
        reads = any(k in s for k in (
            "bpy.data", "context.scene", "context.view_layer", "context.object"))
        if reads and not mutates:
            return "Inspected scene"
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


_CAPTURE_LABELS = frozenset(_TOOL_LABELS[name] for name in CAPTURE_TOOLS)


def _refresh_summary(bubble) -> None:
    images = getattr(bubble, "image_items", None)
    image_count = sum(1 for img in (images or ()) if getattr(img, "step_id", "")) if images is not None else 0
    bubble.steps_summary = format_steps_summary(
        (row.kind for row in bubble.step_items), image_count
    )


# Mirrors SLOT_MAX_IMAGE_ITEMS in mixie_chat_ui_types.hh: the native layout
# copies at most this many image items per bubble, oldest first, so anything
# past it would be invisible. Drop the OLDEST step tiles to stay under it.
MAX_STEP_IMAGES_PER_BUBBLE = 32


def attach_step_images(bubble, request_id: str, records: list) -> int:
    """Add image tiles for the step `request_id` to the bubble's image_items.

    `records` are {local_path, width, height, caption} dicts (capture_store).
    Tiles are tagged with `step_id` (provenance, and what `images_to_fetch`
    keys on); the native side draws every tagged tile of the bubble in ONE
    "Viewed N images" block under the steps, opened for the bubble that most
    recently received a tile (see steps_recorder). Backend-owned gallery
    images (no step_id) are left alone. Returns the number of tiles added.
    """
    if not records:
        return 0
    items = bubble.image_items
    # One tile per file per bubble. A re-served capture (the backend hands back
    # the same image refs for an identical render of an unchanged scene) and a
    # download of a capture already saved locally must not show the same
    # picture twice.
    present = {_tile_key(img.local_path) for img in items if img.step_id and img.local_path}
    added = 0
    for rec in records:
        path = rec.get("local_path") or ""
        key = _tile_key(path)
        if not path or key in present:
            continue
        present.add(key)
        img = items.add()
        img.step_id = request_id or ""
        img.local_path = path
        img.url = ""
        img.thumbnail_url = ""
        img.alt = rec.get("caption") or ""
        img.caption = rec.get("caption") or ""
        img.width = float(rec.get("width") or 0)
        img.height = float(rec.get("height") or 0)
        added += 1
    # Enforce the native cap on step tiles, oldest first.
    step_indices = [i for i, img in enumerate(items) if img.step_id]
    overflow = len(step_indices) - MAX_STEP_IMAGES_PER_BUBBLE
    for idx in reversed(step_indices[:max(overflow, 0)]):
        items.remove(idx)
    if added:
        if hasattr(bubble, "images_collapsed"):
            bubble.images_collapsed = False
        _refresh_summary(bubble)
    return added


def _tile_key(path: str) -> str:
    """Identity of a tile file: its basename without extension. A backend
    image is saved as ``<image id>.<ext>``, so the same id is one tile."""
    base = (path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def bubble_has_image_id(bubble, image_id: str) -> bool:
    return any(img.step_id and _tile_key(img.local_path) == image_id for img in bubble.image_items)


def step_image_count(bubble, request_id: str) -> int:
    return sum(1 for img in bubble.image_items if img.step_id == request_id)


# Labels that say nothing about WHAT happened — a more specific one (from the
# script classifier, the result counts, or the backend) always replaces them.
_GENERIC_LABELS = frozenset({"", "Tool call", "Ran a script"})


def _find_row_by_call_id(bubble, call_id: str):
    if not call_id:
        return None
    for i in range(len(bubble.step_items) - 1, -1, -1):
        row = bubble.step_items[i]
        if getattr(row, "call_id", "") == call_id:
            return row
    return None


def begin_step_on_bubble(bubble, request_id: str, tool_name: str, script: str = "",
                         call_id: str = "") -> None:
    """Start (or adopt) the step row for a tool call whose script just began.

    Duck-typed like apply_steps_to_bubble — used by the live recorder when a
    `blender.execute_script` request begins on the main thread. The label
    prefers a friendly name for a known backend tool, then the script-inferred
    action, then a generic placeholder the result counts will refine on finish.

    `call_id` is the backend tool-call id the RPC carried. When the backend's
    `activity` payload for that call already opened a row, this ADOPTS it —
    re-keyed to `request_id` so the result lands on it — instead of adding a
    second row for the same call.
    """
    row = _find_row_by_call_id(bubble, call_id)
    adopted = row is not None
    if row is None:
        row = bubble.step_items.add()
    row.item_id = request_id or ""
    row.call_id = call_id or ""
    kind = infer_step_kind(tool_name)
    label = humanize_tool_name(tool_name)
    if label == "Tool call":
        classified = classify_script_action(script)
        if classified:
            label = classified
    if label == "Inspected scene":
        kind = "READ"
    # An adopted row keeps a specific backend label over our generic guess.
    if adopted and label in _GENERIC_LABELS and getattr(row, "label", "") not in _GENERIC_LABELS:
        label = row.label
    else:
        row.kind = kind
    row.label = label
    row.target = ""
    row.detail = ""
    row.status = "RUNNING"
    _refresh_summary(bubble)


_ACTIVITY_STATUS = {"running": "RUNNING", "done": "DONE", "failed": "FAILED"}


def apply_activity_to_bubble(bubble, activity: dict):
    """Merge one backend `activity` payload into the bubble's step rows.

    Keyed on `call_id`: the row a script RPC opened for the same call (see
    begin_step_on_bubble) is updated in place, otherwise a new row is added
    with `item_id` = `call_id` (tools that never run a script: view_image,
    delegate_tasks, load_skill, worker-side tools …).

    Returns the row, or None when the payload is unusable. The caller decides
    what to do with `activity["images"]` (see images_to_fetch).
    """
    call_id = str(activity.get("call_id") or "")
    if not call_id:
        return None
    row = _find_row_by_call_id(bubble, call_id)
    created = row is None
    if created:
        row = bubble.step_items.add()
        row.item_id = call_id
        row.call_id = call_id
        row.kind = "READ" if activity.get("kind") == "read" else "TOOL"
        row.label = ""
        row.target = ""
        row.detail = ""
        row.status = "PENDING"
        row.expanded = False

    # The backend names the row it opened (and refines it on `done`: "Viewed
    # an image" -> "Viewed 2 images"); a row the script path opened keeps its
    # own (classifier / result-count) label unless that one is generic.
    backend_owned = created or getattr(row, "item_id", "") == call_id
    label = str(activity.get("label") or "")
    if label and (backend_owned or getattr(row, "label", "") in _GENERIC_LABELS):
        row.label = label

    status = _ACTIVITY_STATUS.get(str(activity.get("status") or "").lower())
    if status == "RUNNING":
        # Never regress a row the script path already finished.
        if row.status not in ("DONE", "FAILED"):
            row.status = "RUNNING"
    elif status == "DONE":
        if row.status != "FAILED":
            row.status = "DONE"
    elif status == "FAILED":
        row.status = "FAILED"
        row.label = "Failed"
        row.target = ""
        row.detail = str(activity.get("error") or "")[:500]
    _refresh_summary(bubble)
    return row


def images_to_fetch(bubble, row, activity: dict) -> list:
    """The backend image refs of `activity` that this bubble has no tile for.

    A capture the client made itself is already a tile under the row (the
    bytes came through its own script reply), so a row that already holds
    tiles takes nothing from the backend — the same pixels under a different
    (backend-side) id would only duplicate it. Rows with no tiles (view_image,
    a worker's capture that reached us only by reference) fetch every ref.
    Returns [{"id", "label"}].
    """
    refs = [r for r in (activity.get("images") or [])
            if isinstance(r, dict) and r.get("id")]
    if not refs or row is None:
        return []
    if str(activity.get("tool") or "") == "view_image":
        # Reopens images that already exist: earlier captures (already tiles)
        # or the user's references. Never a new picture.
        return []
    if step_image_count(bubble, row.item_id) > 0:
        return []
    # An id the bubble already holds (a re-served capture, a second view of
    # the same image) is not fetched or attached again.
    return [{"id": str(r["id"]), "label": str(r.get("label") or "")}
            for r in refs if not bubble_has_image_id(bubble, str(r["id"]))]


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
            # — fall back to the accurate count label. The row is no longer an
            # observation, so drop the READ kind that kept it looking like a
            # label rather than a command.
            if label == "Inspected scene" and (nc or nm or nd):
                label = "Tool call"
                row.kind = "TOOL"
            elif label == "Inspected scene":
                row.kind = "READ"
            # Keep a meaningful label (real tool name or script-inferred action,
            # set at begin) and show the object counts beside it; only synthesize
            # a label from the counts when the row is still the generic
            # "Tool call".
            if label in _CAPTURE_LABELS:
                # A capture's result is the tile(s) drawn under the row.
                row.target = ""
            elif label and label != "Tool call":
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
    if explicit:
        bubble.steps_summary = explicit
    else:
        _refresh_summary(bubble)
