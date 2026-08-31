# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Align, distribute and tidy operators for moodboard nodes.

Thin wrappers: the arrangement itself lives in ``core.node_layout``, which is
``bpy``-free position math and is unit-tested directly.
"""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.core import node_layout


def _tag_redraw(context):
    area = getattr(context, "area", None)
    if area is not None:
        area.tag_redraw()


def _poll_nodes(context) -> bool:
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    return bool(node_layout.layout_targets(scene))


class MIXIE_OT_moodboard_align_nodes(Operator):
    """Line the selected nodes up on one edge"""

    bl_idname = "mixie.moodboard_align_nodes"
    bl_label = "Align Nodes"
    bl_description = "Line the selected nodes up on one edge"
    bl_options = {'REGISTER', 'UNDO'}

    # SKIP_SAVE: REGISTER operators refill unset properties from the previous
    # run, so a menu entry that forgot to set this would silently repeat the
    # last alignment the user picked.
    edge: bpy.props.EnumProperty(
        items=[
            ('LEFT', "Left", "Align left edges"),
            ('RIGHT', "Right", "Align right edges"),
            ('TOP', "Top", "Align top edges"),
            ('BOTTOM', "Bottom", "Align bottom edges"),
            ('CENTER_X', "Centre Horizontally", "Align horizontal centres"),
            ('CENTER_Y', "Centre Vertically", "Align vertical centres"),
        ],
        default='LEFT',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _poll_nodes(context)

    def execute(self, context):
        moved = node_layout.align_nodes(
            node_layout.layout_targets(context.scene), self.edge
        )
        if not moved:
            self.report({'WARNING'}, "Select at least two nodes to align")
            return {'CANCELLED'}
        _tag_redraw(context)
        self.report({'INFO'}, f"Aligned {moved} node(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_distribute_nodes(Operator):
    """Even out the gaps between the selected nodes"""

    bl_idname = "mixie.moodboard_distribute_nodes"
    bl_label = "Distribute Nodes"
    bl_description = "Space the selected nodes evenly along one axis"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(
        items=[
            ('X', "Horizontally", "Even the horizontal gaps"),
            ('Y', "Vertically", "Even the vertical gaps"),
        ],
        default='X',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _poll_nodes(context)

    def execute(self, context):
        moved = node_layout.distribute_nodes(
            node_layout.layout_targets(context.scene), self.axis
        )
        if not moved:
            self.report({'WARNING'}, "Select at least three nodes to distribute")
            return {'CANCELLED'}
        _tag_redraw(context)
        self.report({'INFO'}, f"Distributed {moved} node(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_tidy_nodes(Operator):
    """Lay the nodes out in the order the graph flows"""

    bl_idname = "mixie.moodboard_tidy_nodes"
    bl_label = "Tidy Nodes"
    bl_description = (
        "Arrange nodes into columns following their connections. Acts on the "
        "selection when several nodes are selected, otherwise the whole board. "
        "Reference images and text boxes are left where they are"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_nodes(context)

    def execute(self, context):
        scene = context.scene
        moved = node_layout.tidy_nodes(scene, node_layout.layout_targets(scene))
        if not moved:
            self.report({'WARNING'}, "Nothing to tidy")
            return {'CANCELLED'}
        _tag_redraw(context)
        self.report({'INFO'}, f"Tidied {moved} node(s)")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_align_nodes,
    MIXIE_OT_moodboard_distribute_nodes,
    MIXIE_OT_moodboard_tidy_nodes,
)
