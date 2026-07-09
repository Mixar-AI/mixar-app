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
from ...core.moodboard_clipboard import copy_selected

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


def _has_moodboard_selection(scene):
    """True if any moodboard image or text box is selected."""
    if _selected_moodboard_image(scene) is not None:
        return True
    textboxes = getattr(scene, "mixie_moodboard_textboxes", None)
    return bool(textboxes) and any(tb.selected for tb in textboxes)


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


def _copy_first_image_to_system_clipboard(item):
    """Best-effort: place ``item``'s image on the OS clipboard as a PNG.

    Raises on failure so the caller can log it; never required for the in-app
    copy to succeed.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix='.png', prefix='mixar_clipcopy_', delete=False
        ) as tmp:
            tmp_path = tmp.name
        _save_blender_image_to_png(item.image, tmp_path)
        _copy_png_to_clipboard(tmp_path)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class MIXIE_OT_moodboard_copy_image(Operator):
    """Copy the selected moodboard image(s) and text box(es) so they can be pasted"""

    bl_idname = "mixie.moodboard_copy_image"
    bl_label = "Copy"
    bl_description = (
        f"Copy the selected moodboard images and text boxes; paste with "
        f"{format_shortcut('V')}"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _has_moodboard_selection(context.scene)

    def execute(self, context):
        scene = context.scene

        # Primary path: snapshot the selection into the reliable in-app
        # clipboard so paste is a lossless, cross-platform duplicate.
        count = copy_selected(scene)
        if count == 0:
            self.report({'WARNING'}, "Nothing selected to copy")
            return {'CANCELLED'}

        # Secondary, best-effort: also put the first image on the system
        # clipboard for pasting into other apps.  Failures here (missing xclip,
        # etc.) must not fail the in-app copy.
        item = _selected_moodboard_image(scene)
        if item is not None and item.image is not None:
            try:
                _copy_first_image_to_system_clipboard(item)
            except Exception as e:
                logger.debug("System clipboard copy skipped: %s", e)

        noun = "item" if count == 1 else "items"
        self.report({'INFO'}, f"Copied {count} {noun}")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_copy_image,
)
