# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK provider-dropdown regression coverage."""

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import model_suggestions
from mixar.modules.byok.ui.operators import byok_ops
from mixar.modules.byok.ui.properties import byok_props


def test_client_provider_fallback_does_not_duplicate_catalog_entries():
    model_suggestions.populate(
        providers=[
            ("openrouter", "OpenRouter (admin label)", "From catalog"),
            ("openai", "OpenAI", "From catalog"),
        ],
        models={},
    )

    identifiers = [item[0] for item in model_suggestions.get_provider_items()]

    # OpenRouter is offered as a client-side fallback; when the catalog already
    # lists it, the fallback must not add a duplicate entry.
    assert identifiers.count("openrouter") == 1
    assert identifiers.count("openai") == 1
    model_suggestions.clear()


def test_openrouter_fallback_added_when_absent_from_catalog():
    model_suggestions.populate(
        providers=[("openai", "OpenAI", "From catalog")],
        models={},
    )

    identifiers = [item[0] for item in model_suggestions.get_provider_items()]

    # Always offered even when the backend catalog omits it.
    assert identifiers.count("openrouter") == 1
    model_suggestions.clear()


def test_model_validation_is_scoped_to_selected_provider():
    model_suggestions.populate(
        providers=[
            ("provider-a", "Provider A", "Provider A"),
            ("provider-b", "Provider B", "Provider B"),
        ],
        models={
            "provider-a": [("model-a", "Model A", "Model A")],
            "provider-b": [("model-b", "Model B", "Model B")],
        },
    )

    assert model_suggestions.is_valid_model("provider-a", "model-a") is True
    assert model_suggestions.is_valid_model("provider-a", "model-b") is False
    assert model_suggestions.is_valid_model("provider-a", "NONE") is False
    model_suggestions.clear()


def test_provider_change_selects_first_model_from_new_provider():
    model_suggestions.populate(
        providers=[("provider-b", "Provider B", "Provider B")],
        models={
            "provider-b": [
                ("model-b1", "Model B1", "Model B1"),
                ("model-b2", "Model B2", "Model B2"),
            ]
        },
    )
    wm = SimpleNamespace(
        byok_form_provider="provider-b",
        byok_form_model="stale-model-a",
    )

    byok_props._provider_changed(wm, SimpleNamespace(window_manager=wm))

    assert wm.byok_form_model == "model-b1"
    model_suggestions.clear()


def test_save_rejects_stale_model_from_another_provider(monkeypatch):
    model_suggestions.populate(
        providers=[("provider-b", "Provider B", "Provider B")],
        models={"provider-b": [("model-b", "Model B", "Model B")]},
    )
    wm = SimpleNamespace(
        byok_dialog_state="IDLE",
        byok_last_error="",
        byok_form_provider="provider-b",
        byok_form_model="model-from-provider-a",
        byok_form_api_key="secret",
    )
    context = SimpleNamespace(window_manager=wm)
    monkeypatch.setattr(
        byok_ops.byok_client,
        "save_credentials",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid provider/model reached network")
        ),
    )

    # Save is clickable (poll only guards in-flight requests); the stale
    # combo is rejected in execute() and never reaches the network.
    assert byok_ops.MIXAR_BYOK_OT_save.poll(context) is True
    assert byok_ops.MIXAR_BYOK_OT_save().execute(context) == {'CANCELLED'}
    assert wm.byok_dialog_state == "ERROR"
    model_suggestions.clear()


def test_dialog_cancel_wipes_live_secret_fields():
    wm = SimpleNamespace(
        byok_form_api_key="provider-secret",
        byok_form_codex_bundle="jwt-bundle",
    )

    byok_ops.MIXAR_BYOK_OT_open_dialog().cancel(
        SimpleNamespace(window_manager=wm)
    )

    assert wm.byok_form_api_key == ""
    assert wm.byok_form_codex_bundle == ""


def test_secret_properties_are_not_saved_in_blend_files(monkeypatch):
    string_properties = []

    def _string_property(**kwargs):
        string_properties.append(kwargs)
        return ""

    monkeypatch.setattr(byok_props, "StringProperty", _string_property)
    monkeypatch.setattr(
        byok_props.bpy.types,
        "WindowManager",
        type("TestWindowManager", (), {}),
        raising=False,
    )

    byok_props.register()

    by_name = {item.get("name"): item for item in string_properties}
    assert by_name["API Key"]["options"] == {'SKIP_SAVE'}
    assert by_name["Codex auth.json"]["options"] == {'SKIP_SAVE'}
