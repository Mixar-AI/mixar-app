# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deferred retry-chip dispatch, with recoverable failure and click deduplication."""

from uuid import uuid4

import bpy

from . import parked_resume
from .ui_utils import redraw_chat_areas

_pending = set()
FAILURE_MESSAGE = (
    "Couldn't send the retry. Check your connection and wait for any current "
    "turn to finish, then click Retry failed tasks again."
)


def _notify_failure(scene):
    notice = scene.mixie_chat_messages.add()
    notice.bubble_id = str(uuid4())
    notice.sender = 'AGENT'
    notice.message_type = 'AGENT'
    notice.content = FAILURE_MESSAGE


def schedule_retry(scene, bubble_id):
    """Leave the chip intact until the normal send operator accepts the retry.

    Only primitive identity crosses the timer boundary: neither the operator,
    its context, nor scene/message RNA is retained while windows can close.
    """
    scene_uid = scene.session_uid
    session_id = scene.mixie_session_id
    key = (scene_uid, bubble_id)
    if key in _pending:
        return
    _pending.add(key)

    def _send_later():
        try:
            target = next((sc for sc in bpy.data.scenes if sc.session_uid == scene_uid), None)
            if target is None or target.mixie_session_id != session_id:
                return None
            message = next((m for m in target.mixie_chat_messages if m.bubble_id == bubble_id), None)
            if message is None or not any(a.value == 'retry_failed_tasks' for a in message.action_items):
                return None
            with bpy.context.temp_override(scene=target):
                sent = parked_resume.send_continue(target)
            if sent:
                # Re-resolve after the send/checkpoint; don't retain message RNA.
                for current in target.mixie_chat_messages:
                    if current.bubble_id == bubble_id:
                        current.action_items.clear()
                        break
            else:
                _notify_failure(target)
            redraw_chat_areas()
        finally:
            _pending.discard(key)
        return None

    try:
        bpy.app.timers.register(_send_later, first_interval=0.0)
    except Exception:
        _pending.discard(key)
        raise
