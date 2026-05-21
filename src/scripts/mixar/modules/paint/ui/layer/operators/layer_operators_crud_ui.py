# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing functions for layer CRUD operators"""

from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_active_object


def draw_new_layer_ui(operator, context):
    """Draw the New Layer operator UI."""
    node = get_active_mpaint_node()
    mp = node.node_tree.mp
    obj = get_active_object()

    # Error state
    if len(mp.channels) == 0:
        operator.layout.label(
            text="No channel found! Still want to create a layer?", icon="ERROR"
        )
        return

    # Get channel info
    try:
        channel_idx = int(operator.channel_idx)
        if channel_idx != -1:
            channel = mp.channels[channel_idx]
        else:
            channel = None
    except:
        channel = None

    # Modern layout setup
    layout = operator.layout
    layout.use_property_split = False
    layout.use_property_decorate = False

    main_col = layout.column(align=False)

    # ========== LAYER SETUP SECTION ==========
    _draw_layer_setup_section(operator, main_col, channel)

    # ========== LAYER PROPERTIES SECTION ==========
    _draw_layer_properties_section(operator, main_col, obj)

    # ========== MASK SECTION (if applicable) ==========
    if operator.type != "IMAGE":
        _draw_add_mask_toggle(operator, main_col, obj)

    # ========== INFO/WARNING MESSAGES ==========
    if operator.get_to_be_cleared_image_atlas(context, mp):
        main_col.separator(factor=1.0)
        info_box = main_col.box()
        info_col = info_box.column(align=True)
        info_col.scale_y = 1.1
        info_col.label(text="INFO: An unused atlas segment can be used.", icon="INFO")
        info_col.label(text="It will take a couple seconds to clear.")


def _draw_layer_setup_section(operator, main_col, channel):
    """Draw the layer setup section."""
    setup_box = main_col.box()
    setup_col = setup_box.column(align=False)

    # Header
    header_row = setup_col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Layer Setup", icon="RENDERLAYERS")

    setup_col.separator(factor=1.2)

    # Layer type (if applicable)
    if operator.add_mask and operator.mask_type == "IMAGE" and operator.mask_image_filepath:
        type_row = setup_col.row(align=True)
        type_row.scale_y = 1.4
        type_split = type_row.split(factor=0.25, align=True)
        label_col = type_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Type:")
        type_split.prop(operator, "type", text="")
        setup_col.separator(factor=0.4)

    # Name
    name_row = setup_col.row(align=True)
    name_row.scale_y = 1.4
    name_split = name_row.split(factor=0.25, align=True)
    label_col = name_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Name:")
    name_split.prop(operator, "name", text="")

    setup_col.separator(factor=0.4)

    # Channel selection
    if operator.type not in {"GROUP", "BACKGROUND"}:
        channel_row = setup_col.row(align=True)
        channel_row.scale_y = 1.4
        channel_split = channel_row.split(factor=0.25, align=True)
        label_col = channel_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Channel:")

        channel_value_col = channel_split.column(align=True)
        rrow = channel_value_col.row(align=True)
        rrow.prop(operator, "channel_idx", text="")
        if channel:
            if channel.type == "NORMAL":
                rrow.prop(operator, "normal_blend_type", text="")
            else:
                rrow.prop(operator, "blend_type", text="")

        setup_col.separator(factor=0.4)

        # Normal map type (if applicable)
        if channel and channel.type == "NORMAL":
            normal_row = setup_col.row(align=True)
            normal_row.scale_y = 1.4
            normal_split = normal_row.split(factor=0.25, align=True)
            label_col = normal_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Type:")
            normal_split.prop(operator, "normal_map_type", text="")
            setup_col.separator(factor=0.4)

    setup_col.separator(factor=0.8)
    main_col.separator(factor=0.8)


def _draw_layer_properties_section(operator, main_col, obj):
    """Draw the layer properties section."""
    props_box = main_col.box()
    props_col = props_box.column(align=False)

    # Header
    props_header = props_col.row(align=True)
    props_header.scale_y = 1.4
    props_header.label(text="Layer Properties", icon="PROPERTIES")

    props_col.separator(factor=1.2)

    # Color (for COLOR type)
    if operator.type == "COLOR":
        color_row = props_col.row(align=True)
        color_row.scale_y = 1.4
        color_split = color_row.split(factor=0.25, align=True)
        label_col = color_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Color:")
        color_split.prop(operator, "solid_color", text="")
        props_col.separator(factor=0.4)

    # Vertex color properties
    if operator.type == "VCOL":
        _draw_vcol_properties(operator, props_col)

    # Hemisphere/fake lighting space
    if operator.type == "HEMI":
        space_row = props_col.row(align=True)
        space_row.scale_y = 1.4
        space_split = space_row.split(factor=0.25, align=True)
        label_col = space_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Space:")
        space_split.prop(operator, "hemi_space", text="")
        props_col.separator(factor=0.4)

    # Edge detect radius
    if operator.type == "EDGE_DETECT":
        edge_row = props_col.row(align=True)
        edge_row.scale_y = 1.4
        edge_split = edge_row.split(factor=0.25, align=True)
        label_col = edge_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Radius:")
        edge_split.prop(operator, "edge_detect_radius", text="")
        props_col.separator(factor=0.4)

    # AO distance
    if operator.type == "AO":
        ao_row = props_col.row(align=True)
        ao_row.scale_y = 1.4
        ao_split = ao_row.split(factor=0.25, align=True)
        label_col = ao_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Distance:")
        ao_split.prop(operator, "ao_distance", text="")
        props_col.separator(factor=0.4)

    # Use previous normal (for HEMI, EDGE_DETECT, AO)
    if operator.type in {"HEMI", "EDGE_DETECT", "AO"}:
        normal_row = props_col.row(align=True)
        normal_row.scale_y = 1.2
        normal_split = normal_row.split(factor=0.25, align=True)
        normal_split.label(text="")
        checkbox_col = normal_split.column(align=True)
        checkbox_col.prop(operator, "hemi_use_prev_normal")
        props_col.separator(factor=0.4)

    # Image properties
    if operator.type == "IMAGE":
        _draw_image_properties(operator, props_col)

    # Texture coordinates
    if operator.type not in {"VCOL", "GROUP", "COLOR", "BACKGROUND", "HEMI", "EDGE_DETECT", "AO"}:
        _draw_texcoord_properties(operator, props_col, obj)

    # Divide alpha (for VCOL)
    if operator.type in {"VCOL"}:
        divider_row = props_col.row(align=True)
        divider_row.scale_y = 1.2
        divider_split = divider_row.split(factor=0.25, align=True)
        divider_split.label(text="")
        checkbox_col = divider_split.column(align=True)
        checkbox_col.prop(operator, "use_divider_alpha")
        props_col.separator(factor=0.4)

    # UDIM and Image Atlas (for IMAGE type)
    if operator.type == "IMAGE":
        _draw_udim_atlas_options(operator, props_col)

    props_col.separator(factor=0.8)


def _draw_vcol_properties(operator, props_col):
    """Draw vertex color properties."""
    domain_row = props_col.row(align=True)
    domain_row.scale_y = 1.4
    domain_split = domain_row.split(factor=0.25, align=True)
    label_col = domain_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Domain:")
    domain_value_col = domain_split.column(align=True)
    crow = domain_value_col.row(align=True)
    crow.prop(operator, "vcol_domain", expand=True)
    props_col.separator(factor=0.4)

    dtype_row = props_col.row(align=True)
    dtype_row.scale_y = 1.4
    dtype_split = dtype_row.split(factor=0.25, align=True)
    label_col = dtype_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Data Type:")
    dtype_value_col = dtype_split.column(align=True)
    crow = dtype_value_col.row(align=True)
    crow.prop(operator, "vcol_data_type", expand=True)
    props_col.separator(factor=0.4)


def _draw_image_properties(operator, props_col):
    """Draw image-specific properties."""
    # HDR toggle
    hdr_row = props_col.row(align=True)
    hdr_row.scale_y = 1.2
    hdr_split = hdr_row.split(factor=0.25, align=True)
    hdr_split.label(text="")
    checkbox_col = hdr_split.column(align=True)
    checkbox_col.prop(operator, "hdr")
    props_col.separator(factor=0.4)

    # Resolution
    if not operator.use_custom_resolution:
        res_row = props_col.row(align=True)
        res_row.scale_y = 1.4
        res_split = res_row.split(factor=0.25, align=True)
        label_col = res_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Resolution:")
        res_value_col = res_split.column(align=True)
        crow = res_value_col.row(align=True)
        crow.prop(operator, "image_resolution", expand=True)
        props_col.separator(factor=0.4)
    else:
        width_row = props_col.row(align=True)
        width_row.scale_y = 1.4
        width_split = width_row.split(factor=0.25, align=True)
        label_col = width_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Width:")
        width_split.prop(operator, "width", text="")
        props_col.separator(factor=0.4)

        height_row = props_col.row(align=True)
        height_row.scale_y = 1.4
        height_split = height_row.split(factor=0.25, align=True)
        label_col = height_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Height:")
        height_split.prop(operator, "height", text="")
        props_col.separator(factor=0.4)

    # Custom resolution toggle
    custom_res_row = props_col.row(align=True)
    custom_res_row.scale_y = 1.2
    custom_res_split = custom_res_row.split(factor=0.25, align=True)
    custom_res_split.label(text="")
    checkbox_col = custom_res_split.column(align=True)
    checkbox_col.prop(operator, "use_custom_resolution")
    props_col.separator(factor=0.4)

    # Interpolation
    interp_row = props_col.row(align=True)
    interp_row.scale_y = 1.4
    interp_split = interp_row.split(factor=0.25, align=True)
    label_col = interp_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Interpolation:")
    interp_split.prop(operator, "interpolation", text="")
    props_col.separator(factor=0.4)


def _draw_texcoord_properties(operator, props_col, obj):
    """Draw texture coordinate properties."""
    texcoord_row = props_col.row(align=True)
    texcoord_row.scale_y = 1.4
    texcoord_split = texcoord_row.split(factor=0.25, align=True)
    label_col = texcoord_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Vector:")

    texcoord_value_col = texcoord_split.column(align=True)
    crow = texcoord_value_col.row(align=True)
    crow.prop(operator, "texcoord_type", text="")
    if obj.type == "MESH" and operator.texcoord_type == "UV":
        crow.prop_search(operator, "uv_map", operator, "uv_map_coll", text="", icon="GROUP_UVS")
    props_col.separator(factor=0.4)


def _draw_udim_atlas_options(operator, props_col):
    """Draw UDIM and Image Atlas options."""
    udim_row = props_col.row(align=True)
    udim_row.scale_y = 1.2
    udim_split = udim_row.split(factor=0.25, align=True)
    udim_split.label(text="")
    checkbox_col = udim_split.column(align=True)
    checkbox_col.prop(operator, "use_udim")
    props_col.separator(factor=0.4)

    atlas_row = props_col.row(align=True)
    atlas_row.scale_y = 1.2
    atlas_split = atlas_row.split(factor=0.25, align=True)
    atlas_split.label(text="")
    checkbox_col = atlas_split.column(align=True)
    checkbox_col.prop(operator, "use_image_atlas")
    props_col.separator(factor=0.4)


def _draw_add_mask_toggle(operator, main_col, obj):
    """Draw the add mask toggle and mask section if enabled."""
    main_col.separator(factor=0.8)

    # Add mask button
    add_mask_row = main_col.row(align=True)
    add_mask_row.scale_y = 1.4

    # Toggle button style
    if not operator.add_mask:
        add_mask_row.prop(operator, "add_mask", text="Add Mask", icon="ADD", toggle=True)
    else:
        add_mask_row.prop(operator, "add_mask", text="Remove Mask", icon="REMOVE", toggle=True)

    main_col.separator(factor=0.4)

    if operator.add_mask:
        from .layer_operators_crud_ui_mask import draw_mask_section
        draw_mask_section(operator, main_col, obj)
