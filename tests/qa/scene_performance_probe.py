# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run inside an isolated real Blender GUI via scene_performance_fixes.py."""
import ast
import hashlib
import math
import statistics
import time
from array import array
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

from mixar.modules.common.utils.animation import action_fcurves
from mixar.modules.space_mixie_chat.core import animation_effects, checkpoint_store
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor


def median_call(fn, repeats=3):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return {"median_seconds": statistics.median(samples), "samples": samples}


def run(root, backend):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    executor = ScriptExecutor()
    results = {}

    def noop():
        response = executor.execute('__RESULT__ = {"value": 1}', push_undo=False)
        assert response.success and not response.modified_objects
        assert not response.created_objects and not response.deleted_objects

    results["baseline_noop"] = median_call(noop)
    obj = bpy.data.objects.new("QA_BinaryRoundTrip", None)
    bpy.context.scene.collection.objects.link(obj)
    try:
        payloads = (b"initial", b"\0first\0last\0", b"\0" * 4096,
                    b"", b"abc\0def" * 100000, b"short\0")
        for payload in payloads:
            obj["gaussian_data"] = payload
            assert obj["gaussian_data"] == payload
        # Exercise mapping.update and nested ID-property groups too.
        obj.id_properties_ensure().update({"gaussian_data": b"\0updated\0"})
        obj["nested"] = {"blob": b"first"}
        obj["nested"]["blob"] = b"a\0b\0"
        assert obj["gaussian_data"] == b"\0updated\0"
        assert obj["nested"]["blob"] == b"a\0b\0"
        obj["text"] = "Unicode café"
        obj["text"] = "東京"
        assert obj["text"] == "東京"
        # Blender retains an appended library record after its object is removed.
        saved = root / f"binary-roundtrip-{time.time_ns()}.mixar"
        bpy.ops.wm.save_as_mainfile(filepath=str(saved), copy=True, compress=True)
        with bpy.data.libraries.load(str(saved), link=False) as (source, target):
            target.objects = [obj.name]
        imported = target.objects[0]
        try:
            assert imported["gaussian_data"] == b"\0updated\0"
            assert imported["nested"]["blob"] == b"a\0b\0"
            assert imported["text"] == "東京"
        finally:
            bpy.data.objects.remove(imported, do_unlink=True)
        results["binary_overwrite_and_file_roundtrip"] = True

        payload = np.random.default_rng(12).random(500000 * 59, dtype=np.float32).tobytes()
        obj["gaussian_data"] = payload
        assert obj["gaussian_data"] == payload
        results["payload_bytes"] = len(payload)
        results["binary_noop"] = median_call(noop)
        before = executor._capture_scene_state()
        obj["gaussian_data"] = bytes([payload[0] ^ 255]) + payload[1:]
        assert len(obj["gaussian_data"]) == len(payload)
        after = executor._capture_scene_state()
        assert obj.name in executor._detect_changes(before, after)["modified"]
        results["binary_same_length_edit_detected"] = True
        # Hash the same large bytes through the checkpoint implementation.
        hash_path = root / "hash-fixture.bin"
        hash_path.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()
        def checkpoint_hash():
            assert checkpoint_store._sha256(str(hash_path)) == expected
        results["checkpoint_hash"] = median_call(checkpoint_hash)
        def old_checkpoint_hash():
            digest = hashlib.sha256()
            with hash_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(chunk)
            assert digest.hexdigest() == expected
        results["previous_checkpoint_hash"] = median_call(old_checkpoint_hash)
        results["checkpoint_digest_compatible"] = True
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)

    obj = bpy.data.objects.new("QA_Animated", None)
    bpy.context.scene.collection.objects.link(obj)
    action = None
    try:
        obj.keyframe_insert(data_path="location", index=0, frame=1)
        action = obj.animation_data.action
        curve = action_fcurves(obj)[0]
        curve.keyframe_points.add(1)
        curve.keyframe_points[1].co = (2, 3)
        curve.update()
        edits = {
            "co": (1, 4), "handle_left": (0, 5), "handle_right": (2, 6),
            "interpolation": "ELASTIC", "easing": "EASE_IN",
            "handle_left_type": "FREE", "handle_right_type": "VECTOR",
            "amplitude": 4.0, "back": 3.0, "period": 2.0,
        }
        for field, value in edits.items():
            before = animation_effects.animation_fingerprint(obj, {})
            setattr(curve.keyframe_points[0], field, value)
            assert animation_effects.animation_fingerprint(obj, {}) != before, field
        before = animation_effects.animation_fingerprint(obj, {})
        curve.modifiers.new("NOISE")
        assert animation_effects.animation_fingerprint(obj, {}) != before
        before = animation_effects.animation_fingerprint(obj, {})
        driver = obj.driver_add("scale", 0)
        driver.driver.expression = "2.0"
        assert animation_effects.animation_fingerprint(obj, {}) != before
        obj.driver_remove("scale", 0)
        for modifier in list(curve.modifiers):
            curve.modifiers.remove(modifier)
        results["animation_key_modifier_driver_edits_detected"] = True
        curve.keyframe_points.clear()
        curve.keyframe_points.add(500000)
        coords = array("f", (v for i in range(500000) for v in (i + 1, float(i % 23))))
        curve.keyframe_points.foreach_set("co", coords)
        curve.update()
        results["animation_500k_noop"] = median_call(noop)
        shared = bpy.data.objects.new("QA_SharedAction", None)
        bpy.context.scene.collection.objects.link(shared)
        try:
            shared.animation_data_create()
            shared.animation_data.action = action
            shared.animation_data.action_slot = obj.animation_data.action_slot
            before = executor._capture_scene_state()
            curve.keyframe_points[0].co.y += 1.0
            changed = executor._detect_changes(before, executor._capture_scene_state())["modified"]
            assert obj.name in changed and shared.name in changed
            results["shared_action_edit_detected_for_both_owners"] = True
        finally:
            bpy.data.objects.remove(shared, do_unlink=True)
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        if action:
            bpy.data.actions.remove(action)

    # Hidden-scene edits must still appear in the executor's global diff.
    hidden = bpy.data.scenes.new("QA_HiddenChanges")
    obj = bpy.data.objects.new("QA_HiddenObject", None)
    hidden.collection.objects.link(obj)
    try:
        before = executor._capture_scene_state()
        obj["blob"] = b"\0hidden\0"
        assert obj.name in executor._detect_changes(before, executor._capture_scene_state())["modified"]
        results["other_scene_changes_detected"] = True
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(hidden)

    results["bounds"] = bounds_probe(backend)
    return results


def bounds_probe(backend):
    path = Path(backend) / "modules/agent/tools/scripts/scene_tasks/workspace_operation.py"
    node = next(n for n in ast.parse(path.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == "_make_plan")
    params = {"placement": {"scale": 1.2, "rotation_z_deg": 35, "location": [3, 4, 5]}}
    scope = dict(bpy=bpy, math=math, Matrix=Matrix, Vector=Vector, _P=params,
                 _is_clone=lambda obj: False)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
    scene = bpy.context.scene
    mesh = bpy.data.meshes.new("QA_DenseBounds")
    obj = bpy.data.objects.new("QA_DenseBounds", mesh)
    scene.collection.objects.link(obj)
    try:
        count = 1000000
        mesh.vertices.add(count)
        coords = np.random.default_rng(1).random((count, 3), dtype=np.float32) * 30
        mesh.vertices.foreach_set("co", coords.ravel())
        mesh.update()
        obj.location = (2, 3, 4)
        obj.scale = (-1.0, 1.5, 0.75)
        bpy.context.view_layer.update()
        rotation = Matrix.Rotation(math.radians(35), 4, "Z") @ Matrix.Scale(1.2, 4)
        # Independent original vertex loop oracle (one pass, not timed).
        lo, hi = [math.inf] * 3, [-math.inf] * 3
        for vertex in mesh.vertices:
            point = rotation @ obj.matrix_world @ vertex.co
            lo = [min(a, b) for a, b in zip(lo, point)]
            hi = [max(a, b) for a, b in zip(hi, point)]
        expected = np.array([3 - (lo[0] + hi[0]) / 2, 4 - (lo[1] + hi[1]) / 2, 5 - lo[2]])
        def plan():
            result = scope["_make_plan"](scene, [obj], "QA_BoundsRoot")
            assert np.allclose(np.asarray(result["matrix"])[:3, 3], expected, atol=1e-5)
        timing = median_call(plan)
        # Evaluated modifier output, zero vertices, and invalid coordinates.
        modifier = obj.modifiers.new("QA_Array", "ARRAY")
        modifier.count = 2
        modifier.use_relative_offset = False
        modifier.use_constant_offset = True
        modifier.constant_offset_displace = (50, 0, 0)
        with_modifier = scope["_make_plan"](scene, [obj], "QA_BoundsRoot")
        assert not np.allclose(np.asarray(with_modifier["matrix"])[:3, 3], expected)
        obj.modifiers.remove(modifier)
        coords[0, 0] = np.nan
        mesh.vertices.foreach_set("co", coords.ravel())
        mesh.update()
        try:
            scope["_make_plan"](scene, [obj], "QA_BoundsRoot")
        except RuntimeError as error:
            assert "non-finite" in str(error)
        else:
            raise AssertionError("Non-finite geometry accepted")
        return {**timing, "vertices": count, "placement_matches": True,
                "evaluated_modifier_used": True, "nonfinite_rejected": True}
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
