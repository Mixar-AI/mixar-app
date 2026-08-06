# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Director must not read RNA collection items across an ``add()``.

Blender stores ``CollectionProperty`` items in a reallocating IDProperty
array, so a reference obtained before ``add()`` points at freed memory
afterwards — a use-after-free, not an exception. The fakes below make that
failure loud: every proxy handed out before an ``add()`` raises when touched
again, so any code path that carries a shot or beat reference across a
capture/split/new-take fails the test instead of crashing a real session.
"""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core import camera_moves, shot_api  # noqa: E402


class _StaleReference(AssertionError):
    """Raised when a proxy outlives the ``add()`` that reallocated it."""


class _Proxy:
    """A view onto one backing record, valid only for its own generation."""

    def __init__(self, collection, record, generation):
        object.__setattr__(self, "_collection", collection)
        object.__setattr__(self, "_record", record)
        object.__setattr__(self, "_generation", generation)

    def _check(self):
        if self._collection.generation != self._generation:
            raise _StaleReference(
                "read of a collection item obtained before an add()"
            )

    def __getattr__(self, name):
        self._check()
        try:
            return self._record[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self._check()
        self._record[name] = value


class _Collection:
    """Minimal stand-in for a reallocating Blender CollectionProperty."""

    def __init__(self, defaults):
        self._defaults = defaults
        self._records = []
        self.generation = 0

    def add(self):
        self._records.append(dict(self._defaults))
        # Blender's IDProperty array moves on resize: every outstanding
        # reference is now dangling.
        self.generation += 1
        return self[len(self._records) - 1]

    def remove(self, index):
        del self._records[index]
        self.generation += 1

    def __getitem__(self, index):
        return _Proxy(self, self._records[index], self.generation)

    def __len__(self):
        return len(self._records)

    def __iter__(self):
        generation = self.generation
        for record in list(self._records):
            yield _Proxy(self, record, generation)


_SHOT_DEFAULTS = {
    "shot_id": "",
    "name": "",
    "version": 1,
    "parent_shot_id": "",
    "state": "DRAFT",
    "scene_ref": None,
    "camera": None,
    "prompt": "",
    "guidance_strength": "BALANCED",
    "render_output_types": set(),
    "render_resolution_percentage": 50,
    "handheld": False,
    "handheld_strength": 0.5,
    "active_beat_index": 0,
    "manifest_json": "",
    "beats": None,
}

_BEAT_DEFAULTS = {"beat_id": "", "frame": 1, "image": None}


class _ShotCollection(_Collection):
    def add(self):
        shot = super().add()
        # Each shot owns its own beats collection; adding beats resizes that
        # array, not the shots array.
        shot.beats = _Collection(_BEAT_DEFAULTS)
        return self[len(self._records) - 1]


def _make_scene():
    state = SimpleNamespace(shots=_ShotCollection(_SHOT_DEFAULTS), active_shot_index=0)
    return SimpleNamespace(mixar_director=state, camera=None)


@pytest.fixture()
def quiet_manifest(monkeypatch):
    monkeypatch.setattr(shot_api, "refresh_manifest", lambda scene, shot: "")
    monkeypatch.setattr(shot_api, "scope_preview_range", lambda scene, shot: None)


def test_new_take_inherits_a_parent_that_the_add_invalidated(quiet_manifest):
    scene = _make_scene()
    camera = object()
    parent = shot_api.create_shot(scene, camera)
    parent.prompt = "wide push in"
    parent.handheld = True
    parent.handheld_strength = 0.75
    parent.render_output_types = {"CLAY", "DEPTH"}
    parent.state = 'LOCKED'

    take = shot_api.create_new_take(scene, scene.mixar_director.shots[0])

    assert take.version == 2
    assert take.prompt == "wide push in"
    assert take.handheld is True
    assert take.handheld_strength == 0.75
    assert take.render_output_types == {"CLAY", "DEPTH"}
    assert take.parent_shot_id == scene.mixar_director.shots[0].shot_id


def test_split_reresolves_the_original_shot_after_the_add(quiet_manifest):
    scene = _make_scene()
    shot = shot_api.create_shot(scene, object())
    shot.prompt = "chase"
    for frame in (1, 25, 49, 73):
        beat = shot.beats.add()
        beat.beat_id = f"b{frame}"
        beat.frame = frame

    new_shot = shot_api.split_shot(scene, scene.mixar_director.shots[0], 30)

    original = scene.mixar_director.shots[0]
    assert [beat.frame for beat in original.beats] == [1, 25]
    assert [beat.frame for beat in new_shot.beats] == [49, 73]
    assert new_shot.prompt == "chase"
    # The first half stays active: the playhead still sits inside it.
    assert scene.mixar_director.active_shot_index == 0


def test_camera_move_reports_frames_not_stale_beat_references(monkeypatch):
    scene = SimpleNamespace(
        frame_current=1,
        render=SimpleNamespace(fps=24, fps_base=1.0),
        frame_set=lambda frame: setattr(scene, "frame_current", frame),
    )
    beats = _Collection(_BEAT_DEFAULTS)
    shot = SimpleNamespace(scene_ref=scene, camera=SimpleNamespace(matrix_world=None), beats=beats)

    def _capture(_context, target_shot, _seconds):
        beat = target_shot.beats.add()
        beat.frame = int(scene.frame_current)
        return beat

    monkeypatch.setattr(camera_moves, "capture_beat", _capture)
    monkeypatch.setattr(
        camera_moves, "move_poses", lambda scene, camera, move: [object(), object()]
    )
    context = SimpleNamespace(scene=scene, view_layer=SimpleNamespace(update=lambda: None))

    frames = camera_moves.apply_camera_move(
        context, shot, SimpleNamespace(beat_seconds=1.0), "ORBIT_LEFT"
    )

    assert frames == [1, 25, 49]
    assert all(isinstance(frame, int) for frame in frames)
