# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cinema Mode navigates in PERSPECTIVE.

The aerial view is the one place Director writes an orthographic projection,
and it used to leak out of both exits: a free view kept it (the guard only
looked for a camera view), and a camera view was entered straight over it —
Blender remembers the projection a camera view was entered FROM and returns
to it when the view is orbited back out. Either way every later pan and orbit
was orthographic, the scene flattened, and nothing on the surface said why.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.director.core import viewport

ROOT = Path(__file__).resolve().parents[2]
VIEWPORT = (
    ROOT / "src/scripts/mixar/modules/director/core/viewport.py"
).read_text(encoding="utf-8")


def _space(perspective):
    return SimpleNamespace(
        region_3d=SimpleNamespace(view_perspective=perspective),
        lock_camera=False,
        camera=None,
    )


@pytest.fixture
def viewport_of(monkeypatch):
    def _install(space):
        area = SimpleNamespace(tag_redraw=lambda: None)
        monkeypatch.setattr(
            viewport, "find_view3d_context", lambda _c: (None, area, None, space)
        )
        return SimpleNamespace(
            scene=SimpleNamespace(
                mixar_director=SimpleNamespace(navigation_mode='AERIAL'), camera=None
            )
        )

    return _install


# -------------------------------------------------------------------------
# Leaving the aerial view with no camera.


@pytest.mark.parametrize("before", ['ORTHO', 'CAMERA'])
def test_a_free_view_is_always_perspective(viewport_of, before):
    space = _space(before)
    viewport.enter_free_view(viewport_of(space))
    assert space.region_3d.view_perspective == 'PERSP'


def test_a_free_view_already_perspective_is_left_alone(viewport_of):
    space = _space('PERSP')
    viewport.enter_free_view(viewport_of(space))
    assert space.region_3d.view_perspective == 'PERSP'


# -------------------------------------------------------------------------
# Leaving it with one.


class _Region3D:
    """Records every write, so the ORDER of the two can be asserted."""

    def __init__(self, value):
        self._value = value
        self.writes: list[str] = []

    @property
    def view_perspective(self):
        return self._value

    @view_perspective.setter
    def view_perspective(self, value):
        self._value = value
        self.writes.append(value)


def _enter_camera_view(viewport_of, before):
    space = _space(before)
    space.region_3d = _Region3D(before)
    viewport.enter_camera_view(viewport_of(space), "camera", remember=False)
    return space.region_3d


def test_a_camera_view_is_entered_from_perspective(viewport_of):
    """So the projection Blender returns to on an orbit-out is perspective,
    never the aerial view's leftover ORTHO."""
    region_3d = _enter_camera_view(viewport_of, 'ORTHO')
    assert region_3d.writes == ['PERSP', 'CAMERA']


def test_a_view_already_perspective_is_not_written_twice(viewport_of):
    """There is nothing to correct, and a redundant write is a redundant
    notifier."""
    region_3d = _enter_camera_view(viewport_of, 'PERSP')
    assert region_3d.writes == ['CAMERA']


def test_the_aerial_view_is_the_only_writer_of_ortho():
    """If a second one appears it needs the same two exits thought through."""
    assert VIEWPORT.count("view_perspective = 'ORTHO'") == 1
    aerial = VIEWPORT.split("def enter_aerial_view(", 1)[1].split("\ndef ", 1)[0]
    assert "region_3d.view_perspective = 'ORTHO'" in aerial


def test_neither_helper_guards_on_camera_alone():
    """The guard that caused it: `== 'CAMERA'` leaves every other projection
    exactly where it was."""
    for name in ("enter_free_view", "enter_camera_view"):
        body = VIEWPORT.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
        assert "view_perspective == 'CAMERA'" not in body
        assert "view_perspective != 'PERSP'" in body
