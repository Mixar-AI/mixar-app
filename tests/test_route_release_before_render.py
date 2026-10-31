# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A routed script's window goes back to the user's tab BEFORE a render job starts.

Switching ``window.scene`` runs ``ED_scene_change_update`` →
``ED_render_engine_changed`` → ``RE_FreePersistentData(nullptr)``, which frees every
Render's engine not yet flagged ``RE_ENGINE_RENDERING``. The executor's restore after a
lane ``render_viewport`` script freed the preview job's engine while its thread was
still building the render result (docs/render-job-contract.md, "A scene switch never
lands on a starting render job"). ``release_pin`` restores the window inside the
script, before the invoke; the executor's own restore then switches nothing.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class Window:
    """Records every ``window.scene`` assignment (each one is a native scene switch)."""

    def __init__(self, scene):
        self._scene = scene
        self.switches = []

    @property
    def scene(self):
        return self._scene

    @scene.setter
    def scene(self, value):
        self.switches.append(value.name)
        self._scene = value


@pytest.fixture
def routing(monkeypatch):
    from mixar.modules.space_mixie_chat.core import main_thread_routing as module

    user = SimpleNamespace(name="User Tab", mixie_session_id="chat-1")
    lane = SimpleNamespace(name="Workspace_abc", mixie_session_id="agentlane:abc")
    window = Window(user)
    fake = MagicMock(name="bpy")
    fake.context.window = window
    fake.data.scenes = MagicMock()
    fake.data.scenes.__iter__.side_effect = lambda: iter([user, lane])
    fake.data.scenes.get.side_effect = {"User Tab": user, "Workspace_abc": lane}.get
    monkeypatch.setattr(module, "bpy", fake)
    monkeypatch.setattr(module, "slog", MagicMock())
    for name, value in (("_restore_scene_name", ""), ("_restore_session_id", ""),
                        ("_user_foreground_scene_name", ""), ("_pin_active", False)):
        monkeypatch.setattr(module, name, value)
    module.window, module.user, module.lane = window, user, lane
    return module


def test_a_released_pin_switches_once_and_the_executor_restore_is_a_no_op(routing):
    target, did_switch, error = routing.route_request("agentlane:abc", "render_viewport", "r1")
    assert (target, did_switch, error) == (routing.lane, True, None)
    assert routing.release_pin("native_render") is True
    assert routing.window.scene is routing.user
    # The executor's restore in its finally: the window is already back.
    routing.restore_after(did_switch)
    assert routing.window.switches == ["Workspace_abc", "User Tab"]
    routing.slog.assert_any_call("route.release", None, session_id="agentlane:abc",
                                 reason="native_render")


def test_release_without_a_live_pin_switches_nothing(routing):
    # The user's own tab, no switch: nothing to release.
    routing.window.scene = routing.lane
    routing.window.switches.clear()
    routing.route_request("agentlane:abc", "render_viewport", "r1")
    assert routing.release_pin("native_render") is False
    assert routing.window.switches == []


def test_a_pin_already_restored_is_never_released_again(routing):
    _, did_switch, _ = routing.route_request("agentlane:abc", "execute_workspace_script", "r1")
    routing.restore_after(did_switch)
    # A later script in the user's tab (no pin) starts a render: the stale
    # restore target must not move the window.
    routing.route_request("agent:conn", "render_viewport", "r2")
    routing.window.switches.clear()
    assert routing.release_pin("native_render") is False
    assert routing.window.switches == []


def test_the_restore_target_is_known_only_while_a_pin_is_live(routing):
    assert routing.pin_restore_target() is None
    routing.route_request("agentlane:abc", "render_viewport", "r1")
    assert routing.pin_restore_target() is routing.user
    routing.release_pin("native_render")
    assert routing.pin_restore_target() is None
