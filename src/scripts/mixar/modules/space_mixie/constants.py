# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Space Mixie Module Constants

Centralized configuration values for the Mixie space module.
"""

# =============================================================================
# ImageGen Constants (Fallback values if cache not available)
# =============================================================================

# Maximum reference images per model (fallback values)
IMAGEGEN_MAX_REFS_FLASH = 3
IMAGEGEN_MAX_REFS_PRO = 14


def get_imagegen_max_refs(model: str) -> int:
    """
    Get the maximum reference images for a given model.

    Uses cached model data if available, otherwise falls back to hardcoded values.
    """
    try:
        from mixar.bootstrap.imagegen_cache import get_max_reference_images

        return get_max_reference_images(model)
    except ImportError:
        # Fallback to hardcoded values
        return IMAGEGEN_MAX_REFS_PRO if model == "pro" else IMAGEGEN_MAX_REFS_FLASH
