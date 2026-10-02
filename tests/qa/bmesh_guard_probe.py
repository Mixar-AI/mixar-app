# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native mesh fixtures, executed only inside an isolated QA Dev instance."""
import time

import bpy
import numpy as np

from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
from mixar.modules.space_mixie_chat.core.sandbox_mesh import guard_from_mesh


def run():
    # Own only this fixture's IDs, so the scenario can be replayed without the
    # harness reset's dependency on a particular startup editor layout.
    for obj in list(bpy.data.objects):
        if obj.name.startswith("QA_ValidatedRiver"):
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(("QA_ValidRiver", "QA_InvalidRiver", "QA_DenseRiver")):
            bpy.data.meshes.remove(mesh)
    for material in list(bpy.data.materials):
        if material.name.startswith("QA_RiverWater") and material.users == 0:
            bpy.data.materials.remove(material)
    executor = ScriptExecutor()
    verdict = {}
    mesh_count = len(bpy.data.meshes)
    vertices = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    expressions = [
        "bm.from_mesh(mesh)",
        "convert = bm.from_mesh; convert(mesh)",
        "getattr(bm, 'from_' + 'mesh')(mesh)",
        "bmesh.types.BMesh.from_mesh(bm, mesh=mesh, vertex_normals=False)",
    ]
    for face in [(0, 1, 2, 2, 3), (0, 1, 2, 0, 3), (0, 1, 2, 3, 0)]:
        mesh = bpy.data.meshes.new("QA_InvalidRiver")
        mesh.from_pydata(vertices, [], [face, (0, 2, 3)])
        original = [tuple(p.vertices) for p in mesh.polygons]
        try:
            for expression in expressions:
                code = (
                    "import bpy, bmesh\n"
                    f"mesh = bpy.data.meshes[{mesh.name!r}]\n"
                    "bm = bmesh.new()\ntry:\n    " + expression +
                    "\nfinally:\n    bm.free()\n"
                )
                result = executor.execute(code, push_undo=False)
                assert not result.success, (face, expression, result.to_dict())
                assert "Invalid mesh topology" in result.error, result.to_dict()
                assert [tuple(p.vertices) for p in mesh.polygons] == original
                assert len(bpy.data.meshes) == mesh_count + 1
            # The agent receives an actionable refusal and can repair and continue.
            result = executor.execute(
                "import bpy, bmesh\n"
                f"mesh = bpy.data.meshes[{mesh.name!r}]\n"
                "repaired = mesh.validate(clean_customdata=False)\n"
                "bm = bmesh.new()\ntry:\n"
                "    bm.from_mesh(mesh)\n"
                "    bmesh.ops.delete(bm, geom=list(bm.faces)[:1], context='FACES')\n"
                "    bm.to_mesh(mesh)\n"
                "finally:\n    bm.free()\n"
                "__RESULT__ = {'repaired': repaired, 'faces': len(mesh.polygons)}\n",
                push_undo=False,
            )
            assert result.success and result.return_value["repaired"], result.to_dict()
        finally:
            bpy.data.meshes.remove(mesh)
    verdict["invalid_faces_refused_without_source_mutation"] = 12
    verdict["explicit_repair_and_delete_succeeded"] = 3

    mesh = bpy.data.meshes.new("QA_ValidRiver")
    mesh.from_pydata(vertices, [], [(0, 1, 2), (0, 2, 3)])
    uv = mesh.uv_layers.new(name="RiverUV")
    uv.data.foreach_set("uv", [0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1])
    point = mesh.attributes.new("river_depth", "FLOAT", "POINT")
    point.data.foreach_set("value", [1, 2, 3, 4])
    mesh.polygons[1].use_smooth = True
    material = bpy.data.materials.new("QA_RiverWater")
    material.diffuse_color = (0.025, 0.39, 0.46, 1)
    mesh.materials.append(material)
    obj = bpy.data.objects.new("QA_ValidatedRiver", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.shape_key_add(name="Basis")
    key = obj.shape_key_add(name="Ripple")
    key.data[0].co.z = 0.5
    import bmesh
    bm = bmesh.new()
    try:
        guard_from_mesh(bm.from_mesh)(mesh, use_shape_key=True, shape_key_index=1)
        assert abs(next(iter(bm.verts)).co.z - 0.5) < 1e-6
        assert bm.loops.layers.uv.get("RiverUV") is not None
        assert bm.verts.layers.float.get("river_depth") is not None
    finally:
        bm.free()
    assert [v.value for v in point.data] == [1, 2, 3, 4]
    assert mesh.materials[0] == material and mesh.polygons[1].use_smooth
    assert len(mesh.shape_keys.key_blocks) == 2
    verdict["valid_uv_attribute_material_shading_and_shape_key_preserved"] = True

    # Dense, valid data: measure the guard separately from conversion cost.
    n = 500
    dense = bpy.data.meshes.new("QA_DenseRiver")
    coords = np.zeros(((n + 1) ** 2, 3), dtype=np.float32)
    coords[:, 0] = np.tile(np.arange(n + 1), n + 1)
    coords[:, 1] = np.repeat(np.arange(n + 1), n + 1)
    base = (np.arange(n)[:, None] * (n + 1) + np.arange(n)).ravel()
    corners = np.column_stack((base, base + 1, base + n + 2, base + n + 1))
    dense.vertices.add(len(coords))
    dense.vertices.foreach_set("co", coords.ravel())
    dense.loops.add(corners.size)
    dense.loops.foreach_set("vertex_index", corners.ravel())
    dense.polygons.add(n * n)
    dense.polygons.foreach_set("loop_start", np.arange(n * n) * 4)
    dense.polygons.foreach_set("loop_total", np.full(n * n, 4))
    dense.update(calc_edges=True)
    try:
        timings = {}
        for label, guarded in [("native", False), ("guarded", True)]:
            bm = bmesh.new()
            try:
                convert = guard_from_mesh(bm.from_mesh) if guarded else bm.from_mesh
                start = time.perf_counter()
                convert(dense)
                timings[label] = time.perf_counter() - start
                assert len(bm.faces) == n * n
            finally:
                bm.free()
        verdict["dense_mesh"] = {"faces": n * n, "seconds": timings}
        assert timings["guarded"] < 10, timings
    finally:
        bpy.data.meshes.remove(dense)
    assert len(bpy.data.meshes) == mesh_count + 1
    verdict["temporary_meshes_cleaned"] = True
    return verdict
