# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Top-strip control: show or hide the viewport's grid lines."""

from bpy.types import Operator

from ...core.viewport import find_view3d_context, toggle_grid


def _view3d_target(context):
    """``(area, space)`` for the Director viewport, or ``(None, None)``."""
    target = find_view3d_context(context)
    if target is not None:
        _window, area, _region, space = target
        return area, space
    space = getattr(context, "space_data", None)
    if space is not None and getattr(space, "type", None) == 'VIEW_3D':
        return getattr(context, "area", None), space
    return None, None


class MIXAR_OT_director_toggle_grid(Operator):
    """Show or hide the viewport's grid lines (floor grid and X/Y axes)"""

    bl_idname = "mixar.director_toggle_grid"
    bl_label = "Toggle Grid"
    # View state only: not undoable, and it must work before any shot exists.
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _view3d_target(context)[1] is not None

    def execute(self, context):
        area, space = _view3d_target(context)
        if space is None:
            return {'CANCELLED'}
        toggle_grid(space)
        if area is not None:
            area.tag_redraw()
        return {'FINISHED'}


classes = (MIXAR_OT_director_toggle_grid,)
