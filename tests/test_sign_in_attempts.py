# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One browser sign-in in flight, owned by its attempt; the autoshow waits
for Mixar to be the active app, not merely for the sign-in to end.

Three regressions from the first cut of the login-focus change (PR #1847):

1. A cancelled browser login (the user closed the tab) left the only Sign in
   button disabled and the bubble hidden until the 600 s SSO timeout. While
   waiting the panel now shows a status line and an explicit Cancel that
   ends the wait and brings Login with Browser back; Sign in from another
   surface (MCP dialog, F3) REPLACES the pending attempt.
2. A failed or timed-out login cleared the gate while the user was still in
   the browser, so the autoshow opened the bubble and `WM_window_open`
   activated Mixar over it. The gate now holds until `wm.mixar_app_active`.
3. One shared boolean, cleared by every flow's exit: the first flow to finish
   lifted the gate while another browser login was still open. Exits now
   release only their own attempt, and the automatic path never opens a
   second browser while one is in flight.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.common.utils import sign_in  # noqa: E402
from mixar.modules.space_mixie_chat.ui.operators import auth_ops  # noqa: E402
from mixar.modules.space_mixie_chat.ui.operators import sign_in_cancel_ops  # noqa: E402

LOGIN_PANEL = SCRIPTS / "mixar/modules/space_mixie_chat/ui/login_panel.py"
RNA_WM_MIXAR = ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar.cc"

CANCELLED = {"success": False, "message": "Login was cancelled or timed out", "cancelled": True}
FAILED = {"success": False, "message": "Login was cancelled or timed out"}
OK = {"success": True, "message": "Login successful"}


class _HeldThread:
    """A login thread the test starts by hand: the browser stays 'open'."""

    started = []

    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        _HeldThread.started.append(self)

    def run(self):
        self._target()

    def is_alive(self):
        return True


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(sign_in, "_attempt_id", 0)
    monkeypatch.setattr(sign_in, "_cancel", None)
    monkeypatch.setattr(sign_in, "_browser_handoff", False)
    _HeldThread.started = []

    wm = SimpleNamespace(
        mixie_chat_is_logging_in=False, mixie_chat_session_expired=False,
        mixie_chat_is_logged_in=False, mixie_chat_login_error="", windows=[],
        mixar_app_active=True,
    )
    monkeypatch.setattr(auth_ops.bpy.context, "window_manager", wm)
    monkeypatch.setattr(sign_in.bpy.context, "window_manager", wm)
    monkeypatch.setattr(
        auth_ops.bpy.context, "scene",
        SimpleNamespace(mixie_chat_user_id="", mixie_chat_credits=0),
    )

    def register(fn, first_interval=0.0, persistent=False):
        if first_interval <= 0.0:
            fn()

    monkeypatch.setattr(auth_ops.bpy.app.timers, "register", register)
    state = SimpleNamespace(wm=wm, outcomes=[], cancels=[], browsers=0, activations=0)

    def fake_sso(cancel=None):
        state.browsers += 1
        state.cancels.append(cancel)
        outcome = state.outcomes.pop(0)
        return outcome(cancel) if callable(outcome) else outcome

    def fake_activate():
        state.activations += 1
        return True

    monkeypatch.setattr(auth_ops, "sso_login", fake_sso)
    monkeypatch.setattr(auth_ops, "get_user_info", lambda: None)
    monkeypatch.setattr(auth_ops, "get_access_token", lambda: "")
    monkeypatch.setattr(
        auth_ops, "refresh_access_token", lambda: {"success": False, "retryable": False},
    )
    monkeypatch.setattr(auth_ops, "clear_credentials", lambda: None)
    monkeypatch.setattr(auth_ops, "activate_app", fake_activate)
    monkeypatch.setattr(auth_ops, "_capture_session_started", lambda *a, **k: None)
    monkeypatch.setattr(auth_ops, "_clear_referral_state", lambda wm: None)
    monkeypatch.setattr(auth_ops.threading, "Thread", _HeldThread)
    return state


def _click_sign_in(env):
    """Run the Sign in button; returns the held login thread (browser open)."""
    context = SimpleNamespace(window_manager=env.wm, screen=SimpleNamespace(areas=[]))
    assert auth_ops.MIXIE_CHAT_OT_login().execute(context) == {'FINISHED'}
    return _HeldThread.started[-1]


# ---------------------------------------------------------------------------
# 1. A cancelled browser login is never a dead end
# ---------------------------------------------------------------------------

def test_click_while_auto_sign_in_pending_replaces_it(env):
    """Startup SSO opened the browser; the user closed the tab and clicks
    Sign in. The old wait is cancelled and its exit leaves the new one be."""
    def user_clicks_while_waiting(cancel):
        env.new_thread = _click_sign_in(env)
        assert cancel.is_set()  # the old callback wait is told to stop
        return CANCELLED

    env.outcomes = [user_clicks_while_waiting, OK]
    auth_ops._auth_check_background()

    # The superseded auto attempt ended silently: no error, still waiting.
    assert env.wm.mixie_chat_is_logging_in is True
    assert env.wm.mixie_chat_login_error == ""
    assert auth_ops._auth_check_started is False

    env.new_thread.run()  # the user finishes in the new browser tab
    assert env.wm.mixie_chat_is_logging_in is False
    assert env.wm.mixie_chat_is_logged_in is True
    assert env.activations == 1


def test_second_click_replaces_the_first(env):
    first = _click_sign_in(env)
    second = _click_sign_in(env)
    assert env.wm.mixie_chat_is_logging_in is True
    assert sign_in.sign_in_pending()

    env.outcomes = [CANCELLED, FAILED]
    first.run()
    assert env.cancels[0].is_set()
    assert env.wm.mixie_chat_is_logging_in is True  # second still owns it
    assert env.wm.mixie_chat_login_error == ""

    second.run()
    assert env.wm.mixie_chat_is_logging_in is False
    assert "cancelled" in env.wm.mixie_chat_login_error
    assert env.activations == 0


def _cancel_sign_in(env):
    """Run the login panel's Cancel button."""
    context = SimpleNamespace(window_manager=env.wm)
    assert sign_in_cancel_ops.MIXIE_CHAT_OT_cancel_login().execute(context) == {'FINISHED'}


def test_waiting_shows_status_and_cancel_not_a_clickable_waiting_button():
    """A clickable "Waiting for browser..." silently started a second sign-in
    and orphaned the first browser tab."""
    src = LOGIN_PANEL.read_text()
    waiting = src.split("if wm.mixie_chat_is_logging_in:")[1].split("else:")[0]
    assert 'col.label(text="Continue in your browser"' in waiting
    assert 'col.operator("mixie_chat.cancel_login", text="Cancel")' in waiting
    assert '"mixie_chat.login"' not in waiting
    assert sign_in_cancel_ops.MIXIE_CHAT_OT_cancel_login.bl_options == {'INTERNAL'}


def test_cancel_brings_login_back_at_once_and_its_exit_is_silent(env):
    thread = _click_sign_in(env)
    env.wm.mixie_chat_login_error = "an older failure"
    _cancel_sign_in(env)
    assert env.wm.mixie_chat_is_logging_in is False  # Login with Browser again
    assert env.wm.mixie_chat_login_error == ""
    assert sign_in.sign_in_pending() is False

    env.outcomes = [CANCELLED]
    thread.run()  # the callback wait ends on the cancel event
    assert env.cancels[0].is_set()
    assert env.wm.mixie_chat_is_logging_in is False
    assert env.wm.mixie_chat_login_error == ""  # no "cancelled" error for a Cancel
    assert env.activations == 0


def test_cancel_then_sign_in_again_works(env):
    first = _click_sign_in(env)
    _cancel_sign_in(env)
    second = _click_sign_in(env)
    env.outcomes = [CANCELLED, OK]
    first.run()
    assert env.wm.mixie_chat_is_logging_in is True  # the new attempt owns it
    second.run()
    assert env.wm.mixie_chat_is_logged_in is True
    assert env.activations == 1


def test_cancel_of_the_automatic_sign_in(env):
    """Startup SSO opened the browser; the user cancels from the panel."""
    def user_cancels_while_waiting(cancel):
        _cancel_sign_in(env)
        assert cancel.is_set()
        return CANCELLED

    env.outcomes = [user_cancels_while_waiting]
    auth_ops._auth_check_background()
    assert env.wm.mixie_chat_is_logging_in is False
    assert env.wm.mixie_chat_login_error == ""
    assert env.wm.mixie_chat_session_expired is True  # still says log in again
    assert auth_ops._auth_check_started is False
    assert env.activations == 0


def test_stale_cancel_keeps_the_failure(env):
    """An open popover is not rebuilt when the sign-in fails while the user
    is in the browser; its stale Cancel must reveal the failure, not wipe it."""
    thread = _click_sign_in(env)
    env.outcomes = [FAILED]
    thread.run()
    assert env.wm.mixie_chat_login_error  # the failure is shown
    _cancel_sign_in(env)  # the stale Cancel still on screen
    assert env.wm.mixie_chat_login_error
    assert env.wm.mixie_chat_is_logging_in is False
    assert sign_in.sign_in_pending() is False


# ---------------------------------------------------------------------------
# 2. A failed sign-in never pulls Mixar over the browser
# ---------------------------------------------------------------------------

def test_failed_sign_in_holds_autoshow_until_mixar_is_active(env):
    env.wm.mixar_app_active = False  # the user is in the browser
    env.outcomes = [FAILED]
    auth_ops._auth_check_background()
    assert sign_in.sign_in_pending() is False
    assert env.activations == 0
    assert sign_in.sign_in_holds_autoshow() is True  # still in the browser

    env.wm.mixar_app_active = True  # the user comes back on their own
    assert sign_in.sign_in_holds_autoshow() is False
    env.wm.mixar_app_active = False  # leaving again later is not our business
    assert sign_in.sign_in_holds_autoshow() is False


def test_pending_sign_in_does_not_hide_the_bubble_from_a_returning_user(env):
    thread = _click_sign_in(env)
    env.wm.mixar_app_active = False
    assert sign_in.sign_in_holds_autoshow() is True
    env.wm.mixar_app_active = True  # back in Mixar, browser still waiting
    assert sign_in.sign_in_holds_autoshow() is False
    env.wm.mixar_app_active = False
    assert sign_in.sign_in_holds_autoshow() is True  # still in flight
    env.outcomes = [OK]
    thread.run()
    assert env.activations == 1


def test_without_a_focus_signal_the_gate_holds_only_while_in_flight(env, monkeypatch):
    monkeypatch.delattr(env.wm, "mixar_app_active")
    assert sign_in.app_is_active() is None
    thread = _click_sign_in(env)
    assert sign_in.sign_in_holds_autoshow() is True
    env.outcomes = [FAILED]
    thread.run()
    assert sign_in.sign_in_holds_autoshow() is False


def test_no_sign_in_never_holds_the_autoshow(env):
    env.wm.mixar_app_active = False
    assert sign_in.sign_in_holds_autoshow() is False


def test_native_focus_property_reads_window_activation():
    src = RNA_WM_MIXAR.read_text()
    getter = src.split("static bool rna_WindowManager_mixar_app_active_get")[1].split("\n}\n")[0]
    # 5.2: DNA lists are ListBaseT<T>, iterated by reference (no LISTBASE_FOREACH).
    assert "for (const wmWindow &win : wm->windows)" in getter
    assert "win.active" in getter
    assert "LISTBASE_FOREACH" not in getter
    assert 'RNA_def_property(srna_wm, "mixar_app_active", PROP_BOOLEAN, PROP_NONE)' in src
    assert '"rna_WindowManager_mixar_app_active_get", nullptr' in src


# ---------------------------------------------------------------------------
# 3. Each exit releases only its own attempt
# ---------------------------------------------------------------------------

def test_auto_path_never_opens_a_second_browser(env):
    _click_sign_in(env)  # the user's sign-in owns the browser
    env.outcomes = []
    auth_ops._auth_check_background()
    assert env.browsers == 0
    assert env.wm.mixie_chat_session_expired is True
    assert env.wm.mixie_chat_is_logging_in is True
    assert auth_ops._auth_check_started is False


def test_stale_watchdog_never_releases_a_newer_attempt(env):
    first = _click_sign_in(env)
    first_attempt = sign_in._attempt_id
    _click_sign_in(env)
    auth_ops._release_stuck_login(first_attempt, first)
    assert env.wm.mixie_chat_is_logging_in is True
    assert sign_in.sign_in_pending()
    assert env.wm.mixie_chat_login_error == ""


def test_finish_is_scoped_to_the_current_attempt(env):
    a1, c1 = sign_in.begin_sign_in(supersede=True)
    assert sign_in.begin_sign_in(supersede=False) is None
    a2, c2 = sign_in.begin_sign_in(supersede=True)
    assert c1.is_set() and not c2.is_set()
    assert sign_in.finish_sign_in(a1) is False
    assert sign_in.is_current_sign_in(a2)
    assert sign_in.finish_sign_in(a2) is True
    assert sign_in.finish_sign_in(a2) is False
    assert sign_in.sign_in_pending() is False
