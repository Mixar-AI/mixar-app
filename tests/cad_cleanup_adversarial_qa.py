# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run only in a fresh background --factory-startup process; no vehicle input."""

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from cad_cleanup_fixture import FACES, VERTICES, snapshot
from mixar.modules.common.cad_cleanup.api import dispatch


def run():
    assert bpy.app.background and not bpy.data.filepath, "Fresh background fixture required"
    scene = bpy.data.scenes.new("Adversarial CAD QA")
    bpy.context.window.scene = scene
    root = bpy.data.collections.new("Nested vehicle")
    scene.collection.children.link(root)
    original = bpy.data.collections.new("Original, recoverable")
    root.children.link(original)
    meshes = {}
    for name, position, scale in (("ENGINE BLOCK", (10, 2, 3), (1, 1, 1)),
                                  ("BRAKE CALIPER", (4, 5, 6), (2, 3, 4))):
        data = bpy.data.meshes.new(name)
        data.from_pydata(VERTICES, [], FACES)
        data.update()
        obj = bpy.data.objects.new(name, data)
        original.objects.link(obj)
        obj.location = position
        obj.scale = scale
        meshes[name] = obj
    bpy.context.view_layer.update()
    initial = snapshot(meshes)
    common = {"owner_id": "qa-cad"}
    checks = []

    def call(action, **payload):
        result = dispatch(action, {**common, **payload})
        assert result["success"], (action, result)
        return result

    def refused(action, codes, **payload):
        result = dispatch(action, {**common, **payload})
        assert not result["success"], (action, result)
        assert result["error"]["code"] in codes, (action, result)
        return result

    def preview(stage, name, **changes):
        return call("propose", stage=stage, decisions=[{
            "object_id": ids[name], "category": "_SYS_ENGINE_MAIN" if name == "ENGINE BLOCK" else "_SYS_BRAKES_MAIN",
            "reason": "Adversarial fixture explicit decision", **changes}])["proposal_id"]

    def apply(proposal_id, request_id):
        return call("apply", proposal_id=proposal_id, request_id=request_id)

    started = call("start", request_id="original-start", root_collection=root.name)
    common["run_id"] = started["run_id"]
    resumed = call("start", request_id="resume-alias")
    assert resumed["run_id"] == started["run_id"]
    alias_status = dispatch("status", {"owner_id": "qa-cad", "request_id": "resume-alias"})
    assert alias_status["success"], alias_status
    checks.append("resume_request_alias")
    ids = {row["name"]: row["object_id"] for row in call("inspect")["objects"]}

    guarded = call("propose", stage="1", decisions=[])
    request = {"proposal_id": guarded["proposal_id"], "request_id": "revision-replay",
               "expected_revision": call("status")["revision"]}
    applied = call("apply", **request)
    repeated = call("apply", **request)
    assert repeated == applied, "Expected revision broke idempotent replay"
    call("undo", operation_id=applied["operation_id"], request_id="undo-revision-replay")
    checks.append("expected_revision_retry_is_idempotent")

    units = apply(preview("2", "ENGINE BLOCK", unit_factor=0.001), "units")
    now = snapshot(meshes)
    for a, b in zip(now["ENGINE BLOCK"]["world_vertices"], initial["ENGINE BLOCK"]["world_vertices"]):
        assert max(abs(v - w * 0.001) for v, w in zip(a, b)) < 1e-6
    refused("apply", {"units_already_changed"},
            proposal_id=preview("2", "ENGINE BLOCK", unit_factor=0.001), request_id="units-again")
    call("undo", operation_id=units["operation_id"], request_id="undo-units")
    assert snapshot(meshes) == initial, "unit correction did not exactly restore mesh and memberships"
    checks.append("explicit_units_and_undo")

    scaled = apply(preview("4", "BRAKE CALIPER", bake_scale=True), "scale")
    after_scale = snapshot(meshes)
    assert tuple(meshes["BRAKE CALIPER"].scale) == (1, 1, 1)
    assert after_scale["BRAKE CALIPER"]["world_vertices"] == initial["BRAKE CALIPER"]["world_vertices"]
    assert after_scale["BRAKE CALIPER"]["data"] != initial["BRAKE CALIPER"]["data"]
    call("undo", operation_id=scaled["operation_id"], request_id="undo-scale")
    assert snapshot(meshes) == initial
    checks.append("scale_bake_world_preservation_and_undo")

    stale = preview("8", "ENGINE BLOCK")
    empty = call("propose", stage="8b", decisions=[])
    changed = apply(empty["proposal_id"], "empty-stage")
    refused("apply", {"stale_proposal"}, proposal_id=stale, request_id="stale-apply")
    call("undo", operation_id=changed["operation_id"], request_id="undo-empty")
    checks.append("stale_preview")

    mesh = meshes["ENGINE BLOCK"].data
    coordinate = mesh.vertices[0].co.copy()
    mesh.vertices[0].co.x += 0.2
    stale = preview("4", "ENGINE BLOCK", bake_scale=True)
    refused("apply", {"scene_changed"}, proposal_id=stale, request_id="changed-geometry")
    mesh.vertices[0].co = coordinate
    call("status")
    checks.append("external_mesh_change_detected")

    both = call("propose", stage="8", decisions=[
        {"object_id": key, "category": "_SYS_ENGINE_MAIN", "reason": "Recovery case"}
        for key in ids.values()])
    moved = apply(both["proposal_id"], "both-moved")
    before_missing = snapshot(meshes)
    original_name = original.name
    bpy.data.collections.remove(original)
    refused("undo", {"scene_changed", "missing_collection"},
            operation_id=moved["operation_id"], request_id="missing-recovery")
    assert snapshot(meshes) == before_missing, "failed undo altered membership"
    recreated = bpy.data.collections.new(original_name)
    root.children.link(recreated)
    call("undo", operation_id=moved["operation_id"], request_id="retry-recovery")
    assert snapshot(meshes) == initial
    checks.append("missing_recovery_destination_is_atomic")

    # Original meshes survive geometry copies and are necessary for undo.
    modified = apply(preview("4", "BRAKE CALIPER", bake_scale=True), "missing-mesh-scale")
    original_mesh = bpy.data.meshes["BRAKE CALIPER"]
    backup = original_mesh.copy()
    bpy.data.meshes.remove(original_mesh)
    before_missing = snapshot(meshes)
    refused("undo", {"missing_mesh"}, operation_id=modified["operation_id"], request_id="missing-mesh-undo")
    assert snapshot(meshes) == before_missing
    backup.name = "BRAKE CALIPER"
    call("undo", operation_id=modified["operation_id"], request_id="restored-mesh-undo")
    restored = snapshot(meshes)
    for name in meshes:
        assert restored[name]["world_vertices"] == initial[name]["world_vertices"]
        assert restored[name]["collections"] == initial[name]["collections"]
    checks.append("missing_recovery_mesh_is_atomic")
    return {"success": True, "checks": checks}


def duplicate_visibility():
    """A hidden reference must never cause removal of its visible twin."""
    assert bpy.app.background and not bpy.data.filepath
    scene = bpy.data.scenes.new("Duplicate visibility QA")
    bpy.context.window.scene = scene
    root = bpy.data.collections.new("Shared mesh vehicle")
    scene.collection.children.link(root)
    data = bpy.data.meshes.new("Shared mesh")
    data.from_pydata(VERTICES, [], FACES)
    data.update()
    hidden = bpy.data.objects.new("AAA HIDDEN ENGINE", data)
    visible = bpy.data.objects.new("ZZZ VISIBLE ENGINE", data)
    root.objects.link(hidden)
    root.objects.link(visible)
    hidden.hide_render = True
    bpy.context.view_layer.update()
    hidden.hide_set(True)
    common = {"owner_id": "qa-cad"}

    def call(action, **payload):
        result = dispatch(action, {**common, **payload})
        assert result["success"], result
        return result

    common["run_id"] = call("start", request_id="duplicate-start", root_collection=root.name)["run_id"]
    for stage in ("3", "10"):
        proposed = call("analyze", stage=stage)
        call("apply", proposal_id=proposed["proposal_id"], request_id="duplicate-" + stage)
    assert visible.visible_get(), "Stage3/10 removed the only visible copy"
    from mixar.modules.common.cad_cleanup.core.mutations import _render_eligible
    assert _render_eligible(visible), "Stage3/10 removed the only render-eligible copy"
    return {"success": True, "checks": ["hidden_duplicate_reference_preserves_visible_twin"]}


def failed_apply_is_atomic():
    """A destination ancestor collision must not leave a partially-created graph."""
    assert bpy.app.background and not bpy.data.filepath
    scene = bpy.data.scenes.new("Atomic apply QA")
    bpy.context.window.scene = scene
    root = bpy.data.collections.new("Atomic vehicle")
    scene.collection.children.link(root)
    foreign = bpy.data.collections.new("_SYS_ENGINE")
    scene.collection.children.link(foreign)
    objects = {}
    for name in ("BRAKE CALIPER", "ENGINE BLOCK"):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(VERTICES, [], FACES)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        root.objects.link(obj)
        objects[name] = obj
    bpy.context.view_layer.update()
    common = {"owner_id": "qa-cad"}

    def call(action, **payload):
        result = dispatch(action, {**common, **payload})
        assert result["success"], result
        return result

    common["run_id"] = call("start", request_id="atomic-start", root_collection=root.name)["run_id"]
    records = call("inspect")["objects"]
    by_name = {r["name"]: r["object_id"] for r in records}
    p = call("propose", stage="8", decisions=[
        {"object_id": by_name["BRAKE CALIPER"], "category": "_SYS_BRAKES_MAIN", "reason": "First succeeds"},
        {"object_id": by_name["ENGINE BLOCK"], "category": "_SYS_ENGINE_MAIN", "reason": "Ancestor collision"}])
    before_objects = snapshot(objects)
    before_collections = {c.name for c in bpy.data.collections}
    before_status = call("status")
    failed = dispatch("apply", {**common, "proposal_id": p["proposal_id"], "request_id": "atomic-apply"})
    assert not failed["success"], failed
    assert snapshot(objects) == before_objects, "Failed apply changed objects"
    assert {c.name for c in bpy.data.collections} == before_collections, "Failed apply left created collections"
    after_status = call("status")
    assert after_status["revision"] == before_status["revision"]
    assert after_status["stage_status"] == before_status["stage_status"]
    return {"success": True, "checks": ["failed_apply_restores_collection_graph"]}


if __name__ == "__main__":
    if "--duplicate-visibility" in sys.argv:
        result = duplicate_visibility()
    elif "--failed-apply" in sys.argv:
        result = failed_apply_is_atomic()
    else:
        result = run()
    print("CAD_ADVERSARIAL_RESULT=" + json.dumps(result))
