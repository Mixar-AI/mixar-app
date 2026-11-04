# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Messages typed while a turn streams before its backend run is open.

``can_send`` refuses while the scene is BUSY and the run is not open: the
first moments of every turn (before ``run_status in_progress``) and a
chat-only turn that never opens one. The composer never refuses for that:
the message is held here as a user bubble labelled "Queued until Mixie is
ready", and a short main-thread timer decides what happens to it:

- the run opens (a task is really running): the text is sent into it as a
  steer, one message per tick;
- the turn ends any other way (a chat-only reply, a refusal, an error, a lost
  connection): the bubble goes and the text returns to the front of the
  composer for the user to send. Nothing is sent on their behalf after a
  refusal, so a "resend after sign-in" keeps the original request.

A held message is its text only; images and marks in the composer belong to
the message being written now. Stop and New chat hand held text back too, and
a send that does not go out (the operator cancels) puts the text back rather
than losing it. Entries are keyed by the scene's ``session_uid``, so renaming
a tab never strands one; a chat cleared another way (file load, history
restore) takes the bubble with it and the entry is dropped.
"""
import uuid

import bpy

from mixar.config.logging_config import get_logger

from ..constants import HINT_QUEUED, SessionState

logger = get_logger(__name__)

HELD_PREFIX = "held_"
_INTERVAL = 0.25
_held: dict = {}  # scene.session_uid -> [(bubble_id, text)]
_flushing = {'active': False}


def should_hold(scene) -> bool:
    """BUSY with no open run: a send now has nothing to join yet."""
    from .session import get_session_manager
    session = get_session_manager()
    return session.get_state(scene) == SessionState.BUSY and not session.run_open(scene)


def is_flushing() -> bool:
    """True while a held message is being sent (it goes out as text only)."""
    return _flushing['active']


def _key(scene) -> int:
    return int(scene.session_uid)


def held_count(scene) -> int:
    return len(_held.get(_key(scene), ()))


def hold(scene, text: str) -> None:
    msg = scene.mixie_chat_messages.add()
    msg.sender = 'USER'
    msg.text = text
    bubble_id = f"{HELD_PREFIX}{uuid.uuid4().hex[:12]}"
    msg.bubble_id = bubble_id
    msg.delivery_hint = HINT_QUEUED
    _held.setdefault(_key(scene), []).append((bubble_id, text))
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=_INTERVAL)


def _bubble_index(scene, bubble_id: str) -> int:
    for i, m in enumerate(scene.mixie_chat_messages):
        if getattr(m, 'bubble_id', '') == bubble_id:
            return i
    return -1


def _remove_bubble(scene, bubble_id: str) -> None:
    i = _bubble_index(scene, bubble_id)
    if i >= 0:
        scene.mixie_chat_messages.remove(i)


def _to_composer(scene, text: str) -> None:
    """Put ``text`` at the front of the draft. An active text edit is exited
    first (as voice input does): its private buffer would otherwise be
    written back over the property and erase the words."""
    if not text:
        return
    from ..constants import CHAT_INPUT_MAXLEN
    from . import composer_limit, scribble
    scribble.release_composer()
    draft = scene.mixie_chat_input
    joined = f"{text}\n{draft}" if draft else text
    scene.mixie_chat_input = composer_limit.clamp(joined, CHAT_INPUT_MAXLEN)[0]


def release(scene) -> str:
    """Drop the scene's held messages and their bubbles; returns their text."""
    items = _held.pop(_key(scene), [])
    for bubble_id, _text in items:
        _remove_bubble(scene, bubble_id)
    return "\n".join(text for _bid, text in items)


def restore(scene) -> None:
    """Held text goes back to the front of the composer (Stop, New chat, a
    turn that ended without a running task)."""
    _to_composer(scene, release(scene))


def _decide(scene) -> str:
    """'send' into a running task, 'wait' for one, or 'restore' the text."""
    from .composer_send import can_send
    from .session import get_session_manager
    session = get_session_manager()
    if session.run_open(scene):
        state = session.get_state(scene)
        if state in (SessionState.BUSY, SessionState.IDLE) and can_send(scene)[0]:
            return 'send'
        return 'wait'  # a question or plan edit is answered by the user first
    return 'wait' if should_hold(scene) else 'restore'


def _scene_for(key: int):
    return next((s for s in bpy.data.scenes if int(s.session_uid) == key), None)


def _window_for(scene):
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            if window.scene is scene:
                return window
    return None


def _send(scene, text: str) -> None:
    override = {'scene': scene}
    window = _window_for(scene)
    if window is not None:
        override['window'] = window
    _flushing['active'] = True
    result = set()
    try:
        with bpy.context.temp_override(**override):
            result = bpy.ops.mixie_chat.send_message('EXEC_DEFAULT', message_override=text)
    except Exception:  # noqa: BLE001
        logger.warning("Held message could not be sent", exc_info=True)
    finally:
        _flushing['active'] = False
    if 'FINISHED' not in result:
        # Not sent (no connection, a refusal before the wire, an error):
        # the words go back to the composer instead of disappearing.
        _to_composer(scene, text)


def _tick():
    for key in list(_held):
        scene = _scene_for(key)
        items = [it for it in _held.get(key, []) if scene and _bubble_index(scene, it[0]) >= 0]
        if not items:
            _held.pop(key, None)
            continue
        _held[key] = items
        decision = _decide(scene)
        if decision == 'restore':
            restore(scene)
        elif decision == 'send':
            bubble_id, text = items.pop(0)
            if not items:
                _held.pop(key, None)
            _remove_bubble(scene, bubble_id)
            _send(scene, text)
    return _INTERVAL if _held else None


def clear_all() -> None:
    _held.clear()
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:  # noqa: BLE001
        pass
