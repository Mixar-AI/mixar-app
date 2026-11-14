# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free headless replay of built-in Gaussian splats: Mixar --background --factory-startup --python this_file.

Covers, inside the real app with no backend and no credits:
  * .spz and raw .ply import as one built-in splat each, oriented as before;
  * a PLY without 3DGS fields is refused and leaves nothing behind;
  * EEVEE, Cycles and Workbench F12 draw the splat; hide_render removes it;
  * deleting a world's splat removes its hidden collider;
  * a KIRI-era world (raw point mesh + KIRI modifier, duplicate source mesh,
    proxy Empty, forced Lock Interface) converts to one built-in splat in place.

Writes renders and result.json to QA_SCENARIO_OUT (default /tmp/mixar-native-splats).
"""
import gzip
import json
import math
import os
import pathlib
import struct
import traceback

import bpy
import numpy as np
from mathutils import Vector

from mixar.modules.moodboard.core import splat_lifecycle, splat_legacy, splat_native
from mixar.modules.moodboard.core.splat_import import import_splat_file

out = pathlib.Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-native-splats'))
out.mkdir(parents=True, exist_ok=True)
results = {}


def check(name, fn):
    try:
        results[name] = {'ok': True, 'detail': fn()}
    except Exception as exc:  # noqa: BLE001 - report every case
        results[name] = {'ok': False, 'detail': repr(exc), 'trace': traceback.format_exc()}


def reset():
    bpy.ops.wm.read_homefile(use_empty=True)


def spz_bytes(positions):
    """A degree-0 SPZ v2 with the given positions (file frame)."""
    n, frac = len(positions), 12
    head = struct.pack('<III BBBB', 0x5053474E, 2, n, 0, frac, 0, 0)

    def fixed(v):
        f = int(round(v * (1 << frac))) & 0xFFFFFF
        return bytes((f & 0xFF, (f >> 8) & 0xFF, (f >> 16) & 0xFF))
    pos = b''.join(fixed(c) for p in positions for c in p)
    alpha = bytes([255] * n)
    color = bytes([200, 120, 60] * n)
    scale = bytes([int((-3.0 + 10.0) * 16)] * 3 * n)
    rot = bytes([128] * 3 * n)
    return gzip.compress(head + pos + alpha + color + scale + rot)


def raw_ply(path, positions, splat=True):
    names = ['x', 'y', 'z']
    if splat:
        names += ['f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity', 'scale_0', 'scale_1', 'scale_2',
                  'rot_0', 'rot_1', 'rot_2', 'rot_3']
    rows = []
    for p in positions:
        rows.append(list(p) + ([1.0, 0.2, 0.1, 4.0, -3.0, -3.0, -3.0, 1.0, 0.0, 0.0, 0.0]
                               if splat else []))
    data = np.array(rows, dtype='<f4')
    head = ('ply\nformat binary_little_endian 1.0\nelement vertex %d\n' % len(rows)
            + ''.join('property float %s\n' % k for k in names) + 'end_header\n')
    pathlib.Path(path).write_bytes(head.encode() + data.tobytes())


def world_points(obj):
    attr = obj.data.attributes['position']
    co = np.empty(len(attr.data) * 3, dtype=np.float32)
    attr.data.foreach_get('vector', co)
    mw = obj.matrix_world
    return [tuple(round(c, 2) for c in mw @ Vector(co[i:i + 3])) for i in range(0, len(co), 3)]


def lit_pixels(path):
    img = bpy.data.images.load(str(path))
    try:
        px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
        return int((px[:, :3].max(axis=1) > 0.05).sum())
    finally:
        bpy.data.images.remove(img)


def render(tag, engine):
    sc = bpy.context.scene
    if sc.camera is None:
        cam = bpy.data.objects.new('QA_Cam', bpy.data.cameras.new('QA_Cam'))
        sc.collection.objects.link(cam)
        cam.location = (0.0, -6.0, 0.0)
        cam.rotation_euler = (math.radians(90), 0.0, 0.0)
        sc.camera = cam
    if sc.world is None:
        sc.world = bpy.data.worlds.new('QA_World')
    sc.world.color = (0.0, 0.0, 0.0)
    tree = getattr(sc.world, 'node_tree', None)
    background = tree.nodes.get('Background') if tree else None
    if background is not None:
        background.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
    sc.render.resolution_x, sc.render.resolution_y = 160, 120
    sc.render.engine = engine
    if engine == 'CYCLES':
        sc.cycles.samples = 4
        sc.cycles.device = 'CPU'
    path = out / f'{tag}.png'
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return lit_pixels(path)


def case_spz_import():
    reset()
    spz = out / 'marker.spz'
    spz.write_bytes(spz_bytes([(0, 1, 0), (1, 0, 0), (0, 0, -1)]))
    names = import_splat_file(str(spz), recenter=False)
    objs = [bpy.data.objects[n] for n in names]
    assert len(objs) == 1 and splat_native.is_splat(objs[0]), names
    splat = objs[0]
    assert splat['wl_role'] == 'splat'
    assert splat.users_collection[0].get('mixar_splat_world') is True
    # Converted SPZ keeps the validated Marble orientation (+90 X on the
    # y-up converted frame): file +Y lands on -Z, file -Z on -Y.
    pts = world_points(splat)
    assert pts == [(0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)], pts
    assert bpy.context.view_layer.objects.active == splat
    return {'points': pts}


def case_raw_ply_import():
    reset()
    ply = out / 'raw.ply'
    raw_ply(ply, [(0, 1, 0), (1, 0, 0)])
    names = import_splat_file(str(ply), recenter=False)
    splat = bpy.data.objects[names[0]]
    assert splat_native.is_splat(splat)
    assert tuple(round(math.degrees(a)) for a in splat.rotation_euler) == (-90, 0, 0)
    return {'points': world_points(splat)}


def case_non_splat_ply_refused():
    reset()
    ply = out / 'mesh.ply'
    raw_ply(ply, [(0, 0, 0), (1, 0, 0)], splat=False)
    before = (len(bpy.data.objects), len(bpy.data.collections))
    try:
        import_splat_file(str(ply), recenter=False)
    except ValueError as exc:
        after = (len(bpy.data.objects), len(bpy.data.collections))
        assert after == before, (before, after)
        return {'error': str(exc)}
    raise AssertionError('a mesh PLY was accepted as a splat')


def case_renders():
    reset()
    ply = out / 'cloud.ply'
    rng = np.random.default_rng(0)
    raw_ply(ply, [tuple(p) for p in rng.uniform(-1, 1, (300, 3))])
    names = import_splat_file(str(ply), recenter=False)
    splat = bpy.data.objects[names[0]]
    lit = {e: render(f'render_{e.lower()}', e)
           for e in ('BLENDER_EEVEE', 'CYCLES', 'BLENDER_WORKBENCH')}
    assert all(v > 200 for v in lit.values()), lit
    splat.hide_render = True
    lit['hidden'] = render('render_hidden', 'BLENDER_EEVEE')
    assert lit['hidden'] == 0, lit
    return lit


def case_delete_purges_collider():
    reset()
    ply = out / 'world.ply'
    raw_ply(ply, [(0, 0, 0), (1, 1, 1)])
    names = import_splat_file(str(ply), recenter=False)
    splat = bpy.data.objects[names[0]]
    coll = splat.users_collection[0]
    coll_name = coll.name
    collider = bpy.data.objects.new('QA_Collider', bpy.data.meshes.new('QA_Collider'))
    collider['wl_role'] = 'collider'
    coll.objects.link(collider)
    splat_lifecycle.note_splats_imported()
    bpy.data.objects.remove(splat, do_unlink=True)
    splat_lifecycle._check_splats()
    assert bpy.data.objects.get('QA_Collider') is None
    assert bpy.data.collections.get(coll_name) is None
    return 'collider and collection removed'


def kiri_world():
    """A KIRI-era world as Mixar's 5.2 importer left it in a saved file."""
    coll = bpy.data.collections.new('WorldLabs_Old')
    bpy.context.scene.collection.children.link(coll)
    rng = np.random.default_rng(1)
    n = 400
    pos = rng.uniform(-1, 1, (n, 3)).astype(np.float32)

    def mesh_obj(name):
        me = bpy.data.meshes.new(name)
        me.vertices.add(n)
        me.vertices.foreach_set('co', pos.ravel())
        for key, val in (('f_dc_0', 1.0), ('f_dc_1', 0.3), ('f_dc_2', 0.1), ('opacity', 4.0),
                         ('scale_0', -3.0), ('scale_1', -3.0), ('scale_2', -3.0),
                         ('rot_0', 1.0), ('rot_1', 0.0), ('rot_2', 0.0), ('rot_3', 0.0)):
            me.attributes.new(key, 'FLOAT', 'POINT').data.foreach_set('value', [val] * n)
        for i in range(9):
            me.attributes.new(f'f_rest_{i}', 'FLOAT', 'POINT').data.foreach_set('value', [0.0] * n)
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        ob.rotation_euler = (math.radians(90), 0.0, 0.0)
        ob.location = (0.5, 0.0, 0.25)
        ob['wl_role'] = 'splat'
        return ob

    splat = mesh_obj('Old_Splat')
    group = bpy.data.node_groups.new('KIRI_3DGS_Render_GN', 'GeometryNodeTree')
    splat.modifiers.new('KIRI_3DGS_Render_GN', 'NODES').node_group = group
    splat.hide_set(True)
    splat.hide_render = True
    source = mesh_obj('Old_SplatSource')
    source.hide_set(True)
    proxy = bpy.data.objects.new('Old_SplatProxy', None)
    proxy['is_gaussian_splat'] = True
    proxy['wl_role'] = 'proxy'
    coll.objects.link(proxy)
    collider = bpy.data.objects.new('Old_Collider', bpy.data.meshes.new('Old_Collider'))
    collider['wl_role'] = 'collider'
    coll.objects.link(collider)
    bpy.context.scene.render.use_lock_interface = True
    return splat.matrix_world.copy()


def case_kiri_file_converts():
    reset()
    matrix = kiri_world()
    converted = splat_legacy.convert_kiri_splats()
    assert [o.name for o in converted] == ['Old_Splat'], converted
    splat = converted[0]
    assert splat_native.is_splat(splat)
    assert all(abs(a - b) < 1e-4
               for ra, rb in zip(splat.matrix_world, matrix) for a, b in zip(ra, rb))
    for gone in ('Old_SplatSource', 'Old_SplatProxy'):
        assert bpy.data.objects.get(gone) is None, gone
    assert bpy.data.objects.get('Old_Collider') is not None
    assert bpy.data.node_groups.get('KIRI_3DGS_Render_GN') is None
    assert not bpy.context.scene.render.use_lock_interface
    assert not splat.hide_get() and not splat.hide_render  # the proxy was visible
    assert len(splat.data.points) == 400
    attrs = {a.name for a in splat.data.attributes}
    assert {'radiance:base', 'scale', 'rotation', 'radiance:sh_0', 'radiance:sh_2'} <= attrs
    assert 'radiance:sh_3' not in attrs
    lit = render('render_converted', 'BLENDER_EEVEE')
    assert lit > 200, lit
    assert splat_legacy.convert_kiri_splats() == []  # idempotent
    return {'lit': lit, 'attributes': sorted(attrs)}


for case in (case_spz_import, case_raw_ply_import, case_non_splat_ply_refused, case_renders,
             case_delete_purges_collider, case_kiri_file_converts):
    check(case.__name__, case)

(out / 'result.json').write_text(json.dumps(results, indent=2))
failed = [k for k, v in results.items() if not v['ok']]
print('NATIVE_SPLATS', 'FAIL' if failed else 'PASS', json.dumps(
    {k: (v['ok'], v['detail'] if v['ok'] else v['detail']) for k, v in results.items()}))
for k in failed:
    print(results[k]['trace'])
