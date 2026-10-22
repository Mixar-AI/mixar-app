# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The key-missing card's actions: enter the key, or use Mixar credits.

"Enter key" opens AI Provider Settings prefilled from the refusal with the
credential field focused, and a SUCCESSFUL save resends the refused message
exactly once with a NEW command id (the backend journals the refusal under
the old one). "Use Mixar credits instead" removes the key and resends on
platform credits. The user never retypes the prompt.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import credential_state, key_prompt  # noqa: E402
from mixar.modules.byok.ui.operators import byok_dialog_support, byok_dialog_ui  # noqa: E402
from mixar.modules.common.sheet import kit as byok_sheet  # noqa: E402
from mixar.modules.space_mixie_chat.constants import SessionState  # noqa: E402
from mixar.modules.space_mixie_chat.core import byok_card, byok_notice, byok_resend, composer_send  # noqa: E402

BYOK_OPS = SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators" / "byok_ops.py"
CHAT_OPS = SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "ui" / "operators" / "chat_special_ops.py"


class _Collection(list):
    def add(self):
        item = SimpleNamespace(bubble_id="", sender="", message_type="", text="", content="",
                               metadata="", action_items=_Collection())
        self.append(item)
        return item

    def remove(self, index):
        del self[index]

    def move(self, src, dst):
        self.insert(dst, self.pop(src))


def _scene():
    scene = SimpleNamespace(name="Scene", mixie_session_id="sess-1", mixie_chat_messages=_Collection(),
                            mixie_chat_layout_epoch=0)
    user = scene.mixie_chat_messages.add()
    user.sender, user.bubble_id, user.text = "USER", "cmd-old", "make a chair"
    return scene


def _openai_card():
    data = {"code": "byok_key_required", "provider": "openai", "model": "gpt-5"}
    return byok_notice.refusal_card({}, data)


@pytest.fixture
def f(monkeypatch):
    scene = _scene()
    sent, states = [], []
    handler = SimpleNamespace(last_command_id="")

    def _send(method, payload, user_message=None, interjecting=False):
        handler.last_command_id = f"cmd-new-{len(sent) + 1}"
        sent.append((method, payload, user_message, interjecting))
        return True

    handler._send = _send
    clock = [1000.0]
    monkeypatch.setattr(byok_card, "redraw_chat_areas", lambda: None)
    # The double-click guard has its own tests; elsewhere a click is never
    # within it, and no turn is in flight.
    monkeypatch.setattr(byok_card, "_clock", lambda: clock[0])
    monkeypatch.setattr(byok_card, "CLICK_GUARD_S", 0.0)
    monkeypatch.setattr(byok_dialog_support, "turn_in_flight", lambda context: False)
    byok_card._filled_at.clear()
    byok_card._held.clear()
    monkeypatch.setattr(byok_resend, "_scene_for", lambda sid: scene if sid == "sess-1" else None)
    monkeypatch.setattr(byok_resend, "_handler_for", lambda sc: handler)
    monkeypatch.setattr(byok_resend, "_begin_turn", lambda sc, interjecting: states.append(("busy", interjecting)))
    monkeypatch.setattr(composer_send, "can_send", lambda sc: (True, ""))
    monkeypatch.setattr(composer_send, "is_interjection", lambda sc: False)
    byok_card._cards.clear()
    byok_resend._records.clear()
    byok_resend._auto_ids.clear()
    key_prompt.reset()
    byok_resend.remember("sess-1", "cmd-old", "chat",
                         {"session_id": "sess-1", "message": "make a chair", "byok_key": "sk-x"}, False)
    byok_card.show(scene, _openai_card())
    yield SimpleNamespace(scene=scene, sent=sent, states=states, handler=handler,
                          bubble=scene.mixie_chat_messages[-1], clock=clock)
    byok_card._cards.clear()
    byok_resend._records.clear()
    byok_resend._auto_ids.clear()
    key_prompt.reset()


def _dialog(monkeypatch, opened, result=None):
    monkeypatch.setattr(sys.modules["bpy"].ops.mixar_byok, "open_dialog",
                        lambda *a, **kw: opened.append(a) or (result or {'FINISHED'}), raising=False)


# ---------------------------------------------------------------------------
# Resend
# ---------------------------------------------------------------------------

def test_resend_re_enters_the_transport_with_a_new_command_id_and_the_same_user_bubble(f):
    assert byok_resend.resend("sess-1") is True
    ((method, payload, bubble, interjecting),) = f.sent
    assert method == "chat" and payload == {"session_id": "sess-1", "message": "make a chair"}
    assert bubble is f.scene.mixie_chat_messages[0] and bubble.bubble_id == "cmd-old"
    assert interjecting is False and f.states == [("busy", False)]
    assert f.handler.last_command_id == "cmd-new-1" and byok_resend.pending("sess-1") is None


def test_resend_waits_while_the_session_cannot_take_a_send(f, monkeypatch):
    monkeypatch.setattr(composer_send, "can_send", lambda sc: (False, "busy"))
    assert byok_resend.resend("sess-1") is False
    assert f.sent == [] and byok_resend.pending("sess-1") is not None
    assert byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_RESEND) is True
    assert f.bubble.text.startswith("Couldn't resend yet")
    assert [a.value for a in f.bubble.action_items][0] == byok_card.ACTION_ENTER


def test_a_repeat_refusal_moves_the_one_card_under_the_newest_message(f):
    card_id = f.bubble.bubble_id
    retry = f.scene.mixie_chat_messages.add()
    retry.sender, retry.bubble_id, retry.text = "USER", "cmd-retry", "make a chair"
    byok_card.show(f.scene, _openai_card())
    assert [m.bubble_id for m in f.scene.mixie_chat_messages] == ["cmd-old", "cmd-retry", card_id]
    assert f.scene.mixie_chat_messages[-1].text.startswith("Enter your OpenAI API key")


def test_every_card_change_re_lays_out_the_native_chat(f):
    """The native layout cache keys on the message count: a card moved to the
    end (or refreshed in place) with the count unchanged would draw stale
    rows unless the layout epoch moves."""
    assert f.scene.mixie_chat_layout_epoch == 1  # the first show
    count = len(f.scene.mixie_chat_messages)
    f.scene.mixie_chat_messages.move(len(f.scene.mixie_chat_messages) - 1, 0)
    byok_card.show(f.scene, _openai_card())  # a repeat refusal: moved, not added
    assert len(f.scene.mixie_chat_messages) == count
    assert f.scene.mixie_chat_messages[-1].bubble_id.startswith(byok_card.BUBBLE_PREFIX)
    assert f.scene.mixie_chat_layout_epoch == 2
    card_id = f.scene.mixie_chat_messages[-1].bubble_id
    byok_card.handle_action(f.scene, card_id, byok_card.ACTION_WHY)  # refreshed in place
    assert f.scene.mixie_chat_layout_epoch == 3


def test_why_unfolds_one_line_however_often_a_stale_button_is_clicked(f):
    """A click dispatched on a cached hit target before the re-layout lands
    on a Why button that is already gone."""
    card = _openai_card()
    for _ in range(3):
        assert byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_WHY) is True
    assert f.bubble.text == f"{card.line}\n\n{card.why_line}"
    assert f.bubble.text.count(card.why_line) == 1
    assert byok_card.ACTION_WHY not in [a.value for a in f.bubble.action_items]


def test_a_new_refusal_after_why_resets_the_card(f):
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_WHY)
    card = _openai_card()
    byok_card.show(f.scene, card)
    bubble = f.scene.mixie_chat_messages[-1]
    assert bubble.text == card.line
    assert [a.value for a in bubble.action_items] == [
        byok_card.ACTION_ENTER, byok_card.ACTION_USE_CREDITS, byok_card.ACTION_WHY]


def test_try_again_resends_and_drops_the_card(f):
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_RESEND)
    assert len(f.sent) == 1
    assert [m.bubble_id for m in f.scene.mixie_chat_messages] == ["cmd-old"]


def test_begin_turn_marks_the_scene_busy_with_a_placeholder(monkeypatch):
    from mixar.modules.space_mixie_chat.core import byok_resend as module
    from mixar.modules.space_mixie_chat.core import message_helpers, session

    scene, calls = _scene(), []
    monkeypatch.setattr(session, "get_session_manager", lambda: SimpleNamespace(
        set_state=lambda sc, st: calls.append(st), clear_streaming=lambda: calls.append("clear")))
    monkeypatch.setattr(message_helpers, "add_turn_placeholder", lambda sc: calls.append("placeholder"))
    module._begin_turn(scene, interjecting=False)
    assert calls == [SessionState.BUSY, "clear", "placeholder"]
    module._begin_turn(scene, interjecting=True)
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# Enter key → the dialog → save → resend once
# ---------------------------------------------------------------------------

def test_enter_key_opens_the_dialog_prefilled_and_a_successful_save_resends_once(f, monkeypatch):
    opened = []
    _dialog(monkeypatch, opened)
    assert byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_ENTER) is True
    assert opened == [('INVOKE_DEFAULT',)]
    # The dialog's invoke takes the prefill; from here the form is key-only
    # with the key field focused.
    assert key_prompt.take() == {"provider": "openai", "model": "gpt-5", "focus": key_prompt.FOCUS_KEY}
    assert key_prompt.is_open() and key_prompt.focus_is(key_prompt.FOCUS_KEY)
    assert byok_dialog_ui._device_key_missing(SimpleNamespace(byok_is_active=False, byok_device_key_missing=False))
    assert f.sent == []
    key_prompt.notify_saved()          # the save's echo landed
    key_prompt.notify_saved()          # a second echo (or Done) never resends again
    assert len(f.sent) == 1 and f.sent[0][1]["message"] == "make a chair"
    assert not key_prompt.is_open()
    assert [m.bubble_id for m in f.scene.mixie_chat_messages] == ["cmd-old"]


def test_removing_the_key_in_the_card_opened_dialog_resends_on_credits(f, monkeypatch):
    """Remove key / Disconnect in the dialog is "Use Mixar credits instead":
    the dialog already applied the removal, the card resends once and goes."""
    _dialog(monkeypatch, [])
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_ENTER)
    key_prompt.take()
    epoch = f.scene.mixie_chat_layout_epoch
    key_prompt.notify_removed()        # the DELETE's echo landed
    key_prompt.notify_saved()          # nothing left to run
    assert len(f.sent) == 1 and f.sent[0][1]["message"] == "make a chair"
    assert [m.bubble_id for m in f.scene.mixie_chat_messages] == ["cmd-old"]
    assert f.scene.mixie_chat_layout_epoch == epoch + 1
    assert not key_prompt.is_open()


def test_the_dialog_removal_tells_the_card():
    src = BYOK_OPS.read_text(encoding="utf-8")
    done = src[src.index("def _on_delete_done("):]
    success = done[:done.index("        else:")]
    assert "key_prompt.notify_removed()" in success and "wm.byok_dialog_state = 'REMOVED'" in success


def test_codex_cards_focus_the_sign_in_file_field(f, monkeypatch):
    opened = []
    _dialog(monkeypatch, opened)
    card = byok_notice.refusal_card({}, {"code": "byok_codex_expired"})
    byok_card.show(f.scene, card)
    bubble = f.scene.mixie_chat_messages[-1]
    byok_card.handle_action(f.scene, bubble.bubble_id, byok_card.ACTION_ENTER)
    assert key_prompt.take() == {"provider": "codex", "model": "", "focus": key_prompt.FOCUS_CODEX_PATH}
    assert key_prompt.focus_is(key_prompt.FOCUS_CODEX_PATH) and not key_prompt.focus_is(key_prompt.FOCUS_KEY)


def test_a_dialog_that_is_already_open_keeps_the_card_and_arms_nothing(f, monkeypatch):
    opened = []
    _dialog(monkeypatch, opened, result={'CANCELLED'})
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_ENTER)
    assert key_prompt.take() is None
    assert f.bubble.text.startswith("AI Provider Settings is already open")
    assert len(f.bubble.action_items) == 3


def test_closing_the_dialog_without_saving_forgets_the_resend():
    key_prompt.request("openai", "gpt-5", key_prompt.FOCUS_KEY, on_saved=lambda: (_ for _ in ()).throw(AssertionError))
    key_prompt.take()
    key_prompt.dismiss(saving=True)    # Esc while SAVING keeps the request for its echo
    assert key_prompt.is_open()
    key_prompt.dismiss()               # Cancel / Done
    assert not key_prompt.is_open() and key_prompt.take() is None
    key_prompt.notify_saved()          # nothing to run


def test_the_key_field_focuses_the_credential_field_only_when_asked():
    class Field:
        def prop(self, *a, **kw):
            pass

    rest, asked = Field(), Field()
    byok_sheet.input_field(rest, object(), "byok_form_api_key")
    assert not hasattr(rest, "activate_init")
    byok_sheet.input_field(asked, object(), "byok_form_api_key", activate=True)
    assert asked.activate_init is True


def test_the_dialog_operator_takes_the_prefill_and_resends_on_save():
    src = BYOK_OPS.read_text(encoding="utf-8")
    invoke = src[src.index("def invoke("):src.index("def execute(")]
    assert "_prefill_from_prompt(wm, key_prompt.take())" in invoke
    assert invoke.index("_wipe_form_secrets(wm)") < invoke.index("_prefill_from_prompt(")
    saved = src[src.index("def _on_save_done("):src.index("def _on_save_done(") + 1500]
    success = saved[:saved.index("else:")]
    assert "key_prompt.notify_saved()" in success and "wm.byok_dialog_state = 'SAVED'" in success
    for method in ("def execute(", "def cancel("):
        body = src[src.index(method):]
        body = body[:body.index("\n    def ")]
        assert "key_prompt.dismiss(saving=_saving(context.window_manager))" in body
    # The helper lives beside the dialog's other helpers (byok_ops is at the
    # 500-line rule) and is imported under the same name.
    assert "saving as _saving," in src
    support = (BYOK_OPS.parent / "byok_dialog_support.py").read_text(encoding="utf-8")
    assert "def saving(wm)" in support and "== 'SAVING'" in support


def test_the_slot_action_operator_hands_card_values_to_the_card_first():
    src = CHAT_OPS.read_text(encoding="utf-8")
    body = src[src.index("class MIXIE_CHAT_OT_select_slot_action"):]
    assert body.index("byok_card.is_card_action(self.action_value)") < body.index("CREDIT_UPGRADE_CHAT_ACTION")
    assert "byok_card.handle_action(context.scene, self.bubble_id, self.action_value)" in body


# ---------------------------------------------------------------------------
# Use Mixar credits instead → remove → resend on credits
# ---------------------------------------------------------------------------

@pytest.fixture
def removal(monkeypatch):
    from mixar.modules.byok.core import byok_client, preference_state
    from mixar.modules.byok.core import local_switch

    deletes, refreshes, deregistered = [], [], []
    monkeypatch.setattr(byok_client, "delete_credentials", lambda on_done: deletes.append(on_done))
    monkeypatch.setattr(preference_state, "refresh", lambda: refreshes.append(True))
    monkeypatch.setattr(local_switch, "deregister_local_if_switched_away", deregistered.append)
    credential_state.apply_from_payload({"byok_active": True, "items": [{"provider": "openai", "model": "gpt-5"}]})
    return SimpleNamespace(deletes=deletes, refreshes=refreshes, deregistered=deregistered)


def test_use_mixar_credits_removes_the_key_then_resends_on_credits(f, removal):
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_USE_CREDITS)
    assert f.bubble.text == "Switching to Mixar credits…" and list(f.bubble.action_items) == []
    (on_done,) = removal.deletes
    assert f.sent == []
    on_done(True, 1, None)
    state = credential_state.snapshot()
    assert state["byok_is_active"] is False and state["byok_state_loaded"] is True
    assert removal.refreshes == [True] and removal.deregistered == [None]
    assert len(f.sent) == 1 and f.sent[0][1]["message"] == "make a chair"
    assert [m.bubble_id for m in f.scene.mixie_chat_messages] == ["cmd-old"]


def test_a_failed_removal_keeps_the_key_and_the_card(f, removal):
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_USE_CREDITS)
    removal.deletes[0](False, 0, "NET-3")
    assert credential_state.snapshot()["byok_is_active"] is True
    assert f.sent == [] and removal.refreshes == []
    assert f.bubble.text == "Couldn't switch to Mixar credits — try again"
    assert [a.value for a in f.bubble.action_items] == [
        byok_card.ACTION_ENTER, byok_card.ACTION_USE_CREDITS, byok_card.ACTION_WHY]


# ---------------------------------------------------------------------------
# Stale clicks: the native hit targets are the cached layout
# ---------------------------------------------------------------------------

def test_the_resend_dismissal_re_lays_out_the_chat(f):
    """The resend adds its placeholder before the card goes, so the message
    count ends where it started: only the epoch tells the native layout the
    card's buttons are gone."""
    epoch = f.scene.mixie_chat_layout_epoch
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_RESEND)
    assert not any(m.bubble_id.startswith(byok_card.BUBBLE_PREFIX) for m in f.scene.mixie_chat_messages)
    assert f.scene.mixie_chat_layout_epoch == epoch + 1


def test_a_click_on_a_dismissed_card_does_nothing(f, removal, monkeypatch):
    opened = []
    _dialog(monkeypatch, opened)
    card_id = f.bubble.bubble_id
    byok_card.dismiss(f.scene)
    for value in (byok_card.ACTION_USE_CREDITS, byok_card.ACTION_ENTER, byok_card.ACTION_RESEND):
        assert byok_card.handle_action(f.scene, card_id, value) is True
    assert removal.deletes == [] and opened == [] and f.sent == []


def test_use_credits_waits_while_a_turn_is_in_flight(f, removal, monkeypatch):
    monkeypatch.setattr(byok_dialog_support, "turn_in_flight", lambda context: True)
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_USE_CREDITS)
    assert removal.deletes == [] and f.sent == []
    assert f.bubble.text.startswith("Couldn't resend yet")
    assert [a.value for a in f.bubble.action_items] == [
        byok_card.ACTION_ENTER, byok_card.ACTION_USE_CREDITS, byok_card.ACTION_WHY]


def test_a_click_right_after_the_card_changes_is_ignored(f, removal, monkeypatch):
    """Why unfolds a line and slides "Use Mixar credits instead" under the
    pointer: the second press of a double click must not remove the key."""
    monkeypatch.setattr(byok_card, "CLICK_GUARD_S", 0.5)
    f.clock[0] = 1000.2                       # shown at 1000.0: too soon
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_WHY)
    assert f.bubble.text == _openai_card().line
    f.clock[0] = 1000.6
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_WHY)
    assert f.bubble.text.endswith(_openai_card().why_line)
    f.clock[0] = 1000.8                       # the double click's second press
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_USE_CREDITS)
    assert removal.deletes == []
    f.clock[0] = 1001.2
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_USE_CREDITS)
    assert len(removal.deletes) == 1


# ---------------------------------------------------------------------------
# A refused interjection, and the turn ending
# ---------------------------------------------------------------------------

SESSION_PY = SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core" / "session.py"


def _card_ids(scene):
    return [m.bubble_id for m in scene.mixie_chat_messages if m.bubble_id.startswith(byok_card.BUBBLE_PREFIX)]


def test_a_refused_interjections_card_waits_for_its_turn_to_settle(f, monkeypatch):
    """The card would land between the streaming turn's bubbles: it is held,
    and posted (under everything) once the turn stops streaming."""
    monkeypatch.setattr(sys.modules["bpy"].data, "scenes", [f.scene], raising=False)
    byok_card.dismiss(f.scene)
    f.scene.mixie_chat_state = 'BUSY'
    streamed = f.scene.mixie_chat_messages.add()
    streamed.sender, streamed.bubble_id = "AGENT", "turn-reply"
    byok_card.show(f.scene, _openai_card())
    assert _card_ids(f.scene) == []
    byok_card.turn_settled(f.scene)          # a run closing while still BUSY: still held
    assert _card_ids(f.scene) == []
    f.scene.mixie_chat_state = 'IDLE'
    byok_card.turn_settled(f.scene)
    assert f.scene.mixie_chat_messages[-1].bubble_id.startswith(byok_card.BUBBLE_PREFIX)
    assert f.scene.mixie_chat_messages[-1].text == _openai_card().line
    byok_card.turn_settled(f.scene)          # posted once
    assert len(_card_ids(f.scene)) == 1
    assert byok_resend.pending("sess-1") is not None  # the refused message is still remembered


def test_the_busy_line_is_restored_when_no_turn_runs_any_more(f, removal, monkeypatch):
    monkeypatch.setattr(sys.modules["bpy"].data, "scenes", [f.scene], raising=False)
    running = [True]
    monkeypatch.setattr(byok_dialog_support, "turn_in_flight", lambda context: running[0])
    byok_card.handle_action(f.scene, f.bubble.bubble_id, byok_card.ACTION_USE_CREDITS)
    assert f.bubble.text.startswith("Couldn't resend yet")
    byok_card.turn_settled(f.scene)          # another tab still streams
    assert f.bubble.text.startswith("Couldn't resend yet")
    running[0] = False
    epoch = f.scene.mixie_chat_layout_epoch
    byok_card.turn_settled(f.scene)
    assert f.bubble.text == _openai_card().line
    assert [a.value for a in f.bubble.action_items] == [
        byok_card.ACTION_ENTER, byok_card.ACTION_USE_CREDITS, byok_card.ACTION_WHY]
    assert f.scene.mixie_chat_layout_epoch == epoch + 1 and removal.deletes == []


def test_the_session_tells_the_card_when_a_turn_stops_streaming_or_its_run_closes():
    src = SESSION_PY.read_text(encoding="utf-8")
    set_state = src[src.index("    def set_state("):src.index("    def _turn_eased(")]
    assert "if old_str == SessionState.BUSY.value.upper():" in set_state
    assert set_state.rstrip().count("SessionManager._turn_eased(scene)") == 1
    closed = src[src.index("        if was_open and not open:"):src.index("    def clear_all_runs(")]
    assert "SessionManager._turn_eased(scene)" in closed
    eased = src[src.index("    def _turn_eased("):]
    assert "turn_settled(scene)" in eased[:eased.index("\n    @")]


# ---------------------------------------------------------------------------
# The fetch hook the cold-start resend waits on
# ---------------------------------------------------------------------------

def test_on_next_fetch_fires_once_per_outcome_and_is_dropped_by_logout(monkeypatch):
    seen = []
    credential_state.on_next_fetch(seen.append)
    epoch = credential_state.current_epoch()
    credential_state._apply_fetch_result(epoch, False, None, "net")
    credential_state._apply_fetch_result(epoch, True, {"byok_active": False, "items": []}, None)
    assert seen == [False]
    credential_state.on_next_fetch(seen.append)
    credential_state._apply_fetch_result(epoch, True, {"byok_active": False, "items": []}, None)
    assert seen == [False, True]
    credential_state.on_next_fetch(seen.append)
    credential_state.clear()
    credential_state._apply_fetch_result(credential_state.current_epoch(), True, {"byok_active": False, "items": []}, None)
    assert seen == [False, True]
