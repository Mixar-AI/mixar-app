# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adopting a camera: one rule, shared by the row click and entering the mode.

Each camera is its own shot and its own timeline, so adopting never
reassigns an existing shot's camera — that collapsed every camera onto one
strip. It switches to the take already directing this camera, or mints a
shot for one Director has not seen.

It matters on entry because a session with no active shot greys out every
shot-gated control: the Walk chip came up disabled and the My Cameras row
never lit, on a surface plainly looking through that camera.
"""

from __future__ import annotations

from types import SimpleNamespace

from mixar.modules.director.core import shot_api


class _Shots(list):
    def add(self):
        shot = SimpleNamespace(
            shot_id="", camera=None, name="", version=1, parent_shot_id="",
            prompt="", guidance_strength="", render_output_types=set(),
            render_resolution_percentage=100, speed=1.0, beats=[],
            state="DRAFT",
        )
        self.append(shot)
        return shot


def _scene(*shots):
    collection = _Shots(shots)
    state = SimpleNamespace(shots=collection, active_shot_index=0)
    return SimpleNamespace(mixar_director=state, camera=None)


def _camera(name):
    return SimpleNamespace(name=name, type="CAMERA")


def test_adopting_an_unknown_camera_mints_a_shot():
    scene = _scene()
    camera = _camera("Camera")

    shot = shot_api.adopt_camera(scene, camera)

    assert shot is not None
    assert shot.camera is camera
    assert scene.camera is camera
    assert scene.mixar_director.active_shot_index == 0
    assert len(scene.mixar_director.shots) == 1


def test_adopting_a_known_camera_switches_to_its_newest_take():
    first, second = _camera("A"), _camera("B")
    scene = _scene()
    shot_api.adopt_camera(scene, first)
    shot_api.adopt_camera(scene, second)
    # A second take of the first camera, newer than take 1.
    take2 = scene.mixar_director.shots.add()
    take2.camera = first
    take2.version = 2

    shot = shot_api.adopt_camera(scene, first)

    assert shot is take2
    assert scene.mixar_director.active_shot_index == 2
    assert scene.camera is first
    # Nothing was minted, and nobody's camera was reassigned.
    assert len(scene.mixar_director.shots) == 3
    assert [s.camera for s in scene.mixar_director.shots] == [first, second, first]


def test_adopting_is_idempotent():
    scene = _scene()
    camera = _camera("Camera")
    first = shot_api.adopt_camera(scene, camera)

    assert shot_api.adopt_camera(scene, camera) is first
    assert len(scene.mixar_director.shots) == 1


def test_a_non_camera_is_refused():
    scene = _scene()
    assert shot_api.adopt_camera(scene, SimpleNamespace(type="MESH")) is None
    assert shot_api.adopt_camera(scene, None) is None
    assert len(scene.mixar_director.shots) == 0


def test_a_scene_without_director_state_is_refused():
    assert shot_api.adopt_camera(SimpleNamespace(mixar_director=None), _camera("C")) is None
    assert shot_api.adopt_camera(SimpleNamespace(), _camera("C")) is None
