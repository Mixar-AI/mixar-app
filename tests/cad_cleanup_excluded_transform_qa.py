# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Fresh background-only regression for excluded transform evaluation and rollback."""
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/scripts'))
from mixar.modules.common.cad_cleanup.api import dispatch
from mixar.modules.common.cad_cleanup.core import mutations


def authored(obj):
    return {"location": list(obj.location), "rotation_mode": obj.rotation_mode,
            "rotation_euler": list(obj.rotation_euler),
            "rotation_quaternion": list(obj.rotation_quaternion),
            "scale": list(obj.scale), "delta_location": list(obj.delta_location),
            "delta_rotation_euler": list(obj.delta_rotation_euler),
            "delta_scale": list(obj.delta_scale),
            "basis": [list(r) for r in obj.matrix_basis],
            "parent_inverse": [list(r) for r in obj.matrix_parent_inverse],
            "parent": obj.parent.name if obj.parent else None}


def run(forced=False):
    assert bpy.app.background and not bpy.data.filepath, "Use fresh --factory-startup"
    scene = bpy.data.scenes.new("Excluded authored transforms QA")
    bpy.context.window.scene = scene
    root = bpy.data.collections.new("QA vehicle")
    scene.collection.children.link(root)
    excluded = bpy.data.collections.new("QA excluded original")
    root.children.link(excluded)
    parent = bpy.data.objects.new("QA rotated scaled parent", None)
    root.objects.link(parent)
    parent.location = (120, 30, 20)
    parent.rotation_euler = (0.1, 0.2, 0.3)
    parent.scale = (2, 1, 0.5)
    children = []
    for index in range(24 if forced else 3):
        mesh = bpy.data.meshes.new("QA triangle " + str(index))
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        mesh.update()
        obj = bpy.data.objects.new("Surface QA " + str(index), mesh)
        excluded.objects.link(obj)
        obj.parent = parent
        obj.location = (index, 2, 3)
        obj.rotation_euler = (0.11, 0.22, 0.33)
        obj.scale = (0.7, 1.1, 1.2)
        obj.matrix_parent_inverse = Matrix.Translation((1, -2, 3))
        children.append(obj)
    bpy.context.view_layer.update()
    cached = [[list(r) for r in obj.matrix_world] for obj in children]
    layer = bpy.context.view_layer.layer_collection.children[root.name].children[excluded.name]
    layer.exclude = True
    bpy.context.view_layer.update()
    for obj in children:
        obj.location.x += 17
        obj.delta_location.y = 0.125
    bpy.context.view_layer.update()
    stale = all([list(r) for r in obj.matrix_world] == old for obj, old in zip(children, cached))
    before = {o.name: authored(o) for o in children + [parent]}
    common = {"owner_id": "qa-excluded"}

    def call(action, **payload):
        result = dispatch(action, {**common, **payload})
        assert result["success"], (action, result)
        return result

    common["run_id"] = call("start", request_id="excluded-start", root_collection=root.name)["run_id"]
    records = call("inspect", limit=100)["objects"]
    ids = {r["name"]: r["object_id"] for r in records}
    preview = call("propose", stage="5", decisions=[{
        "object_id": ids[obj.name], "category": "_REVIEW_CULL", "reason": "Excluded fixture"}
        for obj in children])
    updates = []

    def count_update(*args):
        updates.append(1)

    bpy.app.handlers.depsgraph_update_post.append(count_update)
    original_capture = mutations.capture
    captures = 0

    def fail_after_mutation(run, **kwargs):
        nonlocal captures
        captures += 1
        result = original_capture(run, **kwargs)
        if captures == 2:
            raise RuntimeError("QA injected final capture failure")
        return result

    if forced:
        mutations.capture = fail_after_mutation
    try:
        result = dispatch("apply", {**common, "proposal_id": preview["proposal_id"], "request_id": "excluded-apply"})
    finally:
        mutations.capture = original_capture
        bpy.app.handlers.depsgraph_update_post.remove(count_update)
    changed = [o.name for o in children + [parent] if authored(o) != before[o.name]]
    report = {"forced": forced, "stale_world_cache_reproduced": stale,
              "apply_result": result, "authored_changed": changed,
              "depsgraph_updates": len(updates), "object_count": len(children)}
    print("EXCLUDED_TRANSFORM_RESULT=" + json.dumps(report), flush=True)
    assert stale, "Fixture did not reproduce a stale excluded-object world cache"
    assert not changed, "Apply/rollback changed authored transforms: " + str(changed)
    if forced:
        assert captures >= 2 and not result["success"], "Injected final capture failure was not reached"
        assert len(updates) <= 8, "Rollback rebuilt dependency graph per object"
        assert all([c.name for c in obj.users_collection] == [excluded.name] for obj in children)
    else:
        assert result["success"], "Classification mistook evaluation of cached world transforms for edits"
        call("undo", operation_id=result["operation_id"], request_id="excluded-undo")
        assert all(authored(o) == before[o.name] for o in children + [parent]), "Undo changed authored transforms"
        assert all([c.name for c in obj.users_collection] == [excluded.name] for obj in children)
    return report


if __name__ == "__main__":
    run("--forced-rollback" in sys.argv)
