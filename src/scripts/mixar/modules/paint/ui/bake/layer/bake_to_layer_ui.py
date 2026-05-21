# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing methods for MBakeToLayer operator."""

import bpy

from ....core.layer.layer_utils import get_root_height_channel
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_active_material


def _draw_row(col, label, scale_y=1.4, split_factor=0.25):
    """Create a standard row with label column and return split for content."""
    row = col.row(align=True)
    row.scale_y = scale_y
    split = row.split(factor=split_factor, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text=label)
    return row, split


def draw_bake_to_layer_ui(operator, context):
    """Draw the bake to layer operator UI."""
    layout = operator.layout
    layout.use_property_split = False
    layout.use_property_decorate = False

    node = get_active_mpaint_node()
    mp = node.node_tree.mp

    channel = mp.channels[int(operator.channel_idx)] if operator.channel_idx != "-1" else None
    height_root_ch = get_root_height_channel(mp)

    show_subsurf = not operator.type.startswith("MULTIRES_") and operator.type not in {"SELECTED_VERTICES"}
    show_disp = height_root_ch and show_subsurf

    main_col = layout.column(align=False)
    box = main_col.box()
    col = box.column(align=False)

    # Header
    header_row = col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Bake Settings", icon="RENDER_RESULT")
    col.separator(factor=1.2)

    # Overwrite/Name section
    _draw_overwrite_name_section(operator, col, channel)
    # Type-specific settings
    _draw_type_specific_settings(operator, col)
    # Image settings
    _draw_image_settings(operator, col)
    # UV and margin settings
    _draw_uv_margin_settings(operator, col)
    # AA and filtering
    _draw_aa_filtering_settings(operator, col)
    # Advanced options
    _draw_advanced_options(operator, col, show_subsurf, show_disp)

    col.separator(factor=0.8)
    main_col.separator(factor=0.8)


def _draw_overwrite_name_section(operator, col, channel):
    """Draw the overwrite and name section of the UI."""
    if not operator.overwrite_current:
        if len(operator.overwrite_coll) > 0:
            _, split = _draw_row(col, "Overwrite:", scale_y=1.2)
            split.prop(operator, "overwrite_choice", text="")
            col.separator(factor=0.4)

        if len(operator.overwrite_coll) > 0 and operator.overwrite_choice:
            label = "Layer:" if operator.target_type == "LAYER" else "Mask:"
            _, split = _draw_row(col, label)
            split.prop_search(operator, "overwrite_name", operator, "overwrite_coll", text="", icon="IMAGE_DATA")
            col.separator(factor=0.4)

        if not (len(operator.overwrite_coll) > 0 and operator.overwrite_choice):
            _, split = _draw_row(col, "Name:")
            split.prop(operator, "name", text="")
            col.separator(factor=0.4)

            # Channel selection for layers
            if operator.target_type == "LAYER" and operator.type != "OTHER_OBJECT_CHANNELS":
                _, split = _draw_row(col, "Channel:")
                rrow = split.row(align=True)
                rrow.prop(operator, "channel_idx", text="")
                if channel:
                    prop = "normal_blend_type" if channel.type == "NORMAL" else "blend_type"
                    rrow.prop(operator, prop, text="")
                col.separator(factor=0.4)

                if channel and channel.type == "NORMAL":
                    _, split = _draw_row(col, "Type:")
                    split.prop(operator, "normal_map_type", text="")
                    col.separator(factor=0.4)
    else:
        _, split = _draw_row(col, "Name:")
        split.label(text=operator.overwrite_name)
        col.separator(factor=0.4)


def _draw_type_specific_settings(operator, col):
    """Draw type-specific settings based on the bake type."""
    if operator.type.startswith("OTHER_OBJECT_"):
        _draw_other_object_settings(operator, col)
    elif operator.type == "POINTINESS":
        _, split = _draw_row(col, "Normalize:", scale_y=1.2)
        split.prop(operator, "normalize", text="Normalize Pointiness")
        col.separator(factor=0.4)
    elif operator.type == "AO":
        _draw_ao_settings(operator, col)
    elif operator.type in {"BEVEL_NORMAL", "BEVEL_MASK"}:
        _draw_bevel_settings(operator, col)
    elif operator.type.startswith("MULTIRES_"):
        _, split = _draw_row(col, "Base Level:")
        split.prop(operator, "multires_base", text="")
        col.separator(factor=0.4)
    elif operator.type == "POSITION":
        _draw_position_settings(operator, col)


def _draw_other_object_settings(operator, col):
    """Draw settings for OTHER_OBJECT_ bake types."""
    _, split = _draw_row(col, "Cage Object:", scale_y=1.2)
    split.prop(operator, "use_cage", text="")
    col.separator(factor=0.4)

    if operator.use_cage:
        _, split = _draw_row(col, "Cage:")
        split.prop_search(operator, "cage_object_name", operator, "cage_object_coll", text="", icon="OBJECT_DATA")
        col.separator(factor=0.4)

        _, split = _draw_row(col, "Extrusion:")
        split.prop(operator, "cage_extrusion", text="")
        col.separator(factor=0.4)

        if hasattr(bpy.context.scene.render.bake, "max_ray_distance"):
            _, split = _draw_row(col, "Max Distance:")
            split.prop(operator, "max_ray_distance", text="")
            col.separator(factor=0.4)


def _draw_ao_settings(operator, col):
    """Draw AO-specific settings."""
    _, split = _draw_row(col, "Distance:")
    split.prop(operator, "ao_distance", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Only Local:", scale_y=1.2)
    split.prop(operator, "only_local", text="")
    col.separator(factor=0.4)


def _draw_bevel_settings(operator, col):
    """Draw bevel-specific settings."""
    _, split = _draw_row(col, "Samples:")
    split.prop(operator, "bevel_samples", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Radius:")
    split.prop(operator, "bevel_radius", text="")
    col.separator(factor=0.4)


def _draw_position_settings(operator, col):
    """Draw position-specific settings."""
    _, split = _draw_row(col, "Space:")
    split.prop(operator, "position_space", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Normalize:", scale_y=1.2)
    split.prop(operator, "position_normalize", text="Normalize Position")
    col.separator(factor=0.4)


def _draw_image_settings(operator, col):
    """Draw image settings section."""
    _, split = _draw_row(col, "32-bit Float:", scale_y=1.2)
    split.prop(operator, "hdr", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Custom Res:", scale_y=1.2)
    split.prop(operator, "use_custom_resolution", text="")
    col.separator(factor=0.4)

    if not operator.use_custom_resolution:
        _, split = _draw_row(col, "Resolution:")
        crow = split.row(align=True)
        crow.prop(operator, "image_resolution", expand=True)
        col.separator(factor=0.4)
    else:
        _, split = _draw_row(col, "Width:")
        split.prop(operator, "width", text="")
        col.separator(factor=0.4)

        _, split = _draw_row(col, "Height:")
        split.prop(operator, "height", text="")
        col.separator(factor=0.4)

    _, split = _draw_row(col, "Samples:")
    split.prop(operator, "samples", text="")
    col.separator(factor=0.4)


def _draw_uv_margin_settings(operator, col):
    """Draw UV and margin settings section."""
    _, split = _draw_row(col, "UV Map:")
    split.prop_search(operator, "uv_map", operator, "uv_map_coll", text="", icon="GROUP_UVS")
    col.separator(factor=0.4)

    if operator.type == "FLOW":
        _, split = _draw_row(col, "Straight UV:")
        split.prop_search(operator, "uv_map_1", operator, "uv_map_coll", text="", icon="GROUP_UVS")
        col.separator(factor=0.4)

    _, split = _draw_row(col, "Margin:")
    margin_split = split.split(factor=0.4, align=True)
    margin_split.prop(operator, "margin", text="")
    margin_split.prop(operator, "margin_type", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Device:")
    split.prop(operator, "bake_device", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Interpolation:")
    split.prop(operator, "interpolation", text="")
    col.separator(factor=0.4)

    if operator.target_type == "MASK":
        _, split = _draw_row(col, "Blend:")
        split.prop(operator, "blend_type", text="")
        col.separator(factor=0.4)


def _draw_aa_filtering_settings(operator, col):
    """Draw AA and filtering settings."""
    if operator.type.startswith("OTHER_OBJECT_"):
        _, split = _draw_row(col, "Use SSAA:", scale_y=1.2)
        split.prop(operator, "ssaa", text="")
    else:
        _, split = _draw_row(col, "Use FXAA:", scale_y=1.2)
        split.prop(operator, "fxaa", text="")
    col.separator(factor=0.4)

    if operator.type in {"AO", "BEVEL_MASK", "BEVEL_NORMAL"}:
        _, split = _draw_row(col, "Use Denoise:", scale_y=1.2)
        split.prop(operator, "denoise", text="")
        col.separator(factor=0.4)


def _draw_advanced_options(operator, col, show_subsurf_influence, show_use_baked_disp):
    """Draw advanced options section."""
    if show_subsurf_influence:
        row, split = _draw_row(col, "Subsurf:", scale_y=1.2)
        row.active = not operator.use_baked_disp
        split.prop(operator, "subsurf_influence", text="")
        col.separator(factor=0.4)

    if show_use_baked_disp:
        _, split = _draw_row(col, "Use Disp:", scale_y=1.2)
        split.prop(operator, "use_baked_disp", text="")
        col.separator(factor=0.4)

    _, split = _draw_row(col, "Flip Normals:", scale_y=1.2)
    split.prop(operator, "flip_normals", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Force All Poly:", scale_y=1.2)
    split.prop(operator, "force_bake_all_polygons", text="")
    col.separator(factor=0.4)

    _, split = _draw_row(col, "Use UDIM:", scale_y=1.2)
    split.prop(operator, "use_udim", text="")
    col.separator(factor=0.4)
