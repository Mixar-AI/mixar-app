# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One credential-store entry for every Python-owned secret, read once.

The Keychain asks per ITEM when the app's signing identity changes, so the
BYOK records of every account and the auth refresh marker share one entry
(`credential_store.BUNDLE_ENTRY`). The bundle is read once per process and
cached; a refused read (locked keychain, unexpected status) is backed off
for `BUNDLE_RETRY_S` and then retried — never latched for the process, since
the auth refresh marker in here gates every token refresh.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.utils import credential_store  # noqa: E402


class FakeStore:
    def __init__(self):
        self.entries = {}
        self.reads = 0
        self.refuse = False

    def read(self, name):
        self.reads += 1
        if self.refuse:
            raise RuntimeError("keychain locked")
        return self.entries.get(name)

    def set(self, name, value):
        self.entries[name] = value
        return True

    def delete(self, name):
        self.entries.pop(name, None)
        return True


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(credential_store, "_read_secret", fake.read)
    monkeypatch.setattr(credential_store, "set_secret", fake.set)
    monkeypatch.setattr(credential_store, "delete_secret", fake.delete)
    credential_store.invalidate_cache()
    yield fake
    credential_store.invalidate_cache()


def test_values_share_one_entry_and_the_store_is_read_once(store):
    assert credential_store.get_value("byok:alice") is None
    assert credential_store.set_value("byok:alice", {"provider": "openai", "key": "sk-a"})
    assert credential_store.set_value("auth:refresh_attempt", {"idempotency_key": "k"})
    assert set(store.entries) == {credential_store.BUNDLE_ENTRY}
    bundle = json.loads(store.entries[credential_store.BUNDLE_ENTRY])
    assert bundle["v"] == 1 and set(bundle["values"]) == {"byok:alice", "auth:refresh_attempt"}
    reads = store.reads
    assert credential_store.get_value("byok:alice") == {"provider": "openai", "key": "sk-a"}
    assert credential_store.get_value("auth:refresh_attempt") == {"idempotency_key": "k"}
    assert store.reads == reads                     # served from the process cache
    # Returned values are copies: mutating one never leaks into the cache.
    credential_store.get_value("byok:alice")["key"] = "mutated"
    assert credential_store.get_value("byok:alice")["key"] == "sk-a"


def test_a_fresh_process_reads_the_bundle_back(store):
    credential_store.set_value("byok:bob", {"provider": "codex", "auth_path": ""})
    credential_store.invalidate_cache()               # what a new process sees
    assert credential_store.get_value("byok:bob") == {"provider": "codex", "auth_path": ""}
    assert credential_store.delete_value("byok:bob") and credential_store.delete_value("byok:bob")
    assert json.loads(store.entries[credential_store.BUNDLE_ENTRY])["values"] == {}


def test_a_refused_read_backs_off_then_retries(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(credential_store, "_clock", lambda: clock[0])
    store.refuse = True
    assert credential_store.get_value("byok:alice") is None
    assert credential_store.store_available() is False
    reads = store.reads
    credential_store.get_value("byok:alice")
    credential_store.get_value("byok:alice")
    assert store.reads == reads                     # not hammered per message
    store.refuse = False
    clock[0] += credential_store.BUNDLE_RETRY_S - 1
    credential_store.get_value("byok:alice")
    assert store.reads == reads                     # still inside the backoff
    clock[0] += 1
    assert credential_store.store_available() is True   # retried on its own: no restart, no logout
    assert store.reads == reads + 1


def test_a_write_or_invalidate_retries_a_refused_read_at_once(store, monkeypatch):
    monkeypatch.setattr(credential_store, "_clock", lambda: 1000.0)   # the clock never moves
    store.refuse = True
    assert credential_store.store_available() is False
    store.refuse = False
    assert credential_store.store_available() is False
    assert credential_store.set_value("byok:alice", {"provider": "openai"})   # a write retries
    assert credential_store.store_available() is True
    store.refuse = True
    credential_store.invalidate_cache()
    assert credential_store.store_available() is False


def test_an_unreadable_bundle_starts_empty_instead_of_failing(store):
    store.entries[credential_store.BUNDLE_ENTRY] = "{not json"
    assert credential_store.get_value("x") is None and credential_store.store_available()
    store.entries[credential_store.BUNDLE_ENTRY] = json.dumps(["not", "a", "bundle"])
    credential_store.invalidate_cache()
    assert credential_store.get_value("x") is None and credential_store.store_available()


def test_a_failed_write_drops_the_cache(store, monkeypatch):
    credential_store.set_value("byok:alice", {"provider": "openai"})
    monkeypatch.setattr(credential_store, "set_secret", lambda name, value: False)
    assert credential_store.set_value("byok:alice", {"provider": "anthropic"}) is False
    assert credential_store.get_value("byok:alice") == {"provider": "openai"}   # re-read from the store


def test_legacy_standalone_entries_move_into_the_bundle_once(store):
    store.entries["BYOK:alice"] = json.dumps({"v": 1, "provider": "openai", "key": "sk-a"})
    store.entries["RefreshAttempt"] = json.dumps({"idempotency_key": "k", "refresh_token_digest": "d"})
    assert credential_store.migrate_legacy_entry("BYOK:alice", "byok:alice", parse=json.loads)
    assert credential_store.migrate_legacy_entry("RefreshAttempt", "auth:refresh_attempt", parse=json.loads)
    assert "BYOK:alice" not in store.entries and "RefreshAttempt" not in store.entries
    assert credential_store.get_value("byok:alice")["key"] == "sk-a"
    assert credential_store.migrate_legacy_entry("BYOK:alice", "byok:alice") is False   # nothing left
    store.entries["BYOK:carol"] = "{broken"
    assert credential_store.migrate_legacy_entry("BYOK:carol", "byok:carol", parse=json.loads) is False
    assert "BYOK:carol" not in store.entries       # an unreadable legacy value is dropped


# --- macOS: never a dialog ------------------------------------------------------

def _quiet(status, value=None, locked=False):
    deleted = []
    out = credential_store._mac_read_quiet(
        "AccessToken",
        copy=lambda name: (status, value),
        locked=lambda: locked,
        delete=lambda n: deleted.append(n) or 0,
    )
    return out, deleted


def test_mac_quiet_read_returns_the_value_or_absent():
    assert _quiet(0, "tok") == ("tok", [])
    assert _quiet(0, "") == (None, [])
    assert _quiet(credential_store._SEC_ITEM_NOT_FOUND) == (None, [])


def test_an_item_bound_to_another_build_is_dropped_without_a_dialog():
    """The prompt's "Allow" grants ONE read and the app reads tokens per
    request: the only dialog-free answer is to treat the item as absent (the
    user signs in / enters the key once)."""
    for status in (credential_store._SEC_INTERACTION_NOT_ALLOWED, credential_store._SEC_AUTH_FAILED):
        credential_store.invalidate_cache()
        assert _quiet(status) == (None, ["AccessToken"])
    credential_store.invalidate_cache()


def test_a_locked_keychain_raises_and_deletes_nothing():
    with pytest.raises(credential_store.KeychainLocked):
        _quiet(credential_store._SEC_INTERACTION_NOT_ALLOWED, locked=True)


def test_other_failures_propagate():
    with pytest.raises(RuntimeError):
        _quiet(-128)


def test_mac_reads_and_writes_use_the_quiet_path():
    src = (SCRIPTS / "mixar" / "modules" / "common" / "utils" / "credential_store.py").read_text(encoding="utf-8")
    assert "SecKeychainSetUserInteractionAllowed" in src
    assert src.count("with _no_keychain_dialogs():") == 3      # read, quiet delete, add
    assert "if _IS_MACOS:\n        return _mac_read_quiet(name)" in src
    assert "if _IS_MACOS:\n            return _mac_set(name, value)" in src
    auth = (SCRIPTS / "mixar" / "modules" / "auth" / "core" / "auth.py").read_text(encoding="utf-8")
    assert 'keyring.get_password("MixarSafeStorage"' not in auth   # every token read is the quiet path
    assert 'keyring.set_password("MixarSafeStorage"' not in auth
    assert "credential_store.get_secret(item)" in auth


def test_mac_set_replaces_own_item_silently_and_keeps_a_foreign_name_in_memory():
    credential_store.invalidate_cache()
    calls = []
    assert credential_store._mac_set("Mixar.AccessToken", "tok",
                                     delete_quiet=lambda n: calls.append(("quiet", n)) or 0,
                                     add=lambda n, v: calls.append(("add", n)) or 0)
    assert calls == [("quiet", "Mixar.AccessToken"), ("add", "Mixar.AccessToken")]

    # A foreign item holds the name: no dialog can replace it, so the value
    # lives in memory for the session and the app keeps working.
    calls.clear()
    assert credential_store._mac_set("Mixar.AccessToken", "tok2",
                                     delete_quiet=lambda n: calls.append(("quiet", n)) or -25244,
                                     add=lambda n, v: calls.append(("add", n)) or credential_store._SEC_DUPLICATE_ITEM)
    assert [c[0] for c in calls] == ["quiet", "add"]
    assert "Mixar.AccessToken" in credential_store._foreign
    assert credential_store._read_secret("Mixar.AccessToken") == "tok2"      # served from memory
    calls.clear()
    assert credential_store._mac_set("Mixar.AccessToken", "tok3",
                                     delete_quiet=lambda n: calls.append(1), add=lambda n, v: calls.append(1))
    assert calls == [] and credential_store._read_secret("Mixar.AccessToken") == "tok3"   # keychain not touched again
    credential_store.invalidate_cache()
    assert not credential_store._foreign and not credential_store._volatile

    assert credential_store._mac_set("x", "v", delete_quiet=lambda n: 0, add=lambda n, v: -128) is False


def test_a_foreign_item_is_read_as_absent_once_and_not_retried_per_request():
    credential_store.invalidate_cache()
    deletes = []
    out = credential_store._mac_read_quiet("Mixar.AccessToken",
                                           copy=lambda n: (credential_store._SEC_AUTH_FAILED, None),
                                           locked=lambda: False, delete=lambda n: deletes.append(n) or -25244)
    assert out is None and deletes == ["Mixar.AccessToken"]
    assert "Mixar.AccessToken" in credential_store._foreign
    # Later reads short-circuit before the keychain.
    assert credential_store._read_secret("Mixar.AccessToken") is None
    # An item that turned out to be ours (delete succeeded) is simply gone.
    out = credential_store._mac_read_quiet("Mixar.RefreshToken",
                                           copy=lambda n: (credential_store._SEC_AUTH_FAILED, None),
                                           locked=lambda: False, delete=lambda n: 0)
    assert out is None and "Mixar.RefreshToken" not in credential_store._foreign
    credential_store.invalidate_cache()


def test_token_items_are_renamed_on_macos_only(monkeypatch):
    """macOS: the old items belong to the old signing identity and can be
    neither read nor deleted without a dialog, so the stable identity uses
    new names (the user signs in once) — there is no silent move, the old
    item is unreadable by definition. Windows and Linux have no per-app
    access list: they keep the original names, so an upgrade keeps the
    session and the C++ startup gate (which reads before Python runs)
    finds the token. Reads look under exactly one name."""
    import platform

    from mixar.modules.auth.core import auth

    macos = platform.system() == "Darwin"
    expected = ("Mixar.AccessToken", "Mixar.RefreshToken") if macos else ("AccessToken", "RefreshToken")
    assert (auth.ACCESS_TOKEN_ITEM, auth.REFRESH_TOKEN_ITEM) == expected
    py = (SCRIPTS / "mixar" / "modules" / "auth" / "core" / "auth.py").read_text(encoding="utf-8")
    assert 'ACCESS_TOKEN_ITEM = "Mixar.AccessToken" if _is_macos else "AccessToken"' in py
    assert 'WIN_TARGET_NAME_ACCESS = "AccessToken@MixarSafeStorage"' in py
    assert "LEGACY" not in py
    cc = (ROOT / "src" / "source" / "creator" / "creator_auth.cc").read_text(encoding="utf-8")
    apple = cc[cc.index("#if defined(__APPLE__)\nstatic const char* ACCOUNT_NAME"):cc.index("#endif", cc.index("#if defined(__APPLE__)\nstatic const char* ACCOUNT_NAME"))]
    assert 'ACCOUNT_NAME = "Mixar.AccessToken"' in apple and 'REFRESH_ACCOUNT_NAME = "Mixar.RefreshToken"' in apple
    assert '#else\nstatic const char* ACCOUNT_NAME = "AccessToken";' in apple
    assert 'REFRESH_ACCOUNT_NAME = "RefreshToken";' in apple
    assert 'WIN_TARGET_NAME = "AccessToken@MixarSafeStorage"' in cc
    assert 'WIN_REFRESH_TARGET_NAME = "RefreshToken@MixarSafeStorage"' in cc

    entries = {auth.ACCESS_TOKEN_ITEM: "tok"}
    looked_up = []
    monkeypatch.setattr(auth, "_is_windows", False)
    monkeypatch.setattr(credential_store, "get_secret", lambda n: looked_up.append(n) or entries.get(n))
    monkeypatch.setattr(credential_store, "set_secret", lambda n, v: entries.__setitem__(n, v) or True)
    monkeypatch.setattr(credential_store, "delete_secret", lambda n: entries.pop(n, None) or True)
    assert auth.get_access_token() == "tok"
    assert auth.get_refresh_token() == ""
    assert looked_up == [auth.ACCESS_TOKEN_ITEM, auth.REFRESH_TOKEN_ITEM]   # one name each, no legacy lookup
    assert entries == {auth.ACCESS_TOKEN_ITEM: "tok"}                        # nothing moved or created
    assert auth.store_refresh_token("rt") and entries[auth.REFRESH_TOKEN_ITEM] == "rt"
    assert auth.delete_access_token() and auth.ACCESS_TOKEN_ITEM not in entries
