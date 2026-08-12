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
        "scope_preview_range",
        lambda scene, shot: calls.scoped.append(shot),
    )
    monkeypatch.setattr(
        beat_sync,
        "_ensure_timer",
        lambda: setattr(calls, "timer_started", calls.timer_started + 1),
    )
    monkeypatch.setitem(beat_sync._state, "key", None)
    monkeypatch.setitem(beat_sync._state, "count", None)
    monkeypatch.setitem(beat_sync._state, "prune", False)
    monkeypatch.setitem(beat_sync._state, "adopt", False)
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
    assert sync.refreshed == [shot] and sync.scoped == [shot]


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
