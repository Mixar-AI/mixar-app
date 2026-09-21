#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit PR 1570 regressions against an isolated app with current Python.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT set. Injects the
between-pass timeout boundary while a real native Cycles render owns the slot;
checks real handler lists and RNA status, then saves the native render for vision.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

CHECK = '''
import os
from mixar.modules.common.render_coordinator import core as slot
from mixar.modules.director.core import render_outputs as director
from mixar.modules.space_mixie_chat.core.executor_handlers import HandlerCleanupMixin
assert os.environ.get('MIXAR_QA') == '1'
assert not slot.busy() and director._job is None
cleanup = HandlerCleanupMixin()
before = cleanup._snapshot_handlers()
# No event-loop turn occurs between injection and cleanup.
for name in ('depsgraph_update_post', 'frame_change_post'):
    getattr(bpy.app.handlers, name).append(slot._before_load)
if slot._before_load not in bpy.app.handlers.load_pre:
    bpy.app.handlers.load_pre.append(slot._before_load)
cleanup._cleanup_handlers(before)
assert slot._before_load in bpy.app.handlers.load_pre
assert slot._before_load not in bpy.app.handlers.depsgraph_update_post
assert slot._before_load not in bpy.app.handlers.frame_change_post
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    assert scene.camera is not None
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 64
    scene.render.resolution_x = 512
    scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    settings = scene.mixar_camera_export
    settings.render_is_running = True
    settings.render_status = 'Preparing Clay'
    token = slot.acquire('director-guides')
    assert token is not None
    director._job = dict(reservation=token, configured=False, pass_running=False,
        scene_name=scene.name, next_pass_deadline=0,
        target=dict(kind='CAMERA', camera_name=scene.camera.name,
            frame_start=1, frame_end=2, kinds=('CLAY',),
            resolution_percentage=100, display_prefix='QA'))
    director._add_handlers()
    bpy.context.preferences.view.render_display_type = 'NONE'
    assert 'RUNNING_MODAL' in bpy.ops.render.render('INVOKE_DEFAULT')
    assert bpy.app.is_job_running('RENDER')
    assert director._start_next_pass_when_idle() is None
    assert director._job is None and not slot.owns(token)
    assert not settings.render_is_running
    assert 'did not release' in settings.render_status
    assert director._on_render_complete not in bpy.app.handlers.render_complete
    assert director._on_render_cancel not in bpy.app.handlers.render_cancel
    assert director._on_render_write not in bpy.app.handlers.render_write
    assert slot.busy() and slot.acquire('archive') is None
result = {'handler_lists_scoped': True, 'timeout_released_during_native_render': True,
          'status': settings.render_status}
'''


def run(qa):
    qa.step('login', qa.cmd, 'wait_login', timeout=60)
    qa.step('clean_scene', qa.cmd, 'reset_state')
    qa.step('reconnect', qa.cmd, 'wait_login', timeout=60)
    qa.step('dismiss_splash', qa.dismiss_splash)
    verdict = qa.step('handler_cleanup_and_busy_timeout', qa.eval, CHECK)
    qa.step('native_render_finishes', qa.wait,
            "not bpy.app.is_job_running('RENDER')", timeout=60)
    output = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/render-review-qa'))
    output.mkdir(parents=True, exist_ok=True)
    render = str(output / 'native-render.png')
    qa.step('save_render_and_reacquire', qa.eval, f'''
from mixar.modules.common.render_coordinator import core as slot
image = bpy.data.images['Render Result']
image.save_render({render!r}, scene=drv.main_window().scene)
assert not slot.busy()
token = slot.acquire('archive')
assert token is not None
slot.release(token)
result = True
''')
    qa.step('viewport_evidence', qa.snap, str(output / 'viewport.png'))
    return dict(verdict, native_render=render)


if __name__ == '__main__':
    run_scenario('render_review_regressions', run)
