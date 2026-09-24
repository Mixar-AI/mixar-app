# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Each camera frames for its own aspect ratio.

Blender has exactly one render size and it belongs to the scene, so a ratio
picked for the 2.39:1 hero shot silently reshaped the 9:16 cutdown beside it.
Director remembers the ratio on the camera's DATA and mirrors it into
`scene.render` whenever that camera becomes the live one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core.aspect import (
    apply_camera_ratio,
    camera_ratio,
    remember_camera_ratio,
)

ROOT = Path(__file__).resolve().parents[2]
PROPERTIES = (
    ROOT / "src/scripts/mixar/modules/director/ui/properties/director_properties.py"
).read_text(encoding="utf-8")
# The update callbacks live beside the rest of the logic (500-line rule).
UPDATES = (
    ROOT / "src/scripts/mixar/modules/director/core/property_updates.py"
).read_text(encoding="utf-8")


def _camera(*, aspect=None):
    output = SimpleNamespace(aspect_x=16, aspect_y=9, configured=False)
    if aspect is not None:
        output.aspect_x, output.aspect_y = aspect
        output.configured = True
    return SimpleNamespace(data=SimpleNamespace(mixar_director_output=output))


def _scene(width=1920, height=1080):
    return SimpleNamespace(
        render=SimpleNamespace(
            resolution_x=width,
            resolution_y=height,
            pixel_aspect_x=1.0,
            pixel_aspect_y=1.0,
        )
    )


def test_a_camera_remembers_the_ratio_picked_for_it():
    camera = _camera()
    assert camera_ratio(camera) is None
    assert remember_camera_ratio(camera, 239, 100) is True
    assert camera_ratio(camera) == (239, 100)


def test_the_stored_ratio_is_reduced():
    camera = _camera()
    remember_camera_ratio(camera, 1920, 1080)
    assert camera_ratio(camera) == (16, 9)


def test_switching_to_a_camera_reshapes_the_scene():
    scene = _scene(1920, 1080)
    apply_camera_ratio(scene, _camera(aspect=(9, 16)))
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1080, 1920)


def test_an_unconfigured_camera_leaves_the_scene_alone():
    """Snapping the frame to a default nobody chose is the worse surprise."""
    scene = _scene(2390, 1000)
    assert apply_camera_ratio(scene, _camera()) is False
    assert (scene.render.resolution_x, scene.render.resolution_y) == (2390, 1000)


def test_a_camera_already_in_shape_is_not_rewritten():
    """Writing would dirty the file and push an undo step for nothing."""
    scene = _scene(1920, 1080)
    assert apply_camera_ratio(scene, _camera(aspect=(16, 9))) is False


def test_the_short_side_survives_the_switch():
    """Switching cameras changes the SHAPE, never the quality tier."""
    scene = _scene(1280, 720)
    apply_camera_ratio(scene, _camera(aspect=(239, 100)))
    assert min(scene.render.resolution_x, scene.render.resolution_y) == 720


def test_a_camera_with_nowhere_to_store_it_fails_quietly():
    """Property updates also fire during file load, where the store may not
    be reachable yet; they must never raise."""
    bare = SimpleNamespace(data=SimpleNamespace())
    assert remember_camera_ratio(bare, 16, 9) is False
    assert camera_ratio(bare) is None
    assert apply_camera_ratio(_scene(), bare) is False
    assert apply_camera_ratio(_scene(), None) is False


def test_the_store_lives_on_the_camera_data_and_is_registered():
    """On the DATA, not the object: the ratio belongs to the lens the director
    framed with, and travels with the camera into another file."""
    assert "class MixarDirectorCameraOutput(PropertyGroup):" in PROPERTIES
    assert "bpy.types.Camera.mixar_director_output = PointerProperty(" in PROPERTIES
    assert "MixarDirectorCameraOutput," in PROPERTIES.split("classes = (")[1]
    assert "del bpy.types.Camera.mixar_director_output" in PROPERTIES


def test_every_camera_switch_applies_the_ratio():
    """Both switch paths: assigning a shot's camera, and changing the active
    shot. A path that skipped it would leave the frame in the last camera's
    shape."""
    assert UPDATES.count("apply_camera_ratio(scene, camera)") == 2
    for callback in ("_activate_shot_camera", "_on_active_shot_change"):
        body = UPDATES[UPDATES.index(f"def {callback}(") :]
        body = body[: body.index("\ndef ")]
        assert "apply_camera_ratio(scene, camera)" in body, callback
