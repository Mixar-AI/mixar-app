# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every key on the dock is a real key: select, drag and delete act on the
camera's own keys, and the beats sitting on them follow.

Run against fake F-curves that implement the same collection API Blender's
`keyframe_points` does (`foreach_get` / `foreach_set`, `sort`, `remove`), so
the selection flags, the merge on drop and the beat bookkeeping are pinned
without Blender.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mixar.modules.director.core import beat_sync, key_drag, native_keys

_VECTORS = ("co", "handle_left", "handle_right")
_FLAGS = ("select_control_point", "select_left_handle", "select_right_handle")


class _Point:
    def __init__(self, x: float, y: float = 0.0, selected: bool = False):
        self.co = [float(x), float(y)]
        self.handle_left = [float(x) - 1.0, float(y)]
        self.handle_right = [float(x) + 1.0, float(y)]
        for flag in _FLAGS:
            setattr(self, flag, selected)


class _Points(list):
    def foreach_get(self, attribute, buffer):
        for index, point in enumerate(self):
            if attribute in _VECTORS:
                buffer[2 * index], buffer[2 * index + 1] = getattr(point, attribute)
            else:
                buffer[index] = getattr(point, attribute)

    def foreach_set(self, attribute, buffer):
        for index, point in enumerate(self):
            if attribute in _VECTORS:
                getattr(point, attribute)[:] = [buffer[2 * index], buffer[2 * index + 1]]
            else:
                setattr(point, attribute, bool(buffer[index]))

    def sort(self):
        # Stable, like Blender's bubble sort.
        super().sort(key=lambda point: point.co[0])

    def handles_recalc(self):
        pass

    def remove(self, point, fast=False):
        for index, existing in enumerate(self):
            if existing is point:
                del self[index]
                return
        raise ValueError(point)


class _FCurve:
    def __init__(self, path, keys):
        self.data_path = path
        self.keyframe_points = _Points(
            _Point(x, selected=sel) if isinstance(x, (int, float)) else _Point(*x)
            for x, sel in keys
        )

    def update(self):
        self.keyframe_points.sort()


class _Collection(list):
    def remove(self, fcurve):
        for index, existing in enumerate(self):
            if existing is fcurve:
                del self[index]
                return


def _camera(object_curves, lens_curves=()):
    data = SimpleNamespace(curves=_Collection(lens_curves))
    return SimpleNamespace(curves=_Collection(object_curves), data=data)


@pytest.fixture(autouse=True)
def _fake_curves(monkeypatch):
    monkeypatch.setattr(native_keys, "assigned_fcurves", lambda owner: tuple(owner.curves))
    monkeypatch.setattr(native_keys, "action_fcurves", lambda owner: owner.curves)


def _xs(fcurve):
    return [point.co[0] for point in fcurve.keyframe_points]


def _selected(fcurve):
    return [point.co[0] for point in fcurve.keyframe_points if point.select_control_point]


def _shot(camera, frames, shot_id="shot"):
    beats = [SimpleNamespace(frame=frame, time_base=float(frame)) for frame in frames]
    return SimpleNamespace(shot_id=shot_id, camera=camera, state="DRAFT", beats=beats)


def _scene(*shots, frame_start=1, frame_end=100):
    return SimpleNamespace(
        frame_start=frame_start,
        frame_end=frame_end,
        mixar_director=SimpleNamespace(shots=list(shots)),
    )


# -------------------------------------------------------------------------
# The frames contract with the native gestures.


def test_frames_are_parsed_defensively():
    assert native_keys.parse_frames("12.000,3.500, 12") == [3.5, 12.0]
    assert native_keys.parse_frames("") == []
    assert native_keys.parse_frames("a,,nan,inf,-2") == [-2.0]


def test_columns_fold_like_the_keylist():
    assert native_keys.merge_columns([10.0, 10.005, 20.0, 9.999]) == [9.999, 20.0]


# -------------------------------------------------------------------------
# Selection is Blender's own, a column at a time.


def test_set_makes_the_columns_the_selection_on_every_curve():
    loc = _FCurve("location", [(1, True), (2, False), (3, False)])
    lens = _FCurve("lens", [(2, False), (3, True)])
    camera = _camera([loc], [lens])
    assert native_keys.select_columns(camera, [2.0], "SET") == 2
    assert _selected(loc) == [2.0]
    assert _selected(lens) == [2.0]
    # Handles go with the key, as in the Dope Sheet.
    point = loc.keyframe_points[1]
    assert point.select_left_handle and point.select_right_handle


def test_extend_adds_and_toggle_flips_the_column():
    loc = _FCurve("location", [(1, True), (2, False), (3, False)])
    camera = _camera([loc])
    native_keys.select_columns(camera, [3.0], "EXTEND")
    assert _selected(loc) == [1.0, 3.0]
    native_keys.select_columns(camera, [3.0], "TOGGLE")
    assert _selected(loc) == [1.0]
    native_keys.select_columns(camera, [2.0], "TOGGLE")
    assert _selected(loc) == [1.0, 2.0]


def test_all_and_none():
    loc = _FCurve("location", [(1, False), (2, True)])
    camera = _camera([loc])
    native_keys.select_columns(camera, [], "ALL")
    assert _selected(loc) == [1.0, 2.0]
    native_keys.select_columns(camera, [], "NONE")
    assert _selected(loc) == []
    assert not native_keys.has_selected_keys(camera)


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        native_keys.select_columns(_camera([]), [], "INVERT")


# -------------------------------------------------------------------------
# Delete.


def test_delete_removes_the_selected_keys_and_an_emptied_curve():
    loc = _FCurve("location", [(1, True), (2, False), (3, True)])
    lens = _FCurve("lens", [(3, True)])
    camera = _camera([loc], [lens])
    assert native_keys.delete_keys(camera) == [1.0, 3.0]
    assert _xs(loc) == [2.0]
    # Like the Dope Sheet's delete: no empty channel left behind.
    assert list(camera.data.curves) == []


def test_delete_by_frame_takes_the_whole_column():
    loc = _FCurve("location", [(1, False), (2, False)])
    lens = _FCurve("lens", [(2, False)])
    camera = _camera([loc], [lens])
    assert native_keys.delete_keys(camera, [2.0]) == [2.0]
    assert _xs(loc) == [1.0]


def test_beats_without_a_key_lose_only_their_metadata(monkeypatch):
    from mixar.modules.director.core import capture

    calls = []
    monkeypatch.setattr(
        capture,
        "remove_beat",
        lambda scene, shot, index, delete_keys=True: calls.append((index, delete_keys))
        or shot.beats.pop(index)
        or True,
    )
    loc = _FCurve("location", [(10, False), (30, False)])
    camera = _camera([loc])
    shot = _shot(camera, [10, 20, 30])
    assert native_keys.drop_beats_without_keys(_scene(shot), camera) == 1
    assert calls == [(1, False)]
    assert [beat.frame for beat in shot.beats] == [10, 30]


# -------------------------------------------------------------------------
# Drag.


@pytest.fixture
def _quiet_finish(monkeypatch):
    from mixar.modules.director.core import capture, retime, rotation_curves, shot_api

    removed = []

    def _remove(scene, shot, index, delete_keys=True):
        removed.append((shot.beats[index].frame, delete_keys))
        shot.beats.pop(index)
        return True

    timed = []
    shifted = []
    monkeypatch.setattr(capture, "remove_beat", _remove)
    monkeypatch.setattr(retime, "note_beat_timing", lambda shot, beat: timed.append(beat.frame))
    monkeypatch.setattr(retime, "shift_shot_timing", lambda shot, delta: shifted.append(delta))
    monkeypatch.setattr(rotation_curves, "repair_rotation_continuity", lambda camera: 0)
    monkeypatch.setattr(shot_api, "refresh_manifest", lambda scene, shot: None)
    monkeypatch.setattr(shot_api, "release_preview_range", lambda scene: None)
    return SimpleNamespace(removed=removed, timed=timed, shifted=shifted)


def test_the_selected_keys_move_with_their_handles(_quiet_finish):
    loc = _FCurve("location", [(10, False), (20, True), (30, False)])
    camera = _camera([loc])
    drag = key_drag.KeyDrag(_scene(), camera)
    assert drag.apply(5) == 5
    assert _xs(loc) == [10.0, 25.0, 30.0]
    moved = loc.keyframe_points[1]
    assert moved.handle_left[0] == 24.0 and moved.handle_right[0] == 26.0


def test_the_offset_is_absolute_so_coming_back_lands_home(_quiet_finish):
    loc = _FCurve("location", [(10, False), (20, True), (30, False)])
    camera = _camera([loc])
    drag = key_drag.KeyDrag(_scene(), camera)
    drag.apply(14)  # past the neighbour at 30
    assert _xs(loc) == [10.0, 30.0, 34.0]
    drag.apply(-3)
    assert _xs(loc) == [10.0, 17.0, 30.0]
    drag.cancel()
    assert _xs(loc) == [10.0, 20.0, 30.0]


def test_a_dropped_key_replaces_the_one_it_lands_on(_quiet_finish):
    """A per-frame take has a key on every frame; refusing to overlap would
    make every key immovable. The Dope Sheet's grab replaces on confirm."""
    loc = _FCurve("location", [(10, False), (11, True), (12, False), (13, False)])
    camera = _camera([loc])
    drag = key_drag.KeyDrag(_scene(), camera)
    drag.apply(2)
    drag.finish()
    assert _xs(loc) == [10.0, 12.0, 13.0]
    assert _selected(loc) == [13.0]


def test_beats_ride_their_keys_and_a_replaced_beat_goes(_quiet_finish):
    loc = _FCurve("location", [(10, True), (20, False), (30, False)])
    camera = _camera([loc])
    shot = _shot(camera, [10, 20])
    scene = _scene(shot)
    drag = key_drag.KeyDrag(scene, camera)
    drag.apply(10)
    # Live, while the drag runs.
    assert [beat.frame for beat in shot.beats] == [20, 20]
    drag.finish()
    # The moved beat stays on its key; the one whose key it replaced goes,
    # metadata only.
    assert [beat.frame for beat in shot.beats] == [20]
    assert _quiet_finish.removed == [(20, False)]
    assert _quiet_finish.timed == [20]


def test_beats_of_other_shots_on_the_camera_follow_too(_quiet_finish):
    loc = _FCurve("location", [(10, True), (40, True)])
    camera = _camera([loc])
    first, second = _shot(camera, [10], "a"), _shot(camera, [40], "b")
    drag = key_drag.KeyDrag(_scene(first, second), camera)
    drag.apply(3)
    assert first.beats[0].frame == 13 and second.beats[0].frame == 43


def test_the_drag_never_pushes_keys_before_the_scene_start(_quiet_finish):
    loc = _FCurve("location", [(5, True), (8, True)])
    camera = _camera([loc])
    drag = key_drag.KeyDrag(_scene(frame_start=1), camera)
    assert drag.apply(-10) == -4
    assert _xs(loc) == [1.0, 4.0]


def test_dragging_past_the_end_grows_the_scene(_quiet_finish):
    loc = _FCurve("location", [(95, True)])
    camera = _camera([loc])
    scene = _scene(frame_end=100)
    drag = key_drag.KeyDrag(scene, camera)
    drag.apply(10)
    drag.finish()
    assert scene.frame_end == 105


def test_nothing_selected_is_nothing_to_drag(_quiet_finish):
    loc = _FCurve("location", [(10, False)])
    assert key_drag.KeyDrag(_scene(), _camera([loc])).empty


def test_the_strip_drag_moves_every_key_and_slides_the_timing(_quiet_finish):
    """The bar spans every key; a beats-only shift left the recorded
    samples behind."""
    loc = _FCurve("location", [(10, False), (11, False), (12, True)])
    camera = _camera([loc])
    shot = _shot(camera, [10])
    drag = key_drag.KeyDrag(_scene(shot), camera, everything=True)
    drag.apply(4)
    drag.finish()
    assert _xs(loc) == [14.0, 15.0, 16.0]
    assert shot.beats[0].frame == 14
    assert _quiet_finish.shifted == [4]
    assert _quiet_finish.timed == []
    assert _quiet_finish.removed == []


# -------------------------------------------------------------------------
# A move made in the Timeline or the Dope Sheet.


def test_a_move_elsewhere_carries_the_beats(monkeypatch):
    monkeypatch.setattr(beat_sync, "refresh_manifest", lambda scene, shot: None)
    monkeypatch.setattr(beat_sync, "note_beat_timing", lambda shot, beat: None)
    camera = _camera([])
    shot = _shot(camera, [10, 20, 30])
    moved = beat_sync.follow_moved_keys(_scene(shot), camera, {10, 20, 30}, {10, 25, 35})
    assert moved == 2
    assert [beat.frame for beat in shot.beats] == [10, 25, 35]


def test_a_count_change_is_not_a_move():
    camera = _camera([])
    shot = _shot(camera, [10, 20])
    assert beat_sync.follow_moved_keys(_scene(shot), camera, {10, 20}, {10}) == 0
    assert beat_sync.follow_moved_keys(_scene(shot), camera, None, {10}) == 0
    assert [beat.frame for beat in shot.beats] == [10, 20]
