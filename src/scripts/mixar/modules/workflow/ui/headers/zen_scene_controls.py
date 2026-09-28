# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native controls for the reference Zen scene toolbar."""

import bpy

from ...core import viewport_guides, zen_toolbar_layout as tiers
from ...core.zen_scene import render_samples_binding, sky_enabled


def header_tier(context):
    """Width tier of the viewport's scene toolbar (also valid in its popovers)."""
    area = getattr(context, "area", None)
    header = None
    if area is not None:
        header = next((r for r in area.regions if r.type == "HEADER"), None)
    pixels = header.width if header is not None else getattr(context.region, "width", 0)
    scale = max(float(context.preferences.system.ui_scale), 0.01)
    view = getattr(context, "space_data", None)
    restore = view is not None and not getattr(view, "show_region_tool_header", True)
    return tiers.tier_for_width(pixels / scale, object_controls=restore)


def style(layout, variant="SECONDARY"):
    layout.mixar_style(component="TOOLBAR", variant=variant)


def caption(group, text, width, *, variant="SECONDARY"):
    label = group.row(align=True)
    label.ui_units_x = width / 20
    label.label(text=text)
    style(label, variant)


def draw_render_settings(layout, context, *, vertical=False):
    surface = layout.mixar_surface(theme="ZEN", density="COMPACT")
    controls = surface.column() if vertical else surface.row()
    engine = controls.row(align=True)
    engine.ui_units_x = 10.1
    caption(engine, "Render Engine", 112)
    field = engine.row(align=True)
    field.prop(context.scene.render, "engine", text="")
    style(field)
    if not vertical:
        controls.separator(factor=0.5)
    samples = controls.row(align=True)
    samples.ui_units_x = 13.0
    target = getattr(context.window_manager, "mixar_zen_sample_target", "RENDER")
    selector = samples.row(align=True)
    selector.ui_units_x = 8.0
    if hasattr(context.window_manager, "mixar_zen_sample_target"):
        selector.prop(context.window_manager, "mixar_zen_sample_target", text="")
    else:
        selector.label(text="Render Samples")
    style(selector)
    field = samples.row(align=True)
    binding = render_samples_binding(context.scene, target)
    if binding:
        owner, prop = binding
        field.prop(owner, prop, text="", slider=True)
        style(field)
    else:
        field.enabled = False
        field.label(text="N/A")
        style(field)


def draw_playback(layout, context):
    row = layout.mixar_surface(theme="ZEN").row(align=True)
    row.alignment = "EXPAND"
    row.ui_units_x = 5.8
    row.scale_x = 1.9
    row.operator("screen.keyframe_jump", text="", icon="PREV_KEYFRAME").next = False
    style(row)
    playing = context.screen.is_animation_playing
    row.operator("screen.animation_play", text="", icon="PAUSE" if playing else "PLAY")
    style(row)
    row.operator("screen.keyframe_jump", text="", icon="NEXT_KEYFRAME").next = True
    style(row)


def draw_sky(layout, context):
    row = layout.mixar_surface(theme="ZEN", density="COMPACT").row(align=True)
    row.ui_units_x = 8.6
    row.enabled = context.scene.render.engine in {"CYCLES", "BLENDER_EEVEE"}
    settings = row.row(align=True)
    settings.ui_units_x = 5.0
    if hasattr(bpy.types, "MIXAR_PT_zen_sky"):
        settings.popover(panel="MIXAR_PT_zen_sky", text="Sky Light")
    else:
        settings.label(text="Sky Light")
    style(settings)
    toggle = row.row(align=True)
    toggle.ui_units_x = 2.2
    active = sky_enabled(context.scene)
    if hasattr(bpy.types, "MIXAR_OT_zen_set_sky"):
        toggle.operator("mixar.zen_set_sky", text="ON" if active else "OFF",
                        depress=active).enabled = not active
    else:
        toggle.label(text="OFF")
    style(toggle, "GHOST")
    add = row.row(align=True)
    add.ui_units_x = 1.4
    if hasattr(bpy.types, "MIXAR_OT_zen_load_hdri"):
        add.operator("mixar.zen_load_hdri", text="", icon="ADD")
    else:
        add.label(text="", icon="ADD")
    style(add)


def draw_scenes_button(surface, context):
    """Native rounded hamburger with a sliding Scene label on hover."""
    wm = context.window_manager
    drawer_open = bool(getattr(wm, "mixar_scenes_drawer_target", 0))
    attention = bool(getattr(wm, "mixar_scene_tabs_attention", False))
    scenes = surface.row()
    # Reserve the expanded width; the native layout pass contracts the button
    # and shifts the left lane at rest, sharing actual bounds with hit tests.
    scenes.ui_units_x = 4.1
    scenes.operator("view3d.scenes_drawer_toggle", text="Scene",
                    depress=drawer_open or attention)
    style(scenes)
    surface.separator(factor=0.15)


def draw_left(layout, context, *, tier):
    surface = layout.mixar_surface(theme="ZEN", density="COMPACT").row()
    draw_scenes_button(surface, context)
    add = surface.row()
    add.ui_units_x = 5.8
    add.menu("VIEW3D_MT_add", text="Add Objects")
    style(add, "PRIMARY")
    surface.separator(factor=0.5)
    if tier != tiers.FULL:
        icon_only = tiers.at_most(tier, tiers.NARROW)
        render = surface.row()
        render.ui_units_x = 2.0 if icon_only else 8
        if hasattr(bpy.types, "MIXAR_PT_zen_render_settings"):
            render.popover(panel="MIXAR_PT_zen_render_settings",
                           text="" if icon_only else "Render Settings", icon="SCENE")
        else:
            render.enabled = False
            render.label(text="Render Settings")
        style(render)
    else:
        draw_render_settings(surface, context)

    if not context.space_data.show_region_tool_header:
        restore = surface.row()
        compact = tiers.at_most(tier, tiers.NARROW)
        restore.operator('wm.context_toggle', text='' if compact else 'Object Controls',
                         icon='PREFERENCES').data_path = 'space_data.show_region_tool_header'
        style(restore)


def draw_guides(layout, context):
    """Grid/relationship-lines toggle and the X-ray chip."""
    view = context.space_data
    shading = view.shading
    guides = layout.mixar_surface(theme="ZEN").row(align=True)
    guides.operator(
        "mixar.zen_toggle_guides", text="", icon="GRID",
        depress=viewport_guides.guides_shown(view),
    )
    guides.mixar_style(component="TOOLBAR", variant="GHOST")
    chip = layout.mixar_surface(theme="ZEN").row(align=True)
    chip.enabled = shading.type in {"SOLID", "WIREFRAME"}
    xray_prop = "show_xray_wireframe" if shading.type == "WIREFRAME" else "show_xray"
    chip.prop(shading, xray_prop, text="", icon="XRAY", toggle=True)
    chip.mixar_style(component="TOOLBAR", variant="GHOST")


def draw_right(layout, context, *, tier):
    # Native row spacing is enough between groups; extra separators double it.
    if not tiers.at_most(tier, tiers.TIGHT):
        draw_cinema(layout, context)
    if tiers.overflow_sections(tier) and hasattr(bpy.types, "MIXAR_PT_zen_toolbar_more"):
        more = layout.mixar_surface(theme="ZEN", density="COMPACT").row()
        more.ui_units_x = 2.0
        more.popover(panel="MIXAR_PT_zen_toolbar_more", text="", icon="DOWNARROW_HLT")
        style(more)
    else:
        draw_playback(layout, context)
        draw_sky(layout, context)
        draw_export(layout)


def draw_export(layout):
    export = layout.mixar_surface(theme="ZEN", density="COMPACT").row()
    export.ui_units_x = 4.2
    export.menu("TOPBAR_MT_file_export", text="Export", icon="EXPORT")
    style(export, "PRIMARY")


def draw_cinema(layout, context):
    state = getattr(context.scene, "mixar_director", None)
    if state is None:
        return
    row = layout.mixar_surface(theme="ZEN", density="COMPACT").row()
    row.ui_units_x = 9.0
    active = bool(state.is_directing)
    row.operator("mixar.director_finish" if active else "mixar.director_enter",
                 text="Cinema Mode", icon="CINEMA_REEL", depress=active)
    style(row, "PRIMARY")
