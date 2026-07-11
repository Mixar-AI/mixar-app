# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cross-platform system clipboard export for Blender images."""

import io
import os
import platform
import subprocess
import tempfile


_MACOS_CLIPBOARD_SCRIPT = """\
on run argv
  set imagePath to item 1 of argv
  set the clipboard to (read (POSIX file imagePath) as «class PNGf»)
end run
"""


def save_blender_image_to_png(image, dest_path: str, scene) -> None:
    """Save a Blender image to PNG while restoring render output settings."""
    settings = scene.render.image_settings
    previous_format = settings.file_format
    previous_color_mode = settings.color_mode
    try:
        settings.file_format = 'PNG'
        settings.color_mode = 'RGBA' if image.channels == 4 else 'RGB'
        image.save_render(dest_path, scene=scene)
    finally:
        settings.file_format = previous_format
        settings.color_mode = previous_color_mode


def _copy_png_to_clipboard_macos(png_path: str) -> None:
    """Copy PNG bytes on macOS without interpolating the path into code."""
    subprocess.run(
        ['osascript', '-e', _MACOS_CLIPBOARD_SCRIPT, png_path],
        check=True,
        capture_output=True,
    )


def _copy_png_to_clipboard_windows(png_path: str) -> None:
    """Copy a PNG to the Windows clipboard as CF_DIB."""
    import win32clipboard  # type: ignore[import-not-found]
    from PIL import Image

    with Image.open(png_path) as image, io.BytesIO() as output:
        image.convert('RGB').save(output, 'BMP')
        data = output.getvalue()[14:]  # Strip the BMP file header.

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()


def _copy_png_to_clipboard_linux(png_path: str) -> None:
    """Copy a PNG with wl-copy on Wayland or xclip on X11."""
    if os.environ.get('WAYLAND_DISPLAY'):
        with open(png_path, 'rb') as png_file:
            subprocess.run(
                ['wl-copy', '--type', 'image/png'],
                input=png_file.read(),
                check=True,
            )
        return
    subprocess.run(
        ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-i', png_path],
        check=True,
    )


def copy_png_to_system_clipboard(png_path: str) -> None:
    """Copy a PNG file to the native clipboard for the current platform."""
    system = platform.system()
    if system == 'Darwin':
        _copy_png_to_clipboard_macos(png_path)
    elif system == 'Windows':
        _copy_png_to_clipboard_windows(png_path)
    else:
        _copy_png_to_clipboard_linux(png_path)


def copy_blender_image_to_system_clipboard(image, scene) -> None:
    """Export a Blender image to a temporary PNG and copy it natively."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix='.png',
            prefix='mixar_clipcopy_',
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
        save_blender_image_to_png(image, temp_path, scene)
        copy_png_to_system_clipboard(temp_path)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
