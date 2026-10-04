# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Blender fixtures for watch drilling and bulk coordinate edits.

Loaded by watch_performance_e2e.py into the GUI harness. Geometry is isolated
in QA_Watch_Performance. No subprocess or worker is used for geometry.
"""
import math
import time

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def ring(name, outer, inner, height, segments=96):
    vertices = []
    for z in (-height / 2, height / 2):
        for radius in (outer, inner):
            vertices.extend((radius * math.cos(i * math.tau / segments),
                             radius * math.sin(i * math.tau / segments), z)
                            for i in range(segments))
    n = segments
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.extend(((i, j, 2*n+j, 2*n+i), (n+j, n+i, 3*n+i, 3*n+j),
                      (2*n+i, 2*n+j, 3*n+j, 3*n+i), (j, i, n+i, n+j)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def volume(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        return abs(bm.calc_volume())
    finally:
        bm.free()


def boolean_case(api, batched):
    """Same 16 through-holes as the watch; compare sequential Exact to AUTO."""
    name = "QA_Batched" if batched else "QA_Sequential"
    target = ring(name, .01735, .01465, .0008)
    finish = target.modifiers.new("Finish", "BEVEL")
    finish.width, finish.segments = .00002, 2
    target.modifiers.new("Normals", "WEIGHTED_NORMAL")
    before_selection = [o.name for o in bpy.context.selected_objects]
    before_active = bpy.context.view_layer.objects.active
    cutters = []
    start = time.perf_counter()
    for i in range(16):
        cutter = ring("QA_Drill", .00034, .000001, .003)
        cutter.location = (.016 * math.cos(i * math.tau / 16),
                           .016 * math.sin(i * math.tau / 16), 0)
        cutters.append(cutter)
        if not batched:
            mod = target.modifiers.new("Drilling", "BOOLEAN")
            mod.operation, mod.object, mod.solver = "DIFFERENCE", cutter, "EXACT"
            with bpy.context.temp_override(object=target, active_object=target,
                                           selected_objects=[target], selected_editable_objects=[target]):
                assert "FINISHED" in bpy.ops.object.modifier_apply(modifier=mod.name)
            bpy.data.objects.remove(cutter, do_unlink=True)
    if batched:
        receipt = api.boolean_difference(target, cutters)
        assert all(bpy.context.scene.objects.get(o.name) == o for o in cutters)
        for cutter in cutters:
            mesh = cutter.data
            bpy.data.objects.remove(cutter, do_unlink=True)
            if not mesh.users:
                bpy.data.meshes.remove(mesh)
    elapsed = time.perf_counter() - start
    assert [o.name for o in bpy.context.selected_objects] == before_selection
    assert bpy.context.view_layer.objects.active == before_active
    assert [(m.type, m.show_viewport) for m in target.modifiers] == [
        ("BEVEL", True), ("WEIGHTED_NORMAL", True)]
    probe = target.data.copy()
    try:
        assert not probe.validate(clean_customdata=False)
    finally:
        bpy.data.meshes.remove(probe)
    result = dict(seconds=elapsed, solver=receipt["solver"] if batched else "EXACT",
                  faces=len(target.data.polygons),
                  vertices=len(target.data.vertices), volume=volume(target.data))
    target.location.x = .024 if batched else -.024
    return result


def coordinate_case(api):
    mesh = bpy.data.meshes.new("QA_BulkCoordinates")
    count = 100000
    points = np.zeros((count, 3), dtype=np.float32)
    t = np.linspace(0, 2.14, count)
    points[:, 0] = np.sin(t * 177) * .01
    points[:, 1] = .026 * np.cos(t) + .025 * np.sin(t)
    points[:, 2] = -.0007 - .034 * (1 - np.cos(t)) + .001
    mesh.vertices.add(count)
    mesh.vertices.foreach_set("co", points.ravel())
    marker = mesh.attributes.new("qa_marker", "FLOAT", "POINT")
    marker.data.foreach_set("value", np.ones(count, dtype=np.float32))
    obj = bpy.data.objects.new("QA_BulkCoordinates", mesh)
    bpy.context.scene.collection.objects.link(obj)
    start = time.perf_counter()
    for vertex in mesh.vertices:
        w = vertex.co.copy()
        c = (w.z + .0347) / .034
        s = (w.y - .026 * c) / .025
        t = max(0, min(2.14, math.atan2(s, c)))
        dy = -.026 * math.sin(t) + .025 * math.cos(t)
        dz = -.034 * math.sin(t)
        le = math.hypot(dy, dz)
        normal = Vector((0, -dz / le, dy / le))
        base = Vector((w.x, .026 * math.cos(t) + .025 * math.sin(t),
                       -.0007 - .034 * (1 - math.cos(t))))
        h = (w - base).dot(normal)
        if h > 0:
            width = .022 - .0032 * min(t / 1.7, 1)
            ideal = .00125 + .0004 * max(0, 1 - (2 * w.x / width) ** 2)
            vertex.co += normal * max(0, ideal - h) * .75
        vertex.co.y -= .0045 * max(0, 1 - t / .2) ** 2
    slow = time.perf_counter() - start
    expected = api.read_positions(mesh)
    mesh.vertices.foreach_set("co", points.ravel())
    start = time.perf_counter()
    actual = api.read_positions(mesh)
    c = (actual[:, 2] + .0347) / .034
    s = (actual[:, 1] - .026 * c) / .025
    t = np.clip(np.arctan2(s, c), 0, 2.14)
    dy = -.026 * np.sin(t) + .025 * np.cos(t)
    dz = -.034 * np.sin(t)
    length = np.hypot(dy, dz)
    normal_y, normal_z = -dz / length, dy / length
    base_y = .026 * np.cos(t) + .025 * np.sin(t)
    base_z = -.0007 - .034 * (1 - np.cos(t))
    h = (actual[:, 1] - base_y) * normal_y + (actual[:, 2] - base_z) * normal_z
    width = .022 - .0032 * np.minimum(t / 1.7, 1)
    ideal = .00125 + .0004 * np.maximum(0, 1 - (2 * actual[:, 0] / width) ** 2)
    delta = np.where(h > 0, np.maximum(0, ideal - h) * .75, 0)
    actual[:, 1] += normal_y * delta - .0045 * np.maximum(0, 1 - t / .2) ** 2
    actual[:, 2] += normal_z * delta
    api.write_positions(mesh, actual)
    fast = time.perf_counter() - start
    np.testing.assert_allclose(api.read_positions(mesh), expected, rtol=1e-5, atol=1e-7)
    assert mesh.attributes["qa_marker"].data[42].value == 1
    for invalid in (np.zeros((3, 3)), np.full((count, 3), np.nan)):
        try:
            api.write_positions(mesh, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid bulk positions accepted")
    np.testing.assert_allclose(api.read_positions(mesh), expected, rtol=1e-5, atol=1e-7)
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    return dict(vertices=count, sequential_seconds=slow, bulk_seconds=fast)


def fallback_cases(api):
    # Overlapping cutter bounds must retain Exact, including transformed,
    # mirrored and parented operands. Compare with an explicit Exact run.
    results = []
    for solver in ("AUTO", "EXACT"):
        target = ring("QA_Overlap_" + solver, .012, .002, .001)
        cutters = [ring("QA_OverlapCut", .002, .000001, .004) for _ in range(2)]
        cutters[0].location.x, cutters[1].location.x = .006, .007
        cutters[1].scale.x = -1
        cutters[1].rotation_euler.z = .4
        cutters[1].parent = target
        receipt = api.boolean_difference(target, cutters, solver=solver)
        assert receipt["solver"] == "EXACT"
        results.append(volume(target.data))
        for obj in [*cutters, target]:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)
    assert math.isclose(*results, rel_tol=1e-8), results
    return {"overlap_uses_exact": True, "transformed_cutter_volumes": results}


def contracts(api):
    target = ring("QA_Contract", .01, .005, .001)
    cutter = ring("QA_ContractCutter", .001, .000001, .004)
    before = len(target.data.polygons)
    sub = target.modifiers.new("Subdivision", "SUBSURF")
    try:
        api.boolean_difference(target, [cutter])
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported modifier stack accepted")
    assert len(target.data.polygons) == before
    assert target.modifiers[0] == sub and len(target.modifiers) == 1
    target.modifiers.remove(sub)
    target.data.materials.append(bpy.data.materials.new("QA_Material"))
    api.fill_material_index(target.data)
    assert all(p.material_index == 0 for p in target.data.polygons)
    # A rejected cutter must restore finishing settings and discard all temps.
    finish = target.modifiers.new("Finish", "BEVEL")
    finish.show_viewport = True
    broken = bpy.data.meshes.new("QA_InvalidCutter")
    broken.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2, 1)])
    old_mesh = cutter.data
    cutter.data = broken
    try:
        api.boolean_difference(target, [cutter])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid cutter accepted")
    assert finish.show_viewport and len(target.modifiers) == 1
    assert len(target.data.polygons) == before
    cutter.data = old_mesh
    target_mesh = target.data
    target.data = broken
    for solver in ("AUTO", "EXACT"):
        try:
            api.boolean_difference(target, [cutter], solver=solver)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid target accepted by " + solver)
        assert finish.show_viewport and len(target.modifiers) == 1
        assert len(broken.polygons) == 1, "source topology was silently repaired"
    target.data = target_mesh
    bpy.data.meshes.remove(broken)
    assert not any(o.name.startswith("_MixarBooleanOperand") for o in bpy.data.objects)
    assert not any(m.name.startswith("_MixarBooleanOperand") for m in bpy.data.meshes)
    for obj in (target, cutter):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    return {"unsupported_stack_refused": True, "invalid_cutter_refused": True,
            "invalid_target_refused_for_both_solvers": True,
            "finishing_restored": True, "temporary_operands_cleaned": True}
