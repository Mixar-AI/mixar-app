# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runs that span turns — the chat is never blocked while the agent works.

Pins the client half of the backend's wake-up / interjection contract
(``mixar-backend/docs/api/frontend/wakeup-turns.md``):

- Run state lives next to turn state (``SessionManager.set_run``) and a scene
  with an OPEN run counts as active, so background worker scripts are
  accepted while the orchestrator's turn is IDLE.
- ``run_status`` / ``cancelled`` typed payloads drive the run; a turn that
  ends without a ``run_status`` closes the run on turn_end.
- Socket turns (``agent.turn.*``) are pinned in ``test_socket_turns.py``.
- The composer sends while BUSY only when the run is open, as an
  interjection that reads ONLY the ``joined`` ack and never opens a second
  event producer.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from _open_run_support import (  # noqa: F401 — fixtures are collected by name
    _SRC_SCRIPTS,
    _scene,
    clean_state,
    live_bpy,
)
from mixar.modules.space_mixie_chat.constants import SessionState  # noqa: E402
from mixar.modules.space_mixie_chat.core import composer_send  # noqa: E402
from mixar.modules.space_mixie_chat.core import queue_processor  # noqa: E402
from mixar.modules.space_mixie_chat.core.session import SessionManager  # noqa: E402
from mixar.modules.space_mixie_chat.core.agent_events import AgentEvent  # noqa: E402


# ---------------------------------------------------------------------------
# A. Run state next to turn state
# ---------------------------------------------------------------------------


def test_open_run_keeps_idle_scene_active_for_worker_scripts():
    scene = _scene()
    assert not SessionManager.has_active_session()

    SessionManager.set_run(scene, "run-1", True)
    assert scene.mixie_run_open is True
    assert scene.mixie_run_id == "run-1"
    assert SessionManager.run_open(scene)
    assert SessionManager.has_active_session()

    SessionManager.set_run(scene, "", False)
    assert not SessionManager.has_active_session()
    assert scene.mixie_run_id == ""


def test_turn_end_does_not_deactivate_scene_while_run_open():
    scene = _scene(state="BUSY")
    SessionManager.set_state(scene, SessionState.BUSY)
    SessionManager.set_run(scene, "run-1", True)
    SessionManager.set_state(scene, SessionState.IDLE)
    assert SessionManager.has_active_session(), "workers still build"
    SessionManager.set_run(scene, "run-1", False)
    assert not SessionManager.has_active_session()


def test_transient_disconnect_preserves_run_terminal_clears_it(live_bpy):
    scene = _scene()
    live_bpy.data.scenes.append(scene)
    SessionManager.set_run(scene, "run-1", True)

    SessionManager.on_transport_disconnect(terminal=False)
    assert scene.mixie_run_open is True
    assert scene.mixie_chat_state == "OFFLINE"

    SessionManager.on_transport_disconnect(terminal=True)
    assert scene.mixie_run_open is False
    assert not SessionManager.has_active_session()


def test_new_chat_paths_close_the_run():
    scene = _scene()
    SessionManager.set_run(scene, "run-1", True)
    SessionManager.clear_session_id(scene)
    assert scene.mixie_run_open is False

    SessionManager.set_run(scene, "run-2", True)
    SessionManager.clear(scene)
    assert scene.mixie_run_open is False


def test_wakeup_turn_keeps_parallel_agent_cards(monkeypatch):
    cards = MagicMock()
    monkeypatch.setitem(sys.modules, "mixar.modules.agent_panel.core.cards", cards)
    scene = _scene()

    SessionManager.set_state(scene, SessionState.BUSY)  # a new run's first turn
    assert cards.clear_cards.call_count == 1

    SessionManager.set_run(scene, "run-1", True)
    SessionManager.set_state(scene, SessionState.IDLE)
    SessionManager.set_state(scene, SessionState.BUSY)  # wake-up of the same run
    assert cards.clear_cards.call_count == 1, "the run's workers own those cards"


# ---------------------------------------------------------------------------
# B. Typed payloads in the queue processor
# ---------------------------------------------------------------------------


@pytest.fixture
def processor(monkeypatch):
    executor_mod = sys.modules.get("mixar.modules.space_mixie_chat.core.executor")
    if executor_mod is None:
        import mixar.modules.space_mixie_chat.core.executor as executor_mod
    monkeypatch.setattr(executor_mod, "get_executor", lambda: MagicMock())
    monkeypatch.setattr(queue_processor, "redraw_chat_areas", lambda: None)
    proc = queue_processor.get_event_processor()
    proc._run_status_seen.clear()
    return proc


def test_run_status_opens_and_closes_run(processor):
    scene = _scene()
    processor._handle_agent_event_internal(
        AgentEvent("run_status", {"type": "run_status", "run_id": "r1", "status": "in_progress"}),
        scene,
    )
    assert scene.mixie_run_open and scene.mixie_run_id == "r1"
    processor._handle_agent_event_internal(
        AgentEvent("run_status", {"type": "run_status", "run_id": "r1", "status": "completed"}),
        scene,
    )
    assert not scene.mixie_run_open


def test_cancelled_closes_run(processor):
    scene = _scene()
    SessionManager.set_run(scene, "r1", True)
    processor._handle_agent_event_internal(
        AgentEvent("cancelled", {"type": "cancelled", "reason": "user"}), scene
    )
    assert not scene.mixie_run_open


def test_done_closes_run_unless_turn_reported_run_status(processor):
    scene = _scene(state="BUSY")
    SessionManager.set_run(scene, "r1", True)

    # No run_status this turn (older backend / chat-only turn) → closed.
    processor._handle_agent_complete_internal(scene)
    assert scene.mixie_chat_state == "IDLE"
    assert not scene.mixie_run_open

    # run_status in_progress arrived → the run stays open across the turn end.
    SessionManager.set_state(scene, SessionState.BUSY)
    processor._handle_agent_event_internal(
        AgentEvent("run_status", {"type": "run_status", "run_id": "r1", "status": "in_progress"}),
        scene,
    )
    processor._handle_agent_complete_internal(scene)
    assert scene.mixie_chat_state == "IDLE"
    assert scene.mixie_run_open
    assert SessionManager.has_active_session()

    # The flag is per turn: the next turn_end without run_status closes it.
    processor._handle_agent_complete_internal(scene)
    assert not scene.mixie_run_open


def test_unknown_typed_payload_is_still_ignored(processor, monkeypatch):
    scene = _scene()
    applied = []
    monkeypatch.setattr(processor._slot_processor, "apply_event", lambda d, s: applied.append(d))
    processor._handle_agent_event_internal(AgentEvent("weird", {"type": "weird"}), scene)
    assert applied == []
    assert not scene.mixie_run_open


# ---------------------------------------------------------------------------
# D. Composer: one send predicate, interjection path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state, run_open, allowed", [
    ("IDLE", False, True),
    ("IDLE", True, True),
    ("MODIFYING", False, True),
    ("AWAITING_INPUT", False, True),
    ("BUSY", False, False),
    ("BUSY", True, True),
    ("OFFLINE", True, False),
    ("CONNECTING", False, False),
])
def test_can_send_matrix(state, run_open, allowed):
    scene = _scene(state=state)
    scene.mixie_run_open = run_open
    ok, reason = composer_send.can_send(scene)
    assert ok is allowed
    assert bool(reason) is (not allowed), "a refusal always says why"
    assert composer_send.is_interjection(scene) is (state == "BUSY" and run_open)


def test_busy_send_uses_socket_command_without_replacing_live_turn(monkeypatch):
    from mixar.modules.common.agent_rpc import client as rpc
    from mixar.modules.space_mixie_chat.core import turn_transport, rules
    client = SimpleNamespace(connection_id='conn-1')
    monkeypatch.setattr(rpc, 'get_client', lambda: client)
    monkeypatch.setattr(rules, 'compose_wire_message', lambda scene, text: '<rules>'+text)
    monkeypatch.setattr(rules, 'mark_rules_sent', lambda scene: None)
    handler = SimpleNamespace(start_stream=MagicMock(return_value=True))
    monkeypatch.setattr(turn_transport, 'create_turn_handler', lambda **kwargs: handler)
    scene = _scene(state='BUSY', session_id='sid-7')
    SessionManager.set_state(scene, SessionState.BUSY)
    SessionManager.set_run(scene, 'r1', True)
    assert composer_send.send_user_message(scene, composer_send.OutgoingMessage(
        text='make it taller', mark_context={'m':1})) == (True, '')
    payload = handler.start_stream.call_args.kwargs
    assert payload['session_id'] == 'sid-7'
    assert payload['message'] == '<rules>make it taller'
    assert payload['mark_context'] == {'m':1}
    assert scene.mixie_chat_state == 'BUSY'


def test_busy_send_without_open_run_is_refused():
    scene = _scene(state="BUSY")
    ok, err = composer_send.send_user_message(scene, composer_send.OutgoingMessage(text="x"))
    assert ok is False and err


# ---------------------------------------------------------------------------
# E. Surfaces: status, guards, wiring pins
# ---------------------------------------------------------------------------


def test_status_pill_reads_working_in_background_for_idle_open_run(monkeypatch):
    from mixar.modules.agent_bubble.ui import header

    monkeypatch.setattr(header, "_transport_down", lambda: False)
    scene = _scene(state="IDLE")
    assert header._get_status(scene).label == "Idle"
    scene.mixie_run_open = True
    status = header._get_status(scene)
    assert status.label == "Working"
    scene.mixie_chat_state = "BUSY"
    assert header._get_status(scene).label == "Running", "BUSY still wins"


def test_cat_pulses_while_run_open_and_orchestrator_idle():
    from mixar.modules.space_mixie_chat.core import cat_activity

    scene = _scene(state="IDLE")
    cat_activity._pulse(scene, "WORKING")
    assert scene.mixie_chat_cat_activity == ""
    scene.mixie_run_open = True
    cat_activity._pulse(scene, "WORKING")
    assert scene.mixie_chat_cat_activity == "WORKING"


def test_parked_resume_never_fires_over_an_open_run(monkeypatch):
    from mixar.modules.space_mixie_chat.core import parked_resume

    bpy = sys.modules["bpy"]
    bpy.ops.mixie_chat.send_message = MagicMock(side_effect=AssertionError("must not send"))
    scene = _scene(state="IDLE")
    scene.mixie_run_open = True
    assert parked_resume.send_continue(scene) is False


def test_viewport_lock_stays_keyed_on_turn_state_only():
    from mixar.modules.agent_viewport_lock.core import state_probe

    scene = _scene(state="IDLE")
    scene.mixie_chat_active_turn_mode = "AGENT"
    scene.mixie_run_open = True
    assert state_probe.is_agent_executing(scene) is False


def _source(rel):
    root = os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat")
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


def test_every_send_surface_uses_the_shared_predicate():
    chat_ops = _source("ui/operators/chat_ops.py")
    assert "can_send(context.scene)" in chat_ops
    assert "create_sse_handler" not in chat_ops, "the choice point owns the handler"
    assert "send_user_message(scene, OutgoingMessage(" in chat_ops

    quick = _source("ui/operators/quick_prompt_ops.py")
    assert quick.count("can_send(scene)") >= 2

    props = _source("ui/properties/chat_props.py")
    assert "_report_send_refused(reason)" in props, "Enter is never swallowed silently"

    abort = _source("ui/operators/session_ops.py")
    assert 'session.set_run(scene, "", False)' in abort


# ---------------------------------------------------------------------------
# F. Parallel Agents cards outlive the orchestrator's turn, not the run
# ---------------------------------------------------------------------------


def _card_settle(monkeypatch):
    from mixar.modules.agent_panel.core import cards

    calls = []
    monkeypatch.setattr(cards, "settle_running", lambda: calls.append(True))
    return calls


def test_turn_end_of_an_open_run_leaves_the_cards_running(monkeypatch):
    from mixar.modules.space_mixie_chat.core import slot_processor

    calls = _card_settle(monkeypatch)
    monkeypatch.setattr(slot_processor, "_bump_layout_epoch", lambda scene: None)
    scene = _scene(state="IDLE")
    scene.mixie_chat_messages.add()
    SessionManager.set_run(scene, "run-1", True)

    slot_processor.finalize_turn(scene)
    assert calls == [], "the workers on the cards are still building"

    SessionManager.set_run(scene, "run-1", True)  # re-reported open: no edge
    assert calls == []
    SessionManager.set_run(scene, "", False)      # run_status completed / cancel
    assert calls == [True]
    SessionManager.set_run(scene, "", False)      # already closed: no edge
    assert calls == [True]


def test_turn_end_without_an_open_run_settles_the_cards(monkeypatch):
    from mixar.modules.space_mixie_chat.core import slot_processor

    calls = _card_settle(monkeypatch)
    monkeypatch.setattr(slot_processor, "_bump_layout_epoch", lambda scene: None)
    scene = _scene(state="IDLE")
    scene.mixie_chat_messages.add()
    slot_processor.finalize_turn(scene)
    assert calls == [True]


def test_in_progress_turn_end_keeps_cards_and_run_then_completed_closes_both(monkeypatch):
    """The end-to-end order on the main thread: run_status in_progress, the
    `complete` handling (IDLE + finalize_turn), the run stays open and the
    cards keep running; the next turn's `completed` closes the run and
    settles them."""
    from mixar.modules.space_mixie_chat.core import slot_processor

    calls = _card_settle(monkeypatch)
    monkeypatch.setattr(slot_processor, "_bump_layout_epoch", lambda scene: None)
    monkeypatch.setattr(queue_processor.EventProcessor, "_show_feedback_on_last_agent_message", lambda self, scene: None)
    monkeypatch.setattr(queue_processor.EventProcessor, "_redraw_ui", lambda self: None)
    processor = queue_processor.EventProcessor()
    scene = _scene(state="BUSY")
    scene.mixie_chat_messages.add()

    processor._handle_typed_payload({"type": "run_status", "run_id": "run-1", "status": "in_progress"}, scene)
    processor._handle_agent_complete_internal(scene)
    assert scene.mixie_chat_state == "IDLE" and scene.mixie_run_open is True
    assert calls == []

    processor._handle_typed_payload({"type": "run_status", "run_id": "run-1", "status": "completed"}, scene)
    assert calls == [True] and scene.mixie_run_open is False
    # The closed run's turn end settles again — idempotent on terminal cards.
    processor._handle_agent_complete_internal(scene)
    assert calls == [True, True] and scene.mixie_run_open is False


def test_popup_status_reads_working_in_background_for_idle_open_run():
    from mixar.modules.agent_bubble.ui.menus import agent_bubble_menu

    scene = _scene(state="IDLE")
    assert agent_bubble_menu._get_status(scene)[0] == "Idle"
    scene.mixie_run_open = True
    assert agent_bubble_menu._get_status(scene)[0] == "Working"
    scene.mixie_chat_state = "BUSY"
    assert agent_bubble_menu._get_status(scene)[0] == "Running"
