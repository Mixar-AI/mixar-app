# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Client-owned native renders: immediate receipt, then automatic Moodboard delivery.

Handlers only set Python flags. A main-thread timer finalizes after native
teardown, keeping the shared render reservation through persistence/restore.
No chat lifetime, polling RPC, preview caps or synchronous fallback.
"""
import re
import shutil
import tempfile
import time

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.common.render_coordinator import core as slot
from ..constants import RESULTS_NS, MAX_RESULTS, TICK_SECONDS, LOST_AFTER_SECONDS
from .settings import Settings, render_info
from .outputs import deliver, notify

logger = get_logger(__name__)
_job = None
_records = {}


def _publish(key, value):
    _records[key] = dict(value)
    while len(_records) > MAX_RESULTS:
        del _records[next(iter(_records))]
    bpy.app.driver_namespace[RESULTS_NS] = dict(_records)
    return dict(value)


def _reply(key, status, **extra):
    return dict(job_id=key, status=status, success=status in ('started', 'done'), **extra)


@persistent
def _complete(_scene, _depsgraph=None):
    if _job is not None and _job['terminal'] != 'cancelled':
        _job['terminal'] = 'done'


@persistent
def _cancel(_scene, _depsgraph=None):
    if _job is not None:
        _job['terminal'] = 'cancelled'


@persistent
def _write(_scene, _depsgraph=None):
    if _job is not None:
        _job['written'] += 1


def _handlers(add):
    for name, callback in (('render_complete', _complete), ('render_cancel', _cancel),
                           ('render_write', _write)):
        handlers = getattr(bpy.app.handlers, name)
        if add and callback not in handlers:
            handlers.append(callback)
        elif not add and callback in handlers:
            handlers.remove(callback)


@persistent
def _before_load(_unused, _extra=None):
    global _job
    if _job is not None:
        # The timer retains only its old job and cleans files after native teardown.
        _job['invalidated'] = True
        notify(_job['key'], _job['kind'], 'cancelled', 'The project was closed.')
        slot.release(_job['reservation'])
    _job = None
    _records.clear()
    bpy.app.driver_namespace.pop(RESULTS_NS, None)
    _handlers(False)


def _tick(job):
    global _job
    if bpy.app.is_job_running('RENDER'):
        return TICK_SECONDS
    if job.get('invalidated') or _job is not job:
        shutil.rmtree(job['folder'], ignore_errors=True)
        return None
    status = job['terminal']
    if status is None:
        if time.monotonic() - job['started'] < LOST_AFTER_SECONDS:
            return TICK_SECONDS
        status = 'failed'
    value = _reply(job['key'], status, kind=job['kind'], scene_session=job['session'],
                   render=job['render'])
    try:
        slot.phase(job['reservation'], 'finalizing')
        if status == 'done':
            value['moodboard_image_name'] = deliver(job)
        elif status == 'failed':
            value['error'] = 'render_completion_lost'
    except Exception:
        logger.exception('Scene render delivery failed')
        value.update(success=False, status='failed', error='moodboard_delivery_failed')
    finally:
        try:
            last = (job['render']['frame_start'] + max(0, job['written'] - 1) *
                    job['render']['frame_step']) if job['kind'] == 'video' else None
            job['settings'].restore(last)
        finally:
            _handlers(False)
            _job = None
            slot.release(job['reservation'])
            shutil.rmtree(job['folder'], ignore_errors=True)
    value['elapsed_seconds'] = round(time.monotonic() - job['started'], 2)
    _publish(job['key'], value)
    notify(job['key'], job['kind'], value['status'],
           'Open Moodboard to view it.' if value['status'] == 'done' else
           'Check the scene camera and render settings, then try again.' if value['status'] == 'failed' else '')
    return None


def start(context, key, kind='image', label='', expected_session='', **options):
    global _job
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{32}', key):
        return _reply('', 'failed', error='invalid_job_id')
    if key in _records:
        return dict(_records[key])
    # Completed handles belong to the document, not the active window's scene.
    # Check before start-only guards: replay never needs a camera or free renderer.
    for origin in bpy.data.scenes:
        for item in getattr(origin, 'mixie_moodboard_images', ()):
            if item.mixar_job_handle == key and item.image:
                return _publish(key, _reply(
                    key, 'done', kind='video' if item.image.source == 'MOVIE' else 'image',
                    scene_session=str(getattr(origin, 'mixie_session_id', '') or ''),
                    moodboard_image_name=item.image.name))
    if _job is not None or slot.busy():
        return _reply(key, 'busy', error='another_render_running')
    scene = context.scene
    if scene is None:
        return _reply(key, 'failed', error='scene_unavailable')
    session = str(getattr(scene, 'mixie_session_id', '') or '')
    if expected_session and expected_session != session:
        return _reply(key, 'failed', error='wrong_scene')
    if scene.camera is None or context.window is None or bpy.app.background:
        return _reply(key, 'failed', error='camera_and_window_required')
    engine = options.get('engine', '')
    width, height = options.get('width', 0), options.get('height', 0)
    first, last = options.get('frame_start'), options.get('frame_end')
    if (kind not in ('image', 'video') or engine not in ('', 'eevee', 'cycles')
            or bool(width) != bool(height) or min(width, height) < 0
            or max(width, height) > 16384 or not 0 <= options.get('samples', 0) <= 4096
            or not 0 <= options.get('fps', 0) <= 240
            or (first is None) != (last is None)
            or (first is not None and first > last)):
        return _reply(key, 'failed', error='invalid_render_settings')
    if kind == 'video' and (first if first is not None else scene.frame_start) >= (
            last if last is not None else scene.frame_end):
        return _reply(key, 'failed', error='animation_range_required')
    reservation = slot.acquire('scene-render:' + key)
    if reservation is None:
        return _reply(key, 'busy', error='another_render_running')
    job = None
    folder = ''
    try:
        folder = tempfile.mkdtemp(prefix='mixar_scene_render_')
        path = folder + ('/scene.mp4' if kind == 'video' else '/scene.png')
        settings = Settings(scene)
        job = dict(key=key, kind=kind, scene=scene, session=session, settings=settings,
                   folder=folder, path=path, label=label[:200], started=time.monotonic(),
                   terminal=None, written=0, reservation=reservation, render={})
        _job = job
        settings.apply(kind, path, **options)
        job['render'] = render_info(scene)
        if settings.downgraded:
            job['render']['engine_downgraded'] = settings.downgraded
        _handlers(True)
        if _before_load not in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.append(_before_load)
        view = context.preferences.view
        display = view.render_display_type
        try:
            view.render_display_type = 'NONE'
            with bpy.context.temp_override(window=context.window, scene=scene):
                ret = bpy.ops.render.render('INVOKE_DEFAULT', animation=kind == 'video',
                                            write_still=False)
        finally:
            view.render_display_type = display
        if 'RUNNING_MODAL' not in ret:
            raise RuntimeError('async_render_unavailable')
        slot.phase(reservation, 'rendering')
        bpy.app.timers.register(lambda: _tick(job), first_interval=TICK_SECONDS, persistent=True)
        value = _publish(key, _reply(key, 'started', kind=kind, scene_session=session,
                                     render=job['render']))
        notify(key, kind, 'started',
               ('Using EEVEE because this scene exceeds the Cycles memory budget. ' if settings.downgraded else '') +
               'It will appear in Moodboard when finished. Use the render progress control to cancel.')
        return value
    except Exception:
        logger.exception('Could not start scene render')
        if job is not None and bpy.app.is_job_running('RENDER'):
            # Even a post-invoke failure must retain ownership until native teardown.
            bpy.app.timers.register(lambda: _tick(job), first_interval=TICK_SECONDS, persistent=True)
            return _publish(key, _reply(key, 'started', kind=kind, scene_session=session,
                                        render=job['render']))
        if job is not None:
            job['settings'].restore()
        _handlers(False)
        _job = None
        slot.release(reservation)
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        notify(key, kind, 'failed', 'Check the scene camera and render settings, then try again.')
        return _publish(key, _reply(key, 'failed', error='async_render_unavailable'))
