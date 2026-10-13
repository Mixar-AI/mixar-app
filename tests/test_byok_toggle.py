# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island's Mixie | Custom AI toggle switches who answers, in one click.

Contract pinned here (byok/ui/operators/byok_toggle_ops.py,
byok/core/credential_state.py):
- Mixie while a key is in use PAUSES the stored key (`PUT /agent/byok/state`
  `{"enabled": false}`) — no dialog, no deletion.
- Custom AI RESUMES a paused key that still validates — no dialog, no key —
  and otherwise opens AI Provider settings.
- The flip is optimistic on both mirrors (credential state and the hosted
  pick's `byok_active`, which the thumb reads); fetches issued before it are
  dropped while it is in flight; success keeps the echo and re-reads the
  preference; failure restores both, re-reads the server and raises a toast;
  a logout mid-flight leaves nothing behind.
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

from mixar.modules.byok.core import credential_state, preference_state
from mixar.modules.byok.ui.operators import byok_toggle_ops as ops


def _payload(active=True, enabled=True, valid=True, stored=True, model="claude-opus-5-5"):
    items = [{"provider": "anthropic", "model": model, "key_preview": "sk-ant-…1234",
              "enabled": enabled, "is_valid": valid}] if stored else []
    return {"byok_active": active, "items": items}


@pytest.fixture
def env(monkeypatch):
    """Clean mirrors, a recording fake HTTP layer, no redraws, no toasts."""
    import bpy

    wm = SimpleNamespace()
    monkeypatch.setattr(bpy.context, "window_manager", wm, raising=False)
    calls = SimpleNamespace(state=[], fetch=[], pref_fetch=[], toasts=[], dialogs=[])
    monkeypatch.setattr(ops.byok_client, "set_key_enabled",
                        lambda enabled, on_done: calls.state.append((enabled, on_done)))
    monkeypatch.setattr(credential_state.byok_client, "fetch_state",
                        lambda on_done: calls.fetch.append(on_done))
    monkeypatch.setattr(preference_state.preference_client, "fetch_preference",
                        lambda on_done: calls.pref_fetch.append(on_done))
    monkeypatch.setattr(ops, "_toast", lambda enabled, err: calls.toasts.append((enabled, err)))
    monkeypatch.setattr(ops, "_redraw", lambda: None)
    monkeypatch.setattr(preference_state, "_redraw", lambda: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    credential_state.clear(wm)
    preference_state.clear(wm)
    yield wm, calls
    credential_state.clear(wm)
    preference_state.clear(wm)


def _key_in_use(wm):
    credential_state.apply_from_payload(_payload(), wm)
    preference_state.apply_local({"mixar_agent_model_byok_active": True}, wm)


def _paused(wm, valid=True):
    credential_state.apply_from_payload(_payload(active=False, enabled=False, valid=valid), wm)
    preference_state.apply_local({"mixar_agent_model_byok_active": False}, wm)


# ---------------------------------------------------------------------------
# What the server says
# ---------------------------------------------------------------------------

def test_a_paused_key_is_stored_not_active_and_resumable(env):
    wm, _ = env
    _paused(wm)
    snap = credential_state.snapshot()
    assert snap["byok_key_stored"] and snap["byok_key_paused"] and not snap["byok_is_active"]
    assert credential_state.resumable()
    assert wm.byok_key_paused is True and wm.mixar_agent_key_resumable is True
    # The key chip only exists while a key answers.
    assert wm.mixar_agent_key_label == "" and wm.mixar_agent_key_model == ""


def test_a_paused_key_that_stopped_validating_is_not_resumable(env):
    wm, _ = env
    _paused(wm, valid=False)
    assert not credential_state.resumable()
    assert wm.mixar_agent_key_resumable is False


def test_an_older_backend_s_stored_key_counts_as_enabled(env):
    wm, _ = env
    credential_state.apply_from_payload(
        {"byok_active": True, "items": [{"provider": "anthropic", "model": "m"}]}, wm)
    snap = credential_state.snapshot()
    assert snap["byok_key_stored"] and not snap["byok_key_paused"] and snap["byok_is_active"]


# ---------------------------------------------------------------------------
# Mixie: pause
# ---------------------------------------------------------------------------

def test_mixie_pauses_at_once_and_keeps_the_echo(env):
    wm, calls = env
    _key_in_use(wm)
    assert ops.MIXAR_BYOK_OT_use_mixie().execute(SimpleNamespace(window_manager=wm)) == {'FINISHED'}
    # Optimistic: the thumb and the chip flip before the server answers.
    assert wm.mixar_agent_model_byok_active is False
    assert wm.byok_is_active is False and wm.byok_key_paused is True
    assert credential_state.pending() == "pause"
    assert [enabled for enabled, _ in calls.state] == [False]
    # A fetch issued earlier must not flip it back while the PUT is in flight.
    credential_state._apply_fetch_result(credential_state.current_epoch(), True, _payload(), None)
    assert wm.byok_is_active is False

    calls.state[0][1](True, _payload(active=False, enabled=False), None)
    assert credential_state.pending() == ""
    assert wm.byok_is_active is False and wm.byok_key_paused is True
    assert calls.toasts == []
    assert len(calls.pref_fetch) == 1  # the server's word on byok_active follows


def test_a_failed_pause_restores_both_mirrors_and_says_why(env):
    wm, calls = env
    _key_in_use(wm)
    ops.MIXAR_BYOK_OT_use_mixie().execute(SimpleNamespace(window_manager=wm))
    calls.state[0][1](False, None, "Provider unreachable")
    assert credential_state.pending() == ""
    assert wm.byok_is_active is True and wm.byok_key_paused is False
    assert wm.mixar_agent_model_byok_active is True
    assert calls.toasts == [(False, "Provider unreachable")]
    assert len(calls.fetch) == 1 and len(calls.pref_fetch) == 1  # resync with the server


def test_mixie_with_mixie_already_answering_does_nothing(env):
    wm, calls = env
    _paused(wm)
    assert ops.MIXAR_BYOK_OT_use_mixie().execute(SimpleNamespace(window_manager=wm)) == {'CANCELLED'}
    assert calls.state == []


def test_mixie_pauses_even_before_the_credential_mirror_has_loaded(env):
    """The thumb reads the hosted pick's flag; if it says a key answers, the
    click must reach the server (which refuses when nothing is stored)."""
    wm, calls = env
    preference_state.apply_local({"mixar_agent_model_byok_active": True}, wm)
    assert ops.MIXAR_BYOK_OT_use_mixie().execute(SimpleNamespace(window_manager=wm)) == {'FINISHED'}
    assert [enabled for enabled, _ in calls.state] == [False]


# ---------------------------------------------------------------------------
# Custom AI: resume, or the settings
# ---------------------------------------------------------------------------

def test_custom_ai_resumes_a_paused_key_without_the_dialog(env, monkeypatch):
    wm, calls = env
    _paused(wm)
    opened = []
    monkeypatch.setattr(ops.bpy.ops.mixar_byok, "open_dialog",
                        lambda *a, **k: opened.append(a) or {'RUNNING_MODAL'}, raising=False)
    assert ops.MIXAR_BYOK_OT_use_key().execute(SimpleNamespace(window_manager=wm)) == {'FINISHED'}
    assert opened == []
    assert wm.byok_is_active is True and wm.mixar_agent_model_byok_active is True
    calls.state[0][1](True, _payload(), None)
    assert wm.byok_is_active is True and wm.mixar_agent_key_label == "Claude API"


@pytest.mark.parametrize("setup", ["none", "in_use", "invalid"])
def test_custom_ai_opens_the_settings_otherwise(env, monkeypatch, setup):
    wm, calls = env
    if setup == "in_use":
        _key_in_use(wm)
    elif setup == "invalid":
        _paused(wm, valid=False)
    opened = []
    monkeypatch.setattr(ops.bpy.ops.mixar_byok, "open_dialog",
                        lambda *a, **k: opened.append(a) or {'RUNNING_MODAL'}, raising=False)
    assert ops.MIXAR_BYOK_OT_use_key().execute(SimpleNamespace(window_manager=wm)) == {'FINISHED'}
    assert opened == [('INVOKE_DEFAULT',)]
    assert calls.state == []


# ---------------------------------------------------------------------------
# One mutation at a time; logout mid-flight
# ---------------------------------------------------------------------------

def test_the_toggle_waits_for_any_other_account_mutation(env, monkeypatch):
    wm, calls = env
    _key_in_use(wm)
    ctx = SimpleNamespace(window_manager=wm)
    assert ops.MIXAR_BYOK_OT_use_mixie.poll(ctx)
    ops.MIXAR_BYOK_OT_use_mixie().execute(ctx)
    # While the pause is in flight nothing else may mutate the key or pick.
    assert not ops.MIXAR_BYOK_OT_use_mixie.poll(ctx)
    assert not ops.MIXAR_BYOK_OT_use_key.poll(ctx)
    assert not credential_state.begin_switch("claude-sonnet-5-5", wm)
    from mixar.modules.byok.ui.operators import agent_model_ops
    monkeypatch.setattr(agent_model_ops.MIXAR_OT_agent_model_set, "poll_message_set",
                        staticmethod(lambda message: None), raising=False)
    assert not agent_model_ops.MIXAR_OT_agent_model_set.poll(ctx)
    calls.state[0][1](True, _payload(active=False, enabled=False), None)
    assert ops.MIXAR_BYOK_OT_use_key.poll(ctx)
    # ... and a hosted pick in flight holds the toggle.
    monkeypatch.setattr(preference_state, "mutation_pending", lambda: True)
    assert not ops.MIXAR_BYOK_OT_use_key.poll(ctx)


def test_a_toggle_that_lands_after_logout_leaves_nothing_behind(env):
    wm, calls = env
    _key_in_use(wm)
    ops.MIXAR_BYOK_OT_use_mixie().execute(SimpleNamespace(window_manager=wm))
    credential_state.clear(wm)
    preference_state.clear(wm)
    calls.state[0][1](True, _payload(active=False, enabled=False), None)
    assert credential_state.snapshot()["byok_key_stored"] is False
    assert calls.toasts == [] and calls.pref_fetch == []


def test_the_toggle_never_deletes_and_never_opens_settings_from_mixie():
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
              / "byok_toggle_ops.py").read_text(encoding="utf-8")
    assert "delete_credentials" not in source
    use_mixie = source[source.index("class MIXAR_BYOK_OT_use_mixie"):
                       source.index("class MIXAR_BYOK_OT_use_key")]
    assert "open_dialog" not in use_mixie


# ---------------------------------------------------------------------------
# Races and escapes (each one a bug an independent review found)
# ---------------------------------------------------------------------------

def test_an_older_preference_read_cannot_flip_the_thumb_mid_toggle(env):
    """Pause lands and refreshes the preference (GET A); Custom AI right away;
    GET A (still "paused") lands during the resume and must be dropped."""
    wm, calls = env
    _key_in_use(wm)
    ctx = SimpleNamespace(window_manager=wm)
    ops.MIXAR_BYOK_OT_use_mixie().execute(ctx)
    calls.state[0][1](True, _payload(active=False, enabled=False), None)
    assert len(calls.pref_fetch) == 1  # GET A in flight
    ops.MIXAR_BYOK_OT_use_key().execute(ctx)
    assert wm.mixar_agent_model_byok_active is True
    calls.pref_fetch[0](True, {"byok_active": False, "items": []}, None)  # GET A lands late
    assert wm.mixar_agent_model_byok_active is True
    calls.state[1][1](True, _payload(), None)
    assert wm.mixar_agent_model_byok_active is True and wm.byok_is_active is True


def test_an_older_credential_read_cannot_undo_a_finished_toggle(env):
    wm, calls = env
    _key_in_use(wm)
    credential_state.refresh()  # e.g. the launch GET, still in flight
    ops.MIXAR_BYOK_OT_use_mixie().execute(SimpleNamespace(window_manager=wm))
    calls.state[0][1](True, _payload(active=False, enabled=False), None)
    calls.fetch[0](True, _payload(), None)  # the older GET lands after the echo
    assert wm.byok_is_active is False and wm.byok_key_paused is True


def test_an_older_credential_read_cannot_undo_a_save_echo(env):
    wm, calls = env
    credential_state.refresh()
    credential_state.apply_from_payload(_payload(), wm)  # the save's echo
    calls.fetch[0](True, _payload(stored=False, active=False), None)
    assert wm.byok_is_active is True


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
    the island on Mixie, so nothing sends a pause for a deleted key."""
    from mixar.modules.byok.ui.operators import byok_ops
    wm, calls = env
    _key_in_use(wm)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops, "_deregister_local_if_switched_away", lambda _: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    byok_ops._on_delete_done(True, 1, None, epoch=credential_state.current_epoch())
    assert wm.mixar_agent_model_byok_active is False and wm.byok_key_stored is False
    assert ops.MIXAR_BYOK_OT_use_mixie().execute(SimpleNamespace(window_manager=wm)) == {'CANCELLED'}
    assert calls.state == []


def test_a_removal_keeps_the_epoch_so_a_following_save_keeps_its_echo(env, monkeypatch):
    from mixar.modules.byok.ui.operators import byok_ops
    wm, _ = env
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops, "_deregister_local_if_switched_away", lambda _: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    _key_in_use(wm)
    epoch = credential_state.current_epoch()
    byok_ops._on_delete_done(True, 1, None, epoch=epoch)
    assert credential_state.current_epoch() == epoch
    wm.byok_dialog_state = 'SAVING'
    byok_ops._on_save_done(True, _payload(), None, epoch=epoch)
    assert wm.byok_dialog_state == 'SAVED' and wm.byok_is_active is True


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


def test_reopening_while_a_request_is_in_flight_keeps_its_progress(env, monkeypatch):
    from mixar.modules.byok.core import byok_client
    pending = []
    monkeypatch.setattr(byok_client, "get_agent_service", lambda: None)
    monkeypatch.setattr(byok_client.threading, "Thread",
                        lambda target, daemon, name: SimpleNamespace(start=lambda: None))
    byok_client.delete_credentials(on_done=lambda *a: pending.append(a))
    assert byok_client.mutation_in_flight()
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
              / "byok_ops.py").read_text(encoding="utf-8")
    assert "if not byok_client.mutation_in_flight():\n            wm.byok_dialog_state = 'IDLE'" in source
    # Released exactly when the callback runs.
    byok_client._mutations_in_flight = 0


def test_the_hosted_menu_draws_the_toggle_rows_as_the_toggle_operators():
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "menus"
              / "agent_model_menu.py").read_text(encoding="utf-8")
    assert 'row.kind == "USE_MIXIE":\n        line.operator("mixar_byok.use_mixie"' in source
    assert 'line.operator("mixar_byok.use_key"' in source
    assert "byok_resumable=credential_state.resumable()" in source
