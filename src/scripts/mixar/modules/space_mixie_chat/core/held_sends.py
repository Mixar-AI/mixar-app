# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Messages sent while a turn streams before its backend run is open.

``can_send`` refuses while the scene is BUSY and the run is not open: the
first moments of every turn (before ``run_status in_progress``) and a
chat-only turn that never opens one. The composer never refuses for that:
the message is held here, shown as a user bubble labelled "Queued until
Mixie is ready", and a short main-thread timer sends it the moment it can
go, as an interjection once the run opens or as a fresh turn once the turn
is idle. One held message goes per tick, so a second one held behind a
fresh turn joins that turn once its run opens.

Stop and New chat hand held text back to the composer (``restore``), so
nothing typed is lost. A chat cleared some other way (file load, history
restore) takes the bubble with it and the timer drops the entry.
"""
import uuid

import bpy

from mixar.config.logging_config import get_logger

from ..constants import HINT_QUEUED, SessionState

logger = get_logger(__name__)

HELD_PREFIX = "held_"
_INTERVAL = 0.25
_held: dict = {}  # scene name -> [(bubble_id, text)]
_flushing = {'active': False}


def should_hold(scene) -> bool:
    """BUSY with no open run: a send now has nothing to join yet."""
    from .session import get_session_manager
    session = get_session_manager()
    return session.get_state(scene) == SessionState.BUSY and not session.run_open(scene)


def is_flushing() -> bool:
    """True while a held message is being sent (telemetry marks it held)."""
    return _flushing['active']


def held_count(scene) -> int:
    return len(_held.get(scene.name, ()))


def hold(scene, text: str) -> None:
    msg = scene.mixie_chat_messages.add()
    msg.sender = 'USER'
    msg.text = text
    bubble_id = f"{HELD_PREFIX}{uuid.uuid4().hex[:12]}"
    msg.bubble_id = bubble_id
    msg.delivery_hint = HINT_QUEUED
    _held.setdefault(scene.name, []).append((bubble_id, text))
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


def release(scene) -> str:
    """Drop the scene's held messages and their bubbles; returns their text."""
    items = _held.pop(scene.name, [])
    for bubble_id, _text in items:
        _remove_bubble(scene, bubble_id)
    return "\n".join(text for _bid, text in items)


def restore(scene) -> None:
    """Stop / New chat: held text goes back to the front of the composer."""
    text = release(scene)
    if text:
        draft = scene.mixie_chat_input
        scene.mixie_chat_input = f"{text}\n{draft}" if draft else text


def _ready(scene) -> bool:
    """Idle, or busy with an open run. A question (AWAITING_INPUT) or a plan
    edit (MODIFYING) is answered by the user, never by a held message."""
    from .composer_send import can_send
    from .session import get_session_manager
    state = get_session_manager().get_state(scene)
    if state not in (SessionState.IDLE, SessionState.BUSY) or should_hold(scene):
        return False
    return can_send(scene)[0]


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
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.mixie_chat.send_message('EXEC_DEFAULT', message_override=text)
    except Exception:  # noqa: BLE001 — put the words back rather than lose them
        logger.warning("Held message could not be sent", exc_info=True)
        draft = scene.mixie_chat_input
        scene.mixie_chat_input = f"{text}\n{draft}" if draft else text
    finally:
        _flushing['active'] = False


def _tick():
    for name in list(_held):
        scene = bpy.data.scenes.get(name)
        items = [it for it in _held.get(name, []) if scene and _bubble_index(scene, it[0]) >= 0]
        if not items:
            _held.pop(name, None)
            continue
        _held[name] = items
        if not _ready(scene):
            continue
        bubble_id, text = items.pop(0)
        if not items:
            _held.pop(name, None)
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
