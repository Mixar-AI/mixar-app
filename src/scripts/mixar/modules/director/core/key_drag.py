# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dragging the selected camera keys in time, with the beats on them.

The dock's drag is the Dope Sheet's grab: every SELECTED key of the camera
moves by one whole-frame offset.

- The offset is applied ABSOLUTELY, from where each key sat at the press, so
  a drag that comes back lands exactly where it started.
- Curves are re-sorted every step. The camera the viewport shows while the
  drag runs is then the one it will leave.
- On release a moved key that lands on an unselected key REPLACES it, the
  way the Dope Sheet's grab merges on confirm — a per-frame take has a key
  on every frame, so refusing to overlap would make every key immovable.
- A beat is metadata on its key: the beats on the moved columns move with
  them, and a beat whose key was replaced goes (its pose is gone).

``everything=True`` is the strip body's drag: the bar spans every key the
camera carries, so sliding it slides all of them — the recorded samples too,
which a beats-only shift used to leave behind — whatever is selected.
"""

from __future__ import annotations

from math import ceil

from .native_keys import (
    beat_on_column,
    camera_fcurves,
    camera_shots,
    key_times,
    merge_columns,
    near,
    selected_mask,
)

#: Blender's frame limit (`MAXFRAME`).
MAX_FRAME = 1048574


def _read(points, attribute: str) -> list[float]:
    values = [0.0] * (2 * len(points))
    points.foreach_get(attribute, values)
    return values


def _moving(points, everything: bool) -> list[bool]:
    return [True] * len(points) if everything else selected_mask(points)


def _place(fcurve, originals, delta: float, everything: bool) -> None:
    """Put the moving keys of *fcurve* at their press positions + *delta*.

    *originals* is in time order. The moving keys all shift by one offset,
    so their order among themselves never changes and the k-th moving key
    in the (sorted) array is always the k-th original.
    """
    points = fcurve.keyframe_points
    mask = _moving(points, everything)
    co = _read(points, "co")
    left = _read(points, "handle_left")
    right = _read(points, "handle_right")
    k = 0
    for index, selected in enumerate(mask):
        if not selected or k >= len(originals):
            continue
        x, left_x, right_x = originals[k]
        co[2 * index] = x + delta
        left[2 * index] = left_x + delta
        right[2 * index] = right_x + delta
        k += 1
    points.foreach_set("co", co)
    points.foreach_set("handle_left", left)
    points.foreach_set("handle_right", right)
    points.sort()
    points.handles_recalc()


def _merge_onto_selected(fcurve) -> list[float]:
    """Remove unselected keys a selected key now covers; returns their times."""
    points = fcurve.keyframe_points
    times = key_times(points)
    mask = selected_mask(points)
    landed = sorted(x for x, selected in zip(times, mask) if selected)
    doomed = [
        index
        for index, (x, selected) in enumerate(zip(times, mask))
        if not selected and near(landed, x)
    ]
    for index in reversed(doomed):
        points.remove(points[index], fast=True)
    return [times[index] for index in doomed]


def _shot_by_id(scene, shot_id):
    state = getattr(scene, "mixar_director", None)
    for shot in getattr(state, "shots", ()) if state is not None else ():
        if shot.shot_id == shot_id:
            return shot
    return None


class KeyDrag:
    """One drag of the camera's selected keys (or of all of them)."""

    def __init__(self, scene, camera, *, everything: bool = False):
        self.scene = scene
        self.camera = camera
        self.everything = bool(everything)
        self.delta = 0
        #: (fcurve, [(x, handle_left_x, handle_right_x), ...] in time order)
        self._curves = []
        for fcurve in camera_fcurves(camera):
            points = fcurve.keyframe_points
            if not len(points):
                continue
            # Sorted first, so the array order the originals are read in IS
            # time order (`_place` relies on it).
            points.sort()
            mask = _moving(points, self.everything)
            if not any(mask):
                continue
            co = _read(points, "co")
            left = _read(points, "handle_left")
            right = _read(points, "handle_right")
            originals = [
                (co[2 * i], left[2 * i], right[2 * i])
                for i, selected in enumerate(mask)
                if selected
            ]
            self._curves.append((fcurve, originals))
        self.columns = merge_columns(
            x for _fcurve, originals in self._curves for x, _l, _r in originals
        )
        #: (shot_id, beat index, frame at the press) for beats on moved columns.
        self._beats = []
        for shot in camera_shots(scene, camera):
            for index, beat in enumerate(shot.beats):
                if beat_on_column(beat.frame, self.columns):
                    self._beats.append((shot.shot_id, index, int(beat.frame)))

    @property
    def empty(self) -> bool:
        return not self._curves

    def clamp(self, requested: int) -> int:
        """Keep the keys inside Blender's frame range and out of the stretch
        before the scene's start they did not already reach into."""
        if not self.columns:
            return 0
        first, last = self.columns[0], self.columns[-1]
        floor = min(float(self.scene.frame_start), first)
        lower = ceil(floor - first)
        upper = int(MAX_FRAME - last)
        return max(lower, min(int(requested), upper))

    def apply(self, requested: int) -> int:
        """Move the selection to *requested* frames from the press; returns
        the offset actually applied."""
        delta = self.clamp(requested)
        if delta == self.delta:
            return delta
        for fcurve, originals in self._curves:
            _place(fcurve, originals, delta, self.everything)
        for shot_id, index, frame in self._beats:
            shot = _shot_by_id(self.scene, shot_id)
            if shot is not None and index < len(shot.beats):
                shot.beats[index].frame = frame + delta
        self.delta = delta
        return delta

    def cancel(self) -> None:
        self.apply(0)

    def finish(self) -> int:
        """Commit the move; returns how many beats were replaced and removed."""
        from .capture import remove_beat
        from .retime import note_beat_timing, shift_shot_timing
        from .rotation_curves import repair_rotation_continuity
        from .shot_api import refresh_manifest, release_preview_range

        if not self.delta:
            return 0
        replaced: list[float] = []
        for fcurve, _originals in self._curves:
            if not self.everything:
                replaced.extend(_merge_onto_selected(fcurve))
            fcurve.update()
        replaced_columns = merge_columns(replaced)
        moved = {(shot_id, index) for shot_id, index, _frame in self._beats}
        removed = 0
        for shot in camera_shots(self.scene, self.camera):
            # Timing first, while the moved beats' indices still hold.
            if self.everything:
                # Every interval kept: slide the recorded timing exactly
                # rather than re-record it from rounded frames.
                shift_shot_timing(shot, self.delta)
            else:
                following = sorted(
                    (
                        shot.beats[index]
                        for sid, index, _frame in self._beats
                        if sid == shot.shot_id and index < len(shot.beats)
                    ),
                    key=lambda beat: int(beat.frame),
                )
                for beat in following:
                    note_beat_timing(shot, beat)
            doomed = [
                index
                for index, beat in enumerate(shot.beats)
                if (shot.shot_id, index) not in moved
                and beat_on_column(beat.frame, replaced_columns)
            ]
            for index in reversed(doomed):
                if remove_beat(self.scene, shot, index, delete_keys=False):
                    removed += 1
            refresh_manifest(self.scene, shot)
        repair_rotation_continuity(self.camera)
        last = self.columns[-1] + self.delta if self.columns else 0
        self.scene.frame_end = max(int(self.scene.frame_end), int(ceil(last)))
        release_preview_range(self.scene)
        return removed
