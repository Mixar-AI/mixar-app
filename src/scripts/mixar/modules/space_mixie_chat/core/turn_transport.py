# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""WebSocket turn commands, shared by composer and all question/choice controls."""

import uuid

from mixar.modules.common.agent_rpc.client import command, call
from .agent_events import AgentEvent
from .chat_payloads import build_chat_payload, collect_user_preferences
from . import turn_events

_handlers = {}


class TurnTransport:
    def __init__(self, scene_name='', host='', on_event=None, on_error=None, on_complete=None):
        self.scene_name = scene_name
        self._on_error = on_error
        self._session_id = ''
        self._last_seq = -1
        self._running = False
        # The command id of the most recent send — the backend's request id.
        # Read by the send operator to bind its turn checkpoint; the user
        # bubble carries the same id, but a bpy collection reference taken
        # before the placeholder bubble was added can go stale.
        self.last_command_id = ''

    @property
    def is_running(self):
        return any(not turn.complete and turn.session_id == self._session_id
                   for turn in turn_events._turns.values())

    def _send(self, method, payload, user_message=None, interjecting=False):
        import bpy
        from .session import get_session_manager
        scene = bpy.data.scenes.get(self.scene_name)
        if scene is None:
            return False
        # Central boundary covers typed sends, choices, modify, and retries.
        # Legacy prose remains on chat for older servers; updated servers
        # consume this complete snapshot and strip that compatibility prefix.
        if method in ('chat', 'input'):
            from .rules import rules_snapshot
            payload['rules'] = rules_snapshot(scene)
        self._session_id = payload['session_id']
        command_id = str(uuid.uuid4())
        self.last_command_id = command_id
        previous_state = get_session_manager().get_state(scene)
        joining = interjecting
        if previous_state.value == 'busy' and not joining:
            from ..constants import SessionState
            previous_state = SessionState.IDLE
        # One ID follows this exact user bubble through out-of-order acknowledgements.
        if user_message is not None:
            user_message.bubble_id = command_id
            user_message.delivery_hint = 'queued' if joining else ''

        def settled(target, result):
            from .queue_processor import get_event_processor
            for item in target.mixie_chat_messages:
                if item.sender == 'USER' and item.bubble_id == command_id:
                    item.delivery_hint = ('delivery uncertain' if result.get('uncertain') else
                                          '' if result.get('ok', True) else 'could not be delivered')
                    break
            if result.get('ok') is False and not result.get('cancelled') and not result.get('uncertain') and not joining:
                processor = get_event_processor()
                processor._clear_loader_bubbles(target)
                get_session_manager().set_state(target, previous_state)
                processor.handle_command_error(result, target)
            self._running = False

        turn_events.expect(scene, command_id, settled)
        def ack(result):
            if isinstance(result, dict) and result.get('code'):
                turn_events.handle_turn_notification('agent.command.result', {
                    'session_id': payload['session_id'], 'command_id': command_id,
                    'ok': False, 'message': result.get('message'),
                    'status_code': (result.get('data') or {}).get('status_code'),
                    'data': result.get('data') or {},
                    'uncertain': (result.get('data') or {}).get('uncertain', False),
                })
            elif isinstance(result, dict) and result.get('state') == 'complete':
                turn_events.handle_turn_notification('agent.command.result', {
                    'session_id': payload['session_id'], 'command_id': command_id,
                    **(result.get('result') or {}),
                })
            # An admission receipt is not completion; the journal owns lifecycle.
        try:
            command(method, payload, ack, command_id=command_id)
            self._running = True
            return True
        except Exception as exc:
            turn_events.handle_turn_notification('agent.command.result', {
                'session_id': payload['session_id'], 'command_id': command_id,
                'ok': False, 'message': str(exc),
            })
            return False

    def start_stream(self, message, instance_id, session_id, plan_required=True,
                     execution_required=True, approval_required=True, auth_token=None,
                     image_attachments=None, attachment_names=None, imported_object_names=None,
                     project_context=None, mark_context=None, user_message=None,
                     interjecting=False, auto_mode=False):
        payload = build_chat_payload(
            message=message, instance_id=instance_id, session_id=session_id,
            plan_required=plan_required, execution_required=execution_required,
            approval_required=approval_required, image_attachments=image_attachments,
            attachment_names=attachment_names, imported_object_names=imported_object_names,
            project_context=project_context, mark_context=mark_context,
            user_preferences=collect_user_preferences(), auto_mode=auto_mode,
        )
        return self._send('chat', payload, user_message, interjecting)

    def start_input_stream(self, session_id, action, text='', answers=None,
                           interrupt_id=None, auth_token=None, question_ref=None, attachments=None,
                           user_message=None):
        payload = {'session_id': session_id, 'action': action, 'text': text}
        if answers:
            payload['answers'] = answers
        if interrupt_id:
            payload['interrupt_id'] = interrupt_id
        if attachments:
            payload['attachments'] = attachments
        if question_ref:
            payload['question_ref'] = question_ref
        return self._send('input', payload, user_message)

    def stop_stream(self):
        turn_events.drop_scene(self.scene_name)
        self._running = False

    def resume_stream(self, session_id, after_seq=None, auth_token=None):
        import bpy
        self._session_id = session_id
        scene = bpy.data.scenes.get(self.scene_name)
        if scene is None:
            return False
        turn_events.bind(scene)
        def got_status(result):
            info = (result.get('turns') or {}).get(session_id, {})
            # Process status on the main thread via the same bounded ingress.
            turn_events.handle_turn_notification('agent.recovery.status', {
                'session_id': session_id, 'info': info,
            })
        try:
            call('agent.status', {'session_ids': [session_id]}, got_status)
            return True
        except Exception:
            return False


def create_turn_handler(scene_name='', host='', on_event=None, on_error=None, on_complete=None):
    handler = TurnTransport(scene_name, host, on_event, on_error, on_complete)
    _handlers[scene_name] = handler
    return handler


def get_turn_handler(scene_name=''):
    return _handlers.get(scene_name)


def cleanup_turn_handler(scene_name):
    handler = _handlers.pop(scene_name, None)
    if handler:
        handler.stop_stream()


def cleanup_all_turn_handlers(app_exit=False):
    """Release all delivery state without resolving scenes during finalization."""
    for handler in list(_handlers.values()):
        handler._running = False
    _handlers.clear()
    turn_events.shutdown(app_exit=app_exit)
