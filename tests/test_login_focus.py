# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A browser sign-in owns the screen; Mixar comes back only when it succeeds.

On macOS the automatic startup auth check opened the SSO page in the
browser, and seconds later the Agent Bubble autoshow opened its native
window — `WM_window_open` → `[NSApp activateIgnoringOtherApps:YES]` — which
pulled Mixar in front of the browser while the user was typing their
password. After the login nothing brought Mixar back.

Two rules, pinned here:

1. A sign-in attempt is reserved in `common/utils/sign_in.py` BEFORE the
   browser opens (both the automatic SSO path and the Sign in button) and
   released on EVERY exit of that attempt — success, failure, exception and
   the stuck-login watchdog; `wm.mixie_chat_is_logging_in` mirrors it. All
   three autoshow entry points (`splash_watch_tick`, the autoshow retry loop
   and the file-load tick) RESCHEDULE while `sign_in_holds_autoshow()`, so the
   bubble appears by itself once Mixar is active again. The tour check stays
   ahead of the gate. Attempt ownership, supersede and the focus rule are
   pinned in `tests/test_sign_in_attempts.py`.
2. `activate_app()` (native `mixar.activate_app`) runs on the SUCCESS path
   only, never on a failed or cancelled login.
"""

import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.agent_bubble.core import bubble_autoshow  # noqa: E402
from mixar.modules.agent_bubble.core import bubble_lifecycle  # noqa: E402
from mixar.modules.agent_bubble.core import bubble_splash_watch  # noqa: E402
from mixar.modules.agent_bubble.core import bubble_state as _st  # noqa: E402
from mixar.modules.common.utils import app_activate, sign_in  # noqa: E402
from mixar.modules.space_mixie_chat.ui.operators import auth_ops  # noqa: E402

AUTH_OPS = SCRIPTS / "mixar/modules/space_mixie_chat/ui/operators/auth_ops.py"
BUBBLE_CORE = SCRIPTS / "mixar/modules/agent_bubble/core"
EDITOR = ROOT / "src/source/blender/editors/space_agent_bubble"
GHOST = ROOT / "src/intern/ghost/intern"

WATCHDOG_S = auth_ops.SSO_LOGIN_TIMEOUT_S + auth_ops._LOGIN_WATCHDOG_GRACE_S


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

def _wm():
    return SimpleNamespace(
        mixie_chat_is_logging_in=False,
        mixie_chat_session_expired=False,
        mixie_chat_is_logged_in=False,
        mixie_chat_login_error="",
        windows=[],
    )


@pytest.fixture
def timers(monkeypatch):
    """Run zero-delay timer callbacks at once; record the delayed ones."""
    registered = []

    def register(fn, first_interval=0.0, persistent=False):
        registered.append((fn, first_interval))
        if first_interval <= 0.0:
            fn()

    monkeypatch.setattr(auth_ops.bpy.app.timers, "register", register)
    return registered


@pytest.fixture
def flow(monkeypatch, timers):
    """Auth state for one sign-in: a fake browser, a fake /me, no keyring."""
    monkeypatch.setattr(sign_in, "_attempt_id", 0)
    monkeypatch.setattr(sign_in, "_cancel", None)
    monkeypatch.setattr(sign_in, "_browser_handoff", False)
    wm = _wm()
    monkeypatch.setattr(auth_ops.bpy.context, "window_manager", wm)
    monkeypatch.setattr(
        auth_ops.bpy.context, "scene",
        SimpleNamespace(mixie_chat_user_id="", mixie_chat_credits=0),
    )
    state = SimpleNamespace(
        wm=wm, timers=timers, activations=0, pending_at_browser=None,
        outcome={"success": True, "message": "Login successful"},
        me=[None],  # successive get_user_info() results; last one repeats
    )

    def fake_sso(cancel=None):
        state.pending_at_browser = sign_in.sign_in_pending()
        state.cancel = cancel
        if isinstance(state.outcome, BaseException):
            raise state.outcome
        return state.outcome

    def fake_me():
        value = state.me.pop(0) if len(state.me) > 1 else state.me[0]
        if isinstance(value, BaseException):
            raise value
        return value

    def fake_activate():
        state.activations += 1
        return True

    monkeypatch.setattr(auth_ops, "sso_login", fake_sso)
    monkeypatch.setattr(auth_ops, "get_user_info", fake_me)
    monkeypatch.setattr(auth_ops, "get_access_token", lambda: "")
    monkeypatch.setattr(
        auth_ops, "refresh_access_token",
        lambda: {"success": False, "retryable": False},
    )
    monkeypatch.setattr(auth_ops, "clear_credentials", lambda: None)
    monkeypatch.setattr(auth_ops, "activate_app", fake_activate)
    monkeypatch.setattr(auth_ops, "_capture_session_started", lambda *a, **k: None)
    monkeypatch.setattr(auth_ops, "_clear_referral_state", lambda wm: None)
    return state


def _watchdogs(timers):
    return [fn for fn, delay in timers if delay == WATCHDOG_S]


# ---------------------------------------------------------------------------
# Automatic SSO (startup auth check → definitive rejection → browser)
# ---------------------------------------------------------------------------

def test_auto_sso_sets_pending_before_browser_and_clears_on_success(flow):
    auth_ops._auth_check_background()
    assert flow.pending_at_browser is True
    assert flow.wm.mixie_chat_session_expired is False
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.wm.mixie_chat_is_logged_in is True
    assert flow.activations == 1
    assert len(_watchdogs(flow.timers)) == 1


def test_auto_sso_failure_clears_pending_without_activating(flow):
    flow.outcome = {"success": False, "message": "Login was cancelled or timed out"}
    auth_ops._auth_check_background()
    assert flow.pending_at_browser is True
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.wm.mixie_chat_is_logged_in is False
    assert "cancelled" in flow.wm.mixie_chat_login_error
    assert flow.activations == 0


def test_auto_sso_exception_clears_pending_without_activating(flow):
    flow.outcome = RuntimeError("browser exploded")
    auth_ops._auth_check_background()
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.wm.mixie_chat_is_logged_in is False
    assert flow.activations == 0


def test_auto_sso_profile_fetch_crash_still_clears_pending(flow):
    flow.me = [None, RuntimeError("/me down")]
    auth_ops._auth_check_background()
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.wm.mixie_chat_is_logged_in is True
    assert flow.activations == 1


def test_auto_sso_success_with_profile_applies_identity(flow):
    flow.me = [None, {"status": "success", "data": {"email": "a@b.c", "credits": 7}}]
    auth_ops._auth_check_background()
    assert auth_ops.bpy.context.scene.mixie_chat_user_id == "a@b.c"
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.activations == 1


def test_auto_sso_reserves_before_the_browser_without_the_main_thread(flow, monkeypatch):
    """The reservation is the gate: no main-thread round trip, no wait."""
    monkeypatch.setattr(auth_ops.bpy.app.timers, "register", lambda fn, **k: None)
    auth_ops._auth_check_background()
    assert flow.pending_at_browser is True
    assert flow.cancel is not None


def test_crash_after_reservation_releases_only_its_own_attempt(flow, monkeypatch):
    def boom(result):
        raise RuntimeError("profile fetch exploded")

    monkeypatch.setattr(auth_ops, "_user_info_after_sso", boom)
    auth_ops._auth_check_background_safe()
    assert sign_in.sign_in_pending() is False
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.cancel.is_set()
    assert auth_ops._auth_check_started is False


def test_crash_before_reservation_leaves_another_sign_in_alone(flow, monkeypatch):
    attempt, _ = sign_in.begin_sign_in(supersede=True)
    flow.wm.mixie_chat_is_logging_in = True
    monkeypatch.setattr(auth_ops, "_auth_check_background", lambda: 1 / 0)
    auth_ops._auth_check_background_safe()
    assert sign_in.is_current_sign_in(attempt)
    assert flow.wm.mixie_chat_is_logging_in is True
    assert auth_ops._auth_check_started is False


def test_stuck_login_watchdog_releases_pending(flow):
    auth_ops._auth_check_background()
    assert len(_watchdogs(flow.timers)) == 1  # armed by the auto path too
    attempt, cancel = sign_in.begin_sign_in(supersede=True)  # a wedged attempt
    flow.wm.mixie_chat_is_logging_in = True
    # A finished thread, or a stale attempt id, leaves the flag alone.
    dead = SimpleNamespace(is_alive=lambda: False)
    alive = SimpleNamespace(is_alive=lambda: True)
    assert auth_ops._release_stuck_login(attempt, dead) is None
    assert auth_ops._release_stuck_login(attempt - 1, alive) is None
    assert flow.wm.mixie_chat_is_logging_in is True
    # The thread this attempt belongs to is still wedged: release the UI.
    assert auth_ops._release_stuck_login(attempt, alive) is None
    assert flow.wm.mixie_chat_is_logging_in is False
    assert sign_in.sign_in_pending() is False
    assert cancel.is_set()  # its callback wait is told to stop
    assert "did not complete" in flow.wm.mixie_chat_login_error


# ---------------------------------------------------------------------------
# Manual Sign in button
# ---------------------------------------------------------------------------

class _SyncThread:
    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        self._target()

    def is_alive(self):
        return False


def _run_login_operator(monkeypatch, flow):
    monkeypatch.setattr(auth_ops.threading, "Thread", _SyncThread)
    context = SimpleNamespace(window_manager=flow.wm, screen=SimpleNamespace(areas=[]))
    return auth_ops.MIXIE_CHAT_OT_login().execute(context)


def test_manual_login_sets_pending_then_activates_on_success(flow, monkeypatch):
    assert _run_login_operator(monkeypatch, flow) == {'FINISHED'}
    assert flow.pending_at_browser is True
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.wm.mixie_chat_is_logged_in is True
    assert flow.activations == 1
    assert len(_watchdogs(flow.timers)) == 1


def test_manual_login_failure_clears_pending_without_activating(flow, monkeypatch):
    flow.outcome = {"success": False, "message": "Login was cancelled or timed out"}
    _run_login_operator(monkeypatch, flow)
    assert flow.pending_at_browser is True
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.wm.mixie_chat_is_logged_in is False
    assert flow.activations == 0


def test_manual_login_exception_clears_pending_without_activating(flow, monkeypatch):
    flow.outcome = OSError("Failed to start auth server")
    _run_login_operator(monkeypatch, flow)
    assert flow.wm.mixie_chat_is_logging_in is False
    assert flow.activations == 0


# ---------------------------------------------------------------------------
# The shared helpers
# ---------------------------------------------------------------------------

def test_sync_pending_flag_mirrors_the_registry(monkeypatch):
    monkeypatch.setattr(sign_in, "_cancel", None)
    wm = _wm()
    attempt, _ = sign_in.begin_sign_in(supersede=True)
    sign_in.sync_pending_flag(wm)
    assert wm.mixie_chat_is_logging_in is True
    assert sign_in.finish_sign_in(attempt) is True
    sign_in.sync_pending_flag(wm)
    assert wm.mixie_chat_is_logging_in is False
    # A build without the property, or no window manager, is tolerated.
    sign_in.sync_pending_flag(SimpleNamespace())
    sign_in.sync_pending_flag(None)


def test_activate_app_tolerates_a_build_without_the_operator(monkeypatch):
    monkeypatch.setattr(app_activate.bpy.ops, "mixar", SimpleNamespace(), raising=False)
    assert app_activate.activate_app() is False

    def raising():
        raise AttributeError("could not be found")

    monkeypatch.setattr(app_activate.bpy.ops, "mixar", SimpleNamespace(activate_app=raising))
    assert app_activate.activate_app() is False
    monkeypatch.setattr(
        app_activate.bpy.ops, "mixar",
        SimpleNamespace(activate_app=lambda: {'CANCELLED'}),
    )
    assert app_activate.activate_app() is False
    monkeypatch.setattr(
        app_activate.bpy.ops, "mixar",
        SimpleNamespace(activate_app=lambda: {'FINISHED'}),
    )
    assert app_activate.activate_app() is True


# ---------------------------------------------------------------------------
# Autoshow entry points
# ---------------------------------------------------------------------------

@pytest.fixture
def splash_gone(monkeypatch):
    """A dismissed splash and a fresh session, so a clear gate arms."""
    fake = SimpleNamespace(
        is_splash_visible=lambda: False, has_splash_ever_drawn=lambda: True,
    )
    boot = sys.modules.get("mixar.bootstrap")
    if boot is None:
        boot = types.ModuleType("mixar.bootstrap")
        boot.__path__ = []
        monkeypatch.setitem(sys.modules, "mixar.bootstrap", boot)
    monkeypatch.setattr(boot, "splash_menu", fake, raising=False)
    monkeypatch.setitem(sys.modules, "mixar.bootstrap.splash_menu", fake)
    monkeypatch.setattr(bubble_splash_watch.bpy.data, "filepath", "")
    monkeypatch.setattr(bubble_splash_watch, "has_agent_bubble_windows", lambda: False)
    monkeypatch.setattr(bubble_lifecycle, "has_agent_bubble_windows", lambda: False)
    monkeypatch.setattr(bubble_splash_watch, "_splash_watch_started_ts", None)
    return fake


@pytest.fixture
def gates(monkeypatch, splash_gone):
    """Patchable tour/sign-in state plus recorded arm/invoke calls."""
    state = SimpleNamespace(tour=False, pending=False, armed=[], invoked=[])
    for mod in (bubble_splash_watch, bubble_autoshow):
        monkeypatch.setattr(mod, "tour_running", lambda: state.tour)
    for mod in (bubble_splash_watch, bubble_autoshow, bubble_lifecycle):
        monkeypatch.setattr(mod, "sign_in_holds_autoshow", lambda: state.pending)
    monkeypatch.setattr(
        bubble_splash_watch, "arm_autoshow", lambda **kw: state.armed.append(kw),
    )
    monkeypatch.setattr(
        bubble_autoshow, "try_invoke_bubble",
        lambda start_minimised=False: state.invoked.append(start_minimised) or True,
    )
    monkeypatch.setattr(_st, "autoshow_attempts", 0)
    monkeypatch.setattr(_st, "load_autoshow_attempts", 0)
    return state


def test_splash_watch_reschedules_while_sign_in_pending(gates):
    gates.pending = True
    assert bubble_splash_watch.splash_watch_tick() == bubble_splash_watch.SPLASH_POLL_S
    assert gates.armed == []
    gates.pending = False
    assert bubble_splash_watch.splash_watch_tick() is None
    assert gates.armed == [{"reset": True}]


def test_splash_watch_tour_still_stops_the_watch(gates):
    gates.tour = True
    gates.pending = True
    assert bubble_splash_watch.splash_watch_tick() is None
    assert gates.armed == []


def test_autoshow_loop_reschedules_while_sign_in_pending(gates):
    gates.pending = True
    assert bubble_autoshow._autoshow_bubble_inner() == 0.5
    assert gates.invoked == []
    assert _st.autoshow_attempts == 0  # a wait is not an attempt
    gates.pending = False
    assert bubble_autoshow._autoshow_bubble_inner() is None
    assert gates.invoked == [False]


def test_autoshow_loop_tour_still_stops_the_loop(gates):
    gates.tour = True
    gates.pending = True
    assert bubble_autoshow._autoshow_bubble_inner() is None
    assert gates.invoked == []


def test_file_load_tick_reschedules_while_sign_in_pending(gates):
    gates.pending = True
    assert bubble_lifecycle._load_autoshow_tick_inner() == 0.3
    assert gates.invoked == []
    assert _st.load_autoshow_attempts == 0
    gates.pending = False
    assert bubble_lifecycle._load_autoshow_tick_inner() is None
    assert gates.invoked == [True]  # file-load autoshow starts minimised


# ---------------------------------------------------------------------------
# Source-level pins
# ---------------------------------------------------------------------------

def test_auto_path_reserves_before_the_browser_opens():
    src = AUTH_OPS.read_text()
    body = src.split("def _auth_check_background()")[1].split("_auth_check_started = False\n\n")[0]
    reserve = body.index("begin_sign_in(supersede=False)")
    browser = body.index("result = guest.sign_in(lambda: sso_login(cancel=cancel))")
    assert reserve < browser
    apply = body.split("def _apply_sso_result")[1]
    assert apply.index("finish_sign_in(attempt_id)") < apply.index("sync_pending_flag(wm)")


def test_activation_happens_only_inside_a_success_branch():
    src = AUTH_OPS.read_text()
    assert src.count("activate_app()") == 2
    start = 0
    while True:
        idx = src.find("activate_app()", start)
        if idx < 0:
            break
        before = src[:idx]
        success = max(before.rfind('if result.get("success"):'), before.rfind('if result["success"]:'))
        assert success > before.rfind("else:")
        start = idx + 1
    # Every exit of a flow mirrors the registry through the one helper.
    assert "mixie_chat_is_logging_in = " not in src
    assert src.count("sync_pending_flag(") >= 5
    assert "_arm_login_watchdog(attempt[0], sso_thread)" in src
    assert "_arm_login_watchdog(attempt_id, sso_thread)" in src


def test_every_autoshow_entry_point_gates_after_the_tour_check():
    splash = (BUBBLE_CORE / "bubble_splash_watch.py").read_text()
    tick = splash.split("def splash_watch_tick")[1]
    assert tick.index("tour_running()") < tick.index("sign_in_holds_autoshow()") < tick.index("arm_autoshow(")
    assert "return SPLASH_POLL_S" in tick.split("sign_in_holds_autoshow()")[1].split("try:")[0]

    autoshow = (BUBBLE_CORE / "bubble_autoshow.py").read_text()
    inner = autoshow.split("def _autoshow_bubble_inner")[1].split("def arm_autoshow")[0]
    assert inner.index("tour_running()") < inner.index("sign_in_holds_autoshow()") < inner.index("_st.autoshow_attempts += 1")

    lifecycle = (BUBBLE_CORE / "bubble_lifecycle.py").read_text()
    load = lifecycle.split("def _load_autoshow_tick_inner")[1].split("@contextmanager")[0]
    assert load.index("sign_in_holds_autoshow()") < load.index("_st.load_autoshow_attempts += 1")


def test_native_activation_primitive_is_wired():
    cc = (EDITOR / "space_agent_bubble.cc").read_text()
    assert 'ot->idname = "MIXAR_OT_activate_app";' in cc
    assert "WM_operatortype_append(MIXAR_OT_activate_app);" in cc
    exec_body = cc.split("static wmOperatorStatus mixar_activate_app_exec")[1].split("void MIXAR_OT_activate_app")[0]
    assert "Mixar_AppActivate(ghostwin);" in exec_body
    assert "#if defined(__APPLE__) || defined(_WIN32)" in exec_body
    assert 'extern "C" void Mixar_AppActivate(void *window_handle);' in cc
    assert "void MIXAR_OT_activate_app(wmOperatorType *ot);" in (EDITOR / "agent_bubble_intern.hh").read_text()

    cocoa = (GHOST / "GHOST_SystemCocoa.mm").read_text()
    cocoa_body = cocoa.split('extern "C" void Mixar_AppActivate')[1].split("\n}\n")[0]
    assert "[NSApp activateIgnoringOtherApps:YES];" in cocoa_body

    win32 = (GHOST / "GHOST_SystemWin32.cc").read_text()
    win_body = win32.split('extern "C" void Mixar_AppActivate')[1].split("\n}\n")[0]
    assert "Mixar_WindowMakeKey(window_handle);" in win_body
    assert "SW_RESTORE" in win_body
