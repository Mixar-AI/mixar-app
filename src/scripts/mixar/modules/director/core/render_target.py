# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a guide render is FOR: a Director shot, or a plain animated camera.

`render_outputs` runs one multi-pass job; these adapters are the only place
that knows whose camera it is, where the progress goes, and what the resulting
movie is called. Everything the passes need is FROZEN at start — a render that
re-read its span from live beats would shift under a Dope Sheet edit made
while it runs.

The job survives across timers and render handlers, so a target is stored as a
small serialisable ``ref`` dict and re-resolved through `resolve_target` on
every callback rather than held as a Python reference to RNA.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RenderTarget:
    """A frozen render span plus the live RNA that shows its progress."""

    camera: object
    frame_start: int
    frame_end: int
    kinds: tuple[str, ...]
    resolution_percentage: int
    display_prefix: str
    prompt: str = ""
    _status_owner: object = field(default=None, repr=False)

    def set_status(self, *, running=None, progress=None, status=None) -> None:
        owner = self._status_owner
        if owner is None:
            return
        if running is not None:
            owner.render_is_running = bool(running)
        if progress is not None:
            owner.render_progress = float(progress)
        if status is not None:
            owner.render_status = str(status)

    def display_name(self, label: str) -> str:
        return f"{self.display_prefix} · {label}"

    def record_output(self, kind: str, image, rendered_at: str) -> None:
        """Keep a per-target record of the movie. Cameras keep none."""


@dataclass
class ShotRenderTarget(RenderTarget):
    """A Director shot: progress on the shot, movies in `render_outputs`."""

    shot: object = None

    def record_output(self, kind: str, image, rendered_at: str) -> None:
        import uuid

        output = self.shot.render_outputs.add()
        output.output_id = uuid.uuid4().hex
        output.kind = kind
        output.image = image
        output.rendered_at = rendered_at


def shot_target(shot, frame_start: int, frame_end: int, kinds) -> ShotRenderTarget:
    prompt = getattr(shot, "prompt", "") or ""
    return ShotRenderTarget(
        camera=shot.camera,
        frame_start=frame_start,
        frame_end=frame_end,
        kinds=tuple(kinds),
        resolution_percentage=int(shot.render_resolution_percentage),
        display_prefix=f"{shot.name} T{shot.version:02d}",
        prompt=prompt,
        _status_owner=shot,
        shot=shot,
    )


def camera_target(settings, camera, plan) -> RenderTarget:
    """A natively animated camera. The moodboard IS the record of the run."""
    return RenderTarget(
        camera=camera,
        frame_start=plan.frame_start,
        frame_end=plan.frame_end,
        kinds=tuple(plan.kinds),
        resolution_percentage=int(settings.render_resolution_percentage),
        display_prefix=camera.name,
        _status_owner=settings,
    )


def target_ref(target: RenderTarget) -> dict:
    """A serialisable handle the running job can re-resolve on each callback."""
    ref = {
        "kind": "SHOT" if isinstance(target, ShotRenderTarget) else "CAMERA",
        "camera_name": getattr(target.camera, "name", ""),
        "frame_start": target.frame_start,
        "frame_end": target.frame_end,
        "kinds": tuple(target.kinds),
        "resolution_percentage": target.resolution_percentage,
        "display_prefix": target.display_prefix,
        "prompt": target.prompt,
    }
    if ref["kind"] == "SHOT":
        ref["shot_id"] = target.shot.shot_id
    return ref


def resolve_status_owner(scene, ref: dict):
    """The RNA carrying *ref*'s progress, even when its camera is gone.

    ``resolve_target`` needs the camera to rebuild a full target; the status
    owner does not — a shot is found by id and the camera-export settings
    live on the scene — so a finished job can always put "running" down.
    """
    if ref.get("kind") == "SHOT":
        state = getattr(scene, "mixar_director", None)
        if state is None:
            return None
        return next((s for s in state.shots if s.shot_id == ref.get("shot_id")), None)
    return getattr(scene, "mixar_camera_export", None)


def resolve_target(scene, ref: dict):
    """Rebuild the target from *ref*, or ``None`` if what it named is gone."""
    import bpy

    camera = bpy.data.objects.get(ref.get("camera_name", ""))
    if camera is None or camera.type != 'CAMERA':
        return None
    common = {
        "camera": camera,
        "frame_start": ref["frame_start"],
        "frame_end": ref["frame_end"],
        "kinds": tuple(ref["kinds"]),
        "resolution_percentage": ref["resolution_percentage"],
        "display_prefix": ref["display_prefix"],
        "prompt": ref.get("prompt", ""),
    }
    if ref.get("kind") == "SHOT":
        state = getattr(scene, "mixar_director", None)
        shot = None
        if state is not None:
            shot = next(
                (s for s in state.shots if s.shot_id == ref["shot_id"]), None
            )
        if shot is None:
            return None
        return ShotRenderTarget(_status_owner=shot, shot=shot, **common)
    settings = getattr(scene, "mixar_camera_export", None)
    return RenderTarget(_status_owner=settings, **common)
