# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Copy / paste / duplicate operators for moodboard inference nodes.

Copy and paste share Ctrl+C / Ctrl+V with the board's image copy/paste. They
resolve by ``poll()``, not by a modifier of their own: Blender skips a keymap
item whose operator cannot poll and tries the next matching one, so with a node
selected the node operator runs and otherwise the image one does -- one binding,
two meanings, no ordering trickery. Their keymap items are registered BEFORE the
image ones so they get first refusal.
"""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.core import node_clipboard


def _tag_redraw(context):
    area = getattr(context, "area", None)
    if area is not None:
        area.tag_redraw()


class MIXIE_OT_moodboard_copy_nodes(Operator):
    """Copy the selected inference nodes"""

    bl_idname = "mixie.moodboard_copy_nodes"
    bl_label = "Copy Nodes"
    bl_description = "Copy the selected inference nodes, with their connections"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return False
        return bool(node_clipboard.selected_action_nodes(scene))

    def execute(self, context):
        count = node_clipboard.copy_nodes(context.scene)
        if not count:
            self.report({'WARNING'}, "No inference nodes selected")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Copied {count} node(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_paste_nodes(Operator):
    """Paste copied inference nodes at the cursor"""

    bl_idname = "mixie.moodboard_paste_nodes"
    bl_label = "Paste Nodes"
    bl_description = "Paste the copied inference nodes, with their connections"
    bl_options = {'REGISTER', 'UNDO'}

    # SKIP_SAVE: this is a REGISTER operator, so a property the caller leaves
    # unset is re-filled from the last run -- a remembered cursor would drop
    # every later paste at the position of the first one.
    use_cursor: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    cursor_x: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE'})
    cursor_y: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        # Falls through to the image paste when no nodes were copied.
        return node_clipboard.has_content()

    def invoke(self, context, event):
        region = getattr(context, "region", None)
        if region is not None and hasattr(region, "view2d"):
            try:
                self.cursor_x, self.cursor_y = region.view2d.region_to_view(
                    event.mouse_region_x, event.mouse_region_y
                )
                self.use_cursor = True
            except (AttributeError, TypeError):
                self.use_cursor = False
        return self.execute(context)

    def execute(self, context):
        anchor = (self.cursor_x, self.cursor_y) if self.use_cursor else None
        created = node_clipboard.paste_nodes(context.scene, anchor=anchor)
        if not created:
            self.report({'WARNING'}, "Nothing to paste")
            return {'CANCELLED'}
        _tag_redraw(context)
        self.report({'INFO'}, f"Pasted {len(created)} node(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_duplicate_nodes(Operator):
    """Duplicate the selected inference nodes"""

    bl_idname = "mixie.moodboard_duplicate_nodes"
    bl_label = "Duplicate Nodes"
    bl_description = (
        "Duplicate the selected inference nodes with their connections, then "
        "move them into place"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return False
        return bool(node_clipboard.selected_action_nodes(scene))

    def execute(self, context):
        created = node_clipboard.duplicate_selected_nodes(context.scene)
        if not created:
            self.report({'WARNING'}, "No inference nodes selected")
            return {'CANCELLED'}
        _tag_redraw(context)
        self.report({'INFO'}, f"Duplicated {len(created)} node(s) - move to position")
        # The copies land on top of the originals; grab mode places them, the
        # same hand-off Shift+D and image duplication use.
        bpy.ops.mixie.moodboard_grab('INVOKE_DEFAULT')
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_copy_nodes,
    MIXIE_OT_moodboard_paste_nodes,
    MIXIE_OT_moodboard_duplicate_nodes,
)
