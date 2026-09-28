# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compact Zen toolbar popovers retain all scene controls on small windows."""

import bpy

from ..headers.zen_scene_controls import (
    draw_cinema, draw_export, draw_guides, draw_playback, draw_render_settings, draw_sky,
    header_tier,
)
from ...core.zen_toolbar_layout import overflow_sections
from ...core.zen_scene import sky_enabled
from ...core.zen_sky_lighting import sky_nodes, uses_hdri


class MIXAR_PT_zen_render_settings(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Render Settings"
    bl_ui_units_x = 18

    def draw(self, context):
        draw_render_settings(self.layout, context, vertical=True)


class MIXAR_PT_zen_toolbar_more(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Scene Controls"
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        # Whatever the current width tier moved out of the toolbar, in order.
        draw = {
            "CINEMA": lambda: draw_cinema(layout, context),
            "GUIDES": lambda: draw_guides(layout.row(), context),
            "PLAYBACK": lambda: draw_playback(layout, context),
            "SKY": lambda: draw_sky(layout, context),
            "EXPORT": lambda: draw_export(layout),
        }
        for section in overflow_sections(header_tier(context)) or ("PLAYBACK", "SKY", "EXPORT"):
            draw[section]()


class MIXAR_PT_zen_sky(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Sky Light"
    bl_ui_units_x = 14

    def draw(self, context):
        layout = self.layout
        layout.enabled = context.scene.render.engine in {"CYCLES", "BLENDER_EEVEE"}
        nodes = sky_nodes(context.scene)
        if not nodes:
            layout.operator("mixar.zen_set_sky", text="Enable Sky Light").enabled = True
            layout.operator("mixar.zen_load_hdri", text="Add HDRI", icon="ADD")
            return
        if not sky_enabled(context.scene):
            layout.label(text="Lighting is off", icon="INFO")
        hdri = uses_hdri(context.scene)
        source = layout.row(align=True)
        source.operator("mixar.zen_sky_source", text="Sky", depress=not hdri).hdri = False
        choice = source.row(align=True)
        environment = nodes.get("ShaderNodeTexEnvironment")
        choice.enabled = bool(environment and environment.image)
        choice.operator("mixar.zen_sky_source", text="HDRI", depress=hdri).hdri = True
        layout.use_property_split = True
        layout.use_property_decorate = False
        background = nodes.get("ShaderNodeBackground")
        if background:
            layout.prop(background.inputs["Strength"], "default_value", text="Strength")
        if hdri:
            layout.label(text=environment.image.name, icon="IMAGE_DATA")
            mapping = nodes.get("ShaderNodeMapping")
            if mapping:
                layout.prop(mapping.inputs["Rotation"], "default_value", index=2, text="Rotation")
            layout.operator("mixar.zen_load_hdri", text="Replace HDRI", icon="FILE_FOLDER")
        else:
            sky = nodes.get("ShaderNodeTexSky")
            if sky:
                if sky.sky_type in {"SINGLE_SCATTERING", "MULTIPLE_SCATTERING"}:
                    layout.prop(sky, "sun_elevation", text="Sun Elevation")
                    layout.prop(sky, "sun_rotation", text="Sun Rotation")
                    layout.prop(sky, "sun_size", text="Sun Size")
                else:
                    layout.prop(sky, "sun_direction", text="Sun Direction")
                    layout.prop(sky, "turbidity", text="Haze")
        layout.label(text="Visible in Material Preview and Rendered.")


classes = (MIXAR_PT_zen_render_settings, MIXAR_PT_zen_toolbar_more, MIXAR_PT_zen_sky)
