# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The same template action for the editor and sliding canvas."""

import bpy
from bpy.types import Operator

from ...constants import GRAPH_NODE_ID_MAXLEN, NODE_TEMPLATES
from ...core.canvas_context import (
    find_moodboard_canvas_region,
    is_moodboard_context,
    redraw_moodboard_canvases,
)
from ...core.workflow_templates import WORKFLOW_TEMPLATES, is_workflow


def _template_description(key, label):
    return (WORKFLOW_TEMPLATES.get(key, {}).get('description')
            or "Add an editable " + label.lower() + " node")


class MIXIE_OT_moodboard_add_template(Operator):
    bl_idname = "mixie.moodboard_add_template"
    bl_label = "Add Node Template"
    bl_description = "Click to add a draft, or drag a shortcut onto the canvas to place it"
    bl_options = {'UNDO'}

    template: bpy.props.EnumProperty(
        items=[(key, label, _template_description(key, label), icon, index)
               for index, (key, label, icon, _capability) in enumerate(NODE_TEMPLATES)],
        options={'SKIP_SAVE'},
    )
    from_drop: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    drop_x: bpy.props.FloatProperty(options={'HIDDEN', 'SKIP_SAVE'})
    drop_y: bpy.props.FloatProperty(options={'HIDDEN', 'SKIP_SAVE'})
    # A continuation from an image output names its image; workflows read it.
    source_node_id: bpy.props.StringProperty(
        default="", maxlen=GRAPH_NODE_ID_MAXLEN, options={'HIDDEN', 'SKIP_SAVE'},
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
        center = ((self.drop_x, self.drop_y) if self.from_drop else
                  region.view2d.region_to_view(region.width * .5, region.height * .5))
        try:
            node = create_template(context.scene, self.template, center,
                                   exact_position=self.from_drop,
                                   source_node_id=self.source_node_id)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        context.scene.mixie_moodboard_link_drop_active = False
        # Drops never pan or zoom, except a workflow: its frame is far larger
        # than the view and would otherwise land mostly off-screen.
        if not self.from_drop or is_workflow(self.template):
            ensure_moodboard_region_visible(
                node.position_x, node.position_y, node.width, node.height,
            )
        redraw_moodboard_canvases()
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_add_template,)
