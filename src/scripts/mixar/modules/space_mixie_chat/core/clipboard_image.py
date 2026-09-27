# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read an image off the system clipboard into a temp PNG (per platform).

Used by ``mixie_chat.paste_image``; kept free of ``bpy`` so the operator
decides where the file goes (Agent attachment or an island pane reference).
"""

import os
import platform
import shutil
import struct
import subprocess
import uuid
from io import BytesIO

from mixar.config.logging_config import get_logger

from ..constants import SUPPORTED_IMAGE_FORMATS
from .image_utils import get_mixar_screenshots_dir

logger = get_logger(__name__)

# Try to import PIL for Windows clipboard BMP decoding
try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PIL/Pillow not available - image clipboard features disabled")


def _safe_remove(path):
    """Remove a file, ignoring errors if it doesn't exist."""
    try:
        os.remove(path)
    except OSError:
        pass


def read_clipboard_image():
    """Get image from system clipboard (platform-specific).

    Returns path to temp PNG, or None if no image on clipboard.
    """
    system = platform.system()
    screenshots_dir = get_mixar_screenshots_dir()
    temp_path = os.path.join(
        screenshots_dir, f"mixie_paste_{uuid.uuid4().hex}.png"
    )

    if system == 'Darwin':
        return _paste_macos(temp_path)
    elif system == 'Windows':
        return _paste_windows(temp_path)
    else:
        return _paste_linux(temp_path)


def _paste_macos(temp_path):
    """macOS: Check clipboard for image data.

    Strategy:
    1. Check «class furl» (file URL) first — when user copies a file from
       Finder, «class PNGf» returns the file's Finder icon, not the actual
       image. If the file URL points to a supported image format, use it.
    2. Fall back to «class PNGf» for actual image data (screenshots, etc).
    """
    # Step 1: Check if clipboard has a file URL pointing to a real image
    file_path = _macos_get_file_url()
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in SUPPORTED_IMAGE_FORMATS and os.path.isfile(file_path):
            shutil.copy2(file_path, temp_path)
            return temp_path

    # Step 2: Try raw PNG data (screenshots, copied image content)
    escaped_path = temp_path.replace('\\', '\\\\').replace('"', '\\"')
    try:
        result = subprocess.run([
            'osascript', '-e',
            f'try\n'
            f'  set imgData to the clipboard as «class PNGf»\n'
            f'  set outFile to open for access POSIX file "{escaped_path}" '
            f'with write permission\n'
            f'  write imgData to outFile\n'
            f'  close access outFile\n'
            f'  return "success"\n'
            f'on error\n'
            f'  return "no_image"\n'
            f'end try'
        ], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("osascript timed out reading clipboard")
        _safe_remove(temp_path)
        return None

    if result.stdout.strip() == 'success' and os.path.exists(temp_path):
        return temp_path
    _safe_remove(temp_path)
    return None


def _macos_get_file_url():
    """Get the POSIX file path from clipboard «class furl», if any.

    Returns the path string or None.
    """
    try:
        result = subprocess.run([
            'osascript', '-e',
            'try\n'
            '  set fileURL to the clipboard as «class furl»\n'
            '  return POSIX path of (fileURL as alias)\n'
            'on error\n'
            '  return ""\n'
            'end try'
        ], capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        return None

    path = result.stdout.strip()
    if path and os.path.exists(path):
        return path
    return None


def _paste_windows(temp_path):
    """Windows: Access clipboard via ctypes (no external dependencies).

    Strategy (in priority order):
    1. PNG clipboard format — best quality, preserves alpha.
    2. CF_HDROP file drop — image file copied from Explorer.
    3. CF_DIB bitmap data — raw pixels, needs PIL for BMP→PNG conversion.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 64-bit pointer safety: set proper argtypes/restype so handles
        # and pointers are not truncated to 32-bit c_int.
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = ctypes.c_void_p

        CF_DIB = 8
        CF_HDROP = 15

        # RegisterClipboardFormatW returns the ID for the "PNG" format
        # that many applications place on the clipboard.
        cf_png = user32.RegisterClipboardFormatW("PNG")

        if not user32.OpenClipboard(0):
            logger.warning("Could not open Windows clipboard")
            return None

        try:
            # --- Strategy 1: PNG format (raw PNG bytes) ---
            if cf_png and user32.IsClipboardFormatAvailable(cf_png):
                png_data = _win_read_global(
                    user32, kernel32, cf_png)
                if png_data:
                    with open(temp_path, 'wb') as f:
                        f.write(png_data)
                    return temp_path

            # --- Strategy 2: File drop (image copied from Explorer) ---
            if user32.IsClipboardFormatAvailable(CF_HDROP):
                file_path = _win_get_hdrop_path(user32)
                if file_path:
                    ext = os.path.splitext(file_path)[1].lower()
                    if (ext in SUPPORTED_IMAGE_FORMATS
                            and os.path.isfile(file_path)):
                        shutil.copy2(file_path, temp_path)
                        return temp_path

            # --- Strategy 3: CF_DIB bitmap (needs PIL) ---
            if HAS_PIL and user32.IsClipboardFormatAvailable(CF_DIB):
                dib_data = _win_read_global(
                    user32, kernel32, CF_DIB)
                if dib_data:
                    return _win_dib_to_png(dib_data, temp_path)

            return None

        finally:
            user32.CloseClipboard()

    except Exception as e:
        logger.error(f"Windows clipboard access failed: {e}")
        return None


def _win_read_global(user32, kernel32, fmt):
    """Read raw bytes from a clipboard format's global memory handle."""
    import ctypes

    handle = user32.GetClipboardData(fmt)
    if not handle:
        return None
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return None
    try:
        size = kernel32.GlobalSize(handle)
        return ctypes.string_at(ptr, size) if size else None
    finally:
        kernel32.GlobalUnlock(handle)


def _win_get_hdrop_path(user32):
    """Extract the first file path from a CF_HDROP clipboard handle."""
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p, wintypes.UINT,
        wintypes.LPWSTR, wintypes.UINT,
    ]
    shell32.DragQueryFileW.restype = wintypes.UINT

    handle = user32.GetClipboardData(15)  # CF_HDROP
    if not handle:
        return None

    num_files = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
    if num_files < 1:
        return None

    buf_len = shell32.DragQueryFileW(handle, 0, None, 0) + 1
    buf = ctypes.create_unicode_buffer(buf_len)
    shell32.DragQueryFileW(handle, 0, buf, buf_len)
    return buf.value or None


def _win_dib_to_png(dib_data, temp_path):
    """Convert CF_DIB raw bytes to a PNG file via PIL."""
    header_size = struct.unpack_from('<I', dib_data, 0)[0]
    file_size = 14 + len(dib_data)
    pixel_offset = 14 + header_size
    bmp_header = (b'BM'
                  + struct.pack('<I', file_size)
                  + b'\x00\x00\x00\x00'
                  + struct.pack('<I', pixel_offset))
    img = PILImage.open(BytesIO(bmp_header + dib_data))
    img.save(temp_path, 'PNG')
    return temp_path


def _paste_linux(temp_path):
    """Linux: Use xclip to grab image/png data from clipboard."""
    try:
        result = subprocess.run([
            'xclip', '-selection', 'clipboard',
            '-target', 'image/png', '-o'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug(f"xclip failed: {e}")
        return None

    if result.returncode == 0 and result.stdout:
        with open(temp_path, 'wb') as f:
            f.write(result.stdout)
        return temp_path
    return None
