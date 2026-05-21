# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for paint layer operators UI drawing."""

from ...core.node.node_utils import get_active_mpaint_node


def draw_layer_setup_section(layout, operator, channel):
    """Draw the layer setup section of the paint layer dialog.

    This includes layer name, channel selection, blend types, and normal settings.

    Args:
        layout: Blender UI layout to draw into.
        operator: The operator instance containing properties.
        channel: The selected channel object (may be None).
    """
    main_col = layout.column(align=False)

    # ========== LAYER SETUP SECTION ==========
    setup_box = main_col.box()
    setup_col = setup_box.column(align=False)

    # Header
    header_row = setup_col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Paint Layer Setup", icon="BRUSH_DATA")

    setup_col.separator(factor=1.2)

    # Name
    name_row = setup_col.row(align=True)
    name_row.scale_y = 1.4
    name_split = name_row.split(factor=0.25, align=True)
    label_col = name_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Name:")
    name_split.prop(operator, 'name', text='')

    setup_col.separator(factor=0.4)

    # Channel
    channel_row = setup_col.row(align=True)
    channel_row.scale_y = 1.4
    channel_split = channel_row.split(factor=0.25, align=True)
    label_col = channel_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Channel:")
    channel_split.prop(operator, 'channel_idx', text='')

    setup_col.separator(factor=0.4)

    # Normal map type (if applicable)
    if channel and channel.type == 'NORMAL':
        type_row = setup_col.row(align=True)
        type_row.scale_y = 1.4
        type_split = type_row.split(factor=0.25, align=True)
        label_col = type_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Type:")
        type_split.prop(operator, 'normal_map_type', text='')
        setup_col.separator(factor=0.4)

    # Blend type
    blend_row = setup_col.row(align=True)
    blend_row.scale_y = 1.4
    blend_split = blend_row.split(factor=0.25, align=True)
    label_col = blend_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Blend:")
    blend_split.prop(operator, 'blend_type', text='')

    setup_col.separator(factor=0.4)

    # Normal blend (if applicable)
    if channel and channel.type == 'NORMAL':
        normal_blend_row = setup_col.row(align=True)
        normal_blend_row.scale_y = 1.4
        normal_blend_split = normal_blend_row.split(factor=0.25, align=True)
        label_col = normal_blend_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Normal Blend:")
        normal_blend_split.prop(operator, 'normal_blend_type', text='')
        setup_col.separator(factor=0.4)

    setup_col.separator(factor=0.8)
    main_col.separator(factor=0.8)

    return main_col


def draw_image_settings_section(layout, operator):
    """Draw the image settings section of the paint layer dialog.

    This includes HDR, resolution, interpolation, UV map, and UDIM settings.

    Args:
        layout: Blender UI layout (column) to draw into.
        operator: The operator instance containing properties.
    """
    # ========== IMAGE SETTINGS SECTION ==========
    image_box = layout.box()
    image_col = image_box.column(align=False)

    # Header
    image_header = image_col.row(align=True)
    image_header.scale_y = 1.4
    image_header.label(text="Image Settings", icon="IMAGE_DATA")

    image_col.separator(factor=1.2)

    # HDR checkbox
    hdr_row = image_col.row(align=True)
    hdr_row.scale_y = 1.2
    hdr_split = hdr_row.split(factor=0.25, align=True)
    hdr_split.label(text="")  # Empty indent
    hdr_col = hdr_split.column(align=True)
    hdr_col.prop(operator, 'hdr')

    image_col.separator(factor=0.4)

    # Resolution or custom width/height
    if operator.use_custom_resolution:
        _draw_custom_resolution(image_col, operator)
    else:
        _draw_standard_resolution(image_col, operator)

    # Custom resolution checkbox
    custom_res_row = image_col.row(align=True)
    custom_res_row.scale_y = 1.2
    custom_res_split = custom_res_row.split(factor=0.25, align=True)
    custom_res_split.label(text="")  # Empty indent
    custom_res_col = custom_res_split.column(align=True)
    custom_res_col.prop(operator, 'use_custom_resolution')

    image_col.separator(factor=0.4)

    # Interpolation
    interp_row = image_col.row(align=True)
    interp_row.scale_y = 1.4
    interp_split = interp_row.split(factor=0.25, align=True)
    label_col = interp_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Interpolation:")
    interp_split.prop(operator, 'interpolation', text='')

    image_col.separator(factor=0.4)

    # UV Map (if applicable)
    if len(operator.uv_map_coll) > 0:
        uv_row = image_col.row(align=True)
        uv_row.scale_y = 1.4
        uv_split = uv_row.split(factor=0.25, align=True)
        label_col = uv_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="UV Map:")
        uv_split.prop_search(
            operator, 'uv_map', operator, 'uv_map_coll', text='', icon='GROUP_UVS'
        )

        image_col.separator(factor=0.4)

    # UDIM checkbox
    udim_row = image_col.row(align=True)
    udim_row.scale_y = 1.2
    udim_split = udim_row.split(factor=0.25, align=True)
    udim_split.label(text="")  # Empty indent
    udim_col = udim_split.column(align=True)
    udim_col.prop(operator, 'use_udim')

    image_col.separator(factor=0.4)
    image_col.separator(factor=0.8)


def _draw_custom_resolution(image_col, operator):
    """Draw custom width/height fields.

    Args:
        image_col: The image column layout.
        operator: The operator instance.
    """
    width_row = image_col.row(align=True)
    width_row.scale_y = 1.4
    width_split = width_row.split(factor=0.25, align=True)
    label_col = width_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Width:")
    width_split.prop(operator, 'width', text='')

    image_col.separator(factor=0.4)

    height_row = image_col.row(align=True)
    height_row.scale_y = 1.4
    height_split = height_row.split(factor=0.25, align=True)
    label_col = height_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Height:")
    height_split.prop(operator, 'height', text='')

    image_col.separator(factor=0.4)


def _draw_standard_resolution(image_col, operator):
    """Draw standard resolution dropdown.

    Args:
        image_col: The image column layout.
        operator: The operator instance.
    """
    res_row = image_col.row(align=True)
    res_row.scale_y = 1.4
    res_split = res_row.split(factor=0.25, align=True)
    label_col = res_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Resolution:")
    res_split.prop(operator, 'image_resolution', text='')

    image_col.separator(factor=0.4)


def draw_paint_layer_dialog(context, layout, operator):
    """Draw the complete paint layer creation dialog UI.

    This is the main entry point for drawing the dialog, coordinating
    the layer setup and image settings sections.

    Args:
        context: Blender context.
        layout: Blender UI layout.
        operator: The operator instance containing properties.
    """
    node = get_active_mpaint_node()
    mp = node.node_tree.mp

    if len(mp.channels) == 0:
        layout.label(text='No channel found!', icon='ERROR')
        return

    # Get selected channel
    try:
        channel_idx = int(operator.channel_idx)
        if channel_idx != -1:
            channel = mp.channels[channel_idx]
        else:
            channel = None
    except (ValueError, IndexError):
        channel = None

    layout.use_property_split = False
    layout.use_property_decorate = False

    # Draw layer setup section and get the main column
    main_col = draw_layer_setup_section(layout, operator, channel)

    # Draw image settings section
    draw_image_settings_section(main_col, operator)
