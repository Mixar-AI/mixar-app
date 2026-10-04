# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native geometry acceptance for remaining generation stalls; no workers."""
import math
import time

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

from mixar.modules.common.agent_execution import mesh_ops, terrain_ops
from mixar.modules.common.agent_execution.boolean_prepare import oriented_copy


def topology(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        return {'faces': len(bm.faces), 'volume': bm.calc_volume(signed=True),
                'nonmanifold': sum(not e.is_manifold for e in bm.edges),
                'bad_winding': sum(not e.is_contiguous for e in bm.edges)}
    finally:
        bm.free()


def strap(build):
    target, cutters = build()
    original = topology(target.data)
    positions = mesh_ops.read_positions(target.data)
    # Exact on the correctly oriented same surface is the geometric reference.
    baseline = target.copy()
    baseline.data = oriented_copy(target.data)
    baseline.name = 'QA_Exact_Strap'
    assert baseline.data is not None
    assert np.array_equal(positions, mesh_ops.read_positions(baseline.data))
    bpy.context.scene.collection.objects.link(baseline)
    bpy.context.view_layer.update()
    unchanged = [(c.matrix_world.copy(), mesh_ops.read_positions(c.data)) for c in cutters]
    start = time.perf_counter()
    exact = mesh_ops.boolean_difference(baseline, cutters, solver='EXACT')
    exact['seconds'] = time.perf_counter() - start
    start = time.perf_counter()
    fast = mesh_ops.boolean_difference(target, cutters)
    fast['seconds'] = time.perf_counter() - start
    actual, expected = topology(target.data), topology(baseline.data)
    assert fast['solver'] == 'MANIFOLD' and fast['winding_repaired'], fast
    assert actual['nonmanifold'] == actual['bad_winding'] == 0, actual
    assert math.isclose(actual['volume'], expected['volume'], rel_tol=2e-4), (actual, expected)
    bpy.context.view_layer.update()
    holes = []
    for cutter, (matrix, coords) in zip(cutters, unchanged):
        assert cutter.matrix_world == matrix
        assert np.array_equal(coords, mesh_ops.read_positions(cutter.data))
        axis = (cutter.matrix_world.to_3x3() @ Vector((0,0,1))).normalized()
        center = cutter.matrix_world.translation
        clear = not target.ray_cast(center - axis * .005, axis, distance=.01)[0]
        # Adjacent leather remains: a true hole, not a vanished strap.
        beside = target.ray_cast(center + Vector((.0012,0,0)) - axis*.005, axis, distance=.01)[0]
        assert clear and beside, (clear, beside)
        holes.append({'through': clear, 'leather_beside': bool(beside)})
        cutter.hide_render = True
        cutter.hide_set(True)
    baseline.hide_render = True
    baseline.hide_set(True)
    assert not any(o.name.startswith('_MixarBooleanOperand') for o in bpy.data.objects)
    return {'exact': exact, 'auto': fast, 'before': original, 'after': actual,
            'exact_after': expected, 'holes': holes, 'installed_module': mesh_ops.__file__}


def terrain():
    n = 120
    verts = [(x/n*20-10, y/n*20-10, .4*math.sin(x/10)*math.cos(y/12))
             for y in range(n+1) for x in range(n+1)]
    faces = [(y*(n+1)+x, y*(n+1)+x+1, (y+1)*(n+1)+x+1, (y+1)*(n+1)+x)
             for y in range(n) for x in range(n)]
    mesh = bpy.data.meshes.new('QA_Terrain'); mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new('QA_Terrain', mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (2,-1,3)
    obj.scale = (1.4,.8,1.2)
    obj.rotation_euler = (.1,.15,.2)
    mod = obj.modifiers.new('Surface', 'SUBSURF'); mod.levels = 1
    origins = [(2+math.sin(i*.91)*6, -1+math.cos(i*.67)*4, 12) for i in range(128)]
    created = []
    def place(point):
        item = bpy.data.objects.new('QA_Placement', None)
        created.append(item)
        bpy.context.scene.collection.objects.link(item)
        item.location = point
    def single(row):
        graph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(graph)
        matrix = evaluated.matrix_world
        inv = matrix.inverted()
        direction = inv.to_3x3() @ Vector((0,0,-1))
        hit, point, normal, _ = evaluated.ray_cast(inv @ Vector(row), direction)
        assert hit
        return tuple(matrix @ point), tuple((inv.to_3x3().transposed() @ normal).normalized())
    start = time.perf_counter()
    expected = []
    for row in origins:
        point, normal = single(row)
        expected.append((point,normal)); place(point)
    slow = time.perf_counter()-start
    for item in created: bpy.data.objects.remove(item,do_unlink=True)
    created.clear()
    start = time.perf_counter()
    hits = terrain_ops.raycast_terrain(obj, origins)
    for hit in hits: place(hit['position'])
    fast = time.perf_counter()-start
    error = max(abs(a-b) for hit,(point,normal) in zip(hits,expected)
                for a,b in zip((*hit['position'],*hit['normal']),(*point,*normal)))
    assert error < 1e-5, error
    assert terrain_ops.raycast_terrain(obj, [(1e5,1e5,12)]) == [None]
    assert terrain_ops.raycast_terrain(obj, origins[:1], distance=.1) == [None]
    for rows in ([], origins+[origins[0]], [(float('nan'),0,1)]):
        try: terrain_ops.raycast_terrain(obj, rows)
        except ValueError: pass
        else: raise AssertionError('invalid rays accepted')
    for item in created: bpy.data.objects.remove(item,do_unlink=True)
    return {'interleaved_seconds':slow,'batched_seconds':fast,'count':len(hits),
            'max_error':error,'installed_module':terrain_ops.__file__}
