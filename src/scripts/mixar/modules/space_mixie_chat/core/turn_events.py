# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Ordered socket ingress. Only the main-thread consumer touches Blender state.

Start, payload and end travel through the same bounded inbox. A teardown fences
both queued starts and later deliveries. Replay uses the last rendered cursor,
not the last frame received, and never replays a scene-changing tool request.
"""

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from mixar.config.logging_config import get_logger
from ..constants import SessionState
from .agent_events import AgentEvent
from . import turn_cursor

logger = get_logger(__name__)
_LOCK = threading.Lock()
_inbox = deque()
_inbox_bytes = 0
_overflow = set()
_bindings = {}
_turns = {}
_commands = {}
_blocked = set()
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ITEMS = 512


@dataclass
class Turn:
    session_id: str
    turn_id: str
    run_id: str
    cursor: int = -1
    pending: dict = field(default_factory=dict)
    complete: bool = False
    recovering: bool = False


def arm():
    """Arm during connection setup or a UI send (main thread)."""
    import bpy
    if not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, first_interval=0.02, persistent=True)


def _scene_id(scene):
    return scene.as_pointer() if hasattr(scene, 'as_pointer') else id(scene)


def bind(scene):
    from .session import get_session_manager
    sid = get_session_manager().get_session_id(scene)
    if sid:
        _bindings[sid] = _scene_id(scene)
    arm()
    return sid


def expect(scene, command_id, callback=None):
    sid = bind(scene)
    _blocked.discard(sid)
    _commands[command_id] = (sid, callback)
    return sid


def reopen(scene):
    """Rebind a restored transcript; forget its revoked local delivery state."""
    global _inbox_bytes
    sid = bind(scene)
    if not sid:
        return
    with _LOCK:
        retained = [item for item in _inbox if item[1].get('session_id') != sid]
        _inbox.clear()
        _inbox.extend(retained)
        _inbox_bytes = sum(item[2] for item in retained)
        _overflow.discard(sid)
    for tid, turn in list(_turns.items()):
        if turn.session_id == sid:
            _turns.pop(tid)
    for cid, (session_id, _) in list(_commands.items()):
        if session_id == sid:
            _commands.pop(cid)
    _blocked.discard(sid)


def handle_turn_notification(method, params):
    """Nonblocking receive-thread entry; no bpy, queue waits or scene resolution."""
    global _inbox_bytes
    if not isinstance(params, dict):
        return
    size = len(json.dumps(params).encode('utf-8'))
    with _LOCK:
        if len(_inbox) >= _MAX_ITEMS or _inbox_bytes + size > _MAX_BYTES:
            if len(_overflow) < 32:
                _overflow.add(str(params.get('session_id') or ''))
            return
        _inbox.append((method, params, size))
        _inbox_bytes += size


def _resolve(sid):
    import bpy
    scenes = [scene for scene in bpy.data.scenes if getattr(scene, 'mixie_session_id', '') == sid]
    identity = _bindings.get(sid)
    if identity is not None:
        return next((scene for scene in scenes if _scene_id(scene) == identity), None)
    if len(scenes) == 1:
        _bindings[sid] = _scene_id(scenes[0])
        return scenes[0]
    return None


def _drain():
    global _inbox_bytes
    deadline = time.monotonic() + 0.004
    for _ in range(64):
        if time.monotonic() >= deadline:
            break
        with _LOCK:
            if not _inbox:
                break
            method, params, size = _inbox.popleft()
            _inbox_bytes -= size
        try:
            _consume(method, params)
        except Exception:
            logger.exception('Agent event could not be rendered')
    with _LOCK:
        overflowed = list(_overflow)
        _overflow.clear()
    if overflowed:
        reconnect()  # Also recovers a dropped start or command acknowledgement.
    return 0.02


def _consume(method, params):
    if method == 'agent.recovery.status':
        sid = params.get('session_id')
        scene = _resolve(sid)
        info = params.get('info') or {}
        tid = info.get('turn_id')
        if scene is None or sid in _blocked:
            return
        turn = _turns.get(tid)
        saved = turn_cursor.read(scene, sid, tid)
        # A rendered turn_end is proof of completion even after the journal
        # expires. Replay availability is only relevant to missing delivery.
        if tid and ((turn is not None and turn.complete) or saved.get('complete')):
            if saved:
                from .session import get_session_manager
                session = get_session_manager()
                session.set_run(scene, saved.get('run_id', ''), bool(saved.get('run_open')))
                session.set_state(scene, SessionState[saved.get('state', 'IDLE')])
            return
        if not tid:
            from .session import get_session_manager
            local = [t for t in _turns.values() if t.session_id == sid]
            pending = any(entry[0] == sid for entry in _commands.values())
            completed = local[-1].complete if local else saved.get('complete', False)
            if (get_session_manager().run_open(scene) and completed and not pending
                    and not any(not t.complete for t in local)):
                return  # Between wake-ups; no response is missing locally.
        if not tid or not info.get('replay_available'):
            _replay_unavailable(scene, Turn(sid, tid or '', ''))
            return
        if turn is None:
            _commands.setdefault(tid, (sid, None))
            _consume('agent.turn.started', {'session_id': sid, 'turn_id': tid,
                                           'run_id': info.get('run_id', ''), 'replay': True})
            turn = _turns.get(tid)
        if turn is not None and turn.complete:
            saved = turn_cursor.read(scene, sid, tid)
            if saved:
                from .session import get_session_manager
                session = get_session_manager()
                session.set_run(scene, saved.get('run_id', ''), bool(saved.get('run_open')))
                session.set_state(scene, SessionState[saved.get('state', 'IDLE')])
        elif turn is not None:
            _request_replay(turn)
        return
    if method in ('agent.command.result', 'agent.command.delivered'):
        command_id = params.get('command_id')
        entry = _commands.get(command_id) if params.get('uncertain') or method == 'agent.command.delivered' else _commands.pop(command_id, None)
        if entry and entry[0] not in _blocked and entry[1]:
            scene = _resolve(entry[0])
            if scene is not None:
                entry[1](scene, params)
        return
    sid, tid = params.get('session_id'), params.get('turn_id')
    if not sid or not tid or sid in _blocked:
        return
    scene = _resolve(sid)
    if scene is None:
        return
    turn = _turns.get(tid)
    if method == 'agent.turn.started':
        if turn is not None:
            turn.recovering = bool(params.get('replay'))
            return
        from .session import get_session_manager
        session = get_session_manager()
        run_id = str(params.get('run_id') or '')
        expected = tid in _commands
        wakeup = session.run_open(scene) and run_id == getattr(scene, 'mixie_run_id', '')
        if not expected and not wakeup:
            return  # Late start from a revoked/previous run.
        # Bounded history retains completed cursors for duplicate suppression.
        if len(_turns) >= 64:
            completed = next((key for key, value in _turns.items() if value.complete), None)
            if completed:
                _turns.pop(completed)
            else:
                raise RuntimeError('Too many active agent turns')
        saved = turn_cursor.read(scene, sid, tid)
        turn = _turns[tid] = Turn(sid, tid, run_id,
                                  cursor=int(saved.get('cursor', -1)),
                                  complete=bool(saved.get('complete', False)))
        if turn.complete:
            session.set_run(scene, saved.get('run_id', ''), bool(saved.get('run_open')))
            session.set_state(scene, SessionState[saved.get('state', 'IDLE')])
            return
        _begin_scene_turn(scene, run_id)
        return
    if turn is None or turn.complete:
        return
    if method == 'agent.turn.ended':
        # Journaled turn_end is authoritative. Missing tail is recovered before
        # completion can release the viewport lock or settle the run.
        if params.get('last_seq', -1) > turn.cursor:
            _request_replay(turn)
        return
    payload = params.get('event')
    if not isinstance(payload, dict):
        return
    if payload.get('type') == 'resume_unavailable':
        _replay_unavailable(scene, turn)
        return
    seq = params.get('seq', payload.get('seq'))
    if not isinstance(seq, int) or seq <= turn.cursor:
        return
    if len(turn.pending) >= 256 and seq not in turn.pending:
        turn.pending.clear()
        _request_replay(turn)
        return
    turn.pending[seq] = payload
    while turn.cursor + 1 in turn.pending:
        next_seq = turn.cursor + 1
        event = turn.pending[next_seq]
        _apply(scene, turn, event)
        turn.pending.pop(next_seq)
        turn.cursor = next_seq  # Advance only after successful rendering.
        turn_cursor.save(scene, turn)
        if turn.complete:
            turn.pending.clear()
            break
    if turn.pending and not turn.recovering:
        _request_replay(turn)


def _apply(scene, turn, payload):
    from .queue_processor import get_event_processor
    processor = get_event_processor()
    if payload.get('type') == 'turn_end':
        status = payload.get('status')
        processor._handle_typed_payload({'type': 'run_status',
            'run_id': payload.get('run_id', turn.run_id),
            'status': 'in_progress' if status == 'in_progress' else 'completed'}, scene)
        processor._handle_agent_complete_internal(scene)
        processor._clear_loader_bubbles(scene)
        turn.complete = True
        return
    if payload.get('type') == 'run_status':
        turn.run_id = str(payload.get('run_id') or '')
    event_type = 'slot' if 'bubble_id' in payload else payload.get('type', 'unknown')
    processor._handle_agent_event_internal(AgentEvent(event_type, payload), scene)
    processor._redraw_ui()


def _begin_scene_turn(scene, run_id):
    from .executor import get_executor
    from .message_helpers import add_turn_placeholder
    from .session import get_session_manager
    session = get_session_manager()
    if run_id:
        session.set_run(scene, run_id, True)
    add_turn_placeholder(scene)
    get_executor().begin_agent_turn()
    session.set_state(scene, SessionState.BUSY)


def _request_replay(turn):
    from mixar.modules.common.agent_rpc.client import call
    turn.recovering = True
    def reply(result):
        if not isinstance(result, dict) or result.get('status') == 'unavailable' or result.get('code'):
            handle_turn_notification('agent.turn.event', {'session_id': turn.session_id,
                'turn_id': turn.turn_id, 'event': {'type': 'resume_unavailable'}})
    try:
        call('agent.attach', {'session_id': turn.session_id, 'turn_id': turn.turn_id,
                             'after_seq': turn.cursor}, reply)
    except Exception:
        turn.recovering = False


def _replay_unavailable(scene, turn):
    from .queue_processor import get_event_processor
    from .message_helpers import add_agent_message
    from .session import get_session_manager
    processor = get_event_processor()
    processor._clear_loader_bubbles(scene)
    from .executor import get_executor
    get_executor().end_agent_turn()
    get_session_manager().set_run(scene, '', False)
    get_session_manager().set_state(scene, SessionState.IDLE)
    add_agent_message(scene, 'The connection lost part of this response. The task was not restarted. Check the scene before continuing.')
    turn.complete = True


def reconnect():
    """Resume every interrupted delivery from its rendered cursor, main thread."""
    arm()
    for turn in list(_turns.values()):
        if not turn.complete and turn.session_id not in _blocked:
            _request_replay(turn)
    from mixar.modules.common.agent_rpc.client import call
    for command_id, (sid, _) in list(_commands.items()):
        if sid in _blocked:
            continue
        def received(result, cid=command_id, session_id=sid):
            if result.get('state') == 'complete':
                handle_turn_notification('agent.command.result', {
                    'command_id': cid, 'session_id': session_id, **(result.get('result') or {}),
                })
            def described(value):
                info = (value.get('turns') or {}).get(session_id, {})
                if info.get('turn_id'):
                    handle_turn_notification('agent.recovery.status', {'session_id': session_id, 'info': info})
            try:
                call('agent.status', {'session_ids': [session_id]}, described)
            except Exception:
                pass
        try:
            call('agent.request_status', {'command_id': command_id}, received)
        except Exception:
            logger.debug('Pending command recovery waits for the socket')
    import bpy
    from mixar.modules.common.agent_rpc.client import call
    from .session import get_session_manager
    ids = []
    for scene in bpy.data.scenes:
        sid = getattr(scene, 'mixie_session_id', '')
        if sid and sid not in _blocked and (get_session_manager().run_open(scene)
                                           or turn_cursor.read(scene, sid)):
            bind(scene)
            ids.append(sid)
    if ids:
        def status(result):
            for sid, info in (result.get('turns') or {}).items():
                handle_turn_notification('agent.recovery.status', {'session_id': sid, 'info': info})
        try:
            call('agent.status', {'session_ids': ids[:32]}, status)
        except Exception:
            logger.debug('Agent recovery waits for the socket')

    from .turn_resume import check_orphaned_turns
    check_orphaned_turns()


def drop_scene(scene_name):
    import bpy
    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        return
    sid = getattr(scene, 'mixie_session_id', '')
    _blocked.add(sid)
    for turn in _turns.values():
        if turn.session_id == sid:
            turn.complete = True
            turn.pending.clear()
    for key, entry in list(_commands.items()):
        if entry[0] == sid:
            _commands.pop(key, None)


def shutdown(app_exit=False):
    """Stop the consumer on disable/reload; atexit must never call bpy."""
    if not app_exit:
        import bpy
        if bpy.app.timers.is_registered(_drain):
            bpy.app.timers.unregister(_drain)
    reset()


def reset():
    global _inbox_bytes
    with _LOCK:
        _inbox.clear()
        _overflow.clear()
        _inbox_bytes = 0
    _turns.clear()
    _commands.clear()
    _bindings.clear()
    _blocked.clear()
