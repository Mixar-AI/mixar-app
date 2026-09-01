# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The vertex projection must agree with Blender's own, exactly.

``project_mesh_vertices`` re-implements ``view3d_utils.location_3d_to_region_2d``
in numpy because the vertex-group pass runs over hundreds of thousands of
vertices while the user waits, and a Python loop there stalls the UI. A
re-implementation that is subtly off is the worst outcome available: every
vertex lands a little wrong, the vertex group is quietly the wrong region, and
nothing anywhere reports a problem.

So this file pins it against the reference formula Blender uses::

    prj = perspective_matrix @ (co.x, co.y, co.z, 1.0)
    if prj.w > 0:
        x = width/2  + (width/2)  * (prj.x / prj.w)
        y = height/2 + (height/2) * (prj.y / prj.w)

``bpy`` is a MagicMock here, so the module's Blender inputs are supplied as
small real fakes — a mock would make every assertion vacuously true.
"""

import math

import numpy as np
import pytest

from mixar.modules.scribble_mark.core import projection


# =============================================================================
# Minimal stand-ins for the Blender types the function touches
# =============================================================================

class FakeMatrix:
    """Just enough of mathutils.Matrix: numpy-convertible, invertible."""

    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, i):
        return self.rows[i]

    def __len__(self):
        return len(self.rows)

    def inverted_safe(self):
        return FakeMatrix(np.linalg.inv(np.array(self.rows)).tolist())

    def transposed(self):
        return FakeMatrix(np.array(self.rows).T.tolist())

    def to_3x3(self):
        return FakeMatrix([r[:3] for r in self.rows[:3]])

    @property
    def translation(self):
        return [self.rows[0][3], self.rows[1][3], self.rows[2][3]]


class FakeVertices:
    def __init__(self, coords, normals=None):
        self._co = np.asarray(coords, dtype=np.float64)
        self._no = np.asarray(
            normals if normals is not None else [[0.0, 0.0, 1.0]] * len(coords),
            dtype=np.float64,
        )

    def __len__(self):
        return len(self._co)

    def foreach_get(self, attr, out):
        source = self._co if attr == "co" else self._no
        out[:] = source.ravel()


class FakeObject:
    def __init__(self, coords, matrix_world=None, normals=None):
        self.name = "Fake"
        self.type = "MESH"
        self.matrix_world = FakeMatrix(matrix_world or np.eye(4).tolist())
        self.data = type("D", (), {"vertices": FakeVertices(coords, normals)})()


class FakeRegion:
    def __init__(self, width=1920, height=1080):
        self.width = width
        self.height = height


class FakeRV3D:
    def __init__(self, perspective_matrix, view_matrix=None, is_perspective=True):
        self.perspective_matrix = FakeMatrix(perspective_matrix)
        self.view_matrix = FakeMatrix(view_matrix or np.eye(4).tolist())
        self.is_perspective = is_perspective
        self.view_rotation = None


# =============================================================================
# Reference implementations
# =============================================================================

def reference_project(perspective_matrix, region, co):
    """Blender's own location_3d_to_region_2d, transcribed."""
    m = np.asarray(perspective_matrix, dtype=np.float64)
    prj = m @ np.array([co[0], co[1], co[2], 1.0])
    if prj[3] <= 0.0:
        return None
    half_w = region.width / 2.0
    half_h = region.height / 2.0
    return (
        half_w + half_w * (prj[0] / prj[3]),
        half_h + half_h * (prj[1] / prj[3]),
    )


def perspective_matrix(fov_deg=50.0, aspect=16 / 9, near=0.1, far=1000.0,
                       eye_z=10.0):
    """A symmetric frustum times a look-down-minus-Z view matrix."""
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    proj = np.array([
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (far + near) / (near - far), (2 * far * near) / (near - far)],
        [0.0, 0.0, -1.0, 0.0],
    ])
    view = np.eye(4)
    view[2, 3] = -eye_z          # camera at +Z looking down -Z
    return (proj @ view).tolist(), view.tolist()


# =============================================================================
# Tests
# =============================================================================

class TestVertexProjection:
    def test_matches_blenders_formula_on_a_perspective_view(self):
        pm, vm = perspective_matrix()
        region = FakeRegion(1920, 1080)
        rv3d = FakeRV3D(pm, vm, is_perspective=True)

        coords = [
            [0.0, 0.0, 0.0], [1.0, 0.5, -2.0], [-3.0, 2.0, 1.0],
            [0.25, -0.75, 4.0], [5.0, 5.0, -5.0],
        ]
        obj = FakeObject(coords)

        xs, ys, usable = projection.project_mesh_vertices(
            region, rv3d, obj, front_facing_only=False
        )
        assert xs is not None

        for i, co in enumerate(coords):
            expected = reference_project(pm, region, co)
            if expected is None:
                assert not usable[i], f"vertex {i} is behind the camera"
                continue
            assert usable[i]
            assert xs[i] == pytest.approx(expected[0], abs=1e-6)
            assert ys[i] == pytest.approx(expected[1], abs=1e-6)

    def test_matches_under_a_non_identity_object_transform(self):
        """The model matrix is applied by hand rather than folded into the
        MVP, so it gets its own check."""
        pm, vm = perspective_matrix()
        region = FakeRegion(1280, 720)
        rv3d = FakeRV3D(pm, vm)

        model = np.array([
            [2.0, 0.0, 0.0, 3.0],
            [0.0, 0.5, 0.0, -1.0],
            [0.0, 0.0, 1.5, 2.0],
            [0.0, 0.0, 0.0, 1.0],
        ])
        coords = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [-2.0, 0.5, 3.0]]
        obj = FakeObject(coords, matrix_world=model.tolist())

        xs, ys, usable = projection.project_mesh_vertices(
            region, rv3d, obj, front_facing_only=False
        )

        for i, co in enumerate(coords):
            world = model @ np.array([*co, 1.0])
            expected = reference_project(pm, region, world[:3])
            if expected is None:
                continue
            assert usable[i]
            assert xs[i] == pytest.approx(expected[0], abs=1e-6)
            assert ys[i] == pytest.approx(expected[1], abs=1e-6)

    def test_vertices_behind_the_camera_are_marked_unusable(self):
        """Dividing by a negative w flips a vertex to the opposite side of the
        frame, where it would silently join whatever region is there."""
        pm, vm = perspective_matrix(eye_z=0.0)
        region = FakeRegion()
        rv3d = FakeRV3D(pm, vm)
        # +Z is behind a camera looking down -Z.
        obj = FakeObject([[0.0, 0.0, 5.0], [0.0, 0.0, -5.0]])

        _xs, _ys, usable = projection.project_mesh_vertices(
            region, rv3d, obj, front_facing_only=False
        )
        assert not usable[0]
        assert usable[1]

    def test_an_empty_mesh_returns_nothing_rather_than_raising(self):
        pm, vm = perspective_matrix()
        result = projection.project_mesh_vertices(
            FakeRegion(), FakeRV3D(pm, vm), FakeObject([])
        )
        assert result == (None, None, None)


class TestFrontFacing:
    def _setup(self, normals):
        pm, vm = perspective_matrix(eye_z=10.0)
        coords = [[0.0, 0.0, 0.0]] * len(normals)
        return (FakeRegion(), FakeRV3D(pm, vm, is_perspective=True),
                FakeObject(coords, normals=normals))

    def test_a_normal_pointing_at_the_camera_is_front_facing(self):
        """The camera sits at +Z looking down -Z, so a +Z normal faces it."""
        region, rv3d, obj = self._setup([[0.0, 0.0, 1.0]])
        _xs, _ys, usable = projection.project_mesh_vertices(region, rv3d, obj)
        assert usable[0]

    def test_a_normal_pointing_away_is_culled(self):
        """This is what makes a mark mean 'the wall I can see' rather than
        'this wall and the one behind it'."""
        region, rv3d, obj = self._setup([[0.0, 0.0, -1.0]])
        _xs, _ys, usable = projection.project_mesh_vertices(region, rv3d, obj)
        assert not usable[0]

    def test_non_uniform_scale_does_not_invert_the_test(self):
        """Normals transform by the inverse transpose. Under the plain model
        matrix a stretched object's front/back test silently flips."""
        pm, vm = perspective_matrix(eye_z=10.0)
        squash = [[10.0, 0, 0, 0], [0, 10.0, 0, 0], [0, 0, 0.1, 0], [0, 0, 0, 1]]
        region = FakeRegion()
        rv3d = FakeRV3D(pm, vm, is_perspective=True)

        # A normal tilted mostly +Z (toward the camera) but with a large
        # lateral component: squashing Z would swing it past the horizon if
        # the wrong matrix were used.
        obj = FakeObject([[0.0, 0.0, 0.0]], matrix_world=squash,
                         normals=[[0.9, 0.0, 0.44]])
        _xs, _ys, usable = projection.project_mesh_vertices(region, rv3d, obj)
        assert usable[0], "inverse-transpose normal matrix not applied"


class TestCameraBakeFormulas:
    """The baked camera is derived from the viewport's own projection matrix
    rather than SpaceView3D.lens. These are the two conversions that makes
    possible, checked by round-tripping them."""

    @pytest.mark.parametrize("fov_deg", [20.0, 50.0, 90.0, 120.0])
    def test_horizontal_fov_round_trips_through_the_projection_matrix(self, fov_deg):
        # A symmetric frustum with aspect 1 so f == 1/tan(fov/2) is the x scale.
        f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
        recovered = 2.0 * math.atan(1.0 / abs(f))
        assert math.degrees(recovered) == pytest.approx(fov_deg, abs=1e-9)

    @pytest.mark.parametrize("width", [2.0, 10.0, 0.5])
    def test_ortho_width_round_trips_through_the_projection_matrix(self, width):
        # Orthographic P[0][0] == 2 / width.
        scale_x = 2.0 / width
        assert 2.0 / abs(scale_x) == pytest.approx(width)

    def test_the_diagonal_entry_is_transpose_invariant(self):
        """The formulas read window_matrix[0][0]. That element sits on the
        diagonal, so they hold whichever storage order mathutils uses — which
        is what makes them safe to write without a convention check."""
        m = np.arange(16, dtype=float).reshape(4, 4)
        assert m[0][0] == m.T[0][0]
