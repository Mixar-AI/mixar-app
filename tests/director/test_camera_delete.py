# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deleting a camera from "My Cameras" removes the camera, not just its row."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.director.core import camera_delete

ROOT = Path(__file__).resolve().parents[2]
CAMERAS = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_director_cinema_cameras.cc"
).read_text(encoding="utf-8")


class _Shots(list):
    def remove(self, index):
        list.pop(self, index)


class _Scene:
    def __init__(self, cameras, shots):
        self.objects = list(cameras)
        self.camera = cameras[0] if cameras else None
        self.mixar_director = SimpleNamespace(shots=_Shots(shots), active_shot_index=0)


def _camera(name):
    return SimpleNamespace(name=name, type='CAMERA')


@pytest.fixture
def removed(monkeypatch):
    """Record what `bpy.data.objects.remove` was handed."""
    seen = []
    monkeypatch.setattr(
        camera_delete.bpy,
        "data",
        SimpleNamespace(objects=SimpleNamespace(remove=lambda obj, do_unlink: seen.append(obj))),
    )
    return seen


@pytest.fixture(autouse=True)
def _stub_shot_api(monkeypatch):
    def _remove_shot(scene, index):
        scene.mixar_director.shots.remove(index)
        return True

    monkeypatch.setattr(camera_delete, "remove_shot", _remove_shot)
    monkeypatch.setattr(camera_delete, "active_shot", lambda _scene: None)


def test_the_camera_object_is_removed(removed):
    cam = _camera("Camera")
    scene = _Scene([cam], [])
    camera_delete.delete_camera(scene, cam)
    assert removed == [cam]


def test_every_shot_directing_it_goes_with_it(removed):
    cam, other = _camera("Camera"), _camera("Camera.001")
    shots = [
        SimpleNamespace(camera=cam),
        SimpleNamespace(camera=other),
        SimpleNamespace(camera=cam),  # a second take on the same camera
    ]
    scene = _Scene([cam, other], shots)
    assert camera_delete.delete_camera(scene, cam) == 2
    assert [shot.camera for shot in scene.mixar_director.shots] == [other]


def test_shots_are_removed_highest_index_first(removed):
    """`shots.remove(i)` shifts everything after i; ascending order would
    remove the wrong take (and, for the last pair, run off the end)."""
    cam, other = _camera("Camera"), _camera("Camera.001")
    keep = SimpleNamespace(camera=other)
    shots = [SimpleNamespace(camera=cam), keep, SimpleNamespace(camera=cam)]
    scene = _Scene([cam, other], shots)
    camera_delete.delete_camera(scene, cam)
    assert list(scene.mixar_director.shots) == [keep]


def test_the_scene_camera_is_repointed_before_the_object_goes(removed):
    cam, other = _camera("Camera"), _camera("Camera.001")
    scene = _Scene([cam, other], [])
    scene.camera = cam
    camera_delete.delete_camera(scene, cam)
    assert scene.camera is other


def test_deleting_the_last_camera_leaves_the_scene_without_one(removed):
    """Minting a replacement behind the user's back would be a surprise; the
    card's "No cameras yet" empty state is the honest answer."""
    cam = _camera("Camera")
    scene = _Scene([cam], [])
    camera_delete.delete_camera(scene, cam)
    assert scene.camera is None


def test_the_row_chip_and_the_row_never_share_a_band():
    """`ui_but_find_mouse_over_ex` walks a block BACKWARDS, so the chip —
    created last — would swallow the whole row if the rects overlapped."""
    assert "select.xmax = remove.xmin - 2.0f * u;" in CAMERAS
    assert CAMERAS.index('"MIXAR_OT_director_pick_camera"') < CAMERAS.index(
        '"MIXAR_OT_director_delete_camera"'
    )


def test_the_chip_names_the_camera_and_is_published_for_qa():
    assert 'RNA_string_set(ui::button_operator_ptr_ensure(remove_but), "camera_name", name);' in CAMERAS
    assert 'cinema_qa_record(region, remove, "director_camera_delete", name, index);' in CAMERAS


def test_the_operator_confirms_and_survives_a_stale_row():
    source = (
        ROOT
        / "src/scripts/mixar/modules/director/ui/operators/camera_delete_ops.py"
    ).read_text(encoding="utf-8")
    assert "invoke_confirm" in source
    # The row's name is read at draw time; the camera can be gone by the click.
    assert 'if camera is None or camera.type != \'CAMERA\':' in source
    assert "{'CANCELLED'}" in source
