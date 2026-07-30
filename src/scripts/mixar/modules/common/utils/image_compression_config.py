# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Centralized Image Compression Configuration

Per-service compression settings for moodboard image uploads.
Each service entry maps a service name to its max_dimension and quality.
Adjust these values to tune compression per feature without touching operator code.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class CompressionSettings:
    """Compression settings for a single upload service."""

    max_dimension: int
    """Longest edge (px) the image is resized to before upload. 0 = no resize."""

    quality: int
    """JPEG quality (1-95). Higher = better quality, larger file size."""


# ---------------------------------------------------------------------------
# Default fallback – used when a service name is not found in SERVICE_SETTINGS
# ---------------------------------------------------------------------------
DEFAULT_COMPRESSION = CompressionSettings(max_dimension=2048, quality=85)

# ---------------------------------------------------------------------------
# Per-service compression settings
# Keys must match the service names used when calling compress_for_service().
# ---------------------------------------------------------------------------
SERVICE_SETTINGS: Dict[str, CompressionSettings] = {
    # AI image generation – reference images sent alongside text prompts.
    # Moderate resolution is sufficient; the model down-samples internally.
    "imagegen": CompressionSettings(max_dimension=2048, quality=85),

    # Blockout-to-Render (Lookdev) – depth map rendered from the 3D scene.
    # Depth fidelity matters more than colour, keep resolution higher.
    "lookdev": CompressionSettings(max_dimension=2048, quality=90),

    # Lookdev 360 – reference / style image for PBR texture generation.
    # Style transfer works well at moderate resolution.
    "lookdev360": CompressionSettings(max_dimension=1024, quality=85),

    # Image-to-3D – single input image for mesh reconstruction.
    # Higher resolution preserves geometry detail for the reconstruction model.
    "image_to_3d": CompressionSettings(max_dimension=2048, quality=90),

    # Turnaround detection – a model sheet that the backend SPLITS into
    # per-view crops. Each crop is only a fraction of the sheet, so the
    # upload resolution divides down into the actual 3D input: at 2048 a
    # four-panel sheet yields ~500 px views, at 4096 it yields ~1000 px.
    # 4096 / 20 MB is the backend's hard ceiling (core/validators.py) —
    # do not raise it, larger uploads are rejected outright. The extra
    # pixels cost nothing at detection time (the backend downscales its
    # own copy to 1024 to find the panels, then crops the full-resolution
    # original), so they go entirely into panel quality.
    "turnaround_detect": CompressionSettings(max_dimension=4096, quality=92),

    # Scene Segment (SAM / Magic Select) – image uploaded for segmentation.
    # SAM works well at ≤2048 px; quality can be slightly lower.
    "scene_segment": CompressionSettings(max_dimension=2048, quality=85),
}


def get_compression_settings(service: str) -> CompressionSettings:
    """Return the :class:`CompressionSettings` for *service*.

    Falls back to :data:`DEFAULT_COMPRESSION` for unknown service names so
    that callers never need to handle a missing key.

    Args:
        service: A key from :data:`SERVICE_SETTINGS`, e.g. ``"imagegen"``.

    Returns:
        The matching :class:`CompressionSettings` instance.
    """
    return SERVICE_SETTINGS.get(service, DEFAULT_COMPRESSION)
