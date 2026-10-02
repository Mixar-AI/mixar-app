# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native stress cases; run individually with an external process deadline first."""
import hashlib
import math
import time

import bpy
import numpy as np

from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor

CASES = (
    "repeated_adjacent", "repeated_middle", "repeated_closing", "self_edge",
    "bad_edge_index", "bad_corner_index", "duplicate_faces", "nan_vertex",
    "wrong_corner_edge", "empty", "wire", "loose_vertices", "coincident_vertices",
    "zero_area", "non_manifold", "concave_ngon", "large_ngon", "dense_250k",
    "dense_1m", "clipped_raw", "clipped_repaired", "repeated_edits",
)


def grid(mesh, n):
    coords = np.zeros(((n + 1) ** 2, 3), dtype=np.float32)
    coords[:, 0] = np.tile(np.arange(n + 1), n + 1) / n
    coords[:, 1] = np.repeat(np.arange(n + 1), n + 1) / n
    base = (np.arange(n)[:, None] * (n + 1) + np.arange(n)).ravel()
    corners = np.column_stack((base, base + 1, base + n + 2, base + n + 1))
    mesh.vertices.add(len(coords))
    mesh.vertices.foreach_set("co", coords.ravel())
    mesh.loops.add(corners.size)
    mesh.loops.foreach_set("vertex_index", corners.ravel())
    mesh.polygons.add(n * n)
    mesh.polygons.foreach_set("loop_start", np.arange(n * n) * 4)
    mesh.polygons.foreach_set("loop_total", np.full(n * n, 4))
    mesh.update(calc_edges=True)


def clipped(mesh, repair):
    """Replay the incident's clipping + rounded-XY welding pattern on synthetic terrain.

    Shore vertices lie exactly on the water plane. The original <= / < tests
    emit the same endpoint twice, and 'at least three unique IDs' accepts it.
    """
    from mathutils import Vector
    vertices, faces, lookup = [], [], {}
    repeats = 0
    for y in range(300):
        for x in range(-30, 30):
            points = [Vector((a * .1 + math.sin(b * .015), b * .1,
                              (abs(a) - 20) * .01))
                      for a, b in ((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1))]
            for ids in ((0, 1, 2), (0, 2, 3)):
                pts = [points[i] for i in ids]
                if min(p.z for p in pts) >= 0:
                    continue
                poly = []
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    if a.z <= 0:
                        poly.append(a)
                    if (a.z < 0) != (b.z < 0):
                        poly.append(a + (b - a) * (-a.z / (b.z - a.z)))
                face = []
                for p in poly:
                    key = (round(p.x, 6), round(p.y, 6))
                    if key not in lookup:
                        lookup[key] = len(vertices)
                        vertices.append((p.x, p.y, 0))
                    face.append(lookup[key])
                if len(set(face)) < 3:
                    continue
                if len(set(face)) != len(face):
                    repeats += 1
                    if repair:
                        cleaned = []
                        for index in face:
                            if not cleaned or cleaned[-1] != index:
                                cleaned.append(index)
                        if cleaned[0] == cleaned[-1]:
                            cleaned.pop()
                        face = cleaned
                        if len(face) < 3 or len(set(face)) != len(face):
                            continue
                faces.append(face)
    assert repeats > 0, "fixture must exercise the original clipping degeneracy"
    mesh.from_pydata(vertices, [], faces)
    return repeats


def build(name):
    mesh = bpy.data.meshes.new("QA_Stress_" + name)
    vertices = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    faces = [(0, 1, 2), (0, 2, 3)]
    invalid = name in CASES[:9] or name == "clipped_raw"
    extra = {}
    if name.startswith("dense_") or name == "repeated_edits":
        grid(mesh, {"dense_250k": 500, "dense_1m": 1000, "repeated_edits": 100}[name])
    elif name.startswith("clipped_"):
        extra["degenerate_clipped_faces"] = clipped(mesh, name == "clipped_repaired")
    else:
        if name.startswith("repeated_"):
            faces[0] = {"repeated_adjacent": (0, 1, 2, 2, 3),
                        "repeated_middle": (0, 1, 2, 0, 3),
                        "repeated_closing": (0, 1, 2, 3, 0)}[name]
        elif name == "duplicate_faces":
            faces = [(0, 1, 2), (0, 1, 2)]
        elif name == "empty":
            vertices, faces = [], []
        elif name == "wire":
            faces = []
        elif name == "loose_vertices":
            vertices += [(3, 3, 3)]
        elif name == "coincident_vertices":
            vertices[1] = vertices[0]
        elif name == "zero_area":
            vertices = [(i, 0, 0) for i in range(4)]
        elif name == "non_manifold":
            vertices += [(.5, .5, 1), (.5, .5, -1)]
            faces = [(0, 1, 2), (1, 0, 4), (0, 1, 5)]
        elif name == "concave_ngon":
            vertices = [(0, 0, 0), (2, 0, 0), (1, .5, 0), (2, 2, 0), (0, 2, 0)]
            faces = [tuple(range(5))]
        elif name == "large_ngon":
            vertices = [(math.cos(i * math.tau / 4096), math.sin(i * math.tau / 4096), 0)
                        for i in range(4096)]
            faces = [tuple(range(4096))]
        mesh.from_pydata(vertices, [(0, 1), (1, 2)] if name == "wire" else [], faces)
        # Mutate raw arrays after constructing valid edge/corner storage, avoiding
        # a different crash in from_pydata before the conversion under test.
        if name == "self_edge":
            mesh.edges[0].vertices = (0, 0)
        elif name == "bad_edge_index":
            mesh.edges[0].vertices = (0, 99)
        elif name == "bad_corner_index":
            mesh.loops[0].vertex_index = 99
        elif name == "nan_vertex":
            mesh.vertices[0].co.x = float("nan")
        elif name == "wrong_corner_edge":
            mesh.loops[0].edge_index = (mesh.loops[0].edge_index + 1) % len(mesh.edges)
    return mesh, invalid, extra


def digest(mesh):
    result = hashlib.sha256()
    for data, prop, width, dtype in (
        (mesh.vertices, "co", 3, np.float32), (mesh.edges, "vertices", 2, np.int32),
        (mesh.loops, "vertex_index", 1, np.int32), (mesh.loops, "edge_index", 1, np.int32),
        (mesh.polygons, "loop_start", 1, np.int32), (mesh.polygons, "loop_total", 1, np.int32),
    ):
        values = np.empty(len(data) * width, dtype=dtype)
        data.foreach_get(prop, values)
        result.update(values.tobytes())
    return result.hexdigest()


def run_case(name):
    assert name in CASES
    count = len(bpy.data.meshes)
    mesh, invalid, extra = build(name)
    before = digest(mesh)
    iterations = 40 if name == "repeated_edits" else 1
    executor = ScriptExecutor()
    try:
        initial_faces = len(mesh.polygons)
        script = f'''import bpy, bmesh
mesh = bpy.data.meshes[{mesh.name!r}]
for step in range({iterations}):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bad = [f for i, f in enumerate(bm.faces) if i % 17 == 0]
        bmesh.ops.delete(bm, geom=bad, context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.normal_update()
        bm.to_mesh(mesh)
    finally:
        bm.free()
__RESULT__ = {{'faces': len(mesh.polygons), 'verts': len(mesh.vertices)}}
'''
        start = time.perf_counter()
        response = executor.execute(script, push_undo=False)
        elapsed = time.perf_counter() - start
        if invalid:
            assert not response.success and "Invalid mesh topology" in response.error, response.to_dict()
            assert digest(mesh) == before, "rejection changed the source geometry"
        else:
            assert response.success, response.to_dict()
            assert len(mesh.polygons) <= initial_faces
            assert not mesh.validate(clean_customdata=False), "cleanup produced invalid topology"
        assert len(bpy.data.meshes) == count + 1, "validation copy leaked"
        followup = executor.execute("__RESULT__ = {'responsive': True}", push_undo=False)
        assert followup.success and followup.return_value["responsive"]
        return dict(case=name, outcome="refused" if invalid else "completed", seconds=elapsed,
                    initial_faces=initial_faces, remaining_faces=len(mesh.polygons),
                    iterations=iterations, **extra)
    finally:
        bpy.data.meshes.remove(mesh)


def unguarded_repro():
    """Intentionally hangs the old path; ONLY a disposable, deadline-bound child."""
    import os
    import bmesh
    assert bpy.app.background and os.environ.get("MIXAR_QA_UNGUARDED_REPRO") == "1"
    mesh, _, _ = build("clipped_raw")
    print("BASELINE created", len(mesh.polygons), "faces", flush=True)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    print("BASELINE imported; entering delete", flush=True)
    bmesh.ops.delete(bm, geom=[f for i, f in enumerate(bm.faces) if i % 17 == 0], context="FACES")
    bm.free()
    print("BASELINE complete", flush=True)
