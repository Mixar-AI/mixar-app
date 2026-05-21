# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel extras drawing functions for Fill layer material UI."""

from ...core.node.get_nodes import get_tree


def draw_channel_extras(layout, channel, root_ch, layer, expand_blend=False):
    """Draw extra controls based on override_type and channel type.

    Args:
        layout: Box layout to draw into
        channel: YLayerChannel
        root_ch: MPaintChannel (root channel)
        layer: Backend YLayer
        expand_blend: Whether the blend settings are expanded
    """
    # Normal channel has additional options - only show when expanded
    if root_ch.type == 'NORMAL':
        if expand_blend:
            if channel.override_type == 'IMAGE':
                draw_normal_image_extras(layout, channel)
            else:
                draw_normal_channel_extras(layout, channel, layer)
        return

    # Check if AO channel - image selector is shown inline for AO
    is_ao_channel = root_ch.name.upper() in ['AO', 'AMBIENT OCCLUSION']

    # For LAYER mode, no extra controls needed
    if channel.override_type == 'LAYER':
        return

    # For OVERRIDE mode, value/color control is shown inline
    if channel.override_type == 'OVERRIDE':
        return

    # For IMAGE mode, show image selector (except AO which shows inline)
    if channel.override_type == 'IMAGE' and not is_ao_channel:
        draw_channel_image_selector(layout, channel, root_ch, layer)


def draw_normal_image_extras(layout, channel):
    """Draw extras for Normal channel in IMAGE mode.

    Args:
        layout: Box layout to draw into
        channel: YLayerChannel for Normal
    """
    # Normal type selector
    type_row = layout.row(align=True)
    type_row.scale_y = 1.2
    split = type_row.split(factor=0.3, align=True)
    split.label(text="Type")
    split.prop(channel, "normal_map_type", text="")

    # Bump settings (only for bump types)
    if channel.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
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

    # Normal map strength
    if channel.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
        strength_row = layout.row(align=True)
        strength_row.scale_y = 1.2
        split = strength_row.split(factor=0.3, align=True)
        split.label(text="Strength")
        split.prop(channel, 'normal_strength', text="", slider=True)


def draw_normal_channel_extras(layout, channel, layer):
    """Draw extra options for Normal channel.

    Args:
        layout: Box layout to draw into
        channel: YLayerChannel for Normal
        layer: Backend YLayer
    """
    # Normal type row
    type_row = layout.row(align=True)
    type_row.scale_y = 1.2
    split = type_row.split(factor=0.3, align=True)
    split.label(text="Type")
    split.prop(channel, "normal_map_type", text="")

    # Bump settings
    if channel.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
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

    # Normal map strength
    if channel.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
        strength_row = layout.row(align=True)
        strength_row.scale_y = 1.2
        split = strength_row.split(factor=0.3, align=True)
        split.label(text="Strength")
        split.prop(channel, 'normal_strength', text="", slider=True)

    # VDM strength
    if channel.normal_map_type == 'VECTOR_DISPLACEMENT_MAP':
        vdisp_row = layout.row(align=True)
        vdisp_row.scale_y = 1.2
        split = vdisp_row.split(factor=0.3, align=True)
        split.label(text="VDM Strength")
        split.prop(channel, 'vdisp_strength', text="", slider=True)

        flip_row = layout.row(align=True)
        flip_row.scale_y = 1.2
        flip_row.prop(channel, 'vdisp_enable_flip_yz', text="Flip Y/Z")

    # Write Height checkbox
    wh_row = layout.row(align=True)
    wh_row.scale_y = 1.2
    wh_row.prop(channel, 'write_height', text="Write Height")

    # Normal map source selector
    if channel.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
        from .ui_helpers import draw_normal_map_image_source

        nm_box = layout.box()
        nm_header = nm_box.row(align=True)
        nm_header.label(text="Normal Map Source")

        src_row = nm_box.row()
        src_row.prop(channel, 'override_1_type', text="Type")

        if channel.override_1_type == 'IMAGE':
            draw_normal_map_image_source(nm_box, channel, layer)


def draw_ao_image_inline(layout, channel, layer):
    """Draw inline image selector for AO channel.

    Args:
        layout: Row layout to draw into
        channel: YLayerChannel
        layer: Backend YLayer
    """
    tree = get_tree(layer)
    source = None
    if channel.source:
        source = tree.nodes.get(channel.source) if tree else None

    if source and source.bl_idname == 'ShaderNodeTexImage':
        layout.template_ID(source, "image", open="image.open")
    else:
        layout.context_pointer_set('layer', layer)
        layout.context_pointer_set('channel', channel)
        layout.operator(
            'wm.m_open_image_to_override_layer_channel',
            text="Open",
            icon='FILEBROWSER'
        )


def draw_channel_image_selector(layout, channel, root_ch, layer):
    """Draw image selector for IMAGE mode.

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
        split = img_row.split(factor=0.3, align=True)
        split.label(text="Image")
        split.template_ID(source, "image", open="image.open")
    else:
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
