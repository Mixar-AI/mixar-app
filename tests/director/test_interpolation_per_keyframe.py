# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Interpolation is per keyframe, with the shot as the default.

A keyframe's interpolation governs the segment FROM it TO the next one, which
is exactly what "the easing between these two keyframes" means. It used to be
a single value on the shot, so a take could only ease one way from end to end.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.director.constants import (
    BEAT_INTERPOLATION_DEFAULT,
    BEAT_INTERPOLATION_ITEMS,
    INTERPOLATION_ITEMS,
)
from mixar.modules.director.core import interpolation as interp

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
PROPERTIES = (DIRECTOR / "ui/properties/director_properties.py").read_text(encoding="utf-8")
TRACK_OPS = (DIRECTOR / "ui/operators/track_ops.py").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
POPUP = (VIEW3D / "view3d_director_popup_interp.cc").read_text(encoding="utf-8")
KEYS = (VIEW3D / "view3d_director_timeline_keys.cc").read_text(encoding="utf-8")


def _beat(frame, value=BEAT_INTERPOLATION_DEFAULT):
    return SimpleNamespace(frame=frame, interpolation=value)


def _shot(*beats, default="BEZIER"):
    return SimpleNamespace(interpolation=default, beats=list(beats), camera=object())


# -------------------------------------------------------------------------
# Resolution.


def test_a_beat_with_no_opinion_takes_the_shots():
    shot = _shot(_beat(1))
    assert interp.beat_interpolation(shot, shot.beats[0]) == "BEZIER"


def test_a_beat_that_chose_keeps_its_own():
    shot = _shot(_beat(1, "CONSTANT"))
    assert interp.beat_interpolation(shot, shot.beats[0]) == "CONSTANT"


def test_shot_is_never_written_to_a_keyframe():
    """`SHOT` is the beat saying it has no opinion, not a Blender easing."""
    assert BEAT_INTERPOLATION_DEFAULT not in {item[0] for item in INTERPOLATION_ITEMS}
    shot = _shot(_beat(1))
    assert BEAT_INTERPOLATION_DEFAULT not in interp.interpolation_by_frame(shot).values()


def test_each_span_gets_its_own_answer():
    shot = _shot(_beat(1, "CONSTANT"), _beat(25), _beat(49, "LINEAR"))
    assert interp.interpolation_by_frame(shot) == {
        1: "CONSTANT",
        25: "BEZIER",
        49: "LINEAR",
    }


def test_the_capturing_frame_takes_the_shot_default():
    """It is not on `shot.beats` yet, and a beat rests on the shot anyway."""
    shot = _shot(_beat(1, "LINEAR"))
    assert interp.interpolation_by_frame(shot, frame=25) == {1: "LINEAR", 25: "BEZIER"}


def test_a_beat_already_at_that_frame_wins_over_the_capture_default():
    shot = _shot(_beat(25, "CONSTANT"))
    assert interp.interpolation_by_frame(shot, frame=25) == {25: "CONSTANT"}


# -------------------------------------------------------------------------
# Writing the points.


class _Point:
    def __init__(self, frame, value="BEZIER"):
        self.co = [float(frame), 0.0]
        self.interpolation = value


class _Curve:
    def __init__(self, data_path, points):
        self.data_path = data_path
        self.keyframe_points = points
        self.updated = 0

    def update(self):
        self.updated += 1


def _camera(points):
    curve = _Curve("location", points)
    data = SimpleNamespace(animation_data=None)
    camera = SimpleNamespace(data=data)
    return camera, curve


@pytest.fixture
def curves(monkeypatch):
    holder = {}

    def _assigned(owner):
        return holder.get(id(owner), ())

    monkeypatch.setattr(interp, "assigned_fcurves", _assigned)
    return holder


def test_the_points_take_their_own_beats_type(curves):
    points = [_Point(1), _Point(25), _Point(49)]
    camera, curve = _camera(points)
    curves[id(camera)] = (curve,)
    shot = _shot(_beat(1, "CONSTANT"), _beat(25), _beat(49, "LINEAR"))
    shot.camera = camera
    assert interp.apply_interpolation(shot) == 2
    assert [point.interpolation for point in points] == ["CONSTANT", "BEZIER", "LINEAR"]
    assert curve.updated == 1


def test_a_key_the_shot_does_not_own_is_left_alone(curves):
    """A hand-keyed point between two beats keeps whatever its author gave it."""
    stray = _Point(12, "ELASTIC")
    points = [_Point(1), stray, _Point(25)]
    camera, curve = _camera(points)
    curves[id(camera)] = (curve,)
    shot = _shot(_beat(1, "CONSTANT"), _beat(25, "CONSTANT"))
    shot.camera = camera
    interp.apply_interpolation(shot)
    assert stray.interpolation == "ELASTIC"


# -------------------------------------------------------------------------
# The property and the operator.


def test_the_beat_carries_the_enum_and_rests_on_the_shot():
    beat = PROPERTIES.split("class MixarDirectorBeat", 1)[1].split("class ", 1)[0]
    assert "interpolation: EnumProperty(" in beat
    assert "items=BEAT_INTERPOLATION_ITEMS" in beat
    assert f'default=BEAT_INTERPOLATION_DEFAULT' in beat
    assert "update=_on_beat_interpolation_update" in beat


def test_the_beat_enum_is_the_shots_plus_the_inherit_row():
    assert BEAT_INTERPOLATION_ITEMS[0][0] == BEAT_INTERPOLATION_DEFAULT
    assert BEAT_INTERPOLATION_ITEMS[1:] == INTERPOLATION_ITEMS
    # Distinct enum numbers, or Blender resolves two rows to one value.
    numbers = [item[3] for item in BEAT_INTERPOLATION_ITEMS]
    assert len(set(numbers)) == len(numbers)


def test_the_operator_writes_the_selection_when_there_is_one():
    body = TRACK_OPS.split("class MIXAR_OT_director_set_interpolation", 1)[1]
    body = body.split("\nclass ", 1)[0]
    assert "indices: StringProperty(" in body
    assert "shot.beats[index].interpolation = self.interpolation" in body
    assert "shot.interpolation = self.interpolation" in body


def test_handing_back_to_the_shot_needs_a_selection():
    """There is nothing above a shot to inherit from."""
    body = TRACK_OPS.split("class MIXAR_OT_director_set_interpolation", 1)[1]
    body = body.split("\nclass ", 1)[0]
    guard = body.split("if not selected:", 1)[1].split("for index in selected:", 1)[0]
    assert "self.interpolation == BEAT_INTERPOLATION_DEFAULT" in guard
    assert "'CANCELLED'" in guard


# -------------------------------------------------------------------------
# The surface.


def test_the_selection_is_the_beats_on_selected_keys():
    """The chip and the popup act on beats, and a beat is selected when its
    key is. The selection is Blender's own, read from the camera's keys on
    every call — so one made in the Timeline counts too, and nothing in a
    region runtime can go stale."""
    body = KEYS.split("bool view3d_director_timeline_selection(", 1)[1].split("\n}\n", 1)[0]
    assert "view3d_director_state_read(CTX_data_scene(C), &state)" in body
    assert "BEZT_ISSEL_ANY(&fcu.bezt[i])" in body
    assert "r_selected->append(beat.index);" in body
    assert "regiondata" not in body


def test_the_chip_reads_the_selection_and_says_mixed():
    chip = DOCK.split("void interpolation_chip(", 1)[1].split("\n}\n", 1)[0]
    assert "view3d_director_timeline_selection(C, &selected)" in chip
    assert '"Mixed"' in chip
    assert "RNA_property_collection_lookup_int(&shot_ptr, beats, index, &beat_ptr)" in chip


def test_the_popup_lists_the_property_it_writes():
    """With a selection it is the beat's enum — which carries Shot Default —
    and the rows pass the indices through to the operator."""
    assert "view3d_director_timeline_selection(C, &selected)" in POPUP
    assert "PointerRNA list_ptr = data.shot_ptr;" in POPUP
    assert 'RNA_property_enum_items(C, &list_ptr, prop,' in POPUP
    assert 'RNA_string_set(op_ptr, "indices", indices.c_str());' in POPUP
