# SPDX-FileCopyrightText: 2025 Mixar Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Moodboard clipboard operators.

Hosts the Copy operator. The Paste operator lives in ``image_ops.py``; this
module is split out to keep both files under the 500-line limit.

Ctrl/Cmd+C on this canvas copies the SELECTION as one thing -- images, movies,
text boxes and inference nodes with the links between them -- through
``moodboard_clipboard.copy_selected``, which keeps the snapshot in this process
and writes it to the shared on-disk copy buffer so a second running Mixar can
paste it too. There is deliberately ONE copy operator and ONE snapshot: media
and nodes used to have separate clipboards behind the same key, resolved by
``poll()``, and the last copy silently won.
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from ....common.utils.platform_utils import format_shortcut
from ...core.moodboard_clipboard import copy_selected
from ...core.media_utils import selected_exportable_media
from ...core.node_duplicate import selected_action_nodes

logger = get_logger(__name__)


def _has_moodboard_selection(scene):
    """True if any media (a node's result included), text box or copyable
    inference node is selected."""
    if selected_exportable_media(scene):
        return True
    if selected_action_nodes(scene):
        return True
    textboxes = getattr(scene, "mixie_moodboard_textboxes", None)
    return bool(textboxes) and any(tb.selected for tb in textboxes)


class MIXIE_OT_moodboard_copy_image(Operator):
    """Copy the selected moodboard items so they can be pasted, here or in another Mixar window"""

    bl_idname = "mixie.moodboard_copy_image"
    bl_label = "Copy"
    bl_description = (
        f"Copy the selected images, videos, text boxes and inference nodes "
        f"(with their connections and results); paste with "
        f"{format_shortcut('V')} in this or another Mixar instance"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _has_moodboard_selection(context.scene)

    def execute(self, context):
        # One snapshot: the in-process clipboard, the on-disk copy buffer for
        # other instances, and (best-effort, inside copy_selected) the first
        # still on the OS clipboard for other applications.
        count = copy_selected(context.scene)
        if count == 0:
            self.report({'WARNING'}, "Nothing selected to copy")
            return {'CANCELLED'}

        noun = "item" if count == 1 else "items"
        self.report({'INFO'}, f"Copied {count} {noun}")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_copy_image,
)
