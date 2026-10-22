# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pause and resume switch who answers, in one click.

Contract pinned here (byok/ui/operators/byok_toggle_ops.py,
byok/core/credential_state.py, byok/core/byok_client.py); which island pick
runs which is `tests/test_agent_picker.py`:
- A pause (a Mixie pick while a key is in use) DELETES the server rows and
  KEEPS this computer's key record — no dialog, no key lost.
- "Use my key" RESUMES a paused key by re-sending the record
  (`resave_stored_key`, no dialog, no typing) and otherwise opens AI
  Provider Settings.
- Nothing is flipped ahead of the server (a turn sent meanwhile must still
  carry the key); the echo settles it, a failure re-reads and toasts.
- Reads issued before a write are dropped when they land; a read held by a
  mutation is re-issued for whoever waits on it.
- One account mutation at a time: toggle, model switch, hosted pick, save and
  remove exclude each other.
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

from mixar.modules.byok.core import credential_state, key_store, picker, preference_state
from mixar.modules.byok.ui.operators import byok_toggle_ops as ops


def _picker():
    """What the island chip and popup read (core/picker.py over the mirrors)."""
    return picker.picker_state(credential_state.snapshot(), preference_state.snapshot(),
                               pending=credential_state.pending(),
                               switching=credential_state.switching())


def _chip():
    return picker.chip(_picker())

RESUMABLE = {"provider": "anthropic", "model": "claude-opus-5-5"}


def _payload(active=True, model="claude-opus-5-5"):
    items = [{"provider": "anthropic", "model": model, "key_preview": "sk-ant-…1234"}] if active else []
    return {"byok_active": active, "items": items}


@pytest.fixture
def env(monkeypatch):
    """Clean mirrors, a recording fake HTTP layer and key store, no redraws, no toasts."""
    import bpy

    wm = SimpleNamespace()
    monkeypatch.setattr(bpy.context, "window_manager", wm, raising=False)
    calls = SimpleNamespace(delete=[], resave=[], fetch=[], pref_fetch=[], toasts=[],
                            resumable=[], presence=[], forget=[])
    monkeypatch.setattr(ops.byok_client, "delete_credentials",
                        lambda on_done, forget_local=True: calls.delete.append((on_done, forget_local)))
    monkeypatch.setattr(ops.byok_client, "resave_stored_key",
                        lambda model, on_done: calls.resave.append((model, on_done)))
    monkeypatch.setattr(ops.byok_client, "forget_stored_key",
                        lambda on_done: calls.forget.append(on_done))
    monkeypatch.setattr(credential_state.byok_client, "fetch_state",
                        lambda on_done: calls.fetch.append(on_done))
    monkeypatch.setattr(preference_state.preference_client, "fetch_preference",
                        lambda on_done: calls.pref_fetch.append(on_done))
    monkeypatch.setattr(key_store, "check_resumable_async",
                        lambda on_done: calls.resumable.append(on_done))
    monkeypatch.setattr(key_store, "check_presence_async",
                        lambda provider, on_done: calls.presence.append(on_done))
    monkeypatch.setattr(ops, "_toast", lambda title, err: calls.toasts.append((title, err)))
    monkeypatch.setattr(ops, "_redraw", lambda: None)
    monkeypatch.setattr(preference_state, "_redraw", lambda: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    credential_state.clear(wm)
    preference_state.clear(wm)
    yield wm, calls
    credential_state.clear(wm)
    preference_state.clear(wm)


def _key_in_use(wm, calls=None, summary=RESUMABLE):
    credential_state.apply_from_payload(_payload(), wm)
    preference_state.apply_local({"mixar_agent_model_byok_active": True}, wm)
    if calls is not None:
        calls.resumable[-1](summary)  # the record here could be re-sent


def _paused(wm, calls, summary=RESUMABLE):
    credential_state.apply_from_payload(_payload(active=False), wm)
    preference_state.apply_local({"mixar_agent_model_byok_active": False}, wm)
    calls.resumable[-1](summary)  # the off-thread key store answer


# ---------------------------------------------------------------------------
# What this computer holds
# ---------------------------------------------------------------------------

def test_a_paused_key_is_a_record_here_while_the_server_says_inactive(env):
    wm, calls = env
    _paused(wm, calls)
    snap = credential_state.snapshot()
    assert snap["byok_key_resumable"] and not snap["byok_is_active"]
    assert credential_state.resumable()
    assert credential_state.resume_target() == ("anthropic", "claude-opus-5-5")
    assert wm.byok_key_resumable is True and _picker()["resumable"] is True
    # Mixie answers while the key is paused; the key tab offers it back.
    assert _chip()["source"] == picker.TAB_MIXIE


def test_a_record_that_cannot_be_resent_is_not_resumable(env):
    wm, calls = env
    _paused(wm, calls, summary=None)
    assert not credential_state.resumable()
    assert _picker()["resumable"] is False
    assert credential_state.resume_target() == ("", "")


def test_an_active_key_is_never_resumable_but_may_be_pausable(env):
    wm, calls = env
    _key_in_use(wm, calls)
    assert not credential_state.resumable() and _picker()["resumable"] is False
    assert credential_state.pausable()
    calls.resumable[-1](None)  # a Local key, a revoked sign-in, no model
    assert not credential_state.pausable()


def test_the_last_answer_is_kept_until_the_store_answers_again(env):
    """An apply that says "inactive" carries the previous resumable answer, so
    the island does not flicker to "no key" between the apply and the
    off-thread check that follows it."""
    wm, calls = env
    _paused(wm, calls)
    credential_state.apply_from_payload(_payload(active=False), wm)
    assert credential_state.resumable()
    calls.resumable[-1](None)  # the store now says nothing is here
    assert not credential_state.resumable()


# ---------------------------------------------------------------------------
# Mixie: pause
# ---------------------------------------------------------------------------

def test_mixie_deletes_the_rows_and_keeps_the_record(env):
    wm, calls = env
    _key_in_use(wm, calls)
    assert ops.pause(wm) is True
    assert [forget for _, forget in calls.delete] == [False]
    assert credential_state.pending() == "pause"
    # Nothing is flipped ahead of the server: a turn sent now still carries the key.
    assert wm.byok_is_active is True and wm.mixar_agent_model_byok_active is True
    assert _chip()["state"] == picker.STATE_BUSY
    # A fetch issued earlier must not land while the DELETE is in flight.
    credential_state._apply_fetch_result(credential_state.current_epoch(), True, _payload(), None)

    calls.delete[0][0](True, 1, None)
    assert credential_state.pending() == ""
    assert wm.byok_is_active is False and wm.mixar_agent_model_byok_active is False
    assert _chip()["state"] == picker.STATE_OK and _chip()["source"] == picker.TAB_MIXIE
    assert calls.toasts == []
    assert len(calls.pref_fetch) == 1  # the server's word on byok_active follows
    calls.resumable[-1](RESUMABLE)
    assert credential_state.resumable()


def test_a_failed_pause_leaves_the_key_in_use_and_says_why(env):
    wm, calls = env
    _key_in_use(wm, calls)
    ops.pause(wm)
    calls.delete[0][0](False, 0, "Provider unreachable")
    assert credential_state.pending() == ""
    assert wm.byok_is_active is True and wm.mixar_agent_model_byok_active is True
    assert calls.toasts == [("Couldn't switch to Mixie", "Provider unreachable")]
    assert len(calls.fetch) == 1 and len(calls.pref_fetch) == 1  # resync with the server


# ---------------------------------------------------------------------------
# Custom AI: resume, or the settings
# ---------------------------------------------------------------------------

def test_custom_ai_resends_the_record_without_the_dialog(env, monkeypatch):
    wm, calls = env
    from mixar.modules.byok.core import model_suggestions
    monkeypatch.setattr(model_suggestions, "_short_providers", {"anthropic": "Claude API"})
    _paused(wm, calls)
    opened = []
    monkeypatch.setattr(ops.bpy.ops.mixar_byok, "open_dialog",
                        lambda *a, **k: opened.append(a) or {'RUNNING_MODAL'}, raising=False)
    assert ops.MIXAR_BYOK_OT_use_key().execute(SimpleNamespace(window_manager=wm)) == {'FINISHED'}
    assert opened == []
    assert [model for model, _ in calls.resave] == [None]  # the record's own model
    assert credential_state.pending() == "resume"
    assert wm.byok_is_active is False  # the server has not said yes yet
    calls.resave[0][1](True, _payload(), None)
    assert credential_state.pending() == ""
    assert wm.byok_is_active is True and wm.mixar_agent_model_byok_active is True
    assert (_chip()["source"], _chip()["label"]) == (picker.TAB_KEY, "Claude API")
    assert not credential_state.resumable()  # active: nothing is paused
    assert len(calls.pref_fetch) == 1


def test_a_failed_resume_toasts_and_rereads(env):
    wm, calls = env
    _paused(wm, calls)
    ops.MIXAR_BYOK_OT_use_key().execute(SimpleNamespace(window_manager=wm))
    calls.resave[0][1](False, None, "Codex sign-in expired")
    assert credential_state.pending() == ""
    assert wm.byok_is_active is False
    assert calls.toasts == [("Couldn't switch to your API key", "Codex sign-in expired")]
    assert len(calls.fetch) == 1 and len(calls.pref_fetch) == 1


@pytest.mark.parametrize("setup", ["none", "in_use", "not_resumable"])
def test_custom_ai_opens_the_settings_otherwise(env, monkeypatch, setup):
    wm, calls = env
    if setup == "in_use":
        _key_in_use(wm)
    elif setup == "not_resumable":
        _paused(wm, calls, summary=None)
    opened = []
    monkeypatch.setattr(ops.bpy.ops.mixar_byok, "open_dialog",
                        lambda *a, **k: opened.append(a) or {'RUNNING_MODAL'}, raising=False)
    assert ops.MIXAR_BYOK_OT_use_key().execute(SimpleNamespace(window_manager=wm)) == {'FINISHED'}
    assert opened == [('INVOKE_DEFAULT',)]
    assert calls.resave == []


def test_forget_saved_key_drops_the_record_only(env):
    wm, calls = env
    _paused(wm, calls)
    ctx = SimpleNamespace(window_manager=wm)
    assert ops.MIXAR_BYOK_OT_forget_stored_key.poll(ctx)
    assert ops.MIXAR_BYOK_OT_forget_stored_key().execute(ctx) == {'FINISHED'}
    assert calls.delete == []  # the server holds nothing for a paused key
    calls.forget[0](True)
    assert not credential_state.resumable() and _picker()["resumable"] is False
    assert not ops.MIXAR_BYOK_OT_forget_stored_key.poll(ctx)


# ---------------------------------------------------------------------------
# One mutation at a time; logout mid-flight
# ---------------------------------------------------------------------------

def test_the_toggle_waits_for_any_other_account_mutation(env, monkeypatch):
    wm, calls = env
    _key_in_use(wm, calls)
    ctx = SimpleNamespace(window_manager=wm)
    assert ops.pause(wm) is True
    # While the pause is in flight nothing else may mutate the key or pick.
    assert ops.pause(wm) is False
    assert not ops.MIXAR_BYOK_OT_use_key.poll(ctx)
    assert not credential_state.begin_switch("claude-sonnet-5-5", wm)
    from mixar.modules.byok.ui.operators import byok_dialog_support, byok_ops
    assert byok_dialog_support.account_busy()  # the island card's picks wait
    wm.byok_dialog_state = 'IDLE'
    assert not byok_ops.MIXAR_BYOK_OT_save.poll(ctx)
    assert not byok_ops.MIXAR_BYOK_OT_confirm_remove.poll(ctx)
    calls.delete[0][0](True, 1, None)
    calls.resumable[-1](RESUMABLE)
    assert ops.MIXAR_BYOK_OT_use_key.poll(ctx)
    # ... and a hosted pick in flight holds the toggle.
    monkeypatch.setattr(preference_state, "mutation_pending", lambda: True)
    assert not ops.MIXAR_BYOK_OT_use_key.poll(ctx)
    # ... as does a dialog save / removal that has not answered.
    monkeypatch.setattr(preference_state, "mutation_pending", lambda: False)
    monkeypatch.setattr(ops.byok_client, "mutation_in_flight", lambda: True)
    assert ops.pause(wm) is False and calls.delete[1:] == []


def test_use_my_key_does_not_resume_while_a_turn_is_in_flight(env, monkeypatch):
    """The backend bound the running turn's key when it started; a resume now
    would apply only to the next message while the island said otherwise.
    With nothing to resume it may still open the settings. (The island
    card's own turn gate is `mixar.agent_pick`'s, in test_agent_picker.)"""
    wm, calls = env
    _key_in_use(wm, calls)
    ctx = SimpleNamespace(window_manager=wm, scene=SimpleNamespace())
    # The operator binds the gate by name at import.
    monkeypatch.setattr(ops, "turn_in_flight", lambda context: True)
    # A key in use: "Use my key" still polls (it opens the settings).
    assert ops.MIXAR_BYOK_OT_use_key.poll(ctx)
    # A paused key: resuming waits.
    _paused(wm, calls)
    monkeypatch.setattr(ops.MIXAR_BYOK_OT_use_key, "poll_message_set",
                        staticmethod(lambda message: None), raising=False)
    assert not ops.MIXAR_BYOK_OT_use_key.poll(ctx)
    key = ops.MIXAR_BYOK_OT_use_key()
    key.report = lambda *a, **k: None  # the bpy mock's Operator has no report()
    assert key.execute(ctx) == {'CANCELLED'}
    assert calls.resave == [] and credential_state.pending() == ""
    # Idle again: the resume is live.
    monkeypatch.setattr(ops, "turn_in_flight", lambda context: False)
    assert ops.MIXAR_BYOK_OT_use_key.poll(ctx)


def test_the_turn_gate_reads_the_chat_session_the_open_run_and_every_other_tab(monkeypatch):
    from mixar.modules.byok.ui.operators import byok_dialog_support
    from mixar.modules.space_mixie_chat.constants import SessionState
    from mixar.modules.space_mixie_chat.core import session as session_module
    states = {"state": SessionState.IDLE, "run": False, "any": False}
    fake = SimpleNamespace(get_state=lambda scene: states["state"],
                           run_open=lambda scene: states["run"],
                           has_active_session=lambda session_id="": states["any"])
    monkeypatch.setattr(session_module, "get_session_manager", lambda: fake)
    ctx = SimpleNamespace(scene=SimpleNamespace())
    assert not byok_dialog_support.turn_in_flight(ctx)
    for state in (SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT):
        states["state"] = state
        assert byok_dialog_support.turn_in_flight(ctx)
    states["state"] = SessionState.IDLE
    states["run"] = True  # workers still building after an "in progress" answer
    assert byok_dialog_support.turn_in_flight(ctx)
    states["run"] = False
    assert not byok_dialog_support.turn_in_flight(ctx)
    states["any"] = True  # another tab streams on the same account key
    assert byok_dialog_support.turn_in_flight(ctx)
    assert byok_dialog_support.turn_in_flight(SimpleNamespace(scene=None))
    states["any"] = False
    assert not byok_dialog_support.turn_in_flight(SimpleNamespace(scene=None))


def test_a_toggle_that_lands_after_logout_leaves_nothing_behind(env):
    wm, calls = env
    _key_in_use(wm, calls)
    ops.pause(wm)
    credential_state.clear(wm)
    preference_state.clear(wm)
    calls.delete[0][0](True, 1, None)
    assert credential_state.snapshot()["byok_is_active"] is False
    assert credential_state.pending() == ""
    assert calls.toasts == [] and calls.pref_fetch == []


def test_a_pause_never_forgets_the_record_and_never_opens_the_settings():
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
              / "byok_toggle_ops.py").read_text(encoding="utf-8")
    assert "delete_credentials(on_done=_done, forget_local=False)" in source
    assert source.count("delete_credentials(on_done") == 1
    assert "keep_stored_key" not in source and "byok/state" not in source
    pause = source[source.index("def pause("):source.index("def _on_pause_done(")]
    assert "open_dialog" not in pause and "_open_settings" not in pause
    # The island card's rows are its only entry; no Mixie operator is left.
    assert "use_mixie" not in source


def test_the_server_is_never_asked_to_pause_or_reuse_a_key():
    """The server keeps no key: there is no pause route and no key reuse."""
    service = (SCRIPTS / "mixar" / "modules" / "common" / "api" / "services"
               / "agent_service.py").read_text(encoding="utf-8")
    assert "keep_stored_key" not in service and "byok/state" not in service


# ---------------------------------------------------------------------------
# Races and escapes
# ---------------------------------------------------------------------------

def test_an_older_preference_read_cannot_flip_the_thumb_mid_toggle(env):
    """Pause lands and refreshes the preference (GET A); Custom AI right away;
    GET A (still "paused") lands during the resume's echo and must be dropped."""
    wm, calls = env
    _key_in_use(wm, calls)
    ctx = SimpleNamespace(window_manager=wm)
    ops.pause(wm)
    calls.delete[0][0](True, 1, None)
    calls.resumable[-1](RESUMABLE)
    assert len(calls.pref_fetch) == 1  # GET A in flight
    ops.MIXAR_BYOK_OT_use_key().execute(ctx)
    calls.resave[0][1](True, _payload(), None)
    assert wm.mixar_agent_model_byok_active is True
    calls.pref_fetch[0](True, {"byok_active": False, "items": []}, None)  # GET A lands late
    assert wm.mixar_agent_model_byok_active is True and wm.byok_is_active is True


def test_an_older_credential_read_cannot_undo_a_finished_toggle(env):
    wm, calls = env
    _key_in_use(wm, calls)
    credential_state.refresh()  # e.g. the launch GET, still in flight
    ops.pause(wm)
    calls.delete[0][0](True, 1, None)
    calls.fetch[0](True, _payload(), None)  # the older GET lands after the echo
    assert wm.byok_is_active is False


def test_an_older_credential_read_cannot_undo_a_save_echo(env):
    wm, calls = env
    credential_state.refresh()
    credential_state.apply_from_payload(_payload(), wm)  # the save's echo
    calls.fetch[0](True, _payload(active=False), None)
    assert wm.byok_is_active is True


def test_a_superseded_read_still_answers_whoever_waited_on_it(env):
    """The cold-start 409 resend waits on the next fetch; an echo that
    supersedes that fetch IS newer server state, so the wait is over."""
    wm, calls = env
    seen = []
    credential_state.on_next_fetch(seen.append)
    credential_state.refresh()
    credential_state.apply_from_payload(_payload(), wm)
    calls.fetch[0](True, _payload(active=False), None)
    assert seen == [True]


def test_a_read_overtaken_by_a_newer_read_before_anything_loaded_keeps_its_waiter(env):
    """The cold-start 409: the login fetch is still out, a keyless turn is
    refused, byok_notice arms the hook and refreshes. The login fetch lands
    first and is superseded — it must NOT answer the hook with "not loaded"
    (that shows the key-missing card and drops the auto-resend); the newer
    fetch answers it."""
    wm, calls = env
    credential_state.refresh()  # the login fetch
    seen = []
    credential_state.on_next_fetch(seen.append)
    credential_state.refresh()  # the 409 handler's refresh
    assert len(calls.fetch) == 2
    calls.fetch[0](True, _payload(), None)  # the older one lands first
    assert seen == [] and wm.byok_is_active is False
    calls.fetch[1](True, _payload(), None)
    assert seen == [True] and wm.byok_is_active is True


def test_a_read_held_by_a_mutation_is_reissued_for_whoever_waits(env):
    wm, calls = env
    _key_in_use(wm, calls)
    ops.pause(wm)
    seen = []
    credential_state.on_next_fetch(seen.append)
    credential_state.refresh()
    assert calls.fetch == []  # held: the echo is the fresher answer
    calls.delete[0][0](True, 1, None)
    assert len(calls.fetch) == 1  # re-issued by end_pending
    calls.fetch[0](True, _payload(active=False), None)
    assert seen == [True]


def test_a_failed_credential_read_is_retried_unless_superseded(env, monkeypatch):
    wm, calls = env
    import bpy
    registered = []
    monkeypatch.setattr(bpy.app.timers, "register",
                        lambda fn, first_interval=0: registered.append((fn, first_interval)),
                        raising=False)
    credential_state.refresh()
    calls.fetch[0](False, None, "offline")
    assert len(registered) == 1 and registered[0][1] == credential_state._RETRY_DELAY_S
    registered[0][0]()  # nothing newer happened: the retry re-fetches
    assert len(calls.fetch) == 2
    calls.fetch[1](False, None, "offline")
    credential_state.apply_from_payload(_payload(), wm)  # a newer write lands first
    registered[1][0]()
    assert len(calls.fetch) == 2  # superseded: no stale re-fetch


def test_after_a_removal_mixie_does_not_pause_a_key_that_is_gone(env, monkeypatch):
    """Even before the preference refresh lands, a successful removal leaves
    the island on Mixie, so a Mixie pick (`mixar.agent_pick`, which pauses
    only when a key answers by either mirror) sends no pause for a deleted key."""
    from mixar.modules.byok.ui.operators import byok_ops
    wm, calls = env
    _key_in_use(wm, calls)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops, "_deregister_local_if_switched_away", lambda _: None)
    # byok_ops binds bpy at import; the dialog callbacks read the WindowManager through it.
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    byok_ops._on_delete_done(True, 1, None, epoch=credential_state.current_epoch())
    assert wm.mixar_agent_model_byok_active is False and wm.byok_is_active is False
    assert _picker()["source"] == picker.TAB_MIXIE and not _picker()["loading"]
    assert calls.delete == []


def test_a_removal_that_lands_after_logout_changes_nothing(env, monkeypatch):
    from mixar.modules.byok.ui.operators import byok_ops
    wm, _ = env
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    epoch = credential_state.current_epoch()
    credential_state.clear(wm)  # logout, then the next account's key loads
    _key_in_use(wm)
    byok_ops._on_delete_done(True, 1, None, epoch=epoch)
    assert wm.byok_is_active is True and wm.mixar_agent_model_byok_active is True


def test_a_request_finishing_after_the_dialog_closed_still_reports_failure(env, monkeypatch):
    from mixar.modules.byok.ui.operators import byok_ops
    wm, _ = env
    toasts = []
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    monkeypatch.setattr(byok_ops, "_dialog_open", False)
    import mixar.modules.common.notifications as notifications
    monkeypatch.setattr(notifications, "get_notification_store",
                        lambda: SimpleNamespace(push=lambda *a, **k: toasts.append(a[1])))
    byok_ops._on_delete_done(False, 0, "server said no", epoch=credential_state.current_epoch())
    assert toasts == ["Couldn't remove your API key"]
    monkeypatch.setattr(byok_ops, "_dialog_open", True)
    byok_ops._on_delete_done(False, 0, "server said no", epoch=credential_state.current_epoch())
    assert toasts == ["Couldn't remove your API key"]  # an open dialog shows it inline


def test_the_dialog_names_the_paused_key_and_prefills_it(env):
    from mixar.modules.byok.ui.operators import byok_dialog_support, byok_dialog_ui
    wm, calls = env
    _paused(wm, calls)
    assert byok_dialog_support.saved_provider_model(wm) == ("anthropic", "claude-opus-5-5")
    assert byok_dialog_ui._key_paused(wm)
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
              / "byok_provider_settings_ui.py").read_text(encoding="utf-8")
    assert 'OP_USE_KEY = "mixar_byok.use_key"' in source
    assert 'OP_FORGET_KEY = "mixar_byok.forget_stored_key"' in source
