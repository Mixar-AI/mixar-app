# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Chat-attachment compression — the client half of the upload contract.

Everything the user attaches to a Mixie message is base64'd into the chat
request body, so a phone photo must be downscaled and re-encoded BEFORE it
goes on the wire, not after it lands. Uploading originals cost roughly 30x
the bytes on the FILE path and, on the BLEND_DATA path, produced a
full-resolution RGBA PNG that overshot the backend's raw-payload ceiling and
had the attachment dropped outright — the compression never ran because the
payload never got that far.

The targets mirror ``modules/agent/services/chat.py`` on the backend
(``IMAGE_MAX_EDGE_PX`` / ``IMAGE_JPEG_QUALITY``): 1568 px is Anthropic's
effective maximum image edge — anything larger is downscaled provider-side
anyway — and JPEG q85 turns a multi-megapixel camera photo into a few hundred
KB with no meaningful loss for the model. Because we hit the same target, the
backend's own compression pass sees no gain and keeps our bytes as-is.

Generation quality is unaffected: image-to-3D and the other generation tools
consume the full-resolution ``bpy.data.images`` entry via ``image_name``
(forwarded as ``attachment_names``), never this data URL.

The byte-level helpers here are deliberately ``bpy``-free so the FILE path can
run on the encoder thread pool; only :func:`compress_blend_image_for_chat`
touches ``bpy`` and must stay on the main thread.
"""

from __future__ import annotations

import io
import os
from typing import Optional, Tuple

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

try:
    from PIL import Image as PILImage
    from PIL import ImageOps as PILImageOps
    HAS_PIL = True
except ImportError:  # pragma: no cover - PIL ships with the client
    PILImage = None
    PILImageOps = None
    HAS_PIL = False


# Longest edge (px) an attachment is downscaled to before upload. Keep in sync
# with IMAGE_MAX_EDGE_PX in the backend's modules/agent/services/chat.py.
CHAT_ATTACHMENT_MAX_EDGE = 1568

# JPEG quality for the re-encode. Keep in sync with the backend's
# IMAGE_JPEG_QUALITY.
CHAT_ATTACHMENT_JPEG_QUALITY = 85

# Minimum saving before the re-encode is worth taking. Below this the original
# goes up untouched rather than spending a lossy generation to shave a rounding
# error off an already-small JPEG.
MIN_COMPRESSION_GAIN = 0.10

# Formats the LLM providers actually accept. Anything else MUST be converted
# whatever the byte count says — an uncompressed .bmp/.tiff attachment was
# declared as image/bmp and rejected by the provider outright.
PROVIDER_SAFE_FORMATS = frozenset({"JPEG", "PNG", "GIF", "WEBP"})

# Refuse to decode anything above this pixel count. Bounds decoder memory
# independently of the file size, which is what actually protects us from a
# decompression bomb (a few-KB PNG can declare a gigapixel canvas). 80 MP
# clears every phone and full-frame camera; a 48 MP iPhone photo is 48 MP.
MAX_DECODE_PIXELS = 80_000_000

JPEG_MIME = "image/jpeg"


def _flatten_alpha(img):
    """Composite transparency onto WHITE.

    PIL's bare ``convert("RGB")`` composites onto black, which turns a
    dark-foreground cutout into a near-black frame the model cannot read.
    """
    if img.mode not in ("RGBA", "LA", "P"):
        return img
    rgba = img.convert("RGBA")
    canvas = PILImage.new("RGB", rgba.size, (255, 255, 255))
    canvas.paste(rgba, mask=rgba.getchannel("A"))
    return canvas


def _encode_jpeg(img) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(
        out, format="JPEG", quality=CHAT_ATTACHMENT_JPEG_QUALITY, optimize=True
    )
    return out.getvalue()


def compress_image_bytes(
    raw: bytes,
    original_size: Optional[int] = None,
) -> Optional[Tuple[bytes, str]]:
    """Downscale + JPEG re-encode encoded image bytes.

    Args:
        raw: The encoded source image (JPEG/PNG/BMP/TIFF bytes).
        original_size: Byte count the result must beat to be worth using.
            Defaults to ``len(raw)``. Callers whose source is not what would
            otherwise be uploaded (the BLEND_DATA pixel fallback, where the
            alternative is a much larger PNG) pass that alternative's size.

    Returns:
        ``(jpeg_bytes, "image/jpeg")``, or ``None`` when PIL is unavailable,
        the bytes are not a decodable image, the image declares an implausible
        pixel count, or the re-encode would save less than
        :data:`MIN_COMPRESSION_GAIN` on a format the providers already accept.
        ``None`` means "upload the original" — never an error.
    """
    if not HAS_PIL or not raw:
        return None

    budget = len(raw) if original_size is None else original_size

    try:
        img = PILImage.open(io.BytesIO(raw))
        # Only valid straight after open — the transforms below clear it.
        source_format = (img.format or "").upper()

        # Header-only at this point: reject bombs before any pixels are
        # decoded, and let libjpeg decode straight to a reduced scale (draft
        # is DCT-domain, so a 12 MP photo never materialises at full size).
        width, height = img.size
        if width <= 0 or height <= 0:
            return None
        if width * height > MAX_DECODE_PIXELS:
            logger.warning(
                "[ChatCompress] Refusing to decode %sx%s attachment (%.0f MP > %.0f MP cap)",
                width, height, width * height / 1e6, MAX_DECODE_PIXELS / 1e6,
            )
            return None
        img.draft("RGB", (CHAT_ATTACHMENT_MAX_EDGE, CHAT_ATTACHMENT_MAX_EDGE))

        # iPhone photos are stored landscape with an orientation tag; without
        # this the model sees them rotated. The JPEG re-encode drops EXIF, so
        # the backend's own transpose then correctly does nothing.
        img = PILImageOps.exif_transpose(img) or img

        if max(img.size) > CHAT_ATTACHMENT_MAX_EDGE:
            img.thumbnail(
                (CHAT_ATTACHMENT_MAX_EDGE, CHAT_ATTACHMENT_MAX_EDGE),
                PILImage.LANCZOS,
            )

        compressed = _encode_jpeg(_flatten_alpha(img))
    except Exception:
        logger.warning("[ChatCompress] Could not compress attachment; sending original",
                       exc_info=True)
        return None

    worth_it = len(compressed) <= budget * (1 - MIN_COMPRESSION_GAIN)
    if not worth_it and source_format in PROVIDER_SAFE_FORMATS:
        logger.debug("[ChatCompress] Re-encode saves too little (%s -> %s bytes); keeping original",
                     budget, len(compressed))
        return None

    logger.info(
        "[ChatCompress] Attachment %sx%s -> %sx%s, %.1fKB -> %.1fKB",
        width, height, img.size[0], img.size[1], budget / 1024, len(compressed) / 1024,
    )
    return compressed, JPEG_MIME


def compress_file_for_chat(filepath: str) -> Optional[Tuple[bytes, str]]:
    """Compress an image file for upload. Safe to call off the main thread."""
    try:
        with open(filepath, "rb") as handle:
            raw = handle.read()
    except (OSError, IOError) as exc:
        logger.error("[ChatCompress] Could not read attachment %s: %s", filepath, exc)
        return None
    return compress_image_bytes(raw)


def _packed_source_bytes(image) -> Optional[bytes]:
    """Encoded bytes for a blend image, without touching its pixel buffer.

    Packing a still keeps the ORIGINAL file bytes, so a boarded iPhone photo
    is still its own JPEG here — decoding that is orders of magnitude cheaper
    than reading ``image.pixels`` (a 12 MP image is a 195 MB float buffer)
    and it skips the full-resolution PNG re-encode entirely.
    """
    # Unsaved pixel edits do not reach the packed bytes or the file on disk,
    # so a dirty image must go through its pixel buffer like image_to_png_bytes
    # does — otherwise the upload shows the pre-edit picture.
    if getattr(image, "is_dirty", False):
        return None

    packed = getattr(image, "packed_file", None)
    data = getattr(packed, "data", None) if packed else None
    if data:
        try:
            return bytes(data)
        except (TypeError, ValueError):
            return None

    # Not packed, but still file-backed: read the source from disk.
    try:
        import bpy

        filepath = bpy.path.abspath(getattr(image, "filepath", "") or "")
    except Exception:
        return None
    if filepath and os.path.isfile(filepath):
        try:
            with open(filepath, "rb") as handle:
                return handle.read()
        except (OSError, IOError):
            return None
    return None


def _pixels_to_pil(image):
    """Build a PIL image from a blend image's pixel buffer (main thread).

    Matches ``common.utils.image_utils.image_to_png_bytes`` exactly — same
    float->byte truncation, same bottom-up row flip — so a generated image
    (screenshot, crop, paste) compresses to the pixels it would otherwise
    have uploaded.
    """
    from mixar.modules.common.utils.image_utils import image_to_rgba_array

    rgba = image_to_rgba_array(image)
    return PILImage.fromarray(rgba, "RGBA")


def compress_blend_image_for_chat(image_name: str) -> Optional[Tuple[bytes, str]]:
    """Compress a ``bpy.data.images`` entry for upload. MAIN THREAD ONLY."""
    if not HAS_PIL:
        return None

    import bpy

    image = bpy.data.images.get(image_name)
    if image is None:
        return None

    # Fast path: the encoded source is still available (packed or on disk).
    raw = _packed_source_bytes(image)
    if raw:
        result = compress_image_bytes(raw)
        if result is not None:
            return result

    # Fallback: generated/in-memory images have no encoded source. Go through
    # the pixel buffer, and measure the gain against the PNG we would
    # otherwise have uploaded rather than against the raw buffer.
    try:
        img = _pixels_to_pil(image)
    except Exception:
        logger.warning("[ChatCompress] Could not read pixels for '%s'", image_name,
                       exc_info=True)
        return None

    width, height = img.size
    if not width or not height:
        return None
    if max(width, height) > CHAT_ATTACHMENT_MAX_EDGE:
        img.thumbnail(
            (CHAT_ATTACHMENT_MAX_EDGE, CHAT_ATTACHMENT_MAX_EDGE), PILImage.LANCZOS
        )

    try:
        compressed = _encode_jpeg(_flatten_alpha(img))
    except Exception:
        logger.warning("[ChatCompress] Could not encode '%s'", image_name, exc_info=True)
        return None

    logger.info(
        "[ChatCompress] Blend image '%s' %sx%s -> %sx%s, %.1fKB JPEG",
        image_name, width, height, img.size[0], img.size[1], len(compressed) / 1024,
    )
    return compressed, JPEG_MIME
