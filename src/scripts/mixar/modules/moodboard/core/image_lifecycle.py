# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard image lifecycle helpers.

Loaded moodboard images are packed into the session (raw RGBA bytes),
so detaching the PointerProperty alone leaves the datablock alive in
``bpy.data.images`` for the rest of the Blender session. These helpers
explicitly release every image datablock a moodboard entry owns.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def remove_image_safely(image: bpy.types.Image | None) -> None:
    """Remove ``image`` from ``bpy.data.images`` if no one else references it.

    Safe to call with ``None`` or with images already shared by other users
    (e.g. an image still bound to a material). When ``users > 1`` the
    datablock is left alone.
    """
    if image is None:
        return
    try:
        # ``users`` counts both the property holder and any other refs.
        # Treat ``<= 1`` as "only this caller is holding it".
        if image.users <= 1:
            bpy.data.images.remove(image, do_unlink=True)
    except (ReferenceError, RuntimeError) as exc:
        # ReferenceError: datablock already freed.
        # RuntimeError: image not in bpy.data.images (e.g. removed via undo).
        logger.debug("remove_image_safely: %s", exc)


def release_moodboard_image_entry(item) -> None:
    """Release every image datablock owned by a ``MixieMoodboardImage`` entry.

    Frees:
      * ``item.image`` (the source/reference image)
      * ``item.display_image`` (Magic-Select overlay cache)
      * ``item.compressed_image`` (SAM upload cache)
      * ``item.segments[*].mask_image`` (per-segment binary masks)
    """
    if item is None:
        return
    try:
        for seg in getattr(item, "segments", []) or []:
            remove_image_safely(getattr(seg, "mask_image", None))
        remove_image_safely(getattr(item, "compressed_image", None))
        remove_image_safely(getattr(item, "display_image", None))
        remove_image_safely(getattr(item, "image", None))
    except ReferenceError:
        pass


def release_all_moodboard_images(scene: bpy.types.Scene | None) -> int:
    """Release every image datablock owned by every entry in ``scene``.

    Returns the number of entries processed. Caller is responsible for
    ``scene.mixie_moodboard_images.clear()`` afterwards.
    """
    if scene is None:
        return 0
    coll = getattr(scene, "mixie_moodboard_images", None)
    if coll is None:
        return 0
    count = 0
    for item in list(coll):
        release_moodboard_image_entry(item)
        count += 1
    return count
