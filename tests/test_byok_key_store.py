# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The BYOK key lives on this device, scoped per Mixar user.

Pins the key-store record round trip against a fake credential store, the
per-user entry name (two accounts on one machine never share a key), the
Windows chunking of values past the Credential Manager blob limit, and the
save/delete wiring in `byok_client` — the server keeps metadata only, so
the 200 from PUT /agent/byok is what writes the key here, and the Codex
refresh token never leaves the machine.
"""

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import key_store
from mixar.modules.common.api.services import agent_service
from mixar.modules.common.utils import credential_store


class FakeStore:
    def __init__(self):
        self.entries = {}

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, value):
        self.entries[name] = value
        return True

    def delete(self, name):
        self.entries.pop(name, None)
        return True


def _patch_store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(credential_store, "_read_secret", fake.get)
    monkeypatch.setattr(credential_store, "get_secret", fake.get)
    monkeypatch.setattr(credential_store, "set_secret", fake.set)
    monkeypatch.setattr(credential_store, "delete_secret", fake.delete)
    credential_store.invalidate_cache()
    return fake


def _bundle(fake):
    return json.loads(fake.entries[credential_store.BUNDLE_ENTRY])["values"]


def _jwt(claims):
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


# --- user scope --------------------------------------------------------------

def test_user_id_is_the_mixar_token_sub_claim():
    assert key_store.user_id_from_token(_jwt({"sub": "user-123"})) == "user-123"
    assert key_store.user_id_from_token(_jwt({"email": "x"})) is None
    assert key_store.user_id_from_token("opaque") is None
    assert key_store.user_id_from_token(None) is None


def test_records_are_scoped_per_user(monkeypatch):
    fake = _patch_store(monkeypatch)
    key_store.save(key_store.make_record("openai", "sk-a"), user_id="alice")
    key_store.save(key_store.make_record("codex", "at-ignored", auth_path="/p/auth.json"), user_id="bob")
    # Both accounts live inside the ONE bundle entry: one Keychain item, one approval.
    assert set(fake.entries) == {credential_store.BUNDLE_ENTRY}
    assert set(_bundle(fake)) == {"byok:alice", "byok:bob"}
    assert key_store.load("alice")["key"] == "sk-a"
    bob = key_store.load("bob")
    assert (bob["provider"], bob["key"], bob["auth_path"], bob["expired_fingerprint"]) == (
        "codex", None, "/p/auth.json", None)
    assert "refresh_token" not in bob and "at-ignored" not in json.dumps(bob)
    assert key_store.load("carol") is None


def test_update_merges_and_delete_removes(monkeypatch):
    _patch_store(monkeypatch)
    key_store.save(key_store.make_record("codex", None, auth_path="/p/auth.json"), user_id="u")
    assert key_store.update({"expired_fingerprint": "abc"}, user_id="u")
    record = key_store.load("u")
    assert record["expired_fingerprint"] == "abc" and record["auth_path"] == "/p/auth.json"
    assert key_store.delete(user_id="u")
    assert key_store.load("u") is None
    assert key_store.update({"key": "x"}, user_id="u") is False


def test_an_earlier_builds_standalone_entry_is_moved_into_the_bundle(monkeypatch):
    fake = _patch_store(monkeypatch)
    fake.entries["BYOK:alice"] = json.dumps({"v": 2, "provider": "openai", "key": "sk-a"})
    assert key_store.load("alice")["key"] == "sk-a"
    assert "BYOK:alice" not in fake.entries and _bundle(fake)["byok:alice"]["key"] == "sk-a"
    # The bundle is cached: a second load reads nothing from the store.
    monkeypatch.setattr(credential_store, "_read_secret", lambda name: (_ for _ in ()).throw(AssertionError("store read")))
    assert key_store.load("alice")["key"] == "sk-a"
    # Logout drops the cache so the next sign-in reads the store afresh.
    key_store.forget_user()
    monkeypatch.setattr(credential_store, "_read_secret", fake.get)
    assert key_store.load("alice")["key"] == "sk-a"


def test_unreadable_or_foreign_records_read_as_absent(monkeypatch):
    fake = _patch_store(monkeypatch)
    fake.entries["BYOK:u"] = "{not json"          # a broken legacy entry is dropped
    assert key_store.load("u") is None
    credential_store.set_value("byok:u", {"key": "no provider"})
    assert key_store.load("u") is None


def test_the_user_scope_follows_the_access_token_without_a_logout(monkeypatch):
    """A re-login as another account that skipped Logout (session expired →
    re-login, a pair adopted from another process) must never read or write
    the first account's record: the id is derived from the token every call."""
    from mixar.modules.auth.core import auth

    token = {"value": _jwt_for("alice")}
    monkeypatch.setattr(auth, "get_access_token", lambda: token["value"])
    assert key_store.current_user_id() == "alice"
    token["value"] = _jwt_for("bob")                 # no forget_user() in between
    assert key_store.current_user_id() == "bob"
    token["value"] = ""
    assert key_store.current_user_id() is None
    token["value"] = _jwt_for("alice")
    assert key_store.current_user_id() == "alice"


def _jwt_for(sub):
    seg = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{seg({'alg': 'none'})}.{seg({'sub': sub})}.sig"


def test_no_signed_in_user_means_no_write(monkeypatch):
    fake = _patch_store(monkeypatch)
    monkeypatch.setattr(key_store, "current_user_id", lambda: None)
    assert key_store.save(key_store.make_record("openai", "k")) is False
    assert fake.entries == {}


# --- Windows chunking ------------------------------------------------------------

class FakeWinCreds:
    def __init__(self):
        self.targets = {}

    def get(self, target):
        return self.targets.get(target, "")

    def set(self, target, username, value):
        assert len(value.encode("utf-8")) <= 2560, "over the Credential Manager blob limit"
        self.targets[target] = value
        return True

    def delete(self, target):
        self.targets.pop(target, None)
        return True


def test_windows_values_past_the_blob_limit_are_chunked_and_reassembled(monkeypatch):
    creds = FakeWinCreds()
    monkeypatch.setattr(credential_store, "_IS_WINDOWS", True)
    from mixar.modules.common.utils import credential_store_win

    monkeypatch.setattr(credential_store_win, "_helpers", lambda: (creds.get, creds.set, creds.delete))

    big = "é" * 3000 + "x" * 3000  # 9 000 bytes UTF-8, multi-byte boundaries
    assert credential_store.set_secret("BYOK:u", big)
    assert len(creds.targets) > 1
    assert credential_store.get_secret("BYOK:u") == big

    # Shrinking the value removes the stale tail chunks.
    assert credential_store.set_secret("BYOK:u", "small")
    assert creds.targets == {"BYOK:u@MixarSafeStorage": "small"}
    assert credential_store.get_secret("BYOK:u") == "small"

    assert credential_store.set_secret("BYOK:u", big)
    assert credential_store.delete_secret("BYOK:u")
    assert creds.targets == {}
    assert credential_store.get_secret("BYOK:u") is None


# --- save / delete wiring ------------------------------------------------------

def test_put_payload_carries_account_id_only_when_given():
    sent = {}

    class Service(agent_service.AgentService):
        def __init__(self):
            pass

        def put(self, path, json=None, **_):
            sent["path"], sent["json"] = path, json
            return "resp"

    Service().save_credentials_all("codex", "gpt-5", "access-token", account_id="acct")
    assert sent["json"] == {"provider": "codex", "model": "gpt-5", "api_key": "access-token",
                            "account_id": "acct"}
    Service().save_credentials_all("openai", "gpt-5", "sk")
    assert sent["json"] == {"provider": "openai", "model": "gpt-5", "api_key": "sk"}
    Service().save_credentials_all("local", "llama", None, base_url="http://127.0.0.1:1")
    assert "api_key" not in sent["json"] and "account_id" not in sent["json"]


def test_byok_client_stores_the_key_locally_on_200_and_never_sends_the_refresh_token():
    src = (SCRIPTS / "mixar" / "modules" / "byok" / "core" / "byok_client.py").read_text(encoding="utf-8")
    save_body = src[src.index("def save_credentials("):src.index("def _put_sealed(")]
    # The PUT itself lives in `_put_sealed`: the key goes out SEALED, the
    # Codex file reference never goes out at all.
    put_body = src[src.index("def _put_sealed("):src.index("def error_code(")]
    assert "account_id=account_id," in put_body and "api_key=envelope," in put_body
    assert "codex_auth_path" not in put_body
    assert "refresh_token" not in save_body and "refresh_token" not in put_body
    assert "if success and not _store_local_key(provider, api_key, codex_auth_path, model, user_id):" in save_body
    assert "success, err = False, _LOCAL_STORE_FAILED_MSG" in save_body
    delete_body = src[src.index("def delete_credentials("):src.index("def _store_local_key(")]
    assert "_forget_local_key(user_id)" in delete_body  # the account the request was made as
    # Logout keeps the key: only the cached user scope is dropped.
    hooks = (SCRIPTS / "mixar" / "modules" / "auth" / "core" / "auth_hooks.py").read_text(encoding="utf-8")
    assert "key_store.forget_user()" in hooks and "key_store.delete(" not in hooks


def test_a_failed_device_store_write_is_an_error_that_carries_the_server_state(monkeypatch):
    """The PUT landed (BYOK is active for the account) but this device could
    not keep the key: the dialog must say so — with the server payload
    attached so the card flips to "Key needed on this device" — instead of a
    SAVED recap followed by a 409 on the next message."""
    from types import SimpleNamespace

    from mixar.modules.byok.core import byok_client, transport_seal

    class _Inline:
        def __init__(self, target=None, **_kw):
            self._target = target

        def start(self):
            self._target()

    # The PUT carries the key sealed (`tests/test_byok_transport_seal.py`);
    # this test is about what happens after the 200.
    monkeypatch.setattr(transport_seal, "seal", lambda secret: secret)
    echo = {"byok_active": True, "items": [{"provider": "anthropic", "model": "m", "key_preview": "sk-…"}]}
    service = SimpleNamespace(save_credentials_all=lambda **kw: SimpleNamespace(
        success=True, status_code=200, data={"status": "success", "data": echo}))
    monkeypatch.setattr(byok_client, "get_agent_service", lambda: service)
    monkeypatch.setattr(byok_client, "threading", SimpleNamespace(Thread=_Inline))
    monkeypatch.setattr(byok_client, "_schedule_on_main", lambda fn, *a: fn(*a))
    monkeypatch.setattr(byok_client, "_store_local_key", lambda *a: False)
    done = []
    byok_client.save_credentials("anthropic", "m", "sk-ant-x", on_done=lambda *a: done.append(a))
    assert done == [(False, echo, byok_client._LOCAL_STORE_FAILED_MSG)]

    monkeypatch.setattr(byok_client, "_store_local_key", lambda *a: True)
    done.clear()
    byok_client.save_credentials("anthropic", "m", "sk-ant-x", on_done=lambda *a: done.append(a))
    assert done == [(True, echo, None)]
    # And the error branch of the dialog callback adopts that server state.
    ops = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators" / "byok_ops.py").read_text(encoding="utf-8")
    error_branch = ops[ops.index("def _on_save_done("):ops.index("# Remove (two-click confirm)")]
    error_branch = error_branch[error_branch.index("else:"):]
    assert "_apply_cached_state(wm, data, epoch)" in error_branch


def test_codex_save_sends_access_token_and_account_id_only(monkeypatch, tmp_path):
    """The CLI's auth.json is read in place: the PUT carries the access token
    + account id, the local record carries the file PATH and no token."""
    from types import SimpleNamespace

    from mixar.modules.byok.core import model_suggestions
    from mixar.modules.byok.ui.operators import byok_codex_ops

    saved = {}
    monkeypatch.setattr(byok_codex_ops.byok_client, "save_credentials", lambda **kw: saved.update(kw))
    monkeypatch.setattr(model_suggestions, "is_valid_model", lambda provider, model: True)
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"tokens": {
        "access_token": _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-9"}}),
        "refresh_token": "rt-secret",
    }}))
    wm = SimpleNamespace(byok_form_model="gpt-5", byok_form_codex_path=str(auth_file),
                         byok_dialog_state="IDLE", byok_last_error="")
    assert byok_codex_ops.execute_codex(None, wm, on_done=lambda *a: None) == {'FINISHED'}
    assert saved["provider"] == "codex" and saved["account_id"] == "acct-9"
    assert saved["api_key"].count(".") == 2 and "rt-secret" not in saved["api_key"]
    assert "refresh_token" not in saved and saved["codex_auth_path"] == str(auth_file)
    assert wm.byok_dialog_state == "SAVING"
    record = key_store.make_record("codex", saved["api_key"], auth_path=saved["codex_auth_path"])
    assert record["key"] is None and "refresh_token" not in record and record["auth_path"] == str(auth_file)

    missing = SimpleNamespace(byok_form_model="gpt-5", byok_form_codex_path=str(tmp_path / "nope.json"),
                              byok_dialog_state="IDLE", byok_last_error="")
    assert byok_codex_ops.execute_codex(None, missing, on_done=lambda *a: None) == {'CANCELLED'}
    assert missing.byok_dialog_state == "ERROR" and "codex login" in missing.byok_last_error


def test_codex_path_is_prefilled_when_signed_in_and_the_default_is_stored_as_empty(monkeypatch, tmp_path):
    """The dialog opens with the found sign-in file in the field (the user
    just clicks Save & Activate); saving that default keeps the reference
    empty so it follows $CODEX_HOME like the CLI. A typed path is untouched."""
    from types import SimpleNamespace

    from mixar.modules.byok.core import model_suggestions
    from mixar.modules.byok.ui.operators import byok_codex_ops

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    auth_file = tmp_path / "auth.json"

    wm = SimpleNamespace(byok_form_codex_path="")
    byok_codex_ops.prefill_path(wm)
    assert wm.byok_form_codex_path == ""                       # no sign-in yet: nothing to show
    assert byok_codex_ops.path_status("") == ("No Codex sign-in found - run  codex login  in your terminal", False)
    assert not byok_codex_ops.signed_in("")

    auth_file.write_text(json.dumps({"tokens": {
        "access_token": _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"}}),
        "refresh_token": "rt-secret",
    }}))
    byok_codex_ops.prefill_path(wm)
    assert wm.byok_form_codex_path == str(auth_file)
    assert byok_codex_ops.path_status(wm.byok_form_codex_path) == (
        "Codex sign-in found - just click Save & Activate", True)
    assert byok_codex_ops.signed_in(wm.byok_form_codex_path)

    typed = SimpleNamespace(byok_form_codex_path="/elsewhere/auth.json")
    byok_codex_ops.prefill_path(typed)
    assert typed.byok_form_codex_path == "/elsewhere/auth.json"
    assert byok_codex_ops.path_status(typed.byok_form_codex_path)[1] is False
    assert "/elsewhere/auth.json" in byok_codex_ops.path_status(typed.byok_form_codex_path)[0]


    saved = {}
    monkeypatch.setattr(byok_codex_ops.byok_client, "save_credentials", lambda **kw: saved.update(kw))
    monkeypatch.setattr(model_suggestions, "is_valid_model", lambda provider, model: True)
    wm.byok_form_model, wm.byok_dialog_state, wm.byok_last_error = "gpt-5", "IDLE", ""
    assert byok_codex_ops.execute_codex(None, wm, on_done=lambda *a: None) == {'FINISHED'}
    assert saved["codex_auth_path"] == "" and saved["account_id"] == "acct-1"


def test_codex_record_is_materialized_from_the_file_and_renewals_go_back_into_it(monkeypatch, tmp_path):
    """`materialize` completes a Codex record from the CLI's file in a copy;
    `persist_changes` writes renewed tokens INTO the file (never the store)
    and remembers a revoked sign-in by fingerprint until a new login."""
    from mixar.modules.byok.core import codex_auth

    auth_file = tmp_path / "auth.json"
    token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"}})
    auth_file.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {
        "access_token": token, "refresh_token": "rt-1", "account_id": "acct-1"}, "last_refresh": "old"}))
    stored = {}
    monkeypatch.setattr(key_store, "load", lambda user_id=None: dict(stored) if stored else None)
    monkeypatch.setattr(key_store, "update", lambda changes, user_id=None: (stored.update(changes), True)[1])
    stored.update(key_store.make_record("codex", None, auth_path=str(auth_file)))

    live, problem = key_store.materialize(dict(stored))
    assert problem is None
    assert (live["key"], live["refresh_token"], live["account_id"], live["expired"]) == (token, "rt-1", "acct-1", False)
    assert "refresh_token" not in stored and stored["key"] is None     # the store never gained a token

    assert key_store.persist_changes(live, {"key": "at-2", "expired": False, "refresh_token": "rt-2"})
    data = json.loads(auth_file.read_text())
    assert data["tokens"]["access_token"] == "at-2" and data["tokens"]["refresh_token"] == "rt-2"
    assert data["auth_mode"] == "chatgpt" and data["last_refresh"] != "old"
    assert stored["expired_fingerprint"] is None

    # Revoked: remembered by fingerprint; a new `codex login` clears it.
    live, _ = key_store.materialize(dict(stored))
    assert key_store.persist_changes(live, {"expired": True})
    assert stored["expired_fingerprint"] == codex_auth.fingerprint("rt-2")
    assert key_store.materialize(dict(stored))[0]["expired"] is True
    data["tokens"]["refresh_token"] = "rt-3"
    auth_file.write_text(json.dumps(data))
    assert key_store.materialize(dict(stored))[0]["expired"] is False

    auth_file.unlink()
    assert key_store.materialize(dict(stored)) == (None, codex_auth.MSG_FILE_MISSING)
    assert key_store.persist_changes(live, {"key": "at-4"}) is False    # nothing is created from scratch


def test_v1_records_that_copied_codex_tokens_are_upgraded_to_a_reference(monkeypatch):
    fake = _patch_store(monkeypatch)
    raw = {"v": 1, "provider": "codex", "key": "at", "account_id": "a", "refresh_token": "rt", "expired": False}
    fake.entries["BYOK:u1"] = json.dumps(raw)            # an earlier build's own item
    monkeypatch.setattr(key_store, "current_user_id", lambda: "u1")
    record = key_store.load()
    assert record == key_store.make_record("codex", None)
    assert "refresh_token" not in record and record["auth_path"] == ""
    assert "rt" not in json.dumps(fake.entries)           # the token copy did not survive the move


def test_reassign_moves_the_claimed_guest_record_to_the_account(monkeypatch):
    """Signing in claims the guest: the backend moved its BYOK row, so the key
    material on this device (keyed by user id) follows it — unless the
    account already has its own record on this device, which wins."""
    fake = _patch_store(monkeypatch)
    guest = key_store.make_record("codex", None, auth_path="")
    key_store.save(guest, "guest-1")

    assert key_store.reassign("guest-1", "acct-1") is True
    assert key_store.load("guest-1") is None
    assert key_store.load("acct-1")["provider"] == "codex"
    assert f"{key_store.BYOK_KEY_STORE_PREFIX.lower()}:guest-1" not in _bundle(fake)

    # The account's own record wins; the guest's copy is dropped.
    key_store.save(key_store.make_record("anthropic", "sk-own"), "acct-2")
    key_store.save(key_store.make_record("codex", None, auth_path=""), "guest-2")
    assert key_store.reassign("guest-2", "acct-2") is True
    assert key_store.load("acct-2")["provider"] == "anthropic"
    assert key_store.load("guest-2") is None

    # Nothing to move, same user, or no ids: a no-op.
    assert key_store.reassign("guest-3", "acct-3") is False
    assert key_store.reassign("acct-3", "acct-3") is False
    assert key_store.reassign(None, "acct-3") is False
