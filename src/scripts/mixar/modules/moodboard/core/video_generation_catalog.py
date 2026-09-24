# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read the Video Gen input contract from the backend generation catalog.

``video_gen`` serves more than one model and they do NOT share reference
ceilings: Seedance 2.5 takes 30 images / 10 videos / 50 materials / 30.2 s,
the MiniMax H3 family takes 9 / 3 / 12 / 15 s. ``input_spec`` is SERVICE-level
and describes the wider set, so a model that has its own ceilings publishes
them on its catalog row as ``reference_limits`` and they are merged over the
service spec here. A model that publishes none keeps the service's — which is
exactly the behaviour every model had before the field existed.

Getting this wrong is not cosmetic: the submit operators compress and upload
every selected reference BEFORE the backend sees the payload, so a cap that is
too generous costs the user the whole upload and then fails.
"""

import os


def get_video_generation_limits(service_key, model_slug=""):
    """Return normalized reference limits, or ``None`` for invalid config.

    Video Gen is catalog-only, so accepting guessed client defaults would let
    the UI disagree with the DB seed and provider validator. Missing or
    malformed catalog fields therefore fail closed.

    *model_slug* is optional only so an existing caller cannot break; pass it
    wherever the model is known, or the limits are the service's widest.
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
    return _apply_model_limits(limits, service_key, model_slug)


#: Catalog ``reference_limits`` key -> the key it narrows in the service spec.
#: Only these four are caps the client enforces before upload; the per-clip
#: duration bounds the backend stamps into the staged key are not re-derived
#: here (the uploader measures the file, we never do).
_MODEL_LIMIT_KEYS = {
    "max_images": "max_images",
    "max_videos": "max_videos",
    "max_materials": "max_materials",
    "max_video_seconds": "max_video_seconds",
}


def selected_video_model_slug(scene, service_key="video_gen"):
    """Resolved model slug for the Video Gen tab's current selection, or "".

    One definition so the drawer, the submit operator and the Director handoff
    all read the limits of the SAME model. Best effort: anything missing
    (no sidebar, pre-catalog startup) returns "" and the caller falls back to
    the service-level spec.
    """
    try:
        from mixar.modules.common.generation_params import resolve_model_slug

        sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
        tab = getattr(sidebar, "tab_video_gen", None) if sidebar else None
        return resolve_model_slug(service_key, getattr(tab, "model", "")) or ""
    except Exception:
        return ""


def _apply_model_limits(limits, service_key, model_slug):
    """Narrow *limits* by the selected model's own published ceilings.

    Only ever narrows. A model row that publishes a LARGER value than the
    service spec is ignored rather than trusted: the service's ``input_spec``
    is what the upload endpoint itself validates against, so widening here
    would move the rejection from the client to a charged job.
    """
    if not model_slug:
        return limits
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model

        model = get_model(service_key, model_slug) or {}
    except Exception:
        return limits
    model_limits = model.get("reference_limits") or {}
    if not isinstance(model_limits, dict):
        return limits
    for source, target in _MODEL_LIMIT_KEYS.items():
        value = model_limits.get(source)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if 0 < value < limits[target]:
            limits[target] = type(limits[target])(value)
    return limits


_FRAME_IMAGE_MODES = frozenset({"first_frame", "first_last_frame"})


def video_reference_count_error(
    limits, *, image_count, video_count, image_mode="",
):
    """Human-readable reason the reference set is unusable, or None.

    Model-neutral: *limits* has already been narrowed to the selected model
    by ``get_video_generation_limits``, so the same rules serve Seedance and
    the MiniMax H3 tiers.
    """
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
