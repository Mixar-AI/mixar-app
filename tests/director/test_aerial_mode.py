# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Aerial mode: O turns the main viewport into a top-down map of the scene.

`mixar.director_aerial` toggles `navigation_mode` AERIAL (an ORTHO top view
fitted to the scene's padded bounds); a click in the stage runs the native
`MIXAR_OT_director_place_camera`; O again or Esc (`mixar.director_aerial_exit`)
returns to the camera through `enter_camera_view`, the single way back.
"""

import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core import scene_bounds  # noqa: E402
from mixar.modules.director.core import viewport  # noqa: E402

DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"

KEYMAP = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")
AERIAL_OPS = (DIRECTOR / "ui/operators/aerial_ops.py").read_text(encoding="utf-8")
PROPERTIES = (DIRECTOR / "ui/properties/director_properties.py").read_text(encoding="utf-8")
VIEWPORT = (DIRECTOR / "core/viewport.py").read_text(encoding="utf-8")
STATE = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
HEADER = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
PLACE = (VIEW3D / "view3d_director_place_camera.cc").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")
GATE = (VIEW3D / "view3d_director_cinema_gate.cc").read_text(encoding="utf-8")


class _Matrix:
    """Translation-only matrix_world double: ``matrix @ vector``."""

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.offset = (x, y, z)

    def __matmul__(self, vector):
        return tuple(float(v) + o for v, o in zip(vector, self.offset))


def _box(hx, hy, hz):
    return [
        (sx * hx, sy * hy, sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    ]


def _block(source: str, start: str) -> str:
    body = source[source.index(start):]
    return body[: body.index("\n}\n") + 3]


# -------------------------------------------------------------------------
# core/scene_bounds.py


def test_world_bounds_unions_transformed_corners():
    items = [(_Matrix(10.0, 0.0, 0.0), _box(1, 2, 3)), (_Matrix(-4.0, 5.0, 1.0), _box(1, 1, 1))]
    lo, hi = scene_bounds.world_bounds(items)
    assert lo == (-5.0, -2.0, -3.0)
    assert hi == (11.0, 6.0, 3.0)
    assert scene_bounds.world_bounds([]) is None


def test_padding_is_ten_percent_with_a_two_metre_floor():
    # A 100 m wide scene pads by 10 m; a 1 m deep one by the 2 m floor.
    rect = scene_bounds.padded_xy(((0.0, 0.0, 0.0), (100.0, 1.0, 0.0)))
    assert rect == (-10.0, 110.0, -2.0, 3.0)


def test_empty_scene_is_a_twenty_metre_square_and_camera_is_unioned():
    assert scene_bounds.padded_xy(None) == (-10.0, 10.0, -10.0, 10.0)
    rect = scene_bounds.padded_xy(None, camera_xy=(30.0, -25.0))
    # Union only: the camera sits ON the edge, nothing pads after it.
    assert rect == (-10.0, 30.0, -25.0, 10.0)
    inside = scene_bounds.padded_xy(None, camera_xy=(1.0, 1.0))
    assert inside == (-10.0, 10.0, -10.0, 10.0)


def test_aerial_view_centres_the_rect_and_fits_the_stage():
    # 40 x 20 m in a 1000 x 500 px region: width-limited, 40 m across the
    # 1000 px major axis at lens 50 -> dist = 40 * 50 / 72.
    location, distance = scene_bounds.aerial_view(
        (-10.0, 30.0, -10.0, 10.0), 1.5, 1000, 500, 50.0, stage_fraction=1.0
    )
    assert location == (10.0, 0.0, 1.5)
    assert math.isclose(distance, 40.0 * 50.0 / 72.0)
    # A narrower stage needs a wider span: 0.5 doubles it.
    _, narrow = scene_bounds.aerial_view(
        (-10.0, 30.0, -10.0, 10.0), 1.5, 1000, 500, 50.0, stage_fraction=0.5
    )
    assert math.isclose(narrow, 80.0 * 50.0 / 72.0)
    # A tall rect is limited by the height: 40 m over 500 px of a 1000 px major.
    _, tall = scene_bounds.aerial_view((0.0, 1.0, 0.0, 40.0), 0.0, 1000, 500, 50.0, 1.0)
    assert math.isclose(tall, 80.0 * 50.0 / 72.0)


def test_scene_bound_items_skip_geometry_less_and_hidden_objects():
    def obj(type_, visible=True, box=True):
        return SimpleNamespace(
            type=type_,
            visible_get=lambda: visible,
            bound_box=_box(1, 1, 1) if box else None,
            matrix_world=_Matrix(),
        )

    scene = SimpleNamespace(
        objects=[obj('MESH'), obj('CAMERA'), obj('LIGHT'), obj('EMPTY'), obj('MESH', visible=False),
                 obj('CURVE'), obj('MESH', box=False)]
    )
    assert len(scene_bounds.scene_bound_items(scene)) == 2
    assert scene_bounds.HIDDEN_TYPES == {'CAMERA', 'LIGHT', 'SPEAKER', 'EMPTY', 'LIGHT_PROBE'}


def test_python_and_cpp_extents_rules_mirror_each_other():
    extents = (VIEW3D / "view3d_director_minimap_extents.cc").read_text(encoding="utf-8")
    assert "MINIMAP_PAD_FRACTION = 0.1f" in extents and scene_bounds.PAD_FRACTION == 0.1
    assert "MINIMAP_PAD_MIN = 2.0f" in extents and scene_bounds.PAD_MIN == 2.0
    assert "MINIMAP_EMPTY_HALF = 10.0f" in extents and scene_bounds.EMPTY_HALF == 10.0
    minimap_header = (VIEW3D / "view3d_director_minimap.hh").read_text(encoding="utf-8")
    for ob_type in ("OB_CAMERA", "OB_LAMP", "OB_SPEAKER", "OB_EMPTY", "OB_LIGHTPROBE"):
        assert ob_type in minimap_header
    # Documented divergence: the C++ map adds the marker's extent to the
    # camera union (the marker must stay on the card); the aerial view does
    # not (the stage fraction already leaves room), so `padded_xy` takes no
    # margin and `aerial_view` never reads one.
    assert "margin_world" in extents
    assert "margin" not in _block_py(
        (DIRECTOR / "core/scene_bounds.py").read_text(encoding="utf-8"), "def padded_xy("
    )


# -------------------------------------------------------------------------
# core/viewport.py + the operators


def test_navigation_mode_has_the_aerial_item():
    assert '("AERIAL", "Aerial",' in PROPERTIES
    assert re.search(r'"AERIAL", "Aerial",\s*"Look down on the scene[^"]*", 3\)', PROPERTIES)


def test_enter_camera_view_ends_aerial_like_explore():
    assert "state.navigation_mode in {'EXPLORE', 'AERIAL'}" in VIEWPORT
    state = SimpleNamespace(navigation_mode='AERIAL')
    space = SimpleNamespace(region_3d=SimpleNamespace(view_perspective='ORTHO'), lock_camera=False)
    area = SimpleNamespace(tag_redraw=lambda: None)
    scene = SimpleNamespace(mixar_director=state, camera=None)
    context = SimpleNamespace(scene=scene)
    original = viewport.find_view3d_context
    viewport.find_view3d_context = lambda _context: (None, area, None, space)
    try:
        viewport.enter_camera_view(context, "camera", remember=False)
    finally:
        viewport.find_view3d_context = original
    assert state.navigation_mode == 'NAVIGATE'
    assert space.region_3d.view_perspective == 'CAMERA'
    assert space.lock_camera is True


def test_enter_aerial_view_sets_an_ortho_top_view_over_the_scene(monkeypatch):
    class _Quat:
        def __init__(self, values):
            self.values = tuple(values)

    mathutils = SimpleNamespace(Quaternion=_Quat)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils)
    monkeypatch.setattr(viewport, "remember_view", lambda _c, _s: None)
    monkeypatch.setattr(
        scene_bounds, "scene_bound_items", lambda _scene: [(_Matrix(), _box(10, 10, 2))]
    )
    state = SimpleNamespace(navigation_mode='NAVIGATE', shots=[], active_shot_index=0)
    region_3d = SimpleNamespace(view_perspective='CAMERA', view_rotation=None,
                                view_location=None, view_distance=0.0)
    space = SimpleNamespace(region_3d=region_3d, lock_camera=True, lens=50.0)
    region = SimpleNamespace(width=1000, height=500)
    area = SimpleNamespace(tag_redraw=lambda: None)
    scene = SimpleNamespace(mixar_director=state, objects=[])
    monkeypatch.setattr(viewport, "find_view3d_context", lambda _c: (None, area, region, space))
    viewport.enter_aerial_view(SimpleNamespace(scene=scene), scene)
    assert state.navigation_mode == 'AERIAL'
    assert region_3d.view_perspective == 'ORTHO'
    assert region_3d.view_rotation.values == (1.0, 0.0, 0.0, 0.0)
    assert region_3d.view_location == (0.0, 0.0, 0.0)
    assert region_3d.view_distance > 0.0
    assert space.lock_camera is False
    assert "remember_view(context, scene)" in _block_py(VIEWPORT, "def enter_aerial_view(")


def _block_py(source: str, start: str) -> str:
    """A top-level def/class body: up to the next blank-line-separated item."""
    body = source[source.index(start):]
    end = body.find("\n\n\n", 1)
    return body if end < 0 else body[:end]


def test_aerial_operator_is_a_toggle_that_returns_through_enter_camera_view():
    assert 'bl_idname = "mixar.director_aerial"' in AERIAL_OPS
    assert "bl_options = {'REGISTER'}" in AERIAL_OPS
    execute = _block_py(AERIAL_OPS, "class MIXAR_OT_director_aerial(Operator)")
    assert "if state.navigation_mode != 'AERIAL':" in execute
    assert "enter_aerial_view(context, context.scene)" in execute
    assert "_leave_aerial(context)" in execute
    leave = _block_py(AERIAL_OPS, "def _leave_aerial(context)")
    assert "enter_camera_view(context, camera, remember=False)" in leave
    assert "enter_free_view(context)" in leave
    assert "state.navigation_mode = 'NAVIGATE'" in leave
    assert "Aerial view — click to place the camera, O to return" in AERIAL_OPS
    assert "classes = (MIXAR_OT_director_aerial, MIXAR_OT_director_aerial_exit)" in AERIAL_OPS


def test_aerial_exit_polls_only_inside_the_mode():
    exit_op = _block_py(AERIAL_OPS, "class MIXAR_OT_director_aerial_exit(Operator)")
    assert 'bl_idname = "mixar.director_aerial_exit"' in exit_op
    assert "state.navigation_mode == 'AERIAL'" in exit_op
    assert "enter_aerial_view" not in exit_op


def test_toggle_execute_paths_under_the_mock(monkeypatch):
    import importlib

    import bpy
    from mixar.modules.director.ui.operators import aerial_ops

    # `bpy.types.Operator` is a mock whose shape depends on which suite ran
    # first; reload the module over a plain base so the class is a real one.
    # `from bpy.types import Operator` resolves through `sys.modules` when a
    # `bpy.types` entry exists, so patch that reference too.
    base = type("Operator", (), {})
    monkeypatch.setattr(bpy.types, "Operator", base)
    if "bpy.types" in sys.modules:
        monkeypatch.setattr(sys.modules["bpy.types"], "Operator", base)
    aerial_ops = importlib.reload(aerial_ops)
    calls = []
    monkeypatch.setattr(aerial_ops, "enter_aerial_view", lambda c, s: calls.append("aerial"))
    monkeypatch.setattr(
        aerial_ops, "enter_camera_view", lambda c, cam, remember: calls.append(("camera", remember))
    )
    monkeypatch.setattr(aerial_ops, "enter_free_view", lambda c: calls.append("free"))
    camera = object()
    monkeypatch.setattr(aerial_ops, "active_shot", lambda _s: SimpleNamespace(camera=camera))
    state = SimpleNamespace(is_directing=True, navigation_mode='NAVIGATE')
    context = SimpleNamespace(scene=SimpleNamespace(mixar_director=state))
    execute = aerial_ops.MIXAR_OT_director_aerial.execute
    op = SimpleNamespace(report=MagicMock())
    assert execute(op, context) == {'FINISHED'}
    state.navigation_mode = 'AERIAL'
    assert execute(op, context) == {'FINISHED'}
    assert calls == ["aerial", ("camera", False)]
    # No camera: back to a plain perspective and NAVIGATE.
    monkeypatch.setattr(aerial_ops, "active_shot", lambda _s: None)
    calls.clear()
    assert execute(op, context) == {'FINISHED'}
    assert calls == ["free"] and state.navigation_mode == 'NAVIGATE'
    exit_poll = aerial_ops.MIXAR_OT_director_aerial_exit.poll
    assert exit_poll(context) is False
    state.navigation_mode = 'AERIAL'
    assert exit_poll(context) is True


# -------------------------------------------------------------------------
# keymap


def test_o_toggles_aerial_and_esc_leaves_it():
    assert '"director_aerial",' in KEYMAP and '"director_aerial_exit",' in KEYMAP
    o_item = KEYMAP[KEYMAP.index('"mixar.director_aerial",'):]
    o_item = o_item[: o_item.index("addon_keymaps.append")]
    assert "type='O'" in o_item and "head=True" in o_item
    assert "for keymap_name, (space_type, region_type) in _NAVIGATE_KEYMAPS:" in KEYMAP[
        : KEYMAP.index('"mixar.director_aerial",')
    ]
    esc_item = KEYMAP[KEYMAP.index('"mixar.director_aerial_exit",'):]
    esc_item = esc_item[: esc_item.index("addon_keymaps.append")]
    assert "type='ESC'" in esc_item and "value='PRESS'" in esc_item
    before = KEYMAP[: KEYMAP.index('"mixar.director_aerial_exit",')]
    assert 'name="3D View"' in before[before.rfind("keyconfig.keymaps.new("):]
    # The walk lost O and nothing else: it is still registered elsewhere.
    assert '"mixar.director_navigate",\n            type=' not in KEYMAP
    assert "director_navigate" in KEYMAP.split("_OPERATOR_NAMES")[1]
    camera_ops = (DIRECTOR / "ui/operators/camera_ops.py").read_text(encoding="utf-8")
    assert 'bl_idname = "mixar.director_navigate"' in camera_ops


# -------------------------------------------------------------------------
# C++


def test_state_mirrors_aerial_and_the_poll_opens_to_the_stage():
    assert "bool aerial_mode = false;" in HEADER
    assert "r_state->aerial_mode = navigation_mode == 3;" in STATE
    assert "int view3d_director_navigation_mode(Scene *scene)" in STATE
    assert "constexpr int NAVIGATION_MODE_AERIAL = 3;" in PLACE
    poll = _block(PLACE, "bool place_camera_poll(bContext *C)")
    assert "view3d_director_minimap_contains(region, x, y)" in poll
    assert "aerial_mode(C) && stage_contains(C, region, x, y)" in poll
    stage = _block(PLACE, "bool stage_contains(")
    assert "cinema_stage_rect(C, region, &stage)" in stage
    # World XY off the ORTHO top view: the pixel projected on the plane z = camera.z.
    mapping = _block(PLACE, "bool world_xy_at(")
    assert "plane_from_point_normal_v3(plane, loc, normal)" in mapping
    assert "ED_view3d_win_to_3d_on_plane(region, plane, mval_f, false, out)" in mapping
    assert "view3d_director_minimap_world_from_region_px(region, mval[0], mval[1], r_xy)" in mapping


def test_the_hint_is_aerial_view_and_lights_with_the_mode():
    assert '{0.0f, {"O"}, 1, "Aerial view", false}' in TOP
    assert "const bool lit = index == 0 && state.aerial_mode;" in TOP
    assert "lit ? hint_lit : hint_col" in TOP
    assert "const float hint_lit[4] = CINEMA_COL_VALUE;" in TOP
    assert '"Navigate"' not in TOP


def test_the_gate_fit_leaves_the_ortho_view_alone():
    fit = _block(GATE, "void cinema_fit_camera_gate(")
    assert "rv3d->persp != RV3D_CAMOB" in fit.split("rv3d->camzoom")[0]
    rect = _block(GATE, "bool cinema_camera_gate_rect(")
    assert "rv3d->persp != RV3D_CAMOB" in rect
