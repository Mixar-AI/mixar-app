# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The camera aims at the object's visual centre, not its origin.

A Track To constraint aims at its target's ORIGIN, and an origin is very often
nowhere near the middle of the thing — a character's feet, an imported mesh's
world origin. Aiming there keeps the object in shot and NOT centred.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mixar.modules.director.core import tracking


class _Vector(tuple):
    """Enough of mathutils.Vector for the centre arithmetic."""

    def __add__(self, other):
        return _Vector(a + b for a, b in zip(self, other))

    def __truediv__(self, scalar):
        return _Vector(a / scalar for a in self)

    @property
    def length(self):
        return sum(a * a for a in self) ** 0.5


@pytest.fixture(autouse=True)
def _vector(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "mathutils", SimpleNamespace(Vector=_Vector))


def _box(centre, half=1.0):
    cx, cy, cz = centre
    return [
        (cx + sx * half, cy + sy * half, cz + sz * half)
        for sx in (-1, 1)
        for sy in (-1, 1)
        for sz in (-1, 1)
    ]


def test_an_off_origin_mesh_gets_a_centre_to_aim_at():
    obj = SimpleNamespace(bound_box=_box((0.0, 0.0, 3.0)))
    centre = tracking.local_centre(obj)
    assert centre is not None
    assert tuple(round(value, 6) for value in centre) == (0.0, 0.0, 3.0)


def test_an_object_already_centred_on_its_origin_needs_no_helper():
    """The helper would aim at exactly the same point."""
    obj = SimpleNamespace(bound_box=_box((0.0, 0.0, 0.0)))
    assert tracking.local_centre(obj) is None


def test_an_object_with_no_geometry_needs_no_helper():
    assert tracking.local_centre(SimpleNamespace(bound_box=None)) is None
    assert tracking.local_centre(SimpleNamespace(bound_box=[])) is None
    assert tracking.local_centre(SimpleNamespace()) is None


def test_the_marker_identifies_only_our_own_empties():
    assert tracking.is_focus_empty(SimpleNamespace(get=lambda _k: True)) is True
    assert tracking.is_focus_empty(SimpleNamespace(get=lambda _k: None)) is False
    assert tracking.is_focus_empty(None) is False
    # A plain object with no `get` must not raise.
    assert tracking.is_focus_empty(object()) is False


def test_the_helper_is_parented_so_it_follows_the_target():
    """Parenting is what makes it free: every move, rotation and animation of
    the target carries the aim point with it."""
    source = tracking.__file__
    body = open(source, encoding="utf-8").read()
    body = body[body.index("def ensure_focus_empty(") :]
    body = body[: body.index("\ndef ")]
    assert "empty.parent = target" in body
    assert "empty.location = centre" in body


def test_the_helper_is_invisible_but_still_evaluates():
    """A constraint target must keep evaluating, and `hide_viewport` is the
    one flag that can stop it — so the helper is drawn at zero size instead."""
    body = open(tracking.__file__, encoding="utf-8").read()
    body = body[body.index("def ensure_focus_empty(") :]
    body = body[: body.index("\ndef ")]
    assert "empty.empty_display_size = 0.0" in body
    assert "empty.hide_render = True" in body
    assert "empty.hide_select = True" in body
    assert "empty.hide_viewport" not in body


def test_clearing_tracking_takes_the_helper_with_it():
    body = open(tracking.__file__, encoding="utf-8").read()
    clear = body[body.index("def clear_tracking(") :]
    clear = clear[: clear.index("\ndef ")]
    assert "_remove_focus_empty(aimed_at, exclude_camera=camera)" in clear


def test_a_helper_another_camera_still_aims_at_is_kept():
    """Two cameras tracking one object share its helper."""
    body = open(tracking.__file__, encoding="utf-8").read()
    remove = body[body.index("def _remove_focus_empty(") :]
    remove = remove[: remove.index("\ndef ")]
    assert "_focus_used_elsewhere(empty, exclude_camera)" in remove


def test_retargeting_drops_the_helper_it_stopped_using():
    body = open(tracking.__file__, encoding="utf-8").read()
    refresh = body[body.index("def refresh_tracking(") :]
    assert "previous = getattr(constraint, \"target\", None)" in refresh
    assert "if previous is not None and previous != constraint.target:" in refresh


def test_deleting_the_camera_clears_its_tracking():
    source = open(
        tracking.__file__.replace("tracking.py", "camera_delete.py"), encoding="utf-8"
    ).read()
    assert "clear_tracking(camera)" in source
    assert source.index("clear_tracking(camera)") < source.index("doomed = shots_directing")
