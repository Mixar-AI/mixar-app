# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene routing with several tagged scenes: pin the session's scene, restore
the scene the user was looking at, refuse ambiguity, never guess."""

from types import SimpleNamespace

import pytest
from _open_run_support import _scene, live_bpy  # noqa: F401

from mixar.modules.space_mixie_chat.core import main_thread_routing as routing


@pytest.fixture
def two_tabs(live_bpy, monkeypatch):
    a = _scene("A", session_id="sess-a")
    b = _scene("B", session_id="sess-b")
    lane = _scene("Workspace_x", session_id="agentlane:abc")
    live_bpy.data.scenes.extend([a, b, lane])
    window = SimpleNamespace(scene=b)                     # the user is looking at B
    monkeypatch.setattr(live_bpy.context, "window", window, raising=False)
    monkeypatch.setattr(live_bpy.context, "scene", b, raising=False)
    monkeypatch.setattr(live_bpy.app, "driver_namespace", {}, raising=False)
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    routing._restore_scene_name = ""
    routing._user_foreground_scene_name = ""
    return SimpleNamespace(a=a, b=b, lane=lane, window=window, bpy=live_bpy)


def test_pin_runs_in_the_sessions_scene_and_restores_the_scene_the_user_viewed(two_tabs):
    t = two_tabs
    target, switched, error = routing.route_request("sess-a", "execute_bpy_script", "r1")
    assert (target, switched, error) == (t.a, True, None)
    assert t.window.scene is t.a
    assert t.bpy.app.driver_namespace["mixie_route_switched"] is True
    routing.restore_after(switched)
    assert t.window.scene is t.b                          # back to B, not "first scene"
    assert t.bpy.app.driver_namespace["mixie_route_switched"] is False


def test_no_switch_when_the_window_already_shows_the_target(two_tabs):
    t = two_tabs
    target, switched, error = routing.route_request("sess-b", "execute_bpy_script", "r1")
    assert (target, switched, error) == (t.b, False, None)
    assert t.bpy.app.driver_namespace["mixie_route_switched"] is False


def test_restore_never_lands_on_a_lane_scene(two_tabs):
    t = two_tabs
    t.window.scene = t.lane                               # a lane was left showing
    _, switched, _ = routing.route_request("sess-a", "execute_bpy_script", "r1")
    routing.restore_after(switched)
    assert t.window.scene is not t.lane and t.window.scene in (t.a, t.b)


def test_unknown_and_ambiguous_sessions_are_rejected(two_tabs):
    t = two_tabs
    assert routing.route_request("sess-zz", "t", "r1") == (None, False, "no scene for session sess-zz")
    t.bpy.data.scenes.append(_scene("A.001", session_id="sess-a"))   # a Scene copy
    target, switched, error = routing.route_request("sess-a", "t", "r2")
    assert target is None and switched is False
    assert "matches 2 scenes" in error and "A, A.001" in error
    assert t.window.scene is t.b                          # nothing moved


def test_a_timer_tick_without_a_context_window_borrows_the_first_window(two_tabs, monkeypatch):
    t = two_tabs
    monkeypatch.setattr(t.bpy.context, "window", None, raising=False)
    monkeypatch.setattr(t.bpy.context, "window_manager", SimpleNamespace(windows=[t.window]), raising=False)
    target, switched, error = routing.route_request("sess-a", "t", "r1")
    assert (target, switched, error) == (t.a, True, None) and t.window.scene is t.a
    routing.restore_after(switched)
    assert t.window.scene is t.b


def test_no_window_at_all_refuses_rather_than_running_in_the_wrong_scene(two_tabs, monkeypatch):
    t = two_tabs
    monkeypatch.setattr(t.bpy.context, "window", None, raising=False)
    monkeypatch.setattr(t.bpy.context, "window_manager", SimpleNamespace(windows=[]), raising=False)
    target, switched, error = routing.route_request("sess-a", "t", "r1")
    assert target is None and "no window to pin" in error
    # ...but the current scene needs no pin.
    assert routing.route_request("sess-b", "t", "r2") == (t.b, False, None)


def test_unpinned_scripts_follow_and_track_the_users_scene(two_tabs):
    t = two_tabs
    assert routing.route_request("agent:conn", "t", "r1") == (None, False, None)
    assert routing._user_foreground_scene_name == "B"
