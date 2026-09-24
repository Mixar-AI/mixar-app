# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island Model chip's composed label and the BYOK note in its menu.

C++ draws ONE WindowManager string (`mixar_agent_model_label`, empty ->
"Mixie") and dims it on `mixar_agent_model_byok_active`. Python composes that
string at the mirror boundary — model label, saved thinking level, or the
BYOK indicator — while the dict in `preference_state` keeps the model-only
label the other tests pin. The menu's NOTE row names the key in use.
"""

import ast
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

from mixar.modules.byok.core import (
    catalog_labels,
    credential_state,
    model_menu,
    model_suggestions,
    preference_state,
)

MENU_SOURCE = (
    SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "menus" / "agent_model_menu.py"
)


def _record(model_id, **overrides):
    row = {
        "provider_id": "anthropic",
        "provider_label": "Anthropic",
        "model_id": model_id,
        "model_label": model_id,
        "platform_available": True,
        "byok_available": True,
        "supports_vision": True,
        "min_tier": "",
        "eligible": True,
        "thinking_levels": [],
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(preference_state, "_redraw", lambda: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    preference_state.clear()
    credential_state.clear()
    model_suggestions.clear()
    yield
    preference_state.clear()
    credential_state.clear()
    model_suggestions.clear()


# ---------------------------------------------------------------------------
# chip_label — pure
# ---------------------------------------------------------------------------

def test_no_pick_and_no_key_is_empty_so_cpp_falls_back_to_mixie():
    assert model_menu.chip_label("", "", False) == ""
    # A saved level with no model is not a pick either.
    assert model_menu.chip_label("", "high", False) == ""


def test_a_pick_without_a_level_is_the_model_label_only():
    assert model_menu.chip_label("GPT 5.6 Sol", "", False) == "GPT 5.6 Sol"


def test_a_pick_with_a_level_appends_it_after_a_middle_dot():
    assert model_menu.chip_label("GPT 5.6 Sol", "high", False) == "GPT 5.6 Sol · High"
    assert (
        model_menu.chip_label("Claude Sonnet 4.6", "medium_high", False)
        == "Claude Sonnet 4.6 · Medium High"
    )


def test_the_chip_level_wording_matches_the_thinking_submenu():
    """Same Title-cased words as `format_thinking_label`, minus its prefix."""
    for level in ("low", "medium_high", "MAX"):
        expected = model_menu.format_thinking_label(level).removeprefix("Thinking: ")
        assert model_menu.chip_label("M", level, False) == "M" + model_menu.CHIP_SEPARATOR + expected


def test_a_user_key_replaces_the_hosted_pick_on_the_chip():
    assert model_menu.chip_label("GPT 5.6 Sol", "high", True) == model_menu.BYOK_CHIP_TEXT
    assert model_menu.chip_label("", "", True) == model_menu.BYOK_CHIP_TEXT


def test_the_byok_indicator_is_one_short_constant():
    assert model_menu.BYOK_CHIP_TEXT == "Custom"
    assert model_menu.BYOK_CHIP_TEXT != model_menu.RESET_TEXT


# ---------------------------------------------------------------------------
# byok_note_text — pure
# ---------------------------------------------------------------------------

def test_the_note_names_provider_and_model_when_both_are_known():
    assert (
        model_menu.byok_note_text("OpenRouter", "Claude Sonnet 4.6")
        == "Your key: OpenRouter · Claude Sonnet 4.6"
    )


def test_the_note_names_whichever_half_is_known():
    assert model_menu.byok_note_text("OpenRouter", "") == "Your key: OpenRouter"
    assert model_menu.byok_note_text("", "gpt-6") == "Your key: gpt-6"


def test_the_note_falls_back_to_the_generic_wording_when_nothing_is_known():
    assert model_menu.byok_note_text("", "") == model_menu.BYOK_NOTE_TEXT
    assert model_menu.byok_note_text() == model_menu.BYOK_NOTE_TEXT


# ---------------------------------------------------------------------------
# build_rows — the NOTE row
# ---------------------------------------------------------------------------

def test_the_byok_note_row_carries_the_named_key():
    rows = model_menu.build_rows(
        [_record("a"), _record("b", thinking_levels=["high"])],
        byok_active=True,
        byok_provider_label="OpenRouter",
        byok_model_label="Claude Sonnet 4.6",
    )

    assert rows[0].kind == "NOTE"
    assert rows[0].label == "Your key: OpenRouter · Claude Sonnet 4.6"
    assert rows[0].enabled is False
    # Every other rule is untouched: hosted rows greyed, the key row live.
    assert all(row.enabled is False for row in rows if row.kind != "BYOK")
    assert [row.enabled for row in rows if row.kind == "BYOK"] == [True]


def test_the_byok_note_row_keeps_the_generic_text_before_the_credential_lands():
    rows = model_menu.build_rows([_record("a")], byok_active=True)

    assert rows[0].kind == "NOTE"
    assert rows[0].label == model_menu.BYOK_NOTE_TEXT


def test_no_note_row_without_a_key_and_none_on_the_empty_catalog():
    assert "NOTE" not in [
        row.kind for row in model_menu.build_rows(
            [_record("a")], byok_provider_label="OpenRouter", byok_model_label="M")
    ]
    # The empty catalog keeps its sentinel + key route, exactly as before.
    kinds = [row.kind for row in model_menu.build_rows(
        [], byok_active=True, byok_provider_label="OpenRouter")]
    assert kinds == ["SENTINEL", "BYOK"]


def test_the_menu_feeds_the_note_from_the_credential_state():
    """The menu passes the key's catalog labels into `build_rows` — read at
    draw time (never cached) so a late credential fetch shows next draw."""
    source = MENU_SOURCE.read_text(encoding="utf-8")
    assert "catalog_labels.byok_current_labels()" in source
    assert "byok_provider_label=byok_provider_label" in source
    assert "byok_model_label=byok_model_label" in source


# ---------------------------------------------------------------------------
# catalog_labels — the key's labels
# ---------------------------------------------------------------------------

def _populate_byok_catalog():
    model_suggestions.populate(
        [("openrouter", "OpenRouter", "")],
        {"openrouter": [("claude-sonnet-4-6", "Claude Sonnet 4.6", "")]},
    )


def test_the_keys_labels_come_from_the_catalog_with_raw_ids_as_fallback():
    _populate_byok_catalog()
    credential_state.apply_from_payload({
        "byok_active": True,
        "items": [{"provider": "openrouter", "model": "claude-sonnet-4-6"}],
    }, SimpleNamespace())
    assert catalog_labels.byok_current_labels() == ("OpenRouter", "Claude Sonnet 4.6")

    credential_state.apply_from_payload({
        "byok_active": True,
        "items": [{"provider": "mystery", "model": "gpt-6"}],
    }, SimpleNamespace())
    assert catalog_labels.byok_current_labels() == ("mystery", "gpt-6")


def test_no_key_means_no_labels():
    _populate_byok_catalog()
    assert catalog_labels.byok_current_labels() == ("", "")
    credential_state.apply_from_payload({
        "byok_active": False,
        "items": [{"provider": "openrouter", "model": "claude-sonnet-4-6"}],
    }, SimpleNamespace())
    assert catalog_labels.byok_current_labels() == ("", "")


def test_the_dialog_reuses_the_core_lookups():
    from mixar.modules.byok.ui.operators import byok_dialog_ui

    assert byok_dialog_ui.lookup_model_label is catalog_labels.lookup_model_label
    assert byok_dialog_ui.lookup_provider_label is catalog_labels.lookup_provider_label


# ---------------------------------------------------------------------------
# apply_to_wm — the composed label crosses the mirror boundary
# ---------------------------------------------------------------------------

def test_apply_to_wm_writes_the_composed_label_and_keeps_the_dict_model_only():
    wm = SimpleNamespace()
    preference_state.apply_from_payload({
        "byok_active": False,
        "items": [{"role": "default", "provider": "openai", "model": "gpt-5.6-sol",
                   "label": "GPT 5.6 Sol", "thinking_level": "high"}],
    }, wm)

    assert wm.mixar_agent_model_label == "GPT 5.6 Sol · High"
    assert preference_state.snapshot()["mixar_agent_model_label"] == "GPT 5.6 Sol"
    assert preference_state.chip_text() == "GPT 5.6 Sol · High"
    # Every other mirror field is copied verbatim.
    assert wm.mixar_agent_model_thinking == "high"
    assert wm.mixar_agent_model_id == "gpt-5.6-sol"


def test_apply_to_wm_writes_the_model_only_label_without_a_level():
    wm = SimpleNamespace()
    preference_state.apply_from_payload({
        "items": [{"role": "default", "provider": "openai", "model": "m",
                   "label": "GPT 5.6 Sol"}],
    }, wm)

    assert wm.mixar_agent_model_label == "GPT 5.6 Sol"


def test_apply_to_wm_writes_the_byok_indicator_while_a_key_overrides_the_pick():
    wm = SimpleNamespace()
    preference_state.apply_from_payload({
        "byok_active": True,
        "items": [{"role": "default", "provider": "openai", "model": "m",
                   "label": "GPT 5.6 Sol", "thinking_level": "high"}],
    }, wm)

    assert wm.mixar_agent_model_label == model_menu.BYOK_CHIP_TEXT
    assert wm.mixar_agent_model_byok_active is True
    # The dict still knows the pick the key is overriding.
    assert preference_state.snapshot()["mixar_agent_model_label"] == "GPT 5.6 Sol"


def test_clearing_the_pick_blanks_the_chip():
    wm = SimpleNamespace()
    preference_state.apply_from_payload({
        "items": [{"role": "default", "provider": "p", "model": "m", "label": "M",
                   "thinking_level": "low"}],
    }, wm)
    assert wm.mixar_agent_model_label == "M · Low"

    preference_state.clear(wm)
    assert wm.mixar_agent_model_label == ""


def test_the_optimistic_local_write_composes_too():
    wm = SimpleNamespace()
    preference_state.apply_local({
        "mixar_agent_model_label": "Claude Sonnet 4.6",
        "mixar_agent_model_thinking": "medium_high",
    }, wm)

    assert wm.mixar_agent_model_label == "Claude Sonnet 4.6 · Medium High"
