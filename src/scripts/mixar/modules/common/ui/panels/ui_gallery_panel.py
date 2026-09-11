# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from mixar.modules.common.ui.constants import (
    CARD_ROW_ACTION,
    CARD_ROW_CTA,
    CARD_ROW_FIELD,
    DENSITY_COMPACT_SCALE,
)
from mixar.modules.common.ui.operators.ui_gallery_ops import gallery_available


def _chrome_host(layout, fixture):
    """Production chrome host: Compact density, header metrics (no scale_y)."""
    return layout.mixar_surface(theme=fixture.theme, density="COMPACT")


def _tag_topbar(layout, kind, active):
    if hasattr(layout, "mixar_topbar_element"):
        layout.mixar_topbar_element(kind=kind, active=active)


def _draw_chrome_preview(layout, fixture):
    """Production topbar widgets at header metrics — not Compact ``scale_y``."""
    host = _chrome_host(layout, fixture)
    host.separator()
    host.label(text="Topbar chrome (UI.svg recipe)")
    slider = host.row(align=True)
    left = slider.row(align=True)
    left.ui_units_x = 5.5
    left.operator("mixar.ui_gallery_action", text="Zen")
    _tag_topbar(left, "MODE_SLIDER_LEFT", fixture.enabled)
    right = slider.row(align=True)
    right.ui_units_x = 5.5
    right.operator("mixar.ui_gallery_action", text="Engine")
    _tag_topbar(right, "MODE_SLIDER_RIGHT", not fixture.enabled)
    pills = host.row(align=True)
    cinema = pills.row(align=True)
    cinema.ui_units_x = 7.5
    cinema.operator("mixar.ui_gallery_action", text="Cinema Mode")
    _tag_topbar(cinema, "CINEMA_PILL", fixture.enabled)
    solid = pills.row(align=True)
    solid.ui_units_x = 6.5
    solid.operator("mixar.ui_gallery_action", text="Solid")
    _tag_topbar(solid, "VIEWPORT_PILL", True)
    rendered = pills.row(align=True)
    rendered.ui_units_x = 6.5
    rendered.operator("mixar.ui_gallery_action", text="Rendered")
    _tag_topbar(rendered, "VIEWPORT_PILL", False)


def _draw_card_actions_preview(layout, fixture):
    """Shared profile/dialog action recipes at header metrics."""
    host = _chrome_host(layout, fixture)
    host.separator()
    host.label(text="Card actions (profile and dialogs)")
    row = host.row(align=True)
    for kind, text in (
        ("ACCENT", "Accent"),
        ("CARD", "Card"),
        ("DANGER", "Danger"),
        ("GHOST", "Ghost"),
    ):
        item = row.row(align=True)
        item.operator("mixar.ui_gallery_action", text=text)
        if hasattr(item, "mixar_card_button"):
            item.mixar_card_button(kind=kind)


def _draw_card_labels_preview(layout, fixture):
    """Shared heading, plan-chip and divider recipes at header metrics."""
    host = _chrome_host(layout, fixture)
    host.separator()
    host.label(text="Card labels (heading, pill, divider)")
    if not hasattr(host, "mixar_card_label"):
        return
    row = host.row(align=True)
    heading = row.row(align=True)
    heading.mixar_card_label(text="Heading", kind="HEADING")
    pill = row.row(align=True)
    pill.alignment = "RIGHT"
    pill.mixar_card_label(text="Pill", kind="PILL")
    divider = host.row()
    divider.mixar_card_label(text="", kind="DIVIDER")


def _draw_card_rows_preview(layout, fixture):
    """Shared dialog field, footer and profile-grid row scales."""
    host = _chrome_host(layout, fixture)
    host.separator()
    host.label(text="Card rows (field, footer, grid)")
    host.label(text="Field")
    field = host.row(align=True)
    field.scale_y = CARD_ROW_FIELD
    if hasattr(field, "mixar_input"):
        field.mixar_input(fixture, "text", text="")
    else:
        field.prop(fixture, "text", text="")
    footer = host.row(align=True)
    footer.scale_y = CARD_ROW_CTA
    cancel = footer.row(align=True)
    cancel.operator("mixar.ui_gallery_action", text="Footer")
    if hasattr(cancel, "mixar_card_button"):
        cancel.mixar_card_button(kind="GHOST")
    confirm = footer.row(align=True)
    confirm.operator("mixar.ui_gallery_action", text="Confirm")
    if hasattr(confirm, "mixar_card_button"):
        confirm.mixar_card_button(kind="ACCENT")
    grid = host.row(align=True)
    grid.scale_y = CARD_ROW_ACTION
    grid.operator("mixar.ui_gallery_action", text="Grid")
    if hasattr(grid, "mixar_card_button"):
        grid.mixar_card_button(kind="CARD")


def draw_gallery(layout, context):
    fixture = context.window_manager.mixar_ui_gallery
    layout.prop(fixture, "theme")
    layout.prop(fixture, "density")
    layout.label(text=f"Local actions: {fixture.clicks} · no service calls")
    surface = layout.mixar_surface(theme=fixture.theme, density=fixture.density)
    if fixture.density == "COMPACT":
        # Matches MixarDensity::Compact / Default control-height ratio.
        surface.scale_y = DENSITY_COMPACT_SCALE
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
    native = surface.mixar_surface(theme="NATIVE", density=fixture.density)
    native.label(text="Nested Native override")
    native.mixar_input(fixture, "text")
    surface.mixar_input(fixture, "text", text="Parent scope after override")
    layout.prop(fixture, "text", text="Unstyled sibling")
    _draw_chrome_preview(layout, fixture)
    _draw_card_actions_preview(layout, fixture)
    _draw_card_labels_preview(layout, fixture)
    _draw_card_rows_preview(layout, fixture)


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
