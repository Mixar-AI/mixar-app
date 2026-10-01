# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure steps-summary formatter (no bpy required)."""
import importlib.util
import os

# Load steps_format.py directly by path so the test needs no package import
# machinery / bpy. Mirrors how other pure-logic tests isolate a single module.
_HERE = os.path.dirname(__file__)
_PATH = os.path.join(
    _HERE, "..", "space_mixie_chat", "core", "steps_format.py"
)
_spec = importlib.util.spec_from_file_location("steps_format", _PATH)
steps_format = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(steps_format)
format_steps_summary = steps_format.format_steps_summary


def test_empty_returns_empty_string():
    assert format_steps_summary([]) == ""


def test_single_tool():
    assert format_steps_summary(["READ"]) == "1 tool called"


def test_counts_every_kind_without_a_breakdown():
    """The header is a plain count — never "Read 2 files · ran 1 command":
    the agent's tools are Blender scripts, and the per-kind phrasing read as
    noise. The rows carry the specifics."""
    assert format_steps_summary(["READ", "COMMAND"]) == "2 tools called"
    assert format_steps_summary(["READ", "WRITE", "COMMAND", "SEARCH", "TOOL"]) == "5 tools called"


def test_unknown_kind_ignored():
    assert format_steps_summary(["READ", "NOPE"]) == "1 tool called"


def test_summary_never_counts_images():
    """Images have their own "Viewed N images" block; the header stays a tool count."""
    assert format_steps_summary(["READ"], image_count=1) == "1 tool called"
    assert format_steps_summary(["READ", "TOOL"], image_count=3) == "2 tools called"
    assert format_steps_summary([], image_count=3) == ""


# --- normalize_step_item (pure, no bpy) ----------------------------------

def test_normalize_maps_kind_and_status_uppercase():
    out = steps_format.normalize_step_item(
        {"id": "s1", "kind": "read", "label": "Read", "target": "a.py",
         "detail": "x", "status": "done"})
    assert out == {"item_id": "s1", "kind": "READ", "label": "Read",
                   "target": "a.py", "detail": "x", "status": "DONE"}


def test_normalize_defaults_invalid_kind_to_tool_and_status_to_done():
    out = steps_format.normalize_step_item(
        {"id": "", "kind": "bogus", "status": "weird"})
    assert out["kind"] == "TOOL"
    assert out["status"] == "DONE"


def test_normalize_handles_missing_and_none_fields():
    out = steps_format.normalize_step_item({"kind": "command"})
    assert out["item_id"] == ""
    assert out["label"] == ""
    assert out["target"] == ""
    assert out["detail"] == ""
    assert out["kind"] == "COMMAND"


def test_normalize_valid_non_default_status_preserved():
    out = steps_format.normalize_step_item({"kind": "read", "status": "running"})
    assert out["status"] == "RUNNING"


# --- apply_steps_to_bubble (duck-typed bubble, no bpy) -------------------

class _FakeStep:
    """Bare object with freely-settable attributes (like a PropertyGroup item)."""
    pass


class _FakeColl(list):
    def add(self):
        item = _FakeStep()
        self.append(item)
        return item
    # list.clear() already matches Blender collection .clear()


class _FakeImageColl(list):
    def add(self):
        item = _FakeStep()
        item.step_id = ""
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


class _FakeBubble:
    def __init__(self):
        self.step_items = _FakeColl()
        self.image_items = _FakeImageColl()
        self.steps_summary = ""
        self.images_collapsed = True


def test_apply_steps_replaces_items_and_computes_summary():
    bubble = _FakeBubble()
    bubble.step_items.add()  # pre-existing item that must be cleared

    steps_format.apply_steps_to_bubble(bubble, {
        "summary": "",  # empty -> compute from kinds
        "items": [
            {"id": "s1", "kind": "read", "label": "Read", "target": "a.py",
             "detail": "", "status": "done"},
            {"id": "s2", "kind": "command", "label": "Ran", "target": "pytest",
             "detail": "3 passed", "status": "done"},
        ],
    })

    assert len(bubble.step_items) == 2
    assert bubble.step_items[0].item_id == "s1"
    assert bubble.step_items[0].kind == "READ"
    assert bubble.step_items[1].kind == "COMMAND"
    assert bubble.step_items[1].detail == "3 passed"
    assert bubble.steps_summary == "2 tools called"


def test_apply_steps_uses_explicit_summary_when_given():
    bubble = _FakeBubble()
    steps_format.apply_steps_to_bubble(bubble, {
        "summary": "Custom summary",
        "items": [{"id": "s1", "kind": "tool", "label": "X", "status": "running"}],
    })
    assert bubble.steps_summary == "Custom summary"
    assert bubble.step_items[0].kind == "TOOL"
    assert bubble.step_items[0].status == "RUNNING"


# --- live step recording from tool execution (duck-typed, no bpy) ---------

def test_infer_step_kind_from_tool_name():
    assert steps_format.infer_step_kind("get_object_list") == "READ"
    assert steps_format.infer_step_kind("read_scene_info") == "READ"
    assert steps_format.infer_step_kind("search_assets") == "SEARCH"
    assert steps_format.infer_step_kind("export_gltf") == "WRITE"
    assert steps_format.infer_step_kind("execute_script") == "COMMAND"
    assert steps_format.infer_step_kind("create_cube") == "TOOL"
    assert steps_format.infer_step_kind("") == "TOOL"


def test_observation_tools_classify_as_read():
    """The UI renders READ/SEARCH as ○ observed vs ■ acted — observation tools
    must not fall through to the act glyph."""
    for name in ("scene_overview", "render_viewport", "critique_scene",
                 "poll_generation", "operation_history_summary",
                 "describe_object", "get_all_queue_status"):
        assert steps_format.infer_step_kind(name) in ("READ", "SEARCH"), name


def test_begin_step_adds_running_row_and_updates_summary():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "req-1", "create_cube")

    assert len(bubble.step_items) == 1
    row = bubble.step_items[0]
    assert row.item_id == "req-1"
    assert row.kind == "TOOL"
    # An unknown tool name is never shown raw — the counts label it on finish.
    assert row.label == "Tool call"
    assert row.status == "RUNNING"
    assert row.detail == ""
    assert bubble.steps_summary == "1 tool called"


def test_finish_step_marks_done_with_count_and_no_stdout():
    """A finished step shows a clean object COUNT as target and never surfaces
    raw script stdout (the "Blender create Mesh node" log wall) as detail."""
    bubble = _FakeBubble()
    # No tool name + no recognizable script → label synthesized from counts.
    steps_format.begin_step_on_bubble(bubble, "req-1", "unknown")
    found = steps_format.finish_step_on_bubble(bubble, "req-1", {
        "success": True,
        "output": "Blender create Mesh node Cube.099\nBlender create Mesh node Cube.100",
        "created_objects": ["Cube"],
        "modified_objects": ["Material.001"],
    })
    assert found is True
    row = bubble.step_items[0]
    assert row.status == "DONE"
    # Mixed op → labelled "Updated scene" with the breakdown as target.
    assert row.label == "Updated scene"
    assert row.target == "1 created · 1 modified"
    # Detail holds the object NAMES (expandable), never the stdout log wall.
    assert "Cube" in row.detail and "Material.001" in row.detail
    assert "Blender create Mesh node" not in row.detail


def test_finish_step_failure_sets_failed_and_error_detail():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "req-2", "execute_script")
    found = steps_format.finish_step_on_bubble(bubble, "req-2", {
        "success": False,
        "error": "NameError: bpyy",
    })
    assert found is True
    row = bubble.step_items[0]
    assert row.status == "FAILED"
    assert row.detail == "NameError: bpyy"


def test_finish_step_unknown_request_returns_false():
    bubble = _FakeBubble()
    assert steps_format.finish_step_on_bubble(bubble, "missing", {"success": True}) is False


def test_finish_step_updates_most_recent_matching_row():
    # Notification scripts all share request_id "notification" — the most
    # recently started row must be the one completed.
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "notification", "first_tool")
    steps_format.finish_step_on_bubble(bubble, "notification", {"success": True})
    steps_format.begin_step_on_bubble(bubble, "notification", "second_tool")
    steps_format.finish_step_on_bubble(bubble, "notification", {"success": False, "error": "boom"})

    assert bubble.step_items[0].status == "DONE"
    assert bubble.step_items[1].status == "FAILED"
    assert bubble.step_items[1].detail == "boom"


def test_humanize_unknown_tool_name_falls_back():
    assert steps_format.humanize_tool_name("unknown") == "Tool call"
    assert steps_format.humanize_tool_name("") == "Tool call"
    # The raw snake_case name is never the label.
    assert steps_format.humanize_tool_name("inspect_spatial_constraints") == "Checked placement"
    assert steps_format.humanize_tool_name("some_new_tool") == "Tool call"


def test_known_tools_get_friendly_labels():
    h = steps_format.humanize_tool_name
    assert h("render_viewport") == "Captured viewport"
    assert h("inspect_mesh_seams") == "Inspected seams"
    assert h("inspect_geometry") == "Measured geometry"
    assert h("RENDER_VIEWPORT") == "Captured viewport"


def test_capture_row_keeps_label_and_no_count_target():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "r1", "render_viewport")
    assert bubble.step_items[0].kind == "READ"
    steps_format.finish_step_on_bubble(
        bubble, "r1", {"success": True, "modified_objects": ["Camera"]})
    assert bubble.step_items[0].label == "Captured viewport"
    assert bubble.step_items[0].target == ""


def test_attach_step_images_tags_tiles_and_updates_summary():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "r1", "render_viewport")
    added = steps_format.attach_step_images(bubble, "r1", [
        {"local_path": "/tmp/a.jpg", "width": 1024, "height": 768, "caption": "persp"},
        {"local_path": "", "width": 0, "height": 0, "caption": "skipped"},
    ])
    assert added == 1
    tile = bubble.image_items[0]
    assert tile.step_id == "r1"
    assert tile.local_path == "/tmp/a.jpg"
    assert tile.width == 1024.0 and tile.height == 768.0
    assert tile.caption == "persp"
    assert steps_format.step_image_count(bubble, "r1") == 1
    assert bubble.steps_summary == "1 tool called"
    assert bubble.images_collapsed is False  # a new tile opens the gallery


def test_attach_step_images_drops_oldest_past_cap_and_keeps_gallery():
    bubble = _FakeBubble()
    gallery = bubble.image_items.add()  # backend-owned, no step_id
    gallery.local_path = "/tmp/gallery.png"
    cap = steps_format.MAX_STEP_IMAGES_PER_BUBBLE
    for n in range(cap + 3):
        steps_format.attach_step_images(
            bubble, f"r{n}", [{"local_path": f"/tmp/{n}.jpg"}])
    tiles = [img for img in bubble.image_items if img.step_id]
    assert len(tiles) == cap
    assert tiles[0].step_id == "r3"          # the three oldest were dropped
    assert tiles[-1].step_id == f"r{cap + 2}"
    assert bubble.image_items[0].local_path == "/tmp/gallery.png"


def test_classify_uv_scripts():
    c = steps_format.classify_script_action
    assert c("for e in bm.edges: e.seam = True\nbpy.ops.mesh.mark_seam()") == "Marked seams"
    assert c("bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.02)") == "Unwrapped mesh"
    assert c("bpy.ops.uv.pack_islands(margin=0.01)") == "Packed UV islands"


def test_finish_step_detail_is_object_names_not_stdout():
    """Detail holds the object names (expandable), never raw script stdout."""
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "r1", "unknown")
    steps_format.finish_step_on_bubble(bubble, "r1", {
        "success": True,
        "output": 'Creating pyramid...\n__RESULT__{"x": 1}\nDone.',
        "created_objects": ["Pyramid"],
    })
    row = bubble.step_items[0]
    assert row.label == "Created 1 object"
    assert row.detail == "Created: Pyramid"
    assert "__RESULT__" not in row.detail and "Creating pyramid" not in row.detail


def test_classify_script_action():
    c = steps_format.classify_script_action
    assert c("result = bpy.ops.render.render(write_still=True)") == "Rendered scene"
    assert c("mat = bpy.data.materials.new('M'); mat.node_tree") == "Applied materials"
    assert c("cam = bpy.data.cameras.new('Cam')") == "Set up camera"
    assert c("l = bpy.data.lights.new('L', type='SUN')") == "Set up lighting"
    assert c("bpy.ops.object.modifier_add(type='SUBSURF')") == "Added modifier"
    # A modeling script that also assigns a material is still modeling ("").
    assert c("bpy.ops.mesh.primitive_cube_add(); obj.data.materials.append(m)") == ""
    # Read-only query → inspection.
    assert c("objs=[o.name for o in bpy.data.objects]; print(objs)") == "Inspected scene"
    assert c("") == ""


def test_readonly_script_mentioning_materials_is_inspection():
    """Regression: the backend's verification snapshot reads material_slots /
    uv_layers / data.lights without mutating anything — it must classify as
    an observation, never "Applied materials"/"Set up lighting" (it showed as
    an acted step on every prompt, before anything was modelled)."""
    c = steps_format.classify_script_action
    snapshot = (
        "import bpy, json\n"
        "_objs = list(bpy.context.scene.objects)\n"
        "bare = [o.name for o in _objs if o.type == 'MESH'"
        " and not any(s.material for s in o.material_slots)]\n"
        "print(json.dumps({'bare': bare}))"
    )
    assert c(snapshot) == "Inspected scene"
    assert c("uvs = [m.uv_layers.active for m in bpy.data.meshes]") == "Inspected scene"
    assert c("n = len([l for l in bpy.data.lights]); print(n)") == "Inspected scene"


def test_inspected_scene_override_when_objects_change():
    """A read-only guess that actually created objects falls back to counts."""
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "unknown", "for o in bpy.data.objects: pass")
    assert bubble.step_items[0].label == "Inspected scene"
    assert bubble.step_items[0].kind == "READ"
    steps_format.finish_step_on_bubble(
        bubble, "r1", {"success": True, "created_objects": ["A", "B"]})
    assert bubble.step_items[0].label == "Created 2 objects"
    assert bubble.step_items[0].kind == "TOOL"


def test_inspected_scene_stays_read_kind_for_execute_script():
    """execute_bpy_script infers COMMAND, but a read-only body is an
    observation — the native row must use the READ glyph, not the filled
    act mark that reads as a highlighted button."""
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "execute_bpy_script",
        "objs=[o.name for o in bpy.data.objects]; print(objs)")
    assert bubble.step_items[0].label == "Inspected scene"
    assert bubble.step_items[0].kind == "READ"
    assert bubble.steps_summary == "1 tool called"
    steps_format.finish_step_on_bubble(bubble, "r1", {"success": True})
    assert bubble.step_items[0].kind == "READ"
    item = steps_format.normalize_step_item(
        {"kind": "COMMAND", "label": "Inspected scene", "status": "DONE"})
    assert item["kind"] == "READ"


def test_begin_step_uses_script_action_when_tool_name_unknown():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "unknown", "bpy.ops.render.render(write_still=True)")
    assert bubble.step_items[0].label == "Rendered scene"
    # The script-inferred label survives finish (counts shown as target).
    steps_format.finish_step_on_bubble(bubble, "r1", {"success": True})
    assert bubble.step_items[0].label == "Rendered scene"
    assert bubble.step_items[0].target == ""


def test_known_tool_name_takes_priority_over_script():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "inspect_geometry", "bpy.ops.render.render()")
    assert bubble.step_items[0].label == "Measured geometry"


def test_unknown_tool_name_defers_to_script():
    """A tool the label table does not know is never shown by name — the
    script classifier labels the row instead."""
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "apply_pbr_texture", "bpy.ops.render.render(write_still=True)")
    assert bubble.step_items[0].label == "Rendered scene"


def test_execute_bpy_script_treated_as_generic_tool_name():
    """The backend names generated scripts "execute_bpy_script" — that says
    nothing about the action, so the script classifier labels the row."""
    assert steps_format.humanize_tool_name("execute_bpy_script") == "Tool call"
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "execute_bpy_script", "bpy.ops.render.render(write_still=True)")
    assert bubble.step_items[0].label == "Rendered scene"


def test_is_internal_step_hides_underscore_names_and_notifications():
    assert steps_format.is_internal_step("_verify_render")
    assert steps_format.is_internal_step("_wait_generation_poll", "req-1")
    assert steps_format.is_internal_step("scene_overview", "notification")
    assert not steps_format.is_internal_step("execute_bpy_script", "req-1")
    assert not steps_format.is_internal_step("merge_lane_results")
    assert not steps_format.is_internal_step("", "")


# --- backend activity payloads merge on call_id ---------------------------

def _activity(call_id, status, label, tool="view_image", kind="read", images=None, error=""):
    data = {"type": "activity", "bubble_id": "b", "call_id": call_id, "tool": tool,
            "status": status, "label": label, "kind": kind}
    if images is not None:
        data["images"] = images
    if error:
        data["error"] = error
    return data


def test_activity_opens_row_for_a_tool_without_a_script():
    bubble = _FakeBubble()
    row = steps_format.apply_activity_to_bubble(
        bubble, _activity("c1", "running", "Viewed an image"))
    assert row.item_id == "c1" and row.call_id == "c1"
    assert row.status == "RUNNING" and row.kind == "READ" and row.label == "Viewed an image"
    steps_format.apply_activity_to_bubble(
        bubble, _activity("c1", "done", "Viewed 2 images", images=[{"id": "a" * 16, "label": "x"}]))
    assert len(bubble.step_items) == 1
    assert bubble.step_items[0].status == "DONE"
    assert bubble.step_items[0].label == "Viewed 2 images"
    assert bubble.steps_summary == "1 tool called"


def test_script_row_adopts_backend_row_on_call_id_and_keeps_specific_label():
    """Backend activity (running) arrives first, then the script RPC for the
    same call: one row, re-keyed to the request id, with the classifier's
    specific label over the backend's generic one."""
    bubble = _FakeBubble()
    steps_format.apply_activity_to_bubble(
        bubble, _activity("c2", "running", "Ran a script", tool="execute_bpy_script", kind="tool"))
    steps_format.begin_step_on_bubble(
        bubble, "req-9", "execute_bpy_script", "objs=[o.name for o in bpy.data.objects]", call_id="c2")
    assert len(bubble.step_items) == 1
    row = bubble.step_items[0]
    assert row.item_id == "req-9" and row.call_id == "c2"
    assert row.label == "Inspected scene" and row.kind == "READ"
    # The backend's `done` for the same call merges, never duplicates, and a
    # generic backend label does not overwrite the specific one.
    steps_format.apply_activity_to_bubble(
        bubble, _activity("c2", "done", "Ran a script", tool="execute_bpy_script", kind="tool"))
    assert len(bubble.step_items) == 1 and row.label == "Inspected scene"
    assert steps_format.finish_step_on_bubble(bubble, "req-9", {"success": True}) is True


def test_script_row_first_then_activity_merges_and_specific_backend_label_wins_over_generic():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "req-1", "unknown", "x = 1", call_id="c3")
    assert bubble.step_items[0].label == "Tool call"
    steps_format.apply_activity_to_bubble(
        bubble, _activity("c3", "done", "Corrected placement", tool="correct_spatial_placement", kind="tool"))
    assert len(bubble.step_items) == 1
    assert bubble.step_items[0].label == "Corrected placement"


def test_activity_running_never_regresses_a_finished_row():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "req-1", "render_viewport", call_id="c4")
    steps_format.finish_step_on_bubble(bubble, "req-1", {"success": True})
    steps_format.apply_activity_to_bubble(bubble, _activity("c4", "running", "Captured viewport"))
    assert bubble.step_items[0].status == "DONE"


def test_activity_failed_sets_error_detail():
    bubble = _FakeBubble()
    row = steps_format.apply_activity_to_bubble(
        bubble, _activity("c5", "failed", "Delegated a task", tool="delegate_tasks", error="bad brief"))
    assert row.status == "FAILED" and row.label == "Failed" and row.detail == "bad brief"


def test_activity_without_call_id_is_ignored():
    bubble = _FakeBubble()
    assert steps_format.apply_activity_to_bubble(bubble, {"status": "done"}) is None
    assert len(bubble.step_items) == 0


def test_images_to_fetch_skips_rows_that_already_hold_local_tiles():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "req-1", "render_viewport", call_id="c6")
    steps_format.attach_step_images(bubble, "req-1", [{"local_path": "/tmp/a.jpg"}])
    row = steps_format.apply_activity_to_bubble(
        bubble, _activity("c6", "done", "Captured viewport", images=[{"id": "a" * 16, "label": "persp"}]))
    assert steps_format.images_to_fetch(bubble, row, _activity(
        "c6", "done", "Captured viewport", images=[{"id": "a" * 16, "label": "persp"}])) == []
    # A row with no tiles (view_image) fetches every ref.
    row2 = steps_format.apply_activity_to_bubble(
        bubble, _activity("c7", "done", "Inspected UV layout", tool="inspect_uv_map"))
    refs = [{"id": "b" * 16, "label": "top"}, {"id": "c" * 16}, {"nope": 1}]
    assert steps_format.images_to_fetch(bubble, row2, _activity("c7", "done", "x", tool="inspect_uv_map", images=refs)) == [
        {"id": "b" * 16, "label": "top"}, {"id": "c" * 16, "label": ""}]


def test_the_same_image_file_is_one_tile_per_bubble():
    """A re-served capture hands back the same refs; a download of a capture
    already saved locally names the same id. Neither shows the picture twice."""
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(bubble, "r1", "render_viewport")
    assert steps_format.attach_step_images(bubble, "r1", [{"local_path": "/c/aaaaaaaaaaaaaaaa.jpg"}]) == 1
    steps_format.begin_step_on_bubble(bubble, "r2", "render_viewport")
    assert steps_format.attach_step_images(bubble, "r2", [{"local_path": "/c/aaaaaaaaaaaaaaaa.jpg"},
                                                          {"local_path": "/c/bbbbbbbbbbbbbbbb.png"}]) == 1
    assert [steps_format._tile_key(i.local_path) for i in bubble.image_items] == ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"]
    # A ref the bubble already holds is not fetched again either.
    row = steps_format.apply_activity_to_bubble(bubble, _activity("c9", "done", "Captured viewport", tool="render_viewport"))
    refs = [{"id": "aaaaaaaaaaaaaaaa", "label": "same"}, {"id": "cccccccccccccccc", "label": "new"}]
    assert steps_format.images_to_fetch(bubble, row, _activity("c9", "done", "x", tool="render_viewport", images=refs)) == [
        {"id": "cccccccccccccccc", "label": "new"}]


def test_view_image_refs_are_never_fetched():
    bubble = _FakeBubble()
    row = steps_format.apply_activity_to_bubble(bubble, _activity("c10", "done", "Viewed 2 images"))
    refs = [{"id": "d" * 16, "label": "old capture"}]
    assert steps_format.images_to_fetch(bubble, row, _activity("c10", "done", "x", images=refs)) == []
