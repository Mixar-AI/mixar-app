# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK provider-dropdown regression coverage."""

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

from mixar.modules.byok.core import model_suggestions
from mixar.modules.byok.ui.operators import byok_ops
from mixar.modules.byok.ui.properties import byok_props


@pytest.fixture(autouse=True)
def _no_codex_account_list(monkeypatch):
    """Each test starts with the account's model list unknown and leaves no list behind."""
    monkeypatch.setattr(model_suggestions, "_codex_account_models", None)


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


def test_provider_change_back_to_the_key_in_use_keeps_its_model(monkeypatch):
    """Leaving the provider in use and coming back lights the model it runs,
    not the first in the list; a paused key's provider likewise."""
    model_suggestions.populate(
        providers=[("provider-b", "Provider B", "Provider B")],
        models={"provider-b": [("model-b1", "Model B1", "Model B1"),
                               ("model-b2", "Model B2", "Model B2")]},
    )
    wm = SimpleNamespace(byok_form_provider="provider-b", byok_form_model="model-b1",
                         byok_is_active=True, byok_current_provider="provider-b",
                         byok_current_model="model-b2")
    byok_props._provider_changed(wm, SimpleNamespace(window_manager=wm))
    assert wm.byok_form_model == "model-b2"
    # Another provider's key in use: the first model, as before.
    wm.byok_current_provider = "provider-x"
    byok_props._provider_changed(wm, SimpleNamespace(window_manager=wm))
    assert wm.byok_form_model == "model-b1"
    # A paused key on this provider: its model.
    from mixar.modules.byok.core import credential_state
    wm.byok_is_active = False
    monkeypatch.setattr(credential_state, "resume_target", lambda: ("provider-b", "model-b2"))
    byok_props._provider_changed(wm, SimpleNamespace(window_manager=wm))
    assert wm.byok_form_model == "model-b2"
    # A remembered model the catalog no longer lists: the first one.
    monkeypatch.setattr(credential_state, "resume_target", lambda: ("provider-b", "retired"))
    byok_props._provider_changed(wm, SimpleNamespace(window_manager=wm))
    assert wm.byok_form_model == "model-b1"
    model_suggestions.clear()


def test_save_names_what_is_missing(monkeypatch):
    """One message per missing piece: a picked model is never asked for again."""
    model_suggestions.populate(
        providers=[("provider-b", "Provider B", "Provider B")],
        models={"provider-b": [("model-b", "Model B", "Model B")]},
    )
    monkeypatch.setattr(byok_ops.byok_client, "save_credentials",
                        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("reached network")))
    cases = (("provider-b", "model-b", "", "Enter your API key."),
             ("provider-b", "stale", "secret", "Pick a model."),
             ("NONE", "model-b", "secret", "Pick a provider."))
    for provider, model, key, message in cases:
        wm = SimpleNamespace(byok_dialog_state="IDLE", byok_last_error="",
                             byok_form_provider=provider, byok_form_model=model,
                             byok_form_api_key=key)
        assert byok_ops.MIXAR_BYOK_OT_save().execute(SimpleNamespace(window_manager=wm)) == {'CANCELLED'}
        assert (wm.byok_dialog_state, wm.byok_last_error) == ("ERROR", message)
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


def test_codex_save_uses_openai_catalog_models(monkeypatch, tmp_path):
    """Codex has no catalog group of its own: its model dropdown reuses the
    "openai" models. A stale/sentinel selection is rejected before the
    network; a real openai catalog model is sent with the ACCESS TOKEN read
    out of the CLI's auth.json as the key (plus the ChatGPT account id) —
    the file itself never leaves the machine."""
    import base64
    import json

    def _jwt(claims):
        def seg(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
        return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"

    access_token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"}})
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"tokens": {"access_token": access_token, "refresh_token": "rt-1"}}))
    model_suggestions.populate(
        providers=[("openai", "OpenAI", "From catalog")],
        models={"openai": [("gpt-5.5", "GPT-5.5", "GPT-5.5")]},
    )
    assert model_suggestions.get_model_items("codex") == [("gpt-5.5", "GPT-5.5", "GPT-5.5")]
    assert model_suggestions.is_valid_model("codex", "gpt-5.5") is True

    sent = []
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(
        byok_ops.byok_client, "save_credentials", lambda **kwargs: sent.append(kwargs),
    )

    def _wm(model):
        return SimpleNamespace(
            byok_dialog_state="IDLE",
            byok_last_error="",
            byok_form_provider="codex",
            byok_form_model=model,
            byok_form_model_id=model,
            byok_form_codex_path=str(auth_file),
            byok_is_active=False,
        )

    stale = _wm("NONE")
    assert byok_ops.MIXAR_BYOK_OT_save().execute(
        SimpleNamespace(window_manager=stale)) == {'CANCELLED'}
    assert stale.byok_dialog_state == "ERROR"
    assert sent == []

    ok = _wm("gpt-5.5")
    assert byok_ops.MIXAR_BYOK_OT_save().execute(
        SimpleNamespace(window_manager=ok)) == {'FINISHED'}
    assert ok.byok_dialog_state == "SAVING"
    assert sent[0]["provider"] == "codex"
    assert sent[0]["model"] == "gpt-5.5"
    assert sent[0]["api_key"] == access_token
    assert sent[0]["account_id"] == "acct-1"
    assert "refresh_token" not in sent[0]                 # stays in the CLI's file
    assert sent[0]["codex_auth_path"] == str(auth_file)   # the device keeps the reference
    model_suggestions.clear()


def test_codex_lists_only_the_models_the_chatgpt_account_can_run():
    """mixar-backend#1809: a Codex model the ChatGPT plan lacks fails Save with
    model_not_found. Once the account's own listing is known, the Codex chips
    and Save's model check keep to it; OpenAI API keys still see every model."""
    catalog = [("gpt-6.1-terra", "GPT 6.1 Terra", "GPT 6.1 Terra"),
               ("gpt-6-astra", "GPT 6 Astra", "GPT 6 Astra"),
               ("gpt-6-luna", "GPT 6 Luna", "GPT 6 Luna")]
    model_suggestions.populate(providers=[("openai", "OpenAI", "OpenAI")],
                               models={"openai": catalog})
    assert model_suggestions.get_model_items("codex") == catalog   # unknown: everything
    assert model_suggestions.codex_models_hidden() is False

    model_suggestions.set_codex_account_models({"gpt-6-luna", "gpt-reserve"})
    assert model_suggestions.get_model_items("codex") == [catalog[2]]
    assert model_suggestions.is_valid_model("codex", "gpt-6-astra") is False
    assert model_suggestions.is_valid_model("codex", "gpt-6-luna") is True
    assert model_suggestions.get_model_items("openai") == catalog   # API keys unaffected
    assert model_suggestions.is_valid_model("openai", "gpt-6-astra") is True
    assert model_suggestions.codex_models_hidden() is True

    # A list sharing no id with the catalog says nothing about it: unknown, so
    # the whole group (never the NONE sentinel, which would block Codex).
    model_suggestions.set_codex_account_models({"gpt-reserve"})
    assert model_suggestions.get_model_items("codex") == catalog
    assert model_suggestions.codex_models_hidden() is False

    model_suggestions.set_codex_account_models(None)   # unknown again: everything
    assert model_suggestions.get_model_items("codex") == catalog
    model_suggestions.set_codex_account_models({"gpt-6-luna"})
    model_suggestions.clear()                           # logout forgets the account
    model_suggestions.populate(providers=[("openai", "OpenAI", "OpenAI")],
                               models={"openai": catalog})
    assert model_suggestions.get_model_items("codex") == catalog
    model_suggestions.clear()


class _CodexForm:
    """The dialog form as RNA keeps it (see test_byok_enum_identifier_picks):
    the model pick is the stored identifier behind the enum's get / set, and a
    read resolves get()'s index through the CURRENT (narrowed) items."""

    def __init__(self, auth_file, **fields):
        self.byok_form_provider_id = "codex"
        self.byok_form_model_id = ""
        self.byok_form_codex_path = str(auth_file)
        self.byok_dialog_state, self.byok_last_error = "IDLE", ""
        self.byok_is_active, self.byok_device_key_missing = False, False
        self.byok_current_provider, self.byok_current_model = "", ""
        self.__dict__.update(fields)

    @property
    def byok_form_provider(self):
        return byok_props._provider_items(self, None)[byok_props._provider_get(self)][0]

    @byok_form_provider.setter
    def byok_form_provider(self, identifier):   # RNA's set: _provider_changed follows
        ids = [item[0] for item in byok_props._provider_items(self, None)]
        if identifier not in ids:
            raise TypeError(f"enum {identifier!r} not found")
        byok_props._provider_set(self, ids.index(identifier))

    @property
    def byok_form_model(self):
        return byok_props._model_items(self, None)[byok_props._model_get(self)][0]

    @byok_form_model.setter
    def byok_form_model(self, identifier):
        ids = [item[0] for item in byok_props._model_items(self, None)]
        if identifier not in ids:
            raise TypeError(f"enum {identifier!r} not found")
        byok_props._model_set(self, ids.index(identifier))


def _codex_save(monkeypatch, tmp_path, **fields):
    auth_file = tmp_path / "auth.json"
    auth_file.write_text('{"tokens": {"access_token": "at", "refresh_token": "rt", '
                         '"account_id": "acct-1"}}')
    model_suggestions.populate(
        providers=[("openai", "OpenAI", "OpenAI")],
        models={"openai": [("gpt-6-astra", "GPT 6 Astra", "GPT 6 Astra"),
                           ("gpt-6-luna", "GPT 6 Luna", "GPT 6 Luna")]},
    )
    sent = []
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops.byok_client, "save_credentials",
                        lambda **kwargs: sent.append(kwargs))
    return _CodexForm(auth_file, **fields), sent


def _press_save(wm):
    return byok_ops.MIXAR_BYOK_OT_save().execute(SimpleNamespace(window_manager=wm))


def test_codex_save_never_sends_a_model_the_user_did_not_pick(monkeypatch, tmp_path):
    """A pick the account's list hides reads as the FIRST listed model through
    the enum getter; Save must refuse it, not send that first model."""
    wm, sent = _codex_save(monkeypatch, tmp_path)
    wm.byok_form_model = "gpt-6-astra"                      # picked while the list was unknown
    model_suggestions.set_codex_account_models({"gpt-6-luna"})
    assert wm.byok_form_model == "gpt-6-luna"               # the getter's fallback
    assert wm.byok_form_model_id == "gpt-6-astra"           # the stored pick is untouched

    assert _press_save(wm) == {'CANCELLED'}
    assert (wm.byok_dialog_state, wm.byok_last_error) == ("ERROR", "Choose a Codex model.")
    assert sent == []

    wm.byok_form_model = "gpt-6-luna"                       # the user picks a listed model
    assert _press_save(wm) == {'FINISHED'}
    assert sent[-1]["model"] == "gpt-6-luna"
    model_suggestions.clear()


def test_codex_key_only_save_keeps_the_saved_model(monkeypatch, tmp_path):
    """Key needed on this computer: the chips are locked to the account's saved
    model, so Save re-sends THAT model even when the list hides it — never the
    first listed one, which would switch the account's model on every device."""
    wm, sent = _codex_save(monkeypatch, tmp_path, byok_is_active=True,
                           byok_device_key_missing=True, byok_current_provider="codex",
                           byok_current_model="gpt-6-astra")
    model_suggestions.set_codex_account_models({"gpt-6-luna"})
    assert _press_save(wm) == {'FINISHED'}
    assert sent[-1]["model"] == "gpt-6-astra"
    model_suggestions.clear()


def test_dialog_cancel_wipes_live_secret_fields():
    wm = SimpleNamespace(
        byok_form_api_key="provider-secret",
        byok_form_local_custom_key="local-secret",
        byok_form_codex_path="/not/a/secret.json",
    )

    byok_ops.MIXAR_BYOK_OT_open_dialog().cancel(
        SimpleNamespace(window_manager=wm)
    )

    assert wm.byok_form_api_key == ""
    assert wm.byok_form_local_custom_key == ""
    assert wm.byok_form_codex_path == "/not/a/secret.json"   # a path, not a secret


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
    assert by_name["Codex sign-in file"]["options"] == {'SKIP_SAVE'}
    assert by_name["Codex sign-in file"]["subtype"] == 'FILE_PATH'
