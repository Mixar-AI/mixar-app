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
    assert "SIGN_IN_CHAT_ACTION" in ops and "bpy.ops.mixie_chat.login()" in ops
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


def test_guest_sees_hosted_models_greyed_under_a_sign_in_note():
    rows = model_menu.build_rows(_MODELS, active_provider="anthropic", active_model="sonnet",
                                 active_thinking="low", guest=True)
    kinds = [row.kind for row in rows]
    assert kinds[0] == "NOTE" and rows[0].label == model_menu.GUEST_NOTE_TEXT
    assert all(not row.enabled for row in rows if row.kind in {"MODEL", "THINKING_MENU", "RESET"})
    assert [row.kind for row in rows if row.enabled] == ["BYOK"]


def test_guest_with_a_key_sees_the_key_note_only():
    rows = model_menu.build_rows(_MODELS, byok_active=True, guest=True,
                                 byok_provider_label="OpenAI", byok_model_label="gpt")
    notes = [row for row in rows if row.kind == "NOTE"]
    assert len(notes) == 1 and notes[0].label != model_menu.GUEST_NOTE_TEXT


def test_signed_in_rows_are_unchanged_by_the_guest_flag():
    rows = model_menu.build_rows(_MODELS)
    assert [row.enabled for row in rows if row.kind == "MODEL"] == [True, True]
    assert rows[0].kind == "MODEL"


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
    assert "_enter_guest_session, args=(_stay_signed_out,)" in source
    assert source.count("_leave_guest_session(") == 3  # def + two apply paths


def test_claim_carries_the_guest_device_key_to_the_account():
    """QA 2026-10-14: after a claim the account's BYOK row was active server-side
    but the device reported the key missing — the local record is keyed by
    user id. guest.sign_in reports the guest's id and the roles the claim
    moved; the post-SSO background step re-scopes the record (account wins)."""
    guest_src = (MODULES / "auth/core/guest.py").read_text()
    assert 'result["guest_user_id"] = guest_user_id' in guest_src
    assert 'result["byok_moved"] = list(claim.get("byok_moved") or [])' in guest_src
    ops = (MODULES / "space_mixie_chat/ui/operators/auth_ops.py").read_text()
    after_sso = ops[ops.index("def _user_info_after_sso"):ops.index("def _carry_guest_device_key")]
    assert "_carry_guest_device_key(result)" in after_sso
    carry = ops[ops.index("def _carry_guest_device_key"):]
    carry = carry[:carry.index("\ndef ")]
    assert "key_store.reassign(result[\"guest_user_id\"], key_store.current_user_id())" in carry
    assert 'result.get("byok_moved")' in carry


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
    assert 'account.label(text="Guest")' in topbar
    assert "mixie_chat_is_logged_in', False) and not guest" in topbar
    menu = (MODULES / "byok/ui/menus/agent_model_menu.py").read_text()
    assert "guest=bool(getattr(context.window_manager, \"mixie_chat_is_guest\"" in menu


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
