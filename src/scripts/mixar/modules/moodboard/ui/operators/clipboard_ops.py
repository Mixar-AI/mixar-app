# SPDX-FileCopyrightText: 2025 Mixar Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Moodboard clipboard operators.

Hosts the Copy operator that writes the first selected moodboard image to
the system clipboard as a PNG. The Paste operator already lives in
``image_ops.py``; this module is split out to keep both files under the
500-line limit and to group platform-specific clipboard code in one place.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from ....common.utils.platform_utils import format_shortcut
from ...core.moodboard_clipboard import copy_selected
from ...core.system_clipboard import copy_blender_image_to_system_clipboard

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
                copy_blender_image_to_system_clipboard(item.image, scene)
            except Exception as e:
                logger.debug(f"System clipboard copy skipped: {e}")

        noun = "item" if count == 1 else "items"
        self.report({'INFO'}, f"Copied {count} {noun}")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_copy_image,
)
