# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread image preparation for Scene Segment uploads."""

import os
import tempfile

import bpy

from mixar.config.logging_config import get_logger
from ...common.utils.image_compression_config import get_compression_settings

logger = get_logger(__name__)


def compress_image_for_scene_segment(image: bpy.types.Image, img_item=None) -> bytes:
    """Return a resized JPEG and retain its exact uploaded dimensions.

    Blender image datablocks may point at deleted download temp files even
    though their pixels are packed. Packing the upload copy from its filepath
    therefore emits errors and can block file access. Supplying the encoded
    bytes directly keeps the cache independent of that stale source path.
    """
    settings = get_compression_settings("scene_segment")
    width, height = image.size
    max_dim = max(width, height)
    if max_dim > settings.max_dimension:
        scale = settings.max_dimension / max_dim
        new_width = int(width * scale)
        new_height = int(height * scale)
    else:
        new_width, new_height = width, height

    if img_item and img_item.compressed_image:
        try:
            old_compressed = img_item.compressed_image
            img_item.compressed_image = None
            bpy.data.images.remove(old_compressed)
        except Exception:
            pass

    compressed_image = image.copy()
    compressed_image.name = f"{image.name}_compressed"
    export_scene = bpy.data.scenes.new("_scene_segment_jpeg_export")
    fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix="_scene_segment_")
    os.close(fd)
    handed_off = False
    try:
        if (new_width, new_height) != (width, height):
            compressed_image.scale(new_width, new_height)
            logger.debug(
                "[SceneSegment] Resized %sx%s -> %sx%s",
                width, height, new_width, new_height,
            )

        # Image.save() can still preserve the source datablock's PNG encoding
        # despite a .jpg filepath. Give save_render() an isolated scene whose
        # output contract is explicitly JPEG so neither the payload MIME nor
        # the user's render settings can disagree with the bytes on disk.
        export_scene.render.image_settings.file_format = 'JPEG'
        export_scene.render.image_settings.quality = settings.quality
        compressed_image.save_render(temp_path, scene=export_scene)
        with open(temp_path, 'rb') as handle:
            compressed_bytes = handle.read()

        if img_item:
            compressed_image.pack(
                data=compressed_bytes,
                data_len=len(compressed_bytes),
            )
            compressed_image.filepath_raw = ""
            img_item.compressed_image = compressed_image
            handed_off = True

        logger.debug(
            "[SceneSegment] Compressed image: ~%sKB -> %sKB "
            "(max_dim=%s quality=%s)",
            width * height * 4 // 1024,
            len(compressed_bytes) // 1024,
            settings.max_dimension,
            settings.quality,
        )
        return compressed_bytes
    finally:
        if not handed_off:
            try:
                bpy.data.images.remove(compressed_image)
            except (RuntimeError, ReferenceError):
                pass
        bpy.data.scenes.remove(export_scene)
        try:
            os.unlink(temp_path)
        except OSError:
            pass
