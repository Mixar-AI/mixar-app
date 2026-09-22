# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recording a take: what Auto Key does while the timeline plays.

ONE switch. Blender ships one auto-key toggle and a director knows that one;
a second chip beside it wearing the same look asks "which of these do I
want?" about a distinction that is ours, not theirs. So Auto Key answers to
what the director is DOING — and the driver test is what makes that safe,
because pressing play to watch a shot back must not overwrite it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.director.core import record

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
RECORD = (DIRECTOR / "core/record.py").read_text(encoding="utf-8")
CAPTURE_OPS = (DIRECTOR / "ui/operators/capture_ops.py").read_text(encoding="utf-8")


class _Camera:
    def __init__(self):
        self.name = "Camera"
        self.rotation_mode = 'XYZ'
        self.data = SimpleNamespace(lens=50.0, keyframe_insert=self._key_data)
        self.keys: list[tuple[str, int]] = []
        self.types = []

    def keyframe_insert(self, data_path, frame, group=None, keytype='KEYFRAME'):
        self.keys.append((data_path, int(frame)))
        self.types.append(keytype)

    def _key_data(self, data_path, frame, group=None, keytype='KEYFRAME'):
        self.keys.append((f"data.{data_path}", int(frame)))
        self.types.append(keytype)


@pytest.fixture
def stub(monkeypatch):
    camera = _Camera()
    shot = SimpleNamespace(state='DRAFT', camera=camera, beats=[])
    scene = SimpleNamespace(
        frame_current=1,
        render=SimpleNamespace(fps=24, fps_base=1.0),
        mixar_director=SimpleNamespace(
            is_directing=True, auto_key=True, recording=False, beat_seconds=1.0
        ),
    )
    scene.frame_set = lambda frame, **_kw: setattr(scene, "frame_current", int(frame))
    context = SimpleNamespace(scene=scene)
    monkeypatch.setattr(record, "active_shot", lambda _scene: shot)
    monkeypatch.setattr(record, "_playing", lambda: True)
    monkeypatch.setattr(record, "camera_is_being_driven", lambda: True)
    monkeypatch.setattr(record, "repair_rotation_continuity", lambda _camera: None)
    monkeypatch.setattr(record.bpy, "context", context)

    minted: list[int] = []
    import mixar.modules.director.core.capture as capture_module

    monkeypatch.setattr(
        capture_module,
        "capture_beat",
        lambda ctx, _shot, _seconds, **_kw: minted.append(int(ctx.scene.frame_current)),
    )
    record.unregister()
    yield SimpleNamespace(scene=scene, camera=camera, shot=shot, context=context, minted=minted)
    record.unregister()


def _play(stub, frames):
    for frame in frames:
        stub.scene.frame_current = frame
        record._on_frame_change(stub.scene, None)


def test_every_frame_playback_passes_is_keyed(stub):
    _play(stub, range(1, 13))
    assert stub.scene.mixar_director.recording is True
    keyed = {frame for _path, frame in stub.camera.keys}
    assert keyed == set(range(1, 13))
    # Transform AND lens, the same channels a captured keyframe writes.
    paths = {path for path, _frame in stub.camera.keys}
    assert paths == {"location", "rotation_euler", "data.lens"}


def test_a_held_pose_is_still_part_of_the_performance(stub):
    """It keys the frame, not the change: a camera that pauses mid-move has
    to hold, and a gap in the curve is the camera drifting instead."""
    _play(stub, range(1, 6))
    assert len({frame for _p, frame in stub.camera.keys}) == 5


def test_recorded_samples_are_distinct_from_sparse_beats(stub):
    _play(stub, [2, 3, 4])
    assert set(stub.camera.types) == {'JITTER'}


def test_recording_status_covers_finalization(stub, monkeypatch):
    import mixar.modules.director.core.capture as capture_module

    statuses = []
    monkeypatch.setattr(
        capture_module, "capture_beat",
        lambda *_args, **_kw: statuses.append(stub.scene.mixar_director.recording),
    )
    _play(stub, range(1, 30))
    record._finish(stub.scene)
    assert statuses and all(statuses)
    assert not stub.scene.mixar_director.recording


def test_finalization_failure_releases_recording_status(stub, monkeypatch):
    def fail(_camera):
        raise RuntimeError('invalid curve')

    _play(stub, [1, 2])
    monkeypatch.setattr(record, 'repair_rotation_continuity', fail)
    with pytest.raises(RuntimeError, match='invalid curve'):
        record._finish(stub.scene)
    assert not stub.scene.mixar_director.recording
    assert not record.recording_suspended()


def test_nothing_is_recorded_unless_the_timeline_runs(stub, monkeypatch):
    """Scrubbing an armed take would write keys for frames the director is
    only looking at."""
    monkeypatch.setattr(record, "_playing", lambda: False)
    _play(stub, range(1, 10))
    assert stub.camera.keys == []


def test_nothing_is_recorded_unless_auto_key_is_on(stub):
    stub.scene.mixar_director.auto_key = False
    _play(stub, range(1, 10))
    assert stub.camera.keys == []


def test_watching_a_shot_back_does_not_overwrite_it(stub, monkeypatch):
    """The whole reason Record was briefly its own button. Playing with
    nothing driving the camera is a review, and a review that keys every
    frame flattens the curve it is reviewing."""
    monkeypatch.setattr(record, "camera_is_being_driven", lambda: False)
    _play(stub, range(1, 40))
    assert stub.camera.keys == []
    assert stub.scene.mixar_director.recording is False


def test_a_phone_counts_as_a_driver(monkeypatch):
    """It pumps poses from a timer, not a modal, so `move_in_progress`
    cannot see it — and it is the recording case a director reaches for
    first."""
    monkeypatch.setattr(record, "move_in_progress", lambda: False)
    monkeypatch.setattr(
        record.bpy,
        "context",
        SimpleNamespace(
            window_manager=SimpleNamespace(mixar_virtual_camera_connected=True)
        ),
    )
    assert record.camera_is_being_driven() is True


def test_a_locked_take_records_nothing(stub):
    stub.shot.state = 'LOCKED'
    _play(stub, range(1, 10))
    assert stub.camera.keys == []


def test_recording_renders_no_stills(stub):
    """A beat writes a PNG to disk. Twenty-four a second is the wrong shape,
    which is why this path never reaches `capture_beat` at all."""
    _play(stub, range(1, 50))
    assert stub.minted == []
    # Named in a comment as the thing that DOES render; never called before
    # the take ends.
    before_finish = RECORD.split("def _finish(")[0]
    assert "capture_beat(" not in before_finish


def test_stop_mints_beats_at_the_shots_own_cadence(stub):
    """The strip, the Speed slider, Export and the manifest all read beats; a
    take with none of them leaves the surface claiming nothing was recorded."""
    _play(stub, range(1, 50))
    record._finish(stub.scene)
    assert stub.scene.mixar_director.recording is False
    # One beat per second at 24fps, and the LAST frame always, because the
    # end of a move is a pose a director reaches for.
    assert stub.minted == [1, 25, 49]


def test_stop_puts_the_playhead_back(stub):
    _play(stub, range(1, 30))
    stub.scene.frame_current = 7
    record._finish(stub.scene)
    assert stub.scene.frame_current == 7


def test_stop_repairs_the_recorded_rotation(stub, monkeypatch):
    """A performed rotation can wind past a half turn between frames."""
    repaired = []
    monkeypatch.setattr(record, "repair_rotation_continuity", repaired.append)
    _play(stub, range(1, 10))
    record._finish(stub.scene)
    assert repaired == [stub.camera]


def test_stop_with_nothing_recorded_does_nothing(stub):
    record._finish(stub.scene)
    assert stub.minted == []


def test_a_take_stops_itself_before_it_runs_away():
    """Auto Key left on through a loop-playing scene would otherwise key for
    as long as the scene loops."""
    assert record.MAX_RECORDED_FRAMES > 0
    assert 'len(_take["frames"]) >= MAX_RECORDED_FRAMES' in RECORD


def test_there_is_no_second_switch():
    """Blender ships one auto-key toggle. A second chip beside it, wearing
    the same look, asks the director to choose between two of OUR words."""
    assert "MIXAR_OT_director_toggle_record" not in CAPTURE_OPS
    assert "mixar.director_toggle_record" not in CAPTURE_OPS
    actions = (
        ROOT
        / "src/source/blender/editors/space_view3d/view3d_director_cinema_dock_actions.cc"
    ).read_text(encoding="utf-8")
    assert "MIXAR_OT_director_toggle_record" not in actions
    # The chip still SAYS when a take is going down; that is published by the
    # recorder, not by a button.
    assert "state.recording ? ICON_REC" in actions


def test_a_take_is_keyed_before_the_frame_is_evaluated():
    """The bug this pins: a take that recorded ONE pose, over and over.

    `frame_change_post` runs after Blender has evaluated the camera's own
    action for the new frame and flushed it back onto the original
    datablock. A recorder reading the camera there reads the curve it is
    trying to write — so every frame keyed the pose the curve already held,
    and the director watched the camera snap back out of the walk on every
    frame boundary.
    """
    assert '("frame_change_pre", "_on_frame_change")' in RECORD
    # Named in the module docstring as the trap; never as a handler.
    assert '("frame_change_post"' not in RECORD


def test_directors_own_playhead_moves_are_not_a_performance(stub):
    """The re-entrancy `frame_change_pre` opened up.

    `_finish` walks the take's beat frames and `capture_beat` parks on the
    frame it is keying. Both are the code that KEYS a performance, not a
    camera being flown — and both land after `_finish` has emptied the take,
    so each one opened a fresh take and left the chip lit over a take nobody
    started, writing the pose the camera happened to be holding onto
    whichever frame it had been sent to.
    """
    with record.suspend_recording():
        _play(stub, range(1, 20))
    assert stub.camera.keys == []
    assert stub.scene.mixar_director.recording is False
    # And it lifts.
    _play(stub, [20])
    assert stub.camera.keys != []


def test_the_take_is_still_empty_after_it_finishes(stub):
    """A phantom take left `recording` True with frames nobody recorded."""
    _play(stub, range(1, 30))
    record._finish(stub.scene)
    assert record._take["frames"] == []
    assert record._take["camera"] is None
    assert stub.scene.mixar_director.recording is False


def test_minting_suspends_the_recorder():
    body = RECORD[RECORD.index("def _finish(") :]
    assert "with suspend_recording():" in body
    # Wrapping the restore too: it is the same programmatic move.
    assert body.index("with suspend_recording():") < body.index("scene.frame_set(original)")
    capture = (DIRECTOR / "core/capture.py").read_text(encoding="utf-8")
    assert "with suspend_recording():" in capture


def test_playback_ending_is_what_mints_the_beats():
    """No second click to stop: the take ends when the timeline does."""
    assert '("animation_playback_post", "_on_playback_end")' in RECORD
    assert "def _on_playback_end" in RECORD
