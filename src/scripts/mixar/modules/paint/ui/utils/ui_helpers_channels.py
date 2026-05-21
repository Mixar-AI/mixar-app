# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel settings UI drawing helpers.

Contains channel-related drawing functions for layer settings:
- Normal map image source selector
- Channel settings with override system
"""

from ...core.node.get_nodes import get_tree


def draw_normal_map_image_source(layout, channel, layer):
    """Draw normal map image source selector for NORMAL_MAP and BUMP_NORMAL_MAP modes.

    Shows image selector for the normal map texture using the override_1/source_1 system.

    Args:
        layout: UI layout
        channel: YLayerChannel (layer-specific channel data)
        layer: YLayer (needed for context pointer)
    """
    # Get channel's source_1 node for normal map image
    tree = get_tree(layer)
    source_1 = None
    if channel.source_1:
        source_1 = tree.nodes.get(channel.source_1) if tree else None

    # Image selector row
    img_row = layout.row(align=True)
    img_row.scale_y = 1.1

    if source_1 and source_1.bl_idname == 'ShaderNodeTexImage':
        # Show image template_ID with open button
        img_row.template_ID(source_1, "image", open="image.open")

        # Show flip Y option for DirectX normal maps
        flip_row = layout.row(align=True)
        flip_row.prop(channel, 'image_flip_y', text="Flip G (DirectX)")
    else:
        # Show buttons to add image - both file browser and dropdown for existing images
        img_row.context_pointer_set('parent', channel)
        img_row.context_pointer_set('layer', layer)
        img_row.context_pointer_set('channel', channel)
        # File browser button
        img_row.operator('wm.m_open_image_to_override_1_layer_channel', text="Open", icon='FILEBROWSER')
        # Dropdown to select from existing images
        img_row.operator('wm.m_select_existing_normal_image_for_channel', text="", icon='DOWNARROW_HLT')


def draw_channel_settings(context, layout, channel, root_ch, layer):
    """Draw settings for a single channel with 4-option override_type system.

    Shows channel header with override_type dropdown (Brush, Pass-through, Custom, Image)
    and appropriate controls based on selected type.

    Args:
        context: Blender context
        layout: UI layout
        channel: YLayerChannel (layer-specific channel data)
        root_ch: MPaintChannel (root channel with name and type info)
        layer: YLayer (needed for context pointer)
    """
    # Channel box
    box = layout.box()
    box.scale_y = 1.2

    # Header row: expand toggle, enable toggle, channel name, override_type dropdown
    header = box.row(align=True)
    header.scale_y = 1.3

    # Expand toggle (triangle icon)
    expand_blend = getattr(channel, 'expand_blend_settings', False)
    icon = 'TRIA_DOWN' if expand_blend else 'TRIA_RIGHT'
    header.prop(channel, "expand_blend_settings", text="", icon=icon, emboss=False)

    # Enable toggle checkbox
    header.prop(channel, "enable", text="")

    # Channel name (20% width)
    split = header.split(factor=0.20, align=True)
    name_col = split.row(align=True)
    name_col.enabled = channel.enable
    name_col.label(text=root_ch.name)

    # Controls row
    ctrl_row = split.row(align=True)
    ctrl_row.enabled = channel.enable

    # Color picker for Color channel (linked to brush)
    if root_ch.type == 'COLOR':
        brush = context.tool_settings.image_paint.brush if context else None
        if brush:
            ctrl_row.prop(brush, "color", text="")

    # Source type dropdown (Brush, Pass-through, Custom, Image)
    ctrl_row.prop(channel, "override_type", text="")

    # Expanded section: blend mode + opacity
    if expand_blend:
        blend_col = box.column(align=True)
        blend_col.scale_y = 1.2
        blend_col.separator(factor=0.3)

        # Blend mode row
        blend_row = blend_col.row(align=True)
        split = blend_row.split(factor=0.3, align=True)
        split.label(text="Blend")
        if root_ch.type == "NORMAL":
            split.prop(channel, "normal_blend_type", text="")
        else:
            split.prop(channel, "blend_type", text="")

        # Opacity row
        opacity_row = blend_col.row(align=True)
        split = opacity_row.split(factor=0.3, align=True)
        split.label(text="Opacity")
        split.prop(channel, "intensity_value", text="", slider=True)

    # Extra controls based on override_type and channel type
    if channel.enable:
        _draw_channel_settings_extras(box, channel, root_ch, layer, expand_blend)


def _draw_channel_settings_extras(layout, channel, root_ch, layer, expand_blend=False):
    """Draw extra controls based on override_type and channel type.

    Args:
        layout: Box layout to draw into
        channel: YLayerChannel
        root_ch: MPaintChannel (root channel)
        layer: Backend YLayer
        expand_blend: Whether blend settings are expanded (normal extras only show when expanded)
    """
    override_type = getattr(channel, 'override_type', 'LAYER')

    # Normal channel has additional options - only show when expanded
    if root_ch.type == 'NORMAL':
        if not expand_blend:
            return

        # Normal type row
        type_row = layout.row(align=True)
        type_row.scale_y = 1.2
        split = type_row.split(factor=0.3, align=True)
        split.label(text="Type")
        split.prop(channel, "normal_map_type", text="")

        # Bump settings (only for bump types)
        if channel.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
            # Height range
            height_row = layout.row(align=True)
            height_row.scale_y = 1.2
            split = height_row.split(factor=0.3, align=True)
            split.label(text="Height")
            split.prop(channel, 'bump_distance', text="", slider=True)

            # Midlevel
            mid_row = layout.row(align=True)
            mid_row.scale_y = 1.2
            split = mid_row.split(factor=0.3, align=True)
            split.label(text="Midlevel")
            split.prop(channel, 'bump_midlevel', text="", slider=True)

        # Normal map strength - for NORMAL_MAP and BUMP_NORMAL_MAP modes
        if channel.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
            strength_row = layout.row(align=True)
            strength_row.scale_y = 1.2
            split = strength_row.split(factor=0.3, align=True)
            split.label(text="Strength")
            split.prop(channel, 'normal_strength', text="", slider=True)

        # VDM strength - for VECTOR_DISPLACEMENT_MAP mode
        if channel.normal_map_type == 'VECTOR_DISPLACEMENT_MAP':
            vdisp_row = layout.row(align=True)
            vdisp_row.scale_y = 1.2
            split = vdisp_row.split(factor=0.3, align=True)
            split.label(text="VDM Strength")
            split.prop(channel, 'vdisp_strength', text="", slider=True)

            # Flip Y/Z toggle
            flip_row = layout.row(align=True)
            flip_row.scale_y = 1.2
            flip_row.prop(channel, 'vdisp_enable_flip_yz', text="Flip Y/Z")

        # Write Height checkbox
        wh_row = layout.row(align=True)
        wh_row.scale_y = 1.2
        wh_row.prop(channel, 'write_height', text="Write Height")

        # Normal map source selector - for NORMAL_MAP and BUMP_NORMAL_MAP modes
        if channel.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
            nm_box = layout.box()
            nm_header = nm_box.row(align=True)
            nm_header.label(text="Normal Map Source")

            # Override 1 type selector
            src_row = nm_box.row()
            src_row.prop(channel, 'override_1_type', text="Type")

            # Show image selector if using IMAGE type
            if channel.override_1_type == 'IMAGE':
                draw_normal_map_image_source(nm_box, channel, layer)

        # Show bump/height image selector for BUMP_MAP and BUMP_NORMAL_MAP when override_type is IMAGE
        if channel.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
            if override_type == 'IMAGE':
                _draw_image_channel_selector(layout, channel, root_ch, layer)

        return

    # For PASSTHROUGH mode, no extra controls needed
    if override_type == 'PASSTHROUGH':
        return

    # For LAYER mode, no extra controls needed (uses layer source)
    if override_type == 'LAYER':
        return

    # For OVERRIDE mode, show value/color control
    if override_type == 'OVERRIDE':
        value_row = layout.row(align=True)
        value_row.scale_y = 1.2
        split = value_row.split(factor=0.3, align=True)
        split.label(text="Value")

        if root_ch.type == 'VALUE':
            # Float slider for VALUE channels (Metallic, Roughness)
            split.prop(channel, 'override_value', text="", slider=True)
        else:
            # Color picker for RGB channels
            split.prop(channel, 'override_color', text="")

    # For IMAGE mode, show image selector
    elif override_type == 'IMAGE':
        _draw_image_channel_selector(layout, channel, root_ch, layer)


def _draw_image_channel_selector(layout, channel, root_ch, layer):
    """Draw image selector row for IMAGE override mode.

    Args:
        layout: Layout to draw into
        channel: YLayerChannel
        root_ch: MPaintChannel (root channel)
        layer: Backend YLayer
    """
    tree = get_tree(layer)
    source = None
    if channel.source:
        source = tree.nodes.get(channel.source) if tree else None

    img_row = layout.row(align=True)
    img_row.scale_y = 1.2

    if source and source.bl_idname == 'ShaderNodeTexImage':
        # Show image template_ID
        split = img_row.split(factor=0.3, align=True)
        split.label(text="Image")
        split.template_ID(source, "image", open="image.open")
    else:
        # Show button to select/open image
        split = img_row.split(factor=0.3, align=True)
        split.label(text="Image")
        op_row = split.row(align=True)
        op_row.context_pointer_set('layer', layer)
        op_row.context_pointer_set('channel', channel)
        op_row.operator(
            'wm.m_open_image_to_override_layer_channel',
            text="Select Image",
            icon='FILEBROWSER'
        )
