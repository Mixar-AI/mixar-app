#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic repro: a route restore frees a starting preview job's RenderEngine.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4800 \
QA_SCENARIO_OUT=/tmp/route-race python3 tests/qa/preview_route_restore_crash_e2e.py

No credits and no agent turn: it drives the executor's own routing functions and the
preview operator, exactly as a lane ``render_viewport`` tick does (route.pin → the
``mixie_chat.agent_preview_render`` operator → route.restore, all in one main-thread
tick). Cycles' Python ``update_render_passes`` is wrapped so the job thread pauses
inside it (the window in which its engine exists but is not yet flagged
``RE_ENGINE_RENDERING``) until the tick has done its restore. The wrapper then reads
the engine's Python instance: ``ReferenceError`` means the scene switch freed the
engine under the job thread (docs/render-job-contract.md, "A scene switch never lands
on a starting render job"). The outcome is written to ``engine_state.txt`` BEFORE the
job thread resumes, so the evidence survives the crash that usually follows.

The verdict is self-checking and needs no crash: when the engine was freed, the paused
job thread is parked for good instead of resuming into the freed engine, the scenario
prints ``VERDICT: engine freed`` and fails, and the app stays up for the stop script.

Before the fix: ``VERDICT: engine freed`` (the restore switched the window while the job
thread was inside the window). After it: the window is restored before the invoke,
``VERDICT: engine alive``, the restore after the script switches nothing and the
preview returns ``done``.

``QA_LATE_SWITCH=1`` instead switches the tab from a LATER tick while the job thread
waits in the same place (a user clicking a tab in the first milliseconds of a render).
The Python fix cannot cover that; the ``engine.cc`` overlay (flag before the result is
built) does, so this variant passes only on a build that carries it.
"""
import os
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

KEY = uuid.uuid4().hex  # START is idempotent per key: one fresh job per run
LANE = 'agentlane:qarouterace'

SETUP = '''
import os, threading, uuid
from pathlib import Path
from types import SimpleNamespace
from mixar.modules.common.render_coordinator import core as slot
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA profile'
assert not slot.busy() and not bpy.app.is_job_running('RENDER')
root = Path(os.environ['MIXAR_QA_OUT']) / ('route-race-' + uuid.uuid4().hex[:8])
root.mkdir(parents=True, exist_ok=True)
win = drv.main_window()
user = win.scene
assert not user.get('mixie_session_id', '').startswith('agentlane:')
lane = bpy.data.scenes.get('Workspace_qarouterace') or bpy.data.scenes.new('Workspace_qarouterace')
lane.mixie_session_id = %(lane)r
if not lane.objects:
    mesh = bpy.data.meshes.new('QA_RaceCube')
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0), (0, 0, 1.5)],
                     [], [(0, 1, 2, 3), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])
    lane.collection.objects.link(bpy.data.objects.new('QA_RaceCube', mesh))
    cam = bpy.data.objects.new('QA_RaceCam', bpy.data.cameras.new('QA_RaceCam'))
    cam.location = (5, -5, 4)
    cam.rotation_euler = (1.1, 0, 0.785)
    lane.collection.objects.link(cam)
    lane.camera = cam
cycles = next(c for c in bpy.types.RenderEngine.__subclasses__()
              if getattr(c, 'bl_idname', '') == 'CYCLES')
f = drv._route_race = SimpleNamespace(
    root=root, user=user.name, lane=lane.name, cycles=cycles,
    orig=cycles.__dict__['update_render_passes'], armed=False, state='unseen',
    inside=threading.Event(), release=threading.Event())

def paused_update_render_passes(self, scene, srl):
    if f.armed and threading.current_thread() is not threading.main_thread():
        f.armed = False
        f.inside.set()
        f.release.wait(10.0)
        try:
            self.is_animation
            f.state = 'alive'
        except ReferenceError:
            f.state = 'freed'
        (f.root / 'engine_state.txt').write_text(f.state)
        if f.state == 'freed':
            # Never return into RE_engine_render with a freed engine: park this job
            # thread for good, so the verdict needs no crash and the app stays up
            # (the stop script's kill ends it).
            threading.Event().wait()
    return f.orig(self, scene, srl)

cycles.update_render_passes = paused_update_render_passes
result = str(root)
''' % {'lane': LANE}

# One executor tick, as main_thread_executor runs a routed render_viewport script.
TICK = '''
import time
from mixar.modules.space_mixie_chat.core import main_thread_routing as routing
f = drv._route_race
f.armed, f.state = True, 'unseen'
f.inside.clear(); f.release.clear()
win = drv.main_window()
switches = []
with bpy.context.temp_override(window=win):
    target, did_switch, error = routing.route_request(%(lane)r, 'render_viewport', 'qa-race')
    assert error is None and did_switch and win.scene.name == f.lane, (error, did_switch)
    bpy.ops.mixie_chat.agent_preview_render(job_key=%(key)r, width=320, height=240,
                                            engine='cycles')
    response = dict(bpy.app.driver_namespace['mixie_agent_preview_response'])
    assert response['status'] == 'running', response
    # The rest of a real tick holds the GIL in slices; this waits until the job
    # thread is inside update_render_passes, the window a scene switch must miss.
    reached = f.inside.wait(10.0)
    before = win.scene.name
    t0 = time.monotonic()
    routing.restore_after(did_switch)
    restore_ms = round((time.monotonic() - t0) * 1000, 1)
    after = win.scene.name
f.release.set()
deadline = time.monotonic() + 10
while f.state == 'unseen' and time.monotonic() < deadline:
    time.sleep(0.01)
result = {'reached_update_render_passes': reached, 'window_before_restore': before,
          'window_after_restore': after, 'restore_ms': restore_ms, 'engine': f.state}
''' % {'lane': LANE, 'key': KEY}

# Variant: the job starts from the user's own tab and a LATER tick switches tabs.
LATE_START = '''
f = drv._route_race
f.armed, f.state = True, 'unseen'
f.inside.clear(); f.release.clear()
win = drv.main_window()
with bpy.context.temp_override(window=win):
    bpy.ops.mixie_chat.agent_preview_render(job_key=%(key)r, width=320, height=240,
                                            engine='cycles')
response = dict(bpy.app.driver_namespace['mixie_agent_preview_response'])
assert response['status'] == 'running', response
result = f.inside.wait(10.0)
''' % {'key': KEY}

LATE_SWITCH = '''
import time
f = drv._route_race
win = drv.main_window()
with bpy.context.temp_override(window=win):
    win.scene = bpy.data.scenes[f.lane]
    win.scene = bpy.data.scenes[f.user]
f.release.set()
deadline = time.monotonic() + 10
while f.state == 'unseen' and time.monotonic() < deadline:
    time.sleep(0.01)
result = {'engine': f.state}
'''

POLL = '''
from mixar.modules.space_mixie_chat.core import preview_render as preview
value = preview.poll(%(key)r)
result = {k: value.get(k) for k in ('status', 'error', 'render')}
''' % {'key': KEY}

CLEANUP = '''
f = getattr(drv, '_route_race', None)
if f is not None:
    f.release.set()
    f.cycles.update_render_passes = f.orig
    win = drv.main_window()
    if win.scene.name != f.user and f.user in bpy.data.scenes:
        with bpy.context.temp_override(window=win):
            win.scene = bpy.data.scenes[f.user]
    lane = bpy.data.scenes.get(f.lane)
    if lane is not None and not bpy.app.is_job_running('RENDER'):
        bpy.data.scenes.remove(lane, do_unlink=True)
result = True
'''


def _render_done(qa):
    qa.wait("__import__('mixar.modules.space_mixie_chat.core.preview_render', "
            f"fromlist=['poll']).poll({KEY!r})['status'] != 'running'", timeout=120)
    return qa.eval(POLL)


def run(qa):
    qa.step('login', qa.cmd, 'wait_login', timeout=60)
    qa.step('dismiss_splash', qa.cmd, 'dismiss_splash')
    qa.step('setup_lane_and_pause_hook', qa.eval, SETUP)
    try:
        if os.environ.get('QA_LATE_SWITCH') == '1':
            reached = qa.step('start_in_user_tab', qa.eval, LATE_START)
            assert reached, 'job thread never reached update_render_passes'
            tick = qa.step('switch_tabs_from_a_later_tick', qa.eval, LATE_SWITCH)
        else:
            tick = qa.step('lane_render_viewport_tick', qa.eval, TICK)
            assert tick['reached_update_render_passes'], tick
        print(f"VERDICT: engine {tick['engine']} ({tick})", flush=True)
        assert tick['engine'] == 'alive', f"RACE REPRODUCED: RenderEngine freed under the job thread: {tick}"
        if 'window_before_restore' in tick:
            # The restore after the script must find the window already back.
            assert tick['window_before_restore'] == tick['window_after_restore'], tick
        outcome = qa.step('preview_finishes', _render_done, qa)
        assert outcome['status'] == 'done', outcome
        return {'tick': tick, 'preview': outcome}
    finally:
        try:
            # A parked job thread keeps the render "running": cleanup then only
            # restores the hook and the tab; the stop script ends the app.
            qa.eval(CLEANUP)
        except Exception:
            pass


if __name__ == '__main__':
    run_scenario('preview_route_restore_crash', run)
