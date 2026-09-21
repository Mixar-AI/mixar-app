# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The same template action for the editor and sliding canvas."""

import bpy
from bpy.types import Operator

from ...constants import NODE_TEMPLATES
from ...core.canvas_context import (
    find_moodboard_canvas_region,
    is_moodboard_context,
    redraw_moodboard_canvases,
)


class MIXIE_OT_moodboard_add_template(Operator):
    bl_idname = "mixie.moodboard_add_template"
    bl_label = "Add Node Template"
    bl_description = "Add an editable draft; generation starts only when you press Generate"
    bl_options = {'UNDO'}

    template: bpy.props.EnumProperty(
        items=[(key, label, "Add an editable " + label.lower() + " node", icon, index)
               for index, (key, label, icon, _capability) in enumerate(NODE_TEMPLATES)],
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return is_moodboard_context(context)

    def execute(self, context):
        from ...core.node_templates import create_template
        from ...core.moodboard_utils import ensure_moodboard_region_visible

        region = find_moodboard_canvas_region(context)
        if region is None:
            return {'CANCELLED'}
        center = region.view2d.region_to_view(region.width * .5, region.height * .5)
        try:
            node = create_template(context.scene, self.template, center)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        context.scene.mixie_moodboard_link_drop_active = False
        ensure_moodboard_region_visible(
            node.position_x, node.position_y, node.width, node.height,
        )
        redraw_moodboard_canvases()
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_add_template,)
