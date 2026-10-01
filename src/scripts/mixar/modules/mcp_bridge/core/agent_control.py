# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scene-bound MCP hand-off to the ordinary, authenticated chat workflow.

Called on the main thread only. The backend owns durable admission receipts;
the same command UUID follows the user bubble and WebSocket command. No MCP
script lease is held while the hosted agent owns the scene.
"""

import json

from . import lease


def _scene(session_id):
    bpy, session = lease._runtime()
    from mixar.modules.space_mixie_chat.constants import is_lane_scene
    matches = [s for s in bpy.data.scenes if session.get_session_id(s) == session_id]
    if len(matches) != 1 or is_lane_scene(matches[0]):
        raise ValueError("The selected scene is unavailable or ambiguous")
    return matches[0], session


def _messages(scene, command_id):
    messages = list(scene.mixie_chat_messages)
    start = next((i for i, m in enumerate(messages)
                  if m.sender == 'USER' and m.bubble_id == command_id), None)
    if start is None:
        raise ValueError("This task is unavailable in the selected scene's chat")
    end = next((i for i in range(start + 1, len(messages))
                if messages[i].sender == 'USER'), len(messages))
    return messages[start:end], end < len(messages)


def _question(message):
    result = {"input_type": message.input_type, "interrupt_id": message.interrupt_id,
              "text": message.content or message.text,
              "options": [{"label": a.label, "value": a.value} for a in message.action_items]}
    try:
        result['questions'] = json.loads(message.batched_questions or '[]')
    except ValueError:
        result['questions'] = []
    return result


def status(scene, session, command_id):
    from mixar.modules.space_mixie_chat.constants import SessionState
    messages, superseded = _messages(scene, command_id)
    current = session.get_state(scene)
    state = ('superseded' if superseded else
             'waiting_for_input' if current == SessionState.AWAITING_INPUT else
             'running' if current == SessionState.BUSY or session.run_open(scene) else
             'unavailable' if current == SessionState.OFFLINE else 'finished')
    visible = [m for m in messages[1:] if m.sender == 'AGENT']
    questions = [_question(m) for m in visible if m.input_type] if state == 'waiting_for_input' else []
    return {"success": True, "command_id": command_id, "state": state,
            "delivery_hint": messages[0].delivery_hint,
            # Persistent visible content only, never internal thinking/ephemeral slots.
            "messages": [(m.content or m.text)[:16000] for m in visible[-8:] if m.content or m.text],
            "questions": questions[-4:],
            "run_open": bool(session.run_open(scene))}


def dispatch(params):
    from mixar.modules.space_mixie_chat.constants import SessionState
    if not lease._enabled():
        return lease._failure('mcp_disabled', 'Enable Connect Claude / Codex in Mixar first')
    try:
        session_id = lease._uuid(params.get('session_id'))
        command_id = lease._uuid(params.get('command_id'))
        action = params.get('action')
        scene, session = _scene(session_id)
        if action == 'status':
            return status(scene, session, command_id)
        if lease.has_active_operation(session_id):
            raise ValueError('Wait for the active MCP tool to finish')
        current = session.get_state(scene)
        if action in ('respond', 'cancel'):
            target_id = lease._uuid(params.get('target_command_id'))
            _, superseded = _messages(scene, target_id)
            if superseded:
                raise ValueError('A newer chat turn is active; this task cannot control it')
        if action == 'cancel':
            if current not in (SessionState.BUSY, SessionState.AWAITING_INPUT) and not session.run_open(scene):
                raise ValueError('This task is no longer running')
            _cancel(scene, session_id, target_id, command_id)
            return {'success': True, 'command_id': command_id, 'state': 'cancel_requested'}
        if action not in ('start', 'respond'):
            raise ValueError('Unknown agent action')
        text = params.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > 16000:
            raise ValueError('Provide a nonempty task or response of at most 16000 characters')
        if action == 'start' and (current != SessionState.IDLE or session.run_open(scene)):
            raise ValueError('Wait for the current chat task to finish before starting another')
        if action == 'respond':
            from mixar.modules.space_mixie_chat.core.question_ref import pending_interrupt_id
            if (current != SessionState.AWAITING_INPUT or not params.get('interrupt_id')
                    or params['interrupt_id'] != pending_interrupt_id(scene)):
                raise ValueError('The question changed; check task status before answering')
            pending = status(scene, session, target_id)['questions']
            if any(q['input_type'] in ('file_open', 'file_save') for q in pending):
                raise ValueError('Complete the native file picker in Mixar')
        return _send(scene, params, action, command_id)
    except (ValueError, TypeError, AttributeError) as exc:
        return lease._failure('agent_unavailable', str(exc))


def _send(scene, params, action, command_id):
    from mixar.modules.space_mixie_chat.core.composer_send import OutgoingMessage, send_user_message
    from mixar.modules.space_mixie_chat.core import turn_checkpoints
    project_context = None
    if action == 'start' and getattr(scene, 'mixie_chat_mode', '') == 'ADDON_PROJECT':
        from mixar.modules.addon_project.context import build_project_context
        project_context = build_project_context(scene)
    checkpoint = turn_checkpoints.capture(scene, params['text']) if action == 'start' else None
    message = scene.mixie_chat_messages.add()
    message.sender = 'USER'
    message.text = params['text']
    message.bubble_id = command_id
    scene.mixie_chat_user_has_engaged = True
    ok, error = send_user_message(scene, OutgoingMessage(
        text=params['text'], project_context=project_context, user_message=message,
        command_id=command_id, answers=params.get('answers'),
    ))
    if not ok:
        return lease._failure('agent_send_failed', error)
    if checkpoint is not None:
        turn_checkpoints.bind_request(checkpoint, command_id)
    return {'success': True, 'command_id': command_id, 'state': 'submitted',
            'session_id': scene.mixie_session_id}


def _cancel(scene, session_id, target_id, command_id):
    from mixar.modules.common.agent_rpc.client import command
    from mixar.modules.space_mixie_chat.core.main_thread_executor import run_on_main_thread
    generation = lease.transport_generation()

    def settled(result):
        if not isinstance(result, dict) or result.get('code') or result.get('ok') is False:
            return

        def apply():
            if generation != lease.transport_generation():
                return
            try:
                current, session = _scene(session_id)
                _, superseded = _messages(current, target_id)
                if current != scene or superseded:
                    return
            except ValueError:
                return
            from mixar.modules.space_mixie_chat.core.turn_transport import cleanup_turn_handler
            from mixar.modules.space_mixie_chat.core.queue_processor import cleanup_event_queue_for_scene
            from mixar.modules.space_mixie_chat.core.main_thread_executor import cleanup as flush_executor_queue
            from mixar.modules.space_mixie_chat.core.executor import get_executor
            from mixar.modules.space_mixie_chat.core.slot_processor import finalize_turn
            cleanup_turn_handler(current.name)
            cleanup_event_queue_for_scene(current.name)
            flush_executor_queue(session_id=session_id)
            get_executor().end_agent_turn(session_id)
            finalize_turn(current)
            for message in current.mixie_chat_messages:
                message.input_type = ''
                message.interrupt_id = ''
                message.action_items.clear()
            session.set_run(current, '', False)
            session.set_connected(current)

        run_on_main_thread(apply)

    command('cancel', {'session_id': session_id}, settled, command_id=command_id)
