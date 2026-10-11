# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK keys kept on this computer.

The key lives in the OS keychain (``key_vault``), never goes to the backend
(``device_save``), and is added by this app only to requests for the
provider's fixed API host (``cloud_relay``). Codex reads the Codex CLI login
in place (``codex_cli_login``).
"""

import base64
import json
import sys
import time
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok import constants
from mixar.modules.byok.core import (
    cloud_relay,
    codex_cli_login,
    device_save,
    key_vault,
)


def _jwt(claims: dict) -> str:
    def seg(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    return f"{seg(b'{}')}.{seg(json.dumps(claims).encode())}.sig"


# ---------------------------------------------------------------------------
# key_vault
# ---------------------------------------------------------------------------

def test_keys_are_scoped_per_account_and_provider(byok_device_keys, monkeypatch):
    assert key_vault.store_key("openai", "sk-one-xxxxxxxxxxxxxxxx")
    assert key_vault.get_key("openai") == "sk-one-xxxxxxxxxxxxxxxx"
    assert key_vault.get_key("anthropic") == ""
    monkeypatch.setattr(key_vault, "_account_scope", lambda: "other")
    assert key_vault.get_key("openai") == ""  # another account sees nothing


def test_no_account_means_no_keychain_access(byok_device_keys, monkeypatch):
    monkeypatch.setattr(key_vault, "_account_scope", lambda: None)
    assert key_vault.store_key("openai", "sk-xxxxxxxxxxxxxxxxxxxx") is False
    assert byok_device_keys == {}


def test_account_scope_hashes_the_email(monkeypatch):
    from mixar.modules.space_mixie_chat.core import account_identity

    monkeypatch.setattr(account_identity, "_email", "Ada@Example.com")
    scope = key_vault._account_scope()
    assert scope and "ada" not in scope and len(scope) == 16


def test_only_known_providers_are_stored(byok_device_keys):
    assert key_vault.store_key("codex", "x" * 20) is False
    assert key_vault.store_key("evil", "x" * 20) is False


def test_delete_all_except_keeps_one(byok_device_keys):
    key_vault.store_key("openai", "a" * 20)
    key_vault.store_key("anthropic", "b" * 20)
    key_vault.delete_all_except("anthropic")
    assert key_vault.get_key("openai") == ""
    assert key_vault.get_key("anthropic") == "b" * 20


def test_mask_never_reveals_the_key():
    key = "sk-ant-api03-" + "q" * 40 + "WXYZ"
    label = key_vault.mask(key)
    assert label.endswith("WXYZ") and len(label) <= 40 and "q" * 5 not in label
    assert key_vault.mask("shortkey12345") == "••••"


# ---------------------------------------------------------------------------
# cloud_relay
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, body=b'{"ok": true}', status=200,
                 headers=(("Content-Type", "application/json"), ("Set-Cookie", "x"))):
        self._body, self.status = body, status
        self.headers = dict(headers)

    def read(self, n=-1):
        return self._body

    def getcode(self):
        return self.status

    def close(self):
        pass


@pytest.fixture
def fake_urlopen(monkeypatch):
    calls = []

    def _open(request, timeout=None):
        calls.append(request)
        return _Response()

    monkeypatch.setattr(cloud_relay, "_urlopen", _open)
    return calls


def _run(params):
    out = []
    cloud_relay.handle_credential_request(params, out.append)
    assert len(out) == 1
    return out[0]


def _params(provider, url, method="POST", headers=None):
    return {
        "credential": {"provider": provider}, "url": url, "method": method,
        "headers": headers or {}, "body": "{}",
    }


@pytest.mark.parametrize("provider,url,header,value", [
    ("anthropic", "https://api.anthropic.com/v1/messages", "X-api-key", "KEY"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
     "X-goog-api-key", "KEY"),
    ("openai", "https://api.openai.com/v1/chat/completions", "Authorization", "Bearer KEY"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "Authorization", "Bearer KEY"),
    ("kimi", "https://api.moonshot.ai/v1/chat/completions", "Authorization", "Bearer KEY"),
    ("fugu", "https://api.sakana.ai/v1/responses", "Authorization", "Bearer KEY"),
])
def test_relay_adds_the_providers_key(byok_device_keys, fake_urlopen, provider, url, header, value):
    key_vault.store_key(provider, "KEY")
    result = _run(_params(provider, url, headers={
        "Authorization": "Bearer mixar-device-held-key", "x-api-key": "placeholder",
        "Cookie": "c", "Content-Type": "application/json", "anthropic-version": "2023-06-01",
    }))
    assert result["status_code"] == 200
    request = fake_urlopen[0]
    assert request.get_header(header) == value
    sent = {k.lower(): v for k, v in request.header_items()}
    assert "cookie" not in sent
    assert "placeholder" not in json.dumps(sent)
    assert "mixar-device-held-key" not in json.dumps(sent)
    assert sent["content-type"] == "application/json"
    # Response headers are allowlisted.
    assert result["headers"] == {"content-type": "application/json"}


@pytest.mark.parametrize("provider,url,method", [
    ("openai", "https://evil.example/v1/chat/completions", "POST"),
    ("openai", "http://api.openai.com/v1/chat/completions", "POST"),
    ("openai", "https://api.openai.com:444/v1/chat/completions", "POST"),
    ("openai", "https://api.openai.com/v1/x", "DELETE"),
    ("anthropic", "https://api.openai.com/v1/messages", "POST"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/models?key=1", "GET"),
    ("openai", "https://api.openai.com/v1/../../x", "POST"),
    ("codex", "https://chatgpt.com/backend-api/me", "GET"),
    ("unknown", "https://api.openai.com/v1/x", "POST"),
])
def test_relay_never_sends_a_key_elsewhere(byok_device_keys, fake_urlopen, provider, url, method):
    key_vault.store_key("openai", "KEY")
    result = _run(_params(provider, url, method))
    assert result["error"]["code"] == "relay_denied"
    assert fake_urlopen == []


def test_relay_without_a_saved_key_says_so(byok_device_keys, fake_urlopen):
    result = _run(_params("openai", "https://api.openai.com/v1/models", "GET"))
    assert result["error"]["code"] == "relay_no_key"
    assert fake_urlopen == []


def test_provider_errors_pass_through(byok_device_keys, monkeypatch):
    key_vault.store_key("openai", "KEY")

    def _open_err(request, timeout=None):
        err = urllib.error.HTTPError(request.full_url, 401, "no", {}, None)
        err.read = lambda n=-1: b'{"error": "bad key"}'
        err.headers = {"Content-Type": "application/json"}
        raise err

    monkeypatch.setattr(cloud_relay, "_urlopen", _open_err)
    result = _run(_params("openai", "https://api.openai.com/v1/models", "GET"))
    assert result["status_code"] == 401 and "bad key" in result["body"]


def test_transport_failures_never_echo_the_key(byok_device_keys, monkeypatch):
    key_vault.store_key("openai", "SECRETKEY")

    def _open(request, timeout=None):
        raise OSError(f"boom {request.get_header('Authorization')}")

    monkeypatch.setattr(cloud_relay, "_urlopen", _open)
    result = _run(_params("openai", "https://api.openai.com/v1/models", "GET"))
    assert result["error"]["code"] == "relay_transport"
    assert "SECRETKEY" not in json.dumps(result)


def test_redirects_are_refused():
    handler = cloud_relay._RefuseRedirects()
    assert handler.redirect_request(None, None, 302, "", {}, "https://evil.example") is None


def test_codex_uses_the_cli_login(fake_urlopen, monkeypatch):
    monkeypatch.setattr(codex_cli_login, "read", lambda: ("ACCESS", "ACCOUNT"))
    _run(_params("codex", "https://chatgpt.com/backend-api/codex/responses"))
    request = fake_urlopen[0]
    assert request.get_header("Authorization") == "Bearer ACCESS"
    assert request.get_header("Chatgpt-account-id") == "ACCOUNT"


def test_codex_without_a_login_says_so(fake_urlopen, monkeypatch):
    def _read():
        raise codex_cli_login.CodexLoginError(codex_cli_login.MSG_EXPIRED)

    monkeypatch.setattr(codex_cli_login, "read", _read)
    result = _run(_params("codex", "https://chatgpt.com/backend-api/codex/responses"))
    assert result["error"] == {"code": "relay_no_key", "message": codex_cli_login.MSG_EXPIRED}
    assert fake_urlopen == []


def test_local_requests_get_the_bearer_and_keep_local_checks(byok_device_keys, monkeypatch):
    from mixar.modules.local_models.core import relay

    seen = {}
    monkeypatch.setattr(relay, "handle_llm_request",
                        lambda params, respond: seen.update(params) or respond({"ok": 1}))
    key_vault.store_key("local", "LOCALTOKEN")
    _run({"credential": {"provider": "local"}, "url": "http://127.0.0.1:11434/v1/chat/completions",
          "method": "POST", "headers": {"authorization": "Bearer sk-noauth"}, "body": "{}"})
    assert seen["headers"] == {"Authorization": "Bearer LOCALTOKEN"}
    assert "credential" not in seen  # no loop back into the cloud relay


def test_local_falls_back_to_the_managed_server_token(byok_device_keys, monkeypatch):
    from mixar.modules.local_models.core import manifest, relay

    seen = {}
    monkeypatch.setattr(relay, "handle_llm_request",
                        lambda params, respond: seen.update(params) or respond({}))
    monkeypatch.setattr(manifest, "get_api_token", lambda: "MANAGED")
    _run({"credential": {"provider": "local"}, "url": "http://127.0.0.1:1/v1/chat/completions",
          "method": "POST", "headers": {}, "body": "{}"})
    assert seen["headers"]["Authorization"] == "Bearer MANAGED"


def test_relay_entry_point_dispatches_credential_requests(monkeypatch):
    from mixar.modules.local_models.core import relay

    seen = []
    monkeypatch.setattr(cloud_relay, "handle_credential_request",
                        lambda params, respond: seen.append(params))
    relay.handle_llm_request({"credential": {"provider": "openai"}}, lambda r: None)
    assert seen == [{"credential": {"provider": "openai"}}]


def test_targets_match_the_backend_table():
    # Kept in lockstep with the backend's device_key_relay.PROVIDER_TARGETS.
    assert constants.CLOUD_RELAY_TARGETS == {
        "anthropic": ("api.anthropic.com", "/v1/"),
        "openai": ("api.openai.com", "/v1/"),
        "gemini": ("generativelanguage.googleapis.com", "/v1beta/"),
        "fugu": ("api.sakana.ai", "/v1/"),
        "kimi": ("api.moonshot.ai", "/v1/"),
        "openrouter": ("openrouter.ai", "/api/v1/"),
        "codex": ("chatgpt.com", "/backend-api/codex/"),
    }


def test_handshake_advertises_device_keys():
    source = (SCRIPTS / "mixar/modules/space_mixie_chat/core/socket_connection.py").read_text()
    assert '"byok_device_keys"' in source
    assert constants.DEVICE_KEY_CAPABILITY == "byok_device_keys"


# ---------------------------------------------------------------------------
# codex_cli_login
# ---------------------------------------------------------------------------

def test_codex_login_parse_reads_token_and_account():
    access = _jwt({"exp": time.time() + 3600})
    id_token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acc-1"}})
    text = json.dumps({"OPENAI_API_KEY": None,
                       "tokens": {"access_token": access, "id_token": id_token,
                                  "refresh_token": "r"}})
    assert codex_cli_login.parse(text) == (access, "acc-1")


def test_codex_login_parse_refuses_expired_tokens():
    access = _jwt({"exp": time.time() + 30})
    text = json.dumps({"tokens": {"access_token": access, "account_id": "a"}})
    with pytest.raises(codex_cli_login.CodexLoginError) as e:
        codex_cli_login.parse(text)
    assert str(e.value) == codex_cli_login.MSG_EXPIRED


def test_codex_login_parse_refuses_api_key_only_logins():
    with pytest.raises(codex_cli_login.CodexLoginError):
        codex_cli_login.parse(json.dumps({"OPENAI_API_KEY": "sk-x", "tokens": None}))


def test_codex_login_honours_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert codex_cli_login.auth_path() == str(tmp_path / "auth.json")
    with pytest.raises(codex_cli_login.CodexLoginError):
        codex_cli_login.read()


# ---------------------------------------------------------------------------
# device_save
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_put(monkeypatch):
    calls = []

    def _save(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(device_save.byok_client, "save_credentials", _save)
    return calls


def test_save_keeps_the_key_local_and_sends_only_a_label(byok_device_keys, fake_put):
    done = []
    assert device_save.save("anthropic", "claude-x", " sk-ant-" + "k" * 30 + " ",
                            lambda *a: done.append(a)) is None
    put = fake_put[0]
    assert put["api_key"] is None and put["key_location"] == "device"
    assert put["instance_id"] == "conn-1"
    assert put["key_preview"].endswith("kkkk") and "k" * 10 not in put["key_preview"]
    assert key_vault.get_key("anthropic") == "sk-ant-" + "k" * 30
    put["on_done"](True, {}, None)
    assert done == [(True, {}, None)]


def test_failed_save_restores_the_previous_key(byok_device_keys, fake_put):
    key_vault.store_key("openai", "old-key-xxxxxxxxxxxx")
    device_save.save("openai", "gpt-5", "new-key-xxxxxxxxxxxx", lambda *a: None)
    fake_put[0]["on_done"](False, None, "rejected")
    assert key_vault.get_key("openai") == "old-key-xxxxxxxxxxxx"


def test_failed_first_save_leaves_nothing_behind(byok_device_keys, fake_put):
    device_save.save("openai", "gpt-5", "new-key-xxxxxxxxxxxx", lambda *a: None)
    fake_put[0]["on_done"](False, None, "rejected")
    assert byok_device_keys == {}


def test_successful_save_prunes_other_providers(byok_device_keys, fake_put):
    key_vault.store_key("openai", "old-openai-xxxxxxxxx")
    device_save.save("anthropic", "claude-x", "new-anthropic-xxxxxx", lambda *a: None)
    fake_put[0]["on_done"](True, {}, None)
    assert key_vault.get_key("openai") == ""
    assert key_vault.get_key("anthropic") == "new-anthropic-xxxxxx"


def test_codex_save_needs_a_cli_login_and_stores_nothing(byok_device_keys, fake_put, monkeypatch):
    def _missing():
        raise codex_cli_login.CodexLoginError(codex_cli_login.MSG_NOT_FOUND)

    monkeypatch.setattr(codex_cli_login, "read", _missing)
    assert device_save.save("codex", "gpt-5.5", "", lambda *a: None) == codex_cli_login.MSG_NOT_FOUND
    assert fake_put == []
    monkeypatch.setattr(codex_cli_login, "read", lambda: ("a", "b"))
    assert device_save.save("codex", "gpt-5.5", "", lambda *a: None) is None
    assert fake_put[0]["key_location"] == "device" and fake_put[0]["key_preview"] is None
    assert byok_device_keys == {}


def test_save_needs_the_app_connection(byok_device_keys, fake_put, monkeypatch):
    monkeypatch.setattr(device_save, "_app_connection_id", lambda: None)
    assert device_save.save("openai", "gpt-5", "k" * 20, lambda *a: None) == device_save.MSG_CONNECT
    assert fake_put == [] and byok_device_keys == {}


def test_save_refuses_when_the_keychain_does(byok_device_keys, fake_put, monkeypatch):
    monkeypatch.setattr(key_vault, "store_key", lambda *a: False)
    assert device_save.save("openai", "gpt-5", "k" * 20, lambda *a: None) == device_save.MSG_KEYCHAIN
    assert fake_put == []


def test_keyless_local_save_drops_an_old_bearer(byok_device_keys, fake_put):
    key_vault.store_key("local", "old-bearer-xxxxxxxxx")
    device_save.save("local", "llama3", "", lambda *a: None,
                     base_url="http://127.0.0.1:11434", supports_vision=False)
    assert fake_put[0]["base_url"] == "http://127.0.0.1:11434"
    fake_put[0]["on_done"](True, {}, None)
    assert byok_device_keys == {}
