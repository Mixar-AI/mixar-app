# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thread-safe publish state and pure helpers.

The publish pipeline runs on a daemon thread while Blender owns the UI. This
module is the ONLY channel between them: the worker writes through
``PublishState`` (mutex-guarded); a Blender timer reads snapshots and mirrors
them into RNA. No bpy import here — everything is testable outside Blender.

Detail and error text is kept as an untranslated template plus named
arguments: the panel translates at draw time (``iface_``), the agent gets
the English formatting (``format_message``). Terminal outcomes stay readable
by ``publish_id`` after the panel dismisses them, so an agent polling late
still sees ``ready`` / ``failed`` / ``cancelled``.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

# Status values (mirrored by the RNA enum in ui/properties)
STATUS_IDLE = "IDLE"
STATUS_EXPORTING = "EXPORTING"
STATUS_UPLOADING = "UPLOADING"
STATUS_FINALIZING = "FINALIZING"
STATUS_DONE = "DONE"
STATUS_ERROR = "ERROR"
STATUS_CANCELLED = "CANCELLED"

BUSY_STATUSES = frozenset({STATUS_EXPORTING, STATUS_UPLOADING, STATUS_FINALIZING})
TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED})
_RECORD_LIMIT = 8


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
    """A human title from a Blender scene name ("Scene.001" -> "Scene")."""
    name = (scene_name or "").strip()
    if not name:
        return "Untitled Scene"
    stem = name.split(".", 1)[0].replace("_", " ").strip()
    return stem or "Untitled Scene"


def suggest_slug(title: str) -> str:
    """Client-side slug suggestion (backend remains authoritative)."""
    folded = unicodedata.normalize("NFKD", title or "")
    ascii_folded = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_folded).strip("-")
    return (slug or "scene")[:80]


def format_message(template: str, args: Optional[Dict[str, Any]] = None) -> str:
    """``template.format(**args)`` that never raises (a bad template shows raw)."""
    try:
        return str(template or "").format(**(args or {}))
    except (KeyError, IndexError, ValueError):
        return str(template or "")


def _gltf_axes(x: float, y: float, z: float) -> List[float]:
    """Blender Z-up → glTF / three.js Y-up (the exporter's ``export_yup``)."""
    return [round(x, 4), round(z, 4), round(-y, 4)]


def vertical_fov_degrees(lens_mm: float, sensor_width_mm: float, sensor_height_mm: float = 0.0,
                         sensor_fit: str = "AUTO", aspect: float = 16 / 9) -> Optional[float]:
    """three.js ``PerspectiveCamera.fov`` (vertical) for a Blender camera.

    ``aspect`` is the render width/height. AUTO fits the sensor width to the
    larger frame dimension; HORIZONTAL to the width; VERTICAL uses the
    sensor height for the frame height."""
    if not lens_mm or lens_mm <= 0 or aspect <= 0:
        return None
    fit = str(sensor_fit or "AUTO").upper()
    if fit == "VERTICAL" and sensor_height_mm > 0:
        return math.degrees(2.0 * math.atan(sensor_height_mm / (2.0 * lens_mm)))
    if not sensor_width_mm or sensor_width_mm <= 0:
        return None
    half = math.atan(sensor_width_mm / (2.0 * lens_mm))
    if fit == "HORIZONTAL" or aspect >= 1.0:
        half = math.atan(math.tan(half) / aspect)  # sensor spans the width
    return math.degrees(2.0 * half)


def camera_pose_to_config(world_matrix, lens_mm: float, sensor_mm: float, *,
                          sensor_height_mm: float = 0.0, sensor_fit: str = "AUTO",
                          aspect: float = 16 / 9) -> Dict[str, Any]:
    """The viewer's ``viewer_config.camera`` from a Blender camera.

    Coordinates are glTF / three.js Y-up (the same frame as the exported
    GLB) and ``fov`` is VERTICAL degrees, as ``PerspectiveCamera.fov``.
    Blender cameras look down their local -Z (matrix column 2 negated).
    The viewer prefers the exported camera node tagged
    ``mixar_active_camera``; this block is its fallback.
    """
    try:
        px, py, pz = world_matrix.col[3][0], world_matrix.col[3][1], world_matrix.col[3][2]
        fwd = world_matrix.col[2]
        look = (-fwd[0], -fwd[1], -fwd[2])
        if math.isnan(look[0]) or (abs(look[0]) + abs(look[1]) + abs(look[2])) < 1e-9:
            look = (0.0, 0.0, -1.0)
    except Exception:  # noqa: BLE001 — any malformed matrix means "no camera block"
        return {}
    distance = 10.0
    config = {
        "position": _gltf_axes(px, py, pz),
        "target": _gltf_axes(px + look[0] * distance, py + look[1] * distance,
                             pz + look[2] * distance),
        "up": [0.0, 1.0, 0.0],
    }
    fov = vertical_fov_degrees(lens_mm, sensor_mm, sensor_height_mm, sensor_fit, aspect)
    if fov is not None:
        config["fov"] = round(min(120.0, max(10.0, fov)), 2)
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


def build_scene_meta(object_count: int, triangle_count: int, material_count: int,
                     texture_count: int, has_animation: bool) -> Dict[str, Any]:
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
    detail: str = ""  # untranslated template
    detail_args: Dict[str, Any] = field(default_factory=dict)
    progress: float = 0.0
    error: str = ""  # untranslated template (server text arrives as "{message}")
    error_args: Dict[str, Any] = field(default_factory=dict)
    warning: str = ""  # export warning (what glTF could not carry), English

    @property
    def detail_text(self) -> str:
        return format_message(self.detail, self.detail_args)

    @property
    def error_text(self) -> str:
        return format_message(self.error, self.error_args)


@dataclass
class PublishResult:
    scene_id: str = ""
    slug: str = ""
    share_url: str = ""
    viewer_url: str = ""
    revision: int = 0


@dataclass
class PublishJob:
    """Everything the worker thread needs; built on the main thread."""

    title: str
    description: str
    visibility: str
    glb_path: str
    thumbnail_path: str
    content_sha256: str
    scene_meta: Dict[str, Any] = field(default_factory=dict)
    viewer_config: Dict[str, Any] = field(default_factory=dict)
    # Update path: publish a new revision of an existing scene (slug kept)
    existing_scene_id: str = ""
    existing_slug: str = ""


class PublishState:
    """Mutex-guarded state shared between the worker thread and the UI timer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = PublishProgress()
        self._result = PublishResult()
        self._publish_id = ""
        self._scene_name = ""
        self._via = ""
        self._token: Optional[int] = None
        self._cancel_requested = False
        self._applied = False
        self._finished_monotonic = 0.0
        self._records: Dict[str, Tuple[PublishProgress, PublishResult]] = {}

    # -- lifecycle ------------------------------------------------------------

    def begin(self, publish_id: str = "", scene_name: str = "", via: str = "", *,
              token: Optional[int] = None) -> bool:
        """Claim the single publish slot; False while another publish runs.

        Taken BEFORE the export and reused by the worker hand-off: a second
        busy check after the export aborted every #1360 publish, and
        re-claiming would wipe a cancel requested during the export.
        ``token`` is the file-load generation the outcome belongs to."""
        with self._lock:
            if self._progress.status in BUSY_STATUSES:
                return False
            self._progress = PublishProgress(status=STATUS_EXPORTING)
            self._result = PublishResult()
            self._publish_id = publish_id
            self._scene_name = scene_name
            self._via = via
            self._token = token
            self._cancel_requested = False
            self._applied = False
            self._finished_monotonic = 0.0
            return True

    claim = begin  # #1372's name

    def start(self) -> None:
        """Unconditional ``begin`` without an id (tests, legacy callers)."""
        with self._lock:
            self._progress = PublishProgress(status=STATUS_EXPORTING)
            self._result = PublishResult()
            self._cancel_requested = False
            self._applied = False

    # -- worker-side writers ----------------------------------------------------

    # Template helpers take their fixed arguments positional-only: template
    # parameters such as {message} must never collide with them (``detail``
    # and ``progress`` stay keywords — never name a template field so).
    def set_status(self, status: str, /, detail: Optional[str] = None,
                   progress: Optional[float] = None, **args) -> None:
        with self._lock:
            if self._progress.status in TERMINAL_STATUSES and status not in TERMINAL_STATUSES:
                return  # never resurrect a finished publish
            self._progress.status = status
            if detail is not None:
                self._progress.detail = detail
                self._progress.detail_args = dict(args)
            if progress is not None:
                self._progress.progress = _clamp01(progress)

    def set_upload_progress(self, uploaded_bytes: int, total_bytes: int) -> None:
        fraction = _clamp01(uploaded_bytes / total_bytes) if total_bytes > 0 else 0.0
        with self._lock:
            if self._progress.status in TERMINAL_STATUSES:
                return
            self._progress.status = STATUS_UPLOADING
            self._progress.progress = fraction

    def set_warning(self, warning: str) -> None:
        with self._lock:
            self._progress.warning = str(warning or "")

    def set_error(self, template: str, /, **args) -> None:
        self._finish(STATUS_ERROR, error=template, error_args=args)

    def set_cancelled(self) -> None:
        self._finish(STATUS_CANCELLED, error="Publish cancelled", error_args={})

    def set_result(self, result: PublishResult, detail: str = "", /, **args) -> None:
        self._finish(STATUS_DONE, result, detail=detail, detail_args=args, progress=1.0)

    def _finish(self, status: str, result: Optional[PublishResult] = None, /,
                **changes) -> None:
        with self._lock:
            self._progress = replace(self._progress, status=status, **changes)
            if result is not None:
                self._result = replace(result)
            self._finished_monotonic = time.monotonic()
            if self._publish_id:
                self._records[self._publish_id] = (replace(self._progress), replace(self._result))
                while len(self._records) > _RECORD_LIMIT:
                    self._records.pop(next(iter(self._records)))

    def request_cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True

    # -- readers --------------------------------------------------------------

    def snapshot(self) -> Tuple[PublishProgress, PublishResult]:
        with self._lock:
            return replace(self._progress, detail_args=dict(self._progress.detail_args),
                           error_args=dict(self._progress.error_args)), replace(self._result)

    def lookup(self, publish_id: str) -> Optional[Tuple[PublishProgress, PublishResult]]:
        """The live state when ``publish_id`` is current, else its terminal record."""
        with self._lock:
            if (publish_id and publish_id == self._publish_id
                    and self._progress.status != STATUS_IDLE):
                return replace(self._progress), replace(self._result)
            record = self._records.get(publish_id)
            return (replace(record[0]), replace(record[1])) if record else None

    @property
    def publish_id(self) -> str:
        with self._lock:
            return self._publish_id

    @property
    def scene_name(self) -> str:
        with self._lock:
            return self._scene_name

    @property
    def via(self) -> str:
        with self._lock:
            return self._via

    @property
    def token(self) -> Optional[int]:
        with self._lock:
            return self._token

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._progress.status in BUSY_STATUSES

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def mark_applied(self) -> bool:
        """True exactly once per terminal outcome (the timer's mirror guard)."""
        with self._lock:
            if self._applied or self._progress.status not in TERMINAL_STATUSES:
                return False
            self._applied = True
            return True

    def reset(self) -> None:
        """Dismiss the terminal outcome in the panel (records survive)."""
        with self._lock:
            if self._progress.status in BUSY_STATUSES:
                return
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


# Process-wide state: one publish at a time (``begin`` refuses a second).
_state = PublishState()


def get_publish_state() -> PublishState:
    return _state
