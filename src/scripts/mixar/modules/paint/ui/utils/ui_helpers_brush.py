# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Brush properties panel.

Shows brush properties when a Paint Layer is active, matching Blender's
Active Tool and Workspace Settings panel layout.
"""

import bpy
from bl_ui.properties_paint_common import BrushAssetShelf


def _get_ui_state(context):
    """Get MixarUIState from context."""
    wm = context.window_manager
    return wm.mixar_ui if hasattr(wm, 'mixar_ui') else None


def _draw_collapsible_header(layout, ui_state, prop_name, label, icon=None, default=False):
    """Draw a collapsible section header.

    Returns True if expanded, False if collapsed.
    """
    expanded = getattr(ui_state, prop_name, default) if ui_state else default
    arrow = 'DOWNARROW_HLT' if expanded else 'RIGHTARROW'

    row = layout.row(align=True)
    if ui_state:
        row.prop(ui_state, prop_name, text="", icon=arrow, emboss=False)
    else:
        row.label(text="", icon=arrow)

    if icon:
        row.label(text=label, icon=icon)
    else:
        row.label(text=label)

    return expanded


def draw_full_brush_properties(context, layout, layer):
    """Draw brush properties for Paint Layers.

    Args:
        context: Blender context
        layout: UI layout
        layer: Backend YLayer (Paint Layer)
    """
    # Only for IMAGE (Paint) layers
    if layer.type != 'IMAGE':
        return

    # Only in texture paint mode
    if context.mode != 'PAINT_TEXTURE':
        return

    # Check for valid brush
    if not hasattr(context, 'tool_settings') or not context.tool_settings.image_paint:
        return

    settings = context.tool_settings.image_paint
    brush = settings.brush
    if not brush:
        return

    ups = settings.unified_paint_settings
    ui_state = _get_ui_state(context)

    # ========== BRUSH ASSET ==========
    box = layout.box()
    header = box.row()
    label = "Brush Asset"
    if brush.has_unsaved_changes:
        label = "Brush Asset (Unsaved)"
    header.label(text=label)
    header.menu("VIEW3D_MT_brush_context_menu", icon='DOWNARROW_HLT', text="")

    row = box.row()
    col = row.column(align=True)
    BrushAssetShelf.draw_popup_selector(col, context, brush, show_name=False)
    col.prop(brush, "name", text="")

    layout.separator()

    # ========== BRUSH SETTINGS ==========
    box = layout.box()
    box.label(text="Brush Settings", icon='BRUSH_DATA')

    col = box.column()
    col.use_property_split = True
    col.use_property_decorate = False

    col.prop(brush, "blend", text="Blend")

    # Size
    row = col.row(align=True)
    if ups.use_unified_size:
        row.prop(ups, "size", slider=True)
    else:
        row.prop(brush, "size", slider=True)
    row.prop(ups, "use_unified_size", text="", icon='BRUSHES_ALL')
    row.prop(brush, "use_pressure_size", text="", icon='STYLUS_PRESSURE')

    # Strength
    row = col.row(align=True)
    if ups.use_unified_strength:
        row.prop(ups, "strength", slider=True)
    else:
        row.prop(brush, "strength", slider=True)
    row.prop(ups, "use_unified_strength", text="", icon='BRUSHES_ALL')
    row.prop(brush, "use_pressure_strength", text="", icon='STYLUS_PRESSURE')

    layout.separator()

    # ========== COLOR PICKER ==========
    if brush.image_paint_capabilities.has_color:
        box = layout.box()
        box.label(text="Color Picker", icon='COLOR')

        col = box.column()

        # Color/Gradient toggle
        row = col.row()
        row.prop(brush, "color_type", expand=True)

        if brush.color_type == 'COLOR':
            # Color wheel
            if ups.use_unified_color:
                col.template_color_picker(ups, "color", value_slider=True)
            else:
                col.template_color_picker(brush, "color", value_slider=True)

            # Color swatches row
            row = col.row(align=True)
            if ups.use_unified_color:
                row.prop(ups, "color", text="")
                row.prop(ups, "secondary_color", text="")
            else:
                row.prop(brush, "color", text="")
                row.prop(brush, "secondary_color", text="")
            row.separator()
            # Image picker for brush texture
            # Check for both texture existence AND image to avoid black painting
            if brush.texture and brush.texture.image:
                row.template_ID(brush.texture, "image", open="image.open")
                row.operator("wm.m_clear_brush_texture", text="", icon='X')
            else:
                row.operator("wm.m_open_image_to_brush_texture", text="", icon='IMAGE_DATA')
            row.prop(ups, "use_unified_color", text="", icon='BRUSHES_ALL')

            # Randomize Color (collapsible)
            col.separator()
            if _draw_collapsible_header(col, ui_state, 'expand_color_picker', "Randomize Color"):
                sub = col.column(align=True)
                sub.active = brush.use_color_as_displacement if hasattr(brush, 'use_color_as_displacement') else True
                if hasattr(brush, 'color_jitter_h'):
                    sub.prop(brush, "color_jitter_h", slider=True, text="Hue")
                    sub.prop(brush, "color_jitter_s", slider=True, text="Saturation")
                    sub.prop(brush, "color_jitter_v", slider=True, text="Value")

        elif brush.color_type == 'GRADIENT':
            col.template_color_ramp(brush, "gradient", expand=True)
            col.use_property_split = True
            col.prop(brush, "gradient_stroke_mode", text="Mode")

        # Color Palette (collapsible)
        col.separator()
        if _draw_collapsible_header(col, ui_state, 'expand_color_palette', "Color Palette"):
            sub = col.column()
            sub.template_ID(settings, "palette", new="palette.new")
            if settings.palette:
                sub.template_palette(settings, "palette", color=True)

        layout.separator()

    # ========== ADVANCED (collapsible) ==========
    if _draw_collapsible_header(layout, ui_state, 'expand_brush_advanced', "Advanced"):
        box = layout.box()
        col = box.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(brush, "use_accumulate")
        if hasattr(brush, "use_alpha"):
            col.prop(brush, "use_alpha", text="Affect Alpha")

    layout.separator()

    # ========== TEXTURE (collapsible) ==========
    if _draw_collapsible_header(layout, ui_state, 'expand_brush_texture', "Texture"):
        box = layout.box()
        col = box.column()
        tex_slot = brush.texture_slot
        col.template_ID_preview(brush, "texture", new="texture.new", rows=3, cols=8)
        if brush.texture:
            col.separator()
            col.prop(tex_slot, "map_mode", text="Mapping")

    layout.separator()

    # ========== TEXTURE MASK (collapsible) ==========
    if _draw_collapsible_header(layout, ui_state, 'expand_brush_texture_mask', "Texture Mask"):
        box = layout.box()
        col = box.column()
        mask_tex_slot = brush.mask_texture_slot
        col.template_ID_preview(brush, "mask_texture", new="texture.new", rows=3, cols=8)
        if brush.mask_texture:
            col.separator()
            col.prop(mask_tex_slot, "mask_map_mode", text="Mask Mapping")

    layout.separator()

    # ========== STROKE (collapsible) ==========
    if _draw_collapsible_header(layout, ui_state, 'expand_brush_stroke', "Stroke"):
        box = layout.box()
        col = box.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(brush, "stroke_method")
        if brush.stroke_method != 'DOTS':
            col.prop(brush, "spacing", slider=True)

    layout.separator()

    # ========== FALLOFF (collapsible) ==========
    if _draw_collapsible_header(layout, ui_state, 'expand_brush_falloff', "Falloff"):
        box = layout.box()
        col = box.column()
        row = col.row(align=True)
        row.prop(brush, "curve_preset", text="")
        if brush.curve_preset == 'CUSTOM':
            col.template_curve_mapping(brush, "curve", brush=True)

        # Cursor checkbox
        col.separator()
        col.prop(brush, "use_cursor_overlay", text="Cursor")

    layout.separator()

    # ========== SYMMETRY ==========
    box = layout.box()
    box.label(text="Symmetry", icon='MOD_MIRROR')

    ob = context.object
    if ob and ob.data and hasattr(ob.data, 'use_mirror_x'):
        mesh = ob.data
        split = box.split()
        col = split.column()
        col.alignment = 'RIGHT'
        col.label(text="Mirror")
        col = split.column()
        row = col.row(align=True)
        row.prop(mesh, "use_mirror_x", text="X", toggle=True)
        row.prop(mesh, "use_mirror_y", text="Y", toggle=True)
        row.prop(mesh, "use_mirror_z", text="Z", toggle=True)

    layout.separator()

    # ========== OPTIONS ==========
    box = layout.box()
    box.label(text="Options", icon='OPTIONS')

    col = box.column()
    col.use_property_split = True
    col.use_property_decorate = False

    col.prop(settings, "seam_bleed", text="Bleed")
    col.prop(settings, "dither", slider=True)
    col.separator()
    col.prop(settings, "use_occlude")
    col.prop(settings, "use_backface_culling", text="Backface Culling")
