# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""UV-based placement of AxF flakes: the metres-per-UV scale (no Blender needed) and the
operator's contract (source level, since bpy is a mock here)."""

import ast
from pathlib import Path

import numpy as np

from mixar.modules.axf.core.flake_mapping import metres_per_uv, uv_aspect, uv_scale

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "src/scripts/mixar/modules/axf/ui/operators/axf_flake_mapping_ops.py"


def _quad(width, height, uv_scale=1.0, offset=(0.0, 0.0, 0.0)):
    """Two triangles of a width x height plane and their UVs (0..uv_scale)."""
    o = np.asarray(offset)
    p = np.array([[0, 0, 0], [width, 0, 0], [width, height, 0], [0, height, 0]], float) + o
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float) * uv_scale
    tris = [(0, 1, 2), (0, 2, 3)]
    return p[np.array(tris)], uv[np.array(tris)]


def test_unit_uv_square_on_a_two_metre_plane_is_two_metres_per_unit():
    w, u = _quad(2.0, 2.0)
    assert abs(metres_per_uv(w, u) - 2.0) < 1e-12


def test_scale_is_area_weighted_over_islands():
    # A 1 m and a 3 m square plane, each filling a quarter of UV space: world area 10 m^2,
    # UV area 0.5 -> sqrt(20) metres per UV unit.
    w1, u1 = _quad(1.0, 1.0, 0.5)
    w2, u2 = _quad(3.0, 3.0, 0.5, offset=(5, 0, 0))
    got = metres_per_uv(np.concatenate([w1, w2]), np.concatenate([u1, u2]))
    assert abs(got - np.sqrt(20.0)) < 1e-12


def test_degenerate_uvs_give_no_scale():
    w, u = _quad(1.0, 1.0, 0.0)
    assert metres_per_uv(w, u) == 0.0
    assert metres_per_uv(np.empty((0, 3, 3)), np.empty((0, 3, 2))) == 0.0


def test_stretched_unwrap_keeps_flakes_square():
    # A 2 m x 1 m plane on the whole unit UV square: 2 m per unit U, 1 m per unit V.
    w, u = _quad(2.0, 1.0)
    assert abs(uv_aspect(w, u) - 2.0) < 1e-12
    su, sv = uv_scale(w, u)
    assert abs(su - 2.0) < 1e-12 and abs(sv - 1.0) < 1e-12
    # The split preserves the area scale.
    assert abs(su * sv - metres_per_uv(w, u) ** 2) < 1e-12


def test_undistorted_unwrap_has_unit_aspect():
    w, u = _quad(3.0, 3.0, 0.25)
    assert abs(uv_aspect(w, u) - 1.0) < 1e-12
    assert uv_scale(*_quad(1.0, 1.0, 0.0)) == (0.0, 0.0)


def test_degenerate_uv_slivers_do_not_skew_the_scale():
    # A clean 1 m panel on a quarter of UV space, plus one sliver: a 0.1 m^2 triangle whose
    # UVs nearly collapse along V (a seam artifact). Before filtering, its huge dP/dv
    # dragged the aspect far from 1 on a real car body.
    w, u = _quad(1.0, 1.0, 0.5)
    sliver_w = np.array([[[2, 0, 0], [2.5, 0, 0], [2, 0.4, 0]]], float)
    sliver_u = np.array([[[0.6, 0.6], [0.7, 0.6], [0.6, 0.6000001]]], float)
    ww, uu = np.concatenate([w, sliver_w]), np.concatenate([u, sliver_u])
    assert abs(uv_aspect(ww, uu) - 1.0) > 0.5  # The raw estimate is skewed.
    su, sv = uv_scale(ww, uu)
    assert abs(su - 2.0) < 1e-9 and abs(sv - 2.0) < 1e-9


def test_clean_unwrap_is_accepted_for_auto_uv_mapping():
    from mixar.modules.axf.core.flake_mapping import uv_quality, uv_verdict

    q = uv_quality(*_quad(1.0, 1.0, 0.5))
    assert abs(q['even_area'] - 1.0) < 1e-12 and abs(q['stretch'] - 1.0) < 1e-12
    assert uv_verdict(q) == ''


def test_stretched_unwrap_keeps_box_projection():
    from mixar.modules.axf.core.flake_mapping import REASON_STRETCHED, uv_quality, uv_verdict

    q = uv_quality(*_quad(2.0, 1.0))  # 2:1 stretch everywhere.
    assert abs(q['stretch'] - 2.0) < 1e-12
    assert uv_verdict(q) == REASON_STRETCHED


def test_unevenly_packed_islands_keep_box_projection():
    from mixar.modules.axf.core.flake_mapping import REASON_UNEVEN, uv_quality, uv_verdict

    # Two equal-area panels packed at 2 m and 6 m per UV unit: half the car would get
    # flakes three times the wrong size.
    w1, u1 = _quad(1.0, 1.0, 0.5)
    w2, u2 = _quad(1.0, 1.0, 1.0 / 6.0, offset=(5, 0, 0))
    q = uv_quality(np.concatenate([w1, w2]), np.concatenate([u1, u2]))
    assert abs(q['even_area'] - 0.5) < 1e-12
    assert uv_verdict(q) == REASON_UNEVEN


def test_import_places_flakes_along_clean_uvs():
    src = (ROOT / "src/scripts/mixar/modules/axf/ui/operators/axf_import_ops.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MIXIE_OT_import_axf")
    prop = next(n for n in cls.body if isinstance(n, ast.AnnAssign)
                and getattr(n.target, "id", "") == "flakes_along_uv")
    default = next(k.value for k in prop.annotation.keywords if k.arg == "default")
    assert ast.literal_eval(default) is True
    assert "auto_uv_mapping" in src and "evaluated_depsgraph_get" in src


def test_operator_contract():
    tree = ast.parse(OPS.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    fields = {t.id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name) and t.id in ("bl_idname", "bl_options")}
    assert fields["bl_idname"] == "mixie.axf_flake_mapping"
    assert "UNDO" in fields["bl_options"]
    src = OPS.read_text(encoding="utf-8")
    # The scale comes from the evaluated mesh in world space, so object scale is honoured.
    assert "evaluated_depsgraph_get" in src and "object_uv_scale" in src
