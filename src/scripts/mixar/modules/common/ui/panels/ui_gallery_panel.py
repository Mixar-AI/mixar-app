# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from mixar.modules.common.ui.operators.ui_gallery_ops import gallery_available


def draw_gallery(layout, context):
    fixture = context.window_manager.mixar_ui_gallery
    layout.prop(fixture, "theme")
    layout.label(text=f"Local actions: {fixture.clicks} · no service calls")
    surface = layout.mixar_surface(theme=fixture.theme)
    surface.use_property_split = False
    actions = surface.row(align=True)
    for variant in ("PRIMARY", "SECONDARY", "GHOST", "DANGER"):
        item = actions.column()
        item.mixar_operator("mixar.ui_gallery_action", text=variant.title())
        item.mixar_style(component="ACTION", variant=variant)
    disabled = surface.row()
    disabled.enabled = False
    disabled.mixar_operator("mixar.ui_gallery_action", text="Disabled action")
    surface.mixar_operator("mixar.ui_gallery_action", text="Queued (2) — still enabled")
    card = surface.row()
    card.operator("mixar.ui_gallery_action", text="Selectable surface", depress=fixture.enabled)
    card.mixar_style(component="SURFACE")
    surface.mixar_toggle(fixture, "enabled")
    surface.mixar_dropdown(fixture, "choice")
    segments = surface.row(align=True)
    for item in fixture.bl_rna.properties["choice"].enum_items:
        col = segments.column()
        col.prop_enum(fixture, "choice", item.identifier)
        col.mixar_style(component="SEGMENT")
    for name in ("count", "factor"):
        row = surface.row()
        row.prop(fixture, name, slider=name == "factor")
        row.mixar_style(component="NUMBER")
    surface.mixar_input(fixture, "text")
    surface.mixar_input(fixture, "empty")
    multiline = surface.column()
    multiline.scale_y = 3.5
    multiline.mixar_input(fixture, "prompt", text="", multiline=True)
    native = surface.mixar_surface(theme="NATIVE")
    native.label(text="Nested Native override")
    native.mixar_input(fixture, "text")
    surface.mixar_input(fixture, "text", text="Parent scope after override")
    layout.prop(fixture, "text", text="Unstyled sibling")


class MIXAR_PT_ui_gallery(bpy.types.Panel):
    bl_label = "Mixar UI Gallery"
    bl_idname = "MIXAR_PT_ui_gallery"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Developer"

    @classmethod
    def poll(cls, context):
        return gallery_available(context)

    def draw(self, context):
        draw_gallery(self.layout, context)


classes = (MIXAR_PT_ui_gallery,)
