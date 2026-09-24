# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Job ownership, exact-once completion and settings preservation outside Blender."""
import importlib
import sys
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

KEY, OTHER = 'a' * 32, 'b' * 32


@pytest.fixture
def jobs(monkeypatch):
    monkeypatch.setattr(sys.modules['bpy.app.handlers'], 'persistent', lambda f: f)
    module = importlib.import_module('mixar.modules.scene_render.core.jobs')
    monkeypatch.setattr(module, '_job', None)
    monkeypatch.setattr(module, '_records', {})
    fake = MagicMock()
    fake.app.background = False
    fake.app.is_job_running.return_value = False
    fake.app.driver_namespace = {}
    for name in ('load_pre', 'render_complete', 'render_cancel', 'render_write'):
        setattr(fake.app.handlers, name, [])
    fake.context.scene = NS(
        camera=object(), mixie_session_id='s', frame_current=7, frame_subframe=0.0,
        frame_start=1, frame_end=24, frame_step=1, frame_set=MagicMock(),
        cycles=NS(samples=256, device='CPU'), eevee=NS(taa_render_samples=64),
        render=NS(engine='CYCLES', resolution_x=2048, resolution_y=1024,
                  resolution_percentage=75, fps=24, fps_base=1.001,
                  filepath='/private/user-original', use_file_extension=False,
                  use_lock_interface=False,
                  image_settings=NS(media_type='IMAGE', file_format='JPEG',
                                    color_mode='RGB', color_depth='8'),
                  ffmpeg=NS(format='QUICKTIME', codec='MPEG4', constant_rate_factor='HIGH')))
    fake.context.window = object()
    fake.data.scenes = [fake.context.scene]
    fake.context.preferences.view.render_display_type = 'WINDOW'
    fake.ops.render.render.return_value = {'RUNNING_MODAL'}
    monkeypatch.setattr(module, 'bpy', fake)
    monkeypatch.setattr(module.slot, 'bpy', fake)
    monkeypatch.setattr(module.slot, '_active', None)
    monkeypatch.setattr(module, 'notify', MagicMock())
    monkeypatch.setattr(module, 'deliver', MagicMock(return_value='Render'))
    yield module
    if module._job:
        module._job['terminal'] = 'cancelled'
        fake.app.is_job_running.return_value = False
        module._tick(module._job)


def test_receipt_is_immediate_idempotent_and_uses_scene_quality(jobs):
    result = jobs.start(jobs.bpy.context, KEY)
    assert result['status'] == 'started'
    assert result['render']['width'] == 1536
    assert result['render']['samples'] == 256
    assert result['render']['device'] == 'CPU'
    jobs.deliver.assert_not_called()
    assert jobs.start(jobs.bpy.context, KEY) == result
    assert jobs.start(jobs.bpy.context, OTHER)['status'] == 'busy'
    jobs.bpy.ops.render.render.assert_called_once_with('INVOKE_DEFAULT', animation=False, write_still=False)
    assert jobs.bpy.context.preferences.view.render_display_type == 'WINDOW'


def test_completion_waits_for_native_teardown_and_delivers_once(jobs):
    jobs.start(jobs.bpy.context, KEY)
    job = jobs._job
    jobs._complete(None)
    jobs.bpy.app.is_job_running.return_value = True
    assert jobs._tick(job) > 0
    assert jobs.slot.owns(job['reservation'])
    jobs.deliver.assert_not_called()
    jobs.bpy.app.is_job_running.return_value = False
    assert jobs._tick(job) is None
    assert jobs._tick(job) is None
    jobs.deliver.assert_called_once_with(job)
    assert not jobs.slot.busy()
    assert jobs.start(jobs.bpy.context, KEY)['status'] == 'done'
    assert jobs.bpy.context.scene.render.image_settings.file_format == 'JPEG'


def test_video_restores_settings_and_preserves_user_edits(jobs):
    scene = jobs.bpy.context.scene
    jobs.start(jobs.bpy.context, KEY, kind='video', engine='eevee', width=320, height=240,
               frame_start=3, frame_end=9, fps=12)
    job = jobs._job
    assert scene.render.image_settings.file_format == 'FFMPEG'
    assert scene.render.ffmpeg.codec == 'H264'
    assert scene.render.engine == 'BLENDER_EEVEE'
    scene.render.resolution_x = 640  # changed by user during job
    scene.frame_current = 9
    job['written'] = 7
    jobs._complete(None)
    jobs._tick(job)
    assert scene.render.resolution_x == 640
    assert scene.render.resolution_y == 1024
    assert scene.render.resolution_percentage == 75
    assert scene.render.engine == 'CYCLES'
    assert scene.render.filepath == '/private/user-original'
    assert scene.render.ffmpeg.codec == 'MPEG4'
    assert scene.render.image_settings.media_type == 'IMAGE'
    assert (scene.frame_start, scene.frame_end, scene.render.fps_base) == (1, 24, 1.001)
    scene.frame_set.assert_called_once_with(7, subframe=0.0)


@pytest.mark.parametrize('terminal', ['cancelled', 'failed'])
def test_cancel_and_lost_completion_do_not_import(jobs, terminal):
    jobs.start(jobs.bpy.context, KEY)
    job = jobs._job
    job['terminal'] = terminal
    jobs._tick(job)
    jobs.deliver.assert_not_called()
    assert jobs._records[KEY]['status'] == terminal
    assert not jobs.slot.busy()


def test_delivery_failure_is_path_free_and_releases_slot(jobs):
    jobs.start(jobs.bpy.context, KEY)
    job = jobs._job
    jobs.deliver.side_effect = RuntimeError('/Users/private/output.png')
    jobs._complete(None)
    jobs._tick(job)
    assert jobs._records[KEY]['status'] == 'failed'
    assert '/Users' not in str(jobs._records[KEY])
    assert not jobs.slot.busy()


def test_load_invalidates_old_callback_without_touching_new_scene(jobs):
    jobs.start(jobs.bpy.context, KEY)
    old = jobs._job
    jobs._before_load(None)
    assert jobs._job is None
    jobs.start(jobs.bpy.context, OTHER)
    new = jobs._job
    jobs._tick(old)
    assert jobs._job is new
    assert jobs.slot.owns(new['reservation'])
    jobs.deliver.assert_not_called()


@pytest.mark.parametrize('options,error', [
    ({'expected_session': 'other'}, 'wrong_scene'),
    ({'width': 500}, 'invalid_render_settings'),
    ({'kind': 'video', 'frame_start': 1, 'frame_end': 1}, 'animation_range_required'),
])
def test_invalid_requests_do_not_start(jobs, options, error):
    assert jobs.start(jobs.bpy.context, KEY, **options)['error'] == error
    jobs.bpy.ops.render.render.assert_not_called()


def test_job_thread_handlers_do_no_bpy_work(jobs):
    jobs.start(jobs.bpy.context, KEY)
    jobs.bpy.reset_mock()
    jobs._write(None)
    jobs._complete(None)
    jobs._cancel(None)
    assert jobs.bpy.mock_calls == []


def test_invoke_failure_restores_and_remains_idempotent(jobs):
    jobs.bpy.ops.render.render.return_value = {'CANCELLED'}
    assert jobs.start(jobs.bpy.context, KEY)['status'] == 'failed'
    assert jobs.start(jobs.bpy.context, KEY)['status'] == 'failed'
    assert jobs.bpy.context.scene.render.image_settings.file_format == 'JPEG'
    jobs.bpy.ops.render.render.assert_called_once()
    assert not jobs.slot.busy()


def test_geometry_budget_discloses_downgrade_and_restores_engine(jobs, monkeypatch):
    from mixar.modules.common.agent_execution import scene_cost
    monkeypatch.setattr(scene_cost, 'scene_geometry_cost', lambda scene: {'unique_faces': 1000})
    result = jobs.start(jobs.bpy.context, KEY, max_faces=100)
    assert result['render']['engine'] == 'BLENDER_EEVEE'
    assert result['render']['engine_downgraded']['from'] == 'CYCLES'
    job = jobs._job
    jobs._cancel(None)
    jobs._tick(job)
    assert jobs.bpy.context.scene.render.engine == 'CYCLES'


def test_finalizer_timer_survives_file_load_for_old_temp_cleanup(jobs):
    jobs.start(jobs.bpy.context, KEY)
    assert jobs.bpy.app.timers.register.call_args.kwargs['persistent'] is True


def test_trusted_handlers_only_survive_on_their_intended_lists(jobs, monkeypatch):
    from mixar.modules.space_mixie_chat.core.executor_handlers import HandlerCleanupMixin
    cleanup_module = importlib.import_module('mixar.modules.space_mixie_chat.core.executor_handlers')
    monkeypatch.setattr(cleanup_module, 'bpy', jobs.bpy)
    cleanup = HandlerCleanupMixin()
    before = cleanup._snapshot_handlers()
    jobs.start(jobs.bpy.context, KEY)
    jobs.bpy.app.handlers.render_write.append(jobs._complete)
    cleanup._cleanup_handlers(before)
    assert jobs._complete in jobs.bpy.app.handlers.render_complete
    assert jobs._write in jobs.bpy.app.handlers.render_write
    assert jobs._complete not in jobs.bpy.app.handlers.render_write


def test_delivery_does_not_apply_preview_resolution_or_sample_caps(jobs):
    result = jobs.start(jobs.bpy.context, KEY, width=4096, height=2160, samples=512)
    assert (result['render']['width'], result['render']['height'], result['render']['samples']) == (4096, 2160, 512)


def test_saved_moodboard_handle_prevents_replay_after_file_load(jobs):
    jobs.bpy.context.scene.mixie_moodboard_images = [NS(mixar_job_handle=KEY, image=NS(name='Saved render', source='FILE'))]
    result = jobs.start(jobs.bpy.context, KEY)
    assert result['status'] == 'done' and result['moodboard_image_name'] == 'Saved render'
    jobs.bpy.ops.render.render.assert_not_called()


@pytest.mark.parametrize('expected_session', ['', 's'])
@pytest.mark.parametrize('source,kind', [('FILE', 'image'), ('MOVIE', 'video')])
def test_reopened_render_replay_finds_origin_with_another_scene_active(jobs, expected_session, source, kind):
    origin = jobs.bpy.context.scene
    origin.mixie_moodboard_images = [NS(mixar_job_handle=KEY, image=NS(name='Saved render', source=source))]
    other = NS(mixie_session_id='other', mixie_moodboard_images=[], camera=None)
    jobs.bpy.data.scenes.append(other)
    jobs._before_load(None)
    jobs.bpy.context.scene = other
    # An unrelated native render must not hide an already delivered receipt.
    jobs.bpy.app.is_job_running.return_value = True
    result = jobs.start(jobs.bpy.context, KEY, expected_session=expected_session)
    assert result['status'] == 'done'
    assert result['scene_session'] == 's' and result['kind'] == kind
    assert other.mixie_moodboard_images == []
    jobs.bpy.ops.render.render.assert_not_called()


def test_late_complete_does_not_promote_cancelled_pixels(jobs):
    jobs.start(jobs.bpy.context, KEY)
    job = jobs._job
    jobs._cancel(None)
    jobs._complete(None)
    jobs._tick(job)
    jobs.deliver.assert_not_called()
    assert jobs._records[KEY]['status'] == 'cancelled'
