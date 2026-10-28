# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Smart UV result lands over its source, not at the origin at 1 m.

Tripo ``/v3/mesh/uv`` hands the mesh back centred on the origin and scaled so
its largest dimension is 1 m. The client records the source's world box at
submit and fits the imported result's MEASURED box back onto it: one uniform
scale, then a translation matching the box centres. Pinned here: the box
maths, the base-mesh measurement and the bpy glue run against fakes.
"""

import math
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

from mixar.modules.hunyuan.core import tripo_uv_placement as P


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class Vertices:
    def __init__(self, co):
        self.co = np.asarray(co, dtype=np.float64).reshape(-1, 3)

    def __len__(self):
        return len(self.co)

    def foreach_get(self, attr, out):
        assert attr == "co"
        out[:] = self.co.ravel()


def mesh_object(co, matrix=None, type='MESH', name="Obj", parent=None):
    matrix = np.identity(4) if matrix is None else np.asarray(matrix, dtype=float)

    def evaluated_get(_depsgraph):
        raise AssertionError("placement must measure the base mesh, not the evaluated one")

    return NS(name=name, type=type, data=NS(vertices=Vertices(co)),
              matrix_world=matrix.tolist(), matrix_basis=matrix.tolist(),
              matrix_parent_inverse=np.identity(4).tolist(), parent=parent,
              evaluated_get=evaluated_get)


def trs(location=(0, 0, 0), rot_z_deg=0.0, scale=1.0):
    a = math.radians(rot_z_deg)
    c, s = math.cos(a), math.sin(a)
    m = np.identity(4)
    m[:3, :3] = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) * scale
    m[:3, 3] = location
    return m


def cube(size=(1, 1, 1), center=(0, 0, 0)):
    sx, sy, sz = (v * 0.5 for v in size)
    cx, cy, cz = center
    return [(cx + x * sx, cy + y * sy, cz + z * sz)
            for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]


def apply_fit(fit, box):
    scale, offset = fit
    return (tuple(scale * box[0][i] + offset[i] for i in range(3)),
            tuple(scale * box[1][i] + offset[i] for i in range(3)))


def assert_box(actual, expected, tol=1e-9):
    for got, want in zip(actual[0] + actual[1], expected[0] + expected[1]):
        assert got == pytest.approx(want, abs=tol), (actual, expected)


# ---------------------------------------------------------------------------
# Box maths
# ---------------------------------------------------------------------------


# The paid run (QA report, smartuv/dl1): the source Suzanne at loc (-4, 0, 1),
# rot z 30 deg, scale 1.5 has this world box; Tripo returned it as this one.
SOURCE_PAID1 = ((-4.295 - 3.713 / 2, 0.108 - 3.134 / 2, 1.0 - 2.953 / 2),
                (-4.295 + 3.713 / 2, 0.108 + 3.134 / 2, 1.0 + 2.953 / 2))
RESULT_PAID1 = ((-0.5, -0.42211, -0.39771), (0.5, 0.42211, 0.39771))


def test_the_normalised_result_is_scaled_to_the_source_and_centred_on_it():
    scale, offset = P.fit_scale_and_offset(SOURCE_PAID1, RESULT_PAID1)
    assert scale == pytest.approx(3.713)
    assert offset == pytest.approx((-4.295, 0.108, 1.0))
    placed = apply_fit((scale, offset), RESULT_PAID1)
    assert P.box_center(placed) == pytest.approx(P.box_center(SOURCE_PAID1))
    assert P.box_max_dimension(placed) == pytest.approx(3.713)


def test_the_fit_uses_the_measured_result_box_not_a_fixed_metre():
    # A result that is NOT 1 m and NOT centred still lands exactly on the source.
    source = ((2.0, -1.0, 0.0), (6.0, 1.0, 3.0))
    result = ((10.0, 10.0, 10.0), (12.0, 11.0, 11.5))
    fit = P.fit_scale_and_offset(source, result)
    assert fit[0] == pytest.approx(2.0)
    assert_box(apply_fit(fit, result), source)


def test_the_scale_is_uniform_so_the_shape_keeps_its_proportions():
    source = ((0, 0, 0), (4, 2, 1))
    result = ((-0.5, -0.25, -0.125), (0.5, 0.25, 0.125))
    scale, _offset = P.fit_scale_and_offset(source, result)
    placed = apply_fit((scale, _offset), result)
    extents = [placed[1][i] - placed[0][i] for i in range(3)]
    assert extents == pytest.approx([4, 2, 1])


def test_several_sources_are_fitted_to_the_union_of_their_boxes():
    a = ((-3.0, 0.0, 0.0), (-1.0, 1.0, 2.0))
    b = ((1.0, -2.0, 0.5), (4.0, 0.5, 1.0))
    union = P.union_bounds([a, None, b])
    assert union == ((-3.0, -2.0, 0.0), (4.0, 1.0, 2.0))
    result = ((-0.5, -3 / 14, -2 / 14), (0.5, 3 / 14, 2 / 14))
    fit = P.fit_scale_and_offset(union, result)
    assert fit[0] == pytest.approx(7.0)
    assert_box(apply_fit(fit, result), union)


@pytest.mark.parametrize("source, result", [
    (None, RESULT_PAID1),
    (SOURCE_PAID1, None),
    (SOURCE_PAID1, ((0, 0, 0), (0, 0, 0))),
    (((1, 1, 1), (1, 1, 1)), RESULT_PAID1),
    (SOURCE_PAID1, ((0, 0, 0), (float("nan"), 1, 1))),
    (((0, 0, 0), (float("inf"), 1, 1)), RESULT_PAID1),
])
def test_no_fit_without_two_usable_boxes(source, result):
    assert P.fit_scale_and_offset(source, result) is None


def test_union_of_nothing_is_nothing():
    assert P.union_bounds([]) is None
    assert P.union_bounds([None]) is None


def test_fit_matrix_is_scale_then_translate():
    rows = P.fit_matrix(2.0, (1.0, -2.0, 3.0))
    point = np.array([0.5, 0.25, -1.0, 1.0])
    assert (np.array(rows) @ point)[:3] == pytest.approx([2.0, -1.5, 1.0])


# ---------------------------------------------------------------------------
# Measuring meshes
# ---------------------------------------------------------------------------


def test_the_source_box_is_world_space_including_rotation_and_scale():
    matrix = trs((-4, 0, 1), 30.0, 1.5)
    co = cube((2, 1, 1))
    obj = mesh_object(co, matrix)
    world = (np.c_[np.array(co), np.ones(8)] @ matrix.T)[:, :3]
    expected = (tuple(world.min(axis=0)), tuple(world.max(axis=0)))
    assert_box(P.source_world_bounds([obj]), expected)


def test_several_meshes_measure_as_one_union_and_non_meshes_are_ignored():
    a = mesh_object(cube((2, 2, 2)), trs((-3, 0, 0)))
    b = mesh_object(cube((1, 1, 1)), trs((5, 1, 2)))
    light = mesh_object(cube((100, 100, 100)), type='LIGHT')
    empty = mesh_object(np.empty((0, 3)))
    box = P.mesh_world_bounds([a, light, b, empty])
    assert_box(box, ((-4, -1, -1), (5.5, 1.5, 2.5)))


def test_no_vertices_no_box():
    assert P.mesh_world_bounds([mesh_object(np.empty((0, 3)))]) is None
    assert P.mesh_world_bounds([]) is None


def test_the_fresh_world_matrix_composes_the_parent_chain():
    parent = mesh_object(cube(), trs((1, 0, 0)), type='EMPTY')
    child = mesh_object(cube(), trs(scale=2.0), parent=parent)
    child.matrix_world = np.identity(4).tolist()  # stale, as right after an import
    world = P.fresh_world_matrix(child)
    assert world == pytest.approx(trs((1, 0, 0)) @ trs(scale=2.0))
    box = P.mesh_world_bounds([child], P.fresh_world_matrix)
    assert_box(box, ((0, -1, -1), (2, 1, 1)))


# ---------------------------------------------------------------------------
# The bpy glue, against fakes
# ---------------------------------------------------------------------------


class FakeMatrix:
    """Just enough of mathutils.Matrix: row iteration and ``@``."""

    def __init__(self, rows):
        self.m = np.array([list(r) for r in rows], dtype=np.float64)

    def __iter__(self):
        return iter(self.m.tolist())

    def __matmul__(self, other):
        return FakeMatrix(self.m @ FakeMatrix(other).m)


@pytest.fixture
def fake_blender(monkeypatch):
    objects = {}
    monkeypatch.setitem(sys.modules, "bpy", NS(data=NS(objects=objects)))
    monkeypatch.setitem(sys.modules, "mathutils", NS(Matrix=FakeMatrix))
    return objects


def _placed_box(obj):
    return P.mesh_world_bounds([obj], P.fresh_world_matrix)


def test_place_over_source_moves_the_import_onto_the_source_box(fake_blender):
    result = mesh_object(cube((1.0, 0.8442, 0.7954)), name="Src")
    result.matrix_basis = FakeMatrix(np.identity(4))
    fake_blender["Src"] = result

    assert P.place_over_source("Src", SOURCE_PAID1) is True
    assert_box(_placed_box(result), SOURCE_PAID1, tol=2e-3)
    assert P.box_max_dimension(_placed_box(result)) == pytest.approx(3.713)


def test_a_hierarchy_moves_as_one_through_its_root(fake_blender):
    root = mesh_object(cube(), type='EMPTY', name="Root")
    root.matrix_basis = FakeMatrix(trs((0.25, 0, 0)))
    child = mesh_object(cube((1, 0.5, 0.5)), name="Mesh", parent=root)
    child.matrix_basis = FakeMatrix(np.identity(4))
    fake_blender.update(Root=root, Mesh=child)
    source = ((0, 0, 0), (2, 1, 1))

    assert P.place_over_source("Root, Mesh", source) is True
    assert_box(_placed_box(child), source)
    assert child.matrix_basis.m == pytest.approx(np.identity(4))  # only the root moved


def test_placement_is_skipped_without_a_usable_source_box(fake_blender):
    result = mesh_object(cube(), name="Src")
    result.matrix_basis = FakeMatrix(np.identity(4))
    fake_blender["Src"] = result

    assert P.place_over_source("Src", None) is False
    assert P.place_over_source("Missing", SOURCE_PAID1) is False
    assert result.matrix_basis.m == pytest.approx(np.identity(4))
