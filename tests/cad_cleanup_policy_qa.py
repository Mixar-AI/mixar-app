# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Real Blender regression checks for parameter fingerprints and visibility policy."""
import json
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from cad_cleanup_fixture import FACES, VERTICES
from mixar.modules.common.cad_cleanup.api import dispatch


def run():
    assert bpy.app.background and not bpy.data.filepath, "Fresh --factory-startup required"
    scene = bpy.data.scenes.new("CAD parameter and visibility QA")
    bpy.context.window.scene = scene
    root = bpy.data.collections.new("CAD policy vehicle")
    scene.collection.children.link(root)

    def mesh(name):
        data = bpy.data.meshes.new(name)
        data.from_pydata(VERTICES, [], FACES)
        data.update()
        obj = bpy.data.objects.new(name, data)
        root.objects.link(obj)
        return obj

    subject = mesh("ENGINE BLOCK")
    configured = mesh("BRAKE CALIPER")
    bevel = configured.modifiers.new("QA bevel", "BEVEL")
    constraint = configured.constraints.new("LIMIT_LOCATION")
    sheared = mesh("SHEARED BODY PANEL")
    parent = bpy.data.objects.new("Nonuniform parent", None)
    root.objects.link(parent)
    parent.scale = (2, 1, 1)
    sheared.parent = parent
    sheared.rotation_euler.z = 0.5
    bpy.context.view_layer.update()
    common = {"owner_id": "qa-cad"}
    checks = []

    def call(action, **payload):
        result = dispatch(action, {**common, **payload})
        assert result["success"], (action, result)
        return result

    def refused(action, expected, **payload):
        result = dispatch(action, {**common, **payload})
        assert not result["success"] and result["error"]["code"] in expected, result

    common["run_id"] = call("start", request_id="policy-start", root_collection=root.name)["run_id"]
    ids = {r["name"]: r["object_id"] for r in call("inspect")["objects"]}
    checks.append("modifier_constraint_rna_snapshot")
    stale = call("analyze", stage="8")
    original_width = bevel.width
    bevel.width += 0.1
    refused("apply", {"scene_changed"}, proposal_id=stale["proposal_id"], request_id="changed-width")
    bevel.width = original_width
    call("status")
    checks.append("bevel_parameter_edit_invalidates_preview_and_restore_resumes")
    original_min = constraint.min_x
    constraint.min_x += 0.5
    call("status")  # Status is recorded evidence, not a live scene audit.
    refused("apply", {"scene_changed"}, proposal_id=stale["proposal_id"], request_id="changed-constraint")
    constraint.min_x = original_min
    call("status")
    checks.append("constraint_parameter_edit_detected_without_pose_change")

    def propose(stage, target=subject, category="_SYS_ENGINE_MAIN", **extra):
        return call("propose", stage=stage, decisions=[{
            "object_id": ids[target.name], "category": category,
            "reason": "Explicit policy fixture decision", **extra}])["proposal_id"]

    call("apply", proposal_id=propose("8"), request_id="identify")
    hidden = call("apply", proposal_id=propose("10", presentation_hidden=True), request_id="hide")
    assert not subject.visible_get() and subject.hide_render
    shown = call("apply", proposal_id=propose("10", presentation_hidden=False), request_id="show")
    assert subject.visible_get() and not subject.hide_render
    call("undo", operation_id=shown["operation_id"], request_id="undo-show")
    assert not subject.visible_get() and subject.hide_render
    call("undo", operation_id=hidden["operation_id"], request_id="undo-hide")
    assert subject.visible_get() and not subject.hide_render
    checks.append("presentation_hide_show_and_undo")
    refused("propose", {"invalid_visibility"}, stage="10", decisions=[{
        "object_id": ids[subject.name], "category": "_REVIEW_UNCLASSIFIED",
        "reason": "Review must remain visible", "presentation_hidden": True}])
    assert subject.visible_get() and not subject.hide_render
    checks.append("review_parts_cannot_be_presentation_hidden")
    false_duplicate = propose("3", category="_DUP_COINCIDENT")
    refused("apply", {"unproven_duplicate"}, proposal_id=false_duplicate, request_id="false-duplicate")
    assert subject.visible_get() and not subject.hide_render
    checks.append("agent_cannot_assert_unproven_duplicate")
    from mathutils import Matrix
    loc, rot, scale = sheared.matrix_world.decompose()
    approximate = Matrix.LocRotScale(loc, rot, scale)
    assert max(abs(approximate[r][c] - sheared.matrix_world[r][c])
               for r in range(4) for c in range(4)) > 1e-6, "Fixture must contain real world shear"
    before = sheared.matrix_world.copy()
    unsupported = propose("4", target=sheared, bake_scale=True)
    refused("apply", {"unsupported_geometry", "unsupported_shear"},
            proposal_id=unsupported, request_id="shear")
    assert sheared.matrix_world == before
    checks.append("sheared_dependency_geometry_edit_refused")
    return {"success": True, "checks": checks}


if __name__ == "__main__":
    print("CAD_POLICY_RESULT=" + json.dumps(run()))
