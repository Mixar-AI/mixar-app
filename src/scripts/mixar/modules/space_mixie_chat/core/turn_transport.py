# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""WebSocket turn commands, shared by composer and all question/choice controls."""

import uuid
from collections import deque

from mixar.modules.byok.constants import (
    BYOK_TRANSPORT_KEY_STALE_CODE,
    BYOK_TURN_ACCOUNT_FIELD,
    BYOK_TURN_KEY_FIELD,
)
from mixar.modules.common.agent_rpc.client import command, call
from mixar.modules.common.i18n import n_
from .agent_events import AgentEvent
from .chat_payloads import build_chat_payload, collect_user_preferences
from . import attachment_upload, command_retry, turn_events

_handlers = {}
# Per session, sends that wait behind a message whose images are still
# uploading: the server receives a session's messages in the order sent.
_lines = {}


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

    def _scene(self):
        """The handler's scene: by the name it was created under, else — the
        user renamed the scene mid-turn — by the session it is streaming for,
        re-keying the registry under the new name (plan row 1.9)."""
        import bpy
        scene = bpy.data.scenes.get(self.scene_name)
        if scene is None and self._session_id:
            from mixar.modules.common.agent_execution.document import scene_for_session
            scene = scene_for_session(self._session_id, bpy)
            if scene is not None:
                _rekey(self, scene.name)
        return scene

    @property
    def is_running(self):
        return any(not turn.complete and turn.session_id == self._session_id
                   for turn in turn_events._turns.values())

    def _send(self, method, payload, user_message=None, interjecting=False, retry_of=None,
              inline=False, attachments_backup=None):
        """``retry_of`` is the command id of the attempt this send repeats
        after a ``byok_transport_key_stale`` refusal (see ``settled``): the
        user bubble is re-keyed to the new id, and a second refusal is
        shown, never retried again — the guard is this argument.

        Inline images are uploaded over HTTP first and the command carries
        references (``attachment_upload``); ``inline`` skips that, for the
        one resend after the server answered ``attachment_unavailable``.
        ``attachments_backup`` carries the inline originals across a retry
        whose payload already holds references."""
        from .session import get_session_manager
        scene = self._scene()
        if scene is None:
            return False
        # Central boundary covers typed sends, choices, modify, and retries.
        # Legacy prose remains on chat for older servers; updated servers
        # consume this complete snapshot and strip that compatibility prefix.
        if method in ('chat', 'input'):
            from .rules import rules_snapshot
            payload['rules'] = rules_snapshot(scene)
        if method in ('chat', 'input'):
            # Answers can replace folders while a question is pending. Send
            # the complete snapshot (empty clears) on both entry points so
            # the resumed agent sees the folders that this session grants.
            try:
                from mixar.modules.context_folder.core import attach as folders
                payload['folder_context'] = folders.folder_context_for_send(scene, payload['session_id'])
            except Exception:  # noqa: BLE001 — a folder failure never blocks a send
                pass
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
        elif retry_of:
            for item in scene.mixie_chat_messages:
                if item.sender == 'USER' and item.bubble_id == retry_of:
                    item.bubble_id = command_id
                    break

        uploads = {'backup': attachments_backup}

        def settled(target, result):
            from .queue_processor import get_event_processor
            if uploads['backup'] and attachment_upload.unavailable(result):
                # The server no longer holds the uploaded images (expired,
                # or the store lost them): send them inline, once, under a
                # new id — the old one is journaled with this refusal.
                attachment_upload.restore(payload, uploads['backup'])
                for field in (BYOK_TURN_KEY_FIELD, BYOK_TURN_ACCOUNT_FIELD):
                    payload.pop(field, None)  # resealed for the new id
                self._send(method, payload, None, interjecting, retry_of=command_id, inline=True)
                return
            if retry_of is None and _stale_transport_key(result):
                # The key was sealed to a server key that has since rotated:
                # forget the cached one and resend this command ONCE under a
                # new id (the server journals the refusal under the old one,
                # and keys the receipt on the payload's content).
                from mixar.modules.byok.core import transport_seal
                transport_seal.invalidate()
                for field in (BYOK_TURN_KEY_FIELD, BYOK_TURN_ACCOUNT_FIELD):
                    payload.pop(field, None)
                self._send(method, payload, None, interjecting, retry_of=command_id,
                           attachments_backup=uploads['backup'])
                return
            for item in target.mixie_chat_messages:
                if item.sender == 'USER' and item.bubble_id == command_id:
                    # English state tokens: the chat renderer translates them when drawn.
                    item.delivery_hint = (n_('delivery uncertain') if result.get('uncertain') else
                                          '' if result.get('ok', True) else n_('could not be delivered'))
                    break
            if result.get('ok') is False and not result.get('cancelled') and not result.get('uncertain') and not joining:
                processor = get_event_processor()
                processor._clear_loader_bubbles(target)
                get_session_manager().set_state(target, previous_state)
                from .byok_notice import byok_error_code
                if byok_error_code(result, result.get('data') or {}):
                    # A refusal over the user's own key: keep the command so
                    # the key-missing card can resend it (new id) once the
                    # key is entered or the account switches to credits.
                    from . import byok_resend
                    remembered = payload
                    if uploads['backup']:
                        # The card may resend long after the upload expired:
                        # keep the images themselves; the resend uploads again.
                        remembered = dict(payload)
                        attachment_upload.restore(remembered, uploads['backup'])
                    byok_resend.remember(payload['session_id'], command_id, method, remembered, joining)
                processor.handle_command_error(result, target)
            self._running = False

        turn_events.expect(scene, command_id, settled)
        busy_retries = []

        def resend():
            # Main thread (command_retry timer). The SAME id and payload: the
            # backend refused before claiming the receipt, and going back
            # through _send would mint a new id and recompute the rules.
            try:
                command(method, payload, ack, command_id=command_id)
            except Exception as exc:
                turn_events.handle_turn_notification('agent.command.result', {
                    'session_id': payload['session_id'], 'command_id': command_id,
                    'ok': False, 'message': str(exc),
                })

        def ack(result):
            if command_retry.is_busy(result) and not busy_retries:
                # First -32017: no result yet (it would settle the bubble and
                # clear the loader); resend once after the server's hint.
                busy_retries.append(result)
                command_retry.request(payload['session_id'], command_id,
                                      command_retry.retry_after(result), resend)
                return
            lost = (isinstance(result, dict) and result.get('code')
                    and (result.get('data') or {}).get('uncertain'))
            if not lost and turn_events.acknowledged(command_id) and isinstance(result, dict) \
                    and not result.get('code') and result.get('state') != 'complete':
                # A resend after a dead socket was admitted: clear "delivery uncertain".
                turn_events.handle_turn_notification('agent.command.delivered', {
                    'session_id': payload['session_id'], 'command_id': command_id, 'ok': True,
                })
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

        outcome = {}

        def dispatch(byok_fields, byok_error):
            # Main thread. The server holds BYOK metadata only, so the key
            # rides every chat/input command; a refusal (expired Codex
            # sign-in) takes the same settled path as a server rejection.
            if byok_error:
                turn_events.handle_turn_notification('agent.command.result', {
                    'session_id': payload['session_id'], 'command_id': command_id,
                    'ok': False, 'message': byok_error.get('message'),
                    'data': {'code': byok_error.get('code')},
                })
                outcome['ok'] = False
                return
            payload.update(byok_fields or {})
            # Held until the server answers, so a frame that dies with its
            # socket is resent under this id on the next connection.
            turn_events.remember_unsent(command_id, method, payload, ack)
            try:
                command(method, payload, ack, command_id=command_id)
                self._running = True
                outcome['ok'] = True
            except Exception as exc:
                if uploads.get('deferred') and not _socket_connected():
                    # The socket dropped while the images uploaded. Keep the
                    # frame held and mark it uncertain: the reconnect's
                    # request_status finds it unknown and sends it (same id).
                    self._running = True
                    outcome['ok'] = True
                    turn_events.handle_turn_notification('agent.command.result', {
                        'session_id': payload['session_id'], 'command_id': command_id,
                        'ok': False, 'uncertain': True,
                    })
                    return
                turn_events.acknowledged(command_id)  # refused before sending: shown, not held
                turn_events.handle_turn_notification('agent.command.result', {
                    'session_id': payload['session_id'], 'command_id': command_id,
                    'ok': False, 'message': str(exc),
                })
                outcome['ok'] = False

        # Synchronous while BYOK is inactive (the platform path keeps its
        # result and timing); otherwise a worker thread reads the credential
        # store (and refreshes a Codex token) and `dispatch` runs from a
        # main-thread timer, so the send is accepted here and a failure
        # settles through the expected command id above.
        from mixar.modules.byok.core.turn_credentials import prepare
        sid = payload['session_id']
        uploading = not inline and attachment_upload.wanted(method, payload)
        if not uploading and not _lines.get(sid):
            prepare(dispatch, method=method, action=payload.get('action'))
            return outcome.get('ok', True)

        # Images go up over HTTP first; the frame then carries ids. A send
        # behind an upload waits its turn in the session's line. Either way
        # the send is accepted now and settles through the expected id, as
        # on the BYOK worker-thread path.
        def advance():
            line = _lines.get(sid)
            if line and line[0] is start:
                line.popleft()
                if line:
                    line[0]()
                else:
                    _lines.pop(sid, None)

        def sent(byok_fields, byok_error):
            try:
                dispatch(byok_fields, byok_error)
            finally:
                advance()

        def start():
            if not turn_events.command_pending(command_id):  # Stop forgot it
                advance()
            elif uploading:
                turn_events.stage(command_id)
                uploads['deferred'] = True

                def uploaded():
                    turn_events.unstage(command_id)
                    if turn_events.command_pending(command_id):
                        prepare(sent, method=method, action=payload.get('action'))
                    else:
                        advance()
                uploads['backup'] = attachment_upload.offload(method, payload, uploaded)
            else:
                prepare(sent, method=method, action=payload.get('action'))

        _lines.setdefault(sid, deque()).append(start)
        if len(_lines[sid]) == 1:
            start()
        return True

    def start_stream(self, message, instance_id, session_id, plan_required=True,
                     execution_required=True, approval_required=True, auth_token=None,
                     image_attachments=None, attachment_names=None, imported_object_names=None,
                     project_context=None, mark_context=None, user_message=None,
                     interjecting=False, auto_mode=False):
        # ``attachment_names`` mirrors the pairs for callers and QA probes; the
        # wire's names (per block and legacy list) come from image_attachments.
        payload = build_chat_payload(
            message=message, instance_id=instance_id, session_id=session_id,
            plan_required=plan_required, execution_required=execution_required,
            approval_required=approval_required, image_attachments=image_attachments,
            imported_object_names=imported_object_names,
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
        self._session_id = session_id
        scene = self._scene()
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


def _socket_connected():
    from .jsonrpc_client import get_jsonrpc_client
    client = get_jsonrpc_client()
    return bool(client is not None and client.is_connected)


def _stale_transport_key(result):
    """A settled command refused with ``byok_transport_key_stale`` (409):
    the receipt shape carries the code at the top level, a JSON-RPC error
    under ``data``."""
    from .byok_notice import byok_error_code
    data = result.get('data') if isinstance(result, dict) else None
    return byok_error_code(result, data or {}) == BYOK_TRANSPORT_KEY_STALE_CODE


def create_turn_handler(scene_name='', host='', on_event=None, on_error=None, on_complete=None):
    handler = TurnTransport(scene_name, host, on_event, on_error, on_complete)
    _handlers[scene_name] = handler
    return handler


def _rekey(handler, scene_name):
    for key, value in list(_handlers.items()):
        if value is handler:
            _handlers.pop(key, None)
    handler.scene_name = scene_name
    _handlers[scene_name] = handler


def get_turn_handler(scene_name=''):
    handler = _handlers.get(scene_name)
    if handler is not None or not scene_name:
        return handler
    # A renamed scene: find the handler streaming for that scene's session
    # and re-key it under the new name (plan row 1.9).
    import bpy
    scene = bpy.data.scenes.get(scene_name)
    sid = getattr(scene, 'mixie_session_id', '') if scene is not None else ''
    if not sid:
        return None
    for candidate in list(_handlers.values()):
        if candidate._session_id == sid:
            _rekey(candidate, scene_name)
            return candidate
    return None


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
    _lines.clear()
