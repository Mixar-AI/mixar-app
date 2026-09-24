# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicate operator for moodboard inference nodes.

Duplicating a node is Shift+D, and that is the only node-level clipboard-ish
gesture there is. Ctrl/Cmd+C and +V on the canvas belong to MEDIA: with a node
selected they copy the image or video that node generated, so it can be pasted
back as an ordinary board item or into another application. Node copy/paste
operators used to share those keys and resolve by ``poll()``; two meanings on
one binding is a worse deal than one obvious one.
"""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.core import node_duplicate


def _tag_redraw(context):
    area = getattr(context, "area", None)
    if area is not None:
        area.tag_redraw()


class MIXIE_OT_moodboard_duplicate_nodes(Operator):
    """Duplicate the selected inference nodes"""

    bl_idname = "mixie.moodboard_duplicate_nodes"
    bl_label = "Duplicate Nodes"
    bl_description = (
        "Duplicate the selected inference nodes with their connections and "
        "generated media, then move them into place"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return False
        return bool(node_duplicate.selected_action_nodes(scene))

    def execute(self, context):
        created = node_duplicate.duplicate_selected_nodes(context.scene)
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
    MIXIE_OT_moodboard_duplicate_nodes,
)
