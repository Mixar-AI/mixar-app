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
    release_preview_range,
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


def test_playback_uses_the_scenes_own_range_not_the_keyframes():
    """It used to clamp the preview range to the active shot's first and last
    beat, so pressing play looped between two keyframes however long the
    scene was — and the dock's Start and End fields, which edit
    `scene.frame_start` / `frame_end`, had no effect on what played. Two
    controls for one thing, and the invisible one won."""
    scene = SimpleNamespace(
        use_preview_range=True,
        frame_preview_start=1,
        frame_preview_end=49,
    )

    release_preview_range(scene)
    assert scene.use_preview_range is False
    # The preview range itself is the USER's setting; the session saves it on
    # entry and restores it on exit (tests/director/test_preview_range_restore),
    # so nothing here rewrites its bounds.
    assert (scene.frame_preview_start, scene.frame_preview_end) == (1, 49)
