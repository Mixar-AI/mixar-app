# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Undoable scene sky lighting, shared by the header and compact popover."""

import bpy
from bpy.props import BoolProperty

from ...core.zen_scene import set_sky_enabled


class MIXAR_OT_zen_set_sky(bpy.types.Operator):
    bl_idname = "mixar.zen_set_sky"
    bl_label = "Enable Sky Light"
    bl_description = ("Use a procedural sky for scene lighting in renders; "
                      "Off restores the previous world. Visible in Material Preview "
                      "and Rendered shading with Scene World enabled")
    bl_options = {"REGISTER", "UNDO"}

    enabled: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.scene.is_editable

    def execute(self, context):
        try:
            set_sky_enabled(context.scene, self.enabled)
        except (RuntimeError, TypeError, AttributeError) as exc:
            self.report({"ERROR"}, f"Could not change sky lighting: {exc}")
            return {"CANCELLED"}
        areas = context.screen.areas if context.screen else ()
        if self.enabled:
            # Make the scene lighting visible in both preview modes. Solid
            # and Wireframe keep their native, unlit display.
            for area in areas:
                if area.type == "VIEW_3D":
                    area.spaces.active.shading.use_scene_world = True
                    area.spaces.active.shading.use_scene_world_render = True
        for area in areas:
            area.tag_redraw()
        return {"FINISHED"}


classes = (MIXAR_OT_zen_set_sky,)
