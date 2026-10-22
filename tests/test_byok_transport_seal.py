# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sealed BYOK keys in transit.

Every key field that leaves this device — the per-turn ``byok_key`` and the
``api_key`` of a save — is sealed to the backend's X25519 transport key
(`byok/core/transport_seal.py`); the backend refuses plaintext. Pinned here
without the backend: a test-side `unseal` mirrors the backend's
``core/byok_transport.py`` so the vector (HKDF info, AAD, envelope string)
is fixed on this side too. Also: the cache + one-shot stale resend on the
turn path and the save path, the refusal when the key cannot be fetched,
and that no plaintext (or envelope) reaches a log line.
"""

import base64
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from mixar.modules.byok.constants import (
    BYOK_TRANSPORT_KEY_TTL_S,
    BYOK_TRANSPORT_UNAVAILABLE_CODE,
    BYOK_TRANSPORT_UNREACHABLE_CODE,
)
from mixar.modules.byok.core import byok_client, credential_state, key_store, transport_seal, turn_credentials
from mixar.modules.common.api.exceptions import HTTPClientError

SECRET = "sk-plain-0123456789"
RAW = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def unseal(envelope, private):
    """The backend's `unseal_with`: the envelope opened by the RFC 9180
    primitive directly (the client's `hpke.py` is a copy of the backend's,
    both pinned to the RFC's Appendix A.1 vectors in test_byok_hpke.py)."""
    from mixar.modules.byok.core import hpke

    prefix, kid, body = envelope.split(".", 2)
    assert prefix == "mxs1" and kid and "." not in body
    raw = _b64d(body)
    enc, ct = raw[:32], raw[32:]
    return hpke.open_(enc, private, b"mixar-byok-transport/v1", kid.encode("utf-8"), ct).decode("utf-8")


def _server_key(kid="k1"):
    private = X25519PrivateKey.generate()
    return private, transport_seal.TransportKey(kid, _b64e(private.public_key().public_bytes(*RAW)))


@pytest.fixture(autouse=True)
def fresh_cache():
    transport_seal.invalidate()
    yield
    transport_seal.invalidate()


@pytest.fixture
def server():
    private, key = _server_key()
    return private, key


# --- the primitive -------------------------------------------------------------

def test_seal_round_trips_through_the_backend_mirror(server):
    private, key = server
    envelope = transport_seal.seal_with(SECRET, key.public_key, key.kid)
    assert unseal(envelope, private) == SECRET
    assert transport_seal.is_envelope(envelope) and not transport_seal.is_envelope(SECRET)
    assert unseal(transport_seal.seal_with("clé ✓ 鍵", key.public_key, key.kid), private) == "clé ✓ 鍵"


def test_envelope_shape(server):
    private, key = server
    envelope = transport_seal.seal_with(SECRET, key.public_key, key.kid)
    prefix, kid, body = envelope.split(".")
    assert prefix == "mxs1" and kid == "k1"
    assert "=" not in body and set(body) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert len(_b64d(body)) == 32 + len(SECRET.encode()) + 16     # enc || ciphertext, nonce derived
    assert SECRET not in envelope and _b64e(SECRET.encode()) not in envelope
    # A fresh ephemeral key per envelope: sealing twice never repeats bytes.
    assert envelope != transport_seal.seal_with(SECRET, key.public_key, key.kid)


def test_the_kid_is_bound_as_aad_and_tampering_is_detected(server):
    private, key = server
    envelope = transport_seal.seal_with(SECRET, key.public_key, key.kid)
    prefix, kid, body = envelope.split(".")
    with pytest.raises(Exception):
        unseal(f"{prefix}.other.{body}", private)
    raw = bytearray(_b64d(body))
    raw[-1] ^= 0x01
    with pytest.raises(Exception):
        unseal(f"{prefix}.{kid}.{_b64e(bytes(raw))}", private)
    other, _ = _server_key()
    with pytest.raises(Exception):
        unseal(envelope, other)


# --- the cached server key ----------------------------------------------------------

def test_public_key_is_fetched_once_cached_for_the_ttl_and_dropped_by_invalidate(server):
    _, key = server
    fetches = []

    def fetch():
        fetches.append(True)
        return key

    assert transport_seal.public_key(fetch, now=0.0) is key
    assert transport_seal.public_key(fetch, now=10.0) is key
    assert len(fetches) == 1 and transport_seal.cached_kid() == "k1"
    assert transport_seal.public_key(fetch, now=BYOK_TRANSPORT_KEY_TTL_S + 1.0) is key
    assert len(fetches) == 2
    transport_seal.invalidate()
    assert transport_seal.cached_kid() is None
    transport_seal.public_key(fetch, now=BYOK_TRANSPORT_KEY_TTL_S + 2.0)
    assert len(fetches) == 3


def _service(monkeypatch, outcome):
    class Service:
        def get_transport_key(self):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    import mixar.modules.common.api as api

    monkeypatch.setattr(api, "get_agent_service", lambda: Service())
    monkeypatch.setattr("mixar.config.config.get_server_url", lambda: "https://api.example")


def _ok(data):
    return SimpleNamespace(success=True, status_code=200, data={"status": "success", "message": "", "data": data})


def test_fetch_parses_the_standard_envelope(monkeypatch, server):
    private, key = server
    _service(monkeypatch, _ok({"kid": "k1", "public_key": key.public_key,
                               "algorithm": "hpke-base/dhkem-x25519-hkdf-sha256/hkdf-sha256/aes-128-gcm",
                               "envelope": "mxs1", "kem_id": 32, "kdf_id": 1, "aead_id": 1}))
    assert transport_seal.public_key() == key
    assert unseal(transport_seal.seal(SECRET), private) == SECRET


@pytest.mark.parametrize("data", [
    None, {}, {"kid": "k1"}, {"kid": "", "public_key": "AAAA"},
    {"kid": "a.b", "public_key": _b64e(b"\0" * 32)},
    {"kid": "k1", "public_key": _b64e(b"\0" * 31)},
    {"kid": "k1", "public_key": "!!notbase64!!"},
    {"kid": "k1", "public_key": _b64e(b"\0" * 32), "algorithm": "rsa-oaep"},
    {"kid": "k1", "public_key": _b64e(b"\0" * 32), "envelope": "mxs2"},
])
def test_a_key_payload_this_client_cannot_seal_to_is_unavailable(monkeypatch, data):
    _service(monkeypatch, _ok(data))
    with pytest.raises(transport_seal.SealError) as info:
        transport_seal.seal(SECRET)
    assert info.value.code == BYOK_TRANSPORT_UNAVAILABLE_CODE
    assert info.value.message == transport_seal.MSG_TRANSPORT_UNAVAILABLE


def test_a_503_says_mixar_cannot_accept_keys_right_now(monkeypatch):
    _service(monkeypatch, HTTPClientError("no key", status_code=503, response_data={
        "detail": {"status": "failure", "code": "byok_transport_unavailable", "message": "no key"}}))
    with pytest.raises(transport_seal.SealError) as info:
        transport_seal.seal(SECRET)
    assert info.value.code == BYOK_TRANSPORT_UNAVAILABLE_CODE
    assert "cannot accept" in info.value.message


def test_a_network_failure_says_check_the_connection(monkeypatch):
    _service(monkeypatch, HTTPClientError("Failed to connect"))
    with pytest.raises(transport_seal.SealError) as info:
        transport_seal.seal(SECRET)
    assert info.value.code == BYOK_TRANSPORT_UNREACHABLE_CODE
    assert "connection" in info.value.message
    assert transport_seal.cached_kid() is None


def test_an_unexpected_fault_is_still_a_refusal_never_a_plaintext_fallback(monkeypatch):
    monkeypatch.setattr(transport_seal, "_fetch", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(transport_seal.SealError) as info:
        transport_seal.seal(SECRET)
    assert info.value.code == BYOK_TRANSPORT_UNAVAILABLE_CODE


# --- the turn: `prepare` seals ---------------------------------------------------------

class _InlineThread:
    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        self._target()


LOADED = {"byok_is_active": True, "byok_state_loaded": True, "byok_current_provider": "openai"}


def _run_prepare(monkeypatch, record, state=LOADED, **kw):
    monkeypatch.setattr(credential_state, "snapshot", lambda: dict(state))
    monkeypatch.setattr(key_store, "load", lambda *a, **k: record)
    monkeypatch.setattr(turn_credentials, "threading", SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(byok_client, "schedule_on_main", lambda fn, *a: fn(*a))
    flips = []
    monkeypatch.setattr(credential_state, "set_device_key_missing", flips.append)
    seen = []
    turn_credentials.prepare(lambda fields, error: seen.append((fields, error)), **kw)
    return seen, flips


def test_prepare_seals_the_key_field_and_never_emits_the_plaintext(monkeypatch, server):
    private, key = server
    monkeypatch.setattr(transport_seal, "_fetch", lambda: key)
    seen, flips = _run_prepare(monkeypatch, key_store.make_record("openai", SECRET))
    (fields, error), = seen
    assert error is None and flips == [False]
    assert set(fields) == {"byok_key"} and transport_seal.is_envelope(fields["byok_key"])
    assert unseal(fields["byok_key"], private) == SECRET
    assert SECRET not in repr(fields)


def test_prepare_seals_a_codex_access_token_and_leaves_the_account_id_plain(monkeypatch, server):
    private, key = server
    monkeypatch.setattr(transport_seal, "_fetch", lambda: key)
    import json
    token_claims = _b64e(json.dumps({"exp": 4_000_000_000}).encode())
    token = f"{_b64e(b'{}')}.{token_claims}.sig"
    record = {"provider": "codex", "key": token, "account_id": "acct", "refresh_token": "rt", "expired": False}
    monkeypatch.setattr(key_store, "materialize", lambda r: (r, None))
    state = dict(LOADED, byok_current_provider="codex")
    seen, _ = _run_prepare(monkeypatch, record, state)
    (fields, error), = seen
    assert error is None and fields["byok_account_id"] == "acct"
    assert unseal(fields["byok_key"], private) == token and token not in repr(fields)


def test_a_key_that_cannot_be_sealed_refuses_the_turn(monkeypatch):
    def fail():
        raise transport_seal.SealError(transport_seal.MSG_TRANSPORT_UNREACHABLE, BYOK_TRANSPORT_UNREACHABLE_CODE)

    monkeypatch.setattr(transport_seal, "_fetch", fail)
    seen, flips = _run_prepare(monkeypatch, key_store.make_record("openai", SECRET))
    assert seen == [({}, {"message": transport_seal.MSG_TRANSPORT_UNREACHABLE,
                          "code": BYOK_TRANSPORT_UNREACHABLE_CODE})]
    assert flips == [False]  # the key on this device is fine: no "key needed" pill


def test_keyless_turns_never_fetch_the_server_key(monkeypatch):
    monkeypatch.setattr(transport_seal, "_fetch", lambda: (_ for _ in ()).throw(AssertionError("fetched")))
    assert _run_prepare(monkeypatch, key_store.make_record("local", None))[0] == [({}, None)]
    assert _run_prepare(monkeypatch, None)[0] == [({}, None)]
    assert _run_prepare(monkeypatch, key_store.make_record("openai", SECRET),
                        method="input", action="abort")[0] == [({}, None)]
    assert _run_prepare(monkeypatch, key_store.make_record("openai", SECRET),
                        {"byok_is_active": False, "byok_state_loaded": True})[0] == [({}, None)]


def test_sealed_is_pure_over_a_resolution():
    blocked = turn_credentials.Resolution(error="x", code="byok_codex_expired")
    assert turn_credentials.sealed(blocked) is blocked
    empty = turn_credentials.Resolution()
    assert turn_credentials.sealed(empty) is empty


# --- no key material in any log line ------------------------------------------------------------

def test_neither_the_plaintext_nor_the_envelope_reaches_a_log_line(monkeypatch, caplog, server):
    private, key = server
    monkeypatch.setattr(transport_seal, "_fetch", lambda: key)
    with caplog.at_level(logging.DEBUG):
        envelope = transport_seal.seal(SECRET)
        seen, _ = _run_prepare(monkeypatch, key_store.make_record("openai", SECRET))
    assert SECRET not in caplog.text and envelope not in caplog.text
    assert seen[0][0]["byok_key"] not in caplog.text
    src = (SCRIPTS / "mixar" / "modules" / "byok" / "core" / "transport_seal.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if "logger." in line:
            assert "secret" not in line and "envelope" not in line and "api_key" not in line, line
