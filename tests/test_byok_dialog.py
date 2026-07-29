# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK dialog presentation logic — the parts that can be tested at all.

Panel ``draw()`` needs a GUI session, so the dialog's *decisions* are
kept in pure functions and exercised here: what blocks Save, what the
status line says, and how a catalog response is parsed.
"""

import pytest

from mixar.modules.byok.core import model_suggestions
from mixar.modules.byok.ui import byok_dialog_drawer as drawer


@pytest.fixture(autouse=True)
def _catalog():
    """Populate the module-level catalog cache and reset it afterwards."""
    model_suggestions.populate(
        providers=[("anthropic", "Anthropic", "Anthropic")],
        models={"anthropic": [("claude-sonnet-4-5", "Claude Sonnet 4.5", "")]},
    )
    yield
    model_suggestions.clear()


class _WM:
    """Stand-in for the WindowManager the dialog reads."""

    def __init__(self, **overrides):
        self.byok_form_provider = "anthropic"
        self.byok_form_model = "claude-sonnet-4-5"
        self.byok_form_api_key = "sk-secret"
        self.byok_form_openrouter_model = ""
        self.byok_form_codex_model = ""
        self.byok_form_codex_bundle = ""
        self.byok_is_active = False
        self.byok_current_provider = ""
        self.byok_current_model = ""
        self.byok_current_supports_vision = True
        self.byok_key_preview = ""
        self.__dict__.update(overrides)


# --- save_blocker -----------------------------------------------------------

def test_complete_cloud_form_has_no_blocker():
    assert drawer.save_blocker(_WM()) is None


def test_blocker_names_the_missing_api_key():
    blocker = drawer.save_blocker(_WM(byok_form_api_key="   "))

    assert blocker is not None
    assert "API key" in blocker


def test_blocker_rejects_a_model_absent_from_the_providers_catalog():
    # A stale selection left behind by a provider switch or a catalog
    # refresh must not be savable.
    blocker = drawer.save_blocker(_WM(byok_form_model="gone-from-catalog"))

    assert blocker == "Choose a model for this provider."


def test_blocker_rejects_the_sentinel_provider():
    blocker = drawer.save_blocker(_WM(byok_form_provider="NONE"))

    assert blocker == "Choose a provider to continue."


def test_openrouter_accepts_a_free_text_slug_not_in_the_catalog():
    wm = _WM(
        byok_form_provider="openrouter",
        byok_form_openrouter_model="anthropic/claude-opus-4.8",
    )

    assert drawer.save_blocker(wm) is None


def test_codex_requires_the_auth_bundle():
    wm = _WM(byok_form_provider="codex", byok_form_codex_model="gpt-5.5")

    blocker = drawer.save_blocker(wm)

    assert blocker is not None
    assert "auth.json" in blocker


def test_codex_is_complete_once_the_bundle_is_present():
    wm = _WM(
        byok_form_provider="codex",
        byok_form_codex_model="gpt-5.5",
        byok_form_codex_bundle='{"tokens": "..."}',
    )

    assert drawer.save_blocker(wm) is None


def test_blocker_never_reports_the_transient_saving_state():
    # SAVING blocks the button, but it is not a requirement the user can
    # act on, so it must not leak into the hint text.
    wm = _WM()
    wm.byok_dialog_state = 'SAVING'

    assert drawer.save_blocker(wm) is None


# --- status_summary ---------------------------------------------------------

def test_status_summary_explains_the_unconfigured_default():
    summary = drawer.status_summary(_WM())

    assert "default provider" in summary


def test_status_summary_uses_catalog_labels_and_keeps_the_key_preview():
    wm = _WM(
        byok_is_active=True,
        byok_current_provider="anthropic",
        byok_current_model="claude-sonnet-4-5",
        byok_key_preview="sk-...4f2a",
    )

    summary = drawer.status_summary(wm)

    assert "Anthropic" in summary
    assert "Claude Sonnet 4.5" in summary
    assert "sk-...4f2a" in summary


def test_status_summary_falls_back_to_raw_ids_for_a_withdrawn_model():
    # The admin removed the model after the user saved it — the dialog
    # must still name what is actually in use.
    wm = _WM(
        byok_is_active=True,
        byok_current_provider="anthropic",
        byok_current_model="retired-model",
    )

    summary = drawer.status_summary(wm)

    assert "retired-model" in summary
    assert "Key stored securely" in summary


def test_status_summary_labels_codex_as_a_subscription():
    wm = _WM(
        byok_is_active=True,
        byok_current_provider="codex",
        byok_current_model="gpt-5.5",
    )

    assert "ChatGPT subscription" in drawer.status_summary(wm)


# --- codex_bundle_status ----------------------------------------------------

def test_codex_status_counts_a_loaded_bundle():
    text, icon = drawer.codex_bundle_status("x" * 120)

    assert text == "120 characters loaded"
    assert icon == 'CHECKMARK'


def test_codex_status_reports_an_empty_field():
    text, icon = drawer.codex_bundle_status("")

    assert "Empty" in text
    assert icon == 'INFO'


# --- wrap -------------------------------------------------------------------

def test_wrap_breaks_on_word_boundaries_within_the_width():
    lines = drawer.wrap("the quick brown fox jumps over it", width=10)

    assert all(len(line) <= 10 for line in lines)
    assert " ".join(lines) == "the quick brown fox jumps over it"


def test_wrap_truncates_a_single_word_longer_than_the_width():
    assert drawer.wrap("supercalifragilistic", width=8) == ["supercal"]


def test_wrap_always_returns_at_least_one_line():
    assert drawer.wrap("", width=10) == [""]


# --- parse_catalog ----------------------------------------------------------

def test_parse_catalog_maps_providers_and_models_to_enum_tuples():
    providers, models = model_suggestions.parse_catalog({
        "providers": [{
            "id": "anthropic",
            "label": "Anthropic",
            "models": [{"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5"}],
        }],
    })

    assert providers == [("anthropic", "Anthropic", "Anthropic")]
    assert models == {
        "anthropic": [("claude-sonnet-4-5", "Claude Sonnet 4.5", "Claude Sonnet 4.5")],
    }


def test_parse_catalog_skips_malformed_rows_without_losing_the_rest():
    providers, models = model_suggestions.parse_catalog({
        "providers": [
            "not-a-dict",
            {"label": "No ID"},
            {"id": "openai", "models": [{"label": "no id"}, {"id": "gpt-5"}]},
        ],
    })

    # Label-less entries fall back to the raw ID rather than being dropped.
    assert providers == [("openai", "openai", "openai")]
    assert models == {"openai": [("gpt-5", "gpt-5", "gpt-5")]}


def test_parse_catalog_tolerates_an_empty_or_absent_payload():
    assert model_suggestions.parse_catalog({}) == ([], {})
    assert model_suggestions.parse_catalog(None) == ([], {})
