# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A local filesystem path never leaves the machine as a model name.

An unaliased llama-server reports its ``.gguf`` path as the model id and as
every completion's ``model``; prod Langfuse recorded
``C:\\Users\\<name>\\AppData\\Roaming\\Mixar\\...\\*.gguf`` as a model. The
managed server is now started with ``--alias <model id>`` and every local
BYOK save sends a basename or alias, never a path.
"""

import io
import json
import os
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

from mixar.modules.byok.core import byok_client, local_provider
from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.services.agent_service import AgentService
from mixar.modules.local_models.core import (
    detect,
    manifest,
    relay,
    runtime,
    server_supervisor as sup,
)
from mixar.modules.local_models.core.model_name import (
    is_path_like,
    safe_model_name,
    safe_response_body,
)

WINDOWS_PATH = (
    "C:\\Users\\someone\\AppData\\Roaming\\Mixar\\Mixar\\5.0\\datafiles"
    "\\mixar/local_models\\models\\qwen3.6-27b\\Qwen3.6-27B-Q4_K_M.gguf"
)
BASENAME = "Qwen3.6-27B-Q4_K_M.gguf"


class InlineThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


# ---------------------------------------------------------------------------
# safe_model_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    WINDOWS_PATH,
    "C:/Users/someone/models/Qwen3.6-27B-Q4_K_M.gguf",
    "\\\\nas\\share\\Qwen3.6-27B-Q4_K_M.gguf",
    "/Users/someone/Library/Application Support/Mixar/Qwen3.6-27B-Q4_K_M.gguf",
    "~/models/Qwen3.6-27B-Q4_K_M.gguf",
    "./models/Qwen3.6-27B-Q4_K_M.gguf",
    "models/Qwen3.6-27B-Q4_K_M.gguf",
    "file:///home/someone/Qwen3.6-27B-Q4_K_M.gguf",
    '"C:/Users/someone/models/Qwen3.6-27B-Q4_K_M.gguf"',
    "'/Users/someone/models/Qwen3.6-27B-Q4_K_M.gguf'",
])
def test_paths_reduce_to_basename(path):
    assert is_path_like(path)
    assert safe_model_name(path) == BASENAME


@pytest.mark.parametrize("name", [
    BASENAME, "qwen3.6-27b", "llama3:8b", "qwen/qwen3-8b", "hf.co/user/repo:Q4_K_M",
    "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Llama-3.2-3B-Instruct-IQ3_M.gguf",
    "huggingface.co/user/repo:model.gguf",
    '"qwen/qwen3-8b"',
])
def test_model_ids_are_unchanged(name):
    assert safe_model_name(name) == name


@pytest.mark.parametrize("degenerate", ["C:\\", "/", "~", "file:///"])
def test_degenerate_paths_never_echo_the_input(degenerate):
    assert safe_model_name(degenerate) == "local-model"


@pytest.mark.parametrize("body", [
    "not JSON", "[]", '{"error": "unavailable"}', '{"model": 12}',
    '{ "model": "qwen/qwen3-8b", "choices": [] }',
])
def test_non_path_responses_are_unchanged(body):
    assert safe_response_body(body) == body


def test_response_sanitizing_preserves_generated_content():
    reply = {"model": WINDOWS_PATH, "choices": [{"message": {"content": WINDOWS_PATH}}]}
    returned = json.loads(safe_response_body(json.dumps(reply)))
    assert returned["model"] == BASENAME
    assert returned["choices"] == reply["choices"]


# ---------------------------------------------------------------------------
# Managed server: launched with the alias; the path stays in the argv
# ---------------------------------------------------------------------------

def test_argv_alias_is_the_model_id_not_the_path():
    argv = sup.build_server_argv(
        "/rt/llama-server", WINDOWS_PATH, 11500, "tok", alias="qwen3.6-27b",
    )
    assert argv[argv.index("--alias") + 1] == "qwen3.6-27b"
    assert argv[argv.index("-m") + 1] == WINDOWS_PATH


def test_start_server_passes_the_catalog_id_as_alias(monkeypatch):
    captured = {}

    def fake_argv(*args, **kwargs):
        captured.update(kwargs)
        return ["llama-server"]

    def refuse_spawn(*_a, **_k):
        raise OSError("not spawning in tests")

    monkeypatch.setattr(sup, "build_server_argv", fake_argv)
    monkeypatch.setattr(sup.subprocess, "Popen", refuse_spawn)
    monkeypatch.setattr(sup, "server_log_path", lambda: os.devnull)
    monkeypatch.setattr(runtime, "model_file_paths",
                        lambda _mid: {"gguf": WINDOWS_PATH, "mmproj": None})
    monkeypatch.setattr(runtime, "model_files_present", lambda _mid: True)
    monkeypatch.setattr(manifest, "get_port", lambda: None)
    monkeypatch.setattr(manifest, "set_port", lambda _p: None)
    monkeypatch.setattr(manifest, "get_api_token", lambda: "tok")
    monkeypatch.setattr(sup, "choose_port", lambda _pref: 11500)

    states = []
    sup.start_server("qwen3.6-27b", lambda s, d: states.append(s),
                     server_bin="/rt/llama-server")

    assert captured["alias"] == "qwen3.6-27b"
    assert states[-1] == "failed"  # the refused spawn, reported normally


# ---------------------------------------------------------------------------
# Detected apps: an unaliased llama.cpp server's path id is offered as basename
# ---------------------------------------------------------------------------

class _Resp(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_detect_offers_the_basename_of_an_unaliased_server(monkeypatch):
    body = json.dumps({"data": [{"id": WINDOWS_PATH}, {"id": "qwen/qwen3-8b"}]})
    monkeypatch.setattr(detect, "_urlopen",
                        lambda _url, timeout=None: _Resp(body.encode()))
    result = detect._probe_one("llama_cpp", 8080, 0.1)
    assert result["models"] == [BASENAME, "qwen/qwen3-8b"]


# ---------------------------------------------------------------------------
# Every local save sends a basename or alias
# ---------------------------------------------------------------------------

def _capture_payload(monkeypatch):
    service = AgentService.__new__(AgentService)
    captured = {}

    def fake_put(path, json=None, **_kw):
        captured["payload"] = json
        return APIResponse(success=True, status_code=200, data={"byok_active": True})

    service.put = fake_put
    monkeypatch.setattr(byok_client, "get_agent_service", lambda: service)
    monkeypatch.setattr(byok_client.threading, "Thread", InlineThread)
    monkeypatch.setattr(byok_client, "_schedule_on_main",
                        lambda callback, *args: callback(*args))
    # Transport sealing and the OS key store have their own suites. These
    # tests inspect the outgoing model without network or real credentials.
    from mixar.modules.byok.core import transport_seal
    monkeypatch.setattr(transport_seal, "seal", lambda _key: "sealed-test-key")
    monkeypatch.setattr(byok_client, "_store_local_key", lambda *_args: True)
    return captured


def test_local_save_never_sends_an_absolute_path(monkeypatch):
    captured = _capture_payload(monkeypatch)
    byok_client.save_credentials(
        provider="local", model=WINDOWS_PATH, api_key=None,
        base_url="http://127.0.0.1:11500", supports_vision=True,
        on_done=lambda *_a: None,
    )
    assert captured["payload"]["model"] == BASENAME
    assert "AppData" not in json.dumps(captured["payload"])


def test_cloud_save_model_is_untouched(monkeypatch):
    captured = _capture_payload(monkeypatch)
    byok_client.save_credentials(
        provider="openrouter", model="someone/model", api_key="sk-or-x",
        on_done=lambda *_a: None,
    )
    assert captured["payload"]["model"] == "someone/model"


def test_custom_save_sends_and_remembers_the_basename(monkeypatch):
    # The ping runs through byok_client's always-answering worker now.
    monkeypatch.setattr(byok_client.threading, "Thread", InlineThread)
    monkeypatch.setattr(byok_client, "_schedule_on_main",
                        lambda callback, *args: callback(*args))
    monkeypatch.setattr(local_provider, "_ping_models_endpoint", lambda _b: None)
    saved, registered = {}, {}

    def fake_save(**kwargs):
        saved.update(kwargs)
        kwargs["on_done"](True, {}, None)

    monkeypatch.setattr(byok_client, "save_credentials", fake_save)
    monkeypatch.setattr(manifest, "set_registered",
                        lambda base, model, vision: registered.update(model=model))
    from mixar.modules.local_models.core import orchestrator
    monkeypatch.setattr(orchestrator, "refresh_approved_bases", lambda: None)

    wm = SimpleNamespace(
        byok_form_local_custom_base="http://127.0.0.1:8080",
        byok_form_local_custom_model=WINDOWS_PATH,
        byok_form_local_custom_key="",
    )
    started, err = local_provider.save_custom_async(wm, on_done=lambda *_a: None)

    assert (started, err) == (True, None)
    assert saved["model"] == BASENAME
    assert registered["model"] == BASENAME


# ---------------------------------------------------------------------------
# A request by alias reaches the managed server
# ---------------------------------------------------------------------------

def test_relay_forwards_a_request_by_alias(monkeypatch):
    relay.set_approved_bases(["http://127.0.0.1:11500"])
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        reply = {"model": "qwen3.6-27b", "choices": [{"message": {"content": "ok"}}]}
        return _Resp(json.dumps(reply).encode())

    monkeypatch.setattr(relay, "_urlopen", opener)
    results = []
    try:
        relay.handle_llm_request({
            "method": "POST",
            "url": "http://127.0.0.1:11500/v1/chat/completions",
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"model": "qwen3.6-27b", "messages": []}),
        }, results.append)
    finally:
        relay.set_approved_bases([])

    assert seen["body"]["model"] == "qwen3.6-27b"
    assert results[0]["status_code"] == 200
    assert json.loads(results[0]["body"])["model"] == "qwen3.6-27b"


def test_relay_strips_the_model_path_in_custom_server_replies(monkeypatch):
    relay.set_approved_bases(["http://127.0.0.1:11500"])
    reply = {"model": WINDOWS_PATH, "choices": [{"message": {"content": "ok"}}]}
    monkeypatch.setattr(relay, "_urlopen", lambda *_a, **_k: _Resp(json.dumps(reply).encode()))
    results = []
    try:
        relay.handle_llm_request({
            "method": "POST", "url": "http://127.0.0.1:11500/v1/chat/completions",
            "body": json.dumps({"model": BASENAME, "messages": []}),
        }, results.append)
    finally:
        relay.set_approved_bases([])
    returned = json.loads(results[0]["body"])
    assert returned["model"] == BASENAME
    assert returned["choices"] == reply["choices"]
    assert "AppData" not in results[0]["body"]


# ---------------------------------------------------------------------------
# Opt-in: a real llama-server (MIXAR_TEST_LLAMA_SERVER + MIXAR_TEST_GGUF)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (os.environ.get("MIXAR_TEST_LLAMA_SERVER") and os.environ.get("MIXAR_TEST_GGUF")),
    reason="set MIXAR_TEST_LLAMA_SERVER and MIXAR_TEST_GGUF to run against llama-server",
)
@pytest.mark.parametrize("alias", ["tiny-test", None], ids=["managed-alias", "unaliased-custom"])
def test_real_llama_server_model_privacy(tmp_path, alias):
    import shutil
    import subprocess
    import time
    import urllib.request

    gguf_dir = tmp_path / "Users" / "someone" / "AppData" / "models"
    gguf_dir.mkdir(parents=True)
    gguf = gguf_dir / "Tiny-Test.gguf"
    shutil.copy(os.environ["MIXAR_TEST_GGUF"], gguf)
    port = sup.choose_port(None)
    argv = sup.build_server_argv(
        os.environ["MIXAR_TEST_LLAMA_SERVER"], str(gguf), port, "tok",
        ctx_size=512, alias=alias,
    )
    argv[argv.index("-ngl") + 1] = "0"
    if alias is None:
        # Reproduce a user-run server without Mixar's alias or API token.
        for option in ("--alias", "--api-key"):
            index = argv.index(option)
            del argv[index:index + 2]
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    headers = {"Authorization": "Bearer tok", "Content-Type": "application/json"}

    def call(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())

    try:
        for _ in range(60):
            try:
                call("/health")
                break
            except Exception:
                time.sleep(0.5)
        models = call("/v1/models")
        request = {
            "model": alias or gguf.name, "max_tokens": 8, "temperature": 0,
            "messages": [{"role": "user", "content": "hi"}],
        }
        reply = call("/v1/chat/completions", request)
        expected = alias or str(gguf)
        assert [m["id"] for m in models["data"]] == [expected]
        assert reply["model"] == expected
        assert reply["choices"] and reply["usage"]["completion_tokens"] > 0

        relay.set_approved_bases([base])
        results = []
        try:
            relay.handle_llm_request({
                "method": "POST", "url": base + "/v1/chat/completions",
                "headers": headers, "body": json.dumps(request),
            }, results.append)
        finally:
            relay.set_approved_bases([])
        assert results[0]["status_code"] == 200, results
        relayed = json.loads(results[0]["body"])
        assert relayed["model"] == (alias or gguf.name)
        assert relayed["usage"]["completion_tokens"] > 0
        assert "AppData" not in results[0]["body"]
        if alias is None:
            assert "AppData" in reply["model"]  # the real server reproduces the leak
            assert detect._probe_one("llama_cpp", port, 5)["models"] == [gguf.name]
        else:
            assert "AppData" not in json.dumps(models) + json.dumps(reply)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
