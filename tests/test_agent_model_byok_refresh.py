# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Credential mutations must refresh the server-owned hosted picker state."""

from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import credential_state, preference_state
from mixar.modules.byok.ui.operators import byok_ops


@pytest.fixture
def callbacks(monkeypatch):
    import bpy

    wm = SimpleNamespace()
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm)
    monkeypatch.setattr(bpy.context, "window_manager", wm)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops, "_deregister_local_if_switched_away", lambda _: None)
    monkeypatch.setattr(preference_state, "_redraw", lambda: None)
    credential_state.clear(wm)
    preference_state.clear(wm)
    pending = []
    monkeypatch.setattr(
        preference_state.preference_client, "fetch_preference",
        lambda on_done: pending.append(on_done),
    )
    yield wm, pending
    credential_state.clear(wm)
    preference_state.clear(wm)


@pytest.mark.parametrize("saving", [True, False])
def test_success_moves_the_island_on_server_facts_and_refetches(callbacks, saving):
    """The island moves on what the server just answered — the save echo's
    byok_active, or a successful DELETE of every row (byok_active is false by
    construction) — never on a guess, and the preference refetch confirms.
    Waiting for that refetch alone left the thumb on Custom AI with no key
    when it was slow or failed, and Mixie then paused a key that was gone."""
    wm, pending = callbacks
    preference_state.apply_local({"mixar_agent_model_byok_active": not saving})

    if saving:
        byok_ops._on_save_done(True, {"byok_active": True, "items": [{
            "provider": "openai", "model": "test-model",
        }]}, None, epoch=credential_state.current_epoch())
    else:
        byok_ops._on_delete_done(True, 1, None)

    assert wm.byok_dialog_state == ("SAVED" if saving else "REMOVED")
    assert len(pending) == 1
    assert wm.mixar_agent_model_byok_active is saving
    pending[0](True, {"byok_active": saving, "items": []}, None)
    assert wm.mixar_agent_model_byok_active is saving


def test_a_save_echo_saying_inactive_is_not_overridden(callbacks):
    """Server facts only: an echo with byok_active false keeps the thumb off."""
    wm, pending = callbacks
    byok_ops._on_save_done(True, {"byok_active": False, "items": [{
        "provider": "openai", "model": "m"}]}, None, epoch=credential_state.current_epoch())
    assert wm.mixar_agent_model_byok_active is False


def test_a_preference_read_issued_before_the_change_cannot_undo_it(callbacks):
    wm, pending = callbacks
    preference_state.apply_local({"mixar_agent_model_byok_active": True})
    preference_state.refresh()  # in flight, carries the pre-removal answer
    byok_ops._on_delete_done(True, 1, None)
    pending[0](True, {"byok_active": True, "items": []}, None)  # the old read lands
    assert wm.mixar_agent_model_byok_active is False


@pytest.mark.parametrize("saving", [True, False])
def test_failed_mutation_preserves_picker_without_fetching(callbacks, saving):
    wm, pending = callbacks
    preference_state.apply_local({"mixar_agent_model_byok_active": True})
    callback = byok_ops._on_save_done if saving else byok_ops._on_delete_done

    callback(False, None if saving else 0, "Request failed")

    # A failed save shows its error on the form; a failed remove goes back to
    # the confirm step with the error, so Remove retries and Keep backs out.
    assert wm.byok_dialog_state == ("ERROR" if saving else "CONFIRM_REMOVE")
    assert pending == []
    assert wm.mixar_agent_model_byok_active is True


def test_save_after_logout_does_not_refresh_picker(callbacks):
    wm, pending = callbacks
    epoch = credential_state.current_epoch()
    credential_state.clear(wm)

    byok_ops._on_save_done(True, {"byok_active": True}, None, epoch=epoch)

    assert pending == []
    assert wm.mixar_agent_model_byok_active is False


def _submit(kind):
    """A dialog request as the operators send it: epoch-bound, then counted."""
    from mixar.modules.byok.core import byok_client
    if kind == "save":
        return byok_client._track(byok_ops._save_callback())
    epoch = credential_state.current_epoch()
    return byok_client._track(
        lambda ok, n, err: byok_ops._on_delete_done(ok, n, err, epoch=epoch))


def _land(done, kind, success):
    if kind == "save":
        done(success, {"byok_active": True} if success else None, None if success else "rejected")
    else:
        done(success, 1 if success else 0, None if success else "rejected")


def _dialog(wm, state, key):
    wm.byok_dialog_state, wm.byok_form_api_key = state, key
    wm.byok_form_local_custom_key, wm.byok_last_error = "", ""


OUTCOMES = [("save", True), ("save", False), ("delete", True), ("delete", False)]


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_a_late_result_for_the_previous_account_leaves_the_next_accounts_save_alone(
        callbacks, outcome):
    """AUTH-17: account A's save/remove lands after logout while B's own save
    is in flight. It must not flip B's SAVING to IDLE (that stops the redraw
    pump, so B's Done never draws) nor wipe the key B just typed."""
    from mixar.modules.byok.core import byok_client
    wm, pending = callbacks
    kind, success = outcome
    late = _submit(kind)
    credential_state.clear(wm)  # logout: A's epoch is now stale
    byok_client.reset_in_flight()
    _dialog(wm, "SAVING", "sk-typed-by-B")
    own = byok_client._track(lambda *a: None)  # B's save, counted after the reset
    try:
        _land(late, kind, success)
        assert wm.byok_dialog_state == "SAVING" and wm.byok_form_api_key == "sk-typed-by-B"
        assert wm.byok_last_error == "" and pending == []
    finally:
        own.release()


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize("change", ["guest_sign_in", "card_removal"])
def test_a_late_result_after_an_account_change_without_logout_releases_the_dialog(
        callbacks, outcome, change):
    """A guest's sign-in (`invalidate_agent_settings`: epoch bump + in-flight
    reset, no dialog reset) or the chat card's Use credits removal
    (`clear(loaded=True)`) bumps the epoch under a dialog closed with Esc
    mid-request. Its late result is dropped, but the dialog it left busy is
    released — else the redraw pump spins on SAVING for good."""
    from mixar.modules.byok.core import byok_client
    wm, pending = callbacks
    kind, success = outcome
    _dialog(wm, "SAVING" if kind == "save" else "REMOVING", "sk-typed-by-the-guest")
    late = _submit(kind)
    if change == "guest_sign_in":
        credential_state.clear()
        byok_client.reset_in_flight()
    else:
        credential_state.clear(wm, loaded=True)
    _land(late, kind, success)
    assert wm.byok_dialog_state == "IDLE" and wm.byok_form_api_key == ""
    assert not byok_client.mutation_in_flight() and pending == []
