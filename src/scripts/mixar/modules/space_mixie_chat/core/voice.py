# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread dictation coordinator: native PCM → backend → editable draft."""
import queue
import time
from types import SimpleNamespace
from uuid import uuid4

from mixar.config.logging_config import get_logger
from .voice_input.composer import Draft
from ..constants import (VOICE_EVENT_POLL_S, VOICE_TOAST_ID, VOICE_TOAST_TTL_MS,
                         VOICE_STARTUP_TIMEOUT_S, VOICE_SESSION_GRACE_S, VOICE_BUFFER_SECONDS)

_session = None
_last_timings = {}
# True only while a hold of Option/Alt owns the session. A click on the Voice
# control starts a session this flag does not own, so releasing the key must
# not stop it.
_ptt_owned = False
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


def push_to_talk_owned():
    return _ptt_owned


def push_to_talk_begin(context, field_token="", chat_target=False):
    """Start dictation for a held Option/Alt. A click-started session stays as it is."""
    global _ptt_owned
    if _ptt_owned:
        return 'holding'
    if _session is not None:
        return 'busy'
    outcome = (start(context, field_token=field_token, chat_target=chat_target)
               if field_token else start(context))
    if outcome == 'started':
        _ptt_owned = True
    return outcome


def push_to_talk_end(discard=False):
    """Finish a hold. Release keeps the words; Esc drops them."""
    global _ptt_owned
    if not _ptt_owned:
        return 'ignored'
    _ptt_owned = False
    if discard or _session is None:
        if _session is not None:
            cancel()
        return 'cancelled' if discard else 'stopped'
    try:
        stop()
    except Exception as exc:
        logger.warning('Dictation capture finalization failed: %s', exc)
        _finish()
        _toast('warning', 'Voice could not finish. Your draft was preserved.')
    return 'stopped'


def start(context, field_token="", chat_target=False):
    global _session
    clicked_at = time.monotonic()
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
    if not field_token:
        scribble.release_composer()
    sid = str(uuid4())
    _session = SimpleNamespace(
        scene=scene, window=context.window.as_pointer(), field_token=field_token,
        field_chat_identity=_identity(scene) if chat_target else None,
        area=context.area.as_pointer() if context.area else None,
        draft=None if field_token else Draft(scene.mixie_chat_input, _identity(scene)),
        attachments=() if field_token else _attachments(scene), transport=Transport(get_server_url(), token, sid),
        capture=None, state='Permission', began=clicked_at, recording_at=None,
        started=False, ready=False, max_seconds=180, auth_checked=time.monotonic(),
        deadline=time.monotonic() + VOICE_STARTUP_TIMEOUT_S,
    )
    if field_token:
        from .voice_input import fields
        fields.begin(context.window_manager, field_token)
    _session.transport.began = clicked_at
    if _on_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_load)
    try:
        _begin_capture(_session)
    except Exception as exc:
        _finish()
        _toast('warning', str(exc))
        return 'unavailable'
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=VOICE_EVENT_POLL_S)
    return 'started'


def _begin_capture(s):
    import aud
    if not hasattr(s, 'permission_at'):
        s.permission_at = time.monotonic()
        s.transport.timings['local_setup_ms'] = round((s.permission_at - s.began) * 1000, 1)
    permission = aud._mixar_capture_permission()
    if permission == -2:
        raise RuntimeError('Launch Mixar from Finder to allow microphone access.')
    if permission < 0:
        raise RuntimeError('Allow microphone access for Mixar in system privacy settings.')
    if permission != 1:
        _status('Allow microphone')
        return
    opening = time.monotonic()
    s.transport.timings['permission_wait_ms'] = round((opening - s.permission_at) * 1000, 1)
    s.capture = aud._mixar_capture_open()
    s.recording_at = time.monotonic()
    s.transport.timings['capture_open_ms'] = round((s.recording_at - opening) * 1000, 1)
    s.transport.timings['click_to_capture_ms'] = round((s.recording_at - s.began) * 1000, 1)
    logger.info('Dictation capture timings %s', s.transport.timings)
    s.state = 'Listening'
    _status(s.state)
    s.transport.start()
    s.started = True


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
    if getattr(s, 'field_token', ''):
        # A field hold never inherits a click on the chat Send button.
        cancel()
        return True
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


def cancel_field(context, token):
    """A stale field cannot cancel another field or a click-started session."""
    from .voice_input import fields
    if _session is not None and getattr(_session, 'field_token', '') == token:
        cancel()
    fields.clear(context.window_manager, token)


def _on_load(_):
    cancel()


def reset_state():
    cancel()


def _finish(app_exit=False):
    global _session, _last_timings, _ptt_owned
    _ptt_owned = False
    s, _session = _session, None
    if s:
        _last_timings = dict(getattr(s.transport, 'timings', {}))
        s.transport.cancel()
        if s.capture is not None:
            import aud
            try:
                aud._mixar_capture_stop(s.capture)
            except Exception:
                pass
            s.capture = None
    if not app_exit:
        if s and getattr(s, 'field_token', ''):
            import bpy
            from .voice_input import fields
            fields.clear(bpy.context.window_manager, s.field_token)
        _status('')


def shutdown(app_exit=False):
    _finish(app_exit=app_exit)
    from .voice_input import warmup
    warmup.shutdown()


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
        field_token = getattr(s, 'field_token', '')
        if (bpy.context.scene != s.scene
                or (not field_token and _identity(s.scene) != s.draft.identity)
                or (getattr(s, "field_chat_identity", None) is not None
                    and _identity(s.scene) != s.field_chat_identity)
                or not any(w.as_pointer() == s.window for w in bpy.context.window_manager.windows)):
            cancel()
            return None
        if time.monotonic() > s.deadline:
            raise TimeoutError('Voice input timed out. Please try again.')
        if s.recording_at is not None and not s.ready and time.monotonic() - s.recording_at > VOICE_BUFFER_SECONDS:
            raise TimeoutError('Voice could not connect. Your draft was preserved. Please try again.')
        if not field_token and (s.scene.mixie_chat_input != s.draft.base
                                or _attachments(s.scene) != s.attachments):
            s.draft.pending_send = False
        if s.state == 'Permission':
            _begin_capture(s)
        if s.capture is not None:
            data = aud._mixar_capture_read(s.capture)
            if data:
                s.transport.feed(data)
                _publish_level(s, data)
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
                s.ready = True
                s.deadline = s.recording_at + s.max_seconds + VOICE_SESSION_GRACE_S
            elif kind == 'max_duration_reached':
                if s.capture is not None:
                    aud._mixar_capture_stop(s.capture)
                    s.capture = None
                s.state = 'Finishing'
                _status(s.state)
            elif kind == 'error':
                raise RuntimeError(event.get('message', 'Voice input failed.'))
            elif kind == 'final':
                if field_token:
                    from .voice_input import fields
                    _finish()
                    fields.publish(bpy.context.window_manager, field_token, event.get('text', ''))
                    if not bpy.context.window_manager.mixie_chat_voice_field_text:
                        _toast('info', "Didn't catch that. Please try speaking again.")
                    return None
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
                    else:
                        _focus_composer(s)
                return None
    except Exception as exc:
        _finish()
        _toast('warning', 'Voice audio could not keep up. Please try again.' if isinstance(exc, queue.Full) else str(exc))
        return None
    return VOICE_EVENT_POLL_S


def _focus_composer(session):
    """Return editing to the originating live surface without opening a window."""
    import bpy
    for window in bpy.context.window_manager.windows:
        if window.as_pointer() != session.window or window.scene != session.scene:
            continue
        for area in window.screen.areas:
            if area.as_pointer() == session.area and area.type in {'AGENT_BUBBLE'}:
                with bpy.context.temp_override(window=window, area=area):
                    bpy.ops.mixie_chat.focus_composer()
                return


def _publish_level(session, data):
    """Feed the live Voice trace (island chip and Sketch pill) from this chunk.

    Presentation only: a failure here must never end the dictation."""
    import bpy
    from .voice_input import level
    try:
        session.level = level.next_level(getattr(session, 'level', 0.0), data)
        wm = bpy.context.window_manager
        published = float(getattr(wm, 'mixie_chat_voice_level', 0.0))
        if hasattr(wm, 'mixie_chat_voice_level') and level.should_write(published, session.level):
            wm.mixie_chat_voice_level = session.level
    except Exception as exc:  # noqa: BLE001
        logger.debug('Voice level update skipped: %s', exc)


def _status(text):
    import bpy
    wm = bpy.context.window_manager
    if wm and hasattr(wm, 'mixie_chat_voice_listening'):
        wm.mixie_chat_voice_listening = bool(text)
        wm.mixie_chat_voice_status = text
        if text != 'Listening' and hasattr(wm, 'mixie_chat_voice_level'):
            wm.mixie_chat_voice_level = 0.0
    from .voice_input import fields
    if not text or (_session and getattr(_session, 'field_token', '')):
        fields.show_status(text)
    from . import scribble
    scribble.redraw_chat()


def _toast(level, message):
    from mixar.modules.common.notifications import get_notification_store
    get_notification_store().push(level, message, '', id=VOICE_TOAST_ID,
                                  ttl_ms=VOICE_TOAST_TTL_MS)
