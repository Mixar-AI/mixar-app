# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-numpy tests for the real-world scale UV math (agent texturing).

``real_scale_uv`` decides, per mesh, whether the authoring UV map can be
rescaled into metres or must be replaced by a metric box projection, and
bootstraps a non-overlapping authoring map on UV-less meshes. The math is
plain numpy, so it runs here without Blender.
"""

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/scripts/mixar/modules/paint/core/agent_tools/real_scale_uv.py"

_spec = importlib.util.spec_from_file_location("agent_real_scale_uv_under_test", MODULE)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


def _square(size=1.0):
    """Two triangles of a ``size`` x ``size`` square in the XY plane."""
    s = float(size)
    pos = np.array([
        [[0, 0, 0], [s, 0, 0], [s, s, 0]],
        [[0, 0, 0], [s, s, 0], [0, s, 0]],
    ], dtype=np.float64)
    return pos


def test_identity_unwrap_is_square_and_one_metre_per_unit():
    pos = _square(2.0)
    uv = pos[:, :, :2].copy()
    metrics = rs.triangle_metrics(pos, uv)
    assert np.allclose(metrics["area"], [2.0, 2.0])
    assert np.allclose(metrics["anisotropy"], 1.0)
    health = rs.summarize_uv_health(metrics)
    assert health["meters_per_uv"] == pytest.approx(1.0)
    assert health["surface_area_m2"] == pytest.approx(4.0)
    assert rs.uv_is_reusable(health)


def test_a_half_size_unwrap_covers_two_metres_per_unit():
    pos = _square(2.0)
    health = rs.summarize_uv_health(rs.triangle_metrics(pos, pos[:, :, :2] / 2.0))
    assert health["meters_per_uv"] == pytest.approx(2.0)
    assert health["anisotropy"] == pytest.approx(1.0)


def test_a_stretched_unwrap_is_not_reusable():
    """A primitive cube scaled 2:1 keeps its unit UVs: 2:1 texels."""
    pos = _square(1.0) * np.array([2.0, 1.0, 1.0])
    uv = _square(1.0)[:, :, :2]
    health = rs.summarize_uv_health(rs.triangle_metrics(pos, uv))
    assert health["anisotropy"] == pytest.approx(2.0)
    assert not rs.uv_is_reusable(health)


def test_collapsed_uv_triangles_count_as_degenerate():
    pos = _square(1.0)
    uv = np.zeros((2, 3, 2))
    metrics = rs.triangle_metrics(pos, uv)
    assert np.all(np.isinf(metrics["anisotropy"]))
    health = rs.summarize_uv_health(metrics)
    assert health["meters_per_uv"] is None and not rs.uv_is_reusable(health)


def test_islands_at_different_densities_are_not_reusable():
    pos = np.concatenate([_square(1.0), _square(1.0) + [5.0, 0.0, 0.0]])
    uv = np.concatenate([_square(1.0)[:, :, :2], _square(1.0)[:, :, :2] * 0.1 + 2.0])
    health = rs.summarize_uv_health(rs.triangle_metrics(pos, uv))
    assert health["density_spread"] > rs.MAX_DENSITY_SPREAD
    assert not rs.uv_is_reusable(health)


def test_an_empty_region_reports_no_density():
    health = rs.summarize_uv_health({"area": np.zeros(0), "uv_area": np.zeros(0),
                                     "anisotropy": np.zeros(0)})
    assert health["meters_per_uv"] is None and health["surface_area_m2"] == 0.0


def test_v_follows_the_longest_in_plane_axis():
    # A board: long along Y, thin along Z.
    axes = rs.box_projection_axes([0.3, 2.0, 0.05])
    # Top face (dominant Z): V along Y (the board's length), U along X.
    assert axes[2][:2] == (0, 1)
    # Side face (dominant X): V still along Y.
    assert axes[0][1] == 1
    # End face (dominant Y): V along the longer of X / Z.
    assert axes[1][1] == 0


def _cube_faces(extents):
    """Outward-facing quads of a box, wound counter-clockwise from outside."""
    ex, ey, ez = (float(v) / 2.0 for v in extents)
    corners = {
        (sx, sy, sz): np.array([sx * ex, sy * ey, sz * ez])
        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    }
    faces = []
    for axis in range(3):
        for sign in (-1, 1):
            normal = np.zeros(3)
            normal[axis] = sign
            u_axis, v_axis = [a for a in range(3) if a != axis]
            quad = []
            for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                key = [0, 0, 0]
                key[axis], key[u_axis], key[v_axis] = sign, du, dv
                quad.append(corners[tuple(key)])
            quad = np.array(quad)
            # Fix winding so the quad's geometric normal points outward.
            geometric = np.cross(quad[1] - quad[0], quad[2] - quad[0])
            if np.dot(geometric, normal) < 0:
                quad = quad[::-1]
            faces.append((quad, normal))
    return faces


@pytest.mark.parametrize("extents", [(1.0, 1.0, 1.0), (0.6, 0.6, 2.0), (3.0, 0.2, 0.5)])
def test_box_projection_is_metric_and_never_mirrored(extents):
    for quad, normal in _cube_faces(extents):
        uv = rs.box_project(quad, np.repeat(normal[None, :], 4, axis=0), extents)
        # One UV unit per metre: UV edge lengths equal the 3-D edge lengths.
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
            assert np.linalg.norm(uv[b] - uv[a]) == pytest.approx(np.linalg.norm(quad[b] - quad[a]))
        # A face wound counter-clockwise from outside stays counter-clockwise
        # in UV space, so no face shows a mirrored texture.
        signed = 0.5 * sum(uv[i, 0] * uv[(i + 1) % 4, 1] - uv[(i + 1) % 4, 0] * uv[i, 1] for i in range(4))
        assert signed > 0, (normal, signed)


def test_pack_box_groups_keeps_one_scale_and_separate_cells():
    rng = np.random.default_rng(3)
    loop_uv = np.concatenate([rng.uniform(0, span, (8, 2)) for span in (1.0, 1.0, 2.0, 2.0, 0.5, 0.5)])
    groups = np.repeat(np.arange(6), 8)
    packed = rs.pack_box_groups(loop_uv, groups)
    assert packed.min() >= 0.0 and packed.max() <= 1.0
    boxes = []
    ratios = []
    for group in range(6):
        rows = groups == group
        low, high = packed[rows].min(axis=0), packed[rows].max(axis=0)
        boxes.append((low, high))
        src = loop_uv[rows].max(axis=0) - loop_uv[rows].min(axis=0)
        ratios.append((high - low) / src)
    # One common scale: square texels and one density for the whole mesh.
    assert np.allclose(np.array(ratios), ratios[0][0])
    for i in range(6):
        for j in range(i + 1, 6):
            (lo_a, hi_a), (lo_b, hi_b) = boxes[i], boxes[j]
            overlap = np.all(np.minimum(hi_a, hi_b) > np.maximum(lo_a, lo_b))
            assert not overlap, (i, j)


def test_pack_box_groups_handles_missing_groups():
    packed = rs.pack_box_groups(np.array([[0.0, 0.0], [1.0, 1.0]]), np.array([4, 4]))
    assert packed.min() >= 0.0 and packed.max() <= 1.0
    assert rs.pack_box_groups(np.zeros((0, 2)), np.zeros(0, dtype=np.int64)).shape == (0, 2)


def test_rounding_drops_non_finite_values():
    assert rs._rounded(math.inf) is None and rs._rounded(None) is None
    assert rs._rounded(1.234567) == 1.2346
