# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cross-consumer render lifecycle regressions from PR 1570."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

from test_render_coordinator import renderer  # noqa: F401
from mixar.modules.common.render_coordinator import core as slot


def test_sandbox_keeps_director_completion_and_load_cleanup(renderer, monkeypatch):
    from mixar.modules.director.core import render_outputs as director
    from mixar.modules.space_mixie_chat.core import executor_handlers

    for name in executor_handlers.HandlerCleanupMixin._HANDLER_NAMES:
        setattr(renderer.app.handlers, name, [])
    monkeypatch.setattr(director, 'bpy', renderer)
    monkeypatch.setattr(executor_handlers, 'bpy', renderer)
    monkeypatch.setattr(director, '_job', None)
    executor = executor_handlers.HandlerCleanupMixin()
    before = executor._snapshot_handlers()
    token = slot.acquire('director-guides')
    director._job = {'reservation': token, 'scene_name': 'Scene', 'pass_running': True}
    director._add_handlers()

    def impostor(*_args):
        pass

    impostor.__name__ = director._on_render_complete.__name__
    impostor.__module__ = director._on_render_complete.__module__
    renderer.app.handlers.render_complete.append(impostor)
    executor._cleanup_handlers(before)
    assert renderer.app.handlers.render_complete == [director._on_render_complete]
    assert renderer.app.handlers.render_cancel == [director._on_render_cancel]
    assert renderer.app.handlers.render_write == [director._on_render_write]
    assert slot._before_load in renderer.app.handlers.load_pre
    assert director._before_load in renderer.app.handlers.load_pre

    target = MagicMock()
    monkeypatch.setattr(director, '_job_target', lambda _job: (object(), target))
    monkeypatch.setattr(director, '_restore_active_pass', MagicMock())
    director._on_render_cancel(SimpleNamespace(name='Scene'))
    renderer.app.timers.register.call_args.args[0]()
    assert director._job is None
    assert not slot.busy()


def test_picker_file_load_clears_deferred_work_and_restarts(renderer, monkeypatch):
    from mixar.modules.space_mixie_chat.core import asset_choice_previews as picker

    monkeypatch.setattr(picker, 'bpy', renderer)
    monkeypatch.setattr(picker, '_queue', [])
    monkeypatch.setattr(picker, '_timer_running', False)
    monkeypatch.setattr(picker, 'bump_layout_epoch', lambda _scene: None)
    renderer.data.images.get.return_value = None
    action = SimpleNamespace(asset_name='Cube', blend_file='a.blend', library='QA',
                             asset_type='MESH', value='cube', image='')
    bubble = SimpleNamespace(bubble_id='old', action_items=[action])
    scene = SimpleNamespace(name='Scene')
    slot.acquire('director')
    picker.schedule(scene, bubble)
    assert picker._process_next() == 0.25
    for callback in list(renderer.app.handlers.load_pre):
        callback(None)
    assert picker._queue == []
    assert not picker._timer_running
    renderer.app.timers.register.reset_mock()
    picker.schedule(scene, SimpleNamespace(bubble_id='new', action_items=[action]))
    renderer.app.timers.register.assert_called_once()
    assert picker._queue[0][1] == 'new'


def test_reconstruction_export_waits_for_renderer(renderer, monkeypatch):
    from mixar.modules.moodboard.core import scene_asset_exporter as exporter

    monkeypatch.setattr(exporter, 'bpy', renderer)
    export = MagicMock(return_value=True)
    monkeypatch.setattr(exporter, 'export_object_to_asset_library', export)
    obj = SimpleNamespace(name='Chair')
    renderer.data.objects.get.return_value = obj
    token = slot.acquire('agent')
    exporter.schedule_object_export(obj, 'Chair', '/qa/library')
    tick = renderer.app.timers.register.call_args.args[0]
    assert tick() == 0.25
    export.assert_not_called()
    slot.release(token)
    assert tick() is None
    export.assert_called_once_with(obj, 'Chair', '/qa/library')


def test_reconstruction_import_queues_export_without_losing_busy_result(renderer, monkeypatch):
    from mixar.modules.moodboard import core as moodboard_core
    from mixar.modules.moodboard.core import scene_asset_exporter as exporter
    from mixar.modules.moodboard.core import scene_recon_submission as submission

    importer = MagicMock()
    callbacks = {}
    def enqueue(**kwargs):
        callbacks.update(kwargs)
        return object()

    monkeypatch.setitem(sys.modules, 'mixar.modules.moodboard.core.scene_importer', importer)
    # `from core import scene_importer` can reuse the parent's cached module
    # attribute after another test imports the real module. Patch both lookups.
    monkeypatch.setattr(moodboard_core, 'scene_importer', importer, raising=False)
    monkeypatch.setitem(sys.modules, 'mixar.modules.moodboard.core.scene_recon_queue',
                        SimpleNamespace(enqueue_scene_recon_job=enqueue))
    monkeypatch.setattr(exporter, 'bpy', renderer)
    exported = MagicMock(return_value=True)
    monkeypatch.setattr(exporter, 'export_object_to_asset_library', exported)
    assert submission.submit_recon_job(object(), None, b'fixture', True, 100,
                                      save_to_library=True, asset_library_path='/qa/library')
    obj = importer.add_object.return_value
    renderer.data.objects.get.return_value = obj
    token = slot.acquire('agent')
    callbacks['on_object_ready'](b'glb', {}, 'chair', 'Chair')
    importer.add_object.assert_called_once_with(b'glb', {}, 'chair', name='Chair')
    tick = renderer.app.timers.register.call_args.args[0]
    assert tick() == 0.25
    exported.assert_not_called()
    slot.release(token)
    assert tick() is None
    exported.assert_called_once_with(obj, 'Chair', '/qa/library')


def test_deferred_export_does_not_export_replacement_object(renderer, monkeypatch):
    from mixar.modules.moodboard.core import scene_asset_exporter as exporter

    monkeypatch.setattr(exporter, 'bpy', renderer)
    export = MagicMock()
    monkeypatch.setattr(exporter, 'export_object_to_asset_library', export)
    class Object:
        name = 'Chair'

    exporter.schedule_object_export(Object(), 'Chair', '/qa/library')
    renderer.data.objects.get.return_value = Object()
    assert renderer.app.timers.register.call_args.args[0]() is None
    export.assert_not_called()


def test_trusted_handlers_are_removed_from_the_wrong_lists(renderer, monkeypatch):
    from mixar.modules.director.core import render_outputs as director
    from mixar.modules.space_mixie_chat.core import executor_handlers

    executor = executor_handlers.HandlerCleanupMixin()
    for name in executor._HANDLER_NAMES:
        setattr(renderer.app.handlers, name, [])
    monkeypatch.setattr(executor_handlers, 'bpy', renderer)
    before = executor._snapshot_handlers()
    # Exercise every loaded trusted identity on every snapshotted list.
    expected = {
        "load_pre": [slot._before_load, director._before_load],
        "render_complete": [director._on_render_complete],
        "render_cancel": [director._on_render_cancel],
        "render_write": [director._on_render_write],
    }
    callbacks = [slot._before_load, director._before_load,
                 director._on_render_complete, director._on_render_cancel,
                 director._on_render_write]
    for name in executor._HANDLER_NAMES:
        getattr(renderer.app.handlers, name).extend(callbacks)
    executor._cleanup_handlers(before)
    for name in executor._HANDLER_NAMES:
        assert getattr(renderer.app.handlers, name) == expected.get(name, [])
    assert renderer.app.handlers.depsgraph_update_post == []
    assert slot._before_load in renderer.app.handlers.load_pre


def test_director_next_pass_timeout_releases_while_foreign_render_runs(renderer, monkeypatch):
    from mixar.modules.director.core import render_outputs as director

    monkeypatch.setattr(director, 'bpy', renderer)
    token = slot.acquire('director-guides')
    job = {'reservation': token, 'configured': False, 'pass_running': False,
           'next_pass_deadline': float('inf')}
    monkeypatch.setattr(director, '_job', job)
    target = MagicMock()
    monkeypatch.setattr(director, '_job_target', lambda _job: (object(), target))
    restore = MagicMock()
    monkeypatch.setattr(director, 'restore_render_settings', restore)
    for name in ('render_complete', 'render_cancel', 'render_write'):
        setattr(renderer.app.handlers, name, [])
    director._add_handlers()
    renderer.app.timers.register.reset_mock()
    renderer.app.is_job_running.return_value = True
    assert director._start_next_pass_when_idle() == director._NEXT_PASS_POLL_SECONDS
    assert slot.owns(token)
    job['next_pass_deadline'] = 0
    assert director._start_next_pass_when_idle() is None
    assert director._job is None and not slot.owns(token)
    target.set_status.assert_called_once_with(
        running=False, progress=0.0,
        status='Render failed: Blender did not release the render slot')
    restore.assert_not_called()
    renderer.app.timers.register.assert_not_called()
    assert renderer.app.handlers.render_complete == []
    assert renderer.app.handlers.render_cancel == []
    assert renderer.app.handlers.render_write == []
    # Dropping Director ownership must not make the occupied native slot free.
    assert slot.busy() and slot.acquire('archive') is None
    renderer.app.is_job_running.return_value = False
    assert slot.acquire('archive') is not None
