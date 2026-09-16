# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One command choice point for composed messages, interjections and answers."""
from dataclasses import dataclass
from typing import Optional

from ..constants import SessionState, STATE_LABELS
from .session import get_session_manager

HINT_QUEUED = 'queued'
HINT_UNDELIVERED = 'could not be delivered'


@dataclass
class OutgoingMessage:
    text: str
    image_attachments: Optional[list] = None
    attachment_names: Optional[list] = None
    imported_object_names: Optional[list] = None
    project_context: Optional[dict] = None
    mark_context: Optional[dict] = None
    user_message: object = None


def can_send(scene):
    from .turn_checkpoints import rewind_in_flight
    if rewind_in_flight():
        return False, 'Restoring a checkpoint…'
    session = get_session_manager()
    state = session.get_state(scene)
    if state in (SessionState.IDLE, SessionState.MODIFYING, SessionState.AWAITING_INPUT):
        return True, ''
    if state == SessionState.BUSY and session.run_open(scene):
        return True, ''
    return False, STATE_LABELS.get(state, 'Agent is not connected')


def is_interjection(scene):
    session = get_session_manager()
    return session.get_state(scene) == SessionState.BUSY and session.run_open(scene)


def send_user_message(scene, msg):
    from mixar.modules.common.agent_rpc.client import get_client
    from .turn_transport import create_turn_handler
    from .question_ref import pending_question_ref, pending_interrupt_id
    from .rules import compose_wire_message, mark_rules_sent
    allowed, reason = can_send(scene)
    if not allowed:
        return False, reason
    try:
        client = get_client()
    except Exception as exc:
        return False, str(exc)
    session = get_session_manager()
    state = session.get_state(scene)
    handler = create_turn_handler(scene_name=scene.name)
    interjecting = is_interjection(scene)
    if state in (SessionState.MODIFYING, SessionState.AWAITING_INPUT):
        ok = handler.start_input_stream(
            session_id=session.get_session_id(scene),
            action='modify' if state == SessionState.MODIFYING else 'respond',
            text=msg.text, question_ref=pending_question_ref(scene),
            user_message=msg.user_message,
            interrupt_id=pending_interrupt_id(scene), attachments=[
                {"type": "image_url", "image_url": {"url":
                 f"data:{img.get('mime_type', 'image/png')};base64,{img.get('base64', '')}"}}
                for img in (msg.image_attachments or [])],
        )
        if ok:
            session.set_state(scene, SessionState.BUSY)
            session.clear_streaming()
        return ok, '' if ok else 'Failed to send input'
    wire_message = compose_wire_message(scene, msg.text)
    sid = session.get_session_id(scene) if state == SessionState.BUSY else session.start_session(scene, msg.text)
    ok = handler.start_stream(
        message=wire_message, instance_id=client.connection_id, session_id=sid,
        plan_required=getattr(scene, 'mixie_chat_plan_enabled', True),
        execution_required=True, approval_required=True,
        image_attachments=msg.image_attachments, attachment_names=msg.attachment_names,
        imported_object_names=msg.imported_object_names,
        project_context=msg.project_context, mark_context=msg.mark_context,
        user_message=msg.user_message, interjecting=interjecting,
    )
    if ok:
        mark_rules_sent(scene)
    return ok, '' if ok else 'Failed to send message'
