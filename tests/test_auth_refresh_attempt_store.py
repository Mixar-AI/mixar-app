# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pending-refresh marker lives in the shared credential bundle.

It used to be its own Keychain item ("RefreshAttempt"), one more approval
dialog when the app's identity changed. It is now a value inside the one
bundle entry; an older build's item is moved in on first use.
"""

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.auth.core import auth  # noqa: E402
from mixar.modules.common.utils import credential_store  # noqa: E402


def _store(monkeypatch):
    entries = {}
    monkeypatch.setattr(credential_store, "_read_secret", lambda name: entries.get(name))
    monkeypatch.setattr(credential_store, "set_secret", lambda name, value: entries.__setitem__(name, value) or True)
    monkeypatch.setattr(credential_store, "delete_secret", lambda name: entries.pop(name, None) or True)
    credential_store.invalidate_cache()
    return entries


def test_marker_round_trips_through_the_bundle(monkeypatch):
    entries = _store(monkeypatch)
    attempt = {"refresh_token_digest": "a" * 64, "idempotency_key": str(uuid.uuid4())}
    assert auth._persist_refresh_attempt(attempt)
    assert set(entries) == {credential_store.BUNDLE_ENTRY}
    assert auth._load_persisted_refresh_attempt() == (True, attempt)
    assert auth._delete_persisted_refresh_attempt()
    assert auth._load_persisted_refresh_attempt() == (True, None)
    credential_store.invalidate_cache()


def test_invalid_marker_is_discarded_and_legacy_item_is_migrated(monkeypatch):
    entries = _store(monkeypatch)
    assert credential_store.set_value(auth.REFRESH_ATTEMPT_KEY, {"idempotency_key": "nope"})
    assert auth._load_persisted_refresh_attempt() == (True, None)
    assert credential_store.get_value(auth.REFRESH_ATTEMPT_KEY) is None
    legacy = {"refresh_token_digest": "b" * 64, "idempotency_key": str(uuid.uuid4())}
    entries["RefreshAttempt"] = json.dumps(legacy)
    assert auth._load_persisted_refresh_attempt() == (True, legacy)
    assert "RefreshAttempt" not in entries
    credential_store.invalidate_cache()


def test_unavailable_store_is_reported_not_treated_as_absent(monkeypatch):
    _store(monkeypatch)
    monkeypatch.setattr(credential_store, "_read_secret", lambda name: (_ for _ in ()).throw(RuntimeError("locked")))
    credential_store.invalidate_cache()
    assert auth._load_persisted_refresh_attempt() == (False, None)
    credential_store.invalidate_cache()


def test_the_refresh_idempotency_key_is_deterministic_per_token(monkeypatch):
    """Option B: two Mixar instances sharing the keychain compute the SAME key
    for the same refresh token, so the backend coordinates their refresh and
    neither is rejected (which would clear the shared credentials)."""
    assert auth._refresh_idempotency_key("rt-abc") == auth._refresh_idempotency_key("rt-abc")
    assert auth._refresh_idempotency_key("rt-abc") != auth._refresh_idempotency_key("rt-xyz")
    assert uuid.UUID(auth._refresh_idempotency_key("rt-abc")).version == 5  # valid, backend-accepted


def test_a_deterministic_v5_marker_round_trips_and_is_accepted(monkeypatch):
    """The v5 key Option B now writes is a valid marker (the validation was
    relaxed from v4-only to v4/v5; an older build's v4 marker still loads)."""
    _store(monkeypatch)
    v5 = auth._refresh_idempotency_key("rt-abc")
    attempt = {"refresh_token_digest": "c" * 64, "idempotency_key": v5}
    assert auth._persist_refresh_attempt(attempt)
    assert auth._load_persisted_refresh_attempt() == (True, attempt)
    credential_store.invalidate_cache()
