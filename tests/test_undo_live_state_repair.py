# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tab's live state is not document content (undo guard invariant 3).

Bonkers campaign seed 2 (2026-09-30): undoing a finished turn in a tab re-read
its Scene from a step written while the agent was BUSY; the tab then read BUSY
with no run, its own hold refused redo, and nothing flipped it back.
"""

import os
import sys
from types import SimpleNamespace

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

from mixar.modules.space_mixie_chat.core import undo_tab_guard as guard  # noqa: E402


def _scene(uid, name, state="IDLE", run=False, sid="sess", run_id="", email="me@mixar.app"):
    return SimpleNamespace(session_uid=uid, name=name, mixie_chat_state=state, mixie_run_open=run,
                           mixie_run_id=run_id, mixie_session_id=sid, mixie_chat_user_id=email,
                           mixie_chat_credits=42, mixie_chat_model="default")


def test_a_finished_tab_read_busy_by_the_walk_is_idle_again():
    before = [_scene(26, "T1_r", "IDLE", False, "sess-1")]
    saved = guard.snapshot_live_state(before)
    after = [_scene(26, "T1", "BUSY", False, "sess-1")]          # the step's state and name
    changes = guard.restore_live_state(after, saved, saved_runs={})
    assert after[0].mixie_chat_state == "IDLE"
    assert after[0].name == "T1"                                  # the name IS document content
    assert ("T1", "mixie_chat_state", "BUSY", "IDLE") in changes


def test_a_working_tab_keeps_working_across_another_tabs_walk():
    before = [_scene(26, "A", "IDLE"), _scene(53, "B", "BUSY", True, "sess-b", "run-9")]
    saved = guard.snapshot_live_state(before)
    after = [_scene(26, "A", "IDLE"), _scene(53, "B", "IDLE", False, "sess-b", "")]  # an old step of B
    guard.restore_live_state(after, saved, saved_runs={"sess-b": "B"})
    assert after[1].mixie_chat_state == "BUSY" and after[1].mixie_run_open is True
    assert after[1].mixie_run_id == "run-9"


def test_the_session_id_survives_a_walk_past_the_first_message():
    saved = guard.snapshot_live_state([_scene(26, "Sofa", sid="sess-1")])
    after = [_scene(26, "Scene", sid="")]                          # the step predates the session
    guard.restore_live_state(after, saved, saved_runs={})
    assert after[0].mixie_session_id == "sess-1"


def test_a_tab_the_walk_brought_back_is_idle_unless_its_run_was_live():
    reborn = _scene(99, "Gone", "AWAITING_INPUT", True, "sess-g")
    guard.restore_live_state([reborn], saved={}, saved_runs={})
    assert reborn.mixie_chat_state == "IDLE" and reborn.mixie_run_open is False
    live = _scene(98, "Live", "BUSY", True, "sess-l")
    guard.restore_live_state([live], saved={}, saved_runs={"sess-l": "Live"})
    assert live.mixie_chat_state == "BUSY"


def test_lane_scenes_are_left_alone():
    lane = SimpleNamespace(session_uid=7, name="Workspace_x", mixie_chat_state="BUSY", mixie_run_open=False,
                           mixie_run_id="", mixie_session_id="agentlane:x")
    assert guard.snapshot_live_state([lane]) == {}
    assert guard.restore_live_state([lane], {}, {}) == []


def test_the_signed_in_identity_survives_a_walk_older_than_the_login():
    """Seen live (seed 6): the manual tab undone to Original lost its email and
    the header showed the avatar alone; every other tab still had it."""
    saved = guard.snapshot_live_state([_scene(26, "Scene", email="satyam@mixar.app")])
    after = _scene(26, "Scene", email="")
    after.mixie_chat_credits = 0
    guard.restore_live_state([after], saved, saved_runs={})
    assert after.mixie_chat_user_id == "satyam@mixar.app"
    assert after.mixie_chat_credits == 42


class _SceneWithProps(SimpleNamespace):
    """A scene with raw custom properties (``scene["key"]``), like a bpy ID."""

    def __init__(self, props, **kw):
        super().__init__(**kw)
        self._props = dict(props)

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value


def test_the_drawer_order_survives_a_tabs_own_walk():
    """Review 2026-10-02: the tab order is a raw property with no step of its
    own; a tab's undo re-read its Scene and the tab jumped back to where it was
    before the user dragged it."""
    kw = dict(session_uid=53, name="B", mixie_chat_state="IDLE", mixie_run_open=False, mixie_run_id="",
              mixie_session_id="sess-b", mixie_chat_user_id="", mixie_chat_credits=0, mixie_chat_model="")
    saved = guard.snapshot_live_state([_SceneWithProps({"mixar_tab_order": 0}, **kw)])
    after = _SceneWithProps({"mixar_tab_order": 2}, **kw)                  # the step's order
    changes = guard.restore_live_state([after], saved, saved_runs={})
    assert after["mixar_tab_order"] == 0
    assert ("B", "raw:mixar_tab_order", 2, 0) in changes
