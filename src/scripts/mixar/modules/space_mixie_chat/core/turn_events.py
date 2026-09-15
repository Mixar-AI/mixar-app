# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Socket-delivered agent turns (wake-ups) → the SSE inbound queue.

A backend run spans turns: every backend-started turn — a wake-up after a
worker report (``kind: "wakeup"``) or the turn an interjection starts
(``kind: "user"``) — is streamed over the agent WebSocket as
``agent.turn.started`` / ``agent.turn.event`` / ``agent.turn.ended``
(see the backend contract ``docs/api/frontend/wakeup-turns.md``). Every
``event`` is exactly one SSE payload dict, so it is fed into the SAME
main-thread queue the SSE handler feeds (``queue_processor``) and renders
identically; ``ended`` reuses the [DONE] finalisation.

Threads: the notifications arrive on the WebSocket receive thread, which
must never touch ``bpy``. Resolving ``session_id`` → scene needs
``bpy.data.scenes``, so ``started`` is marshalled to the main thread; events
that arrive before that resolution lands are buffered per turn and flushed,
in order, once the scene is known. Dedupe is by ``(turn_id, seq)``.
"""

import threading
from typing import Optional

from mixar.config.logging_config import get_logger

from ..constants import JSONRPCMethod, SessionState

logger = get_logger(__name__)

# Turns are forgotten on `ended`; a turn whose end never arrives (transport
# lost mid-turn) is evicted once this many newer turns started.
_MAX_TRACKED_TURNS = 32


class _Turn:
    __slots__ = ("turn_id", "session_id", "run_id", "scene_name", "pending",
                 "last_seq", "dropped", "ended_status")

    def __init__(self, turn_id: str, session_id: str, run_id: str):
        self.turn_id = turn_id
        self.session_id = session_id
        self.run_id = run_id
        self.scene_name: Optional[str] = None  # None until resolved on main
        self.pending: list = []  # events received before resolution
        self.last_seq = -1
        self.dropped = False  # unknown session / scene torn down
        self.ended_status: Optional[str] = None  # `ended` before resolution


_lock = threading.Lock()
_turns: dict[str, _Turn] = {}  # insertion-ordered: oldest first


# ---------------------------------------------------------------------------
# Entry point (WebSocket thread)
# ---------------------------------------------------------------------------


def handle_turn_notification(method: str, params: dict) -> None:
    """Dispatch one ``agent.turn.*`` notification. Never touches ``bpy``."""
    params = params or {}
    if method == JSONRPCMethod.AGENT_TURN_STARTED:
        _on_started(params)
    elif method == JSONRPCMethod.AGENT_TURN_EVENT:
        _on_event(params)
    elif method == JSONRPCMethod.AGENT_TURN_ENDED:
        _on_ended(params)


def _on_started(params: dict) -> None:
    turn_id = str(params.get("turn_id") or "")
    session_id = str(params.get("session_id") or "")
    run_id = str(params.get("run_id") or "")
    if not turn_id or not session_id:
        logger.warning("agent.turn.started without turn_id/session_id — ignored")
        return
    with _lock:
        while len(_turns) >= _MAX_TRACKED_TURNS:
            _turns.pop(next(iter(_turns)), None)
        _turns[turn_id] = _Turn(turn_id, session_id, run_id)
    # `kind` is informational: "wakeup" (a worker report started the turn)
    # and "user" (an interjection started it — the interjection response
    # only carried the `joined` ack) open the scene turn identically.
    logger.info(
        "agent turn %s started for session %s (%s)",
        turn_id[:8], session_id[:8], params.get("kind") or "wakeup",
    )
    from .main_thread_executor import run_on_main_thread
    run_on_main_thread(lambda: _open_turn(turn_id, session_id, run_id))


def _on_event(params: dict) -> None:
    turn_id = str(params.get("turn_id") or "")
    event = params.get("event")
    if not isinstance(event, dict):
        return
    seq = params.get("seq")
    with _lock:
        turn = _turns.get(turn_id)
        if turn is None:
            logger.debug("agent.turn.event for unknown turn %s — dropped", turn_id[:8])
            return
        if isinstance(seq, int):
            if seq <= turn.last_seq:
                return  # replayed / duplicate delivery
            turn.last_seq = seq
        if turn.dropped:
            return
        if turn.scene_name is None:
            turn.pending.append(event)
            return
        scene_name = turn.scene_name
    _enqueue_event(event, scene_name)


def _on_ended(params: dict) -> None:
    turn_id = str(params.get("turn_id") or "")
    status = str(params.get("status") or "completed")
    run_id = str(params.get("run_id") or "")
    with _lock:
        turn = _turns.get(turn_id)
        if turn is None:
            return
        if turn.scene_name is None and not turn.dropped:
            turn.ended_status = status  # flushed by _open_turn
            return
        _turns.pop(turn_id, None)
        scene_name, dropped = turn.scene_name, turn.dropped
    if dropped or not scene_name:
        return
    _enqueue_ended(scene_name, run_id or turn.run_id, status)


# ---------------------------------------------------------------------------
# Main thread
# ---------------------------------------------------------------------------


def _open_turn(turn_id: str, session_id: str, run_id: str) -> None:
    """Resolve the scene, open the turn on it, flush what arrived meanwhile."""
    import bpy

    scene = next(
        (s for s in bpy.data.scenes
         if (getattr(s, "mixie_session_id", "") or "") == session_id),
        None,
    )
    if scene is None:
        logger.warning(
            "agent.turn.started for unknown session %s — dropped", session_id[:8]
        )
        with _lock:
            _turns.pop(turn_id, None)
        return

    _begin_scene_turn(scene, run_id)

    with _lock:
        turn = _turns.get(turn_id)
        if turn is None:
            return
        turn.scene_name = scene.name
        pending, turn.pending = turn.pending, []
        ended_status = turn.ended_status
        if ended_status is not None:
            _turns.pop(turn_id, None)
    for payload in pending:
        _enqueue_event(payload, scene.name)
    if ended_status is not None:
        _enqueue_ended(scene.name, run_id, ended_status)


def _begin_scene_turn(scene, run_id: str) -> None:
    """What the composer does on a send, for a turn the backend started."""
    from .executor import get_executor
    from .message_helpers import add_turn_placeholder
    from .session import get_session_manager
    from .ui_utils import redraw_chat_areas

    session = get_session_manager()
    session.set_run(scene, run_id, True)
    add_turn_placeholder(scene)
    get_executor().begin_agent_turn()
    session.set_state(scene, SessionState.BUSY)
    redraw_chat_areas()


# ---------------------------------------------------------------------------
# Queue bridge (any thread)
# ---------------------------------------------------------------------------


def _to_sse_event(payload: dict):
    from .sse_handler import SSEEvent

    event_type = "slot" if "bubble_id" in payload else str(payload.get("type", "unknown"))
    return SSEEvent(event_type=event_type, data=payload)


def _enqueue_event(payload: dict, scene_name: str) -> None:
    from .queue_processor import queue_sse_event

    if queue_sse_event(_to_sse_event(payload), scene_name) is False:
        logger.warning("socket turn event for '%s' rejected by the inbound queue", scene_name)


def _enqueue_ended(scene_name: str, run_id: str, status: str) -> None:
    """`ended` = the [DONE] finalisation plus the run's reported status.

    ``in_progress`` keeps the run open (more backend turns will come);
    ``completed`` / ``cancelled`` / ``paused`` close it. ``paused`` leaves
    AWAITING_INPUT exactly as the input slot set it — the completion path
    never overrides that state.
    """
    from .queue_processor import queue_sse_complete

    _enqueue_event(
        {
            "type": "run_status",
            "run_id": run_id,
            "status": "in_progress" if status == "in_progress" else "completed",
        },
        scene_name,
    )
    queue_sse_complete(scene_name)


# ---------------------------------------------------------------------------
# Teardown hooks
# ---------------------------------------------------------------------------


def drop_scene(scene_name: str) -> None:
    """Forget every turn feeding ``scene_name`` (abort / New Chat / switch)."""
    with _lock:
        for turn_id in [t for t, turn in _turns.items() if turn.scene_name == scene_name]:
            _turns.pop(turn_id, None)


def reset() -> None:
    """Drop all tracked turns (tests, connection teardown)."""
    with _lock:
        _turns.clear()
