# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread dictation coordinator: native PCM → backend → editable draft."""
import queue
import time
from types import SimpleNamespace
from uuid import uuid4

from mixar.config.logging_config import get_logger
from .voice_input.composer import Draft
from ..constants import (VOICE_EVENT_POLL_S, VOICE_TOAST_ID,
                         VOICE_STARTUP_TIMEOUT_S, VOICE_SESSION_GRACE_S)

_session = None
logger = get_logger(__name__)


def available():
    try:
        import aud
        return hasattr(aud, '_mixar_capture_open')
    except ImportError:
        return False


def is_listening(wm=None):
    return _session is not None


def _identity(scene):
    from .session import get_session_manager
    from .question_ref import pending_question_ref, pending_interrupt_id
    return (scene.as_pointer(), get_session_manager().get_session_id(scene),
            str(pending_question_ref(scene)), pending_interrupt_id(scene),
            getattr(scene, 'mixie_chat_mode', ''))


def _attachments(scene):
    return tuple((item.as_pointer(), getattr(item, 'name', ''))
                 for item in scene.mixie_chat_pending_attachments)


def toggle(context):
    if _session:
        if _session.state == 'Finishing':
            cancel()
        else:
            try:
                stop()
            except Exception as exc:
                logger.warning('Dictation capture finalization failed: %s', exc)
                _finish()
                _toast('warning', 'Voice could not finish. Your draft was preserved.')
        return 'stopped'
    return start(context)


def start(context):
    global _session
    import bpy
    from mixar.config.config import get_server_url
    from ...auth.core.auth import get_access_token
    from .voice_input.transport import Transport
    from . import scribble
    if not available():
        return 'unavailable'
    scene = context.scene
    if not scene:
        return 'no_scene'
    if scribble.is_busy() or scribble.is_canvas_open(context.window_manager):
        _toast('warning', 'Finish handwriting before starting voice input.')
        return 'unavailable'
    token = get_access_token()
    if not token:
        _toast('warning', 'Sign in to use voice input.')
        return 'unavailable'
    scribble.release_composer()
    sid = str(uuid4())
    _session = SimpleNamespace(
        scene=scene, window=context.window.as_pointer(),
        draft=Draft(scene.mixie_chat_input, _identity(scene)),
        attachments=_attachments(scene), transport=Transport(get_server_url(), token, sid),
        capture=None, state='Permission', began=time.monotonic(), recording_at=None,
        started=False, max_seconds=180, auth_checked=time.monotonic(),
        deadline=time.monotonic() + VOICE_STARTUP_TIMEOUT_S,
    )
    if _on_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_load)
    _status('Connecting')
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=VOICE_EVENT_POLL_S)
    return 'started'


def stop():
    import aud
    s = _session
    if not s or s.state == 'Finishing':
        return
    if s.capture is None:
        cancel()
        return
    s.transport.feed(aud._mixar_capture_stop(s.capture))
    s.capture = None
    s.transport.stop()
    s.state = 'Finishing'
    _status(s.state)


def defer_send(context):
    """True consumes this click. Final success may re-run normal Send once."""
    s = _session
    if not s:
        return False
    if s.scene != context.scene or _identity(s.scene) != s.draft.identity:
        cancel()
        return True
    s.draft.pending_send = True
    s.draft.base = s.scene.mixie_chat_input
    s.attachments = _attachments(s.scene)
    try:
        stop()
    except Exception as exc:
        logger.warning('Dictation capture finalization failed: %s', exc)
        _finish()
        _toast('warning', 'Voice could not finish. Your draft was preserved.')
    return True


def cancel():
    _finish()


def _on_load(_):
    cancel()


def reset_state():
    cancel()


def _finish(app_exit=False):
    global _session
    s, _session = _session, None
    if s:
        s.transport.cancel()
        if s.capture is not None:
            import aud
            try:
                aud._mixar_capture_stop(s.capture)
            except Exception:
                pass
            s.capture = None
    if not app_exit:
        _status('')


def shutdown(app_exit=False):
    _finish(app_exit=app_exit)


def _tick():
    import aud
    import bpy
    s = _session
    if not s:
        return None
    try:
        from ...auth.core.auth import get_access_token
        if time.monotonic() - s.auth_checked > 1:
            s.auth_checked = time.monotonic()
            if not get_access_token():
                cancel()
                return None
        if (bpy.context.scene != s.scene
                or _identity(s.scene) != s.draft.identity
                or not any(w.as_pointer() == s.window for w in bpy.context.window_manager.windows)):
            cancel()
            return None
        if time.monotonic() > s.deadline:
            raise TimeoutError('Voice input timed out. Please try again.')
        if s.scene.mixie_chat_input != s.draft.base or _attachments(s.scene) != s.attachments:
            s.draft.pending_send = False
        if s.state == 'Permission':
            permission = aud._mixar_capture_permission()
            if permission == -2:
                raise RuntimeError('Launch Mixar from Finder to allow microphone access.')
            if permission < 0:
                raise RuntimeError('Allow microphone access for Mixar in system privacy settings.')
            if permission == 1:
                s.transport.start()
                s.started = True
                s.state = 'Connecting'
        if s.capture is not None:
            data = aud._mixar_capture_read(s.capture)
            if data:
                s.transport.feed(data)
            if time.monotonic() - s.recording_at >= s.max_seconds - .25:
                stop()
        for _ in range(32):
            try:
                event = s.transport.events.get_nowait()
            except queue.Empty:
                break
            kind = event.get('type')
            if kind == 'ready':
                s.max_seconds = int(event['max_duration_seconds'])
                s.capture = aud._mixar_capture_open()
                s.recording_at = time.monotonic()
                s.deadline = s.recording_at + s.max_seconds + VOICE_SESSION_GRACE_S
                s.state = 'Listening'
                _status(s.state)
            elif kind == 'max_duration_reached':
                if s.capture is not None:
                    aud._mixar_capture_stop(s.capture)
                    s.capture = None
                s.state = 'Finishing'
                _status(s.state)
            elif kind == 'error':
                raise RuntimeError(event.get('message', 'Voice input failed.'))
            elif kind == 'final':
                text, send = s.draft.final(event.get('text', ''), s.scene.mixie_chat_input, _identity(s.scene))
                if _attachments(s.scene) != s.attachments:
                    send = False
                scene = s.scene
                _finish()
                if text is None:
                    _toast('info', "Didn't catch that. Please try speaking again.")
                else:
                    from . import scribble
                    scribble.release_composer()
                    scene.mixie_chat_input = text
                    scribble.redraw_chat()
                    if send:
                        bpy.ops.mixie_chat.send_message()
                return None
    except Exception as exc:
        _finish()
        _toast('warning', 'Voice audio could not keep up. Please try again.' if isinstance(exc, queue.Full) else str(exc))
        return None
    return VOICE_EVENT_POLL_S


def _status(text):
    import bpy
    wm = bpy.context.window_manager
    if wm and hasattr(wm, 'mixie_chat_voice_listening'):
        wm.mixie_chat_voice_listening = bool(text)
        wm.mixie_chat_voice_status = text
    from . import scribble
    scribble.redraw_chat()


def _toast(level, message):
    from mixar.modules.common.notifications import get_notification_store
    get_notification_store().push(level, message, '', id=VOICE_TOAST_ID)
