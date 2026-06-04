# SPDX-FileCopyrightText: 2025 Mixar Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Moodboard clipboard operators.

Hosts the Copy operator that writes the first selected moodboard image to
the system clipboard as a PNG. The Paste operator already lives in
``image_ops.py``; this module is split out to keep both files under the
500-line limit and to group platform-specific clipboard code in one place.
"""

import os
import platform
import subprocess
import sys
import tempfile

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from ....common.utils.platform_utils import format_shortcut

logger = get_logger(__name__)


def _selected_moodboard_image(scene):
    """Return the first selected moodboard item that has a valid image."""
    images = getattr(scene, "mixie_moodboard_images", None)
    if not images:
        return None
    for item in images:
        if item.selected and item.image:
            return item
    return None


def _save_blender_image_to_png(image, dest_path):
    """Save a bpy.types.Image to a PNG file at ``dest_path``.

    Uses Blender's image saver (handles packed images and non-RGBA modes
    without requiring Pillow on disk).
    """
    settings = bpy.context.scene.render.image_settings
    prev_format = settings.file_format
    prev_color_mode = settings.color_mode
    try:
        settings.file_format = 'PNG'
        settings.color_mode = 'RGBA' if image.channels == 4 else 'RGB'
        image.save_render(dest_path)
    finally:
        settings.file_format = prev_format
        settings.color_mode = prev_color_mode


def _copy_png_to_clipboard_macos(png_path):
    script = (
        f'set the clipboard to (read (POSIX file "{png_path}") as {{«class PNGf»}})'
    )
    subprocess.run(
        ['osascript', '-e', script],
        check=True,
        capture_output=True,
    )


def _copy_png_to_clipboard_windows(png_path):
    # win32clipboard ships with pywin32; CF_DIB is a BMP without the 14-byte
    # file header, which is what Windows expects for image data.
    import win32clipboard  # type: ignore[import-not-found]
    from PIL import Image
    import io

    image = Image.open(png_path)
    output = io.BytesIO()
    image.convert('RGB').save(output, 'BMP')
    data = output.getvalue()[14:]  # strip BMP file header
    output.close()

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()


def _copy_png_to_clipboard_linux(png_path):
    # Prefer wl-copy on Wayland, fall back to xclip on X11.
    if os.environ.get('WAYLAND_DISPLAY'):
        with open(png_path, 'rb') as f:
            subprocess.run(
                ['wl-copy', '--type', 'image/png'],
                input=f.read(),
                check=True,
            )
        return
    subprocess.run(
        ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-i', png_path],
        check=True,
    )


def _copy_png_to_clipboard(png_path):
    system = platform.system()
    if system == 'Darwin':
        _copy_png_to_clipboard_macos(png_path)
    elif system == 'Windows':
        _copy_png_to_clipboard_windows(png_path)
    else:
        _copy_png_to_clipboard_linux(png_path)


class MIXIE_OT_moodboard_copy_image(Operator):
    """Copy the first selected moodboard image to the system clipboard"""

    bl_idname = "mixie.moodboard_copy_image"
    bl_label = "Copy Image to Clipboard"
    bl_description = (
        f"Copy the first selected moodboard image to the system clipboard "
        f"({format_shortcut('C')})"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _selected_moodboard_image(context.scene) is not None

    def execute(self, context):
        item = _selected_moodboard_image(context.scene)
        if item is None or item.image is None:
            self.report({'WARNING'}, "No moodboard image selected")
            return {'CANCELLED'}

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix='.png', prefix='mixar_clipcopy_', delete=False
            ) as tmp:
                tmp_path = tmp.name
            _save_blender_image_to_png(item.image, tmp_path)
            _copy_png_to_clipboard(tmp_path)
        except FileNotFoundError as e:
            logger.exception("Clipboard tool missing: %s", e)
            self.report(
                {'ERROR'},
                "Clipboard tool not found. Install xclip (X11) or wl-clipboard (Wayland).",
            )
            return {'CANCELLED'}
        except subprocess.CalledProcessError as e:
            logger.exception("Clipboard copy command failed: %s", e)
            self.report({'ERROR'}, f"Failed to copy image to clipboard: {e}")
            return {'CANCELLED'}
        except ImportError as e:
            logger.exception("Missing dependency: %s", e)
            self.report(
                {'ERROR'},
                "Missing clipboard dependency (pywin32/Pillow on Windows).",
            )
            return {'CANCELLED'}
        except Exception as e:
            logger.exception("Failed to copy image to clipboard")
            self.report({'ERROR'}, f"Failed to copy image to clipboard: {e}")
            return {'CANCELLED'}
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        self.report({'INFO'}, f"Copied '{item.image.name}' to clipboard")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_copy_image,
)
