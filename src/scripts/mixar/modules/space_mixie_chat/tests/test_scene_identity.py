# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A scene copy never keeps the original's chat session."""

import pytest
from _open_run_support import _scene, live_bpy  # noqa: F401

from mixar.modules.space_mixie_chat.core import scene_identity, turn_events


class _PropScene:
    """A scene double with custom-property access."""

    def __init__(self, base):
        self.__dict__.update(base.__dict__)
        self._props = {"mixie_ws_resume": {"cursor": 3}, "mixar_scene_id": "id-1"}

    def __contains__(self, key):
        return key in self._props

    def __delitem__(self, key):
        del self._props[key]

    def get(self, key, default=None):
        return self._props.get(key, default)


@pytest.fixture
def scenes(live_bpy, monkeypatch):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    original = _PropScene(_scene("Kitchen", session_id="sess-k"))
    original.mixie_chat_messages.add().text = "hello"
    copy = _PropScene(_scene("Kitchen.001", session_id="sess-k"))
    copy.mixie_chat_messages.add().text = "hello"
    other = _PropScene(_scene("Robot", session_id="sess-r"))
    live_bpy.data.scenes.extend([copy, original, other])   # copy sorts first on purpose
    return original, copy, other


def test_the_copy_is_detached_and_the_original_kept(scenes):
    original, copy, other = scenes
    assert scene_identity.dedupe_session_ids() == ["Kitchen.001"]
    assert original.mixie_session_id == "sess-k" and len(original.mixie_chat_messages) == 1
    assert copy.mixie_session_id == "" and len(copy.mixie_chat_messages) == 0
    assert copy.mixie_chat_state == "IDLE" and copy.mixie_run_open is False
    assert "mixie_ws_resume" not in copy and "mixar_scene_id" not in copy
    assert other.mixie_session_id == "sess-r"


def test_the_bound_scene_wins_over_the_shorter_name(scenes):
    original, copy, _ = scenes
    turn_events._bindings["sess-k"] = turn_events._scene_id(copy)
    assert scene_identity.dedupe_session_ids() == ["Kitchen"]
    assert copy.mixie_session_id == "sess-k" and original.mixie_session_id == ""


def test_depsgraph_hook_only_scans_when_the_scene_count_grows(scenes, monkeypatch):
    """The handler only notices growth; the scan (property writes) runs from
    a timer, never inside the depsgraph handler."""
    calls, timers = [], []
    monkeypatch.setattr(scene_identity, "dedupe_session_ids", lambda: calls.append(1))
    monkeypatch.setattr(scene_identity.bpy.app.timers, "is_registered", lambda fn: False)
    monkeypatch.setattr(scene_identity.bpy.app.timers, "register",
                        lambda fn, first_interval=0.0: timers.append(fn))
    scene_identity._last_scene_count = -1
    scene_identity._on_depsgraph_update()          # first sight: record, no scan
    scene_identity._on_depsgraph_update()          # unchanged: nothing
    assert calls == []
    scene_identity._last_scene_count = 2
    scene_identity._on_depsgraph_update()          # grew 2 -> 3: schedule the scan
    assert calls == [] and len(timers) == 1
    assert timers[0]() is None                     # the timer scans once and stops
    assert calls == [1]


@pytest.fixture
def adoption(live_bpy, monkeypatch):
    """A signed-in tab and a scene a script just made (state left at OFFLINE)."""
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    monkeypatch.setattr(live_bpy.context, "window", None, raising=False)
    tab = _scene("Pool", session_id="sess-p")
    tab.mixie_chat_user_id, tab.mixie_chat_credits, tab.mixie_chat_model = "user-1", 120, "auto"
    made = _scene("Classroom", session_id="", state="OFFLINE")
    made.mixie_chat_user_id = ""
    live_bpy.data.scenes.extend([tab, made])
    live = [True]
    monkeypatch.setattr(scene_identity, "_connection_live", lambda: live[0])
    return tab, made, live


def test_a_script_made_scene_is_adopted_while_connected(adoption):
    tab, made, _ = adoption
    assert scene_identity.adopt_new_scenes() == ["Classroom"]
    assert made.mixie_chat_state == "IDLE"
    assert (made.mixie_chat_user_id, made.mixie_chat_credits) == ("user-1", 120)
    assert tab.mixie_chat_state == "IDLE"  # an already-ready tab is untouched


def test_adoption_waits_for_the_connection(adoption):
    _, made, live = adoption
    live[0] = False
    assert scene_identity.adopt_new_scenes() == []
    assert made.mixie_chat_state == "OFFLINE"


def test_lanes_and_open_runs_are_never_adopted(adoption):
    from mixar.modules.space_mixie_chat.constants import AGENT_LANE_SESSION_PREFIX
    _, made, _ = adoption
    made.mixie_session_id = AGENT_LANE_SESSION_PREFIX + "worker"
    assert scene_identity.adopt_scene(made) is False
    made.mixie_session_id, made.mixie_run_open = "", True
    assert scene_identity.adopt_scene(made) is False
    assert made.mixie_chat_state == "OFFLINE"


def test_the_growth_timer_also_adopts(adoption, monkeypatch):
    _, made, _ = adoption
    monkeypatch.setattr(scene_identity, "dedupe_session_ids", lambda: [])
    assert scene_identity._dedupe_later() is None
    assert made.mixie_chat_state == "IDLE"
