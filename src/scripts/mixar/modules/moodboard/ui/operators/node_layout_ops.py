# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Align, distribute and tidy operators for the moodboard canvas.

Thin wrappers: the arrangement itself lives in ``core.node_layout``, which is
position math over plain objects and is unit-tested directly.
"""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.core import node_layout


def _tag_redraw(context):
    area = getattr(context, "area", None)
    if area is not None:
        area.tag_redraw()


def _poll_nodes(context) -> bool:
    """Arranging needs two things to arrange, whatever kind they are."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    return len(node_layout.layout_targets(scene)) >= 2


class MIXIE_OT_moodboard_align_nodes(Operator):
    """Line the selected items up on one edge"""

    bl_idname = "mixie.moodboard_align_nodes"
    bl_label = "Align Items"
    bl_description = (
        "Line up the selected items on one edge. Acts on the selection when "
        "several items are selected, otherwise on everything on the board"
    )
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
            self.report({'WARNING'}, "Nothing to align: the board needs two items")
            return {'CANCELLED'}
        _tag_redraw(context)
        self.report({'INFO'}, f"Aligned {moved} item(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_distribute_nodes(Operator):
    """Even out the gaps between the selected items"""

    bl_idname = "mixie.moodboard_distribute_nodes"
    bl_label = "Distribute Items"
    bl_description = (
        "Space the selected items evenly along one axis. Acts on the "
        "selection when several items are selected, otherwise on everything "
        "on the board"
    )
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
            self.report(
                {'WARNING'}, "Nothing to distribute: the board needs three items"
            )
            return {'CANCELLED'}
        _tag_redraw(context)
        self.report({'INFO'}, f"Distributed {moved} item(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_tidy_nodes(Operator):
    """Lay the board out in the order the graph flows"""

    bl_idname = "mixie.moodboard_tidy_nodes"
    bl_label = "Tidy"
    bl_description = (
        "Arrange the board into columns following the connections between "
        "nodes. Acts on the selection when several items are selected, "
        "otherwise on everything on the board"
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
        self.report({'INFO'}, f"Tidied {moved} item(s)")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_align_nodes,
    MIXIE_OT_moodboard_distribute_nodes,
    MIXIE_OT_moodboard_tidy_nodes,
)
