# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read the Video Gen input contract from the backend generation catalog."""


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
        limits = {
            "max_images": int(image_spec["max_count"]),
            "max_videos": int(video_spec["max_count"]),
            "max_materials": int(spec["max_materials"]),
            "max_video_seconds": float(
                video_spec["max_total_duration_seconds"]
            ),
            "max_video_bytes": int(float(video_spec["max_size_mb"]) * 1024 * 1024),
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
    )
    if any(limits[key] <= 0 for key in numeric_keys):
        return None
    if not limits["video_extensions"]:
        return None
    return limits
