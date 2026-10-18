# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Guest mode: a token pair before any sign-in (docs/modules/guest-accounts.md).

Pins the client side of the backend's guest-accounts contract: the 403
``login_required`` refusal is a typed error that never refreshes, pauses or
opens the credits banner; the chat notice carries the cta's buttons; the
model picker greys hosted models; signing in claims the guest with the
refresh token the login replaced; the WS close 4009 stays a transient close.
"""

import ast
import json
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

from mixar.modules.auth.core import auth as auth_module  # noqa: E402
from mixar.modules.auth.core import guest  # noqa: E402
from mixar.modules.byok.core import model_menu  # noqa: E402
from mixar.modules.common.api import client as client_module  # noqa: E402
from mixar.modules.common.api.exceptions import (  # noqa: E402
    AuthenticationError,
    AuthorizationError,
    LoginRequiredError,
)
from mixar.modules.common.job_queue.core import error_helpers, failure_info  # noqa: E402

MODULES = SCRIPTS / "mixar" / "modules"


@pytest.fixture
def chat_core():
    """``space_mixie_chat.core`` imports the executor, whose digests need the
    bundled ``cryptography``: skip (never stub) in a venv without it, so the
    rest of the session collects exactly as it would otherwise."""
    pytest.importorskip("cryptography")
    from mixar.modules.space_mixie_chat.core import jsonrpc_frames, login_notice

    return SimpleNamespace(jsonrpc_frames=jsonrpc_frames, login_notice=login_notice)

REFUSAL = {
    "status": "failure",
    "message": "Sign in to Mixar to use this.",
    "data": {"code": "login_required", "cta": "login", "action_label": "Sign in"},
}


class _Response:
    def __init__(self, status_code, data, headers=None):
        self.status_code = status_code
        self._data = data
        self.ok = status_code < 400
        self.headers = headers or {}
        self.text = json.dumps(data)

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def _not_a_guest():
    guest._is_guest, guest._email = False, ""
    yield
    guest._is_guest, guest._email = False, ""


@pytest.fixture
def config(monkeypatch):
    store = {}
    monkeypatch.setattr(guest, "get_config", lambda: store)
    monkeypatch.setattr(guest, "add_config", lambda key, value: store.__setitem__(key, value))
    return store


@pytest.fixture(autouse=True)
def bundle(monkeypatch):
    """The credential bundle a deferred claim is kept in (no keychain)."""
    values = {}
    store = guest.credential_store
    monkeypatch.setattr(store, "get_value", lambda key: values.get(key))
    monkeypatch.setattr(store, "set_value", lambda key, value: values.__setitem__(key, value) or True)
    monkeypatch.setattr(store, "delete_value", lambda key: values.pop(key, None) is None or True)
    return values


def _jwt(sub):
    import base64
    claims = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"h.{claims}.s"


# --- the refusal body ---------------------------------------------------------

def test_refusal_is_read_from_every_wire_shape():
    flat = guest.login_required_fields(REFUSAL)
    detail = guest.login_required_fields({"detail": REFUSAL})
    rpc = guest.login_required_fields({"status_code": 403, **REFUSAL})
    assert flat == detail == rpc
    assert flat["cta"] == "login" and flat["message"] == "Sign in to Mixar to use this."

    limited = guest.login_required_fields({
        "status_code": 429, "message": "Sign in to keep going",
        "data": {"code": "guest_rate_limited", "retry_after_s": 3600},
    })
    assert limited["code"] == "guest_rate_limited" and limited["cta"] == "login"

    assert guest.login_required_fields({"data": {"code": "content_policy"}}) == {}
    assert guest.login_required_fields("Forbidden") == {}


# --- HTTP ---------------------------------------------------------------------

def test_http_403_login_required_is_typed_and_never_refreshed(monkeypatch):
    client = client_module.HTTPClient(base_url="https://api.example.test")
    refreshes = []
    monkeypatch.setattr(client_module, "refresh_access_token",
                        lambda: refreshes.append(1) or {"success": True})
    monkeypatch.setattr(client_module, "get_access_token", lambda: "guest-token")
    client._session = SimpleNamespace(request=lambda **kw: _Response(403, {
        **REFUSAL, "data": {**REFUSAL["data"], "cta": "login_or_byok"},
    }))

    with pytest.raises(LoginRequiredError) as caught:
        client.post("api/v1/job-queue/jobs", json={})

    assert caught.value.cta == "login_or_byok"
    assert caught.value.status_code == 403
    assert caught.value.message == "Sign in to Mixar to use this."
    assert not isinstance(caught.value, AuthenticationError)
    assert refreshes == []


def test_plain_403_is_still_a_permission_error():
    client = client_module.HTTPClient(base_url="https://api.example.test")
    error = client._map_exception(_Response(403, {"detail": {"message": "nope", "data": {}}}))
    assert isinstance(error, AuthorizationError)


# --- job queue ----------------------------------------------------------------

def test_a_guest_job_fails_as_sign_in_required_not_paused():
    error = LoginRequiredError("Sign in to Mixar to use this.", cta="login", status_code=403)
    # The queue pauses on AuthenticationError only; this is not one.
    assert not isinstance(error, AuthenticationError)
    assert failure_info._exception_class(error) == "auth"
    assert error_helpers.classify_error(error) == "Sign in to Mixar to use this"

    job = SimpleNamespace(error="", error_class="", error_reason="", user_message="",
                          vendor_code="", backend_job_id="")
    failure_info.apply_client_failure(job, error, stage="submit")
    assert job.error_class == "auth"
    assert failure_info.failure_headline(job) == "Sign-in required"
    assert job.user_message == "Sign in to Mixar to use this"


def test_failure_toast_offers_sign_in_for_the_auth_class():
    source = (MODULES / "common/job_queue/core/queue_manager.py").read_text()
    assert 'operator="mixie_chat.login"' in source
    assert 'error_class", "") == "auth"' in source


def test_a_guest_jobs_toast_says_it_once():
    """Toast: "Sign in to Mixar to use this" beside its Sign in button — not
    the reason again, not "Sign in, then retry." (the button is the retry).
    The queue row, which has no button, keeps the hint."""
    error = LoginRequiredError("Sign in to Mixar to use this.", cta="login", status_code=403)
    job = SimpleNamespace(error="", error_class="", error_reason="", user_message="",
                          vendor_code="", backend_job_id="")
    failure_info.apply_client_failure(job, error, stage="submit")
    assert failure_info.failure_details(job, include_ids=False, include_hint=False) == \
        "Sign in to Mixar to use this"
    assert failure_info.failure_details(job, include_ids=False).endswith("Sign in, then retry.")
    source = (MODULES / "common/job_queue/core/queue_manager.py").read_text()
    assert "include_hint=not actions" in source


# --- the chat notice ----------------------------------------------------------

class _Items(list):
    def add(self):
        item = SimpleNamespace(label="", value="", style="")
        self.append(item)
        return item


class _Messages(list):
    def add(self):
        msg = SimpleNamespace(bubble_id="", sender="", message_type="", content="", text="",
                              action_items=_Items())
        self.append(msg)
        return msg

    def remove(self, index):  # bpy collections remove by index
        del self[index]


def test_notice_buttons_follow_the_cta(chat_core):
    login_notice = chat_core.login_notice
    assert login_notice.notice_buttons("login") == [("Sign in", login_notice.SIGN_IN_CHAT_ACTION)]
    assert login_notice.notice_buttons("login_or_byok") == [
        ("Sign in", login_notice.SIGN_IN_CHAT_ACTION),
        ("Add your own key", login_notice.BYOK_DIALOG_CHAT_ACTION),
    ]
    assert login_notice.notice_buttons("fix_byok") == [
        ("Fix key", login_notice.BYOK_DIALOG_CHAT_ACTION),
        ("Sign in", login_notice.SIGN_IN_CHAT_ACTION),
    ]
    assert login_notice.notice_buttons("something_new") == login_notice.notice_buttons("login")


def test_notice_bubble_is_added_once_and_refreshed(monkeypatch, chat_core):
    login_notice = chat_core.login_notice
    monkeypatch.setattr(login_notice, "redraw_chat_areas", lambda: None)
    scene = SimpleNamespace(mixie_chat_messages=_Messages())

    login_notice.add_login_required_chat_message(scene, cta="login_or_byok", body="Sign in or add a key")
    login_notice.add_login_required_chat_message(scene, cta="login", body="Sign in to Mixar to use this.")

    assert len(scene.mixie_chat_messages) == 1
    msg = scene.mixie_chat_messages[0]
    assert msg.bubble_id.startswith(login_notice.LOGIN_BUBBLE_PREFIX)
    assert msg.sender == "AGENT"
    assert "**Sign in to continue**" in msg.content
    assert [(a.label, a.value, a.style) for a in msg.action_items] == [
        ("Sign in", login_notice.SIGN_IN_CHAT_ACTION, "PRIMARY"),
    ]


def test_chat_surfaces_route_the_refusal_to_the_notice():
    ops = (MODULES / "space_mixie_chat/ui/operators/chat_special_ops.py").read_text()
    assert "SIGN_IN_CHAT_ACTION" in ops and "return sign_in_clicked(context.scene)" in ops
    assert "BYOK_DIALOG_CHAT_ACTION" in ops and "mixar_byok.open_dialog" in ops
    processor = (MODULES / "space_mixie_chat/core/queue_processor.py").read_text()
    assert 'kind == "login_required"' in processor
    assert "login_required_fields(data)" in processor


# --- the model picker ---------------------------------------------------------

_MODELS = [
    {"provider_id": "anthropic", "model_id": "sonnet", "model_label": "Sonnet",
     "eligible": True, "thinking_levels": ["low", "high"]},
    {"provider_id": "google", "model_id": "gemini", "model_label": "Gemini", "eligible": True},
]








# --- guest session + claim ----------------------------------------------------

def test_create_guest_session_stores_the_pair(monkeypatch, config):
    stored = []
    monkeypatch.setattr(guest, "store_login_token_pair", lambda a, r: stored.append((a, r)) or (True, None))
    monkeypatch.setattr(guest, "get_device_id", lambda: "device-1")
    posted = {}

    def post(url, data=None, headers=None, timeout=None):
        posted.update(url=url, body=json.loads(data), headers=headers)
        return _Response(201, {"access_token": "a", "refresh_token": "r", "is_guest": True})

    monkeypatch.setattr(guest.requests, "post", post)
    assert guest.create_guest_session() == {"success": True}
    assert posted["url"].endswith("/api/v1/auth/guest")
    assert posted["body"]["device_id"] == "device-1"
    assert "Authorization" not in posted["headers"]
    assert stored == [("a", "r")]


def test_kill_switch_reports_disabled(monkeypatch, config):
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: _Response(403, {
        "detail": {"status": "failure", "message": "Guest accounts are unavailable.",
                   "data": {"code": "guest_accounts_disabled"}},
    }))
    result = guest.create_guest_session()
    assert result["success"] is False and result["disabled"] is True


def test_sign_in_claims_the_guest_with_the_replaced_refresh_token(monkeypatch, config):
    guest.mark(True, "guest-1@guest.mixar.invalid")
    monkeypatch.setattr(guest, "take_replaced_refresh_token", lambda: "guest-refresh")
    monkeypatch.setattr(guest, "get_access_token", lambda: "account-access")
    posted = {}

    def post(url, data=None, headers=None, timeout=None):
        posted.update(url=url, body=json.loads(data), headers=headers)
        return _Response(200, {"status": "success", "data": {"claimed": True, "byok_moved": ["default"]}})

    monkeypatch.setattr(guest.requests, "post", post)
    result = guest.sign_in(lambda: {"success": True})

    assert posted["url"].endswith("/api/v1/auth/guest/claim")
    assert posted["body"] == {"guest_refresh_token": "guest-refresh"}
    assert posted["headers"]["Authorization"] == "Bearer account-access"
    assert result["claimed_guest"] is True and result["switched_from_guest"] is True


def test_sign_in_as_an_account_never_claims(monkeypatch, config):
    monkeypatch.setattr(guest, "take_replaced_refresh_token", lambda: "old-account-refresh")
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: pytest.fail("claim must not be called"))
    result = guest.sign_in(lambda: {"success": True})
    assert result == {"success": True, "switched_from_guest": False}

    failed = guest.sign_in(lambda: {"success": False, "message": "cancelled"})
    assert failed == {"success": False, "message": "cancelled"}


def test_a_rejected_claim_is_a_plain_sign_in(monkeypatch, config):
    guest.mark(True, "guest-2@guest.mixar.invalid")
    monkeypatch.setattr(guest, "take_replaced_refresh_token", lambda: "guest-refresh")
    monkeypatch.setattr(guest, "get_access_token", lambda: "account-access")
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: _Response(409, {
        "detail": {"status": "failure", "message": "claimed", "data": {"code": "guest_already_claimed"}},
    }))
    result = guest.sign_in(lambda: {"success": True})
    assert result["claimed_guest"] is False and result["switched_from_guest"] is True


@pytest.mark.parametrize("status, retry", [
    (400, False), (409, False), (429, True), (500, True), (503, True), (418, True),
])
def test_claim_failures_are_final_or_transient(monkeypatch, status, retry):
    monkeypatch.setattr(guest, "get_access_token", lambda: "account-access")
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: _Response(status, {}))
    assert guest.claim_guest("guest-refresh") == {"claimed": False, "retry": retry}


def test_a_claim_that_never_reached_the_backend_is_transient(monkeypatch):
    monkeypatch.setattr(guest, "get_access_token", lambda: "account-access")

    def post(*a, **k):
        raise guest.requests.exceptions.Timeout("slow")

    monkeypatch.setattr(guest.requests, "post", post)
    assert guest.claim_guest("guest-refresh") == {"claimed": False, "retry": True}


def test_a_claim_reports_what_moved(monkeypatch):
    monkeypatch.setattr(guest, "get_access_token", lambda: "account-access")
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: _Response(200, {
        "status": "success", "data": {"claimed": True, "byok_moved": ["default"]},
    }))
    claim = guest.claim_guest("guest-refresh")
    assert claim["claimed"] is True and claim["retry"] is False
    assert claim["byok_moved"] == ["default"]


def _sign_in_over_a_guest(monkeypatch, response):
    guest.mark(True, "guest-4@guest.mixar.invalid")
    tokens = {"access": _jwt("guest-id")}
    monkeypatch.setattr(guest, "get_access_token", lambda: tokens["access"])
    monkeypatch.setattr(guest, "take_replaced_refresh_token", lambda: "guest-refresh")
    monkeypatch.setattr(guest.requests, "post", response)

    def login():
        tokens["access"] = _jwt("account-id")
        return {"success": True}

    return guest.sign_in(login)


def test_a_transient_claim_failure_is_kept_for_a_retry(monkeypatch, config, bundle):
    result = _sign_in_over_a_guest(monkeypatch, lambda *a, **k: _Response(503, {}))
    assert result["claimed_guest"] is False and result["switched_from_guest"] is True
    assert bundle[guest.PENDING_CLAIM_KEY] == {
        "guest_refresh_token": "guest-refresh",
        "guest_user_id": "guest-id",
        "guest_email": "guest-4@guest.mixar.invalid",
        "account_user_id": "account-id",
    }


def test_a_final_claim_failure_is_not_retried(monkeypatch, config, bundle):
    result = _sign_in_over_a_guest(monkeypatch, lambda *a, **k: _Response(409, {}))
    assert result["claimed_guest"] is False
    assert guest.PENDING_CLAIM_KEY not in bundle


def _pending(bundle, account="account-id"):
    bundle[guest.PENDING_CLAIM_KEY] = {
        "guest_refresh_token": "guest-refresh", "guest_user_id": "guest-id",
        "guest_email": "guest-5@guest.mixar.invalid", "account_user_id": account,
    }


def test_a_pending_claim_is_retried_and_carried_over(monkeypatch, bundle):
    _pending(bundle)
    monkeypatch.setattr(guest, "get_access_token", lambda: _jwt("account-id"))
    posted = {}

    def post(url, data=None, headers=None, timeout=None):
        posted.update(body=json.loads(data))
        return _Response(200, {"status": "success", "data": {"claimed": True, "byok_moved": ["default"]}})

    monkeypatch.setattr(guest.requests, "post", post)
    assert guest.retry_pending_claim() == {
        "claimed_guest": True, "byok_moved": ["default"],
        "guest_user_id": "guest-id", "guest_email": "guest-5@guest.mixar.invalid",
    }
    assert posted["body"] == {"guest_refresh_token": "guest-refresh"}
    assert guest.PENDING_CLAIM_KEY not in bundle


@pytest.mark.parametrize("status, kept", [(503, True), (429, True), (400, False), (409, False)])
def test_a_pending_claim_stays_only_while_failures_are_transient(monkeypatch, bundle, status, kept):
    _pending(bundle)
    monkeypatch.setattr(guest, "get_access_token", lambda: _jwt("account-id"))
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: _Response(status, {}))
    assert guest.retry_pending_claim() == {}
    assert (guest.PENDING_CLAIM_KEY in bundle) is kept


def test_a_pending_claim_is_never_made_for_another_account(monkeypatch, bundle):
    _pending(bundle, account="first-account")
    monkeypatch.setattr(guest, "get_access_token", lambda: _jwt("second-account"))
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: pytest.fail("claim must not be called"))
    assert guest.retry_pending_claim() == {}
    assert guest.PENDING_CLAIM_KEY not in bundle


def test_nothing_pending_is_nothing_to_retry(monkeypatch, bundle):
    monkeypatch.setattr(guest.requests, "post", lambda *a, **k: pytest.fail("claim must not be called"))
    assert guest.retry_pending_claim() == {}


def test_mark_persists_the_guest_marker(config):
    guest.mark(True, "guest-3@guest.mixar.invalid")
    assert guest.is_guest() and guest.email() == "guest-3@guest.mixar.invalid"
    assert guest.stored_pair_is_guest() is True
    guest.mark(False)
    assert not guest.is_guest() and guest.email() == ""
    assert guest.stored_pair_is_guest() is False


def test_login_keeps_the_replaced_refresh_token_under_the_fence(monkeypatch):
    store = {"access": "guest-a", "refresh": "guest-r"}
    monkeypatch.setattr(auth_module, "get_access_token", lambda: store["access"])
    monkeypatch.setattr(auth_module, "get_refresh_token", lambda: store["refresh"])
    monkeypatch.setattr(auth_module, "store_access_token", lambda t: store.__setitem__("access", t) or True)
    monkeypatch.setattr(auth_module, "store_refresh_token", lambda t: store.__setitem__("refresh", t) or True)
    monkeypatch.setattr(auth_module, "_delete_persisted_refresh_attempt", lambda: True)

    assert auth_module.store_login_token_pair("acct-a", "acct-r") == (True, None)
    assert auth_module.take_replaced_refresh_token() == "guest-r"
    assert auth_module.take_replaced_refresh_token() == ""  # taken once
    assert store == {"access": "acct-a", "refresh": "acct-r"}


# --- the socket ---------------------------------------------------------------

def test_close_4009_at_the_handshake_is_transient_not_auth(chat_core):
    jsonrpc_frames = chat_core.jsonrpc_frames
    pytest.importorskip("websocket")
    from websocket import ABNF

    class _WS:
        def settimeout(self, _):
            pass

        def recv_data(self, control_frame=True):
            return ABNF.OPCODE_CLOSE, (4009).to_bytes(2, "big") + b"in use"

    outcome, detail = jsonrpc_frames.wait_for_handshake(_WS(), timeout=1.0)
    assert outcome == jsonrpc_frames.HANDSHAKE_TRANSIENT
    assert "4009" in detail


# --- login paths --------------------------------------------------------------

def test_every_sign_in_path_goes_through_the_claiming_wrapper():
    source = (MODULES / "space_mixie_chat/ui/operators/auth_ops.py").read_text()
    tree = ast.parse(source)

    def _is_call_to(node, name):
        return isinstance(node, ast.Call) and ast.unparse(node.func) == name

    # Every sso_login(...) call must sit inside a guest.sign_in(...) argument
    # (the lambda that threads the cancel handle through).
    wrapped = {
        id(inner)
        for outer in ast.walk(tree) if _is_call_to(outer, "guest.sign_in")
        for arg in outer.args for inner in ast.walk(arg)
        if _is_call_to(inner, "sso_login")
    }
    bare = [
        node.lineno for node in ast.walk(tree)
        if _is_call_to(node, "sso_login") and id(node) not in wrapped
    ]
    assert bare == [], f"sso_login() called without guest.sign_in at lines {bare}"
    assert source.count("guest.sign_in(lambda: sso_login(cancel=cancel))") == 2
    # Startup without a pair and a sign-out both become a guest; a guest
    # that signs in leaves its session first.
    assert "_enter_guest_session(fallback=_reauthenticate)" in source
    # A refused sign-out guest is retried by the same fallback (logout, then
    # the retry worker, which reads the keyring off the main thread).
    assert source.count("_enter_guest_session, args=(_guest_seat_refused,)") == 1
    assert "_enter_guest_session(_guest_seat_refused)" in source
    assert source.count("_leave_guest_session(") == 3  # def + two apply paths
    # Every apply path moves the guest's state only through the one
    # post-claim step, after the account's identity is applied.
    assert source.count("_apply_guest_claim(") == 4  # def + startup + two sign-in paths
    for apply_path in ("_apply_sso_result", "_apply_result", "def _apply() -> None"):
        body = source[source.index(apply_path):]
        body = body[:body.index("_apply_account_hooks(user_info, is_guest)")]
        assert body.index("_apply_identity(") < body.index("_apply_guest_claim(")


def _carry_over_spies(monkeypatch):
    """``_apply_guest_claim``'s two effects, recorded: the device key record
    re-scoped (byok key_store) and the chat archive re-filed (chat_history,
    stubbed so the chat core's executor never loads)."""
    from mixar.modules.byok.core import key_store
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    calls = []
    monkeypatch.setattr(key_store, "reassign", lambda old, new: calls.append(("key", old, new)))
    monkeypatch.setattr(key_store, "current_user_id", lambda: "account-id")
    history = SimpleNamespace(reassign_owner=lambda old, new: calls.append(("chats", old, new)))
    monkeypatch.setitem(
        sys.modules, "mixar.modules.space_mixie_chat.core", SimpleNamespace(chat_history=history),
    )
    return auth_ops, calls


def test_a_claim_carries_the_guest_device_key_and_chats_to_the_account(monkeypatch):
    """QA 2026-10-14: after a claim the account's BYOK row was active server-side
    but the device reported the key missing — the local record is keyed by
    user id. The one post-claim step re-scopes it (account wins) and re-files
    the guest's chats, for a direct claim and a retried one alike."""
    auth_ops, calls = _carry_over_spies(monkeypatch)
    auth_ops._apply_guest_claim({
        "claimed_guest": True, "byok_moved": ["default"],
        "guest_user_id": "guest-id", "guest_email": "guest@guest.mixar.invalid",
    }, "user@example.com")
    assert calls == [
        ("key", "guest-id", "account-id"),
        ("chats", "guest@guest.mixar.invalid", "user@example.com"),
    ]


def test_a_failed_claim_moves_neither_key_nor_chats(monkeypatch, config, bundle):
    auth_ops, calls = _carry_over_spies(monkeypatch)
    result = _sign_in_over_a_guest(monkeypatch, lambda *a, **k: _Response(503, {}))
    auth_ops._apply_guest_claim(result, "user@example.com")
    auth_ops._apply_guest_claim({}, "user@example.com")
    assert calls == []


def test_account_validation_retries_a_pending_claim(monkeypatch):
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    retried = []
    monkeypatch.setattr(auth_ops.guest, "retry_pending_claim", lambda: retried.append(1) or {})
    monkeypatch.setattr(auth_ops.bpy.app.timers, "register", lambda fn, first_interval=0.0: None)
    auth_ops._schedule_apply_login({"data": {"email": "guest@x", "is_guest": True}}, refreshed=False)
    assert retried == []
    auth_ops._schedule_apply_login({"data": {"email": "user@example.com"}}, refreshed=False)
    assert retried == [1]


def test_a_sign_in_that_claimed_nothing_retries_a_pending_claim(monkeypatch):
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    monkeypatch.setattr(auth_ops, "get_user_info", lambda: {"status": "success"})
    monkeypatch.setattr(auth_ops.guest, "retry_pending_claim", lambda: {"claimed_guest": True})
    plain = {"success": True, "switched_from_guest": False}
    auth_ops._user_info_after_sso(plain)
    assert plain["claimed_guest"] is True

    monkeypatch.setattr(auth_ops.guest, "retry_pending_claim", lambda: pytest.fail("not retried"))
    claimed_now = {"success": True, "switched_from_guest": True, "claimed_guest": False}
    auth_ops._user_info_after_sso(claimed_now)
    assert auth_ops._user_info_after_sso({"success": False}) is None


def test_sign_out_drops_a_pending_claim(bundle):
    _pending(bundle)
    assert guest.clear_pending_claim() is True
    assert guest.PENDING_CLAIM_KEY not in bundle
    source = (MODULES / "space_mixie_chat/ui/operators/auth_ops.py").read_text()
    logout = source[source.index("class MIXIE_CHAT_OT_logout"):]
    logout = logout[:logout.index("return {'FINISHED'}")]
    assert "guest.clear_pending_claim()" in logout


def test_sign_out_starts_a_fresh_chat_in_every_tab():
    """QA 2026-10-14: after sign-out the fresh guest continued the account's
    open session and the backend refused it (-32013 Session unavailable).
    Sign-out runs the New Chat body on every tab that has a session or a
    transcript, before the socket drops and before the owner identity the
    History archive reads is cleared."""
    source = (MODULES / "space_mixie_chat/ui/operators/auth_ops.py").read_text()
    logout = source[source.index("class MIXIE_CHAT_OT_logout"):]
    body = logout[:logout.index("return {'FINISHED'}")]
    fresh = body.index("start_new_chat(open_scene)")
    assert fresh < body.index("manager.disconnect()")
    assert fresh < body.index('scene.mixie_chat_user_id = ""')
    assert "for open_scene in bpy.data.scenes" in body

    ops = (MODULES / "space_mixie_chat/ui/operators/session_ops.py").read_text()
    assert "def start_new_chat(scene, report=None)" in ops
    new_session = ops[ops.index("class MIXIE_CHAT_OT_new_session"):]
    assert "start_new_chat(context.scene, report=self.report)" in new_session


def test_signed_out_surfaces_admit_guests():
    panel = (MODULES / "space_mixie_chat/ui/login_panel.py").read_text()
    assert "mixie_chat_is_guest" in panel
    topbar = (MODULES / "space_mixie_chat/ui/topbar.py").read_text()
    assert 'caption = topbar_layout.account_label(wm, email, iface_("Guest"))' in topbar
    assert 'topbar_layout.account_signed_in(wm)' in topbar
    mirror = (MODULES / "byok/core/picker_mirror.py").read_text()
    assert 'guest=bool(getattr(target, "mixie_chat_is_guest", False))' in mirror


def test_guests_send_no_telemetry_and_no_usage_polls():
    capture = (MODULES / "common/analytics/capture.py").read_text()
    assert "if not _has_auth_token() or _is_guest():" in capture
    poller = (MODULES / "common/usage/core/poller.py").read_text()
    assert "mixie_chat_is_guest" in poller


# --- a socket whose auth gave up hands the session back --------------------

def _auth_ops(monkeypatch):
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    calls = []
    monkeypatch.setattr(auth_ops, "_auth_check_background", lambda: calls.append("check"))
    monkeypatch.setattr(auth_ops, "_enter_guest_session", lambda fallback: calls.append(("guest", fallback)))
    monkeypatch.setattr(auth_ops, "_reauthenticate", lambda: calls.append("reauth"))
    return auth_ops, calls


def test_recovery_with_a_live_pair_reruns_the_auth_check(monkeypatch):
    auth_ops, calls = _auth_ops(monkeypatch)
    monkeypatch.setattr(auth_ops, "get_access_token", lambda: "still-here")
    auth_ops._recover_session_background()
    assert calls == ["check"]


def test_recovery_replaces_a_dead_guest_pair_silently(monkeypatch):
    auth_ops, calls = _auth_ops(monkeypatch)
    monkeypatch.setattr(auth_ops, "get_access_token", lambda: "")
    monkeypatch.setattr(auth_ops.guest, "is_guest", lambda: True)
    auth_ops._recover_session_background()
    assert calls == [("guest", auth_ops._reauthenticate)]


def test_recovery_expires_a_dead_account_session(monkeypatch):
    auth_ops, calls = _auth_ops(monkeypatch)
    monkeypatch.setattr(auth_ops, "get_access_token", lambda: "")
    monkeypatch.setattr(auth_ops.guest, "is_guest", lambda: False)
    auth_ops._recover_session_background()
    assert calls == ["reauth"]


def test_terminal_socket_auth_failure_recovers_the_session(monkeypatch):
    """The reconnect loop stops only when a refresh can never help; that
    disconnect must re-run the auth check, or a guest whose pair died at
    runtime (kill switch, a token revoked or rotated elsewhere) sits OFFLINE
    with no token until a relaunch."""
    source = (MODULES / "space_mixie_chat/core/connection_manager.py").read_text()
    block = source[source.index("def on_disconnected("):source.index("def on_script_execute(")]
    assert "if terminal:" in block and "recover_session()" in block

    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    registered = []
    monkeypatch.setattr(auth_ops.bpy.app.timers, "register", lambda fn, first_interval=0.0: registered.append(fn))
    monkeypatch.setattr(auth_ops, "_last_recovery", 0.0)
    auth_ops.recover_session()
    auth_ops.recover_session()  # inside the window: one event
    assert len(registered) == 1


# --- session-started telemetry ------------------------------------------------

def test_a_guest_to_account_sign_in_captures_session_started_once(monkeypatch, config):
    """capture() drops a guest's events, and capture_session_started spends
    its once-guard even on a dropped one: the sign-in emits it only after
    _apply_identity has unmarked the guest."""
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    guest.mark(True, "guest-6@guest.mixar.invalid")
    captured = []
    monkeypatch.setattr(auth_ops, "_capture_session_started",
                        lambda method, refreshed=None: captured.append((method, guest.is_guest())))
    for name in ("sync_pending_flag", "redraw_sign_in_surfaces", "activate_app", "_arm_login_watchdog",
                 "_clear_referral_state", "_leave_guest_session", "_apply_guest_claim",
                 "_apply_account_hooks", "_apply_account_name"):
        monkeypatch.setattr(auth_ops, name, lambda *a, **k: None)
    monkeypatch.setattr(auth_ops, "begin_sign_in", lambda supersede: ("attempt", None))
    monkeypatch.setattr(auth_ops, "finish_sign_in", lambda attempt_id, cancel=False: True)
    monkeypatch.setattr(auth_ops.guest, "sign_in",
                        lambda login_fn: {"success": True, "switched_from_guest": True, "claimed_guest": True})
    monkeypatch.setattr(auth_ops, "_user_info_after_sso", lambda result: {
        "status": "success", "data": {"email": "user@example.com", "is_guest": False},
    })
    from mixar.modules.common.updates.core import toasts
    monkeypatch.setattr(toasts, "tag_topbar_redraw", lambda: None)
    wm = SimpleNamespace(mixie_chat_login_error="", mixie_chat_is_logged_in=False,
                         mixie_chat_is_guest=True)
    monkeypatch.setattr(auth_ops.bpy, "context", SimpleNamespace(window_manager=wm, scene=None), raising=False)
    monkeypatch.setattr(auth_ops.bpy.app.timers, "register", lambda fn, first_interval=0.0: fn())

    class _Thread:
        def __init__(self, target, **_):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(auth_ops.threading, "Thread", _Thread)
    auth_ops.MIXIE_CHAT_OT_login.execute(SimpleNamespace(), SimpleNamespace(window_manager=wm))

    assert captured == [("interactive_login", False)]
    assert wm.mixie_chat_is_guest is False and wm.mixie_chat_is_logged_in is True


def test_every_sign_in_path_captures_session_started_after_the_identity():
    source = (MODULES / "space_mixie_chat/ui/operators/auth_ops.py").read_text()
    for apply_path, method in (("def _apply_sso_result", "sso_relogin"),
                               ("def _apply_result", "interactive_login")):
        body = source[source.index(apply_path):]
        body = body[:body.index("\n    bpy.app.timers.register(") if apply_path == "def _apply_sso_result"
                    else body.index("return None  # Don't repeat")]
        call = f'_capture_session_started("{method}")'
        assert body.count(call) == 1
        assert body.index("_apply_identity(") < body.index(call)
        assert "if not guest.is_guest():" in body[:body.index(call)]


def test_an_identity_change_without_sign_out_starts_fresh_chats(monkeypatch, config):
    """A chat belongs to the identity that started it (the backend answers
    another's continued session "Session unavailable"). When a different
    identity applies without a sign-out — a guest whose token was lost gets a
    fresh guest — every tab holding another identity's chat starts a fresh
    one. A claim (the guest signing in to an account) keeps its chats."""
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops, session_ops
    reset = []
    monkeypatch.setattr(session_ops, "start_new_chat", lambda scene, report=None: reset.append(scene.name))

    def scenes(*owners):
        return [SimpleNamespace(name=f"s{i}", mixie_chat_user_id=owner, mixie_session_id=sid)
                for i, (owner, sid) in enumerate(owners)]

    a, b = "guest-a@guest.mixar.invalid", "guest-b@guest.mixar.invalid"
    tabs = scenes((a, "sess-1"), (b, "sess-2"), ("", "sess-3"), (a, ""))
    monkeypatch.setattr(auth_ops.bpy, "data", SimpleNamespace(scenes=tabs), raising=False)

    guest.mark(True, a)
    auth_ops._drop_foreign_chats(b, True)          # guest A -> fresh guest B
    assert reset == ["s0"]                         # B's own, unowned and empty tabs untouched

    reset.clear()
    auth_ops._drop_foreign_chats("user@example.com", False)  # guest A claimed into an account
    assert reset == ["s1"]                         # A's chats moved with the claim; B's did not

    reset.clear()
    guest.mark(False)
    auth_ops._drop_foreign_chats("other@example.com", False)  # account -> another account
    assert reset == ["s0", "s1"]
    guest.mark(False)


def _expire(monkeypatch, *, guest_session):
    """Run ``_reauthenticate``'s main-thread expiry with no browser sign-in."""
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    wm = SimpleNamespace(mixie_chat_is_logged_in=True, mixie_chat_is_guest=guest_session,
                         mixie_chat_session_expired=False)
    scene = SimpleNamespace(mixie_chat_user_id="guest-1@guest.mixar.invalid")
    timers = []
    monkeypatch.setattr(auth_ops.bpy, "context", SimpleNamespace(window_manager=wm, scene=scene),
                        raising=False)
    monkeypatch.setattr(auth_ops.bpy.app.timers, "register", lambda fn, **_: timers.append(fn))
    monkeypatch.setattr(auth_ops, "begin_sign_in", lambda supersede: None)
    monkeypatch.setattr(auth_ops, "sync_pending_flag", lambda _wm: None)
    monkeypatch.setattr(auth_ops, "redraw_sign_in_surfaces", lambda _wm: None)
    monkeypatch.setattr(guest, "_is_guest", guest_session)
    monkeypatch.setattr(guest, "add_config", lambda *_: None)
    auth_ops._reauthenticate()
    timers[0]()
    return wm, scene


def test_a_dead_guest_never_reads_as_a_signed_in_account(monkeypatch):
    wm, scene = _expire(monkeypatch, guest_session=True)
    assert (wm.mixie_chat_is_logged_in, wm.mixie_chat_is_guest) == (False, False)
    assert scene.mixie_chat_user_id == ""
    assert wm.mixie_chat_session_expired is True


def test_an_expired_account_keeps_its_address(monkeypatch):
    wm, scene = _expire(monkeypatch, guest_session=False)
    assert wm.mixie_chat_is_logged_in is True
    assert scene.mixie_chat_user_id == "guest-1@guest.mixar.invalid"


# --- a sign-out whose fresh guest was refused retries the seat ---------------

def _seat(monkeypatch, *, refusal, signed_in=False, token=""):
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    timers, threads, notices, keyring_reads = [], [], [], []
    monkeypatch.setattr(auth_ops.bpy.app, "timers", SimpleNamespace(
        register=lambda fn, first_interval=0.0: timers.append((fn, first_interval)),
        is_registered=lambda fn: False, unregister=lambda fn: None), raising=False)
    monkeypatch.setattr(auth_ops.bpy, "context", SimpleNamespace(
        window_manager=SimpleNamespace(mixie_chat_is_logged_in=signed_in)), raising=False)
    monkeypatch.setattr(auth_ops, "get_access_token", lambda: keyring_reads.append(1) or token)
    monkeypatch.setattr(auth_ops.threading, "Thread",
                        lambda target, args=(), **_: SimpleNamespace(start=lambda: threads.append(target)))
    monkeypatch.setattr(auth_ops, "_auth_check_started", False)
    monkeypatch.setattr(auth_ops, "_guest_retry_backoff", 0.0)
    monkeypatch.setattr(auth_ops, "_guest_refusal", refusal)
    from mixar.modules.space_mixie_chat.core import login_notice
    monkeypatch.setattr(login_notice, "add_login_required_chat_message",
                        lambda scene, body="", **_: notices.append(body))
    monkeypatch.setattr(auth_ops, "_qa_keyring_reads", keyring_reads, raising=False)
    return auth_ops, timers, threads, notices


def test_a_rate_limited_guest_is_retried_after_the_server_window(monkeypatch):
    auth_ops, timers, threads, notices = _seat(
        monkeypatch, refusal={"message": "Too many requests", "retry_after": 1200})
    auth_ops._guest_seat_refused()
    timers[0][0]()  # the main-thread scheduler
    assert timers[-1] == (auth_ops._retry_guest_seat, 1200)
    # The chat says why at once, without waiting for a send.
    assert len(notices) == 1 and "about 20 min" in notices[0]
    timers[-1][0]()
    assert threads == [auth_ops._retry_guest_seat_background]


def test_a_network_refusal_backs_off_and_caps(monkeypatch):
    auth_ops, timers, _, _ = _seat(monkeypatch, refusal={"message": "offline"})
    delays = []
    for _ in range(7):
        auth_ops._guest_seat_refused()
        delays.append(auth_ops._guest_retry_backoff)
    assert delays == [30, 60, 120, 240, 480, 600, 600]


def test_guests_switched_off_stay_signed_out(monkeypatch):
    auth_ops, timers, _, _ = _seat(monkeypatch, refusal={"disabled": True})
    auth_ops._guest_seat_refused()
    assert timers == [] and auth_ops._guest_retry_backoff == 0.0


def test_the_retry_stops_once_someone_holds_the_seat(monkeypatch):
    auth_ops, _, threads, _ = _seat(monkeypatch, refusal={}, signed_in=True)
    monkeypatch.setattr(auth_ops, "_guest_retry_backoff", 60.0)
    assert auth_ops._retry_guest_seat() is None
    assert threads == [] and auth_ops._guest_retry_backoff == 0.0


def test_a_send_with_no_session_says_why_in_the_chat(monkeypatch):
    auth_ops, _, threads, notices = _seat(
        monkeypatch, refusal={"retry_after": 1200})
    monkeypatch.setattr(auth_ops, "_guest_retry_backoff", 30.0)
    monkeypatch.setattr(auth_ops, "_guest_retry_due", auth_ops.time.monotonic() + 1200)
    assert auth_ops.guest_seat_unavailable(scene=None) is True
    assert "about 20 min" in notices[0] and threads == []


def test_a_send_after_the_window_tries_the_seat_at_once(monkeypatch):
    auth_ops, _, threads, notices = _seat(monkeypatch, refusal={"message": "offline"})
    monkeypatch.setattr(auth_ops, "_guest_retry_backoff", 30.0)
    monkeypatch.setattr(auth_ops, "_guest_retry_due", 0.0)
    assert auth_ops.guest_seat_unavailable(scene=None) is True
    assert threads == [auth_ops._retry_guest_seat_background] and notices
    assert auth_ops._qa_keyring_reads == []  # The send stayed off the keyring.


def test_a_send_while_signed_in_is_a_plain_connection_error(monkeypatch):
    auth_ops, _, _, notices = _seat(monkeypatch, refusal={}, signed_in=True)
    monkeypatch.setattr(auth_ops, "_guest_retry_backoff", 30.0)
    assert auth_ops.guest_seat_unavailable(scene=None) is False and notices == []


def test_a_429_carries_its_retry_after():
    response = SimpleNamespace(headers={"Retry-After": "1800"}, json=lambda: {})
    assert guest._retry_after(response) == 1800
    response = SimpleNamespace(headers={}, json=lambda: {"retry_after": "90"})
    assert guest._retry_after(response) == 90
    response = SimpleNamespace(headers={}, json=lambda: {})
    assert guest._retry_after(response) == 0


# --- the sign-in notice answers its own buttons -----------------------------

def _notice(monkeypatch, chat_core, cta="login_or_byok", **kwargs):
    login_notice = chat_core.login_notice
    monkeypatch.setattr(login_notice, "redraw_chat_areas", lambda: None)
    monkeypatch.setattr(login_notice, "_notices", {})
    scene = SimpleNamespace(mixie_chat_messages=_Messages())
    monkeypatch.setattr(login_notice.bpy, "data", SimpleNamespace(scenes=[scene]), raising=False)
    login_notice.add_login_required_chat_message(scene, cta=cta, body="Sign in or add a key", **kwargs)
    return login_notice, scene, scene.mixie_chat_messages[0]


def _signed_in_as(monkeypatch, login_notice, *, account):
    logins = []
    monkeypatch.setattr(login_notice.bpy, "context", SimpleNamespace(window_manager=SimpleNamespace(
        mixie_chat_is_logged_in=account, mixie_chat_is_guest=not account)), raising=False)
    monkeypatch.setattr(login_notice.bpy, "ops", SimpleNamespace(mixie_chat=SimpleNamespace(
        login=lambda: logins.append(1) or {'FINISHED'})), raising=False)
    return logins


def test_sign_in_click_waits_on_the_browser_then_settles(monkeypatch, chat_core):
    login_notice, scene, msg = _notice(monkeypatch, chat_core)
    logins = _signed_in_as(monkeypatch, login_notice, account=False)
    login_notice.sign_in_clicked(scene)
    assert logins == [1]
    assert "Finish signing in in your browser" in msg.content
    assert len(msg.action_items) == 2  # Clicking again restarts the sign-in.
    login_notice.session_ready(is_guest=False)
    assert msg.content.startswith("**You're signed in**") and len(msg.action_items) == 0


def test_sign_in_click_when_already_signed_in_settles_at_once(monkeypatch, chat_core):
    login_notice, scene, msg = _notice(monkeypatch, chat_core)
    logins = _signed_in_as(monkeypatch, login_notice, account=True)
    login_notice.sign_in_clicked(scene)
    assert logins == [] and msg.content.startswith("**You're signed in**")


def test_a_failed_sign_in_says_so_and_keeps_the_buttons(monkeypatch, chat_core):
    login_notice, scene, msg = _notice(monkeypatch, chat_core)
    _signed_in_as(monkeypatch, login_notice, account=False)
    login_notice.sign_in_clicked(scene)
    login_notice.sign_in_failed()
    assert "Sign-in didn't finish" in msg.content
    assert msg.content.startswith("**Sign in to use Mixar models") and len(msg.action_items) == 2


def test_a_saved_key_settles_only_a_notice_that_offered_one(monkeypatch, chat_core):
    login_notice, _, msg = _notice(monkeypatch, chat_core, cta="login")
    login_notice.key_saved()
    assert len(msg.action_items) == 1  # "Sign in" only: a key does not answer it.
    login_notice, _, msg = _notice(monkeypatch, chat_core, cta="login_or_byok")
    login_notice.key_saved()
    assert msg.content.startswith("**Your key is saved**") and len(msg.action_items) == 0


def test_a_guest_session_settles_only_a_no_session_notice(monkeypatch, chat_core):
    login_notice, _, msg = _notice(monkeypatch, chat_core)
    login_notice.session_ready(is_guest=True)
    assert len(msg.action_items) == 2  # A guest refused a paid model: still needs a sign-in.
    login_notice, _, msg = _notice(monkeypatch, chat_core, cta="login", resolves_on_guest=True)
    login_notice.session_ready(is_guest=True)
    assert msg.content.startswith("**Guest session started**")


def test_a_restored_notice_is_never_rewritten(monkeypatch, chat_core):
    login_notice, _, msg = _notice(monkeypatch, chat_core)
    monkeypatch.setattr(login_notice, "_notices", {})  # posted by an earlier run
    login_notice.session_ready(is_guest=False)
    assert len(msg.action_items) == 2


def _resend_rig(monkeypatch, chat_core, *, connected, sent=True):
    login_notice, scene, msg = _notice(monkeypatch, chat_core)
    scene.mixie_session_id = "s-1"
    from mixar.modules.space_mixie_chat.core import byok_resend
    resent = []
    monkeypatch.setattr(byok_resend, "pending", lambda sid: object() if sid == "s-1" else None)
    monkeypatch.setattr(byok_resend, "resend", lambda sid: resent.append(sid) or sent)
    monkeypatch.setattr(byok_resend, "_scene_for", lambda sid: scene)
    monkeypatch.setattr(login_notice, "_connected", lambda: connected)

    def run_now(fn, first_interval=0.0):
        while fn() is not None:
            pass
    monkeypatch.setattr(login_notice.bpy.app, "timers", SimpleNamespace(register=run_now), raising=False)
    return login_notice, scene, msg, resent


def test_a_sign_in_resends_the_refused_message_and_drops_the_notice(monkeypatch, chat_core):
    login_notice, scene, msg, resent = _resend_rig(monkeypatch, chat_core, connected=True)
    login_notice.session_ready(is_guest=False)
    assert resent == ["s-1"] and len(scene.mixie_chat_messages) == 0


def test_no_socket_in_time_asks_for_the_send(monkeypatch, chat_core):
    login_notice, scene, msg, resent = _resend_rig(monkeypatch, chat_core, connected=False)
    monkeypatch.setattr(login_notice, "_RESEND_WAIT_S", 0.0)
    login_notice.session_ready(is_guest=False)
    assert resent == [] and len(scene.mixie_chat_messages) == 1
    assert msg.content == "**You're signed in**\n\nSend your message again to continue."


def test_a_saved_key_resends_too(monkeypatch, chat_core):
    login_notice, scene, msg, resent = _resend_rig(monkeypatch, chat_core, connected=True)
    login_notice.key_saved()
    assert resent == ["s-1"] and len(scene.mixie_chat_messages) == 0


def test_the_transport_keeps_a_login_refusal_for_the_resend():
    transport = (MODULES / "space_mixie_chat/core/turn_transport.py").read_text()
    keep = transport[transport.index("if (byok_error_code("):transport.index("byok_resend.remember(")]
    assert "login_required_fields(result.get('data') or {})" in keep


def test_a_pending_guest_seat_lets_the_send_through(monkeypatch):
    """OFFLINE fails can_send, so without this the send operator's poll
    swallowed Enter and the chat never said why (found in the GUI run)."""
    auth_ops, _, _, _ = _seat(monkeypatch, refusal={"message": "offline"})
    assert auth_ops.guest_seat_pending() is False
    monkeypatch.setattr(auth_ops, "_guest_retry_backoff", 30.0)
    assert auth_ops.guest_seat_pending() is True
    auth_ops2, _, _, _ = _seat(monkeypatch, refusal={}, signed_in=True)
    monkeypatch.setattr(auth_ops2, "_guest_retry_backoff", 30.0)
    assert auth_ops2.guest_seat_pending() is False
    ops = (MODULES / "space_mixie_chat/ui/operators/chat_ops.py").read_text()
    poll = ops[ops.index("def poll(cls, context):"):ops.index("def execute(self, context):")]
    assert "if guest_seat_pending():" in poll
    props = (MODULES / "space_mixie_chat/ui/properties/chat_props.py").read_text()
    enter = props[props.index("def _execute_send_message"):props.index("def _report_send_refused")]
    assert "if not allowed and not guest_seat_pending():" in enter  # Enter pre-checks too


def test_the_retry_reads_the_keyring_only_on_its_worker(monkeypatch):
    """Review on #1902: no credential-store read on the main thread. The
    timer and a send decide from in-memory state; the worker reads the pair."""
    auth_ops, _, threads, _ = _seat(monkeypatch, refusal={"message": "offline"})
    monkeypatch.setattr(auth_ops, "_guest_retry_backoff", 30.0)
    auth_ops._retry_guest_seat()
    assert threads == [auth_ops._retry_guest_seat_background]
    assert auth_ops._qa_keyring_reads == []
    calls = []
    monkeypatch.setattr(auth_ops, "_enter_guest_session", lambda fallback: calls.append(("guest", fallback)))
    monkeypatch.setattr(auth_ops, "_auth_check_background_safe", lambda: calls.append("check"))
    auth_ops._retry_guest_seat_background()  # no pair stored: ask for a guest again
    assert calls == [("guest", auth_ops._guest_seat_refused)]
    monkeypatch.setattr(auth_ops, "get_access_token", lambda: "pair")
    calls.clear()
    auth_ops._retry_guest_seat_background()  # another Mixar signed in meanwhile
    assert calls == ["check"] and auth_ops._guest_retry_backoff == 0.0
