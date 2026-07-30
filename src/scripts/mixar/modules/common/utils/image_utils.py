# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared Image Utility Functions

Common helper functions for image conversion and moodboard management,
shared across ImageGen, Lookdev, and other Mixar modules.

Use :func:`compress_for_service` as the preferred upload path – it reads
per-service compression settings from
:mod:`mixar.modules.common.utils.image_compression_config` so compression
behaviour can be tuned centrally without touching individual operators.
"""

import bpy
import base64
import os
import tempfile
from datetime import datetime, timezone

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# Layout constants for image placement
IMAGE_BASE_SIZE = 700.0  # Base size for moodboard images
IMAGE_SPACING = 50.0  # Gap between images


def _png_signature() -> bytes:
    return b'\x89PNG\r\n\x1a\n'


def image_to_png_bytes(image: bpy.types.Image) -> bytes:
    """Convert a Blender Image to PNG bytes."""
    import struct
    import zlib

    # Ensure image has pixels loaded
    if image.pixels is None or len(image.pixels) == 0:
        # Try to force pixel data to load (packed images may not be decoded yet).
        # Skip reload for generated images — they have no file source, and
        # reload() would destroy the in-memory pixel data.
        if image.source != 'GENERATED':
            try:
                image.reload()
            except Exception:
                pass

    if image.pixels is None or len(image.pixels) == 0:
        # Fall back to packed file data if available
        if image.packed_file and image.packed_file.data:
            packed_data = bytes(image.packed_file.data)
            if packed_data[:8] == _png_signature():
                return packed_data
        raise ValueError(f"Image '{image.name}' has no pixel data")

    # Get image dimensions
    width, height = image.size

    # Read + convert pixels with numpy via foreach_get. The previous
    # implementation copied image.pixels into a Python list and ran two
    # pure-Python per-pixel passes (float→byte conversion, then scanline
    # assembly) — multi-second UI freezes for 1K+ images on every chat /
    # brush-gen / moodboard upload. foreach_get is a single memcpy-style
    # bulk read; the conversion below matches the old int() truncation
    # semantics exactly.
    import numpy as np

    flat = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(flat)
    rgba = np.clip(flat * 255.0, 0.0, 255.0).astype(np.uint8)
    rgba = rgba.reshape(height, width * 4)

    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        crc = zlib.crc32(chunk) & 0xffffffff
        return struct.pack('>I', len(data)) + chunk + struct.pack('>I', crc)

    # PNG signature
    png_signature = b'\x89PNG\r\n\x1a\n'

    # IHDR chunk
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    ihdr_chunk = png_chunk(b'IHDR', ihdr_data)

    # IDAT chunk - raw scanlines, filter byte 0 (None) per row.
    # Blender stores rows bottom-to-top; PNG needs top-to-bottom.
    raw = np.zeros((height, 1 + width * 4), dtype=np.uint8)
    raw[:, 1:] = rgba[::-1]

    # Level 6 instead of 9: the payload is a network upload, and level 9
    # costs several times the CPU for a few percent smaller output.
    compressed = zlib.compress(raw.tobytes(), 6)
    idat_chunk = png_chunk(b'IDAT', compressed)

    # IEND chunk
    iend_chunk = png_chunk(b'IEND', b'')

    return png_signature + ihdr_chunk + idat_chunk + iend_chunk


# Upload compression constants
UPLOAD_MAX_DIMENSION = 2048
UPLOAD_JPEG_QUALITY = 85


def compress_image_for_upload(
    image: bpy.types.Image,
    max_dimension: int = UPLOAD_MAX_DIMENSION,
    quality: int = UPLOAD_JPEG_QUALITY,
) -> bytes:
    """Compress a Blender Image for API upload.

    Resizes to max_dimension on the longest side (maintaining aspect ratio)
    and converts to JPEG. Returns compressed JPEG bytes.
    """
    width, height = image.size
    if width == 0 or height == 0:
        raise ValueError(f"Image '{image.name}' has zero dimensions")

    # Calculate new dimensions preserving aspect ratio
    max_dim = max(width, height)
    if max_dim > max_dimension:
        scale = max_dimension / max_dim
        new_width = int(width * scale)
        new_height = int(height * scale)
    else:
        new_width, new_height = width, height

    # Two strategies depending on image source:
    # - Generated/in-memory images (e.g. cropped): read pixels directly to
    #   avoid image.copy() which shares internal buffers and corrupts original.
    # - File/packed images: use image.copy() + save_render() which is reliable
    #   for images loaded from disk.
    is_generated = (image.source == 'GENERATED')

    # Track every temp file we create so a failure between mkstemp and the
    # next try/finally cannot leak the path on disk. Track the temporary
    # Image datablock the same way — bpy.data.images.load can raise after
    # the file is written.
    src_path: str | None = None
    temp_path: str | None = None
    tmp_image = None
    try:
        if is_generated:
            png_bytes = image_to_png_bytes(image)
            fd, src_path = tempfile.mkstemp(suffix=".png", prefix="_mixar_src_")
            os.close(fd)
            with open(src_path, 'wb') as f:
                f.write(png_bytes)

            tmp_image = bpy.data.images.load(src_path, check_existing=False)
            tmp_image.name = f"_upload_tmp_{image.name}"
        else:
            tmp_image = image.copy()
            tmp_image.name = f"_upload_tmp_{image.name}"

        if new_width != width or new_height != height:
            tmp_image.scale(new_width, new_height)
            logger.debug(
                "[ImageUtils] Resized %s from %sx%s to %sx%s",
                image.name, width, height, new_width, new_height,
            )

        fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix="_mixar_upload_")
        os.close(fd)
        tmp_image.file_format = 'JPEG'
        tmp_image.save_render(temp_path)

        with open(temp_path, 'rb') as f:
            compressed_bytes = f.read()

        logger.info(
            "[ImageUtils] Compressed %s (source=%s): %sx%s -> %sKB",
            image.name, image.source, new_width, new_height,
            len(compressed_bytes) // 1024,
        )

        return compressed_bytes
    finally:
        if tmp_image is not None:
            try:
                bpy.data.images.remove(tmp_image)
            except (RuntimeError, ReferenceError):
                pass
        for path in (temp_path, src_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def compress_file_for_upload(
    file_path: str,
    max_dimension: int = UPLOAD_MAX_DIMENSION,
    quality: int = UPLOAD_JPEG_QUALITY,
) -> bytes:
    """Compress an image file for API upload.

    Loads the file, resizes to max_dimension on the longest side
    (maintaining aspect ratio), converts to JPEG, and returns bytes.
    """
    tmp_image = bpy.data.images.load(file_path, check_existing=False)
    try:
        return compress_image_for_upload(tmp_image, max_dimension, quality)
    finally:
        bpy.data.images.remove(tmp_image)


def compress_for_service(
    image: bpy.types.Image,
    service: str,
) -> bytes:
    """Compress a Blender Image using the per-service compression settings.

    This is the preferred entry-point for all moodboard upload paths.
    Compression parameters (resolution cap, JPEG quality) are looked up from
    :mod:`mixar.modules.common.utils.image_compression_config` so they can be
    adjusted centrally without modifying individual operators.

    Args:
        image:   The Blender image to compress.
        service: Service identifier key, e.g. ``"imagegen"``, ``"lookdev"``,
                 ``"lookdev360"``, ``"image_to_3d"``, ``"scene_segment"``.
                 Unknown keys fall back to :data:`DEFAULT_COMPRESSION`.

    Returns:
        JPEG-compressed bytes ready for API upload.
    """
    from mixar.modules.common.utils.image_compression_config import get_compression_settings
    settings = get_compression_settings(service)
    logger.debug("[ImageUtils] compress_for_service: service=%s max_dim=%s quality=%s",
                 service, settings.max_dimension, settings.quality)
    return compress_image_for_upload(image, settings.max_dimension, settings.quality)


def compress_file_for_service(
    file_path: str,
    service: str,
) -> bytes:
    """Compress an image file using the per-service compression settings.

    Convenience wrapper around :func:`compress_for_service` that loads the
    file into Blender first, then removes the temporary image after use.

    Args:
        file_path: Absolute path to the image file.
        service:   Service identifier key (see :func:`compress_for_service`).

    Returns:
        JPEG-compressed bytes ready for API upload.
    """
    tmp_image = bpy.data.images.load(file_path, check_existing=False)
    try:
        return compress_for_service(tmp_image, service)
    finally:
        bpy.data.images.remove(tmp_image)


def load_image_from_base64(data: str, name: str) -> bpy.types.Image:
    """Load a Blender Image from base64 encoded data."""
    # Decode base64
    image_bytes = base64.b64decode(data)

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(image_bytes)
        temp_path = f.name

    try:
        # Load into Blender
        img = bpy.data.images.load(temp_path, check_existing=False)
        img.name = name
        # Keep sRGB colorspace for proper display in Image Editor and other Blender areas
        # Moodboard rendering handles color management bypass separately
        img.colorspace_settings.name = 'sRGB'
        img.pack()
        img.filepath = ""  # Clear temp path so Blender doesn't try to re-pack from deleted file
        return img
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except OSError:
            pass


TEMP_IMAGE_DIR_PREFIX = "mixar_img_"


def filename_from_url(url: str) -> str:
    """Extract the file name from a (presigned) URL's path.

    ``https://s3/.../red-dragon_a1b2_01.png?X-Amz-...`` -> ``red-dragon_a1b2_01.png``.
    Sanitized for the local filesystem; returns "" when the URL has no usable
    path component (caller falls back to an anonymous temp name).
    """
    import re
    from urllib.parse import unquote, urlparse

    name = os.path.basename(unquote(urlparse(url).path or ""))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name


def cleanup_temp_image(temp_path: str) -> None:
    """Remove a downloaded temp image and, when it lives in a directory owned
    by ``download_image_to_tempfile`` (named-file mode), that directory too."""
    try:
        os.unlink(temp_path)
    except OSError:
        pass
    parent = os.path.dirname(temp_path)
    if os.path.basename(parent).startswith(TEMP_IMAGE_DIR_PREFIX):
        try:
            os.rmdir(parent)
        except OSError:
            pass


def download_image_to_tempfile(
    url: str, retries: int = 3, filename: str = "",
) -> tuple[str, int]:
    """Download an image URL to a temporary file.

    This helper is safe to call from a background thread. Blender image loading
    must happen later on the main thread via ``load_image_from_file``.

    When *filename* is given, the temp file keeps that exact name (inside a
    fresh private temp directory, so concurrent downloads can't collide) —
    used to preserve the server-side/S3 file name in the loaded datablock.
    Clean up named-mode files with :func:`cleanup_temp_image`.
    """
    import urllib.request
    import time as _time

    logger.debug("[ImageUtils] Downloading image...")

    # Download image with retry
    image_bytes = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                image_bytes = response.read()
            break
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt  # 1s, 2s
                logger.warning("[ImageUtils] Download attempt %s failed: %s, retrying in %ss...", attempt + 1, e, wait)
                _time.sleep(wait)
            else:
                raise

    if image_bytes is None:
        raise RuntimeError("Failed to download image after retries")

    byte_count = len(image_bytes)
    logger.debug("[ImageUtils] Downloaded %s bytes", byte_count)

    # Write to temp file
    if filename:
        temp_dir = tempfile.mkdtemp(prefix=TEMP_IMAGE_DIR_PREFIX)
        temp_path = os.path.join(temp_dir, filename)
        with open(temp_path, 'wb') as f:
            f.write(image_bytes)
    else:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            temp_path = f.name

    return temp_path, byte_count


def load_image_from_file(
    file_path: str, name: str, keep_filename: bool = False,
) -> bpy.types.Image:
    """Load and pack a Blender Image from a local file on the main thread.

    With *keep_filename* the packed image keeps the source file's name as a
    blend-relative phantom path (``//red-dragon_a1b2_01.png``) so the .blend
    shows the server-side file name; without it the temp path is cleared
    entirely. Either way Blender never re-reads the deleted temp file — the
    pixels are packed.
    """
    img = bpy.data.images.load(file_path, check_existing=False)
    img.name = name
    # Keep sRGB colorspace for proper display in Image Editor and other Blender areas
    # Moodboard rendering handles color management bypass separately
    img.colorspace_settings.name = 'sRGB'
    img.pack()
    # filepath_raw skips path-resolution side effects; the deleted temp path
    # must not survive here or Blender may try to re-pack from it.
    if keep_filename:
        img.filepath_raw = "//" + os.path.basename(file_path)
    else:
        img.filepath_raw = ""
    logger.debug("[ImageUtils] Loaded image: %s", img.name)
    return img


def load_image_from_url(url: str, name: str, retries: int = 3) -> bpy.types.Image:
    """Load a Blender Image from a URL with retry on timeout."""
    temp_path, _byte_count = download_image_to_tempfile(url, retries=retries)

    try:
        return load_image_from_file(temp_path, name)
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def add_image_to_moodboard(
    image: bpy.types.Image,
    prompt: str = "",
    position_x: float | None = None,
    position_y: float | None = None,
    scale: float = 1.0,
    job_handle: str = "",
) -> None:
    """Add an image to the moodboard collection at specified position.

    When *position_x* or *position_y* are ``None`` (the default) the image is
    placed near the centre of the currently visible moodboard viewport so that
    it always pops up where the user is looking, regardless of pan/zoom state,
    and nudged to the nearest free slot so it does not land on top of existing
    images.  Explicit float values override this behaviour and allow callers to
    place images at precise canvas coordinates (e.g. for side-by-side layouts).
    """
    scene = bpy.context.scene
    item = scene.mixie_moodboard_images.add()
    item.image = image
    item.scale = scale
    item.z_order = len(scene.mixie_moodboard_images) - 1
    if prompt:
        item.generation_prompt = prompt
    item.mixar_created_at_iso = datetime.now(timezone.utc).isoformat()
    if job_handle:
        item.mixar_job_handle = job_handle

    if position_x is None or position_y is None:
        # Auto-place into visible free space (centre → nearest free slot →
        # zoom out to reveal).  Shared with the upload/paste paths.
        try:
            from mixar.modules.moodboard.core.moodboard_utils import (
                place_new_moodboard_item,
            )
            place_new_moodboard_item(scene, item)
        except Exception:
            pass
    # Explicit coordinates override the auto-placement.
    if position_x is not None:
        item.position_x = position_x
    if position_y is not None:
        item.position_y = position_y

    # Redraw Mixie space
    for area in bpy.context.screen.areas:
        if area.type == 'MIXIE':
            area.tag_redraw()
