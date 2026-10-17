# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex credentials are handled on the desktop (pure parts).

The server no longer stores BYOK key material, so the client reads the Codex
CLI's ``auth.json`` in place, sends only the access token + ChatGPT account
id, and renews the access token before a turn — writing the new pair back
into that file. These pin the bpy-free pieces: bundle parsing (nested or
flat), the account-id claim fallback chain, the file read / write-back, the
24-hour expiry check and the refresh response classification.
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

from mixar.modules.byok.constants import CODEX_AUTH_CLAIM, CODEX_REFRESH_MARGIN_S
from mixar.modules.byok.core import codex_auth


def _jwt(claims: dict) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


def _account_token(account_id: str, **extra) -> str:
    return _jwt({CODEX_AUTH_CLAIM: {"chatgpt_account_id": account_id}, **extra})


# --- claims ----------------------------------------------------------------

def test_decode_claims_tolerates_non_jwts():
    assert codex_auth.decode_claims("") == {}
    assert codex_auth.decode_claims("not.a.jwt.at.all") == {}
    assert codex_auth.decode_claims("a.b.c") == {}
    assert codex_auth.decode_claims(_jwt({"exp": 5}))["exp"] == 5


def test_account_id_claim_is_read_from_the_openai_auth_claim():
    assert codex_auth.account_id_from_token(_account_token("acct_1")) == "acct_1"
    assert codex_auth.account_id_from_token(_jwt({"sub": "x"})) is None
    assert codex_auth.account_id_from_token(None) is None


# --- auth.json parsing -------------------------------------------------------

def test_parse_bundle_nested_tokens_prefers_explicit_account_id():
    bundle = json.dumps({
        "tokens": {
            "access_token": _account_token("from_access"),
            "refresh_token": "rt-1",
            "id_token": _account_token("from_id"),
            "account_id": "explicit",
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    })
    creds = codex_auth.parse_auth_bundle(bundle)
    assert creds.access_token.startswith("ey")
    assert creds.refresh_token == "rt-1"
    assert creds.account_id == "explicit"
    assert creds.id_token is not None


def test_parse_bundle_flat_falls_back_to_id_token_then_access_token():
    flat_id = json.dumps({
        "access_token": _account_token("from_access"),
        "refresh_token": "rt",
        "id_token": _account_token("from_id"),
    })
    assert codex_auth.parse_auth_bundle(flat_id).account_id == "from_id"

    flat_access = json.dumps({
        "access_token": _account_token("from_access"),
        "refresh_token": "rt",
    })
    assert codex_auth.parse_auth_bundle(flat_access).account_id == "from_access"


@pytest.mark.parametrize("text", ["", "{not json", "[]", "42"])
def test_parse_bundle_rejects_non_objects(text):
    with pytest.raises(codex_auth.CodexBundleError) as info:
        codex_auth.parse_auth_bundle(text)
    assert info.value.message == codex_auth.MSG_BUNDLE_INVALID


def test_parse_bundle_requires_both_tokens():
    with pytest.raises(codex_auth.CodexBundleError) as info:
        codex_auth.parse_auth_bundle(json.dumps({"tokens": {"access_token": _account_token("a")}}))
    assert info.value.message == codex_auth.MSG_BUNDLE_NO_TOKENS
    with pytest.raises(codex_auth.CodexBundleError) as info:
        codex_auth.parse_auth_bundle(json.dumps({"refresh_token": "rt"}))
    assert info.value.message == codex_auth.MSG_BUNDLE_NO_TOKENS


def test_parse_bundle_requires_an_account_id_somewhere():
    with pytest.raises(codex_auth.CodexBundleError) as info:
        codex_auth.parse_auth_bundle(json.dumps({
            "tokens": {"access_token": _jwt({"sub": "u"}), "refresh_token": "rt"},
        }))
    assert info.value.message == codex_auth.MSG_BUNDLE_NO_ACCOUNT


# --- expiry ------------------------------------------------------------------

def test_needs_refresh_inside_24h_window_or_without_exp():
    now = 1_000_000.0
    fresh = _jwt({"exp": now + CODEX_REFRESH_MARGIN_S + 60})
    stale = _jwt({"exp": now + CODEX_REFRESH_MARGIN_S - 60})
    gone = _jwt({"exp": now - 1})
    assert codex_auth.needs_refresh(fresh, now) is False
    assert codex_auth.needs_refresh(stale, now) is True
    assert codex_auth.needs_refresh(gone, now) is True
    assert codex_auth.needs_refresh(_jwt({"sub": "no-exp"}), now) is True
    assert codex_auth.needs_refresh("opaque", now) is True


def test_is_expired_is_strict_about_the_exp_claim():
    now = 50.0
    assert codex_auth.is_expired(_jwt({"exp": 51}), now) is False
    assert codex_auth.is_expired(_jwt({"exp": 50}), now) is True
    assert codex_auth.is_expired(_jwt({"exp": "soon"}), now) is True
    assert codex_auth.is_expired(_jwt({"exp": True}), now) is True
    assert codex_auth.token_expiry(_jwt({"exp": float("inf")})) is None


# --- refresh response --------------------------------------------------------

def test_refresh_ok_rotates_refresh_token_only_when_present():
    rotated = codex_auth.interpret_refresh_response(200, {"access_token": "at2", "refresh_token": "rt2"})
    assert (rotated.status, rotated.access_token, rotated.refresh_token) == ("ok", "at2", "rt2")
    kept = codex_auth.interpret_refresh_response(200, {"access_token": "at2"})
    assert (kept.status, kept.access_token, kept.refresh_token) == ("ok", "at2", None)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_refresh_4xx_means_the_sign_in_is_revoked(status):
    outcome = codex_auth.interpret_refresh_response(status, {"error": "invalid_grant"})
    assert outcome.status == "revoked"
    assert outcome.message == codex_auth.MSG_SIGN_IN_EXPIRED
    assert outcome.access_token is None


@pytest.mark.parametrize("status,body", [(500, {}), (502, None), (None, None), (200, {}), (200, "junk")])
def test_refresh_other_outcomes_are_transient(status, body):
    outcome = codex_auth.interpret_refresh_response(status, body)
    assert outcome.status == "network"
    assert outcome.access_token is None


# --- the CLI's file ----------------------------------------------------------

def test_default_path_follows_codex_home(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert codex_auth.default_auth_path().endswith("/.codex/auth.json")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "cx"))
    assert codex_auth.default_auth_path() == str(tmp_path / "cx" / "auth.json")
    assert codex_auth.resolve_auth_path("") == codex_auth.default_auth_path()
    assert codex_auth.resolve_auth_path("~/x.json").startswith("/")


def test_read_auth_file_reports_missing_unreadable_and_bad(tmp_path):
    with pytest.raises(codex_auth.CodexBundleError) as missing:
        codex_auth.read_auth_file(str(tmp_path / "none.json"))
    assert missing.value.message == codex_auth.MSG_FILE_MISSING
    f = tmp_path / "auth.json"
    f.write_text("{}")
    with pytest.raises(codex_auth.CodexBundleError) as bad:
        codex_auth.read_auth_file(str(f))
    assert bad.value.message == codex_auth.MSG_BUNDLE_NO_TOKENS
    f.write_text(json.dumps({"tokens": {"access_token": _account_token("a9"), "refresh_token": "rt"}}))
    assert codex_auth.read_auth_file(str(f)).account_id == "a9"


def test_write_back_keeps_the_cli_layout_and_is_owner_only(tmp_path):
    import os
    import stat

    nested = tmp_path / "nested.json"
    nested.write_text(json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None,
                                  "tokens": {"id_token": "id", "access_token": "a1", "refresh_token": "r1",
                                             "account_id": "acct"}, "last_refresh": "then"}))
    assert codex_auth.write_back(str(nested), "a2", "r2")
    data = json.loads(nested.read_text())
    assert data["tokens"] == {"id_token": "id", "access_token": "a2", "refresh_token": "r2", "account_id": "acct"}
    assert data["auth_mode"] == "chatgpt" and "OPENAI_API_KEY" in data
    assert data["last_refresh"].endswith("Z") and data["last_refresh"] != "then"
    assert stat.S_IMODE(os.stat(nested).st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["nested.json"]   # no temp file left behind

    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({"access_token": "a1", "refresh_token": "r1"}))
    assert codex_auth.write_back(str(flat), "a2")                       # no rotation: refresh kept
    assert json.loads(flat.read_text())["refresh_token"] == "r1"
    assert codex_auth.write_back(str(tmp_path / "gone.json"), "a2") is False


def test_write_back_into_a_read_only_place_fails_cleanly_and_is_known_beforehand(tmp_path):
    """A failed write-back must never raise (the turn would go out keyless),
    and `can_write_back` answers False BEFORE a refresh grant is spent, so a
    rotated refresh token is never lost — that would sign the CLI out too."""
    import os

    locked = tmp_path / "locked"
    locked.mkdir()
    f = locked / "auth.json"
    f.write_text(json.dumps({"access_token": "a1", "refresh_token": "r1"}))
    assert codex_auth.can_write_back(str(f)) is True
    locked.chmod(0o500)
    try:
        if os.access(str(locked), os.W_OK):
            pytest.skip("directory permissions are not enforced here (root?)")
        assert codex_auth.can_write_back(str(f)) is False
        assert codex_auth.write_back(str(f), "a2", "r2") is False   # no exception, nothing written
        assert json.loads(f.read_text())["refresh_token"] == "r1"
        assert sorted(p.name for p in locked.iterdir()) == ["auth.json"]
    finally:
        locked.chmod(0o700)
    f.chmod(0o400)
    try:
        if os.access(str(f), os.W_OK):
            pytest.skip("file permissions are not enforced here (root?)")
        assert codex_auth.can_write_back(str(f)) is False
    finally:
        f.chmod(0o600)
    assert codex_auth.can_write_back(str(tmp_path / "gone.json")) is False


def test_fingerprint_identifies_a_refresh_token_without_storing_it():
    assert codex_auth.fingerprint(None) is None
    fp = codex_auth.fingerprint("rt-secret")
    assert len(fp) == 16 and "rt-secret" not in fp and fp != codex_auth.fingerprint("rt-other")


def test_refresh_request_shape_and_secrecy():
    """The refresh grant uses the fixed client id/scope/UA and a 10 s budget,
    and the module never logs token material."""
    src = (SCRIPTS / "mixar" / "modules" / "byok" / "core" / "codex_auth.py").read_text(encoding="utf-8")
    assert "CODEX_TOKEN_URL, json=body" in src
    assert "timeout=CODEX_REFRESH_TIMEOUT_S" in src
    assert '"grant_type": "refresh_token"' in src
    assert "classify_network_error(" in src and "log_network_failure(" in src
    import re

    for banned in ("logger.info(\"%s\", refresh_token", "response.text"):
        assert banned not in src
    assert not re.search(r"(?<![A-Za-z_])print\(", src)   # `fingerprint(` is fine
