# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Custom layer list drawing for Substance 3D Painter-style nested layers and masks."""

import bpy
from bpy.types import UIList

from ...core.layer.get_layers import get_layer_depth
from ...core.layer.layer_utils import get_layer_index
from ...core.node.get_nodes import get_layer_source, get_mask_source
from ..utils.thumbnail_generator import get_layer_thumbnail


# Blend mode items for the dropdown (abbreviated for compact display)
BLEND_MODE_ABBREV = {
    'MIX': 'Norm',
    'ADD': 'Add',
    'SUBTRACT': 'Sub',
    'MULTIPLY': 'Mult',
    'SCREEN': 'Scrn',
    'DIVIDE': 'Div',
    'DARKEN': 'Dark',
    'LIGHTEN': 'Light',
    'OVERLAY': 'Over',
    'DIFFERENCE': 'Diff',
    'SOFT_LIGHT': 'Soft',
    'LINEAR_LIGHT': 'Lin',
    'DODGE': 'Dodge',
    'BURN': 'Burn',
    'EXCLUSION': 'Excl',
    'HUE': 'Hue',
    'SATURATION': 'Sat',
    'VALUE': 'Val',
    'COLOR': 'Colr',
}


def get_active_channel_index(context):
    """Get the index of the active channel filter.

    Args:
        context: Blender context.

    Returns:
        int: Index of the active channel, defaults to 0 (first channel).
    """
    wm = context.window_manager
    if hasattr(wm, 'mixar_ui') and hasattr(wm.mixar_ui, 'active_channel_filter'):
        # Parse channel index from filter value
        filter_val = wm.mixar_ui.active_channel_filter
        if filter_val and filter_val.isdigit():
            return int(filter_val)
    return 0


def get_layer_icon(layer):
    """Get appropriate icon for layer type.

    Args:
        layer: MLayer instance.

    Returns:
        str: Blender icon name.
    """
    type_icons = {
        'COLOR': 'COLOR',
        'IMAGE': 'BRUSHES_ALL',
        'GROUP': 'FILE_FOLDER',
        'VCOL': 'VPAINT_HLT',
        'HEMI': 'LIGHT_SUN',
        'AO': 'SHADING_RENDERED',
        'BACKGROUND': 'WORLD',
        'PROCEDURAL': 'MATERIAL',
        'BRICK': 'TEXTURE',
        'CHECKER': 'TEXTURE',
        'GRADIENT': 'TEXTURE',
        'MAGIC': 'TEXTURE',
        'MUSGRAVE': 'TEXTURE',
        'NOISE': 'TEXTURE',
        'VORONOI': 'TEXTURE',
        'WAVE': 'TEXTURE',
        'GABOR': 'TEXTURE',
        'EDGE_DETECT': 'MESH_DATA',
    }
    return type_icons.get(layer.type, 'TEXTURE')


def get_mask_icon(mask):
    """Get appropriate icon for mask type.

    Args:
        mask: Mask instance.

    Returns:
        str: Blender icon name.
    """
    type_icons = {
        'COLOR': 'COLOR',
        'IMAGE': 'IMAGE_DATA',
        'VCOL': 'VPAINT_HLT',
        'HEMI': 'LIGHT_SUN',
        'AO': 'SHADING_RENDERED',
        'COLOR_ID': 'RESTRICT_COLOR_ON',
        'OBJECT_INDEX': 'OBJECT_DATA',
        'EDGE_DETECT': 'EDGESEL',
        'MODIFIER': 'MODIFIER',
        'BRICK': 'TEXTURE',
        'CHECKER': 'TEXTURE',
        'GRADIENT': 'TEXTURE',
        'MAGIC': 'TEXTURE',
        'MUSGRAVE': 'TEXTURE',
        'NOISE': 'TEXTURE',
        'VORONOI': 'TEXTURE',
        'WAVE': 'TEXTURE',
    }
    return type_icons.get(mask.type, 'MOD_MASK')


def _is_layer_hidden_by_collapsed_parent(layer, mp, visited=None):
    """Check if layer is hidden because its parent group is collapsed.

    Args:
        layer: MLayer instance.
        mp: MPaint root property group.
        visited: Set of visited layer indices to prevent infinite recursion.

    Returns:
        bool: True if layer should be hidden.
    """
    if visited is None:
        visited = set()

    layer_idx = get_layer_index(layer)
    if layer_idx in visited:
        # Cycle detected, break recursion
        return False
    visited.add(layer_idx)

    if layer.parent_idx == -1:
        return False
    if layer.parent_idx >= len(mp.layers) or layer.parent_idx < 0:
        return False
    parent = mp.layers[layer.parent_idx]
    if parent.type == 'GROUP' and hasattr(parent, 'expand_children') and not parent.expand_children:
        return True
    # Recursively check for nested groups
    return _is_layer_hidden_by_collapsed_parent(parent, mp, visited)


def _has_children(layer, mp):
    """Check if a GROUP layer has any children.

    Args:
        layer: MLayer instance.
        mp: MPaint root property group.

    Returns:
        bool: True if layer has children.
    """
    if layer.type != 'GROUP':
        return False
    layer_idx = get_layer_index(layer)
    if layer_idx is None:
        return False
    return any(l.parent_idx == layer_idx for l in mp.layers)


def draw_nested_layer_list(context, layout, mp):
    """Draw Substance 3D Painter-style nested layer list with masks.

    Args:
        context: Blender context.
        layout: UI layout to draw into.
        mp: MPaint root property group containing layers.
    """
    if not mp or not hasattr(mp, 'layers'):
        return

    # Create scrollable list area
    col = layout.column(align=True)

    # Get active channel for blend mode display
    channel_idx = get_active_channel_index(context)
    material_name = mp.id_data.name if hasattr(mp, 'id_data') else ""

    # Draw each layer with its masks
    for layer_idx, layer in enumerate(mp.layers):
        # Skip baked-to-layer types (they're shown in the Baking panel)
        if _is_baked_to_layer(layer):
            continue

        # Skip layers hidden by collapsed parent groups
        if _is_layer_hidden_by_collapsed_parent(layer, mp):
            continue

        # Draw the layer row
        draw_layer_row(context, col, mp, layer, layer_idx, channel_idx, material_name)

        # If layer has masks and is expanded, draw masks as nested items
        # For GROUP layers, only show masks if the group is expanded (expand_children=True)
        if hasattr(layer, 'masks') and len(layer.masks) > 0:
            # Check if this is a collapsed GROUP - if so, hide masks too
            is_collapsed_group = (
                layer.type == 'GROUP' and
                hasattr(layer, 'expand_children') and
                not layer.expand_children
            )
            if not is_collapsed_group and hasattr(layer, 'expand_masks') and layer.expand_masks:
                draw_masks_nested(context, col, layer, channel_idx)


def draw_layer_row(context, layout, mp, layer, layer_idx, channel_idx, material_name):
    """Draw a single layer row with Substance Painter layout.

    Layout: [Expand masks] [Eye] [Thumbnail] [Name] [Blend] [Opacity]

    Args:
        context: Blender context.
        layout: UI layout to draw into.
        mp: MPaint root property group.
        layer: MLayer instance.
        layer_idx: Index of this layer.
        channel_idx: Active channel index.
        material_name: Material name for thumbnail cache.
    """
    # Check if this is the active layer
    is_active = (layer_idx == mp.active_layer_index)

    # Create box for outline, then row inside it
    box = layout.box()
    row = box.row(align=True)
    row.scale_y = 1.2

    # Add left strap indicator (for active) or placeholder (for non-active)
    strap = row.row(align=True)
    strap.ui_units_x = 0.2
    if is_active:
        strap.operator("layers.fake_highlight_op", text="", depress=True)
    else:
        strap.label(text="")

    # Add indentation for nested layers (children of GROUP layers)
    depth = get_layer_depth(layer) if layer.parent_idx != -1 else 0
    for _ in range(depth):
        row.label(text='', icon='BLANK1')

    # 1. Expand/collapse button for group children or masks
    has_masks = hasattr(layer, 'masks') and len(layer.masks) > 0
    has_children = _has_children(layer, mp)

    if has_children:
        # Group expand/collapse button (takes priority over masks)
        expand_icon = 'TRIA_DOWN' if layer.expand_children else 'TRIA_RIGHT'
        row.prop(layer, "expand_children", text="", icon=expand_icon, emboss=False)
    elif has_masks:
        expand_icon = 'TRIA_DOWN' if layer.expand_masks else 'TRIA_RIGHT'
        row.prop(layer, "expand_masks", text="", icon=expand_icon, emboss=False)
    else:
        # Placeholder space
        row.label(text="", icon='BLANK1')

    # 2. Visibility toggle (eye icon)
    vis_icon = 'HIDE_OFF' if layer.enable else 'HIDE_ON'
    row.prop(layer, "enable", text="", icon=vis_icon, emboss=False)

    # 3. Layer thumbnail or type icon
    thumbnail_id = 0
    # if layer.type == 'IMAGE':
    #     thumbnail_id = get_layer_thumbnail(layer, channel_idx, material_name)
    # elif layer.type == 'COLOR':
    #     thumbnail_id = get_layer_thumbnail(layer, channel_idx, material_name)

    if thumbnail_id > 0:
        row.template_icon(icon_value=thumbnail_id, scale=1.2)
    else:
        layer_icon = get_layer_icon(layer)
        row.label(text="", icon=layer_icon)

    # 4. Split layout depends on layer type
    # Paint/Fill layers: 40% name, 40% blank, 20% controls
    # GROUP layers: 40% name, 10% blank, 50% controls
    split_row = row.row(align=True)
    split = split_row.split(factor=0.4, align=True)

    # Name section (40% for all)
    name_col = split.row(align=True)
    op = name_col.operator("layers.select_layer", text=layer.name, emboss=False)
    op.index = layer_idx

    # 5. Remaining space: 40% blank, 20% intensity (same for all layer types)
    right_split = split.split(factor=0.67, align=True)
    right_split.label(text="")  # Blank space (40%)
    right_split.prop(layer, "intensity_value", text="", slider=True)


def draw_masks_nested(context, layout, layer, channel_idx):
    """Draw masks as nested items under a layer (Substance Painter style).

    Args:
        context: Blender context.
        layout: UI layout to draw into.
        layer: Parent MLayer instance.
        channel_idx: Active channel index for display context.
    """
    for mask_idx, mask in enumerate(layer.masks):
        draw_mask_row(context, layout, layer, mask, mask_idx, channel_idx)


def draw_mask_row(context, layout, layer, mask, mask_idx, channel_idx):
    """Draw a single mask row nested under its parent layer (same style as layer rows).

    Layout: [indent] [Eye] [Icon] [Name] [Blend] [Opacity]

    Supports Substance Painter-style mask selection - clicking the mask name
    selects it and shows its properties in the Properties panel.

    Args:
        context: Blender context.
        layout: UI layout to draw into.
        layer: Parent MLayer instance.
        mask: Mask instance.
        mask_idx: Index of this mask in layer.masks.
        channel_idx: Active channel index.
    """
    # Check if this mask is selected for editing
    # Must check both: mask index matches AND parent layer is the active layer
    wm = context.window_manager
    is_selected = False
    if hasattr(wm, 'mixar_ui'):
        mixar_ui = wm.mixar_ui
        layer_idx = get_layer_index(layer)
        is_selected = (
            mixar_ui.editing_mask_index == mask_idx and
            mixar_ui.active_layer_index == layer_idx
        )

    # Create box for outline, then row inside it (same as layers)
    box = layout.box()
    row = box.row(align=True)
    row.scale_y = 1.0  # Slightly smaller than layer rows (1.2)

    # Add left strap indicator (for selected) or placeholder (for non-selected)
    strap = row.row(align=True)
    strap.ui_units_x = 0.2
    if is_selected:
        strap.operator("layers.fake_highlight_op", text="", depress=True)
    else:
        strap.label(text="")

    # Indentation (layer depth + 1 for mask nesting)
    depth = get_layer_depth(layer) if layer.parent_idx != -1 else 0
    indent_count = depth + 1  # One level of nesting under parent layer
    # Add extra indentation for GROUP layer masks
    if layer.type == 'GROUP':
        indent_count += 1
    for _ in range(indent_count):
        row.label(text='', icon='BLANK1')

    # 1. Placeholder for expand button (masks don't have sub-items)
    row.label(text="", icon='BLANK1')

    # 2. Visibility toggle (eye icon - same as layers)
    vis_icon = 'HIDE_OFF' if mask.enable else 'HIDE_ON'
    row.prop(mask, "enable", text="", icon=vis_icon, emboss=False)

    # 3. Mask icon
    mask_icon = get_mask_icon(mask)
    row.label(text="", icon=mask_icon)

    # 4. Split remaining space: 40% name, 10% blank, 50% controls (for masks)
    layer_idx = get_layer_index(layer)
    if layer_idx is None:
        layer_idx = -1  # Fallback if layer not found

    split_row = row.row(align=True)
    split = split_row.split(factor=0.4, align=True)

    # Name section (40%)
    name_col = split.row(align=True)
    name_op = name_col.operator("layers.select_mask", text=mask.name, emboss=False)
    name_op.layer_index = layer_idx
    name_op.mask_index = mask_idx

    # Remaining 60% split into blank (40/60 ≈ 0.67) and controls (20/60 ≈ 0.33)
    # Same ratio as layer rows: 40% blank, 20% intensity
    right_split = split.split(factor=0.67, align=True)
    right_split.label(text="")  # Blank space (40%)

    # 5. Opacity in right section (20%)
    right_split.prop(mask, "intensity_value", text="", slider=True)

    # 6. Remove mask button
    row.context_pointer_set('layer', layer)
    row.context_pointer_set('mask', mask)
    row.operator("wm.m_remove_layer_mask", text="", icon='X', emboss=False)


def _is_baked_to_layer(layer):
    """Check if layer is a baked-to-layer type (should be hidden from main list).

    Args:
        layer: MLayer instance.

    Returns:
        bool: True if layer should be hidden from main list.
    """
    if layer.type != 'IMAGE':
        return False

    source = get_layer_source(layer)
    if not source or not hasattr(source, 'image') or not source.image:
        return False

    img = source.image
    return (hasattr(img, 'm_bake_info') and
            img.m_bake_info.is_baked and
            not img.m_bake_info.is_baked_channel)


# Keep the UIList for backward compatibility (used in Properties panel)
class LAYERS_UL_layer_list(UIList):
    """Substance 3D Painter-style layer list with inline blend mode and opacity."""

    bl_idname = "LAYERS_UL_layer_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw a single layer item in the list."""
        layer = item
        mp = data

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Add indentation for nested layers
            if layer.parent_idx != -1:
                depth = get_layer_depth(layer)
                for _ in range(depth):
                    row.label(text='', icon='BLANK1')

            # Expand button for group children or masks
            has_masks = hasattr(layer, 'masks') and len(layer.masks) > 0
            has_children = _has_children(layer, mp)

            if has_children:
                expand_icon = 'TRIA_DOWN' if layer.expand_children else 'TRIA_RIGHT'
                row.prop(layer, "expand_children", text="", icon=expand_icon, emboss=False)
            elif has_masks:
                expand_icon = 'TRIA_DOWN' if layer.expand_masks else 'TRIA_RIGHT'
                row.prop(layer, "expand_masks", text="", icon=expand_icon, emboss=False)
            else:
                row.label(text="", icon='BLANK1')

            # Visibility toggle
            vis_icon = 'HIDE_OFF' if layer.enable else 'HIDE_ON'
            row.prop(layer, "enable", text="", icon=vis_icon, emboss=False)

            # Thumbnail
            channel_idx = get_active_channel_index(context)
            material_name = data.id_data.name if hasattr(data, 'id_data') else ""
            thumbnail_id = 0
            if layer.type in {'IMAGE', 'COLOR'}:
                thumbnail_id = get_layer_thumbnail(layer, channel_idx, material_name)

            if thumbnail_id > 0:
                row.template_icon(icon_value=thumbnail_id, scale=1.0)
            else:
                layer_icon = get_layer_icon(layer)
                row.label(text="", icon=layer_icon)

            # Layer name
            row.prop(layer, "name", text="", emboss=False)

            # Blend mode and opacity
            self._draw_layer_blend_opacity(row, layer, mp, channel_idx)

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon=get_layer_icon(layer))

    def _draw_layer_blend_opacity(self, row, layer, mp, channel_idx):
        """Draw blend mode dropdown and opacity for layers.

        Blend mode is only shown for GROUP layers, not for Paint/Fill layers.
        """
        # Only show blend mode dropdown for GROUP layers
        if layer.type == 'GROUP' and channel_idx < len(layer.channels) and channel_idx < len(mp.channels):
            channel = layer.channels[channel_idx]
            root_ch = mp.channels[channel_idx]

            blend_row = row.row(align=True)
            blend_row.ui_units_x = 3.5
            if root_ch.type == 'NORMAL':
                blend_row.prop(channel, "normal_blend_type", text="")
            else:
                blend_row.prop(channel, "blend_type", text="")

        # Layer Opacity value (shown for all layer types)
        opacity_row = row.row(align=True)
        opacity_row.ui_units_x = 2.5
        opacity_row.prop(layer, "intensity_value", text="", slider=False)

    def filter_items(self, context, data, propname):
        """Filter out baked-to-layer types."""
        layers = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(layers)
        flt_neworder = []

        for i, layer in enumerate(layers):
            if _is_baked_to_layer(layer):
                flt_flags[i] = 0

        return flt_flags, flt_neworder
