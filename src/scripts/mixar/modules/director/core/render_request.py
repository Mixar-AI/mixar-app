# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure readiness rules for the camera-first Export to Moodboard surface.

Director shots carry their own camera, beats and render span. A power user who
keyframed a camera through the native timeline has none of those, so this
module answers the same questions from the scene alone: WHICH camera, over
WHICH frames, and — when the answer is "we cannot render yet" — exactly WHY,
in one sentence the surface can show.

Deliberately ``bpy``-free so every branch is unit-testable outside Blender.
"""

from __future__ import annotations

from dataclasses import dataclass

from .render_spec import ordered_render_kinds, render_duration_seconds


# The reason strings below are user-facing copy. They name the blocker and,
# where there is one, the next action — never a bare "unavailable".
REASON_NO_CAMERA = "No camera in this scene"
REASON_NO_KEYS = "'{name}' has no camera keyframes yet"
REASON_ONE_KEY = "'{name}' has only one keyframe — animate at least two"
REASON_EMPTY_RANGE = "The {label} is empty — set a start and end frame"
REASON_NO_KINDS = "Select at least one video: Beauty, Clay or Depth"
REASON_BUSY = "A render is already running"

_RANGE_LABELS = {
    "CAMERA_KEYS": "camera key range",
    "SCENE": "scene frame range",
    "PREVIEW": "preview range",
}


@dataclass(frozen=True)
class CameraExportPlan:
    """Everything the surface needs to draw itself and to start a render."""

    ok: bool
    reason: str = ""
    frame_start: int = 0
    frame_end: int = 0
    key_count: int = 0
    kinds: tuple[str, ...] = ()

    @property
    def frame_count(self) -> int:
        return max(0, self.frame_end - self.frame_start + 1)


def _is_camera(obj) -> bool:
    return getattr(obj, "type", None) == 'CAMERA'


def resolve_export_camera(scene, *, override=None, active=None, selected=()):
    """Pick the camera this export is about.

    Selection wins over the scene camera on purpose: a user with three cameras
    is asking about the one they are looking at. An explicit override always
    wins, so the surface's camera field is never overruled by a stray click.
    """
    for candidate in (override, active):
        if _is_camera(candidate):
            return candidate
    for candidate in selected:
        if _is_camera(candidate):
            return candidate
    scene_camera = getattr(scene, "camera", None)
    if _is_camera(scene_camera):
        return scene_camera
    cameras = [obj for obj in getattr(scene, "objects", ()) if _is_camera(obj)]
    if len(cameras) == 1:
        return cameras[0]
    return None


def resolve_frame_range(scene, key_frames, source: str) -> tuple[int, int]:
    """The inclusive render span for *source*, unvalidated.

    ``PREVIEW`` falls back to the scene range when no preview range is set,
    which is what the Timeline itself shows in that state.
    """
    if source == "CAMERA_KEYS":
        ordered = sorted({int(frame) for frame in key_frames})
        if not ordered:
            return 0, 0
        return ordered[0], ordered[-1]
    if source == "PREVIEW" and bool(getattr(scene, "use_preview_range", False)):
        return (
            int(scene.frame_preview_start),
            int(scene.frame_preview_end),
        )
    return int(scene.frame_start), int(scene.frame_end)


def build_export_plan(
    scene,
    camera,
    key_frames,
    kinds,
    *,
    range_source: str = "CAMERA_KEYS",
    render_busy: bool = False,
) -> CameraExportPlan:
    """Resolve the camera export into a start-able plan or a stated blocker.

    The checks run in the order the user would fix them, and each one stops at
    the FIRST unmet condition — naming two problems at once reads as noise
    when solving the first may resolve the second.
    """
    frames = sorted({int(frame) for frame in key_frames})
    key_count = len(frames)
    ordered_kinds = ordered_render_kinds(kinds)

    if camera is None:
        return CameraExportPlan(False, REASON_NO_CAMERA, kinds=ordered_kinds)

    name = getattr(camera, "name", "Camera")
    # Keyframes are required for EVERY range source: a still camera rendered
    # over the scene range is a video of nothing moving, which is never what
    # this export is for.
    if key_count == 0:
        return CameraExportPlan(
            False, REASON_NO_KEYS.format(name=name), kinds=ordered_kinds
        )
    if key_count == 1:
        return CameraExportPlan(
            False,
            REASON_ONE_KEY.format(name=name),
            frame_start=frames[0],
            frame_end=frames[0],
            key_count=1,
            kinds=ordered_kinds,
        )

    frame_start, frame_end = resolve_frame_range(scene, frames, range_source)
    if frame_end <= frame_start:
        label = _RANGE_LABELS.get(range_source, "frame range")
        return CameraExportPlan(
            False,
            REASON_EMPTY_RANGE.format(label=label),
            frame_start=frame_start,
            frame_end=frame_end,
            key_count=key_count,
            kinds=ordered_kinds,
        )

    common = {
        "frame_start": frame_start,
        "frame_end": frame_end,
        "key_count": key_count,
        "kinds": ordered_kinds,
    }
    if not ordered_kinds:
        return CameraExportPlan(False, REASON_NO_KINDS, **common)
    if render_busy:
        return CameraExportPlan(False, REASON_BUSY, **common)
    return CameraExportPlan(True, "", **common)


def describe_range(plan: CameraExportPlan, fps: float, fps_base: float = 1.0) -> str:
    """One line summarising the span, e.g. ``1 – 240 · 10.0s``."""
    if plan.frame_end <= plan.frame_start:
        return ""
    seconds = render_duration_seconds(
        plan.frame_start, plan.frame_end, fps, fps_base
    )
    return f"{plan.frame_start} – {plan.frame_end} · {seconds:.1f}s"
