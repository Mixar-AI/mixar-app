# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Provider-neutral sparse camera manifest contracts."""

import json
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core.manifest import (  # noqa: E402
    SCHEMA_ID,
    build_camera_direction_manifest,
    serialize_camera_direction_manifest,
)


def _beat(identifier, frame, x, image):
    return {
        "id": identifier,
        "frame": frame,
        "image_name": image,
        "location": (x, 2.0, 3.0),
        "rotation_quaternion": (1.0, 0.0, 0.0, 0.0),
        "lens_mm": 35.0,
    }


def test_manifest_sorts_beats_and_uses_relative_time():
    manifest = build_camera_direction_manifest(
        shot_id="shot-id",
        shot_name="Machine Shop Master",
        version=2,
        scene_name="Machine Shop",
        camera_name="Shot Camera",
        frame_start=1,
        frame_end=96,
        fps=24,
        fps_base=1.0,
        resolution_x=1920,
        resolution_y=1080,
        prompt="Track toward the robot.",
        guidance_strength="BALANCED",
        beats=[
            _beat("last", 49, 4.0, "Beat 03"),
            _beat("first", 1, 0.0, "Beat 01"),
            _beat("middle", 25, 2.0, "Beat 02"),
        ],
        exported_at="2026-08-05T00:00:00+00:00",
    )

    assert manifest["schema"] == SCHEMA_ID
    assert manifest["output"]["aspect"] == "16:9"
    assert manifest["output"]["pixel_aspect"] == [1.0, 1.0]
    assert manifest["coordinate_system"]["rotation_quaternion_order"] == "WXYZ"
    assert manifest["timeline"]["fps"] == 24.0
    assert manifest["timeline"]["duration_seconds"] == 2.0
    assert [beat["id"] for beat in manifest["beats"]] == [
        "first",
        "middle",
        "last",
    ]
    assert [beat["time_seconds"] for beat in manifest["beats"]] == [
        0.0,
        1.0,
        2.0,
    ]
    assert manifest["beats"][1]["camera"]["location"] == [2.0, 2.0, 3.0]
    assert manifest["beats"][1]["camera"]["projection"] == "PERSP"


def test_manifest_serialization_is_stable_and_unicode_safe():
    manifest = build_camera_direction_manifest(
        shot_id="id",
        shot_name="Café",
        version=1,
        scene_name="Scene",
        camera_name="Camera",
        frame_start=1,
        frame_end=1,
        fps=24,
        fps_base=1,
        resolution_x=1080,
        resolution_y=1080,
        prompt="Pan → reveal",
        guidance_strength="CONSERVATIVE",
        beats=[],
        exported_at="fixed",
    )

    serialized = serialize_camera_direction_manifest(manifest)
    assert "Café" in serialized
    assert "Pan → reveal" in serialized
    assert json.loads(serialized) == manifest
