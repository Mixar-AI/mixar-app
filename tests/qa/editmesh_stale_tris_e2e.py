#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""An agent script grows an edit-mode BMesh, then raises before update_edit_mesh.

Replays the 4.4.0 Windows crash (extract_tris_bmesh <- extract_mesh_ibo_tris.cc:81)
through the REAL ScriptExecutor: the script enters Edit Mode on a 12-triangle
cube, subdivides it to ~20k triangles through bmesh.from_edit_mesh and raises.
The draw cache is then rebuilt from the edit mesh's cached loop triangles.
No backend, no credits. QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT select the
harness, the isolated QA app and the evidence folder.

Stale-state readout: the status-bar statistics in Edit Mode report Faces from
the live BMesh and Tris from the cached BMEditMesh.looptris (info_stats.cc,
stats_object_edit); bm.calc_loop_triangles() gives the true count. A mesh's
loop_triangles reads the original Mesh, which Edit Mode does not update, so it
cannot show the stale cache.

- Unfixed build: the next redraw reads past the end of the 12 cached loop
  triangles. Windows: the app dies (scenario fails with "app died"). macOS may
  survive the out-of-bounds read; then the readout fails deterministically
  with Tris:12 against ~20k fresh triangles.
- Fixed build (executor refreshes edit meshes in its `finally`): Tris equals
  the fresh count, the app survives forced redraws and the red cube draws.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

NAME = 'QA_StaleTrisCube'
STATE = 'qa_editmesh_stale_tris'
CUTS = 40  # 6 * 41^2 quads = 20172 triangles from a 12-triangle cache

# What the agent sent: no update_edit_mesh, because the script failed first.
SCRIPT = f'''import bpy, bmesh
obj = bpy.data.objects[{NAME!r}]
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(obj.data)
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts={CUTS}, use_grid_fill=True)
raise RuntimeError('agent script failed before update_edit_mesh')
'''

VIEW = '''
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
'''

SETUP = VIEW + f'''
import os, bmesh
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA app'
with bpy.context.temp_override(window=win):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
old = bpy.data.objects.get({NAME!r})
if old:
    mesh = old.data
    bpy.data.objects.remove(old, do_unlink=True)
    bpy.data.meshes.remove(mesh)
mesh = bpy.data.meshes.new({NAME!r})
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new({NAME!r}, mesh)
obj.color = (1.0, 0.0, 0.0, 1.0)
win.scene.collection.objects.link(obj)
space = area.spaces.active
# Exactly what RESTORE puts back: only the objects hidden here, the view settings.
saved = bpy.app.driver_namespace[{STATE!r}] = {{
    'hidden': [o.name for o in win.scene.objects
               if o != obj and not o.hide_get(view_layer=win.view_layer)],
    'shading': (space.shading.type, space.shading.color_type),
    'overlays': space.overlay.show_overlays}}
with bpy.context.temp_override(window=win, area=area, region=region):
    for other in win.scene.objects:
        other.select_set(False)
    for name in saved['hidden']:
        win.scene.objects[name].hide_set(True)
    obj.select_set(True)
    win.view_layer.objects.active = obj
    space.shading.type = 'SOLID'
    space.shading.color_type = 'OBJECT'
    space.overlay.show_overlays = False
    bpy.ops.view3d.view_axis(type='FRONT')
    bpy.ops.view3d.view_selected()
result = len(mesh.polygons)
'''

RUN = f'''
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
with bpy.context.temp_override(window=drv.main_window()):
    reply = ScriptExecutor().execute({SCRIPT!r})
result = {{'success': reply.success, 'error': reply.error}}
'''

# The select_set notifier makes the next main-loop pass drop the cached stats.
READOUT = VIEW + f'''
import bmesh, re
obj = bpy.data.objects[{NAME!r}]
with bpy.context.temp_override(window=win):
    obj.select_set(True)
text = win.scene.statistics(win.view_layer)
faces = re.search(r'Faces:[0-9,]+/([0-9,]+)', text)
tris = re.search(r'Tris:([0-9,]+)', text)
bm = bmesh.from_edit_mesh(obj.data)
result = {{'mode': obj.mode, 'stats': text, 'faces_live': len(bm.faces),
          'faces_stats': int(faces.group(1).replace(',', '')) if faces else None,
          'tris_cached': int(tris.group(1).replace(',', '')) if tris else None,
          'tris_fresh': len(bm.calc_loop_triangles())}}
'''

REDRAW = VIEW + '''
with bpy.context.temp_override(window=win, area=area, region=region):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=5)
result = True
'''

RED_PIXELS = '''
import numpy as np
image = bpy.data.images.load({path!r}, check_existing=False)
try:
    px = np.empty(image.size[0] * image.size[1] * 4, np.float32)
    image.pixels.foreach_get(px)
finally:
    bpy.data.images.remove(image)
r, g, b = px[0::4], px[1::4], px[2::4]
result = float(np.mean((r > 0.15) & (g < 0.5 * r) & (b < 0.5 * r)))
'''

RESTORE = VIEW + f'''
saved = bpy.app.driver_namespace.pop({STATE!r}, None)
obj = bpy.data.objects.get({NAME!r})
with bpy.context.temp_override(window=win, area=area, region=region):
    if obj is not None:
        if obj.mode != 'OBJECT':
            win.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='OBJECT')
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    if saved:
        space = area.spaces.active
        space.shading.type, space.shading.color_type = saved['shading']
        space.overlay.show_overlays = saved['overlays']
        for name in saved['hidden']:
            other = win.scene.objects.get(name)
            if other is not None:
                other.hide_set(False)
result = True
'''


def send(qa, step, cmd, **args):
    try:
        return qa.step(step, qa.cmd, cmd, **args)
    except TimeoutError as exc:  # a hung or still-busy app is not a dead one
        raise ScenarioFail(f'{step} timed out: app hung or still busy ({exc})') from exc
    except (ConnectionError, ScenarioFail) as exc:
        if isinstance(exc, ScenarioFail) and 'connection closed' not in str(exc):
            raise
        raise ScenarioFail(f'app died at {step}: {exc}') from exc


def call(qa, step, code, **kw):
    return send(qa, step, 'eval', code=code, **kw)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/editmesh-stale-tris'))
    out.mkdir(parents=True, exist_ok=True)
    finished = False
    try:
        verdict = check(qa, out)
        finished = True
        return verdict
    finally:
        try:
            call(qa, 'restore', RESTORE, _sock_timeout=30)
        except Exception:
            if finished:  # never mask the check's own failure (or a dead app)
                raise


def check(qa, out):
    assert call(qa, 'setup_cube', SETUP) == 6
    reply = call(qa, 'agent_script_raises', RUN, _sock_timeout=60)
    assert reply['success'] is False and 'update_edit_mesh' in (reply['error'] or ''), reply
    deadline = time.monotonic() + 10
    while True:
        state = call(qa, 'readout', READOUT)
        if state['faces_stats'] == state['faces_live'] or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert state['mode'] == 'EDIT', state
    assert state['faces_stats'] == state['faces_live'] == 6 * (CUTS + 1) ** 2, state
    if state['tris_cached'] != state['tris_fresh']:
        raise ScenarioFail(f"stale loop triangles: cached {state['tris_cached']}, "
                           f"fresh {state['tris_fresh']}")
    call(qa, 'forced_redraw', REDRAW, _sock_timeout=60)
    assert call(qa, 'alive_after_redraw', 'result=True', _sock_timeout=10)
    path = str(out / 'editmesh-viewport.png')
    send(qa, 'snap', 'snap', path=path, area='VIEW_3D', _sock_timeout=60)
    red = call(qa, 'mesh_draws', RED_PIXELS.format(path=path))
    assert red > 0.05, f'red cube covers only {red:.1%} of the viewport'
    return {'agent_reply': reply, 'readout': state, 'red_fraction': red, 'evidence': path}


if __name__ == '__main__':
    run_scenario('editmesh_stale_tris', run)
