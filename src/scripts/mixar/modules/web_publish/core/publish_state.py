# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thread-safe publish state and pure helpers.

The publish pipeline runs on a daemon thread while Blender owns the UI. This
module is the ONLY channel between them: worker threads write state through
``PublishState`` (mutex-guarded), a Blender timer copies it into scene RNA for
drawing. No bpy import here — every function is testable outside Blender.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Status values (mirrored by the RNA enum in ui/properties)
STATUS_IDLE = "IDLE"
STATUS_EXPORTING = "EXPORTING"
STATUS_UPLOADING = "UPLOADING"
STATUS_FINALIZING = "FINALIZING"
STATUS_DONE = "DONE"
STATUS_ERROR = "ERROR"

TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_ERROR})


def compute_sha256(path: str, chunk_size: int = 4 * 1024 * 1024) -> Tuple[str, int]:
    """Stream a file to its sha256 hex digest. Returns (hexdigest, size)."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def derive_title(scene_name: str) -> str:
    """A human title from a Blender scene name ("Scene.001" -> "Scene 001")."""
    name = (scene_name or "").strip()
    if not name:
        return "Untitled Scene"
    stem = name.split(".", 1)[0].replace("_", " ").strip()
    return stem or "Untitled Scene"


def suggest_slug(title: str) -> str:
    """Client-side slug suggestion (backend remains authoritative)."""
    import re
    import unicodedata

    folded = unicodedata.normalize("NFKD", title or "")
    ascii_folded = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_folded).strip("-")
    return (slug or "scene")[:80]


def camera_pose_to_config(world_matrix, lens_mm: float, sensor_mm: float) -> Dict[str, Any]:
    """Decompose a camera world matrix into the viewer's config block.

    Rows of the matrix give the camera basis; position is the translation
    column. The viewer reconstructs the same orientation from (position,
    target, up), so project -Z (Blender cameras look down -Z) onto the
    horizontal plane to derive a stable target distance.
    """
    try:
        px, py, pz = world_matrix.col[3][0], world_matrix.col[3][1], world_matrix.col[3][2]
        fwd = world_matrix.col[2]  # camera -Z axis (matrix column 2 = +Z basis)
        # Look direction is -Z of the camera.
        look = (-fwd[0], -fwd[1], -fwd[2])
        if math.isnan(look[0]) or (abs(look[0]) + abs(look[1]) + abs(look[2])) < 1e-9:
            look = (0.0, 0.0, -1.0)
    except Exception:
        return {}
    distance = 10.0
    target = (
        px + look[0] * distance,
        py + look[1] * distance,
        pz + look[2] * distance,
    )
    config = {
        "position": [round(px, 4), round(py, 4), round(pz, 4)],
        "target": [round(target[0], 4), round(target[1], 4), round(target[2], 4)],
        "up": [0.0, 0.0, 1.0],
    }
    if lens_mm and lens_mm > 0 and sensor_mm and sensor_mm > 0:
        fov_deg = math.degrees(2.0 * math.atan(sensor_mm / (2.0 * lens_mm)))
        config["fov"] = round(min(120.0, max(10.0, fov_deg)), 2)
    return config


def viewer_config_block(camera_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble the viewer_config payload sent with the publish request."""
    config: Dict[str, Any] = {
        "nav": ["orbit", "walk"],
        "environment": "studio",
        "background": "environment",
    }
    if camera_config:
        config["camera"] = camera_config
    return config


def build_scene_meta(
    object_count: int,
    triangle_count: int,
    material_count: int,
    texture_count: int,
    has_animation: bool,
) -> Dict[str, Any]:
    return {
        "objects": int(max(object_count, 0)),
        "triangles": int(max(triangle_count, 0)),
        "materials": int(max(material_count, 0)),
        "textures": int(max(texture_count, 0)),
        "animations": 1 if has_animation else 0,
    }


def part_ranges(file_size: int, part_size: int) -> List[Tuple[int, int, int]]:
    """Split a file size into (part_number, start, length) ranges."""
    if file_size <= 0:
        return []
    part_size = max(1, int(part_size))
    ranges = []
    offset = 0
    part_number = 1
    while offset < file_size:
        length = min(part_size, file_size - offset)
        ranges.append((part_number, offset, length))
        offset += length
        part_number += 1
    return ranges


@dataclass
class PublishProgress:
    status: str = STATUS_IDLE
    detail: str = ""
    progress: float = 0.0
    error: str = ""


@dataclass
class PublishResult:
    scene_id: str = ""
    slug: str = ""
    share_url: str = ""
    viewer_url: str = ""
    revision: int = 0


@dataclass
class PublishJob:
    """Everything the worker thread needs; owned by the caller (operator)."""

    title: str
    description: str
    visibility: str
    glb_path: str
    thumbnail_path: str
    content_sha256: str
    scene_meta: Dict[str, Any] = field(default_factory=dict)
    viewer_config: Dict[str, Any] = field(default_factory=dict)
    # Update path: publish a new revision of an existing scene
    existing_scene_id: str = ""
    existing_slug: str = ""


class PublishState:
    """Mutex-guarded state shared between the worker thread and the UI timer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = PublishProgress()
        self._result = PublishResult()
        self._started_monotonic = 0.0
        self._finished_monotonic = 0.0
        self._cancel_requested = False

    # -- worker-side writers -------------------------------------------------

    def start(self) -> None:
        with self._lock:
            self._progress = PublishProgress(status=STATUS_EXPORTING)
            self._result = PublishResult()
            self._started_monotonic = time.monotonic()
            self._finished_monotonic = 0.0
            self._cancel_requested = False

    def set_status(self, status: str, detail: str = "", progress: Optional[float] = None) -> None:
        with self._lock:
            self._progress.status = status
            if detail is not None:
                self._progress.detail = detail
            if progress is not None:
                self._progress.progress = _clamp01(progress)

    def set_upload_progress(self, uploaded_bytes: int, total_bytes: int, detail: str = "") -> None:
        fraction = 0.0
        if total_bytes > 0:
            fraction = _clamp01(uploaded_bytes / total_bytes)
        with self._lock:
            self._progress.status = STATUS_UPLOADING
            self._progress.progress = fraction
            if detail:
                self._progress.detail = detail

    def set_error(self, message: str) -> None:
        with self._lock:
            self._progress.status = STATUS_ERROR
            self._progress.error = message
            self._finished_monotonic = time.monotonic()

    def set_result(self, result: PublishResult, detail: str = "") -> None:
        with self._lock:
            self._progress.status = STATUS_DONE
            self._progress.progress = 1.0
            self._progress.detail = detail
            self._result = result
            self._finished_monotonic = time.monotonic()

    def request_cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True

    # -- reader-side (UI timer) ----------------------------------------------

    def snapshot(self) -> Tuple[PublishProgress, PublishResult]:
        with self._lock:
            return (
                PublishProgress(
                    status=self._progress.status,
                    detail=self._progress.detail,
                    progress=self._progress.progress,
                    error=self._progress.error,
                ),
                PublishResult(
                    scene_id=self._result.scene_id,
                    slug=self._result.slug,
                    share_url=self._result.share_url,
                    viewer_url=self._result.viewer_url,
                    revision=self._result.revision,
                ),
            )

    @property
    def busy(self) -> bool:
        with self._lock:
            return (
                self._progress.status
                not in (STATUS_IDLE, STATUS_DONE, STATUS_ERROR)
            )

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def reset(self) -> None:
        with self._lock:
            self._progress = PublishProgress()
            self._cancel_requested = False


def _clamp01(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, value))


# Process-wide state (one publish at a time — the panel refuses to start a
# second while one is running).
_state = PublishState()


def get_publish_state() -> PublishState:
    return _state
