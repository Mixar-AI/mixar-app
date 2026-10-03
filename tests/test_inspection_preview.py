# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspection rig lifetime across asynchronous render exits."""
import sys
from types import SimpleNamespace

import pytest

from test_async_preview import KEY, OTHER, preview, _pixels  # noqa: F401


@pytest.fixture
def rig(preview, monkeypatch):
    state = {'prepared': 0, 'cleaned': 0, 'fail_prepare': False, 'fail_finish': False}
    class Inspection:
        def __init__(self, scene, params, set_value):
            self.scene, self.set = scene, set_value
        def prepare(self, context):
            state['prepared'] += 1
            self.set(self.scene, 'camera', 'temporary-camera')
            self.set(self.scene, 'world', 'temporary-world')
            if state['fail_prepare']:
                raise ValueError('inspection_focus_not_found')
        def finish(self, result):
            assert self.scene.camera == 'temporary-camera'
            assert preview.render_slot.busy()
            if state['fail_finish']:
                raise ValueError('label projection failed')
            if result.get('status') == 'done':
                result['image_base64'] = result.pop('image_url').split(',', 1)[1]
                result['focus'] = {'objects': ['watch']}
        def cleanup(self):
            assert self.scene.camera is None and self.scene.world == 'original-world'
            state['cleaned'] += 1
    monkeypatch.setitem(sys.modules, 'mixar.modules.space_mixie_chat.core.inspection_preview',
                        SimpleNamespace(Inspection=Inspection))
    preview.bpy.context.scene.camera = None
    preview.bpy.context.scene.world = 'original-world'
    return state


@pytest.mark.parametrize('completed', [True, False])
def test_inspection_keeps_rig_until_native_teardown(preview, rig, completed):
    ctx=preview.bpy.context
    assert preview.start(ctx, KEY, inspection={'view':'hero'})['status']=='running'
    assert preview.start(ctx, OTHER, inspection={})['status']=='busy'
    assert rig['prepared']==1
    _pixels(preview)
    preview.bpy.app.is_job_running.return_value=True
    assert preview._finish(KEY, completed)==.1
    assert ctx.scene.camera=='temporary-camera' and rig['cleaned']==0
    preview.bpy.app.is_job_running.return_value=False
    preview._finish(KEY, completed)
    result=preview.poll(KEY)
    assert result['status']==('done' if completed else 'cancelled')
    assert ('image_base64' in result)==completed
    assert rig['cleaned']==1 and not preview.render_slot.busy()


def test_failed_preparation_rolls_back_without_starting_render(preview,rig):
    rig['fail_prepare']=True
    result=preview.start(preview.bpy.context,KEY,inspection={})
    assert result['status']=='failed' and result['error']=='inspection_focus_not_found'
    assert rig['cleaned']==1 and not preview.render_slot.busy()
    preview.bpy.ops.render.render.assert_not_called()


def test_failed_metadata_still_restores_and_releases(preview,rig):
    rig['fail_finish']=True
    preview.start(preview.bpy.context,KEY,inspection={})
    _pixels(preview)
    preview._finish(KEY,True)
    assert preview.poll(KEY)['status']=='failed'
    assert rig['cleaned']==1 and not preview.render_slot.busy()


def test_lost_native_callback_cleans_inspection(preview,rig):
    preview.start(preview.bpy.context,KEY,inspection={})
    preview._job['started_at']-=3
    assert preview.poll(KEY)['status']=='lost'
    assert rig['cleaned']==1 and not preview.render_slot.busy()


def test_auto_final_uses_bounded_cycles_and_restores_engine_and_denoising(preview):
    scene = preview.bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.cycles.samples = 512
    result = preview.start(preview.bpy.context, KEY, engine='auto', width=800, height=600)
    assert result['status'] == 'running'
    assert result['render']['engine'] == 'CYCLES'
    assert result['render']['samples'] == 32 and scene.cycles.use_denoising
    _pixels(preview)
    preview._finish(KEY, True)
    assert scene.render.engine == 'BLENDER_EEVEE'
    assert scene.cycles.samples == 512 and not scene.cycles.use_denoising
