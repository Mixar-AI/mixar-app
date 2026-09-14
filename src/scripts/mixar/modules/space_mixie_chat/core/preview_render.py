# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native asynchronous previews. All image/RNA work stays on the main thread."""
import base64
import re
import tempfile
import time

import bpy

RESULTS_NS = 'mixie_agent_preview'
_job = None
_revision = 0
_records = {}


def _changed(scene, depsgraph):
    global _revision
    # The render evaluates its own graph; only viewport changes invalidate it.
    if depsgraph.mode == 'VIEWPORT' and depsgraph.updates:
        _revision += 1


def _publish(key, value):
    _records[key] = value
    # Only a small number of bounded PNGs may remain in client memory.
    while len(_records) > 4:
        del _records[next(iter(_records))]
    bpy.app.driver_namespace[RESULTS_NS] = _records


def _restore(job):
    for owner, name, original, applied in job['settings']:
        # Preserve a user's new setting if it changed while the job was running.
        if getattr(owner, name) == applied:
            setattr(owner, name, original)
    bpy.context.view_layer.update()


def _remove_render_handlers():
    for handlers, callback in ((bpy.app.handlers.render_complete, _complete),
                               (bpy.app.handlers.render_cancel, _cancelled)):
        if callback in handlers:
            handlers.remove(callback)


def _finish(key, completed, lost=False):
    global _job
    if _job is None or _job['key'] != key:
        return None
    # render_complete precedes WM job teardown. Do not read Render Result early.
    if bpy.app.is_job_running('RENDER'):
        return 0.1
    job = _job
    scene = job['scene']
    result = {'job_id': key, 'status': 'lost' if lost else 'cancelled', 'render_revision': job['revision']}
    try:
        bpy.context.view_layer.update()
        stale = _revision != job['revision']
        if completed and not stale:
            image = bpy.data.images.get('Render Result')
            if image is None or not image.has_data:
                raise RuntimeError('missing_pixels')
            with tempfile.TemporaryDirectory(prefix='mixar_preview_') as folder:
                path = folder + '/preview.png'
                fmt = scene.render.image_settings.file_format
                try:
                    scene.render.image_settings.file_format = 'PNG'
                    image.save_render(path, scene=scene)
                finally:
                    scene.render.image_settings.file_format = fmt
                with open(path, 'rb') as handle:
                    pixels = handle.read(4000001)
            if len(pixels) > 4000000:
                raise RuntimeError('image_too_large')
            result.update(status='done', image_url='data:image/png;base64,' + base64.b64encode(pixels).decode('ascii'))
        elif completed:
            result.update(status='stale', error='scene_changed_during_render')
    except Exception:
        # Errors can embed local temp paths. Only fixed codes leave this module.
        result.update(status='failed', error='preview_image_unavailable')
    finally:
        try:
            _restore(job)
        except (ReferenceError, RuntimeError):
            result.update(status='failed', error='scene_unavailable')
            result.pop('image_url', None)
        _job = None
        _remove_render_handlers()
        result['scene_revision'] = _revision
        result['finished_at'] = time.monotonic()
        _publish(key, result)
    return None


def _schedule(completed):
    # Called on Blender's render job thread: touch plain Python state only,
    # then schedule RNA/image processing on the main-loop timer.
    job = _job
    if job is not None:
        job['finishing'] = True
        key = job['key']
        bpy.app.timers.register(lambda: _finish(key, completed), first_interval=0.1)


def _complete(_scene, _depsgraph=None):
    _schedule(True)


def _cancelled(_scene, _depsgraph=None):
    _schedule(False)


def _before_load(_unused):
    global _job, _revision
    _job = None
    _revision += 1
    _records.clear()
    _remove_render_handlers()


def _install():
    for handlers, callback in ((bpy.app.handlers.depsgraph_update_post, _changed),
                               (bpy.app.handlers.load_pre, _before_load)):
        if callback not in handlers:
            handlers.append(callback)


def poll(key):
    """Read-only result delivery, including changes since render completion."""
    if _job and _job['key'] == key:
        if (not _job['finishing'] and time.monotonic() - _job['started_at'] > 2
                and not bpy.app.is_job_running('RENDER')):
            _finish(key, False, lost=True)
        else:
            return {'job_id': key, 'status': 'running', 'render_revision': _job['revision']}
    value = dict(_records.get(key, {'job_id': key, 'status': 'lost'}))
    if value.get('status') == 'done':
        bpy.context.view_layer.update()
        if value['scene_revision'] != _revision:
            value.update(status='stale', error='scene_changed_after_render')
            value.pop('image_url', None)
    return value


def start(context, key):
    global _job
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        return {'status': 'failed', 'error': 'invalid_job_id'}
    _install()
    if key in _records or (_job and _job['key'] == key):
        return poll(key)  # Idempotent kickoff; never repeat a lost acknowledgement.
    if _job is not None:
        poll(_job['key'])  # Recover lost completion before deciding it is busy.
    if _job is not None or bpy.app.is_job_running('RENDER'):
        return {'job_id': key, 'status': 'busy', 'error': 'another_render_running'}
    scene = context.scene
    win = context.window or next(iter(context.window_manager.windows), None)
    if scene.camera is None or win is None or bpy.app.background:
        return {'job_id': key, 'status': 'failed', 'error': 'camera_and_window_required'}
    settings = []
    def set_value(owner, name, value):
        settings.append((owner, name, getattr(owner, name), value))
        setattr(owner, name, value)
    job = {'key': key, 'scene': scene, 'settings': settings, 'started_at': time.monotonic(),
           'revision': _revision, 'finishing': False}
    _job = job
    try:
        render = scene.render
        scale = min(1.0, 768 / max(render.resolution_x, render.resolution_y))
        set_value(render, 'resolution_x', max(1, round(render.resolution_x * scale)))
        set_value(render, 'resolution_y', max(1, round(render.resolution_y * scale)))
        set_value(render, 'resolution_percentage', 100)
        set_value(render.image_settings, 'file_format', 'PNG')
        set_value(scene.cycles, 'samples', min(scene.cycles.samples, 32))
        bpy.context.view_layer.update()
        bpy.app.handlers.render_complete.append(_complete)
        bpy.app.handlers.render_cancel.append(_cancelled)
        # Preview results go to the agent; do not open an image-editor window.
        view = context.preferences.view
        display = view.render_display_type
        try:
            view.render_display_type = 'NONE'
            with bpy.context.temp_override(window=win, scene=scene):
                result = bpy.ops.render.render('INVOKE_DEFAULT', write_still=False)
        finally:
            view.render_display_type = display
        if 'RUNNING_MODAL' not in result:
            raise RuntimeError('async_render_not_started')
        bpy.context.view_layer.update()
        job['revision'] = _revision
        return {'job_id': key, 'status': 'running', 'render_revision': _revision}
    except Exception:
        _remove_render_handlers()
        _restore(job)
        _job = None
        value = {'job_id': key, 'status': 'failed', 'error': 'async_render_unavailable'}
        _publish(key, value)
        return value
