#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app replay of the render → agent-callback → watch loop (no credits).

A tiny EEVEE animation is started through ``mixar.scene_render_start`` with an
``agent_ref_json`` the way the backend's ``render_scene_video`` tool passes it;
the callback sender is recorded instead of sent. When the render lands the
recorded ``generation.agent_result`` params must name the Moodboard clip, and
``moodboard.view_video`` must then sample that very clip. Requires QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

KEY = '5' * 32
REF = {'generation_id': 'gen-qa-0001', 'session_id': '', 'run_id': 'run-qa-0001',
       'task_id': '', 'worker_id': 'qa-worker', 'job_type': 'scene_render_video'}

SETUP = '''
import json, bmesh, bpy
from mathutils import Vector
from mixar.modules.common.job_queue.core import agent_results
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    if not scene.mixie_session_id:
        scene.mixie_session_id = 'qa-scene-render-callback'
    ns = bpy.app.driver_namespace
    ns.pop('qa_render_cb', None)
    ns['qa_render_restore'] = dict(engine=scene.render.engine, rx=scene.render.resolution_x,
                                   ry=scene.render.resolution_y, pct=scene.render.resolution_percentage,
                                   fs=scene.frame_start, fe=scene.frame_end, cam=scene.camera.name if scene.camera else '')
    mesh = bpy.data.meshes.new('QA_CB_Cube'); bm = bmesh.new(); bmesh.ops.create_cube(bm, size=2.0); bm.to_mesh(mesh); bm.free()
    cube = bpy.data.objects.new('QA_CB_Cube', mesh); scene.collection.objects.link(cube)
    cam_data = bpy.data.cameras.new('QA_CB_Camera'); cam = bpy.data.objects.new('QA_CB_Camera', cam_data)
    cam.location = Vector((0.0, -8.0, 0.0)); cam.rotation_euler = (1.5708, 0.0, 0.0); scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 160, 90, 100
    scene.frame_start, scene.frame_end = 1, 6
    agent_results._qa_original = agent_results.report_agent_result_params
    def _record(key, params):
        bpy.app.driver_namespace['qa_render_cb'] = {'key': key, 'params': json.loads(json.dumps(params))}
    agent_results.report_agent_result_params = _record
    ref = dict(%(ref)s); ref['session_id'] = scene.mixie_session_id
    ns.pop('mixar_scene_render_response', None)
    status = bpy.ops.mixar.scene_render_start(job_key=%(key)r, kind='video', label='QA preview',
                                              agent_ref_json=json.dumps(ref))
    receipt = dict(ns.get('mixar_scene_render_response') or {})
result = {'status': list(status), 'receipt': {k: receipt.get(k) for k in ('status', 'success', 'error')}}
'''

CLEANUP = '''
import bpy
from mixar.modules.common.job_queue.core import agent_results
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    r = bpy.app.driver_namespace.pop('qa_render_restore', {})
    if hasattr(agent_results, '_qa_original'):
        agent_results.report_agent_result_params = agent_results._qa_original; del agent_results._qa_original
    for name in ('QA_CB_Cube', 'QA_CB_Camera'):
        obj = bpy.data.objects.get(name)
        if obj: bpy.data.objects.remove(obj, do_unlink=True)
    if r:
        scene.render.engine = r['engine']; scene.render.resolution_x = r['rx']; scene.render.resolution_y = r['ry']
        scene.render.resolution_percentage = r['pct']; scene.frame_start, scene.frame_end = r['fs'], r['fe']
        scene.camera = bpy.data.objects.get(r['cam']) if r['cam'] else None
result = True
'''


def run():
    qa = QA()
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/scene-render-callback-qa'))
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    def record(case, fn):
        try:
            rows.append({'case': case, 'status': 'PASS', 'detail': fn()})
        except Exception as exc:  # noqa: BLE001
            rows.append({'case': case, 'status': 'FAIL', 'detail': repr(exc)})
        (out / 'scene-render-callback.json').write_text(json.dumps(rows, indent=2, default=str))
        print(json.dumps(rows[-1], default=str), flush=True)

    state = {}

    def start():
        started = qa.eval(SETUP % {'ref': REF, 'key': KEY})
        assert started['receipt'].get('status') == 'started', started
        return started
    record('01 render started with an agent ref', start)

    def callback():
        qa.wait("'qa_render_cb' in bpy.app.driver_namespace", timeout=180)
        cb = qa.eval("result=bpy.app.driver_namespace['qa_render_cb']")
        p = cb['params']
        assert cb['key'] == KEY and p['backend_job_id'] == KEY, cb
        assert p['status'] == 'succeeded' and p['error'] == '', p
        assert p['feature_key'] == 'scene_render' and p['job_type'] == 'scene_render_video', p
        assert p['generation_id'] == REF['generation_id'] and p['agent_ref']['run_id'] == REF['run_id'], p
        assert len(p['result_names']) == 1 and p['result_names'][0], p
        state['name'] = p['result_names'][0]
        on_board = qa.eval("import bpy\n"
                           f"img=bpy.data.images.get({state['name']!r})\n"
                           "result=bool(img) and img.source=='MOVIE' and any(i.image==img for i in drv.main_window().scene.mixie_moodboard_images)")
        assert on_board, state['name']
        return p
    record('02 finished render reports generation.agent_result naming the Moodboard clip', callback)

    def watch():
        reply = qa.eval(
            "import time\nfrom mixar.modules.moodboard.core import video_rpc\n"
            "box={}\n"
            f"video_rpc.handle_request('moodboard.view_video', {{'image_name': {state['name']!r}, "
            "'session_id': drv.main_window().scene.mixie_session_id, 'count': 3}, lambda r: box.setdefault('r', r), "
            "run_on_main_thread=lambda fn: (fn(), True)[1])\n"
            "t=time.monotonic()\n"
            "while 'r' not in box and time.monotonic()-t<30: time.sleep(0.05)\n"
            "r=dict(box['r']); r['frames']=[{k:v for k,v in f.items() if k!='image_base64'} for f in r.get('frames',[])]\n"
            "result=r")
        assert reply.get('success'), reply.get('error')
        assert reply['frame_count'] == 6 and len(reply['frames']) == 3, reply
        return {'frames': reply['frames'], 'fps': reply['fps']}
    record('03 the delivered clip is watchable through moodboard.view_video', watch)

    qa.eval(CLEANUP)
    failed = [r for r in rows if r['status'] != 'PASS']
    print(f"{len(rows) - len(failed)}/{len(rows)} passed")
    return not failed


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
