# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Brush panel UI drawing functions.

Implements Substance Painter-style brush panel with subtabs:
- TOOL: Color picker, texture, general brush settings and stroke settings
- ALPHA: Mask texture settings with preview and transforms
- FALLOFF: Curve preset, normal falloff, and cursor display settings

Also provides _draw_brush_texture_generation() for AI brush texture generation UI,
which is displayed in the main properties panel below the CHANNELS/BRUSH tabs.
"""

import bpy

from . import get_mixar_ui


def _draw_brush_texture_generation(context, layout):
    """Draw the brush texture generation UI section.

    Args:
        context: Blender context
        layout: Parent layout to draw into
    """
    mixar_ui = get_mixar_ui(context)
    if not mixar_ui:
        return

    box = layout.box()
    col = box.column(align=True)

    # Header
    header_row = col.row(align=True)
    header_row.alignment = 'CENTER'
    header_row.scale_y = 1.2
    header_row.label(text="Brush Texture Generation", icon="BRUSH_DATA")

    col.separator(factor=0.5)

    is_generating = mixar_ui.brush_gen_in_progress
    gen_progress = mixar_ui.brush_gen_progress
    gen_status = mixar_ui.brush_gen_status

    if is_generating:
        # Show progress section when generation is in progress
        progress_section = col.column(align=True)

        # Progress bar
        progress_row = progress_section.row(align=True)
        progress_row.scale_y = 1.5
        progress_row.prop(mixar_ui, "brush_gen_progress", text="Progress", slider=True)

        # Status message
        status_row = progress_section.row(align=True)
        status_row.alignment = 'CENTER'
        status_row.scale_y = 0.9
        status_row.label(text=gen_status, icon='INFO')

        # Percentage display
        percentage_row = progress_section.row(align=True)
        percentage_row.alignment = 'CENTER'
        percentage_row.scale_y = 0.8
        percentage_row.label(text=f"{gen_progress * 100:.0f}%")

    else:
        # Show normal prompt input when not generating
        prompt_section = col.column(align=True)
        prompt_section.enabled = not is_generating

        # Prompt input
        prompt_row = prompt_section.row(align=True)
        prompt_row.scale_y = 1.1
        prompt_row.prop(mixar_ui, "brush_texture_prompt", text="")

        # Character counter
        current_length = len(mixar_ui.brush_texture_prompt)
        counter_row = col.row(align=True)
        counter_row.alignment = 'RIGHT'
        counter_row.scale_y = 0.7
        counter_row.label(text=f"{current_length}/1024 characters")

        col.separator(factor=0.5)

        # Model selector + refresh
        model_row = col.row(align=True)
        model_row.prop(mixar_ui, "brush_gen_model", text="Model")
        model_row.operator("wm.m_brush_gen_refresh_models", text="", icon='FILE_REFRESH')

        col.separator(factor=0.5)

        # Reference image picker (from loaded/packed images in memory)
        ref_row = col.row(align=True)
        ref_row.prop_search(
            mixar_ui, "brush_gen_ref_image",
            bpy.data, "images",
            text="Ref", icon='IMAGE_DATA'
        )
        if mixar_ui.brush_gen_ref_image:
            ref_row.operator("wm.m_brush_gen_clear_reference", text="", icon='X')

        col.separator(factor=0.5)

        # Generate button
        button_row = col.row(align=True)
        button_row.scale_y = 1.4
        button_row.enabled = not is_generating
        button_row.operator(
            "wm.m_generate_brush_texture",
            text="Generate Texture",
            icon="PLAY"
        )

        # Show completion hint after successful generation
        if gen_status == "Added to moodboard!":
            hint_row = col.row(align=True)
            hint_row.alignment = 'CENTER'
            hint_row.scale_y = 0.8
            hint_row.label(text="Check moodboard for result", icon='INFO')

        col.separator(factor=0.5)

        # Apply selected moodboard image as brush mask
        apply_row = col.row(align=True)
        apply_row.scale_y = 1.2
        apply_row.operator(
            "wm.m_apply_brush_selected_image",
            text="Apply Selected Image",
            icon="CHECKMARK"
        )


def draw_brush_tab(context, layout, mixar_ui, mp=None, layer=None):
    """Draw the main BRUSH tab content with subtabs and channel settings."""
    # Check if in Texture Paint mode
    is_texture_paint = (
        context.mode == 'PAINT_TEXTURE' or
        (context.object and context.object.mode == 'TEXTURE_PAINT')
    )

    if not is_texture_paint:
        # Show message with Paint Mode button
        box = layout.box()
        row = box.row(align=True)
        row.scale_y = 1.3
        row.label(text="Not in Paint Mode", icon='INFO')
        row.operator("object.mode_set", text="Paint Mode", icon='BRUSH_DATA').mode = 'TEXTURE_PAINT'
        return

    # Check for valid brush
    if not hasattr(context, 'tool_settings') or not context.tool_settings.image_paint:
        box = layout.box()
        row = box.row(align=True)
        row.scale_y = 1.3
        row.label(text="No paint settings", icon='INFO')
        row.operator("object.mode_set", text="Object Mode", icon='OBJECT_DATA').mode = 'OBJECT'
        return

    settings = context.tool_settings.image_paint
    brush = settings.brush
    if not brush:
        box = layout.box()
        row = box.row(align=True)
        row.scale_y = 1.3
        row.label(text="No brush selected", icon='INFO')
        row.operator("object.mode_set", text="Object Mode", icon='OBJECT_DATA').mode = 'OBJECT'
        return

    # Subtab row
    subtab_row = layout.row(align=True)
    subtab_row.scale_y = 1.3
    subtab_row.prop(mixar_ui, "brush_subtab", expand=True)

    layout.separator(factor=1.0)

    # Draw content based on active subtab
    if mixar_ui.brush_subtab == 'TOOL':
        draw_brush_tool_subtab(context, layout, brush, settings)
    elif mixar_ui.brush_subtab == 'ALPHA':
        draw_brush_alpha_subtab(context, layout, brush, settings)
    elif mixar_ui.brush_subtab == 'FALLOFF':
        draw_brush_falloff_subtab(context, layout, brush, settings)


def draw_brush_tool_subtab(context, layout, brush, settings):
    """Draw TOOL subtab - Color picker, Texture, General and Stroke settings."""
    ups = settings.unified_paint_settings
    tex_slot = brush.texture_slot

    # ==================== COLOR PICKER SECTION ====================
    if brush.image_paint_capabilities.has_color:
        box = layout.box()
        col = box.column(align=False)

        col.label(text="Color", icon='COLOR')

        col.separator(factor=0.5)

        # Color/Gradient toggle
        row = col.row(align=True)
        row.prop(brush, "color_type", expand=True)

        col.separator(factor=0.5)

        if brush.color_type == 'COLOR':
            # Color wheel
            if ups.use_unified_color:
                col.template_color_picker(ups, "color", value_slider=True)
            else:
                col.template_color_picker(brush, "color", value_slider=True)

            col.separator(factor=0.5)

            # Color swatches row
            row = col.row(align=True)
            if ups.use_unified_color:
                row.prop(ups, "color", text="")
                row.prop(ups, "secondary_color", text="")
            else:
                row.prop(brush, "color", text="")
                row.prop(brush, "secondary_color", text="")

            row.separator(factor=0.5)
            row.operator("paint.brush_colors_flip", text="", icon='FILE_REFRESH')
            row.prop(ups, "use_unified_color", text="", icon='BRUSHES_ALL')

        elif brush.color_type == 'GRADIENT':
            # Gradient ramp
            col.template_color_ramp(brush, "gradient", expand=True)

            col.separator(factor=0.5)

            # Gradient mode
            split = col.split(factor=0.35)
            split.label(text="Mode")
            split.prop(brush, "gradient_stroke_mode", text="")

            # Fill mode options
            if brush.gradient_stroke_mode == 'PRESSURE':
                split = col.split(factor=0.35)
                split.label(text="Spacing")
                split.prop(brush, "grad_spacing", text="")

        layout.separator(factor=0.8)

    # ==================== TEXTURE SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    # Header with action buttons
    header = col.row(align=True)
    header.label(text="Texture", icon='TEXTURE')
    header.separator(factor=1.0)
    header.operator("wm.m_open_image_to_brush_texture", text="", icon='FILE_IMAGE')
    header.operator("wm.m_clear_brush_texture", text="", icon='X')

    col.separator(factor=0.5)

    # Texture preview
    col.template_ID_preview(brush, "texture", new="texture.new", rows=3, cols=8)

    col.separator(factor=0.5)

    # Mapping
    split = col.split(factor=0.35)
    split.label(text="Mapping")
    split.prop(tex_slot, "map_mode", text="")

    # Stencil operators
    if tex_slot.map_mode == 'STENCIL':
        col.separator(factor=0.3)
        if brush.texture and brush.texture.type == 'IMAGE':
            col.operator("brush.stencil_fit_image_aspect")
        col.operator("brush.stencil_reset_transform")

    # Offset and Size (when not STENCIL)
    if tex_slot.map_mode != 'STENCIL':
        col.separator(factor=0.5)

        # Offset
        split = col.split(factor=0.35)
        split.label(text="Offset")
        row = split.row(align=True)
        row.prop(tex_slot, "offset", text="")

        # Size
        split = col.split(factor=0.35)
        split.label(text="Size")
        row = split.row(align=True)
        row.prop(tex_slot, "scale", text="")

    # Angle settings
    if tex_slot.has_texture_angle:
        col.separator(factor=0.5)

        split = col.split(factor=0.35)
        split.label(text="Angle")
        split.prop(tex_slot, "angle", text="")

        if tex_slot.has_texture_angle_source:
            col.separator(factor=0.3)
            row = col.row(align=True)
            row.prop(tex_slot, "use_rake", text="Rake")
            row.separator(factor=1.0)
            if brush.brush_capabilities.has_random_texture_angle and tex_slot.has_random_texture_angle:
                row.prop(tex_slot, "use_random", text="Random")

            if tex_slot.use_random:
                col.separator(factor=0.3)
                split = col.split(factor=0.35)
                split.label(text="Random")
                split.prop(tex_slot, "random_angle", text="")

    layout.separator(factor=0.8)

    # ==================== BASIC BRUSH SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    # Blend
    split = col.split(factor=0.35)
    split.label(text="Blend")
    split.prop(brush, "blend", text="")

    col.separator(factor=0.5)

    # Radius
    split = col.split(factor=0.35)
    split.label(text="Radius")
    row = split.row(align=True)
    if ups.use_unified_size:
        row.prop(ups, "size", text="", slider=True)
    else:
        row.prop(brush, "size", text="", slider=True)
    row.prop(brush, "use_pressure_size", text="", icon='STYLUS_PRESSURE')
    row.prop(ups, "use_unified_size", text="", icon='BRUSHES_ALL')

    # Strength
    split = col.split(factor=0.35)
    split.label(text="Strength")
    row = split.row(align=True)
    if ups.use_unified_strength:
        row.prop(ups, "strength", text="", slider=True)
    else:
        row.prop(brush, "strength", text="", slider=True)
    row.prop(brush, "use_pressure_strength", text="", icon='STYLUS_PRESSURE')
    row.prop(ups, "use_unified_strength", text="", icon='BRUSHES_ALL')

    layout.separator(factor=0.8)

    # ==================== STROKE SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    col.label(text="Stroke", icon='STROKE')

    col.separator(factor=0.5)

    # Method
    split = col.split(factor=0.35)
    split.label(text="Method")
    split.prop(brush, "stroke_method", text="")

    # Spacing (not for DOTS)
    if brush.stroke_method != 'DOTS':
        col.separator(factor=0.3)
        split = col.split(factor=0.35)
        split.label(text="Spacing")
        row = split.row(align=True)
        row.prop(brush, "spacing", text="", slider=True)
        row.prop(brush, "use_pressure_spacing", toggle=True, text="", icon='STYLUS_PRESSURE')

    # Airbrush rate
    if brush.use_airbrush:
        col.separator(factor=0.3)
        split = col.split(factor=0.35)
        split.label(text="Rate")
        split.prop(brush, "rate", text="", slider=True)

    # Edge to edge for anchor
    if brush.use_anchor:
        col.separator(factor=0.3)
        col.prop(brush, "use_edge_to_edge", text="Edge to Edge")

    # Paint curve for curve stroke
    if brush.use_curve:
        col.separator(factor=0.5)
        col.template_ID(brush, "paint_curve", new="paintcurve.new")
        col.operator("paintcurve.draw")

    # Dash settings
    if brush.use_space or brush.use_line or brush.use_curve:
        col.separator(factor=0.5)

        split = col.split(factor=0.35)
        split.label(text="Dash Ratio")
        split.prop(brush, "dash_ratio", text="", slider=True)

        split = col.split(factor=0.35)
        split.label(text="Dash Length")
        split.prop(brush, "dash_samples", text="")

    layout.separator(factor=0.8)

    # ==================== VARIATION SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    col.label(text="Variation", icon='RNDCURVE')

    col.separator(factor=0.5)

    # Jitter
    split = col.split(factor=0.35)
    split.label(text="Jitter")
    row = split.row(align=True)
    if brush.jitter_unit == 'BRUSH':
        row.prop(brush, "jitter", text="", slider=True)
    else:
        row.prop(brush, "jitter_absolute", text="")
    row.prop(brush, "use_pressure_jitter", toggle=True, text="", icon='STYLUS_PRESSURE')

    col.separator(factor=0.3)

    # Jitter unit
    split = col.split(factor=0.35)
    split.label(text="")
    row = split.row(align=True)
    row.prop(brush, "jitter_unit", expand=True)

    layout.separator(factor=0.8)

    # ==================== SMOOTHING SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    col.label(text="Smoothing", icon='MOD_SMOOTH')

    col.separator(factor=0.5)

    # Input samples
    split = col.split(factor=0.35)
    split.label(text="Samples")
    row = split.row(align=True)
    row.prop(brush, "input_samples", text="", slider=True)
    row.prop(ups, "use_unified_input_samples", text="", icon='BRUSHES_ALL')

    col.separator(factor=0.5)

    # Stabilize stroke
    col.prop(brush, "use_smooth_stroke", text="Stabilize Stroke")

    if brush.use_smooth_stroke:
        col.separator(factor=0.3)

        # Indented sub-properties
        split = col.split(factor=0.1)
        split.separator()
        subcol = split.column(align=True)

        subsplit = subcol.split(factor=0.28)
        subsplit.label(text="Radius")
        subsplit.prop(brush, "smooth_stroke_radius", text="", slider=True)

        subsplit = subcol.split(factor=0.28)
        subsplit.label(text="Factor")
        subsplit.prop(brush, "smooth_stroke_factor", text="", slider=True)


def draw_brush_alpha_subtab(context, layout, brush, settings):
    """Draw ALPHA subtab - Mask texture settings."""
    mask_tex_slot = brush.mask_texture_slot

    # ==================== MASK TEXTURE SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    # Header with action buttons
    header = col.row(align=True)
    header.label(text="Mask Texture", icon='MOD_MASK')
    header.separator(factor=1.0)
    header.operator("wm.m_open_image_to_mask_texture", text="", icon='FILE_IMAGE')
    header.operator("wm.m_clear_mask_texture", text="", icon='X')

    col.separator(factor=0.5)

    # Mask texture preview
    col.template_ID_preview(mask_tex_slot, "texture", new="texture.new", rows=3, cols=8)

    col.separator(factor=0.5)

    # Mapping
    split = col.split(factor=0.35)
    split.label(text="Mapping")
    split.prop(mask_tex_slot, "mask_map_mode", text="")

    # Mask stencil operators
    if mask_tex_slot.map_mode == 'STENCIL':
        col.separator(factor=0.3)
        if brush.mask_texture and brush.mask_texture.type == 'IMAGE':
            col.operator("brush.stencil_fit_image_aspect").mask = True
        col.operator("brush.stencil_reset_transform").mask = True

    # Offset and Size (when not STENCIL)
    if mask_tex_slot.map_mode != 'STENCIL':
        col.separator(factor=0.5)

        # Offset
        split = col.split(factor=0.35)
        split.label(text="Offset")
        row = split.row(align=True)
        row.prop(mask_tex_slot, "offset", text="")

        # Size
        split = col.split(factor=0.35)
        split.label(text="Size")
        row = split.row(align=True)
        row.prop(mask_tex_slot, "scale", text="")

    col.separator(factor=0.5)

    # Pressure masking
    split = col.split(factor=0.35)
    split.label(text="Pressure")
    split.prop(brush, "use_pressure_masking", text="")

    # Mask angle settings
    if mask_tex_slot.has_texture_angle:
        col.separator(factor=0.5)

        split = col.split(factor=0.35)
        split.label(text="Angle")
        split.prop(mask_tex_slot, "angle", text="")

        if mask_tex_slot.has_texture_angle_source:
            col.separator(factor=0.3)
            row = col.row(align=True)
            row.prop(mask_tex_slot, "use_rake", text="Rake")
            row.separator(factor=1.0)
            if brush.brush_capabilities.has_random_texture_angle and mask_tex_slot.has_random_texture_angle:
                row.prop(mask_tex_slot, "use_random", text="Random")

            if mask_tex_slot.use_random:
                col.separator(factor=0.3)
                split = col.split(factor=0.35)
                split.label(text="Random")
                split.prop(mask_tex_slot, "random_angle", text="")


def draw_brush_falloff_subtab(context, layout, brush, settings):
    """Draw FALLOFF subtab - Curve preset, normal falloff, and cursor settings."""
    tex_slot = brush.texture_slot
    mask_tex_slot = brush.mask_texture_slot

    # ==================== FALLOFF SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    col.label(text="Falloff", icon='SMOOTHCURVE')

    col.separator(factor=0.5)

    # Preset
    split = col.split(factor=0.35)
    split.label(text="Preset")
    split.prop(brush, "curve_distance_falloff_preset", text="")

    # Custom curve editor
    if brush.curve_distance_falloff_preset == 'CUSTOM':
        col.separator(factor=0.5)
        col.template_curve_mapping(brush, "curve_distance_falloff", brush=True)

    col.separator(factor=0.8)

    # Normal falloff
    col.prop(settings, "use_normal_falloff", text="Normal Falloff")

    if settings.use_normal_falloff:
        col.separator(factor=0.3)
        split = col.split(factor=0.35)
        split.label(text="Angle")
        split.prop(settings, "normal_angle", text="")

    layout.separator(factor=0.8)

    # ==================== CURSOR SECTION ====================
    box = layout.box()
    col = box.column(align=False)

    col.label(text="Cursor", icon='PIVOT_CURSOR')

    col.separator(factor=0.5)

    # Show brush cursor
    col.prop(settings, "show_brush", text="Show Brush")

    if settings.show_brush:
        col.separator(factor=0.5)

        # Cursor color
        split = col.split(factor=0.35)
        split.label(text="Color")
        split.prop(brush, "cursor_color_add", text="")

    layout.separator(factor=0.8)

    # ==================== OVERLAY SECTION ====================
    box = layout.box()
    col = box.column(align=False)
    col.active = settings.show_brush

    col.label(text="Overlay", icon='OVERLAY')

    col.separator(factor=0.5)

    # Falloff overlay
    split = col.split(factor=0.35)
    split.label(text="Falloff")
    row = split.row(align=True)
    row.prop(brush, "cursor_overlay_alpha", text="", slider=True)
    row.prop(brush, "use_cursor_overlay_override", toggle=True, text="", icon='BRUSH_DATA')
    row.prop(
        brush, "use_cursor_overlay", text="", toggle=True,
        icon='HIDE_OFF' if brush.use_cursor_overlay else 'HIDE_ON',
    )

    col.separator(factor=0.3)

    # Texture overlay
    split = col.split(factor=0.35)
    split.label(text="Texture")
    row = split.row(align=True)
    row.prop(brush, "texture_overlay_alpha", text="", slider=True)
    row.prop(brush, "use_primary_overlay_override", toggle=True, text="", icon='BRUSH_DATA')
    if tex_slot.map_mode != 'STENCIL':
        row.prop(
            brush, "use_primary_overlay", text="", toggle=True,
            icon='HIDE_OFF' if brush.use_primary_overlay else 'HIDE_ON',
        )

    col.separator(factor=0.3)

    # Mask texture overlay
    split = col.split(factor=0.35)
    split.label(text="Mask")
    row = split.row(align=True)
    row.prop(brush, "mask_overlay_alpha", text="", slider=True)
    row.prop(brush, "use_secondary_overlay_override", toggle=True, text="", icon='BRUSH_DATA')
    if mask_tex_slot.map_mode != 'STENCIL':
        row.prop(
            brush, "use_secondary_overlay", text="", toggle=True,
            icon='HIDE_OFF' if brush.use_secondary_overlay else 'HIDE_ON',
        )
