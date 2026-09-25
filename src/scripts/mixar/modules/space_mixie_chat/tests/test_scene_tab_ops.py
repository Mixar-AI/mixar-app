# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene tab operators: a new tab is empty and connected, switching moves every
window, closing stops the tab's agent first and never removes the last tab."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from _open_run_support import _scene, clean_state, live_bpy  # noqa: F401

from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core.session import SessionManager
from mixar.modules.space_mixie_chat.ui.operators import scene_tab_ops as ops


class _TabScene(SimpleNamespace):
    """A scene double with custom-property access (the tab order lives there)."""

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    def __setitem__(self, key, value):
        self.__dict__[key] = value

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other


def _tab_scene(name, session_id=""):
    base = _scene(name, session_id=session_id)
    return _TabScene(**base.__dict__)


class _Scenes(list):
    def get(self, name):
        return next((s for s in self if s.name == name), None)

    def __contains__(self, name):
        return any(s.name == name for s in self) if isinstance(name, str) else list.__contains__(self, name)

    def new(self, name):
        s = _tab_scene(name)
        s.mixie_chat_state = "OFFLINE"
        self.append(s)
        return s

    def remove(self, scene):
        list.remove(self, scene)


@pytest.fixture
def rig(live_bpy, monkeypatch):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    scenes = _Scenes()
    monkeypatch.setattr(live_bpy.data, "scenes", scenes, raising=False)
    a = scenes.new("Scene"); a.mixie_session_id = "sess-a"; a.mixie_chat_state = "IDLE"
    lane = scenes.new("Workspace_x"); lane.mixie_session_id = "agentlane:x"
    windows = [SimpleNamespace(scene=a), SimpleNamespace(scene=a)]
    monkeypatch.setattr(live_bpy.data, "window_managers", [SimpleNamespace(windows=windows)], raising=False)
    monkeypatch.setattr(ops, "_connection_live", lambda: True)
    ctx = SimpleNamespace(scene=a, window=windows[0])
    return SimpleNamespace(scenes=scenes, a=a, lane=lane, windows=windows, ctx=ctx)


def test_new_tab_is_empty_connected_and_shown_in_every_window(rig):
    new = ops.new_scene_tab("Kitchen")
    assert new is rig.scenes.get("Kitchen")
    assert new.mixie_session_id == "" and new.mixie_chat_state == "IDLE"
    assert all(w.scene is new for w in rig.windows)
    assert [s.name for s in ops.real_scenes()] == ["Scene", "Kitchen"]
    assert ops.new_scene_tab("Kitchen").name == "Kitchen 2"


def test_new_tab_offline_stays_offline(rig, monkeypatch):
    monkeypatch.setattr(ops, "_connection_live", lambda: False)
    assert ops.new_scene_tab("B").mixie_chat_state == "OFFLINE"


def test_switch_moves_every_window_and_refuses_lanes(rig):
    b = rig.scenes.new("B")
    assert ops.switch_scene_tab(b, was=rig.a) is True
    assert all(w.scene is b for w in rig.windows)
    assert ops.switch_scene_tab(rig.lane) is False and ops.switch_scene_tab(None) is False


def test_close_never_removes_the_last_tab(rig):
    assert ops.close_scene_tab(rig.a) == (False, "Keep at least one scene open")
    assert rig.scenes.get("Scene") is not None


def test_close_stops_a_running_tab_then_removes_it(rig, monkeypatch):
    b = rig.scenes.new("B"); b.mixie_session_id = "sess-b"
    SessionManager.set_state(b, SessionState.BUSY)
    SessionManager.set_run(b, "run-b", True)
    for w in rig.windows:
        w.scene = b
    stopped, archived, swept = [], [], []

    def fake_stop(scene, sid):
        stopped.append((scene.name, sid))
        SessionManager.set_run(scene, "", False)
        SessionManager.set_state(scene, SessionState.IDLE)

    monkeypatch.setattr(ops, "stop_scene_tab", fake_stop)
    import sys
    hist = MagicMock(); hist.archive_current = lambda scene: archived.append(scene.name)
    monkeypatch.setitem(sys.modules, "mixar.modules.space_mixie_chat.core.chat_history", hist)
    sweep = MagicMock(); sweep.sweep_leaked_lane_scenes = lambda parent_session_id="": swept.append(parent_session_id)
    monkeypatch.setitem(sys.modules, "mixar.modules.space_mixie_chat.core.lane_scene_sweep", sweep)
    monkeypatch.setitem(sys.modules, "mixar.modules.agent_panel.core.cards", MagicMock())

    assert ops.close_scene_tab(b) == (True, "")
    assert stopped == [("B", "sess-b")] and archived == ["B"] and swept == ["sess-b"]
    assert rig.scenes.get("B") is None
    assert all(w.scene is rig.a for w in rig.windows)
    assert not SessionManager.has_active_session("sess-b")


def test_close_of_a_running_tab_is_refused_offline(rig, monkeypatch):
    b = rig.scenes.new("B"); b.mixie_session_id = "sess-b"
    SessionManager.set_state(b, SessionState.BUSY)
    monkeypatch.setattr(ops, "_connection_live", lambda: False)
    closed, reason = ops.close_scene_tab(b)
    assert closed is False and "Reconnect" in reason and rig.scenes.get("B") is not None


def test_reorder_moves_a_tab_and_new_tabs_take_the_last_slot(rig):
    b = ops.new_scene_tab("B")
    c = ops.new_scene_tab("C")
    assert [s.name for s in ops.ordered_tabs()] == ["Scene", "B", "C"]
    assert ops.reorder_scene_tab(c, 0) is True
    assert [s.name for s in ops.ordered_tabs()] == ["C", "Scene", "B"]
    assert ops.reorder_scene_tab(rig.lane, 0) is False
    assert ops.reorder_scene_tab(b, 99) is True
    assert [s.name for s in ops.ordered_tabs()] == ["C", "Scene", "B"]


def test_send_selection_copies_objects_and_data(live_bpy):
    """Row 3.4: a send is a duplicate (object, data, materials), never a link."""
    from types import SimpleNamespace as NS

    class Copyable:
        def __init__(self, name, **kw):
            self.name = name
            self.__dict__.update(kw)

        def copy(self):
            clone = Copyable(self.name + ".001", **{k: v for k, v in self.__dict__.items() if k != "name"})
            return clone

    linked = []
    source = _scene(name="A", session_id="sa")
    target = _scene(name="B", session_id="sb")
    target.collection = NS(objects=NS(link=lambda o: linked.append(o)))
    mat = Copyable("Mat")
    mesh = Copyable("Mesh", materials=[mat])
    obj = Copyable("Cube", data=mesh)
    made = ops.send_selection_to_scene(source, target, [obj])
    assert made == ["Cube.001"] and len(linked) == 1
    copy = linked[0]
    assert copy is not obj and copy.data is not mesh and copy.data.materials[0] is not mat
    assert ops.send_selection_to_scene(source, source, [obj]) == []


def test_new_tab_inherits_the_signed_in_account():
    from types import SimpleNamespace as NS
    source = NS(name="A", mixie_chat_user_id="me@mixar.app", mixie_chat_credits=42, mixie_chat_model="m")
    fresh = NS(name="B", mixie_chat_user_id="", mixie_chat_credits=0, mixie_chat_model="")
    ops.inherit_account(source, fresh)
    assert (fresh.mixie_chat_user_id, fresh.mixie_chat_credits, fresh.mixie_chat_model) == ("me@mixar.app", 42, "m")
    ops.inherit_account(None, fresh)  # no source: untouched
    assert fresh.mixie_chat_user_id == "me@mixar.app"
