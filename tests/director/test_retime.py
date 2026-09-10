# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Cinema Mode Speed slider retimes the active shot.

``shot.speed`` scales every interval between the shot's keyframes around
the first one (``factor = 2 ** -speed``); the native camera keys move with
the beats, and ``beat.time_base`` keeps a slider drag drift-free.
"""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
DIRECTOR = SCRIPTS / "mixar/modules/director"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director import constants  # noqa: E402
from mixar.modules.director.core import retime, timeline  # noqa: E402


def _read(relative: str) -> str:
    return (DIRECTOR / relative).read_text(encoding="utf-8")


class _Point:
    def __init__(self, frame, value=0.0):
        self.co = [float(frame), float(value)]
        self.handle_left = [float(frame) - 0.25, float(value) - 1.0]
        self.handle_right = [float(frame) + 0.5, float(value) + 1.0]


class _Curve:
    def __init__(self, data_path, frames, index=0):
        self.data_path = data_path
        self.array_index = index
        self.keyframe_points = [_Point(frame, frame * 10.0) for frame in frames]
        self.updates = 0

    def update(self):
        self.updates += 1
        self.keyframe_points.sort(key=lambda point: point.co[0])


def _camera(frames):
    data = SimpleNamespace(curves=(_Curve("lens", frames),))
    return SimpleNamespace(
        type="CAMERA",
        data=data,
        curves=(
            _Curve("location", frames, 0),
            _Curve("location", frames, 2),
            _Curve("rotation_euler", frames, 1),
        ),
    )


def _beat(frame, time_base=None):
    return SimpleNamespace(
        beat_id=f"b{frame}",
        frame=int(frame),
        time_base=float(frame) if time_base is None else float(time_base),
    )


def _shot(frames, *, speed=0.0, state="DRAFT", recorded=True):
    beats = [_beat(frame, None if recorded else 0.0) for frame in frames]
    return SimpleNamespace(
        state=state,
        beats=beats,
        camera=_camera(frames),
        manifest_json="",
        speed=speed,
    )


def _scene(*, frame_end=48):
    scene = SimpleNamespace(
        frame_start=1,
        frame_end=frame_end,
        frame_current=1,
        frame_preview_start=1,
        frame_preview_end=frame_end,
        use_preview_range=True,
    )
    scene.frame_set = lambda frame: setattr(scene, "frame_current", frame)
    return scene


def _frames(shot):
    return [beat.frame for beat in shot.beats]


def _key_frames(camera):
    curves = tuple(camera.curves) + tuple(camera.data.curves)
    return sorted({round(point.co[0]) for curve in curves for point in curve.keyframe_points})


@pytest.fixture()
def quiet(monkeypatch):
    calls = SimpleNamespace(refreshed=0, scoped=0)
    monkeypatch.setattr(
        timeline,
        "_assigned_fcurves",
        lambda animated_id: tuple(getattr(animated_id, "curves", ())),
    )

    def _refresh(_scene, _shot):
        calls.refreshed += 1

    def _scope(_scene, _shot):
        calls.scoped += 1

    monkeypatch.setattr(retime, "refresh_manifest", _refresh)
    monkeypatch.setattr(retime, "scope_preview_range", _scope)
    return calls


# -------------------------------------------------------------------------
# Contract names and factor semantics.


def test_speed_contract_constants_and_factor():
    assert constants.SPEED_MIN == -1.0
    assert constants.SPEED_MAX == 1.0
    assert constants.DEFAULT_SPEED == 0.0
    # Middle of the slider is neutral: intervals stay as captured.
    assert retime.speed_factor(0.0) == 1.0
    # Right halves every interval (twice as fast), left doubles it.
    assert retime.speed_factor(1.0) == 0.5
    assert retime.speed_factor(-1.0) == 2.0
    assert retime.speed_factor(0.5) == pytest.approx(2 ** -0.5)


def test_shot_speed_property_binds_the_contract():
    properties = _read("ui/properties/director_properties.py")
    shot = properties.split("class MixarDirectorShot", 1)[1]
    speed = shot.split("speed: FloatProperty(", 1)[1].split("update=_on_speed_update", 1)[0]
    assert 'name="Speed"' in speed
    for line in ("min=SPEED_MIN", "max=SPEED_MAX", "default=DEFAULT_SPEED",
                 "soft_min=SPEED_MIN", "soft_max=SPEED_MAX", "step=5",
                 "precision=2"):
        assert line in speed, line
    assert "update=_on_speed_update" in shot
    beat = properties.split("class MixarDirectorBeat", 1)[1].split("class ", 1)[0]
    assert "time_base: FloatProperty(" in beat
    assert "default=0.0" in beat.split("time_base: FloatProperty(", 1)[1]
    # beat_seconds stays the capture spacing; it just left the slider.
    assert "beat_seconds: FloatProperty(" in properties


# -------------------------------------------------------------------------
# Retime semantics.


def test_faster_contracts_around_the_first_beat(quiet):
    shot = _shot((1, 25, 49), speed=1.0)
    scene = _scene(frame_end=49)

    assert retime.apply_shot_speed(scene, shot) == 2
    assert _frames(shot) == [1, 13, 25]
    assert _key_frames(shot.camera) == [1, 13, 25]
    assert quiet.refreshed == 1 and quiet.scoped == 1


def test_slower_expands_and_extends_the_scene_end(quiet):
    shot = _shot((1, 25, 49), speed=-1.0)
    scene = _scene(frame_end=49)

    assert retime.apply_shot_speed(scene, shot) == 2
    assert _frames(shot) == [1, 49, 97]
    assert scene.frame_end == 97


def test_anchor_stays_even_when_it_is_not_the_first_in_the_collection(quiet):
    # Capturing at the playhead can append an earlier beat; the anchor is
    # the chronologically first one, not beats[0].
    shot = _shot((25, 49, 1), speed=1.0)
    scene = _scene(frame_end=49)

    retime.apply_shot_speed(scene, shot)
    assert _frames(shot) == [13, 25, 1]
    assert _key_frames(shot.camera) == [1, 13, 25]


def test_neutral_speed_is_a_no_op(quiet):
    shot = _shot((1, 25, 49), speed=0.0)
    assert retime.apply_shot_speed(_scene(), shot) == 0
    assert _frames(shot) == [1, 25, 49]
    assert quiet.refreshed == 0


def test_many_small_updates_are_drift_free(quiet):
    original = (3, 20, 31, 44, 58, 77)
    shot = _shot(original, speed=0.0)
    scene = _scene(frame_end=77)
    steps = 100
    for step in range(1, steps + 1):
        shot.speed = step / steps
        retime.apply_shot_speed(scene, shot)
    assert _frames(shot) == [3, 12, 17, 24, 31, 40]
    for step in range(steps - 1, -1, -1):
        shot.speed = step / steps
        retime.apply_shot_speed(scene, shot)

    assert _frames(shot) == list(original)
    assert _key_frames(shot.camera) == list(original)
    assert [beat.time_base for beat in shot.beats] == [float(f) for f in original]


def test_keys_and_handles_move_with_the_beats_values_untouched(quiet):
    shot = _shot((1, 25, 49), speed=1.0)
    scene = _scene(frame_end=49)
    before = {
        (curve.data_path, curve.array_index): [
            (point.co[1], point.handle_left[1], point.handle_right[1])
            for point in curve.keyframe_points
        ]
        for curve in shot.camera.curves + shot.camera.data.curves
    }

    retime.apply_shot_speed(scene, shot)

    for curve in shot.camera.curves + shot.camera.data.curves:
        assert curve.updates == 1
        assert [round(p.co[0]) for p in curve.keyframe_points] == [1, 13, 25]
        # Handles keep their offset from the key (x only).
        for point in curve.keyframe_points:
            assert point.handle_left[0] == pytest.approx(point.co[0] - 0.25)
            assert point.handle_right[0] == pytest.approx(point.co[0] + 0.5)
        values = [
            (p.co[1], p.handle_left[1], p.handle_right[1])
            for p in curve.keyframe_points
        ]
        assert values == before[(curve.data_path, curve.array_index)]


def test_collapsing_beats_keep_one_frame_apart_in_order(quiet):
    # Halved, 1/2/3/4 would round onto 1/2/2/3; they stay one frame apart
    # in chronological order, and the far beat still lands where it should.
    shot = _shot((1, 2, 3, 4, 9), speed=1.0)
    scene = _scene(frame_end=9)

    assert retime.apply_shot_speed(scene, shot) == 1
    assert _frames(shot) == [1, 2, 3, 4, 5]
    # No key merged or deleted: every curve still carries all five keys.
    for curve in shot.camera.curves + shot.camera.data.curves:
        assert [round(p.co[0]) for p in curve.keyframe_points] == [1, 2, 3, 4, 5]


def test_collision_resolution_does_not_lose_the_captured_timing(quiet):
    shot = _shot((1, 2, 3, 4, 9), speed=0.0)
    scene = _scene(frame_end=9)
    shot.speed = 1.0
    retime.apply_shot_speed(scene, shot)
    shot.speed = 0.0
    retime.apply_shot_speed(scene, shot)
    assert _frames(shot) == [1, 2, 3, 4, 9]
    assert _key_frames(shot.camera) == [1, 2, 3, 4, 9]


def test_locked_shot_is_left_untouched(quiet):
    shot = _shot((1, 25, 49), speed=1.0, state="LOCKED")
    assert retime.apply_shot_speed(_scene(), shot) == 0
    assert _frames(shot) == [1, 25, 49]
    assert _key_frames(shot.camera) == [1, 25, 49]
    assert quiet.refreshed == 0


def test_shot_without_a_camera_is_a_no_op(quiet):
    shot = _shot((1, 25), speed=1.0)
    shot.camera = None
    assert retime.apply_shot_speed(_scene(), shot) == 0


def test_old_files_backfill_time_base_from_the_current_frames(quiet):
    shot = _shot((1, 25, 49), speed=1.0, recorded=False)
    assert [beat.time_base for beat in shot.beats] == [0.0, 0.0, 0.0]

    retime.apply_shot_speed(_scene(frame_end=49), shot)

    assert _frames(shot) == [1, 13, 25]
    assert [beat.time_base for beat in shot.beats] == [1.0, 25.0, 49.0]


def test_failure_restores_beats_keys_and_scene(quiet, monkeypatch):
    shot = _shot((1, 25, 49), speed=1.0)
    scene = _scene(frame_end=49)
    scene.frame_current = 30

    def _boom(_scene, _shot):
        raise RuntimeError("manifest")

    monkeypatch.setattr(retime, "refresh_manifest", _boom)
    with pytest.raises(RuntimeError):
        retime.apply_shot_speed(scene, shot)

    assert _frames(shot) == [1, 25, 49]
    assert _key_frames(shot.camera) == [1, 25, 49]
    assert scene.frame_end == 49
    assert scene.frame_current == 30


# -------------------------------------------------------------------------
# Recording time_base outside the speed update.


def test_note_beat_timing_inverts_the_retime_at_the_current_speed():
    shot = _shot((1, 13), speed=1.0)
    beat = SimpleNamespace(beat_id="new", frame=19, time_base=0.0)
    shot.beats.append(beat)

    retime.note_beat_timing(shot, beat)

    assert beat.time_base == pytest.approx(37.0)


def test_note_beat_timing_rebases_everything_when_the_anchor_moves():
    shot = _shot((1, 25, 49), speed=0.0)
    shot.beats[0].frame = 7
    retime.note_beat_timing(shot, shot.beats[0])
    assert [b.time_base for b in shot.beats] == [7.0, 25.0, 49.0]

    # An earlier capture becomes the new anchor: bases are measured from it.
    shot.speed = 1.0
    earlier = SimpleNamespace(beat_id="e", frame=3, time_base=0.0)
    shot.beats.append(earlier)
    retime.note_beat_timing(shot, earlier)
    assert [b.time_base for b in shot.beats] == [11.0, 47.0, 95.0, 3.0]


def test_shift_shot_timing_keeps_sub_frame_bases_exact():
    shot = _shot((1, 25), speed=1.0)
    shot.beats[1].time_base = 25.37
    retime.shift_shot_timing(shot, 10)
    assert [b.time_base for b in shot.beats] == pytest.approx([11.0, 35.37])


def test_timeline_drags_record_timing(quiet):
    shot = _shot((1, 25, 49), speed=1.0)
    # Consistent with speed 1: the captured timing was twice as long.
    for beat, time_base in zip(shot.beats, (1.0, 49.0, 97.0), strict=True):
        beat.time_base = time_base
    scene = _scene(frame_end=49)
    timeline.move_single_beat(scene, shot, 1, 6, rebuild_manifest=False)
    assert shot.beats[1].frame == 31
    assert shot.beats[1].time_base == pytest.approx(61.0)

    timeline.shift_camera_beats(scene, shot, 4, rebuild_manifest=False)
    assert _frames(shot) == [5, 35, 53]
    assert [b.time_base for b in shot.beats] == pytest.approx([5.0, 65.0, 101.0])


def test_every_frame_writer_records_time_base():
    capture = _read("core/capture.py")
    assert "beat.frame = target_frame\n        note_beat_timing(shot, beat)" in capture

    beat_sync = _read("core/beat_sync.py")
    assert "beat.frame = frame\n        note_beat_timing(shot, beat)" in beat_sync

    source = _read("core/timeline.py")
    single = source.split("def move_single_beat", 1)[1].split("def shift_camera_beats", 1)[0]
    assert "beat.frame = new_frame" in single
    assert "note_beat_timing(shot, beat)" in single
    whole = source.split("def shift_camera_beats", 1)[1]
    assert "beat.frame += delta" in whole
    assert "shift_shot_timing(shot, delta)" in whole

    shot_api = _read("core/shot_api.py")
    split = shot_api.split("def split_shot", 1)[1].split("def create_new_take", 1)[0]
    assert "copy.frame = beat_frame" in split
    assert "note_beat_timing(new_shot, copy)" in split
    assert "new_shot.speed = carried.speed" in split

    # The speed update itself never re-records: that is what keeps it drift-free.
    retime_source = _read("core/retime.py")
    apply = retime_source.split("def apply_shot_speed", 1)[1]
    assert "note_beat_timing(" not in apply
    assert "time_base =" not in apply


def test_speed_update_is_load_safe_and_skips_locked_shots():
    properties = _read("ui/properties/director_properties.py")
    update = properties.split("def _on_speed_update", 1)[1].split("\ndef ", 1)[0]
    assert "if self.state != 'DRAFT':\n        return" in update
    assert "apply_shot_speed(scene, self)" in update
    assert "try:" in update and "except Exception:" in update
    assert "bpy.ops" not in update
