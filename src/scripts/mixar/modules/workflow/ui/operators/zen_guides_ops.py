# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zen Mode header control: show or hide viewport grids and relationship lines."""

from bpy.types import Operator

from ...core.viewport_guides import toggle_guides


def _view3d_space(context):
    space = getattr(context, "space_data", None)
    if space is not None and getattr(space, "type", None) == "VIEW_3D":
        return space
    return None


class MIXAR_OT_zen_toggle_guides(Operator):
    """Show or hide the viewport floor grid and relationship lines together"""

    bl_idname = "mixar.zen_toggle_guides"
    bl_label = "Toggle Grid & Relationship Lines"
    # View state only — not undoable.
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _view3d_space(context) is not None

    def execute(self, context):
        space = _view3d_space(context)
        if space is None:
            return {"CANCELLED"}
        toggle_guides(space)
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()
        return {"FINISHED"}


classes = (MIXAR_OT_zen_toggle_guides,)
