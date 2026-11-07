# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Steering and parallel-tab discovery: held sends, busy composer hints,
the New chat choice while a task runs, and the telemetry that measures them."""

import importlib
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest

from mixar.modules.common.analytics import essential_events as essential
from mixar.modules.space_mixie_chat import constants
from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core import held_sends, tab_activity

composer_send = importlib.import_module('mixar.modules.space_mixie_chat.core.composer_send')

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src/scripts/mixar/modules"
BUBBLE = ROOT / "src/source/blender/editors/space_agent_bubble"


def read(path):
    return Path(path).read_text(encoding="utf-8")


class FakeMessages(list):
    def add(self):
        msg = NS(sender='', text='', bubble_id='', delivery_hint='')
        self.append(msg)
        return msg

    def remove(self, index):
        del self[index]


_uids = iter(range(1000, 100000))


def scene(name='Tab', state=SessionState.BUSY, run_open=False):
    return NS(name=name, session_uid=next(_uids), mixie_chat_messages=FakeMessages(),
              mixie_chat_input='', _state=state, mixie_run_open=run_open)


def fake_session():
    return NS(get_state=lambda s: s._state, run_open=lambda s: s.mixie_run_open)


@pytest.fixture(autouse=True)
def clean_state():
    held_sends._held.clear()
    with patch('mixar.modules.space_mixie_chat.core.session.get_session_manager',
               return_value=fake_session()), \
            patch.object(composer_send, 'get_session_manager', return_value=fake_session()):
        yield
    held_sends._held.clear()


# ---- delivery labels ----------------------------------------------------

def test_delivery_labels_fit_the_bubble_property():
    # ChatMessage.delivery_hint is maxlen=32; the native label buffer is 40.
    for hint in (constants.HINT_STEER, constants.HINT_QUEUED):
        assert 0 < len(hint) < 32


# ---- held sends ---------------------------------------------------------

def test_hold_only_while_busy_without_an_open_run():
    assert held_sends.should_hold(scene(state=SessionState.BUSY, run_open=False))
    assert not held_sends.should_hold(scene(state=SessionState.BUSY, run_open=True))
    assert not held_sends.should_hold(scene(state=SessionState.IDLE))
    assert not held_sends.should_hold(scene(state=SessionState.AWAITING_INPUT))


def test_held_message_is_a_labelled_bubble_and_restores_to_the_composer():
    s = scene()
    held_sends.hold(s, "make it red")
    held_sends.hold(s, "and taller")
    assert [m.delivery_hint for m in s.mixie_chat_messages] == [constants.HINT_QUEUED] * 2
    assert all(m.bubble_id.startswith(held_sends.HELD_PREFIX) for m in s.mixie_chat_messages)
    s.mixie_chat_input = "draft"
    held_sends.restore(s)
    assert list(s.mixie_chat_messages) == []
    assert s.mixie_chat_input == "make it red\nand taller\ndraft"
    assert held_sends.held_count(s) == 0


def test_tick_sends_into_a_running_task_one_message_per_tick():
    s = scene()
    held_sends.hold(s, "first")
    held_sends.hold(s, "second")
    sent = []
    with patch.object(held_sends, '_scene_for', return_value=s), \
            patch.object(held_sends, '_decide', side_effect=['wait', 'send', 'send']), \
            patch.object(held_sends, '_send', side_effect=lambda sc, t: sent.append(t)):
        assert held_sends._tick() == held_sends._INTERVAL   # no running task yet: both wait
        assert sent == []
        assert held_sends._tick() == held_sends._INTERVAL   # one per tick
        assert sent == ["first"]
        assert held_sends._tick() is None                   # drained: timer stops
    assert sent == ["first", "second"]
    assert list(s.mixie_chat_messages) == []


def test_turn_ending_without_a_running_task_hands_the_text_back():
    # A chat-only reply, a refusal, an error or a lost connection: nothing is
    # sent for the user; the words return to the composer.
    s = scene()
    held_sends.hold(s, "also make it red")
    s._state = SessionState.IDLE          # the turn settled, no run ever opened
    with patch.object(held_sends, '_scene_for', return_value=s), \
            patch.object(held_sends, '_send') as send:
        assert held_sends._tick() is None
    send.assert_not_called()
    assert list(s.mixie_chat_messages) == []
    assert s.mixie_chat_input == "also make it red"


def test_decide_only_sends_into_an_open_run():
    with patch.object(composer_send, 'can_send', return_value=(True, '')):
        assert held_sends._decide(scene(state=SessionState.BUSY, run_open=True)) == 'send'
        assert held_sends._decide(scene(state=SessionState.IDLE, run_open=True)) == 'send'
        assert held_sends._decide(scene(state=SessionState.BUSY, run_open=False)) == 'wait'
        assert held_sends._decide(scene(state=SessionState.AWAITING_INPUT, run_open=True)) == 'wait'
        for ended in (SessionState.IDLE, SessionState.OFFLINE, SessionState.CONNECTING,
                      SessionState.AWAITING_INPUT):
            assert held_sends._decide(scene(state=ended, run_open=False)) == 'restore'


def test_a_send_that_does_not_go_out_puts_the_text_back():
    s = scene(state=SessionState.BUSY, run_open=True)
    s.mixie_chat_input = "draft"
    ops = MagicMock(return_value={'CANCELLED'})
    with patch.object(held_sends.bpy.ops.mixie_chat, 'send_message', ops), \
            patch.object(held_sends, '_window_for', return_value=None):
        held_sends._send(s, "make it red")
    assert s.mixie_chat_input == "make it red\ndraft"
    assert not held_sends.is_flushing()


def test_tick_drops_entries_whose_chat_was_cleared():
    s = scene()
    held_sends.hold(s, "lost")
    s.mixie_chat_messages.clear()          # file load / history restore
    with patch.object(held_sends, '_scene_for', return_value=s), \
            patch.object(held_sends, '_send') as send:
        assert held_sends._tick() is None
    send.assert_not_called()


def test_held_entries_follow_the_tab_not_its_name():
    s = scene()
    held_sends.hold(s, "keep me")
    s.name = "Renamed tab"
    assert held_sends.held_count(s) == 1


def test_queued_send_is_text_only():
    src = read(MOD / "space_mixie_chat/ui/operators/chat_ops.py")
    assert "plain = is_modify or is_awaiting_input or held" in src
    assert "outgoing_attachments = [] if held else list(pending_attachments)" in src
    assert "if not held:\n            pending_attachments.clear()" in src
    assert "if not held:\n                deselect_all_moodboard_origin_attachments(scene)" in src


def test_can_compose_holds_instead_of_refusing_a_busy_turn():
    s = scene(state=SessionState.BUSY, run_open=False)
    with patch.object(composer_send, '_blocked', return_value=''), \
            patch.object(composer_send, 'can_send', return_value=(False, 'Working...')):
        assert composer_send.can_compose(s) == (True, '')
    # A real refusal (video attachment, model switch, rewind) still refuses.
    with patch.object(composer_send, '_blocked', return_value='Restoring'), \
            patch.object(composer_send, 'can_send', return_value=(False, 'Restoring')):
        assert composer_send.can_compose(s) == (False, 'Restoring')


def test_joins_running_task_covers_open_runs_only():
    assert composer_send.joins_running_task(scene(state=SessionState.BUSY, run_open=True))
    assert composer_send.joins_running_task(scene(state=SessionState.IDLE, run_open=True))
    assert not composer_send.joins_running_task(scene(state=SessionState.BUSY, run_open=False))
    assert not composer_send.joins_running_task(scene(state=SessionState.AWAITING_INPUT, run_open=True))


# ---- telemetry -------------------------------------------------------------

def test_message_sent_carries_steering_and_tab_counts_only():
    ctx = NS(area=NS(type='VIEW_3D'), scene=NS(mixie_chat_mode='AGENT', name='/private/x'))
    with patch.object(essential, 'capture') as emit, \
            patch.object(tab_activity, 'tab_counts', return_value=(3, 2)):
        essential.capture_agent_message(ctx, [], False, False, None, interjecting=True)
        essential.capture_agent_message(ctx, [], False, False, None)
    steered, plain = (c.args[1] for c in emit.call_args_list)
    assert (steered['interjecting'], steered['held']) == (True, False)
    assert 'busy_hint' not in steered
    assert (steered['scene_tabs'], steered['other_tabs_working']) == (3, 2)
    assert plain['interjecting'] is False
    assert '/private' not in str([c.args[1] for c in emit.call_args_list])


def test_new_scene_operator_reports_parallel_context():
    with patch.object(tab_activity, 'tab_counts', return_value=(2, 1)):
        props = essential.scene_tab_operator_properties('mixie_chat.new_scene_tab', {'FINISHED'}, None)
        assert props == {'other_tabs_working': 1}
        assert essential.scene_tab_operator_properties('mixie_chat.new_scene_tab', {'CANCELLED'}, None) == {}
        assert essential.scene_tab_operator_properties('mixie_chat.switch_scene_tab', {'FINISHED'}, None) == {}


# ---- wiring (operators are mocks under the stubbed bpy) ---------------------

def test_send_operator_polls_can_compose_and_holds_before_encoding():
    src = read(MOD / "space_mixie_chat/ui/operators/chat_ops.py")
    poll = src[src.index("def poll(cls, context):"):src.index("def execute(self, context):")]
    assert "can_compose(context.scene)" in poll
    hold = src.index("held_sends.hold(scene, message_text)")
    assert src.index("ws_client.connection_id") < hold < src.index("encode_outgoing_attachments(")
    assert "user_msg.delivery_hint = HINT_STEER" in src
    assert "interjecting=steering, held=held" in src


@pytest.mark.parametrize('blocked, sends', [('', True), ('Restoring', False)])
def test_enter_holds_a_busy_send_like_the_button(monkeypatch, blocked, sends):
    """#1887: Enter refused with "Working..." while the Steer button held the
    message. Enter now asks the operator's predicate: a busy turn with no open
    run reaches send_message (which holds it); a real refusal still reports."""
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    from mixar.modules.space_mixie_chat.ui.properties import chat_props
    monkeypatch.setattr(composer_send, 'can_send', lambda sc: (False, blocked or 'Working...'))
    monkeypatch.setattr(composer_send, '_blocked', lambda sc: blocked)
    monkeypatch.setattr(held_sends, 'should_hold', lambda sc: True)
    monkeypatch.setattr(auth_ops, 'guest_seat_pending', lambda: False)
    send, refused = MagicMock(), MagicMock()
    monkeypatch.setattr(chat_props.bpy.ops.mixie_chat, 'send_message', send, raising=False)
    monkeypatch.setattr(chat_props, '_report_send_refused', refused)
    chat_props._execute_send_message()
    assert send.called is sends
    assert refused.call_args_list == ([] if sends else [((blocked,),)])


def test_stop_and_new_chat_hand_held_text_back():
    src = read(MOD / "space_mixie_chat/ui/operators/session_ops.py")
    assert "held_sends.restore(scene)" in src
    assert "held_text = held_sends.release(scene)" in src
    assert "scene.mixie_chat_input = held_text" in src


def test_new_chat_while_working_offers_a_scene_tab_first():
    src = read(MOD / "space_mixie_chat/ui/operators/session_ops.py")
    invoke = src[src.index("    def invoke(self, context, event):\n        # The \"+\""):]
    assert 'call_menu(name="MIXIE_CHAT_MT_new_chat_busy")' in invoke
    menu = read(MOD / "agent_bubble/ui/menus/new_chat_menu.py")
    first, second = menu.index("mixie_chat.new_scene_tab"), menu.index("mixie_chat.new_session")
    assert first < second
    assert "operator_context = 'EXEC_DEFAULT'" in menu  # the second row must not re-open the menu


def test_native_island_reads_the_hint_and_labels_steer():
    state = read(BUBBLE / "agent_ui_state.cc")
    assert 'IFACE_("Mixie is working. Type here to steer it...")' in state and "steer_visible" in state
    assert 'enum_is(&scene_ptr, "mixie_chat_state", "BUSY")' in state
    assert 'IFACE_("Steer")' in read(BUBBLE / "agent_ui_controls_paint.cc")
    assert "steer_visible" in read(BUBBLE / "agent_bubble_references.cc")


def test_multiline_placeholder_shows_while_editing_an_empty_draft():
    # The composer auto-focuses when the island opens; a placeholder drawn
    # only while NOT editing was never seen (the busy hint included).
    src = read(ROOT / "src/source/blender/editors/interface/interface_widgets.cc")
    block = src[src.index("if (!drawstr || !drawstr[0]) {"):src.index("/* Calculate line height */")]
    assert "button_placeholder_get(but)" in block
    assert block.index("button_placeholder_get(but)") < block.index("if (!but->editstr) {\n        return;")
