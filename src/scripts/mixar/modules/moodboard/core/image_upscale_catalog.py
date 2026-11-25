# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read the Image Upscale input contract from the backend generation catalog.

Image Upscale (Topaz on fal) takes ONE Moodboard still and returns a larger
one. The source limits — file size, source and output megapixels, and the
upload ``purpose`` that stages it — are published on the ``image_upscale``
service's ``input_spec`` and read here at runtime, so limits and error text
follow the catalog row with no app release. Catalog-only: a missing or
malformed field fails closed instead of guessing.

The backend is authoritative (it measures the staged file, refuses an output
past the cap and prices by output megapixels); the checks here only refuse
early, before an upload, with an actionable message.

Deliberately ``bpy``-free so the standalone suite exercises it directly.
"""

import math

from mixar.modules.common.i18n import rpt_

CAPABILITY_KEY = "image_upscale"
SERVICE_KEY = "image_upscale"
#: Fallback for a catalog row that predates ``upload_purpose``.
DEFAULT_UPLOAD_PURPOSE = "image_upscale"
#: Payload field the backend reads the staged source from.
IMAGE_KEY_FIELD = "image_s3_key"
#: The catalog's factor parameter; read to check the output cap up front.
FACTOR_PARAM = "upscale_factor"
DEFAULT_FACTOR = 2.0


def get_image_upscale_limits(service_key=SERVICE_KEY):
    """Return the normalized source limits, or ``None`` for invalid config."""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_service

        service = get_service(service_key) or {}
        inputs = (service.get("input_spec") or {}).get("inputs") or []
        image_spec = next(
            item for item in inputs
            if item.get("kind") == "image" and not item.get("multiple")
        )
        limits = {
            "max_bytes": int(float(image_spec["max_size_mb"]) * 1024 * 1024),
            "max_pixels": int(image_spec["max_pixels"]),
            "max_output_pixels": int(image_spec["max_output_pixels"]),
            "upload_purpose": str(
                image_spec.get("upload_purpose") or DEFAULT_UPLOAD_PURPOSE
            ),
        }
    except Exception:
        return None
    if min(limits["max_bytes"], limits["max_pixels"], limits["max_output_pixels"]) <= 0:
        return None
    return limits


def output_size(width: int, height: int, factor: float) -> tuple[int, int]:
    """Upper bound on the upscaled size (edges rounded up, as the server does)."""
    return int(math.ceil(width * factor)), int(math.ceil(height * factor))


def max_factor_for(width: int, height: int, max_output_pixels: int) -> float:
    """Largest factor (one decimal, at least 1) whose output fits the cap; 0 if none."""
    if width <= 0 or height <= 0:
        return 0.0
    factor = math.floor(math.sqrt(max_output_pixels / float(width * height)) * 10) / 10
    while factor >= 1.0:
        out_w, out_h = output_size(width, height, factor)
        if out_w * out_h <= max_output_pixels:
            return min(factor, 4.0)
        factor = round(factor - 0.1, 1)
    return 0.0


def _megapixels(pixels: int) -> str:
    """``96`` for 96,000,000; ``0.5`` for a sub-megapixel cap (never ``0``)."""
    return f"{round(pixels / 1_000_000, 1):g}"


def image_upscale_source_error(width: int, height: int, factor, limits: dict):
    """Why this source cannot be upscaled by ``factor``, or ``None``."""
    if width <= 0 or height <= 0:
        return rpt_("The image has no pixels to upscale")
    if width * height > limits["max_pixels"]:
        return rpt_(
            "The image is {width}x{height}; Image Upscale takes images up to "
            "{megapixels} megapixels"
        ).format(width=width, height=height,
                 megapixels=_megapixels(limits["max_pixels"]))
    try:
        factor = float(factor if factor is not None else DEFAULT_FACTOR)
    except (TypeError, ValueError):
        factor = DEFAULT_FACTOR
    out_w, out_h = output_size(width, height, factor)
    if out_w * out_h > limits["max_output_pixels"]:
        best = max_factor_for(width, height, limits["max_output_pixels"])
        return rpt_(
            "Upscaling {width}x{height} by {factor}x would pass the {megapixels} "
            "megapixel output limit; use a factor of {best}x or less"
        ).format(width=width, height=height, factor=f"{factor:g}",
                 megapixels=_megapixels(limits["max_output_pixels"]),
                 best=f"{best:g}")
    return None
