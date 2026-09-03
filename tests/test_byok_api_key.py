# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock()
if "requests.adapters" not in sys.modules:
    requests_adapters = MagicMock()
    requests_adapters.HTTPAdapter = MagicMock
    sys.modules["requests.adapters"] = requests_adapters
if "urllib3" not in sys.modules:
    sys.modules["urllib3"] = MagicMock()
if "urllib3.util" not in sys.modules:
    sys.modules["urllib3.util"] = MagicMock()
if "urllib3.util.retry" not in sys.modules:
    retry_module = MagicMock()
    retry_module.Retry = MagicMock
    sys.modules["urllib3.util.retry"] = retry_module

import bpy

from mixar.modules.byok.constants import BYOK_API_KEY_MAX_LENGTH
from mixar.modules.byok.core import model_suggestions
from mixar.modules.byok.ui.operators import byok_ops
from mixar.modules.byok.ui.properties import byok_props


def test_byok_api_key_property_allows_long_provider_keys():
    # Inspect the callable captured by byok_props at import time. Other test
    # modules may reinstall the bpy mock during collection.
    byok_props.StringProperty.reset_mock()

    byok_props.register()

    api_key_calls = [
        call.kwargs
        for call in byok_props.StringProperty.call_args_list
        if call.kwargs.get("name") == "API Key"
    ]
    assert api_key_calls
    assert api_key_calls[-1]["maxlen"] == BYOK_API_KEY_MAX_LENGTH
    assert BYOK_API_KEY_MAX_LENGTH == 256


def test_byok_save_passes_long_api_key_without_truncation(monkeypatch):
    saved = {}
    long_key = "sk-proj-" + ("a" * 180) + "_tail"
    wm = SimpleNamespace(
        byok_dialog_state="IDLE",
        byok_form_provider="openai",
        byok_form_model="gpt-5",
        byok_form_api_key=f"  {long_key}  ",
        byok_last_error="",
    )
    context = SimpleNamespace(window_manager=wm)

    def fake_save_credentials(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(byok_ops.byok_client, "save_credentials", fake_save_credentials)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    model_suggestions.populate(
        providers=[("openai", "OpenAI", "OpenAI")],
        models={"openai": [("gpt-5", "GPT-5", "GPT-5")]},
    )

    try:
        result = byok_ops.MIXAR_BYOK_OT_save().execute(context)
    finally:
        model_suggestions.clear()

    assert result == {"FINISHED"}
    assert saved["provider"] == "openai"
    assert saved["model"] == "gpt-5"
    assert saved["api_key"] == long_key
    assert len(saved["api_key"]) == len(long_key)


def test_native_password_field_buffer_matches_byok_key_limit():
    handlers = (
        ROOT
        / "src"
        / "source"
        / "blender"
        / "editors"
        / "interface"
        / "interface_handlers.cc"
    )

    # Blender 5.2 replaced the fixed UI_MAX_PASSWORD_STR char buffer with an
    # unbounded std::string, so long BYOK keys can no longer be truncated by
    # the native password field. Pin the std::string-based implementation.
    text = handlers.read_text(encoding="utf-8")
    assert "UI_MAX_PASSWORD_STR" not in text
    assert "std::string password_str" in text
