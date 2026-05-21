# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Draw helper functions for MNewLayerMask operator.

This module contains helper functions for drawing the UI of the
MNewLayerMask operator, split by section for maintainability.
"""


def draw_mask_setup_section(layout, operator):
    """Draw the mask setup section of the operator UI.

    Args:
        layout: Blender UI layout object.
        operator: The MNewLayerMask operator instance.
    """
    setup_box = layout.box()
    setup_col = setup_box.column(align=False)

    # Header
    header_row = setup_col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Mask Setup", icon="MOD_MASK")

    setup_col.separator(factor=1.2)

    # Name
    name_row = setup_col.row(align=True)
    name_row.scale_y = 1.4
    name_split = name_row.split(factor=0.25, align=True)
    label_col = name_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Name:")
    name_split.prop(operator, "name", text="")

    setup_col.separator(factor=0.4)

    # Blend
    blend_row = setup_col.row(align=True)
    blend_row.scale_y = 1.4
    blend_split = blend_row.split(factor=0.25, align=True)
    label_col = blend_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Blend:")
    blend_split.prop(operator, "blend_type", text="")

    setup_col.separator(factor=0.4)
    setup_col.separator(factor=0.8)


def draw_image_type_properties(props_col, operator):
    """Draw IMAGE type specific properties.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    # Custom resolution checkbox
    custom_row = props_col.row(align=True)
    custom_row.scale_y = 1.2
    custom_split = custom_row.split(factor=0.25, align=True)
    custom_split.label(text="")
    custom_col = custom_split.column(align=True)
    custom_col.prop(operator, "use_custom_resolution")

    props_col.separator(factor=0.4)

    # Resolution or Width/Height
    if operator.use_custom_resolution:
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
    else:
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

    # HDR checkbox
    hdr_row = props_col.row(align=True)
    hdr_row.scale_y = 1.2
    hdr_split = hdr_row.split(factor=0.25, align=True)
    hdr_split.label(text="")
    hdr_col = hdr_split.column(align=True)
    hdr_col.prop(operator, "hdr")

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


def draw_color_option(props_col, operator):
    """Draw color option property for IMAGE and VCOL types.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    color_row = props_col.row(align=True)
    color_row.scale_y = 1.4
    color_split = color_row.split(factor=0.25, align=True)
    label_col = color_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Color:")
    color_split.prop(operator, "color_option", text="")

    props_col.separator(factor=0.4)


def draw_color_id_properties(props_col, operator, obj):
    """Draw COLOR_ID type specific properties.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
        obj: The active Blender object.
    """
    color_id_row = props_col.row(align=True)
    color_id_row.scale_y = 1.4
    color_id_split = color_id_row.split(factor=0.25, align=True)
    label_col = color_id_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Color ID:")
    color_id_split.prop(operator, "color_id", text="")

    props_col.separator(factor=0.4)

    if obj.mode == "EDIT":
        fill_row = props_col.row(align=True)
        fill_row.scale_y = 1.2
        fill_split = fill_row.split(factor=0.25, align=True)
        fill_split.label(text="")
        fill_col = fill_split.column(align=True)
        fill_col.prop(operator, "vcol_fill", text="Fill Selected Faces")

        props_col.separator(factor=0.4)


def draw_vcol_properties(props_col, operator, obj):
    """Draw VCOL type specific properties.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
        obj: The active Blender object.
    """
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

    if obj.mode == "EDIT" and operator.color_option == "BLACK":
        vcol_fill_row = props_col.row(align=True)
        vcol_fill_row.scale_y = 1.2
        vcol_fill_split = vcol_fill_row.split(factor=0.25, align=True)
        vcol_fill_split.label(text="")
        vcol_fill_col = vcol_fill_split.column(align=True)
        vcol_fill_col.prop(operator, "vcol_fill", text="Fill Selected Faces")

        props_col.separator(factor=0.4)


def draw_hemi_properties(props_col, operator):
    """Draw HEMI type specific properties.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    hemi_row = props_col.row(align=True)
    hemi_row.scale_y = 1.4
    hemi_split = hemi_row.split(factor=0.25, align=True)
    label_col = hemi_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Space:")
    hemi_split.prop(operator, "hemi_space", text="")

    props_col.separator(factor=0.4)


def draw_edge_detect_properties(props_col, operator):
    """Draw EDGE_DETECT type specific properties.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    edge_row = props_col.row(align=True)
    edge_row.scale_y = 1.4
    edge_split = edge_row.split(factor=0.25, align=True)
    label_col = edge_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Radius:")
    edge_split.prop(operator, "edge_detect_radius", text="")

    props_col.separator(factor=0.4)


def draw_ao_properties(props_col, operator):
    """Draw AO type specific properties.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    ao_row = props_col.row(align=True)
    ao_row.scale_y = 1.4
    ao_split = ao_row.split(factor=0.25, align=True)
    label_col = ao_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="AO Distance:")
    ao_split.prop(operator, "ao_distance", text="")

    props_col.separator(factor=0.4)


def draw_prev_normal_option(props_col, operator):
    """Draw use previous normal option for HEMI, EDGE_DETECT, AO types.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    prev_normal_row = props_col.row(align=True)
    prev_normal_row.scale_y = 1.2
    prev_normal_split = prev_normal_row.split(factor=0.25, align=True)
    prev_normal_split.label(text="")
    prev_normal_col = prev_normal_split.column(align=True)
    prev_normal_col.prop(operator, "hemi_use_prev_normal")

    props_col.separator(factor=0.4)


def draw_vector_properties(props_col, operator, obj):
    """Draw vector/texcoord properties section.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
        obj: The active Blender object.
    """
    vector_row = props_col.row(align=True)
    vector_row.scale_y = 1.4
    vector_split = vector_row.split(factor=0.25, align=True)
    label_col = vector_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Vector:")
    vector_value_col = vector_split.column(align=True)
    crow = vector_value_col.row(align=True)
    crow.prop(operator, "texcoord_type", text="")
    if obj.type == "MESH" and operator.texcoord_type == "UV":
        crow.prop_search(
            operator, "uv_name", operator, "uv_map_coll", text="", icon="GROUP_UVS"
        )

    props_col.separator(factor=0.4)


def draw_udim_and_atlas_options(props_col, operator):
    """Draw UDIM and Image Atlas options for IMAGE type.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    udim_row = props_col.row(align=True)
    udim_row.scale_y = 1.2
    udim_split = udim_row.split(factor=0.25, align=True)
    udim_split.label(text="")
    udim_col = udim_split.column(align=True)
    udim_col.prop(operator, "use_udim")

    props_col.separator(factor=0.4)

    atlas_row = props_col.row(align=True)
    atlas_row.scale_y = 1.2
    atlas_split = atlas_row.split(factor=0.25, align=True)
    atlas_split.label(text="")
    atlas_col = atlas_split.column(align=True)
    atlas_col.prop(operator, "use_image_atlas")

    props_col.separator(factor=0.4)


def draw_object_index_properties(props_col, operator):
    """Draw OBJECT_INDEX type specific properties.

    Args:
        props_col: Blender UI column for properties.
        operator: The MNewLayerMask operator instance.
    """
    obj_idx_row = props_col.row(align=True)
    obj_idx_row.scale_y = 1.4
    obj_idx_split = obj_idx_row.split(factor=0.25, align=True)
    label_col = obj_idx_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Object Index:")
    obj_idx_split.prop(operator, "object_index", text="")

    props_col.separator(factor=0.4)


def draw_image_atlas_warning(main_col, has_atlas_to_clear):
    """Draw image atlas warning if needed.

    Args:
        main_col: Main column layout.
        has_atlas_to_clear: Boolean indicating if atlas needs clearing.
    """
    if has_atlas_to_clear:
        main_col.separator(factor=0.8)

        warning_box = main_col.box()
        warning_col = warning_box.column(align=False)

        warning_row1 = warning_col.row(align=True)
        warning_row1.label(text="INFO: An unused atlas segment can be used.", icon="ERROR")

        warning_col.separator(factor=0.2)

        warning_row2 = warning_col.row(align=True)
        warning_row2.label(text="It will take a couple seconds to clear.")


# Types that don't use vector/texcoord properties
NON_VECTOR_TYPES = {
    "VCOL",
    "HEMI",
    "OBJECT_INDEX",
    "COLOR_ID",
    "BACKFACE",
    "EDGE_DETECT",
    "MODIFIER",
    "AO",
}

# Types that use previous normal option
PREV_NORMAL_TYPES = {"HEMI", "EDGE_DETECT", "AO"}


def draw_mask_properties_section(layout, operator, obj):
    """Draw the mask properties section of the operator UI.

    Args:
        layout: Blender UI layout object.
        operator: The MNewLayerMask operator instance.
        obj: The active Blender object.
    """
    props_box = layout.box()
    props_col = props_box.column(align=False)

    # Header
    props_header = props_col.row(align=True)
    props_header.scale_y = 1.4
    props_header.label(text="Mask Properties", icon="PROPERTIES")

    props_col.separator(factor=1.2)

    # IMAGE type properties
    if operator.type == "IMAGE":
        draw_image_type_properties(props_col, operator)

    # Color option (IMAGE and VCOL)
    if operator.type in {"VCOL", "IMAGE"}:
        draw_color_option(props_col, operator)

    # COLOR_ID properties
    if operator.type == "COLOR_ID":
        draw_color_id_properties(props_col, operator, obj)

    # VCOL properties
    if operator.type == "VCOL":
        draw_vcol_properties(props_col, operator, obj)

    # HEMI properties
    if operator.type == "HEMI":
        draw_hemi_properties(props_col, operator)

    # EDGE_DETECT properties
    if operator.type == "EDGE_DETECT":
        draw_edge_detect_properties(props_col, operator)

    # AO properties
    if operator.type == "AO":
        draw_ao_properties(props_col, operator)

    # Use prev normal (HEMI, EDGE_DETECT, AO)
    if operator.type in PREV_NORMAL_TYPES:
        draw_prev_normal_option(props_col, operator)

    # Vector/Texcoord properties
    if operator.type not in NON_VECTOR_TYPES:
        draw_vector_properties(props_col, operator, obj)

        # UDIM and Image Atlas (IMAGE only)
        if operator.type == "IMAGE":
            draw_udim_and_atlas_options(props_col, operator)

    # OBJECT_INDEX properties
    if operator.type == "OBJECT_INDEX":
        draw_object_index_properties(props_col, operator)

    props_col.separator(factor=0.8)


__all__ = [
    'draw_mask_setup_section',
    'draw_mask_properties_section',
    'draw_image_atlas_warning',
    'NON_VECTOR_TYPES',
    'PREV_NORMAL_TYPES',
]
