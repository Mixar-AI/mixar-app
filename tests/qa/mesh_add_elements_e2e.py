# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Adding edges/loops/faces to a big existing mesh: no backend, no credits.

Replays mixar-backend#1858: an agent script grew a 47,466-corner mesh with
`mesh.loops.add(n)` and the app died in ED_mesh_loops_add ->
fill_attribute_range_default -> fill_segment. At our Blender pin the edge,
corner and face helpers filled `[old_size, n)` instead of `[old_size,
old_size + n)` (the overlay of src/source/blender/editors/mesh/mesh_data.cc
backports upstream 56a6f5b4ac). Here a >50k-corner UV sphere gets
`loops.add(3)`, `edges.add(2)`, `polygons.add(1)` from Python; the app must
survive, every new value (`.corner_vert`, `.corner_edge`, UVs, edge vertices,
material index, custom EDGE/CORNER/FACE attributes) must be 0 and every
existing value unchanged. The new face is then wired up, the mesh validated,
linked and drawn, and the main loop must still answer.

QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT select harness, app and evidence.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

NAME = 'QA_MeshAddRange'

PROBE = f'''
import os, bmesh
import numpy as np
assert os.environ.get('MIXAR_QA') == '1'
NAME = {NAME!r}
for o in [o for o in bpy.data.objects if o.name.startswith(NAME)]:
    bpy.data.objects.remove(o)
for m in [m for m in bpy.data.meshes if m.name.startswith(NAME)]:
    bpy.data.meshes.remove(m)

me = bpy.data.meshes.new(NAME)
bm = bmesh.new()
bm.loops.layers.uv.new('UVMap')
bmesh.ops.create_uvsphere(bm, u_segments=256, v_segments=128, radius=1.0, calc_uvs=True)
bm.to_mesh(me)
bm.free()
for domain in ('EDGE', 'CORNER', 'FACE'):
    attr = me.attributes.new('qa_' + domain.lower(), 'FLOAT', domain)
    attr.data.foreach_set('value', np.full(len(attr.data), 7.0, dtype=np.float32))

def read(coll, prop, width=1, dtype=np.int32):
    buf = np.empty(len(coll) * width, dtype=dtype)
    coll.foreach_get(prop, buf)
    return buf.reshape(-1, width) if width > 1 else buf

def snapshot():
    return {{'corner_vert': read(me.loops, 'vertex_index'),
             'corner_edge': read(me.loops, 'edge_index'),
             'uv': read(me.uv_layers[0].data, 'uv', 2, np.float32),
             'edge_verts': read(me.edges, 'vertices', 2),
             'material_index': read(me.polygons, 'material_index'),
             'qa_edge': read(me.attributes['qa_edge'].data, 'value', dtype=np.float32),
             'qa_corner': read(me.attributes['qa_corner'].data, 'value', dtype=np.float32),
             'qa_face': read(me.attributes['qa_face'].data, 'value', dtype=np.float32)}}

old_e, old_l, old_f = len(me.edges), len(me.loops), len(me.polygons)
assert old_l > 50000, old_l
before = snapshot()

me.loops.add(3)
me.edges.add(2)
me.polygons.add(1)

sizes = (len(me.edges), len(me.loops), len(me.polygons))
assert sizes == (old_e + 2, old_l + 3, old_f + 1), sizes
after = snapshot()
bad = []
for key, arr in after.items():
    n = len(before[key])
    if not np.array_equal(arr[:n], before[key]):
        bad.append(key + ': existing values changed')
    if np.any(arr[n:]):
        bad.append(key + ': new values ' + repr(arr[n:].tolist()))
assert not bad, bad

# Wire the new face to the three new corners (loops.add moved the old last
# face's end onto them) and make the mesh drawable.
me.polygons[old_f].loop_start = old_l
me.loops.foreach_set('vertex_index', np.concatenate([after['corner_vert'][:old_l],
                                                     np.array([0, 1, 2], dtype=np.int32)]))
me.update(calc_edges=True)
me.validate(verbose=False)
obj = bpy.data.objects.new(NAME, me)
drv.main_window().scene.collection.objects.link(obj)
drv.main_window().view_layer.update()
result = {{'corners_before': old_l, 'edges_before': old_e, 'faces_before': old_f,
          'sizes_after_add': sizes, 'checked': sorted(after),
          'after_validate': (len(me.edges), len(me.loops), len(me.polygons))}}
'''

FRAME = f'''
window = drv.main_window()
obj = bpy.data.objects[{NAME!r}]
with bpy.context.temp_override(window=window):
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.view3d.view_selected()
result = True
'''

CLEANUP = f'''
for o in [o for o in bpy.data.objects if o.name.startswith({NAME!r})]:
    bpy.data.objects.remove(o)
for m in [m for m in bpy.data.meshes if m.name.startswith({NAME!r})]:
    bpy.data.meshes.remove(m)
result = True
'''


def run(qa):
    output = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mesh-add-elements-evidence')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qa.step('reset', qa.cmd, 'reset_state')
    qa.step('dismiss_splash', qa.dismiss_splash)
    try:
        probe = qa.step('add_elements_to_big_mesh', qa.cmd, 'eval', code=PROBE, _sock_timeout=120)
        # A separate request proves the main loop still runs after the adds.
        alive = qa.step('main_loop_responsive', qa.eval,
                        f"result = len(bpy.data.objects[{NAME!r}].data.loops)")
        if alive != probe['after_validate'][1]:
            raise ScenarioFail(f'mesh changed between requests: {alive} != {probe}')
        qa.step('frame_mesh', qa.eval, FRAME)
        qa.step('viewport', qa.cmd, 'snap', path=str(output / 'mesh-add-elements.png'), area='VIEW_3D')
    finally:
        qa.step('cleanup', qa.eval, CLEANUP)
    return {'probe': probe, 'output': str(output)}


if __name__ == '__main__':
    run_scenario('mesh_add_elements', run)
