# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tour teardown: file loads, the Scenes drawer flag, the seen flag's
email, and a user pause across a lost host window."""

from __future__ import annotations

import ast
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

for _name in ("gpu", "gpu.state", "gpu.shader", "gpu.matrix", "gpu.types",
              "gpu_extras", "gpu_extras.batch", "blf", "bgl", "mathutils",
              "addon_utils"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.onboarding.core.tour import (  # noqa: E402
    actions,
    actions_extra,
    deferred_restore,
    session as session_mod,
    session_lifecycle,
)

TOUR_DIR = (Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules"
            / "onboarding")


# ---- CL-26: load_pre defers every operator-driven restore ---------------------

class _Stoppable(session_lifecycle.SessionLifecycleMixin):
    def __init__(self, snapshot):
        self.running = True
        self.runner = None
        self.clock = SimpleNamespace(close=lambda: None)
        self.video = SimpleNamespace(close=lambda: None)
        self._handles = []
        self.tour = SimpleNamespace(id="t")
        self._pre_tour_state = snapshot
        self.published = []

    def _publish(self, final=False, force=False):
        self.published.append(final)

    @staticmethod
    def _tag_redraw_all():
        pass


@pytest.fixture
def teardown(monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "restore_state", lambda snap: calls.append(("restore", snap)))
    monkeypatch.setattr(actions_extra, "reset_transients", lambda: calls.append(("reset",)))
    monkeypatch.setattr(session_lifecycle, "_telemetry", lambda: None)
    timers = []
    fake_bpy = SimpleNamespace(
        app=SimpleNamespace(
            handlers=SimpleNamespace(load_post=[], load_post_fail=[]),
            timers=SimpleNamespace(register=lambda fn, **kw: timers.append((fn, kw))),
        ),
        context=SimpleNamespace(window_manager=SimpleNamespace(mixie_chat_is_logged_in=True)),
    )
    monkeypatch.setattr(deferred_restore, "bpy", fake_bpy)
    monkeypatch.setattr(deferred_restore, "_pending", None)
    monkeypatch.setattr(session_mod, "_current", None)
    return SimpleNamespace(calls=calls, timers=timers, bpy=fake_bpy)


SNAP = {"ui_mode": "pro", "drawer_amount": 0.4, "island": "pill", "bubble_tab": "IMAGE"}


def test_a_file_load_stop_runs_no_operator_restore_synchronously(teardown):
    live = _Stoppable(SNAP)
    live.stop("file-loaded", defer_ui=True)

    assert teardown.calls == []
    assert live.published == [True] and live.running is False
    assert deferred_restore.pending() == SNAP
    assert teardown.bpy.app.handlers.load_post == [deferred_restore._on_load_post]
    assert teardown.bpy.app.handlers.load_post_fail == [deferred_restore._on_load_post]


def test_the_restore_runs_from_a_timer_after_load_post(teardown):
    _Stoppable(SNAP).stop("file-loaded", defer_ui=True)
    deferred_restore._on_load_post(None)

    assert teardown.bpy.app.handlers.load_post == []   # one-shot
    assert teardown.bpy.app.handlers.load_post_fail == []
    [(fn, kwargs)] = teardown.timers
    assert kwargs.get("persistent") is True
    assert teardown.calls == []                        # still nothing in load_post
    fn()
    # Reduced restore: mode + island only; the outgoing file's drawer and
    # tab are not carried over.
    assert teardown.calls == [("reset",), ("restore", {"ui_mode": "pro", "island": "pill"})]
    assert deferred_restore.pending() is None


def test_a_failed_load_restores_too_and_leaves_nothing_pending(teardown):
    _Stoppable(SNAP).stop("file-loaded", defer_ui=True)
    # Blender fires load_post_fail instead of load_post.
    teardown.bpy.app.handlers.load_post_fail[0](None)
    assert teardown.bpy.app.handlers.load_post == []
    assert teardown.bpy.app.handlers.load_post_fail == []
    [(fn, _kwargs)] = teardown.timers
    fn()
    assert teardown.calls[-1] == ("restore", {"ui_mode": "pro", "island": "pill"})
    assert deferred_restore.pending() is None


def test_signed_out_skips_the_island(teardown):
    teardown.bpy.context.window_manager.mixie_chat_is_logged_in = False
    _Stoppable(SNAP).stop("file-loaded", defer_ui=True)
    deferred_restore.run()
    assert teardown.calls[-1] == ("restore", {"ui_mode": "pro"})


def test_a_new_tour_cancels_the_deferred_restore(teardown, monkeypatch):
    _Stoppable(SNAP).stop("file-loaded", defer_ui=True)
    monkeypatch.setattr(session_mod, "_current", SimpleNamespace(running=True))
    deferred_restore.run()
    assert teardown.calls == []


def test_other_interruptions_still_restore_synchronously(teardown):
    _Stoppable(SNAP).stop("cancelled")
    assert teardown.calls == [("reset",), ("restore", SNAP)]
    assert deferred_restore.pending() is None


def test_load_pre_passes_defer_ui():
    props = (TOUR_DIR / "ui/properties/tour_props.py").read_text(encoding="utf-8")
    load_pre = props.split("def _on_load_pre", 1)[1].split("\ndef ", 1)[0]
    assert 'live.stop("file-loaded", defer_ui=True)' in load_pre


# ---- CL-27: the Scenes drawer flag ------------------------------------------

def _scenes(monkeypatch, target):
    wm = SimpleNamespace(mixar_scenes_drawer_target=target)
    ops = []

    def call_op(path, **_kw):
        ops.append(path)
        wm.mixar_scenes_drawer_target = 1 if path.endswith("reveal") else 0
        return True

    monkeypatch.setattr(actions_extra, "_wm", lambda: wm)
    monkeypatch.setattr(actions_extra, "_scenes_drawer_opened", False)
    monkeypatch.setattr(actions_extra, "help_menu_close", lambda _a: True)
    monkeypatch.setattr(actions, "_call_op", call_op)
    monkeypatch.setattr(actions, "_zen_view3d_override", lambda: {})
    monkeypatch.setattr(actions_extra.bpy.context, "temp_override",
                        lambda **_kw: nullcontext(), raising=False)
    return wm, ops


def test_reset_clears_the_flag_after_the_user_closed_the_tours_drawer(monkeypatch):
    wm, ops = _scenes(monkeypatch, 0)
    actions_extra.scenes_drawer({"open": True})
    assert actions_extra._scenes_drawer_opened is True
    wm.mixar_scenes_drawer_target = 0           # the user shuts it
    actions_extra.reset_transients()
    assert actions_extra._scenes_drawer_opened is False
    # The user's own drawer, opened later, is never toggled shut.
    wm.mixar_scenes_drawer_target = 1
    actions_extra.reset_transients()
    actions_extra.scenes_drawer({"open": False})
    assert ops == ["view3d.scenes_drawer_reveal"]
    assert wm.mixar_scenes_drawer_target == 1


def test_an_already_closed_drawer_clears_the_flag(monkeypatch):
    wm, ops = _scenes(monkeypatch, 0)
    actions_extra.scenes_drawer({"open": True})
    wm.mixar_scenes_drawer_target = 0
    assert actions_extra.scenes_drawer({"open": False}) is True
    assert actions_extra._scenes_drawer_opened is False
    wm.mixar_scenes_drawer_target = 1
    assert actions_extra.scenes_drawer({"open": False}) is True
    assert ops == ["view3d.scenes_drawer_reveal"]


def test_reset_transients_assigns_the_module_flag():
    tree = ast.parse((TOUR_DIR / "core/tour/actions_extra.py").read_text(encoding="utf-8"))
    reset = next(n for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "reset_transients")
    globals_ = {name for n in ast.walk(reset) if isinstance(n, ast.Global) for name in n.names}
    assert "_scenes_drawer_opened" in globals_
    assigned = {t.id for n in ast.walk(reset) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assert "_scenes_drawer_opened" in assigned
    # No module-level reassignment left behind below the function.
    module_assigns = [n.lineno for n in tree.body if isinstance(n, ast.Assign)
                      and any(getattr(t, "id", "") == "_scenes_drawer_opened"
                              for t in n.targets)]
    assert len(module_assigns) == 1 and module_assigns[0] < reset.lineno


# ---- NB-6: a user pause survives a lost host window ---------------------------

class _Runner:
    def __init__(self):
        self.user_paused = False

    def set_user_paused(self, paused):
        self.user_paused = paused


def _host_session(monkeypatch):
    region = SimpleNamespace(type="WINDOW", as_pointer=lambda: 7)
    area = SimpleNamespace(type="VIEW_3D", regions=[region])
    window = SimpleNamespace(screen=SimpleNamespace(areas=[area]))
    monkeypatch.setattr(session_mod.anchors, "window_by_ptr", lambda _p: window)
    monkeypatch.setattr(session_mod.anchors, "normalize_ptr", lambda p: p)
    s = SimpleNamespace(
        _host_window_ptr=1, _host_region_ptr=7, _host_lost=False,
        _paused_before_host_lost=False, exit_confirm=False, runner=_Runner(),
        cursor=SimpleNamespace(hide=lambda: None),
        anchor_cache=SimpleNamespace(invalidate=lambda: None),
        card_motion=SimpleNamespace(reset=lambda: None),
        _refresh_host=lambda w, r: None,
    )
    alive = lambda: session_mod.TourSession._host_alive(s)  # noqa: E731
    return s, area, alive


def test_a_user_pause_survives_the_host_coming_back(monkeypatch):
    s, area, alive = _host_session(monkeypatch)
    s.runner.user_paused = True                   # the user paused
    area.type = "IMAGE_EDITOR"                    # host lost
    assert alive() and s._host_lost
    area.type = "VIEW_3D"                         # host back
    assert alive() and not s._host_lost
    assert s.runner.user_paused is True


def test_an_automatic_host_pause_still_resumes(monkeypatch):
    s, area, alive = _host_session(monkeypatch)
    area.type = "IMAGE_EDITOR"
    alive()
    assert s.runner.user_paused is True
    area.type = "VIEW_3D"
    alive()
    assert s.runner.user_paused is False
