# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lifecycle checks; native job and pixel proof lives in qa/async_preview_e2e.py."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'src/scripts/mixar/modules/space_mixie_chat/core'


@pytest.fixture
def preview(monkeypatch):
    spec = importlib.util.spec_from_file_location('mixar.modules.space_mixie_chat.core.preview_test', CORE / 'preview_render.py')
    module = importlib.util.module_from_spec(spec)
    from mixar.modules.space_mixie_chat.core import render_devices
    monkeypatch.setattr(render_devices, "select_device", lambda context, set_value: {"device": "CPU"})
    spec.loader.exec_module(module)
    fake = MagicMock()
    fake.app.background = False
    fake.app.is_job_running.return_value = False
    fake.app.driver_namespace = {}
    for name in ('render_complete', 'render_cancel', 'depsgraph_update_post', 'load_pre'):
        setattr(fake.app.handlers, name, [])
    scene = SimpleNamespace(
        camera=object(), cycles=SimpleNamespace(samples=64),
        render=SimpleNamespace(resolution_x=1200, resolution_y=900,
                               resolution_percentage=80, use_lock_interface=False,
                               image_settings=SimpleNamespace(file_format='JPEG')),
    )
    fake.context.scene = scene
    fake.context.preferences.view.render_display_type = 'WINDOW'
    fake.ops.render.render.return_value = {'RUNNING_MODAL'}
    monkeypatch.setattr(module, 'bpy', fake)
    return module


def test_start_is_native_async_and_duplicate_is_idempotent(preview):
    key = 'a' * 32
    assert preview.start(preview.bpy.context, key)['status'] == 'running'
    preview.bpy.app.is_job_running.return_value = True
    assert preview.start(preview.bpy.context, key)['status'] == 'running'
    assert preview.start(preview.bpy.context, 'b' * 32)['status'] == 'busy'
    preview.bpy.ops.render.render.assert_called_once_with('INVOKE_DEFAULT', write_still=False)
    assert preview.bpy.context.preferences.view.render_display_type == 'WINDOW'
    assert not preview.bpy.context.scene.render.use_lock_interface


def test_render_callback_only_schedules_main_loop_work(preview):
    preview.start(preview.bpy.context, 'a' * 32)
    preview.bpy.reset_mock()
    preview._complete(None)
    preview.bpy.app.timers.register.assert_called_once()
    preview.bpy.context.view_layer.update.assert_not_called()
    preview.bpy.data.images.get.assert_not_called()
    assert preview._job['finishing']


@pytest.mark.parametrize('completed', [True, False])
def test_stale_or_cancelled_never_reads_pixels_and_preserves_user_setting(preview, completed):
    key = 'a' * 32
    preview.start(preview.bpy.context, key)
    preview._changed(None, SimpleNamespace(mode='VIEWPORT', updates=[object()]))
    preview.bpy.context.scene.cycles.samples = 48
    preview._finish(key, completed)
    result = preview.poll(key)
    assert result['status'] == ('stale' if completed else 'cancelled')
    assert 'image_url' not in result
    preview.bpy.data.images.get.assert_not_called()
    scene = preview.bpy.context.scene
    assert (scene.render.resolution_x, scene.render.resolution_y,
            scene.render.resolution_percentage, scene.cycles.samples) == (1200, 900, 80, 48)
    assert scene.render.image_settings.file_format == 'JPEG'
    assert preview._job is None
    assert not preview.bpy.app.handlers.render_complete
    assert not preview.bpy.app.handlers.render_cancel


def test_render_graph_updates_do_not_invalidate_preview(preview):
    preview._changed(None, SimpleNamespace(mode='RENDER', updates=[object()]))
    assert preview._revision == 0


def test_finalize_waits_for_native_teardown(preview):
    preview.start(preview.bpy.context, 'a' * 32)
    preview.bpy.app.is_job_running.return_value = True
    assert preview._finish('a' * 32, True) == .1
    preview.bpy.data.images.get.assert_not_called()
    assert preview._job is not None


def test_lost_callback_recovers_settings_without_restarting(preview, monkeypatch):
    key = 'a' * 32
    preview.start(preview.bpy.context, key)
    monkeypatch.setattr(preview.time, 'monotonic', lambda: preview._job['started_at'] + 3 if preview._job else 100)
    assert preview.poll(key)['status'] == 'lost'
    assert preview.bpy.context.scene.render.resolution_x == 1200
    preview.bpy.ops.render.render.assert_called_once()


def test_image_failure_is_path_free_and_restores_settings(preview):
    key = 'a' * 32
    preview.start(preview.bpy.context, key)
    preview.bpy.data.images.get.side_effect = RuntimeError('/Users/private/secret.blend')
    preview._finish(key, True)
    result = preview.poll(key)
    assert result['status'] == 'failed'
    assert '/Users' not in str(result)
    assert preview.bpy.context.scene.render.resolution_x == 1200


def test_headless_and_failed_invoke_have_no_blocking_fallback(preview):
    preview.bpy.app.background = True
    assert preview.start(preview.bpy.context, 'a' * 32)['status'] == 'failed'
    preview.bpy.ops.render.render.assert_not_called()
    preview.bpy.app.background = False
    preview.bpy.ops.render.render.return_value = {'CANCELLED'}
    assert preview.start(preview.bpy.context, 'b' * 32)['status'] == 'failed'
    preview.bpy.ops.render.render.assert_called_once_with('INVOKE_DEFAULT', write_still=False)
    assert preview.bpy.context.scene.render.resolution_x == 1200


def test_reload_discards_old_scene_results(preview):
    preview.start(preview.bpy.context, 'a' * 32)
    preview._before_load(None)
    assert preview.poll('a' * 32)['status'] == 'lost'
    assert preview._job is None


def test_sandbox_preserves_exact_callbacks_but_removes_impostors(monkeypatch):
    from mixar.modules.space_mixie_chat.core import executor_handlers, preview_render
    from mixar.modules.space_mixie_chat.ui.operators import agent_final_render_ops

    handlers = SimpleNamespace(render_complete=[], render_cancel=[],
                               depsgraph_update_post=[], load_pre=[])
    monkeypatch.setattr(executor_handlers, 'bpy', SimpleNamespace(app=SimpleNamespace(handlers=handlers)))
    executor = executor_handlers.HandlerCleanupMixin()
    snapshot = executor._snapshot_handlers()
    def impostor(*args):
        pass
    impostor.__name__ = preview_render._complete.__name__
    impostor.__module__ = preview_render._complete.__module__
    handlers.render_complete.extend([preview_render._complete, agent_final_render_ops._on_render_complete, impostor])
    handlers.render_cancel.append(preview_render._cancelled)
    handlers.depsgraph_update_post.append(preview_render._changed)
    handlers.load_pre.append(preview_render._before_load)
    executor._cleanup_handlers(snapshot)
    assert handlers.render_complete == [preview_render._complete, agent_final_render_ops._on_render_complete]
    assert handlers.render_cancel == [preview_render._cancelled]
    assert handlers.depsgraph_update_post == [preview_render._changed]
    assert handlers.load_pre == [preview_render._before_load]


def test_native_render_stop_sets_the_pipeline_cancellation_flag():
    source = (ROOT / 'src/source/blender/editors/interface/templates/interface_template_running_jobs.cc').read_text()
    block = source.split('if (WM_jobs_test(wm, &scene, WM_JOB_TYPE_RENDER)) {', 1)[1].split('icon = ICON_SCENE;', 1)[0]
    assert 'G.is_break = true;' in block
    assert 'WM_jobs_stop_all_from_owner(CTX_wm_manager(&C), &scene);' in block
