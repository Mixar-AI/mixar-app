# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read the Video Gen input contract from the backend generation catalog."""

import os


def get_video_generation_limits(service_key):
    """Return normalized reference limits, or ``None`` for invalid config.

    Video Gen is catalog-only, so accepting guessed client defaults would let
    the UI disagree with the DB seed and provider validator. Missing or
    malformed catalog fields therefore fail closed.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_service

        service = get_service(service_key) or {}
        spec = service.get("input_spec") or {}
        inputs = spec.get("inputs") or []
        image_spec = next(
            item for item in inputs
            if item.get("kind") == "image" and item.get("multiple")
        )
        video_spec = next(
            item for item in inputs
            if item.get("kind") == "video" and item.get("multiple")
        )
        # fal's image ceiling is 30 MB. Older catalog rows omit max_size_mb
        # on the image input; keep that floor so a 16–30 MB still is not
        # staged only to 503 in the content screen.
        image_max_mb = image_spec.get("max_size_mb")
        limits = {
            "max_images": int(image_spec["max_count"]),
            "max_videos": int(video_spec["max_count"]),
            "max_materials": int(spec["max_materials"]),
            "max_video_seconds": float(
                video_spec["max_total_duration_seconds"]
            ),
            "max_video_bytes": int(float(video_spec["max_size_mb"]) * 1024 * 1024),
            "max_image_bytes": int(
                float(30 if image_max_mb is None else image_max_mb) * 1024 * 1024
            ),
            "video_extensions": tuple(
                str(extension).lower()
                for extension in video_spec["extensions"]
            ),
        }
    except Exception:
        return None

    numeric_keys = (
        "max_images",
        "max_videos",
        "max_materials",
        "max_video_seconds",
        "max_video_bytes",
        "max_image_bytes",
    )
    if any(limits[key] <= 0 for key in numeric_keys):
        return None
    if not limits["video_extensions"]:
        return None
    return limits


_FRAME_IMAGE_MODES = frozenset({"first_frame", "first_last_frame"})


def seedance_reference_count_error(
    limits, *, image_count, video_count, image_mode="",
):
    """Human-readable reason the Seedance reference set is unusable, or None."""
    image_mode = str(image_mode or "")
    if image_mode in _FRAME_IMAGE_MODES:
        wanted = 1 if image_mode == "first_frame" else 2
        frames = "one image" if wanted == 1 else "exactly two images"
        if image_count != wanted:
            return (
                f"Image mode {image_mode!r} uses {frames} "
                f"(got {image_count})"
            )
        if video_count:
            return (
                "Video references are not supported in first/last-frame "
                "image modes"
            )
        return None
    if image_count > limits["max_images"]:
        return f"Select at most {limits['max_images']} images"
    if video_count > limits["max_videos"]:
        return f"Select at most {limits['max_videos']} videos"
    if image_count + video_count > limits["max_materials"]:
        return f"Select at most {limits['max_materials']} reference materials"
    return None


def build_video_reference_inputs(videos, limits) -> list[dict]:
    """Validate and shape streamed movie references, or raise ValueError.

    One definition for BOTH submit paths (node graph and sidebar drawer): a
    second copy of these checks diverged once already (different error text,
    one path silently accepting a different image-fallback label). Movies
    stream from ``filepath`` at upload time, so only path/size/extension are
    resolved here — never the bytes.
    """
    inputs = []
    for video in videos:
        if video["file_size_bytes"] > limits["max_video_bytes"]:
            raise ValueError(f"Video is too large: {video['filename']}")
        extension = os.path.splitext(video["filename"])[1].lower()
        if extension not in limits["video_extensions"]:
            raise ValueError(f"Unsupported video reference: {video['filename']}")
        inputs.append({
            "filename": video["filename"],
            "mime_type": video["mime_type"],
            "filepath": video["resolved_filepath"],
            "file_size_bytes": video["file_size_bytes"],
        })
    return inputs


def build_image_reference_inputs(images, limits, compress) -> list[dict]:
    """Compress and validate still references into upload-ready dicts.

    *compress* is injected (``compress_for_service``) so this stays pure: no
    bpy, no PIL, and the byte cap is exercised by the standalone suite.
    """
    inputs = []
    for index, item in enumerate(images):
        payload = compress(item["image"], "video_gen")
        if len(payload) > limits["max_image_bytes"]:
            raise ValueError(
                "Image is too large after compression: "
                f"{item.get('filename') or item.get('image_name') or 'reference'}"
            )
        inputs.append({
            "filename": f"reference_{index + 1}.jpg",
            "mime_type": "image/jpeg",
            "bytes": payload,
        })
    return inputs
