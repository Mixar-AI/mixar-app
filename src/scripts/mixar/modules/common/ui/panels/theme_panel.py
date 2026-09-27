# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Expose native Mixar colors beside Blender's existing theme editors."""

from bpy.types import Panel


def color_group(identifier):
    """Group every shared RNA slot, including future active slots."""
    name = identifier.removeprefix("mixar_")
    if name.startswith("gradient_") or name in {"ink", "brand", "brand_text"}:
        return "Actions & Generation"
    if name.startswith("cinema_"):
        return "Cinema Mode"
    if name.startswith(("slider_", "viewport_", "profile_", "toolbar_")):
        return "Toolbar & Account"
    if name.startswith(("text", "fg_")) or name == "glyph":
        return "Text & Icons"
    if name in {"focus", "primary", "selected", "danger", "warning"}:
        return "Selection & Feedback"
    return "Surfaces & Controls"


def draw_colors(layout, data, identifiers):
    layout.use_property_split = True
    layout.use_property_decorate = False
    for identifier in identifiers:
        layout.prop(data, identifier)


class MIXAR_PT_theme_preferences(Panel):
    bl_label = "Mixar"
    bl_idname = "MIXAR_PT_theme_preferences"
    bl_space_type = 'PREFERENCES'
    bl_region_type = 'WINDOW'
    bl_context = "themes"
    bl_parent_id = "USERPREF_PT_theme"

    def draw(self, context):
        layout = self.layout
        theme = context.preferences.themes[0]
        layout.label(text="Shared across Zen, Engine and Texturing workspaces.")
        layout.operator("mixar.apply_forest_theme", text="Apply Mixar Forest", icon='BRUSH_DATA')
        header, body = layout.panel("mixar_theme_canvases", default_closed=False)
        header.label(text="Workspace Backgrounds")
        if body:
            body.use_property_split = True
            body.use_property_decorate = False
            body.prop(theme.view_3d.space.gradients, "background_type", text="Viewport Style")
            body.prop(theme.view_3d.space.gradients, "high_gradient", text="Viewport (Zen & Engine)")
            body.prop(theme.view_3d.space.gradients, "gradient", text="Viewport Gradient")
            body.prop(theme.mixie.space, "back", text="Moodboard (Zen & Panel)")
            body.operator("mixar.apply_forest_backgrounds", icon='LOOP_BACK')
            body.label(text="Defaults: Viewport #0F0F0F · Moodboard #1E1E1E")
        groups = {}
        for prop in theme.user_interface.bl_rna.properties:
            if prop.identifier.startswith("mixar_") and not prop.is_hidden:
                groups.setdefault(color_group(prop.identifier), []).append(prop.identifier)
        for title, identifiers in groups.items():
            header, body = layout.panel("mixar_theme_" + title, default_closed=True)
            header.label(text=title)
            if body:
                draw_colors(body, theme.user_interface, identifiers)
        for title, data, prefixes in (
            ("Agent Island", theme.agent_bubble, ("agent_",)),
            ("Chat", theme.mixie_chat, ("chat_",)),
            ("Moodboard", theme.mixie, ("mixar_", "moodboard_")),
        ):
            header, body = layout.panel("mixar_theme_" + title, default_closed=True)
            header.label(text=title)
            if body:
                draw_colors(body, data, [
                    p.identifier for p in data.bl_rna.properties
                    if p.identifier.startswith(prefixes) and not p.is_hidden
                ])


classes = (MIXAR_PT_theme_preferences,)
