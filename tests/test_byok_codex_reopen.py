# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex: the chip lit, the pick stored and the model Save sends agree when
the dialog reopens on a saved key the account's model list hides, whether the
list was known before the open or lands after it (mixar-backend#1809).

The dialog is opened for real (`open_dialog.invoke`), so the prefill runs as
on screen; the form keeps the model pick the way RNA does (`_CodexForm`)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_byok_dialog_ui import FakeLayout, _draw, _wm  # noqa: E402
from test_byok_model_suggestions import _codex_save, _press_save  # noqa: E402

from mixar.modules.byok.core import model_suggestions  # noqa: E402
from mixar.modules.byok.ui.operators import byok_dialog_ui, byok_ops  # noqa: E402

IN_USE = dict(byok_is_active=True, byok_current_provider="codex",
              byok_current_model="gpt-6-astra")
KEY_NEEDED = dict(IN_USE, byok_device_key_missing=True)


@pytest.fixture(autouse=True)
def _fresh_catalog(monkeypatch):
    monkeypatch.setattr(model_suggestions, "_codex_account_models", None)
    yield
    model_suggestions.clear()


def _open(monkeypatch, wm):
    """open_dialog.invoke with the network stubbed (no catalog or list fetch)."""
    monkeypatch.setattr(byok_ops.byok_client, "mutation_in_flight", lambda: False)
    monkeypatch.setattr(byok_ops.model_suggestions, "is_loaded", lambda: True)
    monkeypatch.setattr(byok_ops.codex_models, "refresh_for_form", lambda wm: None)
    monkeypatch.setattr(byok_ops, "_dialog_host_window", lambda context: None)
    monkeypatch.setattr(byok_ops, "_dialog_open", False)
    wm.mixar_invoke_modal_dialog = lambda op, width, **kwargs: {'RUNNING_MODAL'}
    context = SimpleNamespace(window_manager=wm, window=None)
    assert byok_ops.MIXAR_BYOK_OT_open_dialog().invoke(context, None) == {'RUNNING_MODAL'}


def _lit_chips(log):
    return [log[i - 1].split(":")[2] for i, entry in enumerate(log)
            if entry == "sheet:CHIP:True" and log[i - 1].startswith("pick:model:")]


def _lit(wm):
    """The model chip the sheet lights, drawn (None: no chip is lit)."""
    for name, value in vars(_wm()).items():   # what else the sheet reads
        if not hasattr(wm, name):
            setattr(wm, name, value)
    log = []
    byok_dialog_ui.draw_dialog(FakeLayout(log, card_api=True), wm)
    lit = _lit_chips(log)
    assert len(lit) <= 1, lit
    return lit[0] if lit else None


def _reopen(monkeypatch, tmp_path, fields, account_list, list_first):
    wm, sent = _codex_save(monkeypatch, tmp_path, **fields)
    if list_first:
        model_suggestions.set_codex_account_models(account_list)   # known from an earlier open
    _open(monkeypatch, wm)
    if not list_first:
        model_suggestions.set_codex_account_models(account_list)   # lands after the open
    return wm, sent


@pytest.mark.parametrize("list_first", [True, False], ids=["list-known-first", "list-lands-after"])
def test_in_use_reopen_keeps_a_saved_model_the_list_hides(monkeypatch, tmp_path, list_first):
    """The saved model stays the pick (no chip lit for it) and Save refuses it;
    the first listed model is never lit or sent in its place."""
    wm, sent = _reopen(monkeypatch, tmp_path, IN_USE, {"gpt-6-luna"}, list_first)
    assert wm.byok_form_model_id == "gpt-6-astra"
    assert _lit(wm) is None
    assert _press_save(wm) == {'CANCELLED'}
    assert (wm.byok_dialog_state, wm.byok_last_error) == ("ERROR", "Choose a Codex model.")
    assert sent == []

    wm.byok_form_model = "gpt-6-luna"                    # the user picks a listed chip
    assert _lit(wm) == "gpt-6-luna"
    assert _press_save(wm) == {'FINISHED'}
    assert sent[-1]["model"] == "gpt-6-luna"


@pytest.mark.parametrize("list_first", [True, False], ids=["list-known-first", "list-lands-after"])
@pytest.mark.parametrize("account_list", [{"gpt-6-luna"}, {"gpt-6-astra", "gpt-6-luna"}],
                         ids=["hides-it", "lists-it"])
def test_key_needed_reopen_lights_and_sends_the_saved_model(monkeypatch, tmp_path,
                                                            list_first, account_list):
    wm, sent = _reopen(monkeypatch, tmp_path, KEY_NEEDED, account_list, list_first)
    assert wm.byok_form_model_id == "gpt-6-astra"
    assert _lit(wm) == ("gpt-6-astra" if "gpt-6-astra" in account_list else None)
    assert _press_save(wm) == {'FINISHED'}
    assert sent[-1]["model"] == "gpt-6-astra"


def test_key_needed_save_resends_a_saved_model_the_catalog_dropped(monkeypatch, tmp_path):
    """Key needed, and the saved model left the catalog: its chips are locked,
    so Save re-sends it as it is and Codex's own check decides. Refusing here
    left no way forward; switching to the first chip changed the account."""
    wm, sent = _codex_save(monkeypatch, tmp_path, **dict(KEY_NEEDED, byok_current_model="gpt-5.5"))
    _open(monkeypatch, wm)
    assert _press_save(wm) == {'FINISHED'}
    assert sent[-1]["model"] == "gpt-5.5"


def test_the_sheet_lights_the_saved_model_when_only_the_key_is_asked(monkeypatch):
    models = [("gpt-6-astra", "GPT 6 Astra", ""), ("gpt-6-luna", "GPT 6 Luna", "")]
    monkeypatch.setattr(model_suggestions, "get_provider_items",
                        lambda: [("codex", "Codex (ChatGPT sub)", "")])
    monkeypatch.setattr(model_suggestions, "get_model_items", lambda provider: models)
    log = _draw('IDLE', card_api=True, byok_form_provider='codex', byok_form_model='gpt-6-luna',
                **KEY_NEEDED)
    assert _lit_chips(log) == ["gpt-6-astra"]
