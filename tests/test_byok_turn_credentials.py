# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The key rides every agent turn — the pre-send decision table.

`turn_credentials.resolve` is pure: a stored record (or none), a clock and a
refresher in → the `byok_key` / `byok_account_id` payload fields, or a
refusal, plus the record changes to persist. Pinned here without bpy, the
credential store or the network. The threaded `prepare` wrapper is pinned
at source level (worker thread, main-thread callback, inactive fast path).
"""

import base64
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

from mixar.modules.byok.constants import (
    BYOK_CODEX_EXPIRED_CODE,
    BYOK_CODEX_REFRESH_FAILED_CODE,
    CODEX_REFRESH_MARGIN_S,
)
from mixar.modules.byok.core import codex_auth, key_store, turn_credentials
from mixar.modules.byok.core.codex_auth import RefreshOutcome

NOW = 2_000_000.0


def _jwt(claims: dict) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


FRESH = _jwt({"exp": NOW + 2 * CODEX_REFRESH_MARGIN_S})
STALE_BUT_VALID = _jwt({"exp": NOW + 3600})       # inside the 24 h window
EXPIRED = _jwt({"exp": NOW - 10})


def _codex(token, refresh_token="rt-old", expired=False):
    return {"provider": "codex", "key": token, "account_id": "acct",
            "refresh_token": refresh_token, "expired": expired}


class Refresher:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def __call__(self, refresh_token):
        self.calls.append(refresh_token)
        return self.outcome


# --- non-codex ---------------------------------------------------------------

def test_no_record_sends_nothing_and_lets_the_server_decide():
    resolution = turn_credentials.resolve(None, NOW)
    assert resolution.fields == {} and not resolution.blocked


def test_cloud_key_rides_as_byok_key_only():
    resolution = turn_credentials.resolve(key_store.make_record("anthropic", "sk-ant-x"), NOW)
    assert resolution.fields == {"byok_key": "sk-ant-x"}
    assert not resolution.blocked and resolution.record_changes is None


def test_keyless_local_omits_the_field():
    resolution = turn_credentials.resolve(key_store.make_record("local", None), NOW)
    assert resolution.fields == {} and not resolution.blocked


def test_local_bearer_rides_as_byok_key():
    assert turn_credentials.resolve(key_store.make_record("local", "bearer"), NOW).fields == {
        "byok_key": "bearer"}


# --- codex -------------------------------------------------------------------

def test_codex_fresh_token_is_sent_with_the_account_id_without_a_refresh():
    refresher = Refresher(RefreshOutcome("ok", "never"))
    resolution = turn_credentials.resolve(_codex(FRESH), NOW, refresher)
    assert resolution.fields == {"byok_key": FRESH, "byok_account_id": "acct"}
    assert refresher.calls == []


def test_codex_within_24h_refreshes_first_and_persists_rotated_tokens():
    refresher = Refresher(RefreshOutcome("ok", access_token="at-new", refresh_token="rt-new"))
    resolution = turn_credentials.resolve(_codex(STALE_BUT_VALID), NOW, refresher)
    assert refresher.calls == ["rt-old"]
    assert resolution.fields == {"byok_key": "at-new", "byok_account_id": "acct"}
    assert resolution.record_changes == {"key": "at-new", "expired": False, "refresh_token": "rt-new"}


def test_codex_file_that_cannot_keep_a_renewal_is_never_refreshed():
    """The refresh grant rotates the refresh token; a renewal the sign-in
    file cannot store would be lost and sign the Codex CLI out as well. So
    while the current token is valid it is sent as is, and once it is
    expired the turn is refused with the permissions message — the grant is
    never spent (`key_store.materialize` sets ``can_persist`` from the file)."""
    refresher = Refresher(RefreshOutcome("ok", access_token="at-new", refresh_token="rt-new"))
    record = dict(_codex(STALE_BUT_VALID), can_persist=False)
    resolution = turn_credentials.resolve(record, NOW, refresher)
    assert refresher.calls == [] and resolution.record_changes is None
    assert resolution.fields == {"byok_key": STALE_BUT_VALID, "byok_account_id": "acct"}
    record = dict(_codex(EXPIRED), can_persist=False)
    resolution = turn_credentials.resolve(record, NOW, refresher)
    assert refresher.calls == [] and resolution.blocked
    assert resolution.error == codex_auth.MSG_FILE_NOT_WRITABLE
    assert resolution.code == BYOK_CODEX_REFRESH_FAILED_CODE
    # A record without the flag (a non-file record, older callers) refreshes as before.
    assert turn_credentials.resolve(_codex(STALE_BUT_VALID), NOW, refresher).record_changes
    src = (SCRIPTS / "mixar" / "modules" / "byok" / "core" / "key_store.py").read_text(encoding="utf-8")
    assert "can_persist=codex_auth.can_write_back(record.get(\"auth_path\"))" in src


def test_codex_refresh_without_rotation_keeps_the_old_refresh_token():
    refresher = Refresher(RefreshOutcome("ok", access_token="at-new"))
    resolution = turn_credentials.resolve(_codex(STALE_BUT_VALID), NOW, refresher)
    assert resolution.record_changes == {"key": "at-new", "expired": False}


def test_codex_revoked_refresh_blocks_and_marks_the_record_expired():
    refresher = Refresher(RefreshOutcome("revoked", message=codex_auth.MSG_SIGN_IN_EXPIRED))
    resolution = turn_credentials.resolve(_codex(STALE_BUT_VALID), NOW, refresher)
    assert resolution.blocked and resolution.fields == {}
    assert resolution.code == BYOK_CODEX_EXPIRED_CODE
    assert resolution.error == codex_auth.MSG_SIGN_IN_EXPIRED
    assert resolution.record_changes == {"expired": True}


def test_codex_network_failure_with_a_valid_token_sends_the_current_one():
    refresher = Refresher(RefreshOutcome("network", message="NET-1"))
    resolution = turn_credentials.resolve(_codex(STALE_BUT_VALID), NOW, refresher)
    assert resolution.fields == {"byok_key": STALE_BUT_VALID, "byok_account_id": "acct"}
    assert not resolution.blocked and resolution.record_changes is None


def test_codex_network_failure_with_an_expired_token_blocks_retryably():
    refresher = Refresher(RefreshOutcome("network", message="NET-1 could not reach"))
    resolution = turn_credentials.resolve(_codex(EXPIRED), NOW, refresher)
    assert resolution.blocked and resolution.code == BYOK_CODEX_REFRESH_FAILED_CODE
    assert resolution.error == "NET-1 could not reach"
    assert resolution.record_changes is None  # the sign-in is not known to be gone


def test_codex_expired_flag_blocks_without_touching_the_network():
    refresher = Refresher(RefreshOutcome("ok", "at-new"))
    resolution = turn_credentials.resolve(_codex(FRESH, expired=True), NOW, refresher)
    assert resolution.blocked and resolution.code == BYOK_CODEX_EXPIRED_CODE
    assert refresher.calls == []


def test_codex_without_a_refresh_token_uses_what_is_valid():
    assert turn_credentials.resolve(_codex(STALE_BUT_VALID, refresh_token=None), NOW).fields == {
        "byok_key": STALE_BUT_VALID, "byok_account_id": "acct"}
    gone = turn_credentials.resolve(_codex(EXPIRED, refresh_token=None), NOW)
    assert gone.blocked and gone.code == BYOK_CODEX_EXPIRED_CODE


# --- another provider's key ------------------------------------------------------

def test_a_key_for_another_provider_is_not_sent_and_marks_the_device():
    """Device A holds an Anthropic key; the account was switched to OpenAI
    from device B. Sending `sk-ant-…` would pass the credit bypass and die
    on a provider 401 mid-turn: send nothing, let the server 409."""
    record = key_store.make_record("anthropic", "sk-ant-x")
    stale = turn_credentials.resolve(record, NOW, active_provider="openai")
    assert stale.fields == {} and not stale.blocked and stale.key_missing
    assert turn_credentials.resolve(record, NOW, active_provider="anthropic").fields == {"byok_key": "sk-ant-x"}
    # Account provider not known yet (cold start): the record is trusted.
    assert turn_credentials.resolve(record, NOW).fields == {"byok_key": "sk-ant-x"}
    codex = turn_credentials.resolve(_codex(FRESH), NOW, Refresher(RefreshOutcome("ok", "x")),
                                     active_provider="openai")
    assert codex.fields == {} and codex.key_missing and not codex.blocked


# --- the threaded wrapper + the send path ---------------------------------------

class _InlineThread:
    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        self._target()


def _run_prepare(monkeypatch, state, record, **kw):
    """`prepare` with the worker thread and the main-thread hop run inline."""
    from types import SimpleNamespace

    from mixar.modules.byok.core import byok_client, credential_state, transport_seal

    monkeypatch.setattr(credential_state, "snapshot", lambda: dict(state))
    monkeypatch.setattr(key_store, "load", lambda *a, **k: record)
    monkeypatch.setattr(turn_credentials, "threading", SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(byok_client, "schedule_on_main", lambda fn, *a: fn(*a))
    # The wire field is sealed to the backend's key (`tests/test_byok_transport_seal.py`);
    # the decision table here is read on the plaintext.
    monkeypatch.setattr(transport_seal, "seal", lambda secret: secret)
    flips = []
    monkeypatch.setattr(credential_state, "set_device_key_missing", flips.append)
    seen = []
    turn_credentials.prepare(lambda fields, error: seen.append((fields, error)), **kw)
    return seen, flips


LOADED_OPENAI = {"byok_is_active": True, "byok_state_loaded": True, "byok_current_provider": "openai"}
COLD = {"byok_is_active": False, "byok_state_loaded": False, "byok_current_provider": ""}


def test_prepare_is_synchronous_and_empty_while_byok_is_inactive(monkeypatch):
    from mixar.modules.byok.core import credential_state

    monkeypatch.setattr(credential_state, "snapshot",
                        lambda: {"byok_is_active": False, "byok_state_loaded": True})
    monkeypatch.setattr(key_store, "load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("store touched")))
    seen = []
    turn_credentials.prepare(lambda fields, error: seen.append((fields, error)))
    assert seen == [({}, None)]


def test_an_input_abort_is_sent_at_once_without_the_store_or_a_refresh(monkeypatch):
    """The server exempts an abort from the key requirement; a dead Codex
    sign-in (or a 10 s refresh) must never keep the user from declining a
    plan. Every other input still goes through the store."""
    from mixar.modules.byok.core import credential_state

    monkeypatch.setattr(credential_state, "snapshot", lambda: {
        "byok_is_active": True, "byok_state_loaded": True, "byok_current_provider": "codex"})
    monkeypatch.setattr(key_store, "load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("store touched")))
    seen = []
    turn_credentials.prepare(lambda fields, error: seen.append((fields, error)), method="input", action="abort")
    assert seen == [({}, None)]
    seen, flips = _run_prepare(monkeypatch, LOADED_OPENAI, key_store.make_record("openai", "sk-o"),
                               method="input", action="approve")
    assert seen == [({"byok_key": "sk-o"}, None)] and flips == [False]
    seen, _ = _run_prepare(monkeypatch, LOADED_OPENAI, key_store.make_record("openai", "sk-o"),
                           method="chat", action="abort")
    assert seen == [({"byok_key": "sk-o"}, None)]


def test_before_the_first_fetch_the_turn_is_sent_keyless_and_synchronously(monkeypatch):
    """The cold-start window reads "inactive": the platform path's timing is
    kept and the store is not touched; the 409 that may follow refreshes the
    mirror (`test_byok_key_required_notice`) instead of flipping the pill."""
    from mixar.modules.byok.core import credential_state

    monkeypatch.setattr(credential_state, "snapshot", lambda: dict(COLD))
    monkeypatch.setattr(key_store, "load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("store touched")))
    seen = []
    turn_credentials.prepare(lambda fields, error: seen.append((fields, error)))
    assert seen == [({}, None)]


def test_once_loaded_a_missing_or_foreign_record_marks_the_device(monkeypatch):
    seen, flips = _run_prepare(monkeypatch, LOADED_OPENAI, key_store.make_record("anthropic", "sk-ant-x"))
    assert seen == [({}, None)] and flips == [True]
    seen, flips = _run_prepare(monkeypatch, LOADED_OPENAI, None)
    assert seen == [({}, None)] and flips == [True]
    seen, flips = _run_prepare(monkeypatch, LOADED_OPENAI, key_store.make_record("openai", "sk-o"))
    assert seen == [({"byok_key": "sk-o"}, None)] and flips == [False]


def test_prepare_reads_the_store_off_thread_and_calls_back_on_main():
    src = (SCRIPTS / "mixar" / "modules" / "byok" / "core" / "turn_credentials.py").read_text(encoding="utf-8")
    assert "threading.Thread(target=_thread, daemon=True" in src
    assert "schedule_on_main(_deliver" in src
    assert "refresher=codex_auth.refresh_access_token" in src
    assert "key_store.materialize(record)" in src
    assert "key_store.persist_changes(live, changes, user_id)" in src
    # The key field is sealed on the same worker thread, after the Codex
    # write-back (`serve`), and the catch-all fallback is keyless — never plaintext.
    assert "resolution = sealed(serve(record, active_provider=active_provider))" in src
    assert src.index("key_store.persist_changes(live, changes, user_id)") < src.index("resolution = sealed(serve(")
    assert src.index("resolution = sealed(serve(") < src.index("except Exception as exc:  # noqa: BLE001 — never block the turn")


def test_codex_turn_reads_the_cli_file_and_writes_a_renewal_back(monkeypatch, tmp_path):
    """End to end through `prepare`: the store holds only the file path; the
    turn's token comes from auth.json; a within-24h token is refreshed and the
    new pair lands in auth.json; a missing file refuses like an expired sign-in."""
    import json

    from mixar.modules.byok.core import credential_state

    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"tokens": {"access_token": STALE_BUT_VALID, "refresh_token": "rt-old",
                                                "account_id": "acct"}}))
    monkeypatch.setattr(codex_auth, "refresh_access_token",
                        lambda rt: RefreshOutcome("ok", access_token="at-new", refresh_token="rt-new"))
    monkeypatch.setattr(key_store, "update", lambda changes, user_id=None: True)
    record = key_store.make_record("codex", None, auth_path=str(auth_file))
    loaded = {"byok_is_active": True, "byok_state_loaded": True, "byok_current_provider": "codex"}

    seen, flips = _run_prepare(monkeypatch, loaded, record)
    assert seen == [({"byok_key": "at-new", "byok_account_id": "acct"}, None)] and flips == [False]
    data = json.loads(auth_file.read_text())
    assert data["tokens"] == {"access_token": "at-new", "refresh_token": "rt-new", "account_id": "acct"}
    assert "last_refresh" in data

    auth_file.unlink()
    seen, flips = _run_prepare(monkeypatch, loaded, record)
    assert seen[0][0] == {} and seen[0][1]["code"] == BYOK_CODEX_EXPIRED_CODE
    assert "codex login" in seen[0][1]["message"] and flips == [True]


def test_turn_transport_attaches_the_fields_before_every_chat_and_input_command():
    src = (SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core" / "turn_transport.py").read_text(encoding="utf-8")
    assert "from mixar.modules.byok.core.turn_credentials import prepare" in src
    assert "payload.update(byok_fields or {})" in src
    # The command's method/action reach `prepare`, so an `input` abort is exempt.
    assert "prepare(dispatch, method=method, action=payload.get('action'))" in src
    # The refusal settles through the expected command id, never a retry.
    assert "'data': {'code': byok_error.get('code')}" in src
    assert src.index("turn_events.expect(scene, command_id, settled)") < src.index("prepare(dispatch, method=method")


def test_key_material_never_reaches_a_log_line():
    for name in ("key_store.py", "turn_credentials.py", "codex_auth.py", "byok_client.py", "transport_seal.py"):
        src = (SCRIPTS / "mixar" / "modules" / "byok" / "core" / name).read_text(encoding="utf-8")
        for line in src.splitlines():
            if "logger." in line:
                assert "api_key" not in line and "refresh_token" not in line and "access_token" not in line, line


# ---------------------------------------------------------------------------
# The sign-in changes while its refresh is in flight (KEY-22)
# ---------------------------------------------------------------------------

def _live_jwt(seconds: float) -> str:
    import time

    return _jwt({"exp": time.time() + seconds})


def _sign_in(path, access, refresh):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tokens": {"access_token": access, "refresh_token": refresh,
                                           "account_id": "acct"}}))
    path.chmod(0o600)


def _race(monkeypatch, tmp_path, during):
    """A Codex turn whose sign-in is stale (it must refresh) and whose
    `during(auth_file, record)` runs while the refresh grant is in flight."""
    auth_file = tmp_path / "old" / "auth.json"
    _sign_in(auth_file, EXPIRED, "rt-old")
    record = key_store.make_record("codex", None, auth_path=str(auth_file))
    spent = []

    def refresh(refresh_token):
        spent.append(refresh_token)
        during(auth_file, record)
        return RefreshOutcome("ok", access_token="at-renewed", refresh_token="rt-renewed")

    monkeypatch.setattr(codex_auth, "refresh_access_token", refresh)
    monkeypatch.setattr(key_store, "update", lambda changes, user_id=None: True)
    loaded = {"byok_is_active": True, "byok_state_loaded": True, "byok_current_provider": "codex"}
    seen, _ = _run_prepare(monkeypatch, loaded, record)
    return seen, auth_file, spent


def test_a_sign_in_removed_during_its_refresh_refuses_the_turn(monkeypatch, tmp_path):
    seen, auth_file, spent = _race(monkeypatch, tmp_path, lambda f, _r: f.unlink())
    assert spent == ["rt-old"]
    assert seen == [({}, {"message": codex_auth.MSG_FILE_MISSING, "code": BYOK_CODEX_EXPIRED_CODE})]
    assert not auth_file.exists()                       # never recreated


def test_a_sign_in_that_turns_unwritable_during_its_refresh_refuses_the_turn(monkeypatch, tmp_path):
    import os

    def lock(f, _r):
        f.parent.chmod(0o500)

    try:
        seen, auth_file, spent = _race(monkeypatch, tmp_path, lock)
        if os.access(str(auth_file.parent), os.W_OK):
            pytest.skip("directory permissions are not enforced here (root?)")
        assert spent == ["rt-old"]                      # one grant, never a second one
        assert seen == [({}, {"message": codex_auth.MSG_FILE_NOT_WRITABLE,
                              "code": BYOK_CODEX_REFRESH_FAILED_CODE})]
        assert json.loads(auth_file.read_text())["tokens"]["refresh_token"] == "rt-old"
    finally:
        (tmp_path / "old").chmod(0o700)


def test_a_newer_codex_login_during_the_refresh_is_kept_and_sent(monkeypatch, tmp_path):
    current = _live_jwt(3 * CODEX_REFRESH_MARGIN_S)

    def login(f, _r):
        _sign_in(f, current, "rt-cli")

    seen, auth_file, spent = _race(monkeypatch, tmp_path, login)
    assert spent == ["rt-old"]
    assert seen == [({"byok_key": current, "byok_account_id": "acct"}, None)]
    assert json.loads(auth_file.read_text())["tokens"]["refresh_token"] == "rt-cli"   # not overwritten


def test_a_reference_switched_during_the_refresh_sends_the_new_sign_in(monkeypatch, tmp_path):
    current = _live_jwt(3 * CODEX_REFRESH_MARGIN_S)
    other = tmp_path / "new" / "auth.json"

    def switch(_f, record):
        _sign_in(other, current, "rt-other")
        record["auth_path"] = str(other)                # the store now names another file

    seen, auth_file, spent = _race(monkeypatch, tmp_path, switch)
    assert spent == ["rt-old"]
    assert seen == [({"byok_key": current, "byok_account_id": "acct"}, None)]
    # The renewal still lands in the file it renewed: its CLI is not signed out.
    assert json.loads(auth_file.read_text())["tokens"]["refresh_token"] == "rt-renewed"
    assert json.loads(other.read_text())["tokens"]["refresh_token"] == "rt-other"


def test_a_failed_write_back_never_spends_the_refresh_token_twice(monkeypatch, tmp_path):
    """The write-back fails while the file still reads as writable (a Windows
    sharing lock, a full disk): the file keeps the token the renewal spent, so
    the second pass refuses instead of refreshing it again (a reuse the
    endpoint answers as revoked)."""
    import os

    def fail_replace(*_a, **_k):
        raise OSError("sharing violation")

    monkeypatch.setattr(os, "replace", fail_replace)
    seen, auth_file, spent = _race(monkeypatch, tmp_path, lambda _f, _r: None)
    assert spent == ["rt-old"]
    assert seen == [({}, {"message": codex_auth.MSG_FILE_NOT_WRITABLE,
                          "code": BYOK_CODEX_REFRESH_FAILED_CODE})]
    assert json.loads(auth_file.read_text())["tokens"]["refresh_token"] == "rt-old"
    assert [p.name for p in auth_file.parent.iterdir()] == ["auth.json"]   # temp file removed


def test_a_sign_in_that_changes_under_every_renewal_is_served_as_it_is_now(monkeypatch, tmp_path):
    """Two renewals in a row are superseded by new logins: the third state is
    served without renewing again — its token when still valid, else an
    accurate "expired" refusal, never a "not writable" one."""
    logins = iter([(EXPIRED, "rt-cli-1"), (_live_jwt(3 * CODEX_REFRESH_MARGIN_S), "rt-cli-2")])
    state = {}

    def relogin(f, _r):
        access, refresh = next(logins)
        state["current"] = access
        _sign_in(f, access, refresh)

    seen, auth_file, spent = _race(monkeypatch, tmp_path, relogin)
    assert spent == ["rt-old", "rt-cli-1"]
    assert seen == [({"byok_key": state["current"], "byok_account_id": "acct"}, None)]
    assert json.loads(auth_file.read_text())["tokens"]["refresh_token"] == "rt-cli-2"
