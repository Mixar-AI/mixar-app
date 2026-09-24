# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Previous / Next keyframe step from the PLAYHEAD, never a stored index.

The dock's transport arrows used to step from ``shot.active_beat_index``. That
index is only written by a deliberate jump, so scrubbing, dragging a handle,
retiming with the Speed slider or playing the shot left it stale — and the
arrow then either jumped somewhere unrelated or, once the index had been
clamped to an end, reported FINISHED and moved nothing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mixar.modules.director.ui.operators import surface_ops


class _Beat:
    def __init__(self, frame: int) -> None:
        self.frame = frame


def _context(frames, current):
    scene = SimpleNamespace(frame_current=current)
    scene.frame_set = lambda frame: setattr(scene, "frame_current", frame)
    shot = SimpleNamespace(
        beats=[_Beat(frame) for frame in frames],
        active_beat_index=0,
        camera=SimpleNamespace(),
    )
    return SimpleNamespace(scene=scene), shot


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setattr(surface_ops, "enter_camera_view", lambda *a, **k: None)


def _run(monkeypatch, frames, current, offset, *, active_index=0):
    context, shot = _context(frames, current)
    shot.active_beat_index = active_index
    monkeypatch.setattr(surface_ops, "active_shot", lambda _scene: shot)
    result = surface_ops._jump_relative(context, offset)
    return result, context.scene.frame_current, shot


def test_previous_steps_back_from_the_playhead(monkeypatch):
    result, frame, shot = _run(monkeypatch, [1, 25, 50, 75], 50, -1)
    assert result == {'FINISHED'}
    assert frame == 25
    assert shot.active_beat_index == 1


def test_next_steps_forward_from_the_playhead(monkeypatch):
    result, frame, _shot = _run(monkeypatch, [1, 25, 50, 75], 25, 1)
    assert result == {'FINISHED'}
    assert frame == 50


def test_a_stale_active_index_does_not_decide_the_step(monkeypatch):
    """The regression: index pinned at the end, playhead in the middle.

    The old code clamped `0 + -1` (or `last + 1`) and moved nothing.
    """
    result, frame, _shot = _run(monkeypatch, [1, 25, 50, 75], 50, -1, active_index=0)
    assert result == {'FINISHED'}
    assert frame == 25

    result, frame, _shot = _run(monkeypatch, [1, 25, 50, 75], 25, 1, active_index=3)
    assert result == {'FINISHED'}
    assert frame == 50


def test_playhead_between_keyframes_lands_on_the_neighbour(monkeypatch):
    _result, frame, _shot = _run(monkeypatch, [1, 25, 50], 30, -1)
    assert frame == 25
    _result, frame, _shot = _run(monkeypatch, [1, 25, 50], 30, 1)
    assert frame == 50


def test_retimed_beats_are_searched_in_frame_order(monkeypatch):
    """A drag reorders beats in TIME but not in the collection."""
    _result, frame, shot = _run(monkeypatch, [50, 1, 25], 50, -1)
    assert frame == 25
    assert shot.active_beat_index == 2


def test_the_ends_refuse_instead_of_reporting_a_move(monkeypatch):
    result, frame, _shot = _run(monkeypatch, [1, 25, 50], 1, -1)
    assert result == {'CANCELLED'}
    assert frame == 1
    result, frame, _shot = _run(monkeypatch, [1, 25, 50], 50, 1)
    assert result == {'CANCELLED'}
    assert frame == 50


def test_no_beats_cancels(monkeypatch):
    result, _frame, _shot = _run(monkeypatch, [], 1, 1)
    assert result == {'CANCELLED'}
