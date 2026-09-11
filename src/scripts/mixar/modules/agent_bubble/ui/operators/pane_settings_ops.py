# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Native popup over the same catalog parameter groups as the island strips."""
import bpy
from bpy.props import StringProperty

from mixar.modules.common.generation_params import draw_service_params, has_params


class MIXAR_OT_pane_generation_settings(bpy.types.Operator):
    bl_idname = "mixar.pane_generation_settings"
    bl_label = "Generation Settings"
    bl_description = "Edit all available settings for this generation model"

    service_key: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    model_slug: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'AGENT_BUBBLE'

    def invoke(self, context, _event):
        if not has_params(self.service_key, self.model_slug):
            self.report({'INFO'}, "Generation settings are unavailable; reload the catalog")
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=460)

    def check(self, _context):
        # Native popup layouts rebuild after edits only when check requests it.
        # This keeps schema visible_if/grouping current without a redraw timer.
        return True

    def draw(self, _context):
        surface = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        surface.label(text="Generation Settings")
        # The schema renderer owns order, grouping and visible_if. Values bind
        # directly to the existing WM group; closing the popup keeps edits.
        if not draw_service_params(surface, self.service_key, self.model_slug):
            surface.label(text="Settings are no longer available", icon='INFO')

    def execute(self, _context):
        return {'FINISHED'}


classes = (MIXAR_OT_pane_generation_settings,)
