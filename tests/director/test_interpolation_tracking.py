# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cinema Mode top-strip controls: keyframe interpolation and object tracking."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from mixar.modules.director import constants
from mixar.modules.director.core import interpolation, tracking

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"

# Blender's KeyframePoint.interpolation identifiers, in Blender's order.
BLENDER_INTERPOLATION = (
    "CONSTANT", "LINEAR", "BEZIER",
    "SINE", "QUAD", "CUBIC", "QUART", "QUINT", "EXPO", "CIRC",
    "BACK", "BOUNCE", "ELASTIC",
)


def _point(value):
    return SimpleNamespace(interpolation=value)


def _fcurve(*values):
    return SimpleNamespace(keyframe_points=[_point(v) for v in values], update=MagicMock())


def _shot_with_curves(object_curves, data_curves, interpolation_value="LINEAR", monkeypatch=None):
    camera = SimpleNamespace(data=SimpleNamespace())
    curves = {id(camera): object_curves, id(camera.data): data_curves}
    monkeypatch.setattr(
        interpolation, "assigned_fcurves", lambda owner: tuple(curves.get(id(owner), ()))
    )
    return SimpleNamespace(camera=camera, interpolation=interpolation_value)


# -------------------------------------------------------------------------
# Interpolation


def test_the_dropdown_offers_every_blender_interpolation_type_in_order():
    identifiers = tuple(item[0] for item in constants.INTERPOLATION_ITEMS)
    assert identifiers == BLENDER_INTERPOLATION
    numbers = [item[3] for item in constants.INTERPOLATION_ITEMS]
    assert numbers == list(range(len(numbers)))


def test_apply_interpolation_rewrites_every_camera_key_and_refreshes_curves(monkeypatch):
    location = _fcurve("BEZIER", "BEZIER", "LINEAR")
    rotation = _fcurve("BEZIER")
    lens = _fcurve("BEZIER", "BEZIER")
    shot = _shot_with_curves([location, rotation], [lens], "LINEAR", monkeypatch)

    changed = interpolation.apply_interpolation(shot)

    assert changed == 5
    for curve in (location, rotation, lens):
        assert {p.interpolation for p in curve.keyframe_points} == {"LINEAR"}
        curve.update.assert_called_once()


def test_apply_interpolation_is_a_no_op_without_a_camera_or_keys(monkeypatch):
    assert interpolation.apply_interpolation(SimpleNamespace(camera=None, interpolation="LINEAR")) == 0
    shot = _shot_with_curves([], [], "LINEAR", monkeypatch)
    assert interpolation.apply_interpolation(shot) == 0


def test_every_capture_reapplies_the_shots_interpolation():
    capture = (DIRECTOR / "core/capture.py").read_text(encoding="utf-8")
    key = capture.index("_key_camera(camera, target_frame)")
    assert "apply_interpolation(shot)" in capture[key:]


def test_the_shot_property_applies_on_change_and_the_operator_writes_the_property():
    props = (DIRECTOR / "ui/properties/director_properties.py").read_text(encoding="utf-8")
    assert "items=INTERPOLATION_ITEMS" in props
    assert "update=_on_interpolation_update" in props
    ops = (DIRECTOR / "ui/operators/track_ops.py").read_text(encoding="utf-8")
    assert 'bl_idname = "mixar.director_set_interpolation"' in ops
    assert "shot.interpolation = self.interpolation" in ops


def test_the_popup_lists_the_property_own_items():
    popup = (VIEW3D / "view3d_director_popup_interp.cc").read_text(encoding="utf-8")
    # Rows come from RNA, never a hardcoded list that could drift from Python.
    assert 'RNA_struct_find_property(&data.shot_ptr, "interpolation")' in popup
    assert "RNA_property_enum_items(" in popup
    assert '"MIXAR_OT_director_set_interpolation"' in popup
    assert "MEM_delete_void" in popup


# -------------------------------------------------------------------------
# Tracking


class _Constraints(list):
    def get(self, name):
        return next((c for c in self if c.name == name), None)

    def new(self, kind):
        constraint = SimpleNamespace(type=kind, name="", target=None, mute=True)
        self.append(constraint)
        return constraint


def _camera():
    return SimpleNamespace(type='CAMERA', constraints=_Constraints())


def test_refresh_tracking_adds_a_track_to_constraint_pointing_at_the_target():
    camera = _camera()
    target = SimpleNamespace(type='MESH', name="Cube")
    shot = SimpleNamespace(camera=camera, track_target=target)

    assert tracking.refresh_tracking(shot) is True
    constraint = camera.constraints.get(constants.TRACK_CONSTRAINT_NAME)
    assert constraint is not None and constraint.type == 'TRACK_TO'
    assert constraint.target is target
    assert constraint.track_axis == 'TRACK_NEGATIVE_Z' and constraint.up_axis == 'UP_Y'
    assert constraint.mute is False

    # Re-targeting reuses the same constraint rather than stacking another.
    other = SimpleNamespace(type='MESH', name="Suzanne")
    shot.track_target = other
    tracking.refresh_tracking(shot)
    assert len(camera.constraints) == 1
    assert camera.constraints[0].target is other


def test_clearing_the_target_removes_only_directors_constraint():
    camera = _camera()
    foreign = camera.constraints.new('TRACK_TO')
    foreign.name = "User's own"
    shot = SimpleNamespace(camera=camera, track_target=SimpleNamespace(type='MESH', name="Cube"))
    tracking.refresh_tracking(shot)
    assert len(camera.constraints) == 2

    shot.track_target = None
    assert tracking.refresh_tracking(shot) is False
    assert [c.name for c in camera.constraints] == ["User's own"]


def test_the_camera_can_never_track_itself():
    camera = _camera()
    shot = SimpleNamespace(camera=camera, track_target=camera)
    assert tracking.refresh_tracking(shot) is False
    assert len(camera.constraints) == 0


def test_the_eyedropper_ray_casts_instead_of_selecting():
    ops = (DIRECTOR / "ui/operators/track_ops.py").read_text(encoding="utf-8")
    core = (DIRECTOR / "core/tracking.py").read_text(encoding="utf-8")
    assert "scene.ray_cast(" in core
    assert "view3d.select" not in ops and "view3d.select" not in core
    assert "cursor_modal_set('EYEDROPPER')" in ops
    # A miss keeps the eyedropper alive; RMB/Esc cancel; picking restores the cursor.
    assert "return {'RUNNING_MODAL'}" in ops[ops.index("No object under the cursor"):]
    assert "{'RIGHTMOUSE', 'ESC'}" in ops
    assert ops.count("cursor_modal_restore()") >= 3


def test_the_strip_chip_passes_clear_when_a_target_is_live():
    top = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")
    assert '"MIXAR_OT_director_pick_track_target"' in top
    assert 'RNA_boolean_set(ui::button_operator_ptr_ensure(but), "clear", tracking)' in top
    assert 'cinema_qa_record(region, chip, "director_track"' in top
    assert 'cinema_qa_record(region, row, "director_interpolation"' in top
    # The hints yield to the controls, never the other way round.
    assert "std::min(controls_left, float(region->winx))" in top
