# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parallel scenes: the client globals that used to assume one live session."""

from types import SimpleNamespace

import pytest
from _open_run_support import _scene, clean_state, live_bpy  # noqa: F401

from mixar.modules.space_mixie_chat.core import executor as executor_mod
from mixar.modules.space_mixie_chat.core import lane_scene_sweep
from mixar.modules.space_mixie_chat.core.session import SessionManager
from mixar.modules.space_mixie_chat.constants import SessionState


# --- executor: per-session undo turns -------------------------------------

def test_undo_turn_counters_are_per_session(monkeypatch):
    ex = executor_mod.ScriptExecutor()
    ex._turns.clear()
    monkeypatch.setattr(executor_mod, "AGENT_UNDO_GROUP_PER_TURN", False)
    monkeypatch.setattr(executor_mod, "AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN", 2)
    monkeypatch.setattr(ex, "_push_undo_checkpoint", lambda: True)

    ex.begin_agent_turn("sess-a")
    ex.begin_agent_turn("sess-b")
    ex._current_session = "sess-a"
    assert ex._should_push_undo() and ex._push_undo_for_script()
    assert ex._should_push_undo() and ex._push_undo_for_script()
    assert not ex._should_push_undo(), "A reached its cap"
    ex._current_session = "sess-b"
    assert ex._should_push_undo(), "B has its own budget"
    ex.end_agent_turn("sess-b")          # B's turn ends: A keeps its state
    ex._current_session = "sess-a"
    assert not ex._should_push_undo()
    ex._current_session = "sess-c"       # no turn: every script pushes
    assert ex._should_push_undo()
    ex.end_agent_turn(None)
    assert ex._turns == {}


# --- session manager: per-session active gate ------------------------------

def test_active_gate_admits_by_session_and_rejects_idle_tabs():
    a = _scene("A", session_id="sess-a")
    b = _scene("B", session_id="sess-b")
    SessionManager.set_state(a, SessionState.BUSY)
    assert SessionManager.has_active_session("sess-a")
    assert not SessionManager.has_active_session("sess-b")
    assert SessionManager.has_active_session("")                 # any
    assert SessionManager.has_active_session("agentlane:abc")    # lanes: any
    SessionManager.set_run(b, "run-b", True)                     # workers building, turn idle
    assert SessionManager.has_active_session("sess-b")
    assert sorted(SessionManager.active_session_ids()) == ["sess-a", "sess-b"]
    SessionManager.set_state(a, SessionState.IDLE)
    assert not SessionManager.has_active_session("sess-a") and SessionManager.has_active_session("sess-b")


# --- lane sweep: only lanes whose parent session is gone -------------------

class _Lane(SimpleNamespace):
    def get(self, key, default=""):
        return self.__dict__.get(key, default)


@pytest.fixture
def lanes(live_bpy, monkeypatch):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    a = _scene("A", session_id="sess-a")
    b = _scene("B", session_id="sess-b")
    la = _Lane(name="Workspace_a", mixie_session_id="agentlane:aaa", mixar_workspace_main_session="sess-a")
    lb = _Lane(name="Workspace_b", mixie_session_id="agentlane:bbb", mixar_workspace_main_session="sess-b")
    orphan = _Lane(name="Workspace_o", mixie_session_id="agentlane:ooo")
    live_bpy.data.scenes.extend([a, b, la, lb, orphan])
    removed = []
    monkeypatch.setattr(lane_scene_sweep, "_remove_lane_scene", lambda lane: removed.append(lane.name) or True)
    return SimpleNamespace(a=a, b=b, removed=removed)


def test_a_running_tab_keeps_its_lanes_while_the_idle_tabs_are_swept(lanes):
    SessionManager.set_run(lanes.a, "run-a", True)
    assert lane_scene_sweep.sweep_leaked_lane_scenes() == 1
    assert lanes.removed == ["Workspace_b"]            # B idle: swept; A live: kept; orphan: kept (something active)


def test_sweep_for_one_tab_and_orphans_once_everything_is_idle(lanes):
    SessionManager.set_run(lanes.a, "run-a", True)
    assert lane_scene_sweep.sweep_leaked_lane_scenes(parent_session_id="sess-a") == 0
    SessionManager.set_run(lanes.a, "", False)
    assert lane_scene_sweep.sweep_leaked_lane_scenes(parent_session_id="sess-a") == 1
    assert lanes.removed == ["Workspace_a"]
    lanes.removed.clear()
    lane_scene_sweep.sweep_leaked_lane_scenes()
    assert sorted(lanes.removed) == ["Workspace_a", "Workspace_b", "Workspace_o"], lanes.removed  # fake removal keeps scenes
