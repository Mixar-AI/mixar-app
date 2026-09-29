# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An undo never moves the user's view and never strands a live run."""

from types import SimpleNamespace

from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core import undo_tab_guard as g


def _scene(name, sid=""):
    return SimpleNamespace(name=name, mixie_session_id=sid)


def _win(scene):
    return SimpleNamespace(scene=scene)


LANE = _scene("Workspace_abc", "agentlane:abc")
A = _scene("Kitchen", "sid-a")
B = _scene("Sofa", "sid-b")
C = _scene("Scene 5", "")


def test_snapshot_view_records_real_scenes_only():
    assert g.snapshot_view([_win(C), _win(LANE), _win(A)]) == {0: "Scene 5", 2: "Kitchen"}


def test_snapshot_runs_keeps_only_live_sessions():
    session = SimpleNamespace(
        get_state=lambda s: SessionState.BUSY if s is A else SessionState.IDLE,
        run_open=lambda s: s is B,
    )
    assert g.snapshot_runs([A, B, C, LANE], session) == {"sid-a": "Kitchen", "sid-b": "Sofa"}


def test_restore_view_puts_the_window_back_on_the_users_tab():
    # The memfile step was written while an agent script had the window pinned
    # to its tab: after the undo the window shows Kitchen, the user was on Scene 5.
    w = _win(A)
    scenes = {s.name: s for s in (A, B, C)}
    moves = g.restore_view([w], {0: "Scene 5"}, scenes.get, [A, B, C])
    assert w.scene is C and moves == [(0, "Kitchen", "Scene 5")]


def test_restore_view_moves_a_window_off_a_lane_even_without_a_saved_scene():
    w = _win(LANE)
    scenes = {s.name: s for s in (A, LANE)}
    moves = g.restore_view([w], {}, scenes.get, [LANE, A])
    assert w.scene is A and moves == [(0, "Workspace_abc", "Kitchen")]


def test_restore_view_never_targets_a_lane_and_leaves_a_settled_window_alone():
    w = _win(C)
    scenes = {s.name: s for s in (C, LANE)}
    assert g.restore_view([w], {0: "Workspace_abc"}, scenes.get, [C, LANE]) == []
    assert w.scene is C
    assert g.restore_view([w], {0: "Scene 5"}, scenes.get, [C]) == []


def test_restore_view_keeps_the_current_scene_when_the_saved_one_is_gone():
    w = _win(A)
    scenes = {"Kitchen": A}
    assert g.restore_view([w], {0: "Deleted"}, scenes.get, [A]) == []
    assert w.scene is A


def test_cancel_orphaned_runs_cancels_only_sessions_whose_scene_vanished():
    cancelled, ended = [], []
    out = g.cancel_orphaned_runs({"sid-a": "Kitchen", "sid-b": "Sofa"}, ["sid-b", ""],
                                 cancelled.append, ended.append)
    assert out == ["sid-a"] and cancelled == ["sid-a"] and ended == ["sid-a"]


def test_cancel_orphaned_runs_survives_a_failing_cancel():
    def boom(sid):
        raise RuntimeError("socket down")
    out = g.cancel_orphaned_runs({"sid-a": "Kitchen"}, [], boom, lambda sid: None)
    assert out == ["sid-a"]


def test_live_session_ids_skip_lanes():
    assert g.live_session_ids([A, LANE, C]) == ["sid-a", ""]
