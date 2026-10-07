# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vision-capability probe (detect.probe_vision) — functional coverage.

The probe decides whether Mixar may send 3D screenshots to a custom local
model, so the cases that matter are the ones where a server gives no usable
answer: those must land on None (inconclusive), never on a wrong False.
``detect._urlopen`` is the seam — no sockets, every answer canned.
"""

import base64
import io
import json
import urllib.error
from urllib.parse import urlsplit

import pytest

from mixar.modules.local_models.core import detect

BASE = "http://127.0.0.1:8181"
MODEL = "qwen3.5-9b"
CHAT = "/v1/chat/completions"
DETAIL = f"/v1/models/{MODEL}"
PROPS = "/props"
SHOW = "/api/show"


class FakeResponse:
    """Minimal urlopen response: context-managed, like the real thing."""

    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, n=-1):
        return self._body if n in (-1, None) else self._body[:n]

    def getcode(self):
        return self.status


class UnreadableBody(io.BytesIO):
    """An error body that explodes when read — some servers/proxies do this."""

    def read(self, n=-1):
        raise OSError("connection reset")


def install_server(monkeypatch, routes=None, unreadable_paths=()):
    """Route ``detect._urlopen`` to canned answers; returns the request log.

    ``routes`` maps a URL path to ``(status, body)``; paths with no entry
    raise URLError, which is what a closed port or missing endpoint looks
    like. Statuses >= 400 are raised as HTTPError, as urllib would.
    """
    table = dict(routes or {})
    log = []

    def opener(request, timeout=None):
        path = urlsplit(request.full_url).path
        log.append({
            "path": path,
            "url": request.full_url,
            "method": request.get_method(),
            "body": json.loads(request.data) if request.data else None,
            "auth": request.get_header("Authorization"),
        })
        if path in unreadable_paths:
            raise urllib.error.HTTPError(
                request.full_url, 500, "boom", {}, UnreadableBody())
        answer = table.get(path)
        if answer is None:
            raise urllib.error.URLError(f"no route for {path}")
        status, body = answer
        if status >= 400:
            payload = b"" if body is None else json.dumps(body).encode()
            raise urllib.error.HTTPError(
                request.full_url, status, "rejected", {}, io.BytesIO(payload))
        return FakeResponse(body, status)

    monkeypatch.setattr(detect, "_urlopen", opener)
    return log



# ---------------------------------------------------------------------------
# Primary signal: send a 1x1 image and read the reaction
# ---------------------------------------------------------------------------


def test_vision_server_answering_means_yes(monkeypatch):
    log = install_server(monkeypatch,
                         {CHAT: (200, {"choices": [{"message": {"content": "ok"}}]})})
    assert probe() is True
    assert [entry["path"] for entry in log] == [CHAT]  # one request, no fallbacks


def test_probe_payload_is_a_one_token_request_with_a_real_png(monkeypatch):
    log = install_server(monkeypatch, {CHAT: (200, {})})
    probe()
    payload = log[0]["body"]
    assert payload["model"] == MODEL
    assert payload["max_tokens"] == 1
    assert payload["stream"] is False
    parts = payload["messages"][0]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    data_url = parts[1]["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    png = base64.b64decode(data_url.split(",", 1)[1])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # a server must be able to decode it
    assert png[16:24] == b"\x00\x00\x00\x01\x00\x00\x00\x01"  # IHDR says 1x1


@pytest.mark.parametrize("status", [400, 404, 409, 415, 422])
def test_image_rejection_wording_decides_no(monkeypatch, status):
    install_server(monkeypatch, {CHAT: (status, {
        "error": {"message": "Error: model does not support image inputs"}})})
    assert probe() is False


@pytest.mark.parametrize("message", [
    "this model does not support image inputs",
    "requested capabilities do not support image input",
    "images are not supported by this model",
    "model is not a multimodal one",
    "no mmproj loaded for this model",
    "vision projector missing",
    "THIS MODEL DOES NOT SUPPORT IMAGES",
])
def test_rejection_wording_is_matched_loosely(monkeypatch, message):
    install_server(monkeypatch, {CHAT: (400, {"error": {"message": message}})})
    assert probe() is False


def test_unrelated_rejection_proves_nothing(monkeypatch):
    """A 400 about something else (bad parameter) is not a vision answer."""
    install_server(monkeypatch, {CHAT: (400, {
        "error": {"message": "max_tokens must be <= 4096"}})})
    assert probe() is None


@pytest.mark.parametrize("status", [401, 403])
def test_auth_wall_proves_nothing(monkeypatch, status):
    install_server(monkeypatch, {CHAT: (status, {"error": {"message": "unauthorized"}})})
    assert probe() is None


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error_proves_nothing(monkeypatch, status):
    install_server(monkeypatch, {CHAT: (status, {"error": {"message": "boom"}})})
    assert probe() is None


def test_unparseable_rejection_body_is_ignored(monkeypatch):
    install_server(monkeypatch, {CHAT: (400, None)})
    assert probe() is None


def test_error_body_that_cannot_be_read_is_ignored(monkeypatch):
    install_server(monkeypatch, unreadable_paths=(CHAT,))
    assert probe() is None


def test_transport_failure_proves_nothing(monkeypatch):
    install_server(monkeypatch, {})  # nothing answers at all
    assert probe() is None


def test_api_key_travels_as_bearer_only_when_given(monkeypatch):
    log = install_server(monkeypatch, {CHAT: (200, {})})
    probe(api_key="secret-token")
    assert log[0]["auth"] == "Bearer secret-token"
    log.clear()
    probe()
    assert log[0]["auth"] is None


@pytest.mark.parametrize("base,expected_url", [
    ("http://127.0.0.1:8181", "http://127.0.0.1:8181/v1/chat/completions"),
    ("http://127.0.0.1:8181/", "http://127.0.0.1:8181/v1/chat/completions"),
    ("http://127.0.0.1:8181/v1", "http://127.0.0.1:8181/v1/chat/completions"),
    ("http://127.0.0.1:8181/v1/", "http://127.0.0.1:8181/v1/chat/completions"),
])
def test_chat_endpoint_is_built_once(monkeypatch, base, expected_url):
    log = install_server(monkeypatch, {CHAT: (200, {})})
    probe(base=base)
    assert log[0]["url"] == expected_url  # never /v1/v1/...


@pytest.mark.parametrize("base", ["", "   ", None])
@pytest.mark.parametrize("model", ["", "   ", None])
def test_missing_base_or_model_asks_nothing(monkeypatch, base, model):
    log = install_server(monkeypatch, {CHAT: (200, {})})
    assert detect.probe_vision(base, model) is None
    assert log == []


# ---------------------------------------------------------------------------
# Fallback signals: capability metadata the server already publishes
# ---------------------------------------------------------------------------

NO_CHAT = {CHAT: (404, {"error": {"message": "not found"}})}


def test_llama_cpp_props_projector_means_yes(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, PROPS: (200, {"projector_path": "mmproj.gguf"})})
    assert probe() is True


def test_llama_cpp_props_without_projector_means_no(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, PROPS: (200, {"projector_path": ""})})
    assert probe() is False


def test_model_detail_modalities_decide(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, DETAIL: (200, {"supported_modalities": ["text", "image"]})})
    assert probe() is True


def test_model_detail_text_only_modalities_decide_no(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, DETAIL: (200, {"input_modalities": ["text"]})})
    assert probe() is False


def test_model_detail_projector_field_decides(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, DETAIL: (200, {"mmproj_file": "mmproj.gguf"})})
    assert probe() is True


def test_ollama_capabilities_decide(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, SHOW: (200, {"capabilities": ["completion", "vision"]})})
    assert probe() is True


def test_ollama_capabilities_without_vision_decide_no(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, SHOW: (200, {"capabilities": ["completion", "embedding"]})})
    assert probe() is False


def test_ollama_projector_in_model_info_decides(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, SHOW: (200, {"model_info": {"mmproj.projector": 1}})})
    assert probe() is True


def test_metadata_read_behind_an_auth_wall_proves_nothing(monkeypatch):
    """404 on the chat endpoint but the metadata reads answer 401."""
    install_server(monkeypatch, {CHAT: (404, {}), DETAIL: (401, {}), PROPS: (401, {}), SHOW: (401, {})})
    assert probe() is None


def test_garbage_metadata_is_ignored(monkeypatch):
    install_server(monkeypatch, {**NO_CHAT, DETAIL: (200, ["not", "a", "dict"]), PROPS: (200, "<html>")})
    assert probe() is None


def test_metadata_endpoint_never_reached_after_a_clear_yes(monkeypatch):
    log = install_server(monkeypatch, {CHAT: (200, {}), PROPS: (200, {"projector_path": "x"})})
    assert probe() is True
    assert [entry["path"] for entry in log] == [CHAT]


def test_slash_in_model_id_is_url_encoded(monkeypatch):
    detail_path = "/v1/models/ollama%2Fqwen3.5"  # quote(safe='') keeps the slash encoded
    log = install_server(monkeypatch, {
        CHAT: (404, {}), detail_path: (200, {"modalities": ["image"]})})
    assert probe(model="ollama/qwen3.5") is True
    assert detail_path in [entry["path"] for entry in log]


# ---------------------------------------------------------------------------
# Last resort: the model name (may only ever say yes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "qwen2.5-vl-7b", "llava-v1.6-mistral", "MiniCPM-V-2_6", "Pixtral-12B",
    "moondream2", "Phi-3.5-vision-instruct", "glm-4v:9b", "InternVL2-4B",
    "nanovlm-7b", "fuyu-8b", "qwen3.5-vl", "nv-vl-dense",
])
def test_vision_looking_name_rescues_an_inconclusive_probe(monkeypatch, name):
    install_server(monkeypatch, {})
    assert probe(model=name) is True


@pytest.mark.parametrize("name", [
    "qwen3.5-9b", "deepseek-r1-8b", "llama3.1-8b", "gemma3n-e4b",
    "phi4-reasoning", "mistral-nemo", "command-r", "nova2-mini",
])
def test_text_looking_name_stays_unknown(monkeypatch, name):
    install_server(monkeypatch, {})
    assert probe(model=name) is None


def test_a_clear_no_is_never_overridden_by_the_name(monkeypatch):
    """The server answered "no images"; a -vl in the name cannot undo that."""
    install_server(monkeypatch, {CHAT: (400, {
        "error": {"message": "no mmproj loaded, image inputs unsupported"}})})
    assert probe(model="qwen2.5-vl-7b") is False


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body,expected", [
    ("model does not support image inputs", True),
    ("Images Are NOT SUPPORTED", True),
    ("missing mmproj", True),
    ("vision projector required", True),
    ("multimodal projector missing", True),
    ("", False),
    ("invalid model name", False),
    (None, False),
])
def test_rejects_images(body, expected):
    assert detect._rejects_images(body) is expected


@pytest.mark.parametrize("value,expected", [
    (["text", "image"], True),
    (["vision"], True),
    (["completion", "embedding"], False),
    ("image", True),
    ({"image": True}, True),
    (["audio"], None),
    ([], None),
    (None, None),
    ("", None),
    (42, None),
])
def test_verdict_from_capabilities(value, expected):
    assert detect._verdict_from_capabilities(value) is expected


@pytest.mark.parametrize("base,expected", [
    ("http://127.0.0.1:8181", "http://127.0.0.1:8181/v1"),
    ("http://127.0.0.1:8181/", "http://127.0.0.1:8181/v1"),
    ("http://127.0.0.1:8181/v1", "http://127.0.0.1:8181/v1"),
    ("http://127.0.0.1:8181/v1/", "http://127.0.0.1:8181/v1"),
    ("", "/v1"),
])
def test_chat_base(base, expected):
    assert detect._chat_base(base) == expected


def test_authorization_header_only_when_a_key_exists():
    assert "Authorization" not in detect._request_headers(None)
    assert "Authorization" not in detect._request_headers("")
    assert detect._request_headers("tok")["Authorization"] == "Bearer tok"


def test_probe_never_raises_whatever_urlopen_does(monkeypatch):
    for boom in (RuntimeError("nope"), OSError("reset"),
                 urllib.error.URLError("nope")):
        def explode(request, timeout=None, _boom=boom):
            raise _boom()
        monkeypatch.setattr(detect, "_urlopen", explode)
        assert probe() is None


def probe(model=MODEL, base=BASE, **kwargs):
    return detect.probe_vision(base, model, **kwargs)
