# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pure contracts for per-camera shot selection and playback scoping."""

from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core.shot_api import (  # noqa: E402
    latest_shot_index_for_camera,
    scope_preview_range,
)


def test_camera_switching_prefers_the_newest_take():
    camera = object()
    other_camera = object()
    state = SimpleNamespace(
        shots=[
            SimpleNamespace(camera=camera, version=1),
            SimpleNamespace(camera=other_camera, version=9),
            SimpleNamespace(camera=camera, version=3),
            SimpleNamespace(camera=camera, version=2),
        ]
    )

    assert latest_shot_index_for_camera(state, camera) == 2
    assert latest_shot_index_for_camera(state, object()) == -1


def test_preview_range_tracks_only_the_active_shot_keyframes():
    scene = SimpleNamespace(
        use_preview_range=False,
        frame_preview_start=0,
        frame_preview_end=0,
    )
    shot = SimpleNamespace(
        beats=[
            SimpleNamespace(frame=49),
            SimpleNamespace(frame=1),
            SimpleNamespace(frame=25),
        ]
    )

    scope_preview_range(scene, shot)
    assert scene.use_preview_range is True
    assert (scene.frame_preview_start, scene.frame_preview_end) == (1, 49)

    scope_preview_range(scene, None)
    assert scene.use_preview_range is False
