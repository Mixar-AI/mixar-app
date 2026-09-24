# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto Key against Blender's own auto-key rules.

Blender auto-keys from a TRANSFORM, at the moment it confirms, and skips the
insert when the value is already what the channel holds. Director's cameras
are mostly moved by things with no such boundary — a nudge, an aerial click,
a gizmo drag — so a debounce stands in for one. These are the rules it can
and does keep, each pinned to the behaviour rather than to a line of source.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from mixar.modules.director.core import auto_key


class _Camera:
    def __init__(self, pose=0.0, lens=50.0):
        self.name = "Camera"
        self.matrix_world = [[float(pose)] * 4 for _ in range(4)]
        self.data = SimpleNamespace(lens=lens)


@pytest.fixture
def stub(monkeypatch):
    camera = _Camera()
    shot = SimpleNamespace(state='DRAFT', camera=camera)
    scene = SimpleNamespace(
        frame_current=12,
        mixar_director=SimpleNamespace(
            is_directing=True,
            auto_key=True,
            navigation_mode='NAVIGATE',
            beat_seconds=1.0,
        ),
        as_pointer=lambda: 1,
    )
    captured = []
    monkeypatch.setattr(auto_key, "active_shot", lambda _scene: shot)
    monkeypatch.setattr(auto_key, "move_in_progress", lambda: False)
    monkeypatch.setattr(auto_key, "_playing", lambda: False)
    monkeypatch.setattr(auto_key.bpy, "context", SimpleNamespace(scene=scene))
    monkeypatch.setattr(
        auto_key.bpy.app.timers, "is_registered", lambda _fn: True
    )

    import mixar.modules.director.core.capture as capture_module

    def _capture_beat(_context, _shot, _seconds, replace_existing=False):
        captured.append(auto_key.camera_signature(camera))
        return SimpleNamespace(frame=scene.frame_current)

    monkeypatch.setattr(capture_module, "capture_beat", _capture_beat)
    auto_key._reset()
    auto_key._watch["captured_sig"] = None
    yield SimpleNamespace(scene=scene, camera=camera, captured=captured)
    auto_key._reset()
    auto_key._watch["captured_sig"] = None


def _settle():
    """Put the debounce window in the past."""
    auto_key._watch["changed_at"] = time.monotonic() - auto_key.DEBOUNCE_SECONDS - 1.0


def test_a_move_that_settles_somewhere_new_is_keyed(stub):
    auto_key._on_depsgraph_update(stub.scene, None)
    stub.camera.matrix_world[3][3] = 5.0
    auto_key._on_depsgraph_update(stub.scene, None)
    _settle()
    auto_key._debounce_timer()
    assert len(stub.captured) == 1


def test_a_move_back_to_where_it_started_is_not(stub):
    """Blender's "only insert needed": the settled pose is already what this
    frame holds, so there is nothing to insert. Only the LAST pose used to be
    remembered, so a nudge out and back keyed a frame that never changed."""
    auto_key._on_depsgraph_update(stub.scene, None)
    stub.camera.matrix_world[3][3] = 5.0
    auto_key._on_depsgraph_update(stub.scene, None)
    stub.camera.matrix_world[3][3] = 0.0
    auto_key._on_depsgraph_update(stub.scene, None)
    _settle()
    auto_key._debounce_timer()
    assert stub.captured == []


def test_a_capture_becomes_the_new_baseline(stub):
    """Otherwise the very next settle would compare against the pose from
    before the capture and key it all over again."""
    auto_key._on_depsgraph_update(stub.scene, None)
    stub.camera.matrix_world[3][3] = 5.0
    auto_key._on_depsgraph_update(stub.scene, None)
    _settle()
    auto_key._debounce_timer()
    assert len(stub.captured) == 1
    assert auto_key._watch["baseline"] == auto_key.camera_signature(stub.camera)

    auto_key._watch["dirty"] = True
    _settle()
    auto_key._debounce_timer()
    assert len(stub.captured) == 1


def test_a_frame_change_rebaselines_on_the_pose_it_arrives_at(stub):
    """Scrubbing and playback move the camera through its own animation, and
    keying those poses would duplicate keys nobody authored."""
    auto_key._on_depsgraph_update(stub.scene, None)
    stub.scene.frame_current = 40
    stub.camera.matrix_world[3][3] = 9.0
    auto_key._on_depsgraph_update(stub.scene, None)
    assert auto_key._watch["dirty"] is False
    assert auto_key._watch["baseline"] == auto_key.camera_signature(stub.camera)
    _settle()
    auto_key._debounce_timer()
    assert stub.captured == []


def test_a_move_still_in_progress_is_waited_out(stub, monkeypatch):
    """Blender keys when the transform confirms; firing mid-drag keys a pose
    nobody chose and then keys the real one over it."""
    auto_key._on_depsgraph_update(stub.scene, None)
    stub.camera.matrix_world[3][3] = 5.0
    auto_key._on_depsgraph_update(stub.scene, None)
    _settle()
    monkeypatch.setattr(auto_key, "move_in_progress", lambda: True)
    auto_key._debounce_timer()
    assert stub.captured == []
    # And it is keyed once the transform lets go.
    monkeypatch.setattr(auto_key, "move_in_progress", lambda: False)
    auto_key._on_depsgraph_update(stub.scene, None)
    auto_key._watch["dirty"] = True
    _settle()
    auto_key._debounce_timer()
    assert len(stub.captured) == 1


def test_a_transform_that_paused_mid_drag_is_still_keyed(stub, monkeypatch):
    """Deferring is "not yet", never "forget it".

    Blender keys when the transform CONFIRMS, and a confirm streams no NEW
    pose — the last modal step already moved the camera there. So a deferral
    that drops the pending move, or that wipes the baseline while the modal
    runs, loses the keyframe outright: the director drags the camera, holds
    still long enough for one debounce tick, lets go, and nothing is keyed.
    """
    auto_key._on_depsgraph_update(stub.scene, None)

    monkeypatch.setattr(auto_key, "move_in_progress", lambda: True)
    # The drag streams poses...
    for value in (2.0, 4.0, 6.0):
        stub.camera.matrix_world[3][3] = value
        auto_key._on_depsgraph_update(stub.scene, None)
    # ...and pauses long enough for a tick to land mid-drag.
    _settle()
    auto_key._debounce_timer()
    assert stub.captured == []

    # The confirm moves nothing further, so there is no new depsgraph update
    # to re-dirty anything. The pending move has to have survived.
    monkeypatch.setattr(auto_key, "move_in_progress", lambda: False)
    _settle()
    auto_key._debounce_timer()
    assert len(stub.captured) == 1
    assert stub.captured[0] == auto_key.camera_signature(stub.camera)
