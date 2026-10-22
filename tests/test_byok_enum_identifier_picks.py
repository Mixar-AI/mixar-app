# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK provider / model dropdowns keep the user's pick when the list reshapes.

Blender stores a dynamic 3-tuple EnumProperty's selection as the list INDEX, so
OpenRouter picked while the catalog was loading (index 1) became the second
cloud provider once it loaded, and an auto-set first model became whichever
model a refresh put first. The picks now live in hidden identifier strings
(`byok_form_provider_id` / `byok_form_model_id`) behind the enums' get / set.
`_WM` plays RNA's part: a read resolves get()'s index through the current
items, a write validates the identifier and hands set() its index.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import model_suggestions
from mixar.modules.byok.ui.properties import byok_props


PROVIDERS = [
    ("anthropic", "Anthropic", "Anthropic"),
    ("google", "Google", "Google"),
    ("openai", "OpenAI", "OpenAI"),
]
MODELS = {
    "anthropic": [("claude-a", "Claude A", "Claude A"), ("claude-b", "Claude B", "Claude B")],
    "openai": [
        ("gpt-5", "GPT-5", "GPT-5"),
        ("gpt-5.5", "GPT-5.5", "GPT-5.5"),
        ("gpt-5-mini", "GPT-5 mini", "GPT-5 mini"),
    ],
}


class _WM:
    def __init__(self):
        self.byok_form_provider_id = ''
        self.byok_form_model_id = ''

    @staticmethod
    def _write(items, identifier, setter, wm):
        ids = [item[0] for item in items]
        if identifier not in ids:
            raise TypeError(f"enum {identifier!r} not found")
        setter(wm, ids.index(identifier))

    @property
    def byok_form_provider(self):
        return byok_props._provider_items(self, None)[byok_props._provider_get(self)][0]

    @byok_form_provider.setter
    def byok_form_provider(self, identifier):
        self._write(byok_props._provider_items(self, None), identifier,
                    byok_props._provider_set, self)

    @property
    def byok_form_model(self):
        return byok_props._model_items(self, None)[byok_props._model_get(self)][0]

    @byok_form_model.setter
    def byok_form_model(self, identifier):
        self._write(byok_props._model_items(self, None), identifier,
                    byok_props._model_set, self)


@pytest.fixture(autouse=True)
def _fresh_catalog():
    model_suggestions.clear()
    yield
    model_suggestions.clear()


def test_the_auto_set_first_model_survives_a_reorder():
    # The reviewer's case: picking OpenAI auto-sets its FIRST model, gpt-5; a
    # refresh then puts gpt-6 first. Save must still send gpt-5.
    model_suggestions.populate(PROVIDERS, MODELS)
    wm = _WM()
    wm.byok_form_provider = "openai"
    assert wm.byok_form_model == "gpt-5"

    reordered = dict(MODELS)
    reordered["openai"] = [("gpt-6", "GPT-6", "GPT-6")] + MODELS["openai"]
    model_suggestions.populate(PROVIDERS, reordered)

    assert wm.byok_form_provider == "openai"
    assert wm.byok_form_model == "gpt-5"


def test_the_first_provider_survives_a_provider_sorting_ahead_of_it():
    model_suggestions.populate(PROVIDERS, MODELS)
    wm = _WM()
    wm.byok_form_provider = "anthropic"

    model_suggestions.populate([("aaa", "AAA", "AAA")] + PROVIDERS, MODELS)

    assert wm.byok_form_provider == "anthropic"
    assert wm.byok_form_model == "claude-a"


@pytest.mark.parametrize("picked", ["openrouter", "codex", "local"])
def test_a_client_option_picked_while_loading_survives_the_catalog_load(picked, monkeypatch):
    monkeypatch.setattr(byok_props, "is_local", lambda _provider: False)
    wm = _WM()
    assert wm.byok_form_provider == "NONE"  # the "Loading…" sentinel
    wm.byok_form_provider = picked

    model_suggestions.populate(PROVIDERS, MODELS)

    assert wm.byok_form_provider == picked


def test_a_model_pick_survives_a_refresh_that_reorders_the_models():
    model_suggestions.populate(PROVIDERS, MODELS)
    wm = _WM()
    wm.byok_form_provider = "openai"
    wm.byok_form_model = "gpt-5-mini"

    reordered = dict(MODELS)
    reordered["openai"] = [MODELS["openai"][2], ("gpt-6", "GPT-6", "GPT-6"), MODELS["openai"][0]]
    model_suggestions.populate(PROVIDERS, reordered)

    assert wm.byok_form_model == "gpt-5-mini"


def test_a_provider_switch_resets_the_model_by_identifier():
    model_suggestions.populate(PROVIDERS, MODELS)
    wm = _WM()
    wm.byok_form_provider = "openai"
    wm.byok_form_model = "gpt-5.5"

    wm.byok_form_provider = "anthropic"

    assert wm.byok_form_model_id == "claude-a"
    assert wm.byok_form_model == "claude-a"


def test_unset_or_unknown_ids_fall_back_to_the_first_item():
    wm = _WM()
    assert wm.byok_form_provider == "NONE"
    assert wm.byok_form_model == "NONE"

    # The first item in display order (no catalog order here: the default
    # order puts OpenAI first) and its first model.
    model_suggestions.populate(PROVIDERS, MODELS)
    assert wm.byok_form_provider == "openai"
    assert wm.byok_form_model == "gpt-5"

    wm.byok_form_provider_id = "retired-provider"
    wm.byok_form_model_id = "retired-model"
    assert wm.byok_form_provider == "openai"
    assert wm.byok_form_model == "gpt-5"


def test_an_unlisted_identifier_is_refused_and_keeps_the_pick():
    model_suggestions.populate(PROVIDERS, MODELS)
    wm = _WM()
    wm.byok_form_provider = "openai"
    with pytest.raises(TypeError):
        wm.byok_form_model = "not-in-the-catalog"
    assert wm.byok_form_model == "gpt-5"


def test_the_enums_are_identifier_backed_and_runtime_only(monkeypatch):
    class WindowManager:
        pass

    monkeypatch.setattr(byok_props.bpy.types, "WindowManager", WindowManager)
    for name in ("EnumProperty", "StringProperty", "BoolProperty"):
        monkeypatch.setattr(byok_props, name, lambda **kwargs: kwargs)
    byok_props.register()

    provider = WindowManager.byok_form_provider
    model = WindowManager.byok_form_model
    assert provider["get"] is byok_props._provider_get
    assert provider["set"] is byok_props._provider_set
    assert "update" not in provider  # the set function runs the model reset
    assert model["get"] is byok_props._model_get
    assert model["set"] is byok_props._model_set
    for prop in (provider, model, WindowManager.byok_form_provider_id,
                 WindowManager.byok_form_model_id):
        assert prop["options"] == {'SKIP_SAVE'}
    for attr in ("byok_form_provider_id", "byok_form_model_id"):
        assert attr in byok_props._WM_ATTRS
    # Plain 3-tuples: the stable-number scheme is gone.
    model_suggestions.populate(PROVIDERS, MODELS)
    assert all(len(item) == 3 for item in byok_props._provider_items(None, None))
    assert not hasattr(model_suggestions, "enum_items")
