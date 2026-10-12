# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A retopology result lands on its source mesh, not the world origin.

``post_import_rename_and_setup`` moves the cleaned mesh's bottom-center origin
to (0, 0, 0) — right for a fresh generation, wrong for retopology, where the
low-poly should overlay the high-poly it was made from (and a batch of N
results should not stack at the origin). Retopology captures the source's
world bottom-center at enqueue time and passes it back as ``target_location``;
every other caller keeps the origin default.
"""

import sys
import types
from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core import model_io as MIO  # noqa: E402


class _Vec:
    def __init__(self, xyz):
        self.x, self.y, self.z = (float(v) for v in xyz)

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __neg__(self):
        return _Vec((-self.x, -self.y, -self.z))

    def __iadd__(self, other):
        return _Vec((self.x + other.x, self.y + other.y, self.z + other.z))


class _Translate:
    """A world matrix that only translates (enough for bbox math)."""

    def __init__(self, offset):
        self.offset = offset

    def __matmul__(self, v):
        ox, oy, oz = self.offset
        return _Vec((v.x + ox, v.y + oy, v.z + oz))


def _box(lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


@pytest.fixture
def fake_mathutils(monkeypatch):
    mod = types.ModuleType("mathutils")
    mod.Vector = _Vec
    mod.Matrix = SimpleNamespace(Translation=lambda v: v)
    monkeypatch.setitem(sys.modules, "mathutils", mod)


def test_world_bottom_center_is_bbox_xy_center_at_lowest_z(fake_mathutils):
    # A 2x4x6 box whose local origin is at its center, moved to (10, 20, 30).
    obj = SimpleNamespace(bound_box=_box((-1, -2, -3), (1, 2, 3)),
                          matrix_world=_Translate((10, 20, 30)))
    assert MIO.world_bottom_center(obj) == (10.0, 20.0, 27.0)


def _mesh():
    mesh = SimpleNamespace(
        bound_box=_box((0, 0, 0), (2, 2, 2)),
        data=SimpleNamespace(transform=lambda m: None),
        matrix_world=SimpleNamespace(translation=_Vec((0, 0, 0))),
        select_set=lambda v: None,
        location=None,
    )
    return mesh


@pytest.mark.parametrize("target, expected", [
    (None, (0, 0, 0)),
    ((10.0, 20.0, 27.0), (10.0, 20.0, 27.0)),
])
def test_origin_default_kept_and_target_honoured(fake_mathutils, monkeypatch,
                                                 target, expected):
    monkeypatch.setattr(MIO.bpy, "context", SimpleNamespace(
        mode="OBJECT", view_layer=SimpleNamespace(objects=SimpleNamespace(active=None))))
    mesh = _mesh()
    MIO._set_origin_bottom_and_center(mesh, target)
    assert mesh.location == expected
