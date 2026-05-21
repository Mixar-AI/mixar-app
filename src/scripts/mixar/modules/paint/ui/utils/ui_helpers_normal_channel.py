# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Normal channel UI helper functions.

Provides a specialized UI panel for Normal channel with:
- Type selector (Bump Map, Normal Map, Bump + Normal Map)
- Height, Midlevel, and Strength sliders based on type
- Image properties section for loaded textures
"""

from ...core.node.get_nodes import get_tree


def draw_normal_channel_panel(context, layout, channel, root_ch, layer):
    """Draw Normal channel panel with type and parameters.

    Shows different controls based on normal_map_type:
    - BUMP_MAP: Height, Midlevel sliders
    - NORMAL_MAP: Strength slider
    - BUMP_NORMAL_MAP: All sliders

    Args:
        context: Blender context
        layout: UI layout to draw into
        channel: YLayerChannel (Normal channel)
        root_ch: MPaintChannel (root channel)
        layer: YLayer (parent layer)
    """
    normal_map_type = getattr(channel, 'normal_map_type', 'BUMP_MAP')

    # === NORMAL SETTINGS SECTION (combined) ===
    _draw_normal_settings_section(layout, channel, normal_map_type)

    # === VECTOR DISPLACEMENT SETTINGS ===
    if normal_map_type == 'VECTOR_DISPLACEMENT_MAP':
        _draw_vdm_settings_section(layout, channel)

    # === IMAGE PROPERTIES SECTION ===
    _draw_image_properties_section(layout, channel, layer, normal_map_type)


def _draw_normal_settings_section(layout, channel, normal_map_type):
    """Draw combined Normal Settings section.

    Contains: Type, Height, Midlevel, Strength, Space, Write Height
    based on the selected normal_map_type.

    Args:
        layout: UI layout
        channel: YLayerChannel
        normal_map_type: Current normal map type
    """
    settings_box = layout.box()
    header = settings_box.row(align=True)
    header.scale_y = 1.1
    header.label(text="Normal Settings", icon='NORMALS_FACE')

    content = settings_box.column(align=True)
    content.scale_y = 1.1

    # Type row
    type_row = content.row(align=True)
    split = type_row.split(factor=0.25, align=True)
    split.label(text="Type")
    split.prop(channel, "normal_map_type", text="")

    # Separator after type
    content.separator(factor=1.0)

    # Height + Midlevel on one row (for bump types)
    if normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
        bump_row = content.row(align=True)
        left_split = bump_row.split(factor=0.5, align=True)

        # Height
        height_sub = left_split.row(align=True)
        height_sub.label(text="Height")
        height_sub.prop(channel, 'bump_distance', text="", slider=True)

        # Midlevel
        mid_sub = left_split.row(align=True)
        mid_sub.label(text="Midlevel")
        mid_sub.prop(channel, 'bump_midlevel', text="", slider=True)

    # Strength + Space on one row (for normal map types)
    if normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
        normal_row = content.row(align=True)

        if hasattr(channel, 'normal_space'):
            left_split = normal_row.split(factor=0.5, align=True)

            strength_sub = left_split.row(align=True)
            strength_sub.label(text="Strength")
            strength_sub.prop(channel, 'normal_strength', text="", slider=True)

            space_sub = left_split.row(align=True)
            space_sub.label(text="Space")
            space_sub.prop(channel, 'normal_space', text="")
        else:
            split = normal_row.split(factor=0.25, align=True)
            split.label(text="Strength")
            split.prop(channel, 'normal_strength', text="", slider=True)

    # Write Height checkbox (for bump types and VDM)
    if normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP', 'VECTOR_DISPLACEMENT_MAP'}:
        content.separator(factor=1.0)
        wh_row = content.row(align=True)
        wh_row.prop(channel, 'write_height', text="Write Height")


def _draw_vdm_settings_section(layout, channel):
    """Draw Vector Displacement Map settings section.

    Args:
        layout: UI layout
        channel: YLayerChannel
    """
    settings_box = layout.box()
    header = settings_box.row(align=True)
    header.scale_y = 1.1
    header.label(text="VDM Settings", icon='MOD_DISPLACE')

    content = settings_box.column(align=True)
    content.scale_y = 1.1

    if hasattr(channel, 'vdisp_strength'):
        vdm_row = content.row(align=True)

        if hasattr(channel, 'vdisp_enable_flip_yz'):
            left_split = vdm_row.split(factor=0.5, align=True)

            strength_sub = left_split.row(align=True)
            strength_sub.label(text="Strength")
            strength_sub.prop(channel, 'vdisp_strength', text="", slider=True)

            flip_sub = left_split.row(align=True)
            flip_sub.label(text="Flip Y/Z")
            flip_sub.prop(channel, 'vdisp_enable_flip_yz', text="")
        else:
            split = vdm_row.split(factor=0.25, align=True)
            split.label(text="Strength")
            split.prop(channel, 'vdisp_strength', text="", slider=True)


def _draw_image_properties_section(layout, channel, layer, normal_map_type):
    """Draw Image Properties section if any images are loaded.

    Shows properties for bump image (source) and/or normal image (source_1)
    based on normal_map_type and what images are loaded.

    Args:
        layout: UI layout
        channel: YLayerChannel
        layer: YLayer
        normal_map_type: Current normal map type
    """
    tree = get_tree(layer)
    if not tree:
        return

    # Collect loaded images
    bump_source = None
    normal_source = None

    # Check bump source (for BUMP_MAP and BUMP_NORMAL_MAP)
    if normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
        if channel.source:
            node = tree.nodes.get(channel.source)
            if node and node.bl_idname == 'ShaderNodeTexImage' and node.image:
                bump_source = node

    # Check normal source (for NORMAL_MAP and BUMP_NORMAL_MAP)
    if normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
        if hasattr(channel, 'source_1') and channel.source_1:
            node = tree.nodes.get(channel.source_1)
            if node and node.bl_idname == 'ShaderNodeTexImage' and node.image:
                normal_source = node

    # Only show section if at least one image is loaded
    if not bump_source and not normal_source:
        return

    # layout.separator(factor=0.5)

    # Section box with header
    props_box = layout.box()
    header = props_box.row(align=True)
    header.scale_y = 1.1
    header.label(text="Image Properties", icon='IMAGE_DATA')

    content = props_box.column(align=True)
    content.scale_y = 1.1

    # Draw bump image properties
    if bump_source:
        if normal_source:
            # Label to distinguish when both are present
            content.label(text="Bump Image:", icon='RNDCURVE')
        _draw_image_properties(content, bump_source)

    # Draw normal image properties
    if normal_source:
        if bump_source:
            content.separator(factor=0.5)
            content.label(text="Normal Image:", icon='NORMALS_FACE')
        _draw_image_properties(content, normal_source)


def _draw_image_properties(layout, source):
    """Draw image properties (Color Space, Alpha Mode, Interpolation, Extension).

    Args:
        layout: UI layout to draw into
        source: ShaderNodeTexImage node with the image
    """
    if not source or source.bl_idname != 'ShaderNodeTexImage' or not source.image:
        return

    image = source.image
    props_col = layout.column(align=True)
    props_col.scale_y = 1.1

    # Color Space
    cs_row = props_col.row(align=True)
    split = cs_row.split(factor=0.35, align=True)
    split.label(text="Color Space")
    split.prop(image.colorspace_settings, "name", text="")

    # Alpha Mode
    alpha_row = props_col.row(align=True)
    split = alpha_row.split(factor=0.35, align=True)
    split.label(text="Alpha Mode")
    split.prop(image, "alpha_mode", text="")

    # Interpolation (on the node)
    interp_row = props_col.row(align=True)
    split = interp_row.split(factor=0.35, align=True)
    split.label(text="Interpolation")
    split.prop(source, "interpolation", text="")

    # Extension (on the node)
    ext_row = props_col.row(align=True)
    split = ext_row.split(factor=0.35, align=True)
    split.label(text="Extension")
    split.prop(source, "extension", text="")
