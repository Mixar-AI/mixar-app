# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image utilities for Mixie Chat attachments.

Provides functions for image validation, base64 encoding, and thumbnail generation.
"""

import base64
import os
import uuid
from io import BytesIO
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_SIZE_BYTES,
    SUPPORTED_IMAGE_FORMATS,
    THUMBNAIL_SIZE,
)

logger = get_logger(__name__)

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def get_mixar_screenshots_dir() -> str:
    """Get (and create if needed) the Mixar screenshots directory.

    Uses a 'mixar_screenshots' subfolder inside Blender's temp directory.
    This avoids macOS symlink issues (/var -> /private/var) and keeps
    temp images in a well-known, Blender-managed location.

    Returns:
        Absolute path to the screenshots directory.
    """
    import bpy
    base = bpy.app.tempdir or os.path.join(os.path.expanduser('~'), '.mixar', 'cache')
    screenshots_dir = os.path.join(base, 'mixar_screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)
    return screenshots_dir


# Sensitive paths that should never be accessed
BLOCKED_PATH_PATTERNS = (
    '/etc/',
    '/root/',
    '/.ssh/',
    '/.gnupg/',
    '/private/',
    '/.config/',
    '/var/log/',
    '/proc/',
    '/sys/',
    '\\windows\\system32',
    '\\program files',
)


def _is_path_safe(filepath: str) -> tuple[bool, str]:
    """
    Validate that a filepath is safe to access.

    Checks for path traversal attempts and blocks access to sensitive directories.

    Args:
        filepath: Path to validate

    Returns:
        Tuple of (is_safe, error_message)
    """
    if not filepath:
        return False, "Empty filepath"

    # Resolve to absolute path to detect traversal attempts
    try:
        abs_path = os.path.realpath(filepath)
    except (OSError, ValueError) as e:
        return False, f"Invalid path: {e}"

    # Check for path traversal (original path different from resolved)
    # This catches attempts like "../../../etc/passwd"
    normalized_input = os.path.normpath(filepath)
    if '..' in filepath and abs_path != os.path.realpath(normalized_input):
        return False, "Path traversal detected"

    # Allow temp directories (on macOS /var/folders resolves to /private/var/folders)
    import tempfile
    allowed_roots = [os.path.realpath(tempfile.gettempdir())]
    try:
        import bpy
        if bpy.app.tempdir:
            allowed_roots.append(os.path.realpath(bpy.app.tempdir))
    except Exception:
        pass
    for allowed in allowed_roots:
        if abs_path.startswith(allowed + os.sep) or abs_path == allowed:
            return True, ""

    # Block sensitive directories - normalize separators for cross-platform matching
    lower_path = abs_path.lower().replace('\\', '/')
    for blocked in BLOCKED_PATH_PATTERNS:
        if blocked.lower().replace('\\', '/') in lower_path:
            return False, f"Access to sensitive path blocked: {blocked}"

    return True, ""


# Preview collection for thumbnails
_preview_collection = None


def get_preview_collection():
    """Get or create the preview collection for chat thumbnails."""
    global _preview_collection
    if _preview_collection is None:
        import bpy.utils.previews
        _preview_collection = bpy.utils.previews.new()
    return _preview_collection


def cleanup_preview_collection():
    """Clean up the preview collection on unregister."""
    global _preview_collection
    if _preview_collection is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_preview_collection)
        _preview_collection = None


def _same_file_path(a: str, b: str) -> bool:
    """Compare Blender/file-system paths defensively."""
    if not a or not b:
        return False
    try:
        a_abs = os.path.realpath(bpy.path.abspath(a))
        b_abs = os.path.realpath(bpy.path.abspath(b))
    except Exception:
        try:
            a_abs = os.path.realpath(a)
            b_abs = os.path.realpath(b)
        except Exception:
            return False
    return a_abs == b_abs


def cleanup_loaded_file_image(filepath: str) -> None:
    """Remove an unowned file image that was loaded only for chat drawing.

    The C++ chat renderer loads file attachments into ``bpy.data.images`` via
    ``BKE_image_load_exists``. Attachment/message removal only clears RNA
    records, so explicitly drop the matching image datablock when it has no
    other Blender users.
    """
    if not filepath:
        return

    basename = os.path.basename(filepath)
    candidates = []
    if basename and basename in bpy.data.images:
        candidates.append(bpy.data.images[basename])

    try:
        candidates.extend(
            img for img in bpy.data.images
            if img not in candidates and _same_file_path(getattr(img, "filepath", ""), filepath)
        )
    except Exception:
        pass

    for img in candidates:
        if not _same_file_path(getattr(img, "filepath", ""), filepath):
            continue
        if getattr(img, "users", 0) > 0:
            continue
        try:
            bpy.data.images.remove(img)
        except Exception:
            logger.debug("Failed to remove chat image datablock: %s", filepath, exc_info=True)


def cleanup_loaded_file_images(filepaths) -> None:
    """Remove unowned chat-loaded image datablocks for multiple paths."""
    for filepath in filepaths:
        cleanup_loaded_file_image(filepath)


def collect_message_file_image_paths(message) -> list[str]:
    """Collect file-backed image paths referenced by a chat message."""
    paths: list[str] = []

    for att in getattr(message, "attachments", ()):
        if getattr(att, "image_source", "") == "FILE" and getattr(att, "image_path", ""):
            paths.append(att.image_path)

    for item in getattr(message, "image_items", ()):
        for attr in ("local_path", "thumbnail_url", "url"):
            path = getattr(item, attr, "")
            if path and os.path.exists(path):
                paths.append(path)

    return paths


def validate_image_file(filepath: str) -> tuple[bool, str]:
    """
    Validate an image file for chat attachment.

    Performs security checks including:
    - Path traversal prevention
    - File extension validation
    - File size limits
    - Image dimension limits (memory exhaustion prevention)

    Args:
        filepath: Path to the image file

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not filepath:
        return False, "No file path provided"

    # Security: Validate path before any file operations
    is_safe, error = _is_path_safe(filepath)
    if not is_safe:
        return False, error

    if not os.path.exists(filepath):
        return False, "File does not exist"

    # Check file extension
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in SUPPORTED_IMAGE_FORMATS:
        return False, f"Unsupported format: {ext}. Supported: {', '.join(SUPPORTED_IMAGE_FORMATS)}"

    # Check file size
    file_size = os.path.getsize(filepath)
    if file_size > MAX_IMAGE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        max_mb = MAX_IMAGE_SIZE_BYTES / (1024 * 1024)
        return False, f"File too large: {size_mb:.1f}MB (max {max_mb:.0f}MB)"

    # Security: Validate image dimensions to prevent memory exhaustion
    if HAS_PIL:
        try:
            with PILImage.open(filepath) as img:
                width, height = img.size
                if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                    return False, (
                        f"Image dimensions too large: {width}x{height} "
                        f"(max {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION})"
                    )
        except (OSError, IOError) as e:
            return False, f"Could not read image: {e}"

    return True, ""


def image_file_to_base64(filepath: str) -> Optional[str]:
    """
    Convert an image file to base64 string.

    Args:
        filepath: Path to the image file

    Returns:
        Base64 encoded string or None on error
    """
    # Security: Validate path before opening to prevent path traversal
    is_safe, error = _is_path_safe(filepath)
    if not is_safe:
        logger.error(f"Path validation failed: {error}")
        return None

    try:
        with open(filepath, 'rb') as f:
            image_data = f.read()
        return base64.b64encode(image_data).decode('utf-8')
    except (OSError, IOError) as e:
        logger.error(f"Error encoding image file: {e}")
        return None


def blend_image_to_base64(image_name: str) -> Optional[str]:
    """
    Convert a Blender data image to base64 PNG string.

    Reads pixels directly from the image's internal buffer to avoid
    modifying the original image (setting filepath_raw on a generated
    image permanently changes it to file-based, causing pink display).

    Args:
        image_name: Name of the image in bpy.data.images

    Returns:
        Base64 encoded PNG string or None on error
    """
    if image_name not in bpy.data.images:
        logger.error(f"Image not found in blend data: {image_name}")
        return None

    image = bpy.data.images[image_name]

    try:
        from mixar.modules.common.utils.image_utils import image_to_png_bytes
        png_data = image_to_png_bytes(image)
        return base64.b64encode(png_data).decode('utf-8')
    except (OSError, IOError, RuntimeError, ValueError) as e:
        logger.error(f"Error encoding blend image: {e}")
        return None


def image_to_base64(image_path_or_name: str, source: str) -> Optional[str]:
    """
    Convert an image to base64 string.

    Args:
        image_path_or_name: File path or blend image name
        source: Either 'FILE' or 'BLEND_DATA'

    Returns:
        Base64 encoded string or None on error
    """
    if source == 'FILE':
        return image_file_to_base64(image_path_or_name)
    elif source == 'BLEND_DATA':
        return blend_image_to_base64(image_path_or_name)
    else:
        logger.error(f"Unknown image source: {source}")
        return None


def get_image_thumbnail_id(image_path_or_name: str, source: str) -> int:
    """
    Get or generate a thumbnail preview ID for an image.

    Args:
        image_path_or_name: File path or blend image name
        source: Either 'FILE' or 'BLEND_DATA'

    Returns:
        Preview icon ID, or 0 if generation failed
    """
    pcoll = get_preview_collection()

    # Create a unique key for this image
    key = f"{source}:{image_path_or_name}"

    if key in pcoll:
        return pcoll[key].icon_id

    try:
        if source == 'FILE':
            if os.path.exists(image_path_or_name):
                preview = pcoll.load(key, image_path_or_name, 'IMAGE')
                return preview.icon_id
        elif source == 'BLEND_DATA':
            if image_path_or_name in bpy.data.images:
                image = bpy.data.images[image_path_or_name]
                # For blend images, we need to use the image's preview
                if image.preview:
                    return image.preview.icon_id
                # Generate preview if not available
                image.preview_ensure()
                if image.preview:
                    return image.preview.icon_id
    except Exception as e:
        logger.error(f"Error generating thumbnail: {e}")

    return 0


def get_blend_images() -> list[dict]:
    """
    Get list of available images in bpy.data.images.

    Returns:
        List of dicts with 'name', 'width', 'height', 'has_data' keys
    """
    images = []
    for image in bpy.data.images:
        # Skip render results and viewer images
        if image.type in {'RENDER_RESULT', 'COMPOSITING'}:
            continue

        images.append({
            'name': image.name,
            'width': image.size[0],
            'height': image.size[1],
            'has_data': image.has_data,
            'filepath': image.filepath if image.filepath else None,
        })

    return images


def get_image_display_name(image_path_or_name: str, source: str) -> str:
    """
    Get a display-friendly name for an image.

    Args:
        image_path_or_name: File path or blend image name
        source: Either 'FILE' or 'BLEND_DATA'

    Returns:
        Display name for the image
    """
    if source == 'FILE':
        return os.path.basename(image_path_or_name)
    else:
        return image_path_or_name


def clear_thumbnail_cache():
    """Clear all cached thumbnails."""
    pcoll = get_preview_collection()
    pcoll.clear()
