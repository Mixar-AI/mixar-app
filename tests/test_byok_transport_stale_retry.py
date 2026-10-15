# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sealed BYOK keys in transit — the two send paths and their one-shot resend.

The primitive, the cached server key and `prepare` are pinned in
`tests/test_byok_transport_seal.py`. Here: a turn refused with
``byok_transport_key_stale`` is resent exactly once by `turn_transport._send`
(new command id, bubble re-keyed, `retry_of` as the guard); a credential save
seals ``api_key`` on the worker thread, stores the plaintext locally and
repeats the PUT once on the same refusal; the transport refusals read as a
retry line in chat and never flip "Key needed on this device".
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
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from mixar.modules.byok.constants import (
    BYOK_KEY_REQUIRED_CODE,
    BYOK_KEY_UNSEALED_CODE,
    BYOK_TRANSPORT_KEY_STALE_CODE,
    BYOK_TRANSPORT_UNAVAILABLE_CODE,
    BYOK_TRANSPORT_UNREACHABLE_CODE,
)
from mixar.modules.byok.core import byok_client, credential_state, key_store, transport_seal, turn_credentials
from mixar.modules.common.api.exceptions import HTTPClientError
from mixar.modules.space_mixie_chat.core import byok_notice

SECRET = "sk-plain-0123456789"
RAW = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def unseal(envelope, private):
    """The backend's `unseal_with`: the RFC 9180 primitive directly (see test_byok_transport_seal.py)."""
    from mixar.modules.byok.core import hpke

    prefix, kid, body = envelope.split(".", 2)
    raw = _b64d(body)
    return hpke.open_(raw[:32], private, b"mixar-byok-transport/v1", kid.encode("utf-8"), raw[32:]).decode("utf-8")


@pytest.fixture(autouse=True)
def fresh_cache():
    transport_seal.invalidate()
    yield
    transport_seal.invalidate()


@pytest.fixture
def server():
    private = X25519PrivateKey.generate()
    return private, transport_seal.TransportKey("k1", _b64e(private.public_key().public_bytes(*RAW)))


class _InlineThread:
    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        self._target()


# --- the turn: one automatic resend on a stale server key ------------------------------

@pytest.fixture
def transport(monkeypatch, tmp_path):
    from mixar.modules.space_mixie_chat.constants import SessionState
    from mixar.modules.space_mixie_chat.core import queue_processor, rules_global, session, turn_transport

    bubble = SimpleNamespace(sender="USER", bubble_id="", delivery_hint="")
    scene = SimpleNamespace(name="SealScene", mixie_chat_rules="", mixie_chat_messages=[bubble])
    monkeypatch.setattr(sys.modules["bpy"].data, "scenes", {scene.name: scene})
    monkeypatch.setattr(rules_global, "_store_path", lambda: str(tmp_path / "global.json"))
    monkeypatch.setattr(session, "get_session_manager", lambda: SimpleNamespace(
        get_state=lambda _: SessionState.IDLE, set_state=lambda *a: None))
    monkeypatch.setattr(turn_transport, "collect_user_preferences", lambda: {})
    expects, calls, errors, invalidations = [], [], [], []
    monkeypatch.setattr(turn_transport.turn_events, "expect",
                        lambda scene, cid, cb=None: expects.append((cid, cb)))
    monkeypatch.setattr(turn_transport, "command",
                        lambda method, payload, ack, command_id=None: calls.append((method, dict(payload), command_id)))
    monkeypatch.setattr(queue_processor, "get_event_processor", lambda: SimpleNamespace(
        _clear_loader_bubbles=lambda target: None,
        handle_command_error=lambda result, target: errors.append(result)))
    monkeypatch.setattr(transport_seal, "invalidate", lambda: invalidations.append(True))
    seals = []

    def prepare(dispatch, method="chat", action=None):
        seals.append(method)
        dispatch({"byok_key": f"mxs1.k{len(seals)}.body"}, None)

    monkeypatch.setattr(turn_credentials, "prepare", prepare)
    handler = turn_transport.TurnTransport(scene.name)
    return SimpleNamespace(scene=scene, bubble=bubble, handler=handler, expects=expects, calls=calls,
                           errors=errors, invalidations=invalidations, seals=seals)


STALE = {"ok": False, "status_code": 409, "status": "failure", "code": BYOK_TRANSPORT_KEY_STALE_CODE,
         "message": "Mixar's key-sealing key changed. Try again."}


def test_a_stale_server_key_resends_the_command_once_under_a_new_id(transport):
    t = transport
    assert t.handler.start_stream("hi", "inst", "sess", user_message=t.bubble)
    first = t.calls[0][2]
    assert t.bubble.bubble_id == first and t.handler.last_command_id == first
    assert t.calls[0][1]["byok_key"] == "mxs1.k1.body"

    t.expects[0][1](t.scene, dict(STALE, command_id=first))
    assert t.invalidations == [True] and t.seals == ["chat", "chat"]
    assert len(t.calls) == 2 and t.calls[1][0] == "chat"
    second = t.calls[1][2]
    assert second != first
    assert t.calls[1][1]["byok_key"] == "mxs1.k2.body" and t.calls[1][1]["message"] == "hi"
    # The user bubble and the handler follow the resend; nothing was shown.
    assert t.bubble.bubble_id == second and t.handler.last_command_id == second
    assert t.errors == [] and t.expects[1][0] == second

    # A second refusal is shown like any BYOK error — never a third attempt.
    t.expects[1][1](t.scene, dict(STALE, command_id=second))
    assert len(t.calls) == 2 and t.invalidations == [True]
    assert [e["code"] for e in t.errors] == [BYOK_TRANSPORT_KEY_STALE_CODE]
    assert t.bubble.delivery_hint == "could not be delivered"


def test_the_json_rpc_error_shape_is_retried_too_and_input_commands_alike(transport):
    t = transport
    assert t.handler.start_input_stream("sess", "respond", text="yes", user_message=t.bubble)
    t.expects[0][1](t.scene, {"ok": False, "message": "rotated",
                              "data": {"status_code": 409, "code": BYOK_TRANSPORT_KEY_STALE_CODE}})
    assert len(t.calls) == 2 and t.calls[1][0] == "input" and t.calls[1][1]["text"] == "yes"
    assert t.invalidations == [True]


def test_other_byok_refusals_are_never_resent(transport):
    t = transport
    assert t.handler.start_stream("hi", "inst", "sess", user_message=t.bubble)
    for code in (BYOK_KEY_REQUIRED_CODE, BYOK_KEY_UNSEALED_CODE, BYOK_TRANSPORT_UNAVAILABLE_CODE):
        t.errors.clear()
        t.expects[-1][1](t.scene, {"ok": False, "status_code": 409, "code": code, "message": "m"})
        assert len(t.calls) == 1 and t.invalidations == [] and [e["code"] for e in t.errors] == [code]


def test_the_resend_lives_in_the_transport_not_the_error_handler():
    src = (SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core" / "turn_transport.py").read_text(encoding="utf-8")
    body = src[src.index("def settled(target, result):"):src.index("turn_events.expect(scene, command_id, settled)")]
    assert body.index("retry_of is None and _stale_transport_key(result)") < body.index("processor.handle_command_error(result, target)")
    stale = body[body.index("retry_of is None and _stale_transport_key(result)"):]
    assert "self._send(method, payload, None, interjecting, retry_of=command_id," in stale
    assert "transport_seal.invalidate()" in body
    qp = (SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core" / "queue_processor.py").read_text(encoding="utf-8")
    assert "transport_seal" not in qp and "retry_of" not in qp


# --- the save path seals ------------------------------------------------------------------

def _run_save(monkeypatch, service, api_key=SECRET, **kw):
    monkeypatch.setattr(byok_client, "get_agent_service", lambda: service)
    monkeypatch.setattr(byok_client, "threading", SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(byok_client, "_schedule_on_main", lambda fn, *a: fn(*a))
    stored = []
    monkeypatch.setattr(key_store, "save", lambda record, user_id=None: stored.append(record) or True)
    done = []
    byok_client.save_credentials("openai", "gpt-5", api_key, lambda *a: done.append(a), **kw)
    return done, stored


class _Service:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def save_credentials_all(self, **payload):
        self.calls.append(payload)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _stale_http():
    return HTTPClientError("rotated", status_code=409, response_data={
        "detail": {"status": "failure", "code": BYOK_TRANSPORT_KEY_STALE_CODE, "message": "rotated"}})


SAVED = SimpleNamespace(success=True, status_code=200,
                        data={"status": "success", "message": "", "data": {"byok_active": True, "items": []}})


def test_save_seals_the_api_key_and_stores_the_plaintext_locally(monkeypatch, server):
    private, key = server
    monkeypatch.setattr(transport_seal, "_fetch", lambda: key)
    service = _Service(SAVED)
    done, stored = _run_save(monkeypatch, service)
    assert done == [(True, {"byok_active": True, "items": []}, None)]
    sent = service.calls[0]["api_key"]
    assert transport_seal.is_envelope(sent) and unseal(sent, private) == SECRET
    assert SECRET not in repr(service.calls)
    assert stored[0]["provider"] == "openai" and stored[0]["key"] == SECRET


def test_save_refetches_and_repeats_the_put_once_on_a_stale_key(monkeypatch, server):
    private, key = server
    fetches = []
    monkeypatch.setattr(transport_seal, "_fetch", lambda: fetches.append(True) or key)
    service = _Service(_stale_http(), SAVED)
    done, _ = _run_save(monkeypatch, service)
    assert done[0][0] is True and len(service.calls) == 2 and len(fetches) == 2
    assert service.calls[0]["api_key"] != service.calls[1]["api_key"]
    assert unseal(service.calls[1]["api_key"], private) == SECRET

    service = _Service(_stale_http(), _stale_http(), SAVED)
    done, stored = _run_save(monkeypatch, service)
    assert len(service.calls) == 2 and done == [(False, None, "rotated")] and stored == []


def test_save_refuses_without_a_put_when_the_key_cannot_be_sealed(monkeypatch):
    monkeypatch.setattr(transport_seal, "_fetch", lambda: (_ for _ in ()).throw(
        transport_seal.SealError(transport_seal.MSG_TRANSPORT_UNAVAILABLE, BYOK_TRANSPORT_UNAVAILABLE_CODE)))
    service = _Service(SAVED)
    done, stored = _run_save(monkeypatch, service)
    assert service.calls == [] and stored == []
    assert done == [(False, None, transport_seal.MSG_TRANSPORT_UNAVAILABLE)]


def test_a_keyless_local_save_sends_no_key_and_never_fetches(monkeypatch):
    monkeypatch.setattr(transport_seal, "_fetch", lambda: (_ for _ in ()).throw(AssertionError("fetched")))
    service = _Service(SAVED)
    done, _ = _run_save(monkeypatch, service, api_key=None, base_url="http://127.0.0.1:1234/v1")
    assert done[0][0] is True and service.calls[0]["api_key"] is None


def test_other_409s_on_a_save_are_not_a_stale_key():
    other = HTTPClientError("m", status_code=409, response_data={"detail": {"code": "byok_key_required"}})
    assert not byok_client.is_stale_transport_key(other)
    assert not byok_client.is_stale_transport_key(HTTPClientError("m", status_code=400, response_data={
        "detail": {"code": BYOK_TRANSPORT_KEY_STALE_CODE}}))
    assert byok_client.is_stale_transport_key(_stale_http())
    assert byok_client.error_code(HTTPClientError("m", status_code=409, response_data={
        "code": BYOK_TRANSPORT_KEY_STALE_CODE})) == BYOK_TRANSPORT_KEY_STALE_CODE
    assert byok_client.error_code(HTTPClientError("m")) == ""


def test_a_save_logs_neither_the_plaintext_nor_an_envelope(monkeypatch, caplog, server):
    _, key = server
    monkeypatch.setattr(transport_seal, "_fetch", lambda: key)
    service = _Service(_stale_http(), _stale_http())
    with caplog.at_level(logging.DEBUG):
        _run_save(monkeypatch, service)
    assert SECRET not in caplog.text
    for call in service.calls:
        assert call["api_key"] not in caplog.text


# --- the chat line ----------------------------------------------------------------------------

def test_transport_refusals_are_a_retry_card_and_never_flip_the_device_key_card(monkeypatch):
    """A sealed-transport refusal becomes a Try-again (resend) card: the key on
    this device is fine, so it carries the server line, a resend action and no
    provider prefill, and never touches the device-key settings card."""
    touched = []
    monkeypatch.setattr(credential_state, "set_device_key_missing", touched.append)
    monkeypatch.setattr(credential_state, "refresh", lambda: touched.append("refresh"))
    monkeypatch.setattr(key_store, "check_presence_async", lambda *a: touched.append("checked"))
    for code, status in ((BYOK_TRANSPORT_KEY_STALE_CODE, 409), (BYOK_TRANSPORT_UNAVAILABLE_CODE, 503),
                         (BYOK_TRANSPORT_UNREACHABLE_CODE, None)):
        data = {"status_code": status, "code": code, "message": "server line"}
        card = byok_notice.refusal_card({"message": "server line", "data": data}, data)
        assert card.code == code and card.line == "server line"
        assert card.primary_action == byok_notice.ACTION_RESEND and card.primary_label == "Try again"
        assert not card.provider and "AI Provider Settings" not in card.line
    card = byok_notice.refusal_card({"message": "not sealed. Update Mixar and try again."},
                                    {"status_code": 400, "code": BYOK_KEY_UNSEALED_CODE})
    assert card.line == "not sealed. Update Mixar and try again."
    assert card.primary_action == byok_notice.ACTION_RESEND
    fallback = byok_notice.refusal_card({}, {"code": BYOK_KEY_UNSEALED_CODE})
    assert "Update Mixar" in fallback.line
    assert touched == []
