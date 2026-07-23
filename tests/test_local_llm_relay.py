# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Security regression coverage for the client-side local LLM relay."""

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import local_llm_relay as relay


class _Response:
    status = 200
    headers = {"content-type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return b'{"choices": []}'


def test_target_is_pinned_to_exact_approved_chat_endpoint():
    approved = "http://localhost:11434"

    assert relay._target_matches_approval(
        "http://localhost:11434/v1/chat/completions", approved
    )
    assert not relay._target_matches_approval(
        "http://localhost:11435/v1/chat/completions", approved
    )
    assert not relay._target_matches_approval(
        "http://127.0.0.1:11434/v1/chat/completions", approved
    )
    assert not relay._target_matches_approval(
        "http://localhost:11434/v1/models", approved
    )
    assert not relay._target_matches_approval(
        "http://localhost:11434/v1/chat/completions?target=other", approved
    )


def test_v1_base_is_not_duplicated():
    assert relay._target_matches_approval(
        "http://localhost:1234/v1/chat/completions",
        "http://localhost:1234/v1",
    )
    assert not relay._target_matches_approval(
        "http://localhost:1234/v1/v1/chat/completions",
        "http://localhost:1234/v1",
    )


def test_metadata_link_local_address_is_not_an_allowed_model_host():
    assert not relay._is_local_host("169.254.169.254")
    assert relay._is_local_host("127.0.0.1")
    assert relay._is_local_host("192.168.1.20")


def test_relay_rejects_unapproved_method_and_target(monkeypatch):
    monkeypatch.setattr(relay, "get_approved_base_url", lambda: "http://localhost:11434")
    called = False

    def _open(*_args, **_kwargs):
        nonlocal called
        called = True
        return _Response()

    monkeypatch.setattr(relay._NO_REDIRECT_OPENER, "open", _open)

    wrong_method = relay.handle_llm_request({
        "url": "http://localhost:11434/v1/chat/completions",
        "method": "DELETE",
    })
    wrong_path = relay.handle_llm_request({
        "url": "http://localhost:11434/admin",
        "method": "POST",
    })

    assert wrong_method["status_code"] == 403
    assert wrong_path["status_code"] == 403
    assert not called


def test_relay_forwards_only_allowlisted_headers(monkeypatch):
    monkeypatch.setattr(relay, "get_approved_base_url", lambda: "http://localhost:11434")
    captured = {}

    def _open(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(relay._NO_REDIRECT_OPENER, "open", _open)
    result = relay.handle_llm_request({
        "url": "http://localhost:11434/v1/chat/completions",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer local-token",
            "Content-Type": "application/json",
            "X-Backend-Controlled": "must-not-pass",
            "Proxy-Authorization": "must-not-pass",
        },
        "body": "{}",
        "timeout": 9999,
    })

    sent_headers = {key.lower(): value for key, value in captured["request"].header_items()}
    assert result["status_code"] == 200
    assert sent_headers["authorization"] == "Bearer local-token"
    assert sent_headers["content-type"] == "application/json"
    assert "x-backend-controlled" not in sent_headers
    assert "proxy-authorization" not in sent_headers
    assert captured["timeout"] == relay._DEFAULT_TIMEOUT


def test_redirect_handler_never_follows_location():
    handler = relay._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://example.com") is None


def test_relay_byte_limits_match_backend_transport_contract():
    assert relay._MAX_REQUEST_BYTES == 16 * 1024 * 1024
    assert relay._MAX_RESPONSE_BYTES == 32 * 1024 * 1024


def test_relay_rejects_oversized_request_without_opening_target(monkeypatch):
    monkeypatch.setattr(relay, "get_approved_base_url", lambda: "http://localhost:11434")
    monkeypatch.setattr(relay, "_MAX_REQUEST_BYTES", 8)
    called = False

    def _open(*_args, **_kwargs):
        nonlocal called
        called = True
        return _Response()

    monkeypatch.setattr(relay._NO_REDIRECT_OPENER, "open", _open)
    result = relay.handle_llm_request({
        "url": "http://localhost:11434/v1/chat/completions",
        "method": "POST",
        "body": "123456789",
    })

    assert result["status_code"] == 413
    assert not called


def test_relay_stops_reading_oversized_local_response(monkeypatch):
    monkeypatch.setattr(relay, "get_approved_base_url", lambda: "http://localhost:11434")
    monkeypatch.setattr(relay, "_MAX_RESPONSE_BYTES", 8)

    class _OversizedResponse(_Response):
        def read(self, size=-1):
            return b"x" * size

    monkeypatch.setattr(
        relay._NO_REDIRECT_OPENER,
        "open",
        lambda *_args, **_kwargs: _OversizedResponse(),
    )
    result = relay.handle_llm_request({
        "url": "http://localhost:11434/v1/chat/completions",
        "method": "POST",
        "body": "{}",
    })

    assert result["status_code"] == 502


def test_endpoint_approval_is_persisted_locally(monkeypatch):
    values = {}
    fake_keyring = SimpleNamespace(
        get_password=lambda service, account: values.get((service, account)),
        set_password=lambda service, account, value: values.__setitem__((service, account), value),
        delete_password=lambda service, account: values.pop((service, account), None),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(relay, "_approved_base_url", None)

    saved, error = relay.store_approved_base_url("http://localhost:11434/")

    assert saved and error is None
    assert relay.get_approved_base_url() == "http://localhost:11434"
    relay.clear_approved_base_url()
    assert relay.get_approved_base_url() == ""
