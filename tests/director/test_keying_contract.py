# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One place turns a Director camera pose into keyframes.

A beat and the native keys under it are ONE thing: `core/timeline.py` retimes
a beat by finding the keys on its frame, so a partly keyed pose is a pose
that comes apart the first time it is dragged. These pin that every keying
path writes the same channels, and that the three Blender keying preferences
which would break the coupling stay deliberately unhonoured.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core import keying

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/scripts/mixar/modules/director/core"
KEYING = (CORE / "keying.py").read_text(encoding="utf-8")


class _Camera:
    def __init__(self, rotation_mode="XYZ"):
        self.rotation_mode = rotation_mode
        self.keys: list[tuple[str, int, str]] = []
        self.data = SimpleNamespace(keyframe_insert=self._key_data)

    def keyframe_insert(self, data_path, frame, group=None, keytype='KEYFRAME'):
        self.keys.append((data_path, int(frame), group))

    def _key_data(self, data_path, frame, group=None, keytype='KEYFRAME'):
        self.keys.append((f"data.{data_path}", int(frame), group))


def test_a_pose_is_location_rotation_and_lens():
    camera = _Camera()
    keying.key_camera_pose(camera, 7)
    assert camera.keys == [
        ("location", 7, "Director"),
        ("rotation_euler", 7, "Director"),
        ("data.lens", 7, "Director"),
    ]


def test_rotation_follows_the_cameras_own_mode():
    """Director never converts a user's rotation mode; the key follows it."""
    camera = _Camera(rotation_mode='QUATERNION')
    keying.key_camera_pose(camera, 3)
    assert ("rotation_quaternion", 3, "Director") in camera.keys


def test_every_camera_keying_path_goes_through_it():
    """Two call sites used to spell the same three inserts out separately,
    which is how they drift."""
    for name in ("capture.py", "record.py"):
        source = (CORE / name).read_text(encoding="utf-8")
        assert "key_camera_pose(camera, frame" in source, name
        assert 'keyframe_insert(data_path="location"' not in source, name


def test_blenders_keying_preferences_stay_unhonoured_on_purpose():
    """Each is right for Blender's model and wrong for this one. The reasons
    are recorded so the next reader does not "fix" it — a beat is retimed by
    the keys found on its frame, so a per-channel skip splits the pose, and
    `core/tracking.py` states the opposite contract to visual keying."""
    for preference in (
        "key_insert_channels",
        "use_auto_keyframe_insert_needed",
        "use_keyframe_insert_needed",
        "use_visual_keying",
    ):
        assert preference in KEYING, preference
    # Named as reasons, never READ as settings: no preference lookup and no
    # `options=` on the inserts.
    body = KEYING.split('"""', 2)[2]
    assert "preferences" not in body
    assert "INSERTKEY" not in body
    assert "options=" not in body
