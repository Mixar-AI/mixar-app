# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing functions for channel baking operators"""

from ....core.layer.layer_utils import get_root_height_channel
from ....utils.blender_commons import get_active_object, is_bl_equal


def draw_bake_channels_ui(operator, context, layout):
    """Draw the UI for the MBakeChannels operator.

    Args:
        operator: The operator instance
        context: Blender context
        layout: UI layout
    """
    from ....core.node.node_utils import get_active_mpaint_node

    layout.use_property_split = False
    layout.use_property_decorate = False

    node = get_active_mpaint_node()
    mp = node.node_tree.mp
    height_root_ch = get_root_height_channel(mp)

    obj = get_active_object()

    # NOTE: Because of api changes, vertex color shift doesn't work with Blender 3.2
    active_channel = None
    if operator.only_active_channel and not is_bl_equal(3, 2):
        active_channel = operator.channels[0]

    any_color_channel = any(
        [
            c
            for c in operator.channels
            if c.type == "RGB" and c.colorspace == "SRGB" and c.use_clamp
        ]
    )

    main_col = layout.column(align=False)

    # ========== BAKE CHANNELS ==========
    box = main_col.box()
    col = box.column(align=False)

    # Header
    header_row = col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Bake Channels", icon="RENDER_RESULT")

    col.separator(factor=1.2)

    # Custom Resolution
    _draw_custom_resolution(operator, col)

    # Samples
    _draw_property_row(col, "Samples:", operator, "samples")

    # AA Level
    _draw_property_row(col, "AA Level:", operator, "aa_level")

    # Margin
    _draw_margin_row(operator, col)

    # Float for Normal/Displacement
    if height_root_ch:
        _draw_float_options(operator, col)

    # Bake Device
    _draw_bake_device(operator, col)

    # Interpolation
    _draw_property_row(col, "Interpolation:", operator, "interpolation")

    # UV Map
    _draw_uv_map(operator, col)

    # Vertex Color Force First
    _draw_vcol_force_first(operator, col, active_channel)

    # UDIM
    _draw_checkbox_row(col, "Use UDIM:", operator, "use_udim")

    # FXAA
    _draw_checkbox_row(col, "Use FXAA:", operator, "fxaa")

    # Denoise
    _draw_checkbox_row(col, "Use Denoise:", operator, "denoise")

    # Dithering
    if any_color_channel:
        _draw_dithering(operator, col)

    # Use OSL
    _draw_checkbox_row(col, "Use OSL:", operator, "use_osl")

    # Force Bake All Polygons
    _draw_checkbox_row(col, "Force All Poly:", operator, "force_bake_all_polygons")

    # Bake Disabled Layers
    _draw_checkbox_row(col, "Bake Disabled:", operator, "bake_disabled_layers")

    col.separator(factor=0.8)
    main_col.separator(factor=0.8)


def _draw_property_row(col, label, operator, prop_name, scale_y=1.4):
    """Draw a standard property row."""
    row = col.row(align=True)
    row.scale_y = scale_y
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text=label)
    split.prop(operator, prop_name, text="")
    col.separator(factor=0.4)


def _draw_checkbox_row(col, label, operator, prop_name):
    """Draw a checkbox property row."""
    row = col.row(align=True)
    row.scale_y = 1.2
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text=label)
    split.prop(operator, prop_name, text="")
    col.separator(factor=0.4)


def _draw_custom_resolution(operator, col):
    """Draw custom resolution settings."""
    row = col.row(align=True)
    row.scale_y = 1.2
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Custom Res:")
    split.prop(operator, "use_custom_resolution", text="")
    col.separator(factor=0.4)

    if not operator.use_custom_resolution:
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Resolution:")
        crow = split.row(align=True)
        crow.prop(operator, "image_resolution", expand=True)
        col.separator(factor=0.4)
    else:
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Width:")
        split.prop(operator, "width", text="")
        col.separator(factor=0.4)

        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Height:")
        split.prop(operator, "height", text="")
        col.separator(factor=0.4)


def _draw_margin_row(operator, col):
    """Draw margin settings."""
    row = col.row(align=True)
    row.scale_y = 1.4
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Margin:")
    margin_split = split.split(factor=0.4, align=True)
    margin_split.prop(operator, "margin", text="")
    margin_split.prop(operator, "margin_type", text="")
    col.separator(factor=0.4)


def _draw_float_options(operator, col):
    """Draw float options for normal/displacement."""
    row = col.row(align=True)
    row.scale_y = 1.2
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="32-bit Float:")
    splits = split.split(factor=0.4)
    splits.prop(operator, "use_float_for_normal", emboss=True, text="Normal")
    splits.prop(operator, "use_float_for_displacement", emboss=True, text="Displacement")
    col.separator(factor=0.4)


def _draw_bake_device(operator, col):
    """Draw bake device settings."""
    row = col.row(align=True)
    row.scale_y = 1.4
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Device:")
    if operator.use_osl:
        split.label(text="CPU (OSL)")
    else:
        split.prop(operator, "bake_device", text="")
    col.separator(factor=0.4)


def _draw_uv_map(operator, col):
    """Draw UV map selection."""
    row = col.row(align=True)
    row.scale_y = 1.4
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="UV Map:")
    split.prop_search(operator, "uv_map", operator, "uv_map_coll", text="", icon="GROUP_UVS")
    col.separator(factor=0.4)


def _draw_vcol_force_first(operator, col, active_channel):
    """Draw vertex color force first settings."""
    if active_channel and active_channel.enable_bake_to_vcol:
        row = col.row(align=True)
        row.scale_y = 1.2
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Force First:")
        split.prop(operator, "vcol_force_first_ch_idx_bool", text="Force First Vcol")
        col.separator(factor=0.4)
    elif operator.enable_bake_as_vcol and not is_bl_equal(3, 2):
        row = col.row(align=True)
        row.scale_y = 1.2
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Force First:")
        split.prop(operator, "vcol_force_first_ch_idx", text="")
        col.separator(factor=0.4)


def _draw_dithering(operator, col):
    """Draw dithering settings."""
    row = col.row(align=True)
    row.scale_y = 1.2
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Use Dithering:")
    if operator.use_dithering:
        dither_split = split.split(factor=0.55)
        dither_split.prop(operator, "use_dithering", text="")
        dither_split.prop(operator, "dither_intensity", text="")
    else:
        split.prop(operator, "use_dithering", text="")
    col.separator(factor=0.4)
