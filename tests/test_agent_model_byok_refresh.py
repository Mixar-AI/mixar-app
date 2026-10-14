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
def test_success_refetches_picker_and_waits_for_server_state(callbacks, saving):
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
    # No guessed local flip: only the preference response owns byok_active.
    assert wm.mixar_agent_model_byok_active is not saving
    pending[0](True, {"byok_active": saving, "items": []}, None)
    assert wm.mixar_agent_model_byok_active is saving


@pytest.mark.parametrize("saving", [True, False])
def test_failed_mutation_preserves_picker_without_fetching(callbacks, saving):
    wm, pending = callbacks
    preference_state.apply_local({"mixar_agent_model_byok_active": True})
    callback = byok_ops._on_save_done if saving else byok_ops._on_delete_done

    callback(False, None if saving else 0, "Request failed")

    assert wm.byok_dialog_state == "ERROR"
    assert pending == []
    assert wm.mixar_agent_model_byok_active is True


def test_save_after_logout_does_not_refresh_picker(callbacks):
    wm, pending = callbacks
    epoch = credential_state.current_epoch()
    credential_state.clear(wm)

    byok_ops._on_save_done(True, {"byok_active": True}, None, epoch=epoch)

    assert pending == []
    assert wm.mixar_agent_model_byok_active is False
