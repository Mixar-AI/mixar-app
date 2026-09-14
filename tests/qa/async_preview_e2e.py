#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native GUI render lifecycle through the real script sandbox; no paid calls.

Run on an isolated authoring QA instance with QA_HARNESS, MIXAR_QA_PORT,
MIXAR_BACKEND and a fresh QA_SCENARIO_OUT. Replaces the QA instance's scene.
Uses the backend's actual generated START/POLL transport scripts.
"""
import base64
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, os.environ['MIXAR_BACKEND'])
from lib import ScenarioFail, run_scenario
from modules.agent_next.render_job import request_script

SETUP = """
import bpy
from mathutils import Vector
for obj in list(bpy.context.scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, location=(0,0,1))
obj = bpy.context.object
obj.name = 'Preview_QA_Sphere'
mat = bpy.data.materials.new('Preview_QA_Blue')
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Base Color'].default_value = (.03,.15,.8,1)
bsdf.inputs['Roughness'].default_value = .3
obj.data.materials.append(mat)
for polygon in obj.data.polygons:
    polygon.use_smooth = True
bpy.ops.mesh.primitive_plane_add(size=200)
bpy.context.object.name = 'Preview_QA_Ground'
bpy.ops.object.camera_add(location=(5,-7,4))
camera = bpy.context.object
camera.rotation_euler = (Vector((0,0,1))-camera.location).to_track_quat('-Z','Y').to_euler()
bpy.context.scene.camera = camera
bpy.ops.object.light_add(type='AREA', location=(2,-3,6))
light = bpy.context.object
light.data.energy = 1200
light.data.size = 4
light.rotation_euler = (Vector((0,0,0))-light.location).to_track_quat('-Z','Y').to_euler()
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 64
scene.render.resolution_x = 1200
scene.render.resolution_y = 900
scene.render.resolution_percentage = 80
scene.render.use_lock_interface = False
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.region_3d.view_perspective = 'CAMERA'
result = True
"""


def require(condition, message):
    if not condition:
        raise ScenarioFail(message)


def script(qa, code):
    value = qa.eval('from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor\n'
                    f'result=ScriptExecutor().execute({code!r}, push_undo=False).to_dict()')
    require(value.get('success'), f'Sandbox failure: {value}')
    return value


def request(qa, key, action):
    return script(qa, request_script(key, action))


def settings(qa):
    return qa.eval("s=bpy.context.scene; result=[s.render.resolution_x, "
                   "s.render.resolution_y,s.render.resolution_percentage,s.cycles.samples]")


def await_result(qa, key):
    deadline = time.monotonic() + 60
    ticks = []
    while time.monotonic() < deadline:
        start = time.monotonic()
        running = qa.eval("result=bpy.app.is_job_running('RENDER')")
        ticks.append({'rendering': running, 'seconds': time.monotonic() - start})
        value = request(qa, key, 'POLL')
        if value.get('status') != 'running':
            return value, ticks
        time.sleep(.15)
    raise ScenarioFail('Render did not settle within 60 seconds')


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=False)
    qa.eval(SETUP)
    original = settings(qa)
    evidence = {}
    key = uuid.uuid4().hex
    start = time.monotonic()
    require(request(qa, key, 'START')['status'] == 'running', 'Not asynchronous')
    evidence['start_seconds'] = time.monotonic() - start
    require(request(qa, key, 'START')['status'] == 'running', 'Duplicate kickoff restarted')
    require(request(qa, uuid.uuid4().hex, 'START')['status'] == 'busy', 'Second render accepted')
    # Exercise native event dispatch while rendering: open the viewport sidebar.
    qa.cmd('focus_area', area='VIEW_3D')
    before = qa.eval("result=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D').spaces.active.show_region_ui")
    qa.press('N')
    qa.wait("next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D').spaces.active.show_region_ui != " + repr(before), timeout=3)
    qa.snap(str(out / 'during-render.png'))
    result, ticks = await_result(qa, key)
    require(result['status'] == 'done', f'No final image: {result.get("status")}')
    (out / 'preview.png').write_bytes(base64.b64decode(result.pop('image_url').split(',', 1)[1]))
    evidence['completion'] = result
    evidence['main_loop_ticks'] = ticks
    require(settings(qa) == original, 'Preview settings not restored')
    # A later viewport edit must invalidate an already completed image.
    script(qa, "import bpy\nbpy.data.objects['Preview_QA_Sphere'].location.x += .1")
    later = request(qa, key, 'POLL')
    require(later['status'] == 'stale' and 'image_url' not in later, 'Old image survived an edit')
    evidence['after_completion_edit'] = later
    # An actual sandbox edit during the native job is allowed, but its image is stale.
    key = uuid.uuid4().hex
    require(request(qa, key, 'START')['status'] == 'running', 'Second lifecycle failed')
    require(qa.eval("result=bpy.app.is_job_running('RENDER')"), 'Render ended before edit test')
    start = time.monotonic()
    script(qa, "import bpy\nbpy.data.objects['Preview_QA_Sphere'].location.x += .2\n"
               "bpy.context.scene.cycles.samples = 48")
    evidence['edit_during_render_seconds'] = time.monotonic() - start
    stale, _ = await_result(qa, key)
    require(stale['status'] == 'stale' and 'image_url' not in stale, f'Edit not detected: {stale}')
    require(settings(qa) == [1200, 900, 80, 48], 'User setting was overwritten during restore')
    evidence['during_render_edit'] = stale
    # The native status-bar Stop control cancels the background job.
    key = uuid.uuid4().hex
    require(request(qa, key, 'START')['status'] == 'running', 'Cancellation kickoff failed')
    qa.wait("any(w.get('tip')=='Stop this job' for w in drv.find())", timeout=2)
    button = qa.eval("result=next({k:v for k,v in w.items() if not k.startswith('_')} "
                     "for w in drv.find() if w.get('tip')=='Stop this job')")
    qa.cmd('click_xy', window=button['window'], x=button['center'][0], y=button['center'][1])
    cancelled, _ = await_result(qa, key)
    require(cancelled['status'] == 'cancelled', f'Native cancellation failed: {cancelled.get("status")}')
    require(settings(qa) == [1200, 900, 80, 48], 'Cancel did not restore settings')
    require('image_url' not in cancelled, 'Cancelled pixels were delivered')
    evidence['cancelled'] = cancelled
    qa.snap(str(out / 'after-cancel.png'))
    (out / 'evidence.json').write_text(json.dumps(evidence, indent=2))
    return {'evidence': str(out), 'backend_calls': 0, **evidence}


if __name__ == '__main__':
    run_scenario('async_preview_e2e', run)
