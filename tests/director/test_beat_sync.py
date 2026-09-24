# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Two-way beat/native-key reconciliation: adoption and edit detection."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core import beat_sync  # noqa: E402


class _Beats(list):
    def add(self):
        beat = SimpleNamespace(beat_id="", frame=0, image=None)
        self.append(beat)
        return beat


def _shot(camera, frames=(), state='DRAFT'):
    beats = _Beats()
    for frame in frames:
        beat = beats.add()
        beat.frame = frame
    return SimpleNamespace(
        camera=camera,
        state=state,
        beats=beats,
        active_beat_index=0,
    )


def _scene(*shots, frame_end=50):
    return SimpleNamespace(
        mixar_director=SimpleNamespace(shots=list(shots)),
        frame_end=frame_end,
        as_pointer=lambda: 1,
    )


@pytest.fixture
def sync(monkeypatch):
    """beat_sync with its Blender seams faked and state reset."""
    calls = SimpleNamespace(refreshed=[], scoped=[], timer_started=0)
    monkeypatch.setattr(
        beat_sync,
        "refresh_manifest",
        lambda scene, shot: calls.refreshed.append(shot),
    )
    monkeypatch.setattr(
        beat_sync,
        "release_preview_range",
        lambda scene: calls.scoped.append(scene),
    )
    monkeypatch.setattr(
        beat_sync,
        "_ensure_timer",
        lambda: setattr(calls, "timer_started", calls.timer_started + 1),
    )
    monkeypatch.setattr(
        beat_sync, "repair_rotation_continuity", lambda camera: 0
    )
    for key, value in beat_sync._INITIAL_STATE.items():
        monkeypatch.setitem(beat_sync._state, key, value)
    return calls


def _native(monkeypatch, frames):
    monkeypatch.setattr(
        beat_sync, "_native_key_frames", lambda camera: set(frames)
    )


def test_native_keys_the_strip_never_saw_become_beats(sync, monkeypatch):
    """Regression: hand-keyed cameras animated behind an empty strip."""
    _native(monkeypatch, {26, 58})
    camera = object()
    shot = _shot(camera)
    scene = _scene(shot)

    assert beat_sync.adopt_native_keyframes(scene, shot) == 2

    frames = [beat.frame for beat in shot.beats]
    ids = {beat.beat_id for beat in shot.beats}
    assert frames == [26, 58]
    assert len(ids) == 2 and all(ids)
    assert all(beat.image is None for beat in shot.beats)
    assert shot.active_beat_index == 1
    assert scene.frame_end == 58
    assert sync.refreshed == [shot] and sync.scoped == [scene]


def test_frames_claimed_by_shots_sharing_the_camera_stay_put(
    sync, monkeypatch
):
    """Takes and split shots share one camera timeline — never duplicate."""
    _native(monkeypatch, {1, 25, 49})
    camera = object()
    first_half = _shot(camera, frames=(1, 25))
    second_half = _shot(camera, frames=(49,))
    scene = _scene(first_half, second_half)

    assert beat_sync.adopt_native_keyframes(scene, first_half) == 0
    assert [beat.frame for beat in first_half.beats] == [1, 25]
    assert sync.refreshed == []


def test_adoption_fails_closed_without_a_draft_shot(sync, monkeypatch):
    _native(monkeypatch, {10})
    camera = object()
    locked = _shot(camera, state='LOCKED')
    assert beat_sync.adopt_native_keyframes(_scene(locked), locked) == 0

    cameraless = _shot(None)
    assert (
        beat_sync.adopt_native_keyframes(_scene(cameraless), cameraless) == 0
    )
    assert sync.refreshed == []


def test_handler_adopts_on_growth_and_fresh_watch_but_never_on_a_move(
    sync, monkeypatch
):
    camera = SimpleNamespace(name="Camera")
    shot = _shot(camera, frames=(1, 25))
    scene = _scene(shot)
    monkeypatch.setattr(beat_sync, "_watchable_shot", lambda _scene: shot)

    # A shot freshly under watch may already carry unseen native keys.
    _native(monkeypatch, {1, 25})
    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["adopt"] is True
    beat_sync._state["adopt"] = False

    # Growth: a key inserted through the native timeline.
    _native(monkeypatch, {1, 25, 40})
    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["adopt"] is True
    beat_sync._state["adopt"] = False

    # A MOVE keeps the count: the beat still exists, nothing to adopt.
    _native(monkeypatch, {1, 25, 44})
    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["adopt"] is False
    assert beat_sync._state["prune"] is False


def test_handler_prunes_only_on_a_genuine_deletion(sync, monkeypatch):
    camera = SimpleNamespace(name="Camera")
    shot = _shot(camera, frames=(1, 25, 49))
    scene = _scene(shot)
    monkeypatch.setattr(beat_sync, "_watchable_shot", lambda _scene: shot)

    _native(monkeypatch, {1, 25, 49})
    beat_sync._on_depsgraph_update(scene, None)
    _native(monkeypatch, {1, 25})
    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["prune"] is True


def test_request_reconcile_runs_without_waiting_for_depsgraph(sync):
    """Directing entry / shot switches cause no depsgraph tick.

    Regression: a natively keyed camera showed an empty Director strip
    until an unrelated edit (e.g. an outliner rename) happened to tick the
    watcher. An explicit request resets the baseline so the next tick is a
    fresh watch, flags adoption, and starts the timer immediately.
    """
    beat_sync._state["key"] = ("stale", "Camera")
    beat_sync.request_reconcile()

    assert beat_sync._state["key"] is None
    assert beat_sync._state["adopt"] is True
    assert sync.timer_started == 1


def test_switching_shots_resets_the_count_baseline(sync, monkeypatch):
    """A camera swap must not read as an edit of the previous camera."""
    first = _shot(SimpleNamespace(name="A"), frames=(1, 25, 49))
    second = _shot(SimpleNamespace(name="B"), frames=(1,))
    scene = _scene(first, second)

    monkeypatch.setattr(beat_sync, "_watchable_shot", lambda _scene: first)
    _native(monkeypatch, {1, 25, 49})
    beat_sync._on_depsgraph_update(scene, None)

    # Fewer native keys on the next camera is not a deletion.
    monkeypatch.setattr(beat_sync, "_watchable_shot", lambda _scene: second)
    _native(monkeypatch, {1})
    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["prune"] is False
    assert beat_sync._state["adopt"] is True


def test_a_live_recording_is_not_reconciled(sync, monkeypatch):
    shot = _shot(SimpleNamespace(name="Camera"))
    scene = _scene(shot)
    scene.mixar_director.is_directing = True
    scene.mixar_director.recording = True
    monkeypatch.setattr(beat_sync, "active_shot", lambda _scene: shot)
    _native(monkeypatch, {1, 2, 3, 4})
    assert beat_sync._watchable_shot(scene) is None


def test_recorded_samples_do_not_become_beats_after_reopening(sync, monkeypatch):
    from mixar.modules.director.core import anim_curves

    camera = SimpleNamespace(data=None)
    points = [SimpleNamespace(co=(f, 0), type='JITTER') for f in range(2, 25)]
    points += [SimpleNamespace(co=(f, 0), type='KEYFRAME') for f in (1, 25, 50)]
    monkeypatch.setattr(
        anim_curves, "assigned_fcurves",
        lambda _id: [SimpleNamespace(data_path='location', keyframe_points=points)],
    )
    shot = _shot(camera, frames=(1, 25))
    # A separate native I-key edit still gets adopted.
    assert beat_sync.adopt_native_keyframes(_scene(shot), shot) == 1
    assert [b.frame for b in shot.beats] == [1, 25, 50]
    # Export/render ranges continue to see the complete performance.
    assert anim_curves.camera_key_frames(camera) == set(range(1, 26)) | {50}


# -------------------------------------------------------------------------
# A beat is metadata on its key: it follows the key wherever it moves.


def _timer_context(monkeypatch, scene, *, transforming=False):
    windows = []
    if transforming:
        windows.append(
            SimpleNamespace(modal_operators={"TRANSFORM_OT_transform": object()})
        )
    monkeypatch.setattr(
        beat_sync.bpy,
        "context",
        SimpleNamespace(scene=scene, window_manager=SimpleNamespace(windows=windows)),
    )


def test_a_move_in_the_timeline_carries_the_beat_to_its_key(sync, monkeypatch):
    """A MOVE keeps the count, so it adopts and prunes nothing — the beat
    follows its key instead, however many updates the gesture took."""
    camera = SimpleNamespace(name="Camera")
    shot = _shot(camera, frames=(1, 25))
    scene = _scene(shot)
    monkeypatch.setattr(beat_sync, "_watchable_shot", lambda _scene: shot)
    monkeypatch.setattr(beat_sync, "note_beat_timing", lambda shot, beat: None)

    _native(monkeypatch, {1, 25})
    beat_sync._on_depsgraph_update(scene, None)
    for frames in ({1, 30}, {1, 36}, {1, 40}):  # one drag, three updates
        _native(monkeypatch, frames)
        beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["follow"] is True
    assert beat_sync._state["prune"] is False

    _timer_context(monkeypatch, scene)
    assert beat_sync._sync_timer() is None
    assert [beat.frame for beat in shot.beats] == [1, 40]
    assert beat_sync._state["synced"] == {1, 40}


def test_the_timer_waits_out_a_running_grab(sync, monkeypatch):
    """Mid-grab the frame set is not the one the director lets go on."""
    camera = SimpleNamespace(name="Camera")
    shot = _shot(camera, frames=(1, 25))
    scene = _scene(shot)
    beat_sync._state["follow"] = True
    _timer_context(monkeypatch, scene, transforming=True)
    assert beat_sync._sync_timer() == beat_sync._TIMER_INTERVAL
    # Still owed.
    assert beat_sync._state["follow"] is True


def test_a_dock_edit_holds_the_watcher_and_rebaselines_on_release(sync, monkeypatch):
    camera = SimpleNamespace(name="Camera")
    shot = _shot(camera, frames=(1, 25))
    scene = _scene(shot)
    monkeypatch.setattr(beat_sync, "_watchable_shot", lambda _scene: shot)
    monkeypatch.setattr(beat_sync, "_held", False)
    _native(monkeypatch, {1, 25})
    beat_sync._on_depsgraph_update(scene, None)

    beat_sync.hold(True)
    # Mid-drag the count dips: never read as a deletion while held.
    _native(monkeypatch, {1})
    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["prune"] is False
    _timer_context(monkeypatch, scene)
    assert beat_sync._sync_timer() == beat_sync._TIMER_INTERVAL

    beat_sync.hold(False)
    assert beat_sync._state["key"] is None
    assert beat_sync._state["synced"] is None
    assert beat_sync._state["follow"] is False
