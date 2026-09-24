# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicating keyframes.

A director reaches for this constantly — return to a pose already framed, or
repeat a move a beat later — and re-flying the camera back to a pose by hand
never lands on it exactly. There was no way to do it at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.director.core import duplicate

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
OPS = (DIRECTOR / "ui/operators/selection_ops.py").read_text(encoding="utf-8")
STRIP = (DIRECTOR / "ui/operators/strip_ops.py").read_text(encoding="utf-8")
SELECT = (VIEW3D / "view3d_director_timeline_select.cc").read_text(encoding="utf-8")


# -------------------------------------------------------------------------
# Where the copies land.


def test_the_group_keeps_its_spacing_after_the_last_keyframe():
    assert duplicate.duplicate_plan([1, 25, 49], last_frame=49, stride=12) == [
        (1, 61),
        (25, 85),
        (49, 109),
    ]


def test_a_single_keyframe_lands_one_stride_on():
    assert duplicate.duplicate_plan([25], last_frame=49, stride=12) == [(25, 61)]


def test_duplicates_never_collide_with_an_existing_key():
    """Two Director keys on one frame would be unrecoverable: beats and
    native keys are matched BY FRAME VALUE and nothing else."""
    plan = duplicate.duplicate_plan([1, 25], last_frame=25, stride=1)
    assert all(target > 25 for _source, target in plan)


def test_the_order_is_chronological_and_duplicates_are_dropped():
    assert duplicate.duplicate_plan([49, 1, 1, 25], last_frame=49, stride=10) == [
        (1, 59),
        (25, 83),
        (49, 107),
    ]


def test_nothing_selected_plans_nothing():
    assert duplicate.duplicate_plan([], last_frame=10, stride=4) == []


def test_a_zero_stride_still_moves_the_copies_on():
    """A stride of zero would put the first copy ON the last keyframe."""
    assert duplicate.duplicate_plan([5], last_frame=5, stride=0) == [(5, 6)]


# -------------------------------------------------------------------------
# Copying the camera keys.


class _Handle(list):
    pass


class _Point:
    def __init__(self, frame, value, interpolation="BEZIER"):
        self.co = [float(frame), float(value)]
        self.handle_left = _Handle([float(frame) - 2.0, float(value)])
        self.handle_right = _Handle([float(frame) + 2.0, float(value)])
        self.handle_left_type = 'AUTO_CLAMPED'
        self.handle_right_type = 'AUTO_CLAMPED'
        self.easing = 'AUTO'
        self.interpolation = interpolation


class _Points(list):
    def insert(self, frame, value, options=None):
        point = _Point(frame, value)
        self.append(point)
        self.inserted_options = options
        return point


class _Curve:
    def __init__(self, data_path, points):
        self.data_path = data_path
        self.keyframe_points = _Points(points)
        self.updated = 0

    def update(self):
        self.updated += 1


@pytest.fixture
def curves(monkeypatch):
    holder = {}
    monkeypatch.setattr(
        duplicate, "assigned_fcurves", lambda owner: holder.get(id(owner), ())
    )
    return holder


def _camera(curves, object_curves, data_curves=()):
    data = SimpleNamespace()
    camera = SimpleNamespace(type='CAMERA', data=data)
    curves[id(camera)] = tuple(object_curves)
    curves[id(data)] = tuple(data_curves)
    return camera


def test_every_channel_of_the_keyframe_is_copied(curves):
    location = _Curve("location", [_Point(10, 3.0)])
    lens = _Curve("lens", [_Point(10, 50.0)])
    camera = _camera(curves, [location], [lens])
    assert duplicate.copy_camera_keys(camera, [(10, 30)]) == 2
    assert [point.co[0] for point in location.keyframe_points] == [10.0, 30.0]
    assert location.keyframe_points[-1].co[1] == 3.0
    assert lens.keyframe_points[-1].co[1] == 50.0


def test_a_channel_the_shot_does_not_own_is_not_copied(curves):
    """`shift_x` or a hand-keyed DOF rack on the same camera is the user's."""
    stray = _Curve("shift_x", [_Point(10, 1.0)])
    camera = _camera(curves, [stray])
    assert duplicate.copy_camera_keys(camera, [(10, 30)]) == 0
    assert len(stray.keyframe_points) == 1


def test_the_handles_travel_with_the_copy(curves):
    """Copying the values without them silently flattens a Bezier the
    director spent time on."""
    location = _Curve("location", [_Point(10, 3.0)])
    camera = _camera(curves, [location])
    duplicate.copy_camera_keys(camera, [(10, 30)])
    copy = location.keyframe_points[-1]
    assert copy.handle_left[0] == pytest.approx(28.0)
    assert copy.handle_right[0] == pytest.approx(32.0)
    assert copy.handle_left[1] == pytest.approx(3.0)


def test_the_easing_travels_with_the_copy(curves):
    location = _Curve("location", [_Point(10, 3.0, interpolation="CONSTANT")])
    camera = _camera(curves, [location])
    duplicate.copy_camera_keys(camera, [(10, 30)])
    assert location.keyframe_points[-1].interpolation == "CONSTANT"


def test_each_curve_is_resorted_once(curves):
    """FAST insertion skips the per-insert re-sort, so the update is owed."""
    location = _Curve("location", [_Point(10, 3.0), _Point(20, 4.0)])
    camera = _camera(curves, [location])
    duplicate.copy_camera_keys(camera, [(10, 30), (20, 40)])
    assert location.keyframe_points.inserted_options == {'FAST'}
    assert location.updated == 1


def test_an_untouched_curve_is_not_updated(curves):
    location = _Curve("location", [_Point(10, 3.0)])
    camera = _camera(curves, [location])
    duplicate.copy_camera_keys(camera, [(99, 130)])
    assert location.updated == 0


# -------------------------------------------------------------------------
# The beats.


class _Beats(list):
    def add(self):
        beat = SimpleNamespace(
            beat_id="", frame=0, time_base=0.0, image=None, interpolation="SHOT"
        )
        self.append(beat)
        return beat


def _shot(frames, camera):
    beats = _Beats()
    for index, frame in enumerate(frames):
        beat = beats.add()
        beat.beat_id = f"src{index}"
        beat.frame = frame
        beat.time_base = float(frame)
        beat.image = SimpleNamespace(name=f"still{index}")
        beat.interpolation = "LINEAR" if index == 0 else "SHOT"
    return SimpleNamespace(
        state='DRAFT',
        camera=camera,
        beats=beats,
        interpolation="BEZIER",
        speed=0.0,
        active_beat_index=0,
        manifest_json="",
    )


def _scene():
    return SimpleNamespace(
        frame_end=100,
        frame_current=1,
        render=SimpleNamespace(fps=24, fps_base=1.0),
    )


@pytest.fixture
def quiet(monkeypatch, curves):
    monkeypatch.setattr(duplicate, "refresh_manifest", lambda *_a, **_k: None)
    monkeypatch.setattr(duplicate, "release_preview_range", lambda *_a, **_k: None)
    monkeypatch.setattr(duplicate, "repair_rotation_continuity", lambda _c: 0)
    return curves


def test_a_copy_is_its_own_keyframe(quiet):
    location = _Curve("location", [_Point(1, 0.0), _Point(25, 1.0)])
    camera = _camera(quiet, [location])
    shot = _shot([1, 25], camera)
    created = duplicate.duplicate_beats(_scene(), shot, [0], beat_seconds=1.0)
    assert len(created) == 1
    assert created[0].beat_id and created[0].beat_id != "src0"
    assert created[0].frame == 25 + 24


def test_a_copy_carries_the_pose_it_looks_like(quiet):
    """The still and the easing are what the pose looks like; a copy of the
    pose is the same pose."""
    location = _Curve("location", [_Point(1, 0.0)])
    camera = _camera(quiet, [location])
    shot = _shot([1], camera)
    created = duplicate.duplicate_beats(_scene(), shot, [0], beat_seconds=1.0)
    assert created[0].image is shot.beats[0].image
    assert created[0].interpolation == "LINEAR"


def test_the_time_base_is_recorded(quiet):
    """Every writer of `beat.frame` other than the speed update records it."""
    location = _Curve("location", [_Point(1, 0.0)])
    camera = _camera(quiet, [location])
    shot = _shot([1], camera)
    created = duplicate.duplicate_beats(_scene(), shot, [0], beat_seconds=1.0)
    assert created[0].time_base == pytest.approx(float(created[0].frame))


def test_the_scene_end_grows_to_hold_the_copies(quiet):
    location = _Curve("location", [_Point(1, 0.0)])
    camera = _camera(quiet, [location])
    shot = _shot([1], camera)
    scene = _scene()
    scene.frame_end = 5
    duplicate.duplicate_beats(scene, shot, [0], beat_seconds=1.0)
    assert scene.frame_end == shot.beats[-1].frame


def test_a_locked_take_refuses(quiet):
    shot = _shot([1], _camera(quiet, []))
    shot.state = 'LOCKED'
    with pytest.raises(ValueError):
        duplicate.duplicate_beats(_scene(), shot, [0], beat_seconds=1.0)


def test_a_shot_with_no_camera_refuses(quiet):
    shot = _shot([1], None)
    with pytest.raises(ValueError):
        duplicate.duplicate_beats(_scene(), shot, [0], beat_seconds=1.0)


def test_an_index_that_names_nothing_duplicates_nothing(quiet):
    location = _Curve("location", [_Point(1, 0.0)])
    camera = _camera(quiet, [location])
    shot = _shot([1], camera)
    assert duplicate.duplicate_beats(_scene(), shot, [7], beat_seconds=1.0) == []
    assert len(shot.beats) == 1


# -------------------------------------------------------------------------
# Reaching it.


def test_the_operator_falls_back_to_the_keyframe_in_hand():
    body = OPS.split("class MIXAR_OT_director_duplicate_beats", 1)[1]
    body = body.split("\nclass ", 1)[0]
    assert 'bl_idname = "mixar.director_duplicate_beats"' in body
    assert "active = int(getattr(shot, \"active_beat_index\", -1))" in body
    assert "'UNDO'" in body


def _shift_d_block() -> str:
    return SELECT.split("bool duplicate_selected(", 1)[1].split("\n}\n", 1)[0]


def test_shift_d_is_the_gesture():
    """The one the Dope Sheet and the viewport both train."""
    assert "EVT_DKEY && event->val == KM_PRESS && (event->modifier & KM_SHIFT)" in SELECT
    gesture = SELECT.split("EVT_DKEY", 1)[1][:300]
    assert "!state.locked" in gesture
    assert "duplicate_selected(C, runtime, event)" in gesture
    block = _shift_d_block()
    assert '"mixar.director_duplicate_beats"' in block
    # The beats duplicated are the ones on the selected KEYS.
    assert "view3d_director_timeline_selection(C, &beats)" in block


def test_the_copies_go_straight_into_a_drag():
    """A duplicate that lands a beat further on and stops there is one the
    director then has to go and find; what they wanted was this pose, HERE."""
    block = _shift_d_block()
    assert '"mixar.director_drag_keys"' in block
    assert block.index('"mixar.director_duplicate_beats"') < block.index(
        '"mixar.director_drag_keys"'
    )
    # The drag moves the selection as it stands — no key to click — at the
    # frames-per-pixel the view is at, anchored on the event.
    assert 'RNA_boolean_set(&drag_ptr, "use_frame", false);' in block
    assert "runtime->view_span_frames / width" in block
    assert "&drag_ptr, event)" in block


def test_the_copies_become_the_selection():
    """The operator selects the copies' keys, so the drag moves them and
    nothing else — and the Timeline shows them selected too."""
    body = OPS.split("class MIXAR_OT_director_duplicate_beats", 1)[1]
    assert "select_columns(shot.camera, [int(beat.frame) for beat in created], 'SET')" in body
    assert body.index("select_columns(") > body.index("duplicate_beats(scene, shot, selected")


def test_the_strip_menu_offers_it_before_delete():
    """A destructive row should never be the one the cursor lands on."""
    assert '"mixar.director_duplicate_beats"' in STRIP
    assert STRIP.index('"mixar.director_duplicate_beats"') < STRIP.index(
        '"mixar.director_remove_beat"'
    )
    assert "copy.indices = str(beat_index)" in STRIP
