# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A bubble window that cannot be created is tried once, not 70 times.

Prod 4.4.0, Windows, AMD integrated GPU: the OS refused the Agent Bubble
window a GL context. ``MIXAR_OT_agent_bubble_show_window`` then reports
"Failed to open Agent Bubble window" and ``try_invoke_bubble`` sees a
RuntimeError. Before the latch, the file-load tick retried every 0.25 s up
to 40 times and the autoshow loop 30 more, each attempt another failed
window (and, on Windows, another modal "Unsupported Graphics Card" box).

Pinned here:

1. The first such failure latches ``bubble_state.window_unavailable``; the
   autoshow loop and the file-load tick stop at once and do not invoke again
   until the next file load, which clears the latch (a GL failure can be
   transient: a locked or remote session, a driver reset) and tries once.
2. The signal is the RuntimeError itself, not its (translated) text: the
   native operator has no poll and reports only the window failure, and the
   Python wrapper's poll always passes. A not-yet-registered operator
   (AttributeError, startup) does not latch.
3. An explicit open (``mixar.agent_bubble_open_window``, Shift+M) ignores
   the latch, tries once, reports the failure without a modal box, and
   clears the latch when the window does open.
"""

import importlib.util
import sys
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
from mixar.modules.agent_bubble.core import bubble_state as _st  # noqa: E402

OPERATORS = SCRIPTS / "mixar/modules/agent_bubble/ui/operators"
GHOST_WIN32 = ROOT / "src/intern/ghost/intern/GHOST_WindowWin32.cc"
BUBBLE_CC = ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"

WINDOW_FAILED = RuntimeError("Error: Failed to open Agent Bubble window\n")
NOT_REGISTERED = AttributeError(
    'Calling operator "bpy.ops.mixar.agent_bubble_show_window" error, '
    "could not be found"
)


class _Op:
    """Records calls; raises ``error`` (if set) or returns ``result``."""

    def __init__(self, error=None, result=frozenset({"FINISHED"})):
        self.calls = 0
        self.error = error
        self.result = set(result)

    def __call__(self, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def bubble(monkeypatch):
    """Autoshow + file-load loops wired to a fake bubble operator."""
    fake_splash = SimpleNamespace(is_splash_visible=lambda: False)
    boot = sys.modules.get("mixar.bootstrap")
    if boot is None:
        boot = types.ModuleType("mixar.bootstrap")
        boot.__path__ = []
        monkeypatch.setitem(sys.modules, "mixar.bootstrap", boot)
    monkeypatch.setattr(boot, "splash_menu", fake_splash, raising=False)
    monkeypatch.setitem(sys.modules, "mixar.bootstrap.splash_menu", fake_splash)

    for mod in (bubble_autoshow, bubble_lifecycle):
        monkeypatch.setattr(mod, "sign_in_holds_autoshow", lambda: False)
    monkeypatch.setattr(bubble_autoshow, "tour_running", lambda: False)
    monkeypatch.setattr(bubble_lifecycle, "_is_app_exiting", lambda: False)
    monkeypatch.setattr(bubble_lifecycle, "has_agent_bubble_windows", lambda: False)

    window = SimpleNamespace(screen=object())
    monkeypatch.setattr(
        bubble_autoshow, "find_target_context",
        lambda: (window, object(), object()),
    )
    # Patch through the module's own bpy: the suite swaps the global mock.
    bpy = bubble_autoshow.bpy
    monkeypatch.setattr(bpy.context.window_manager, "windows", [], raising=False)
    op = _Op(error=WINDOW_FAILED)
    monkeypatch.setattr(
        bpy.ops, "mixar",
        SimpleNamespace(agent_bubble_show_window=op, agent_bubble_open_window=op),
        raising=False,
    )
    monkeypatch.setattr(_st, "window_unavailable", False, raising=False)
    monkeypatch.setattr(_st, "autoshow_attempts", 0)
    monkeypatch.setattr(_st, "load_autoshow_attempts", 0)
    monkeypatch.setattr(_st, "autoshow_start_minimised", False)
    return op


def _run(tick, limit=100):
    """Drive a retry timer the way bpy.app.timers would; return tick count."""
    for count in range(1, limit + 1):
        if tick() is None:
            return count
    return limit


# ---------------------------------------------------------------------------
# 1. The latch stops both retry loops after one failed window
# ---------------------------------------------------------------------------

def test_file_load_tick_stops_after_first_failed_window(bubble):
    ticks = _run(bubble_lifecycle._load_autoshow_tick_inner)
    assert bubble.calls == 1
    assert ticks == 1
    assert getattr(_st, "window_unavailable", None) is True
    assert _st.load_autoshow_attempts == 0


def test_autoshow_loop_stops_after_first_failed_window(bubble):
    ticks = _run(bubble_autoshow._autoshow_bubble_inner)
    assert bubble.calls == 1
    assert ticks == 1
    assert _st.window_unavailable is True


def test_latch_holds_across_retry_loops(bubble):
    """File load fails once; autoshow (workspace change, splash) and a
    re-armed file-load tick never invoke the operator again."""
    _run(bubble_lifecycle._load_autoshow_tick_inner)
    _run(bubble_autoshow._autoshow_bubble_inner)
    _run(bubble_lifecycle._load_autoshow_tick_inner)
    assert bubble.calls == 1
    assert bubble_autoshow.try_invoke_bubble(start_minimised=True) is False
    assert bubble.calls == 1


def test_next_file_load_clears_latch_and_tries_once(bubble, monkeypatch):
    _run(bubble_lifecycle._load_autoshow_tick_inner)
    assert _st.window_unavailable is True
    monkeypatch.setattr(bubble_lifecycle, "close_restored_agent_bubble_windows", lambda: 0)
    monkeypatch.setattr(bubble_lifecycle.pill_icons, "refresh", lambda: None)
    bubble_lifecycle.reset_restored_bubbles_after_load()
    assert _st.window_unavailable is False
    _run(bubble_lifecycle._load_autoshow_tick_inner)
    assert bubble.calls == 2
    assert _st.window_unavailable is True


def test_any_runtime_error_latches_whatever_its_text(bubble):
    """Blender translates the report (``RPT_``); the latch never reads it."""
    bubble.error = RuntimeError(
        "Erreur : Impossible d'ouvrir la fenêtre Agent Bubble\n"
    )
    assert bubble_autoshow.try_invoke_bubble() is False
    assert _st.window_unavailable is True


# ---------------------------------------------------------------------------
# 2. A not-yet-registered operator keeps retrying (startup depends on it)
# ---------------------------------------------------------------------------

def test_unregistered_operator_does_not_latch(bubble):
    bubble.error = NOT_REGISTERED
    assert bubble_lifecycle._load_autoshow_tick_inner() == 0.25
    assert bubble_autoshow._autoshow_bubble_inner() == 0.5
    assert _st.window_unavailable is False
    assert bubble.calls == 2


def _function_body(src: str, start: str) -> str:
    body = src[src.index(start):]
    return body[:body.index("\n}\n")]


def test_native_operator_errors_only_when_the_window_fails():
    """The latch treats any RuntimeError as a refused window. That holds
    only while the native operator has no poll and its one error report is
    the WM_window_open failure."""
    src = BUBBLE_CC.read_text(encoding="utf-8")
    exec_body = _function_body(src, "static wmOperatorStatus agent_bubble_show_window_exec")
    assert exec_body.count("RPT_ERROR") == 1
    assert "if (win == nullptr) {" in exec_body
    register = _function_body(src, "void MIXAR_OT_agent_bubble_show_window(wmOperatorType *ot)")
    assert "ot->poll" not in register
    wrapper = (OPERATORS / "window_ops.py").read_text(encoding="utf-8")
    poll = wrapper[wrapper.index("def poll(cls, context):"):wrapper.index("def execute(")]
    assert "return context.window_manager is not None" in poll


# ---------------------------------------------------------------------------
# 3. An explicit open still tries once and reports without a modal box
# ---------------------------------------------------------------------------

def _load_operator_module(monkeypatch, filename, fake_bpy):
    """Import an operator file against a bpy whose Operator is a real class
    (the suite-wide mock may have turned operator classes into mocks)."""
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    monkeypatch.setitem(sys.modules, "bpy.types", fake_bpy.types)
    spec = importlib.util.spec_from_file_location(
        f"_window_unavailable_{filename[:-3]}", OPERATORS / filename,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Operator:
    def __init__(self):
        self.reports = []

    def report(self, kind, message):
        self.reports.append((set(kind), message))


def _fake_bpy(**mixar_ops):
    return SimpleNamespace(
        types=SimpleNamespace(Operator=_Operator),
        ops=SimpleNamespace(mixar=SimpleNamespace(**mixar_ops)),
        context=SimpleNamespace(window_manager=SimpleNamespace(windows=[])),
        app=SimpleNamespace(timers=SimpleNamespace(register=lambda *a, **k: None)),
    )


def test_explicit_open_ignores_latch_tries_once_and_reports(monkeypatch):
    monkeypatch.setattr(_st, "window_unavailable", True, raising=False)
    show = _Op(error=WINDOW_FAILED)
    fake = _fake_bpy(agent_bubble_show_window=show, bubble_restore=_Op())
    window_ops = _load_operator_module(monkeypatch, "window_ops.py", fake)

    op = window_ops.MIXAR_OT_agent_bubble_open_window()
    assert op.execute(SimpleNamespace()) == {"CANCELLED"}
    assert show.calls == 1
    kinds = [kind for kind, _ in op.reports]
    assert kinds == [{"ERROR"}]  # an operator report, not a modal dialog
    assert "Failed to open Agent Bubble window" in op.reports[0][1]
    assert _st.window_unavailable is True


def test_explicit_open_success_clears_latch(monkeypatch):
    monkeypatch.setattr(_st, "window_unavailable", True, raising=False)
    show = _Op()
    fake = _fake_bpy(agent_bubble_show_window=show, bubble_restore=_Op())
    window_ops = _load_operator_module(monkeypatch, "window_ops.py", fake)

    op = window_ops.MIXAR_OT_agent_bubble_open_window()
    assert op.execute(SimpleNamespace()) == {"FINISHED"}
    assert show.calls == 1
    assert _st.window_unavailable is False


def test_shift_m_reports_a_failed_open(monkeypatch):
    """Shift+M calls the open op through bpy.ops, which swallows its report;
    open_mixie must surface the failure itself (status-bar warning)."""
    open_window = _Op(error=RuntimeError(
        "Error: Failed to open Agent Bubble window: Error: Failed to open "
        "Agent Bubble window\n"
    ))
    fake = _fake_bpy(agent_bubble_open_window=open_window)
    open_mixie = _load_operator_module(monkeypatch, "open_mixie_op.py", fake)
    monkeypatch.setattr(open_mixie, "_focus_composer_soon", lambda: None)

    op = open_mixie.MIXAR_OT_open_mixie()
    wm = SimpleNamespace(mixar_bubble_tab="AGENT")
    assert op.execute(SimpleNamespace(window_manager=wm)) == {"FINISHED"}
    assert open_window.calls == 1
    assert op.reports == [({"WARNING"}, "Failed to open Agent Bubble window")]


# ---------------------------------------------------------------------------
# 4. Native side: only the main window raises the modal GPU message box
# ---------------------------------------------------------------------------

def _gl_failure_branch() -> str:
    src = GHOST_WIN32.read_text(encoding="utf-8")
    start = src.index("if (!setDrawingContextType(type)) {")
    return src[start:src.index("RegisterTouchWindow(h_wnd_, 0);", start)]


def test_child_window_gl_failure_skips_message_box():
    branch = _gl_failure_branch()
    assert "MessageBox(" in branch
    assert (
        "if (type == GHOST_kDrawingContextTypeOpenGL && parent_window == nullptr)"
        in branch
    )


def test_processor_identifier_read_is_null_guarded():
    branch = _gl_failure_branch()
    assert 'strncmp(blender::BLI_getenv("PROCESSOR_IDENTIFIER")' not in branch
    assert "processor != nullptr && strncmp(processor" in branch


def test_no_opaque_format_fallback():
    """Windows sets a pixel format once per window; a retry with another
    format reuses the first, so the PR's opaque fallback could not help."""
    src = GHOST_WIN32.read_text(encoding="utf-8")
    assert "for (const bool alpha : {true, false})" not in src
