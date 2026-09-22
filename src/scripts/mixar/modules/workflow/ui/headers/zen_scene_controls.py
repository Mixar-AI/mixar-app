# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native controls for the reference Zen scene toolbar."""

import bpy

from ...core.zen_scene import render_samples_binding, sky_enabled


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
        controls.separator(factor=0.8)
    samples = controls.row(align=True)
    samples.ui_units_x = 12.2
    caption(samples, "Render Samples", 124)
    field = samples.row(align=True)
    binding = render_samples_binding(context.scene)
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
    row.alignment = "EXPAND"
    row.ui_units_x = 8.4
    caption(row, "Enable Sky Light", 116, variant="GHOST")
    if not hasattr(bpy.types, "MIXAR_OT_zen_set_sky"):
        row.enabled = False
        row.label(text="OFF")
        style(row, "GHOST")
        return
    row.enabled = context.scene.render.engine in {"CYCLES", "BLENDER_EEVEE"}
    active = sky_enabled(context.scene)
    for enabled, label in ((False, "OFF"), (True, "ON")):
        button = row.row(align=True)
        button.ui_units_x = 1.3
        button.operator("mixar.zen_set_sky", text=label, depress=active == enabled).enabled = enabled
        style(button, "GHOST")


def draw_left(layout, context, *, compact):
    surface = layout.mixar_surface(theme="ZEN", density="COMPACT").row()
    add = surface.row()
    add.ui_units_x = 5.8
    add.menu("VIEW3D_MT_add", text="Add Objects")
    style(add, "PRIMARY")
    surface.separator(factor=0.8)
    if compact:
        render = surface.row()
        render.ui_units_x = 8
        if hasattr(bpy.types, "MIXAR_PT_zen_render_settings"):
            render.popover(panel="MIXAR_PT_zen_render_settings", text="Render Settings", icon="SCENE")
        else:
            render.enabled = False
            render.label(text="Render Settings")
        style(render)
    else:
        draw_render_settings(surface, context)


def draw_right(layout, context, *, compact):
    draw_playback(layout, context)
    layout.separator(factor=0.8)
    if compact:
        sky = layout.mixar_surface(theme="ZEN", density="COMPACT").row()
        sky.ui_units_x = 5.2
        if hasattr(bpy.types, "MIXAR_PT_zen_sky"):
            sky.popover(panel="MIXAR_PT_zen_sky", text="Sky Light", icon="WORLD")
        else:
            sky.enabled = False
            sky.label(text="Sky Light")
        style(sky)
    else:
        draw_sky(layout, context)
    layout.separator(factor=0.8)
    export = layout.mixar_surface(theme="ZEN", density="COMPACT").row()
    export.ui_units_x = 4.2
    export.menu("TOPBAR_MT_file_export", text="Export", icon="EXPORT")
    style(export, "PRIMARY")
