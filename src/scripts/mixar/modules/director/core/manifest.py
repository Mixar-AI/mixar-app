# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Provider-neutral sparse camera-direction manifest."""

from __future__ import annotations

from datetime import datetime, timezone
from math import gcd
import json
from typing import Any, Mapping, Sequence

from .frame_math import effective_fps, seconds_from_frame


SCHEMA_ID = "mixar.camera_direction.v1"


def _rounded(values: Sequence[float]) -> list[float]:
    return [round(float(value), 6) for value in values]


def _aspect_label(width: int, height: int) -> str:
    divisor = gcd(max(1, int(width)), max(1, int(height)))
    return f"{int(width) // divisor}:{int(height) // divisor}"


def build_camera_direction_manifest(
    *,
    shot_id: str,
    shot_name: str,
    version: int,
    scene_name: str,
    camera_name: str,
    frame_start: int,
    frame_end: int,
    fps: float,
    fps_base: float,
    resolution_x: int,
    resolution_y: int,
    prompt: str,
    guidance_strength: str,
    beats: Sequence[Mapping[str, Any]],
    pixel_aspect_x: float = 1.0,
    pixel_aspect_y: float = 1.0,
    exported_at: str | None = None,
) -> dict[str, Any]:
    """Build the model-neutral contract consumed by future adapters.

    Each beat must provide ``id``, ``frame``, ``location``,
    ``rotation_quaternion`` and ``lens_mm``. ``image_name`` is optional.
    """
    ordered = sorted(beats, key=lambda beat: int(beat["frame"]))
    origin = int(ordered[0]["frame"]) if ordered else int(frame_start)
    fps_value = effective_fps(fps, fps_base)
    serialized_beats = []
    for index, beat in enumerate(ordered):
        frame = int(beat["frame"])
        camera = {
            "location": _rounded(beat["location"]),
            "rotation_quaternion": _rounded(
                beat["rotation_quaternion"]
            ),
            "projection": str(beat.get("projection", "PERSP")),
            "lens_mm": round(float(beat["lens_mm"]), 4),
            "ortho_scale": round(float(beat.get("ortho_scale", 6.0)), 4),
            "sensor_mm": [
                round(float(beat.get("sensor_width_mm", 36.0)), 4),
                round(float(beat.get("sensor_height_mm", 32.0)), 4),
            ],
            "sensor_fit": str(beat.get("sensor_fit", "AUTO")),
            "shift": [
                round(float(beat.get("shift_x", 0.0)), 6),
                round(float(beat.get("shift_y", 0.0)), 6),
            ],
        }
        serialized_beats.append({
            "id": str(beat["id"]),
            "index": index,
            "frame": frame,
            "time_seconds": round(
                seconds_from_frame(
                    frame,
                    origin_frame=origin,
                    fps=fps,
                    fps_base=fps_base,
                ),
                6,
            ),
            "image_name": str(beat.get("image_name", "") or ""),
            "camera": camera,
        })

    duration = serialized_beats[-1]["time_seconds"] if serialized_beats else 0.0
    return {
        "schema": SCHEMA_ID,
        "exported_at": exported_at or datetime.now(timezone.utc).isoformat(),
        "shot": {
            "id": str(shot_id),
            "name": str(shot_name),
            "version": int(version),
            "scene": str(scene_name),
            "camera": str(camera_name),
            "prompt": str(prompt or ""),
            "guidance_strength": str(guidance_strength),
        },
        "timeline": {
            "frame_start": int(frame_start),
            "frame_end": int(frame_end),
            "fps": round(fps_value, 6),
            "duration_seconds": round(float(duration), 6),
        },
        "output": {
            "resolution": [int(resolution_x), int(resolution_y)],
            "aspect": _aspect_label(resolution_x, resolution_y),
            "pixel_aspect": [
                round(float(pixel_aspect_x), 6),
                round(float(pixel_aspect_y), 6),
            ],
        },
        "coordinate_system": {
            "handedness": "RIGHT_HANDED",
            "up_axis": "+Z",
            "camera_forward_axis": "-Z",
            "rotation_quaternion_order": "WXYZ",
        },
        "beats": serialized_beats,
    }


def serialize_camera_direction_manifest(manifest: Mapping[str, Any]) -> str:
    """Serialize a manifest deterministically for Text datablocks/snapshots."""
    return json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
