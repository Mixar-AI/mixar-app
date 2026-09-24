# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read the Video Upscale input contract from the backend generation catalog.

Video Upscale (FLUX Video Upscale on fal) takes ONE moodboard movie and
returns an upscaled movie. Everything about that source clip — how long, how
big, how many pixels, which container, and which upload ``purpose`` stages it
— is published by the backend on the ``video_upscale`` service's
``input_spec`` and read here at runtime, so limits and error text follow the
catalog row with no plugin release. Like Video Gen this is catalog-only:
missing or malformed fields fail closed instead of guessing.

Deliberately ``bpy``-free so the standalone suite exercises it directly.
"""

import os

CAPABILITY_KEY = "video_upscale"
SERVICE_KEY = "video_upscale"
#: Query-param value the backend uploader expects for an upscale SOURCE clip
#: (``POST /job-queue/uploads/video?purpose=video_upscale``). The catalog row
#: publishes it too (``upload_purpose``); this is the fallback for a row that
#: predates the field.
DEFAULT_UPLOAD_PURPOSE = "video_upscale"


def get_video_upscale_limits(service_key=SERVICE_KEY):
    """Return the normalized source-clip limits, or ``None`` for invalid config.

    Reads the single required ``video`` input of the service's ``input_spec``.
    ``max_side_pixels`` / ``max_pixels`` are optional (an older row may omit
    them — the backend still enforces its own ceilings at upload); duration,
    size and extensions are required.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_service

        service = get_service(service_key) or {}
        spec = service.get("input_spec") or {}
        inputs = spec.get("inputs") or []
        video_spec = next(
            item for item in inputs
            if item.get("kind") == "video" and not item.get("multiple")
        )
        limits = {
            "max_seconds": float(video_spec["max_duration_seconds"]),
            "max_bytes": int(float(video_spec["max_size_mb"]) * 1024 * 1024),
            "max_side_pixels": _optional_positive_int(video_spec.get("max_side_pixels")),
            "max_pixels": _optional_positive_int(video_spec.get("max_pixels")),
            "video_extensions": tuple(
                str(extension).lower() for extension in video_spec["extensions"]
            ),
            "upload_purpose": str(
                video_spec.get("upload_purpose") or DEFAULT_UPLOAD_PURPOSE
            ),
            "prompt_optional": not any(
                item.get("kind") == "prompt" and item.get("required")
                for item in inputs
            ),
        }
    except Exception:
        return None

    if limits["max_seconds"] <= 0 or limits["max_bytes"] <= 0:
        return None
    if not limits["video_extensions"]:
        return None
    return limits


def _optional_positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def video_upscale_source_error(*, video_count):
    """Human-readable reason the selection is not ONE usable source, or None."""
    if video_count == 0:
        return "Select one video on the moodboard to upscale"
    if video_count > 1:
        return "Video Upscale takes one video at a time — select just one"
    return None


def build_video_upscale_input(video, limits) -> dict:
    """Validate and shape the ONE streamed source clip, or raise ValueError.

    One definition for BOTH submit paths (node graph and sidebar drawer), the
    same rule ``build_video_reference_inputs`` follows for Video Gen. Movies
    stream from ``filepath`` at upload time, so the bytes are never read
    here: size and extension come from the path, and the frame size Blender
    already knows (``describe_moodboard_media``) is checked against the
    catalog's pixel ceilings so an oversize clip is refused BEFORE a 50 MB
    upload the backend would only reject. The backend still measures the
    uploaded bytes itself (duration, frame size) and stamps them into the
    staged key — that measurement, not this one, is what prices the job.
    """
    if not video.get("source_available", True):
        raise ValueError(f"Video source was moved or deleted: {video['filename']}")
    if video["file_size_bytes"] > limits["max_bytes"]:
        raise ValueError(
            f"Video is too large to upscale ({limits['max_bytes'] // (1024 * 1024)} MB max): "
            f"{video['filename']}"
        )
    extension = os.path.splitext(video["filename"])[1].lower()
    if extension not in limits["video_extensions"]:
        raise ValueError(f"Unsupported video for upscaling: {video['filename']}")
    _check_frame_size(video, limits)
    return {
        "filename": video["filename"],
        "mime_type": video["mime_type"],
        "filepath": video["resolved_filepath"],
        "file_size_bytes": video["file_size_bytes"],
    }


def _check_frame_size(video, limits) -> None:
    """Refuse a source whose known frame size exceeds the catalog ceilings.

    An unknown size (0x0 — the movie has not been probed yet, or the caller
    passed a bare path) is allowed through: the backend measures the real
    container at upload and fails closed there.
    """
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        return
    max_side = limits.get("max_side_pixels")
    if max_side and max(width, height) > max_side:
        raise ValueError(
            f"Video frame is too large to upscale ({width}x{height}; "
            f"{max_side} px on the longest side max): {video['filename']}"
        )
    max_pixels = limits.get("max_pixels")
    if max_pixels and width * height > max_pixels:
        raise ValueError(
            f"Video frame is too large to upscale ({width}x{height}; "
            f"{max_pixels} pixels max): {video['filename']}"
        )


def describe_source_limits(limits) -> list[str]:
    """Short hint lines for the sidebar's "Source Limits" box."""
    lines = [
        f"Up to {limits['max_seconds']:g} seconds, "
        f"{limits['max_bytes'] // (1024 * 1024)} MB",
    ]
    if limits.get("max_side_pixels"):
        lines.append(f"Up to {limits['max_side_pixels']} px on the longest side")
    lines.append(
        "Formats: " + ", ".join(ext.lstrip(".").upper() for ext in limits["video_extensions"])
    )
    return lines
