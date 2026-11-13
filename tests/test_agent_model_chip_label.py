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




# ---------------------------------------------------------------------------
# byok_note_text — pure
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# build_rows — the NOTE row
# ---------------------------------------------------------------------------







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


def test_the_key_chip_names_providers_from_the_catalog(monkeypatch):
    """Short names are the backend's (`short_label`, GET /agent/models); the
    desktop names only the providers it defines itself."""
    from mixar.modules.byok.core import catalog_labels
    monkeypatch.setattr(model_suggestions, '_short_providers',
                        {'anthropic': 'Claude API', 'gemini': 'Gemini API', 'newco': 'Newco API'})
    assert catalog_labels.chip_provider_label('anthropic') == 'Claude API'
    assert catalog_labels.chip_provider_label('newco') == 'Newco API'  # no client release needed
    assert catalog_labels.chip_provider_label('codex') == 'Codex'
    assert catalog_labels.chip_provider_label('openrouter') == 'OpenRouter'
    assert catalog_labels.chip_provider_label('local') == 'Local'
    assert catalog_labels.chip_provider_label('') == ''
    assert set(catalog_labels._CLIENT_PROVIDER_CHIP_LABELS) == {'openrouter', 'codex'}
    # A catalog provider without a short name (an older backend) reads its label.
    monkeypatch.setattr(catalog_labels, 'lookup_provider_label', lambda pid: 'Moonshot Kimi')
    assert catalog_labels.chip_provider_label('kimi') == 'Moonshot Kimi'


def test_the_key_chip_model_name_is_the_catalogs_short_label(monkeypatch):
    from mixar.modules.byok.core import catalog_labels
    monkeypatch.setattr(model_suggestions, '_short_models',
                        {('anthropic', 'claude-opus-5-5'): 'Opus 5.5', ('openai', 'gpt-6-sol'): 'GPT 6 Sol'})
    monkeypatch.setattr(catalog_labels, 'lookup_model_label',
                        lambda provider, model: {('anthropic', 'claude-sonnet-5'): 'Claude Sonnet 5'}
                        .get((provider, model), model))
    assert catalog_labels.chip_model_label('anthropic', 'claude-opus-5-5') == 'Opus 5.5'
    assert catalog_labels.chip_model_label('codex', 'gpt-6-sol') == 'GPT 6 Sol'  # the openai group
    # No short label: the full label as written — the client never cuts a word.
    assert catalog_labels.chip_model_label('anthropic', 'claude-sonnet-5') == 'Claude Sonnet 5'
    assert catalog_labels.chip_model_label('anthropic', 'claude-x') == 'claude-x'
    assert catalog_labels.chip_model_label('anthropic', '') == ''
