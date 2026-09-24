# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render ownership and deferred consumers, without a Blender runtime."""

from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_async_preview import KEY, OTHER, preview  # noqa: F401 — shared fixture

from mixar.modules.common.render_coordinator import core as slot
from mixar.modules.asset_search.core import generation_library as archive


@pytest.fixture
def renderer(monkeypatch):
    bpy = MagicMock()
    bpy.app.is_job_running.return_value = False
    bpy.app.handlers.load_pre = []
    monkeypatch.setattr(slot, 'bpy', bpy)
    monkeypatch.setattr(slot, '_active', None)
    return bpy


def test_native_render_refuses_acquisition(renderer):
    renderer.app.is_job_running.return_value = True
    assert slot.acquire('thumbnail') is None


def test_reservation_covers_setup_and_finalization(renderer):
    token = slot.acquire('agent')
    for phase in ('preparing', 'rendering', 'finalizing'):
        slot.phase(token, phase)
        assert slot.acquire('thumbnail') is None
    slot.release(token)
    assert slot.acquire('thumbnail') is not None


def test_borrowed_token_does_not_release_parent(renderer):
    with slot.reserve('export') as token:
        with slot.reserve('rig', token):
            with slot.reserve('jpeg', token):
                assert slot.owns(token)
        assert slot.owns(token)
    assert not slot.busy()


def test_exception_releases_reservation(renderer):
    with pytest.raises(ValueError):
        with slot.reserve('export'):
            raise ValueError('failed setup')
    assert not slot.busy()


def test_old_release_cannot_unlock_new_owner(renderer):
    old = slot.acquire('old')
    slot._before_load(None)
    new = slot.acquire('new')
    slot.release(old)
    assert slot.owns(new)
    with pytest.raises(slot.RenderBusy):
        with slot.reserve('stale', old):
            pytest.fail('stale token accepted')


def test_off_thread_reservation_is_rejected(renderer):
    errors = []
    def acquire():
        try:
            slot.acquire('worker')
        except RuntimeError as exc:
            errors.append(str(exc))
    thread = Thread(target=acquire)
    thread.start()
    thread.join()
    assert errors == ['Render reservations require the main thread']
    renderer.app.is_job_running.assert_not_called()


def test_archive_waits_without_popping_and_drains_once(renderer, monkeypatch):
    jobs = [SimpleNamespace(id='one'), SimpleNamespace(id='two')]
    monkeypatch.setattr(archive, '_archive_queue', jobs.copy())
    monkeypatch.setattr(archive, '_archive_timer_running', True)
    monkeypatch.setattr(archive, '_batch_dirty', False)
    saved = []
    monkeypatch.setattr(archive, '_save_job', saved.append)
    token = slot.acquire('agent')
    slot.phase(token, 'finalizing')
    for _ in range(3):
        assert archive._process_archive_queue() == 0.25
        assert archive._archive_queue == jobs
        assert archive._archive_timer_running
    slot.release(token)
    assert archive._process_archive_queue() == 0.0
    assert archive._process_archive_queue() is None
    assert saved == jobs
    assert not archive._archive_timer_running
    archive._process_archive_queue()
    assert saved == jobs


def test_rig_busy_does_not_touch_scene(renderer):
    from mixar.modules.asset_search.utils.preview_render import PreviewRenderRig
    scene = MagicMock()
    token = slot.acquire('agent')
    with pytest.raises(slot.RenderBusy):
        with PreviewRenderRig(scene):
            pytest.fail('entered busy rig')
    assert scene.mock_calls == []
    assert slot.owns(token)


def test_partial_rig_setup_restores_before_releasing(renderer, monkeypatch):
    from mixar.modules.asset_search.utils.preview_render import PreviewRenderRig
    rig = PreviewRenderRig(MagicMock())
    events = []
    def setup():
        events.append('setup')
        assert slot.owns(rig.token)
        raise ValueError('setup failed')
    def restore():
        assert slot.owns(rig.token)
        events.append('restore')
    monkeypatch.setattr(rig, '_setup', setup)
    monkeypatch.setattr(rig, '_restore', restore)
    with pytest.raises(ValueError, match='setup failed'):
        with rig:
            pass
    assert events == ['setup', 'restore']
    assert not slot.busy()


def test_modal_session_does_not_consume_items_while_busy(renderer, monkeypatch, tmp_path):
    from mixar.modules.asset_search.core.render_session import RenderSession
    items = [{'name': str(i), 'library': 'qa'} for i in range(3)]
    session = RenderSession(MagicMock(), items, str(tmp_path))
    session.start()
    rendered = []
    monkeypatch.setattr(session, '_render_item', rendered.append)
    token = slot.acquire('agent')
    assert session.step() == 0
    assert session.index == 0
    slot.release(token)
    assert session.step(count=1) == 1
    assert rendered == items[:1]


def test_export_busy_does_not_create_datablocks_or_directories(renderer, monkeypatch):
    from mixar.modules.moodboard.core import scene_asset_exporter as exporter
    fake_bpy, makedirs = MagicMock(), MagicMock()
    monkeypatch.setattr(exporter, 'bpy', fake_bpy)
    monkeypatch.setattr(exporter.os, 'makedirs', makedirs)
    slot.acquire('agent')
    assert not exporter.export_object_to_asset_library(object(), 'asset', '/unused')
    assert fake_bpy.mock_calls == []
    makedirs.assert_not_called()


def test_file_load_discards_old_document_archive_names(renderer, monkeypatch):
    monkeypatch.setattr(archive, 'bpy', renderer)
    monkeypatch.setattr(archive, '_archive_queue', [SimpleNamespace(id='old-document')])
    monkeypatch.setattr(archive, '_saved_job_ids', {'old-document'})
    monkeypatch.setattr(archive, '_archive_timer_running', True)
    monkeypatch.setattr(archive, '_batch_dirty', True)
    monkeypatch.setattr(archive, '_retrain_scheduled', True)
    archive._clear_pending_archives(None)
    assert not archive._archive_queue and not archive._saved_job_ids
    assert not archive._archive_timer_running and not archive._batch_dirty
    assert not archive._retrain_scheduled


def test_director_cancel_keeps_ownership_until_teardown(renderer, monkeypatch):
    from mixar.modules.director.core import render_outputs as director
    monkeypatch.setattr(director, 'bpy', renderer)
    token = slot.acquire('director')
    job = {'reservation': token, 'configured': True}
    monkeypatch.setattr(director, '_job', job)
    monkeypatch.setattr(director, '_job_target', lambda job: (object(), MagicMock()))
    restored = []
    def restore(job, scene):
        assert slot.owns(token)
        restored.append(True)
    monkeypatch.setattr(director, '_restore_active_pass', restore)
    renderer.app.is_job_running.return_value = True
    director._finish_job(False, 'Cancelled')
    assert slot.owns(token) and not restored
    callback = renderer.app.timers.register.call_args.args[0]
    assert callback() > 0
    renderer.app.is_job_running.return_value = False
    callback()
    assert restored == [True] and not slot.busy()
    assert director._job is None


def test_director_timer_from_old_job_does_not_touch_new_one(renderer, monkeypatch):
    from mixar.modules.director.core import render_outputs as director
    monkeypatch.setattr(director, 'bpy', renderer)
    monkeypatch.setattr(director, '_job', {'reservation': slot.acquire('old')})
    complete = MagicMock()
    director._schedule_for_job(complete, 0.1)
    callback = renderer.app.timers.register.call_args.args[0]
    slot._before_load(None)
    new = slot.acquire('new')
    director._job = {'reservation': new}
    assert callback() is None
    complete.assert_not_called()
    assert slot.owns(new)

def test_archive_waits_through_agent_result_copy_and_restore(preview, monkeypatch):
    from mixar.modules.asset_search.core import generation_library as archive
    preview.start(preview.bpy.context, KEY)
    token = preview._job['reservation']
    monkeypatch.setattr(archive, '_archive_queue', [SimpleNamespace(id='qa')])
    monkeypatch.setattr(archive, '_archive_timer_running', True)
    monkeypatch.setattr(archive, '_batch_dirty', False)
    saved = []
    monkeypatch.setattr(archive, '_save_job', saved.append)
    def read(scene):
        assert preview.render_slot.owns(token)
        assert archive._process_archive_queue() == 0.25
        return b'agent-image'
    original_restore = preview._restore
    def restore(job):
        assert archive._process_archive_queue() == 0.25
        original_restore(job)
    monkeypatch.setattr(preview, '_read_png', read)
    monkeypatch.setattr(preview, '_restore', restore)
    # Native job has already ended; the reservation is still essential.
    preview._finish(KEY, True)
    assert not preview.render_slot.busy()
    assert archive._process_archive_queue() is None
    assert len(saved) == 1


def test_cancel_holds_slot_until_native_teardown(preview):
    preview.start(preview.bpy.context, KEY)
    preview.bpy.app.is_job_running.return_value = True
    assert preview._finish(KEY, False) == 0.1
    assert preview.render_slot._active is not None
    preview.bpy.app.is_job_running.return_value = False
    preview._finish(KEY, False)
    assert not preview.render_slot.busy()


def test_old_completion_cannot_release_a_new_render(preview):
    preview.start(preview.bpy.context, KEY)
    preview._before_load(None)
    preview.start(preview.bpy.context, OTHER)
    token = preview._job['reservation']
    preview._finish(KEY, False)
    assert preview.render_slot.owns(token)

def test_a_finished_job_puts_running_down_even_when_the_camera_is_gone():
    """Renaming or deleting the export camera mid-render must not freeze the
    drawer at 'rendering' until the file is reloaded."""
    from mixar.modules.director.core import render_outputs, render_target

    settings = SimpleNamespace(render_is_running=True, render_progress=0.4, render_status="Rendering")
    scene = SimpleNamespace(name="Scene", mixar_camera_export=settings, mixar_director=None)
    ref = {"kind": "CAMERA", "camera_name": "gone"}
    assert render_target.resolve_status_owner(scene, ref) is settings

    render_outputs._job = {"scene_name": "Scene", "target": ref, "configured": False}
    with MagicMock() as bpy_mock:
        bpy_mock.app.is_job_running.return_value = False
        bpy_mock.data.scenes.get.return_value = scene
        bpy_mock.data.objects.get.return_value = None
        original = render_outputs.bpy
        render_outputs.bpy = bpy_mock
        try:
            render_outputs._finish_job(False, "The render camera was removed while rendering")
        finally:
            render_outputs.bpy = original
    assert render_outputs._job is None
    assert settings.render_is_running is False
    assert settings.render_progress == 0.0
    assert "removed" in settings.render_status
