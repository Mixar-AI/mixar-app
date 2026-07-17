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


def test_single_read():
    assert format_steps_summary(["READ"]) == "Read 1 file"


def test_read_and_command():
    # One file read, one command run.
    assert format_steps_summary(["READ", "COMMAND"]) == "Read 1 file · ran 1 command"


def test_pluralization_and_grouping():
    # Two reads, two commands -> pluralized, grouped, kind order preserved.
    summary = format_steps_summary(["READ", "COMMAND", "READ", "COMMAND"])
    assert summary == "Read 2 files · ran 2 commands"


def test_all_kinds_order():
    summary = format_steps_summary(["READ", "WRITE", "COMMAND", "SEARCH", "TOOL"])
    assert summary == (
        "Read 1 file · wrote 1 file · ran 1 command · "
        "ran 1 search · used 1 tool"
    )


def test_unknown_kind_ignored():
    assert format_steps_summary(["READ", "NOPE"]) == "Read 1 file"


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


class _FakeBubble:
    def __init__(self):
        self.step_items = _FakeColl()
        self.steps_summary = ""


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
    assert bubble.steps_summary == "Read 1 file · ran 1 command"


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
    assert row.label == "Create cube"
    assert row.status == "RUNNING"
    assert row.detail == ""
    assert bubble.steps_summary == "Used 1 tool"


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
    steps_format.finish_step_on_bubble(
        bubble, "r1", {"success": True, "created_objects": ["A", "B"]})
    assert bubble.step_items[0].label == "Created 2 objects"


def test_begin_step_uses_script_action_when_tool_name_unknown():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "unknown", "bpy.ops.render.render(write_still=True)")
    assert bubble.step_items[0].label == "Rendered scene"
    # The script-inferred label survives finish (counts shown as target).
    steps_format.finish_step_on_bubble(bubble, "r1", {"success": True})
    assert bubble.step_items[0].label == "Rendered scene"
    assert bubble.step_items[0].target == ""


def test_real_tool_name_takes_priority_over_script():
    bubble = _FakeBubble()
    steps_format.begin_step_on_bubble(
        bubble, "r1", "apply_pbr_texture", "bpy.ops.render.render()")
    assert bubble.step_items[0].label == "Apply pbr texture"


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
