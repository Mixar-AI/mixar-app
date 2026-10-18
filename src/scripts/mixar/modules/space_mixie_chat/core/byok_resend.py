# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Resend a chat/input command a BYOK refusal stopped — the user never retypes.

`turn_transport._send` remembers the refused command here (method, payload,
the user bubble's command id) when its receipt carries a ``byok_*`` code or
a guest's ``login_required``; the key-missing card (`byok_card`), a
successful save in AI Provider Settings (`byok/core/key_prompt`), the
cold-start fetch (`byok_notice`) and a settled sign-in notice
(`login_notice`) call `resend`, which re-enters the transport with a NEW command id: the backend
journals the refusal under the old id and would answer a repeat with the
cached failure. `turn_credentials.prepare` attaches whatever this device
holds now (a key just saved, nothing after a removal), so the server decides
again. One record per session; the payload never carries key material
(the BYOK fields are stripped) and nothing here is logged.
"""

from dataclasses import dataclass, field
from typing import Optional

from mixar.modules.byok.constants import BYOK_TURN_ACCOUNT_FIELD, BYOK_TURN_KEY_FIELD

_SECRET_FIELDS = (BYOK_TURN_KEY_FIELD, BYOK_TURN_ACCOUNT_FIELD)


@dataclass
class RefusedCommand:
    session_id: str
    command_id: str
    method: str
    payload: dict = field(default_factory=dict)
    interjecting: bool = False
    # True when this command was already an automatic (cold-start) resend:
    # a second refusal shows the card instead of resending again.
    auto_resent: bool = False


_records: dict = {}
_auto_ids: set = set()


def remember(session_id: str, command_id: str, method: str, payload: dict, interjecting: bool) -> None:
    """Keep the refused command (main thread, from the settled receipt)."""
    clean = {key: value for key, value in (payload or {}).items() if key not in _SECRET_FIELDS}
    _records[session_id] = RefusedCommand(
        session_id=session_id, command_id=command_id, method=method, payload=clean,
        interjecting=bool(interjecting), auto_resent=command_id in _auto_ids,
    )
    _auto_ids.discard(command_id)


def pending(session_id: str) -> Optional[RefusedCommand]:
    return _records.get(session_id)


def forget(session_id: str) -> None:
    _records.pop(session_id, None)


def resend(session_id: str, *, automatic: bool = False) -> bool:
    """Send the remembered command again under a new command id.

    False when there is nothing to resend, the scene is gone, or the
    session cannot take a send right now (another turn is streaming with
    no open run) — the caller tells the user. ``automatic`` marks the new
    command as a one-shot cold-start resend (see `RefusedCommand`).
    """
    record = _records.pop(session_id, None)
    if record is None:
        return False
    scene = _scene_for(session_id)
    if scene is None:
        return False
    from .composer_send import can_send, is_interjection
    allowed, _reason = can_send(scene)
    if not allowed:
        _records[session_id] = record
        return False
    interjecting = is_interjection(scene)
    handler = _handler_for(scene)
    bubble = _user_bubble(scene, record.command_id)
    _begin_turn(scene, interjecting)
    sent = handler._send(record.method, dict(record.payload), user_message=bubble,
                         interjecting=interjecting)
    if not sent:
        _records[session_id] = record
        return False
    if automatic:
        _auto_ids.add(handler.last_command_id)
    return True


# ---------------------------------------------------------------------------
# Seams (monkeypatched by tests)
# ---------------------------------------------------------------------------

def _scene_for(session_id: str):
    import bpy

    from mixar.modules.common.agent_execution.document import scene_for_session
    return scene_for_session(session_id, bpy)


def _handler_for(scene):
    from .turn_transport import create_turn_handler, get_turn_handler
    return get_turn_handler(scene.name) or create_turn_handler(scene_name=scene.name)


def _user_bubble(scene, command_id: str):
    for item in scene.mixie_chat_messages:
        if getattr(item, 'sender', '') == 'USER' and getattr(item, 'bubble_id', '') == command_id:
            return item
    return None


def _begin_turn(scene, interjecting: bool) -> None:
    """The composer's bookkeeping for a fresh turn: BUSY, a cleared stream
    and the optimistic "Thinking…" placeholder (an interjection joins the
    open run and changes nothing)."""
    if interjecting:
        return
    from ..constants import SessionState
    from .message_helpers import add_turn_placeholder
    from .session import get_session_manager
    session = get_session_manager()
    session.set_state(scene, SessionState.BUSY)
    session.clear_streaming()
    add_turn_placeholder(scene)
