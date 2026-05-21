# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask UI drawing functions for layer CRUD operators"""


def draw_mask_section(operator, main_col, obj):
    """Draw the mask section of the UI."""
    mask_box = main_col.box()
    mask_col = mask_box.column(align=False)

    # Header
    mask_header = mask_col.row(align=True)
    mask_header.scale_y = 1.4
    mask_header.label(text="Mask", icon="MOD_MASK")

    mask_col.separator(factor=1.2)

    # Mask type
    mask_type_row = mask_col.row(align=True)
    mask_type_row.scale_y = 1.4
    mask_type_split = mask_type_row.split(factor=0.25, align=True)
    label_col = mask_type_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Type:")
    mask_type_split.prop(operator, "mask_type", text="")
    mask_col.separator(factor=0.4)

    # Mask-specific properties
    if operator.mask_type == "COLOR_ID":
        _draw_mask_color_id(operator, mask_col, obj)
    elif operator.mask_type == "EDGE_DETECT":
        _draw_mask_edge_detect(operator, mask_col)
    elif operator.mask_type == "IMAGE":
        _draw_mask_image_properties(operator, mask_col, obj)
    elif operator.mask_type == "VCOL":
        _draw_mask_vcol(operator, mask_col, obj)


def _draw_mask_color_id(operator, mask_col, obj):
    """Draw Color ID mask properties."""
    colorid_row = mask_col.row(align=True)
    colorid_row.scale_y = 1.4
    colorid_split = colorid_row.split(factor=0.25, align=True)
    label_col = colorid_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Color ID:")
    colorid_split.prop(operator, "mask_color_id", text="")
    mask_col.separator(factor=0.4)

    if obj.mode == "EDIT":
        fill_row = mask_col.row(align=True)
        fill_row.scale_y = 1.2
        fill_split = fill_row.split(factor=0.25, align=True)
        fill_split.label(text="")
        checkbox_col = fill_split.column(align=True)
        checkbox_col.prop(operator, "mask_vcol_fill", text="Fill Selected Faces")
        mask_col.separator(factor=0.4)


def _draw_mask_edge_detect(operator, mask_col):
    """Draw Edge Detect mask properties."""
    edge_row = mask_col.row(align=True)
    edge_row.scale_y = 1.4
    edge_split = edge_row.split(factor=0.25, align=True)
    label_col = edge_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Radius:")
    edge_split.prop(operator, "mask_edge_detect_radius", text="")
    mask_col.separator(factor=0.4)

    prev_normal_row = mask_col.row(align=True)
    prev_normal_row.scale_y = 1.2
    prev_normal_split = prev_normal_row.split(factor=0.25, align=True)
    prev_normal_split.label(text="")
    checkbox_col = prev_normal_split.column(align=True)
    checkbox_col.prop(operator, "mask_use_prev_normal", text="Use Previous Normal")
    mask_col.separator(factor=0.4)


def _draw_mask_vcol(operator, mask_col, obj):
    """Draw Vertex Color mask properties."""
    mdomain_row = mask_col.row(align=True)
    mdomain_row.scale_y = 1.4
    mdomain_split = mdomain_row.split(factor=0.25, align=True)
    label_col = mdomain_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Domain:")
    mdomain_value_col = mdomain_split.column(align=True)
    crow = mdomain_value_col.row(align=True)
    crow.prop(operator, "mask_vcol_domain", expand=True)
    mask_col.separator(factor=0.4)

    mdtype_row = mask_col.row(align=True)
    mdtype_row.scale_y = 1.4
    mdtype_split = mdtype_row.split(factor=0.25, align=True)
    label_col = mdtype_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Data Type:")
    mdtype_value_col = mdtype_split.column(align=True)
    crow = mdtype_value_col.row(align=True)
    crow.prop(operator, "mask_vcol_data_type", expand=True)
    mask_col.separator(factor=0.4)

    if obj.mode == "EDIT":
        mfill_row = mask_col.row(align=True)
        mfill_row.scale_y = 1.2
        mfill_split = mfill_row.split(factor=0.25, align=True)
        mfill_split.label(text="")
        checkbox_col = mfill_split.column(align=True)
        checkbox_col.prop(operator, "mask_vcol_fill", text="Fill Selected Faces")
        mask_col.separator(factor=0.4)


def _draw_mask_image_properties(operator, mask_col, obj):
    """Draw mask image properties."""
    if operator.mask_image_filepath:
        filepath_row = mask_col.row(align=True)
        filepath_row.scale_y = 1.4
        filepath_split = filepath_row.split(factor=0.25, align=True)
        label_col = filepath_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Path:")
        filepath_split.prop(operator, "mask_image_filepath", text="")
        mask_col.separator(factor=0.4)

    if not operator.mask_image_filepath:
        # Mask color
        mcolor_row = mask_col.row(align=True)
        mcolor_row.scale_y = 1.4
        mcolor_split = mcolor_row.split(factor=0.25, align=True)
        label_col = mcolor_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Color:")
        mcolor_split.prop(operator, "mask_color", text="")
        mask_col.separator(factor=0.4)

        # HDR
        mhdr_row = mask_col.row(align=True)
        mhdr_row.scale_y = 1.2
        mhdr_split = mhdr_row.split(factor=0.25, align=True)
        mhdr_split.label(text="")
        checkbox_col = mhdr_split.column(align=True)
        checkbox_col.prop(operator, "mask_use_hdr")
        mask_col.separator(factor=0.4)

        # Custom resolution toggle
        mcustom_res_row = mask_col.row(align=True)
        mcustom_res_row.scale_y = 1.2
        mcustom_res_split = mcustom_res_row.split(factor=0.25, align=True)
        mcustom_res_split.label(text="")
        checkbox_col = mcustom_res_split.column(align=True)
        checkbox_col.prop(operator, "mask_use_custom_resolution")
        mask_col.separator(factor=0.4)

        # Resolution
        if not operator.mask_use_custom_resolution:
            mres_row = mask_col.row(align=True)
            mres_row.scale_y = 1.4
            mres_split = mres_row.split(factor=0.25, align=True)
            label_col = mres_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Resolution:")
            mres_value_col = mres_split.column(align=True)
            crow = mres_value_col.row(align=True)
            crow.prop(operator, "mask_image_resolution", expand=True)
            mask_col.separator(factor=0.4)
        else:
            mwidth_row = mask_col.row(align=True)
            mwidth_row.scale_y = 1.4
            mwidth_split = mwidth_row.split(factor=0.25, align=True)
            label_col = mwidth_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Width:")
            mwidth_split.prop(operator, "mask_width", text="")
            mask_col.separator(factor=0.4)

            mheight_row = mask_col.row(align=True)
            mheight_row.scale_y = 1.4
            mheight_split = mheight_row.split(factor=0.25, align=True)
            label_col = mheight_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Height:")
            mheight_split.prop(operator, "mask_height", text="")
            mask_col.separator(factor=0.4)

    # Interpolation
    minterp_row = mask_col.row(align=True)
    minterp_row.scale_y = 1.4
    minterp_split = minterp_row.split(factor=0.25, align=True)
    label_col = minterp_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Interpolation:")
    minterp_split.prop(operator, "mask_interpolation", text="")
    mask_col.separator(factor=0.4)

    # Texture coordinates
    mtexcoord_row = mask_col.row(align=True)
    mtexcoord_row.scale_y = 1.4
    mtexcoord_split = mtexcoord_row.split(factor=0.25, align=True)
    label_col = mtexcoord_split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text="Vector:")

    mtexcoord_value_col = mtexcoord_split.column(align=True)
    crow = mtexcoord_value_col.row(align=True)
    crow.prop(operator, "mask_texcoord_type", text="")
    if operator.mask_texcoord_type == "UV" and obj.type == "MESH":
        crow.prop_search(operator, "mask_uv_name", operator, "uv_map_coll", text="", icon="GROUP_UVS")
    mask_col.separator(factor=0.4)

    if not operator.mask_image_filepath:
        # UDIM
        mudim_row = mask_col.row(align=True)
        mudim_row.scale_y = 1.2
        mudim_split = mudim_row.split(factor=0.25, align=True)
        mudim_split.label(text="")
        checkbox_col = mudim_split.column(align=True)
        checkbox_col.prop(operator, "use_udim_for_mask")
        mask_col.separator(factor=0.4)

        # Image Atlas
        matlas_row = mask_col.row(align=True)
        matlas_row.scale_y = 1.2
        matlas_split = matlas_row.split(factor=0.25, align=True)
        matlas_split.label(text="")
        checkbox_col = matlas_split.column(align=True)
        checkbox_col.prop(operator, "use_image_atlas_for_mask", text="Use Image Atlas")
        mask_col.separator(factor=0.4)
