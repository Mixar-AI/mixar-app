# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local (this computer) BYOK provider — functional coverage.

Runs under the standalone suite (bpy mocked): provider dropdown entry,
model-item suffix rules, save-path payloads (managed uses the manifest
api-token + the live server base; the extended base_url/supports_vision
fields are forwarded only when provided), and the Save poll gating.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import byok_client, local_provider, model_suggestions
from mixar.modules.byok.ui.operators import byok_local_ops, byok_ops
from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.services.agent_service import AgentService
from mixar.modules.local_models.core import (
    detect,
    manifest,
    orchestrator,
    server_supervisor,
)


class InlineThread:
    """threading.Thread stand-in that runs the target on start()."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


# ---------------------------------------------------------------------------
# Provider dropdown
# ---------------------------------------------------------------------------


def test_local_provider_always_offered():
    model_suggestions.clear()
    identifiers = [item[0] for item in model_suggestions.get_provider_items()]
    assert identifiers.count("local") == 1
    assert model_suggestions.is_local("local") is True
    assert model_suggestions.is_local("openrouter") is False


def test_local_provider_not_duplicated_when_catalog_lists_it():
    model_suggestions.populate(
        providers=[("local", "Local (admin label)", "From catalog")],
        models={},
    )
    identifiers = [item[0] for item in model_suggestions.get_provider_items()]
    assert identifiers.count("local") == 1
    model_suggestions.clear()


# ---------------------------------------------------------------------------
# Managed model dropdown suffixes
# ---------------------------------------------------------------------------


def test_build_model_items_suffix_rules():
    rows = [
        {"id": "a", "label": "A", "description": "d", "total_bytes": 2 * 1024**3,
         "downloaded": True, "fit": "fits", "recommended": True},
        {"id": "b", "label": "B", "description": "d", "total_bytes": 1024**3,
         "downloaded": False, "fit": "fits", "recommended": False},
        {"id": "c", "label": "C", "description": "d", "total_bytes": 20 * 1024**3,
         "downloaded": False, "fit": "too_big", "recommended": False},
    ]
    items = local_provider.build_model_items(rows)
    labels = {ident: label for ident, label, _d in items}
    assert labels["a"] == "A (recommended)"
    assert labels["b"] == "B — not downloaded"
    assert labels["c"] == "C — too large for this machine"


# ---------------------------------------------------------------------------
# agent_service / byok_client — extended payload only when provided
# ---------------------------------------------------------------------------


def _capturing_service():
    """AgentService with its HTTP verbs stubbed; captures (method, path, payload).

    BYOK is plain HTTP again: PUT /api/v1/agent/byok, not the `byok.set`
    WebSocket command. Settings must be reachable before the agent socket
    exists — that is the whole reason for the transport.
    """
    captured = {}

    def _put(path, json=None, **kwargs):
        captured.update(method="PUT", path=path, payload=json)
        return APIResponse(success=True, status_code=200, data={
            "status": "success", "message": "",
            "data": {"byok_active": True, "items": []},
        })

    service = AgentService.__new__(AgentService)
    service.put = _put
    return service, captured


def test_save_credentials_all_omits_extended_fields_by_default():
    service, captured = _capturing_service()
    service.save_credentials_all(provider="openai", model="m", api_key="k")
    assert (captured["method"], captured["path"]) == ("PUT", "byok")
    assert "base_url" not in captured["payload"]
    assert "supports_vision" not in captured["payload"]


def test_save_credentials_all_forwards_extended_fields_when_provided():
    service, captured = _capturing_service()
    service.save_credentials_all(
        provider="local", model="qwen3.5-4b", api_key="tok",
        base_url="http://127.0.0.1:11500", supports_vision=True,
    )
    assert captured["payload"]["base_url"] == "http://127.0.0.1:11500"
    assert captured["payload"]["supports_vision"] is True


def test_byok_client_forwards_extended_fields(monkeypatch):
    service, captured = _capturing_service()
    monkeypatch.setattr(byok_client, "get_agent_service", lambda: service)
    monkeypatch.setattr(byok_client.threading, "Thread", InlineThread)
    done = {}
    monkeypatch.setattr(
        byok_client, "_schedule_on_main",
        lambda callback, *args: done.update(result=args) or callback(*args),
    )

    byok_client.save_credentials(
        provider="local", model="qwen3.5-4b", api_key="tok",
        base_url="http://127.0.0.1:11501", supports_vision=False,
        on_done=lambda *_a: None,
    )
    assert captured["payload"]["base_url"] == "http://127.0.0.1:11501"
    assert captured["payload"]["supports_vision"] is False
    assert done["result"][0] is True  # success reached on_done


# ---------------------------------------------------------------------------
# Managed save path
# ---------------------------------------------------------------------------


def test_save_managed_requires_healthy_matching_server(monkeypatch):
    monkeypatch.setattr(server_supervisor, "is_healthy", lambda: False)
    monkeypatch.setattr(server_supervisor, "current", lambda: None)
    wm = SimpleNamespace(byok_form_local_model="qwen3.5-4b")
    started, err = local_provider.save_managed(wm, on_done=lambda *_a: None)
    assert started is False
    assert "Start the local model" in err


def test_save_managed_registers_token_base_and_vision(monkeypatch):
    monkeypatch.setattr(server_supervisor, "is_healthy", lambda: True)
    monkeypatch.setattr(server_supervisor, "current", lambda: {
        "model_id": "qwen3.5-4b", "port": 11500, "pid": 1, "state": "ready",
        "base_url": "http://127.0.0.1:11500",
    })
    monkeypatch.setattr(manifest, "get_api_token", lambda: "manifest-token")
    registered = {}
    monkeypatch.setattr(
        manifest, "set_registered",
        lambda base, model, vision: registered.update(
            base=base, model=model, vision=vision),
    )
    monkeypatch.setattr(manifest, "set_active_model_id", lambda _mid: None)
    monkeypatch.setattr(orchestrator, "refresh_approved_bases", lambda: None)

    saved = {}

    def fake_save_credentials(**kwargs):
        saved.update(kwargs)
        kwargs["on_done"](True, {"byok_active": True}, None)

    monkeypatch.setattr(byok_client, "save_credentials", fake_save_credentials)

    finished = {}
    wm = SimpleNamespace(byok_form_local_model="qwen3.5-4b")
    started, err = local_provider.save_managed(
        wm, on_done=lambda ok, data, e: finished.update(ok=ok),
    )

    assert (started, err) == (True, None)
    assert saved["provider"] == "local"
    assert saved["model"] == "qwen3.5-4b"
    assert saved["api_key"] == "manifest-token"
    assert saved["base_url"] == "http://127.0.0.1:11500"
    assert saved["supports_vision"] is True  # qwen3.5-4b is a vision model
    assert registered == {
        "base": "http://127.0.0.1:11500", "model": "qwen3.5-4b", "vision": True,
    }
    assert finished["ok"] is True


def test_save_custom_rejects_non_local_base():
    wm = SimpleNamespace(
        byok_form_local_custom_base="https://api.evil.example",
        byok_form_local_custom_model="m",
        byok_form_local_custom_key="",
    )
    started, err = local_provider.save_custom_async(wm, on_done=lambda *_a: None)
    assert started is False
    assert "local" in err.lower()


# ---------------------------------------------------------------------------
# Save gating + dialog dispatch
#
# Gating deliberately lives in execute(), not poll(): an invalid form
# routes to the ERROR state with an actionable message instead of a
# silently disabled Save button. poll() only guards in-flight requests.
# ---------------------------------------------------------------------------


def _local_context(**extra):
    wm = SimpleNamespace(
        byok_dialog_state="IDLE",
        byok_form_provider="local",
        byok_form_local_mode="MANAGED",
        byok_form_local_model="qwen3.5-4b",
        byok_form_local_custom_base="",
        byok_form_local_custom_model="",
        byok_form_local_custom_key="",
        byok_form_api_key="",
        byok_last_error="",
    )
    for key, value in extra.items():
        setattr(wm, key, value)
    return SimpleNamespace(window_manager=wm), wm


def test_save_execute_managed_errors_until_server_healthy(monkeypatch):
    context, wm = _local_context()
    monkeypatch.setattr(server_supervisor, "is_healthy", lambda: False)
    monkeypatch.setattr(server_supervisor, "current", lambda: None)

    # Save is clickable (poll only guards in-flight requests) and the
    # unhealthy server routes to ERROR with the actionable message.
    assert byok_ops.MIXAR_BYOK_OT_save.poll(context) is True
    assert byok_ops.MIXAR_BYOK_OT_save().execute(context) == {'CANCELLED'}
    assert wm.byok_dialog_state == 'ERROR'
    assert "Start the local model" in wm.byok_last_error


def test_save_execute_custom_requires_base_and_model():
    context, wm = _local_context(byok_form_local_mode="CUSTOM")
    assert byok_ops.MIXAR_BYOK_OT_save().execute(context) == {'CANCELLED'}
    assert wm.byok_dialog_state == 'ERROR'
    assert "Base URL and model" in wm.byok_last_error


def test_save_poll_blocks_while_request_in_flight():
    for busy in ('SAVING', 'REMOVING'):
        context, _wm = _local_context(byok_dialog_state=busy)
        assert byok_ops.MIXAR_BYOK_OT_save.poll(context) is False
        assert byok_ops.MIXAR_BYOK_OT_save().execute(context) == {'CANCELLED'}


def test_save_execute_dispatches_local(monkeypatch):
    context, wm = _local_context(byok_form_local_mode="CUSTOM")
    wm.byok_form_local_custom_base = "http://127.0.0.1:11434"
    wm.byok_form_local_custom_model = "qwen3:4b"
    calls = {}
    monkeypatch.setattr(
        byok_local_ops.local_provider, "save_custom_async",
        lambda _wm, on_done: calls.update(on_done=on_done) or (True, None),
    )
    result = byok_ops.MIXAR_BYOK_OT_save().execute(context)
    assert result == {'FINISHED'}
    assert wm.byok_dialog_state == 'SAVING'
    assert callable(calls["on_done"])


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------


def test_is_managed_registration():
    assert orchestrator.is_managed_registration({
        "base_url": "http://127.0.0.1:11500", "model_id": "qwen3.5-4b",
        "supports_vision": True,
    }) is True
    # Custom server (not a catalog model on our loopback base).
    assert orchestrator.is_managed_registration({
        "base_url": "http://127.0.0.1:11434", "model_id": "qwen3:4b-ollama",
        "supports_vision": False,
    }) is False
    assert orchestrator.is_managed_registration(None) is False


# ---------------------------------------------------------------------------
# Custom save path: the vision probe decides what gets stored
#
# A custom base is not in the managed catalog, so detect.probe_vision asks
# the server itself. Three rules matter: the probe runs only when the user
# left the choice automatic, its answer lands in both the credential and the
# manifest snapshot, and an inconclusive answer stays text-only.
# ---------------------------------------------------------------------------


def _custom_wm(**extra):
    wm = SimpleNamespace(
        byok_form_local_custom_base="http://127.0.0.1:8181",
        byok_form_local_custom_model="qwen3.5-9b",
        byok_form_local_custom_key="",
        byok_form_local_custom_vision=False,
        byok_form_local_custom_vision_auto=True,
    )
    for key, value in extra.items():
        setattr(wm, key, value)
    return wm


def _save_custom(monkeypatch, probe_result, **wm_extra):
    """Run a custom save inline; returns (saved, registered, finished, wm)."""
    monkeypatch.setattr(local_provider.threading, "Thread", InlineThread)
    monkeypatch.setattr(
        local_provider, "_schedule_on_main",
        lambda callback, *args: callback(*args),
    )
    monkeypatch.setattr(local_provider, "_ping_models_endpoint", lambda _base: None)
    monkeypatch.setattr(orchestrator, "refresh_approved_bases", lambda: None)

    probe_calls = []

    def fake_probe(base_url, model, api_key=None):
        probe_calls.append((base_url, model, api_key))
        if isinstance(probe_result, Exception):
            raise probe_result
        return probe_result

    monkeypatch.setattr(detect, "probe_vision", fake_probe)

    saved, registered, finished = {}, {}, {}

    def fake_save_credentials(**kwargs):
        saved.update(kwargs)
        kwargs["on_done"](True, {"byok_active": True}, None)

    monkeypatch.setattr(byok_client, "save_credentials", fake_save_credentials)
    monkeypatch.setattr(
        manifest, "set_registered",
        lambda base, model, vision: registered.update(
            base=base, model=model, vision=vision),
    )

    wm = _custom_wm(**wm_extra)
    started, err = local_provider.save_custom_async(
        wm, on_done=lambda ok, data, e: finished.update(ok=ok, err=e),
    )
    assert (started, err) == (True, None)
    return saved, registered, finished, probe_calls


def test_custom_save_stores_probe_yes(monkeypatch):
    saved, registered, finished, probe_calls = _save_custom(monkeypatch, True)
    assert saved["supports_vision"] is True
    assert saved["base_url"] == "http://127.0.0.1:8181"
    assert saved["model"] == "qwen3.5-9b"
    assert saved["api_key"] is None  # blank key stays absent, not ""
    assert registered == {
        "base": "http://127.0.0.1:8181", "model": "qwen3.5-9b", "vision": True,
    }
    assert finished["ok"] is True
    assert probe_calls == [("http://127.0.0.1:8181", "qwen3.5-9b", None)]


def test_custom_save_stores_probe_no(monkeypatch):
    saved, registered, _finished, _calls = _save_custom(monkeypatch, False)
    assert saved["supports_vision"] is False
    assert registered["vision"] is False


def test_custom_save_without_an_answer_stays_text_only(monkeypatch):
    """Unknown must never become True — the safe direction is text-only."""
    saved, registered, finished, _calls = _save_custom(monkeypatch, None)
    assert saved["supports_vision"] is False
    assert registered["vision"] is False
    assert finished["ok"] is True  # an undecided probe never fails a save


def test_custom_save_treats_a_crashing_probe_as_unknown(monkeypatch):
    saved, _registered, finished, _calls = _save_custom(
        monkeypatch, RuntimeError("probe blew up"))
    assert saved["supports_vision"] is False
    assert finished["ok"] is True


def test_custom_save_probe_forwards_the_api_key(monkeypatch):
    _saved, _registered, _finished, calls = _save_custom(
        monkeypatch, True, byok_form_local_custom_key="secret")
    assert calls == [("http://127.0.0.1:8181", "qwen3.5-9b", "secret")]


@pytest.mark.parametrize("checked,expected", [(True, True), (False, False)])
def test_custom_save_manual_checkbox_overrides_the_probe(monkeypatch, checked, expected):
    """Manual wins both ways — and then the server is never asked."""
    saved, registered, _finished, calls = _save_custom(
        monkeypatch, not expected,
        byok_form_local_custom_vision=checked,
        byok_form_local_custom_vision_auto=False,
    )
    assert saved["supports_vision"] is expected
    assert registered["vision"] is expected
    assert calls == []


def test_custom_save_skips_the_probe_when_the_server_is_unreachable(monkeypatch):
    monkeypatch.setattr(local_provider.threading, "Thread", InlineThread)
    monkeypatch.setattr(
        local_provider, "_schedule_on_main",
        lambda callback, *args: callback(*args),
    )
    monkeypatch.setattr(
        local_provider, "_ping_models_endpoint",
        lambda _base: "Could not reach the local server.",
    )

    def explode(*_args, **_kwargs):
        raise AssertionError("must not probe an unreachable server")

    monkeypatch.setattr(detect, "probe_vision", explode)
    monkeypatch.setattr(
        byok_client, "save_credentials",
        lambda **kwargs: pytest.fail("must not store credentials"),
    )

    finished = {}
    started, err = local_provider.save_custom_async(
        _custom_wm(), on_done=lambda ok, data, e: finished.update(ok=ok, err=e))
    assert (started, err) == (True, None)
    assert finished["ok"] is False
    assert "reach" in finished["err"]


def test_dialog_prefill_mirrors_the_stored_vision_flag(monkeypatch):
    """Opening the dialog shows what is actually stored, then re-detects.

    The checkbox is a mirror of the credential, not an edit of it: auto is
    reset so the next save asks the server again rather than trusting a
    choice made in a previous session.
    """
    monkeypatch.setattr(local_provider, "refresh_model_items", lambda: None)
    monkeypatch.setattr(local_provider, "refresh_detected_async", lambda: None)

    def prefill(reg):
        monkeypatch.setattr(manifest, "get_registered", lambda: reg)
        wm = SimpleNamespace(byok_form_local_mode="MANAGED",
                             byok_form_local_model="NONE")
        byok_local_ops.prepare_dialog(wm)
        return wm

    stored = prefill({
        "base_url": "http://127.0.0.1:8181",
        "model_id": "Qwen2.5-VL-7B-Instruct",  # not a catalog model id
        "supports_vision": True,
    })
    assert stored.byok_form_local_mode == "CUSTOM"
    assert stored.byok_form_local_custom_base == "http://127.0.0.1:8181"
    assert stored.byok_form_local_custom_model == "Qwen2.5-VL-7B-Instruct"
    assert stored.byok_form_local_custom_vision is True
    assert stored.byok_form_local_custom_vision_auto is True

    text_only = prefill({
        "base_url": "http://127.0.0.1:8181",
        "model_id": "Qwen2.5-VL-7B-Instruct",
        "supports_vision": False,
    })
    assert text_only.byok_form_local_custom_vision is False

    managed = prefill({
        "base_url": "http://127.0.0.1:11500", "model_id": "qwen3.5-4b",
        "supports_vision": True,
    })
    assert managed.byok_form_local_mode == "MANAGED"
    assert not hasattr(managed, "byok_form_local_custom_vision")
