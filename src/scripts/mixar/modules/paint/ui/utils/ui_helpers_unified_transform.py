# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unified transform panel for layers, channels, and masks.

Consolidates all transform controls into a single panel that adapts
based on context (active channel, layer type, editing mask).
"""

import bpy

from ...core.node.get_nodes import get_tree, get_layer_source
from ...core.subtree.get_subtree import get_mask_tree, get_tree as get_layer_tree
from ..operators.decal_operators import get_decal_object
from .ui_helpers_base import draw_input_prop


def layer_has_any_images(layer):
    """Check if a layer has any images in its source or channels.

    Args:
        layer: YLayer instance

    Returns:
        bool: True if layer has any image sources
    """
    # Check layer source for Fill layers with IMAGE source type
    if hasattr(layer, 'source_type') and layer.source_type == 'IMAGE':
        return True

    # Check if layer source node is an image texture
    tree = get_tree(layer)
    if tree:
        source = get_layer_source(layer, tree)
        if source and source.bl_idname == 'ShaderNodeTexImage' and source.image:
            return True

    # Check channel sources for IMAGE override
    for ch in layer.channels:
        override_type = getattr(ch, 'override_type', 'LAYER')
        if override_type == 'IMAGE':
            if ch.source and tree:
                ch_source = tree.nodes.get(ch.source)
                if ch_source and ch_source.bl_idname == 'ShaderNodeTexImage':
                    return True

        # Check override_1 for Normal channels
        override_1_type = getattr(ch, 'override_1_type', 'DEFAULT')
        if override_1_type == 'IMAGE':
            source_1 = getattr(ch, 'source_1', '')
            if source_1 and tree:
                ch_source_1 = tree.nodes.get(source_1)
                if ch_source_1 and ch_source_1.bl_idname == 'ShaderNodeTexImage':
                    return True

    return False


def get_mask_mapping_node(mask):
    """Get the mapping node for a mask.

    Args:
        mask: YLayerMask instance

    Returns:
        Mapping node or None
    """
    tree = get_mask_tree(mask)
    if tree and mask.mapping:
        return tree.nodes.get(mask.mapping)
    return None


def get_layer_mapping_node(layer):
    """Get the mapping node for a layer.

    Args:
        layer: YLayer instance

    Returns:
        Mapping node or None
    """
    tree = get_tree(layer)
    if tree and layer.mapping:
        return tree.nodes.get(layer.mapping)
    return None


def draw_unified_transform_panel(context, layout, layer, mp):
    """Draw unified transform panel in properties area.

    Shows transform controls based on context:
    1. If editing a mask -> mask transform
    2. If active channel has IMAGE override -> channel image transform
    3. If fill layer with IMAGE/MATERIAL -> layer transform
    4. Otherwise -> nothing

    Args:
        context: Blender context
        layout: UI layout to draw into
        layer: Active YLayer
        mp: Root MPaint property group
    """
    wm = context.window_manager
    mixar_ui = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

    # Determine transform context
    ctx_type, target, display_name = _get_transform_context(mp, layer, mixar_ui)

    if ctx_type is None:
        return  # No transform to show

    # Get expand state from UI state
    expand = mixar_ui.expand_transform if mixar_ui else True

    # Draw header with expand toggle
    header_row = layout.row(align=True)
    header_row.scale_y = 1.2

    # Collapse arrow icon
    icon = 'TRIA_DOWN' if expand else 'TRIA_RIGHT'
    if mixar_ui:
        header_row.prop(mixar_ui, "expand_transform", text="", icon=icon, emboss=False)

    # Show what is being transformed
    header_row.label(text=f"Transform", icon='ORIENTATION_LOCAL')

    if not expand:
        return

    layout.separator(factor=0.3)

    # Draw appropriate transform controls
    if ctx_type == 'MASK':
        _draw_mask_transform(layout, target)
    elif ctx_type == 'LAYER':
        _draw_layer_transform(layout, layer)


def _get_transform_context(mp, layer, mixar_ui):
    """Determine what transform controls to show.

    Transform is always available when:
    1. Editing a mask -> show mask transform (coordinate section + transform grid if mapping exists)
    2. Layer has a mapping node -> show layer transform
    3. Paint Layers (type='IMAGE') -> no transform (skip)

    Args:
        mp: Root MPaint property group
        layer: Active YLayer
        mixar_ui: MixarUIState instance or None

    Returns:
        Tuple of (context_type, target_object, display_name)
        context_type: 'LAYER', 'MASK', or None
        target_object: The layer/mask to transform
        display_name: String to show in header
    """
    # Priority 1: Editing a mask - always show transform for mask
    if mixar_ui and mixar_ui.editing_mask_index >= 0:
        mask_idx = mixar_ui.editing_mask_index
        if mask_idx < len(layer.masks):
            mask = layer.masks[mask_idx]
            return ('MASK', mask, f"Mask: {mask.name}")

    # Skip transform for Paint Layers (type='IMAGE') only on Channels tab
    # Show transform on Brush tab for Paint Layers
    if layer.type == 'IMAGE':
        if mixar_ui and mixar_ui.main_panel_tab == 'CHANNELS':
            return (None, None, None)

    # Priority 2: Layer transform - available for non-paint layers
    # Uses mapping node if exists, otherwise uses layer properties
    return ('LAYER', layer, "Layer")


def _draw_layer_transform(layout, layer):
    """Draw transform controls for layer.

    Uses mapping node if available, otherwise uses layer properties directly.
    Shows offset, rotation, and scale in a clean 3-column grid layout.

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    mapping = get_layer_mapping_node(layer)

    # Check if layer has any images - only show Coordinate section if images exist
    has_images = layer_has_any_images(layer)

    if has_images:
        # === COORDINATE SECTION ===
        _draw_coordinate_section(layout, layer)
        layout.separator(factor=0.3)

    # For Decal coordinate type, skip the transform controls
    texcoord_type = getattr(layer, 'texcoord_type', 'UV')
    if texcoord_type == 'Decal':
        return

    # Main container
    main_box = layout.box()
    main_col = main_box.column(align=True)

    # === OFFSET / ROTATION / SCALE in 3 columns ===
    grid_row = main_col.row(align=True)

    if mapping:
        # Use mapping node inputs directly
        # --- Offset Column ---
        offset_col = grid_row.column(align=True)
        offset_col.scale_x = 1.0
        offset_col.label(text="Offset")
        if len(mapping.inputs) > 1:
            offset_input = mapping.inputs[1]
            offset_col.prop(offset_input, "default_value", index=0, text="X")
            offset_col.prop(offset_input, "default_value", index=1, text="Y")
            offset_col.prop(offset_input, "default_value", index=2, text="Z")

        # --- Rotation Column ---
        rot_col = grid_row.column(align=True)
        rot_col.scale_x = 1.0
        rot_col.label(text="Rotation")
        if len(mapping.inputs) > 2:
            rotation_input = mapping.inputs[2]
            rot_col.prop(rotation_input, "default_value", index=0, text="X")
            rot_col.prop(rotation_input, "default_value", index=1, text="Y")
            rot_col.prop(rotation_input, "default_value", index=2, text="Z")

        # --- Scale Column ---
        scale_col = grid_row.column(align=True)
        scale_col.scale_x = 1.0

        # Scale header with lock toggle
        scale_header = scale_col.row(align=True)
        scale_header.label(text="Scale")
        lock_icon = 'LOCKED' if layer.enable_uniform_scale else 'UNLOCKED'
        scale_header.prop(layer, "enable_uniform_scale", text="", icon=lock_icon, emboss=False)

        if len(mapping.inputs) > 3:
            scale_input = mapping.inputs[3]
            if layer.enable_uniform_scale:
                draw_input_prop(scale_col, layer, 'uniform_scale_value', text="XYZ")
            else:
                scale_col.prop(scale_input, "default_value", index=0, text="X")
                scale_col.prop(scale_input, "default_value", index=1, text="Y")
                scale_col.prop(scale_input, "default_value", index=2, text="Z")

        # === Additional Options Row ===
        main_col.separator(factor=0.5)

        options_row = main_col.row(align=True)
        options_row.prop(mapping, "vector_type", text="")

        if hasattr(layer, 'enable_blur_vector'):
            blur_sub = options_row.row(align=True)
            blur_sub.prop(layer, "enable_blur_vector", text="", icon='MOD_SMOOTH')
            if layer.enable_blur_vector and hasattr(layer, 'blur_vector_factor'):
                blur_sub.prop(layer, "blur_vector_factor", text="Blur")
    else:
        # Fallback to layer properties when no mapping node
        # --- Offset Column ---
        offset_col = grid_row.column(align=True)
        offset_col.scale_x = 1.0
        offset_col.label(text="Offset")
        offset_col.prop(layer, "translation", index=0, text="X")
        offset_col.prop(layer, "translation", index=1, text="Y")
        offset_col.prop(layer, "translation", index=2, text="Z")

        # --- Rotation Column ---
        rot_col = grid_row.column(align=True)
        rot_col.scale_x = 1.0
        rot_col.label(text="Rotation")
        rot_col.prop(layer, "rotation", index=0, text="X")
        rot_col.prop(layer, "rotation", index=1, text="Y")
        rot_col.prop(layer, "rotation", index=2, text="Z")

        # --- Scale Column ---
        scale_col = grid_row.column(align=True)
        scale_col.scale_x = 1.0

        scale_header = scale_col.row(align=True)
        scale_header.label(text="Scale")
        lock_icon = 'LOCKED' if layer.enable_uniform_scale else 'UNLOCKED'
        scale_header.prop(layer, "enable_uniform_scale", text="", icon=lock_icon, emboss=False)

        if layer.enable_uniform_scale:
            draw_input_prop(scale_col, layer, 'uniform_scale_value', text="XYZ")
        else:
            scale_col.prop(layer, "scale", index=0, text="X")
            scale_col.prop(layer, "scale", index=1, text="Y")
            scale_col.prop(layer, "scale", index=2, text="Z")


def _draw_mask_coordinate_section(layout, mask):
    """Draw coordinate type selector for mask.

    Shows:
    - Coordinate/Vector dropdown
    - UV Map selector (when UV)
    - Decal controls (when Decal)
    - Blur controls

    Args:
        layout: UI layout
        mask: YLayerMask instance
    """
    texcoord_type = getattr(mask, 'texcoord_type', 'UV')

    # Main coordinate box
    coord_box = layout.box()
    coord_col = coord_box.column(align=True)

    # === COORDINATE TYPE DROPDOWN ===
    coord_row = coord_col.row(align=True)
    coord_row.scale_y = 1.1
    split = coord_row.split(factor=0.3, align=True)
    split.label(text="Coordinate")
    split.prop(mask, "texcoord_type", text="")

    # === UV-SPECIFIC CONTROLS ===
    if texcoord_type == 'UV':
        coord_col.separator(factor=0.3)
        # Get active object to access UV layers
        obj = bpy.context.active_object
        is_mesh = obj and obj.type == 'MESH' and obj.data

        uv_row = coord_col.row(align=True)
        uv_row.scale_y = 1.1
        split = uv_row.split(factor=0.3, align=True)
        split.label(text="UV Map")

        if is_mesh and hasattr(mask, 'uv_name'):
            split.prop_search(mask, "uv_name", obj.data, "uv_layers", text="", icon='GROUP_UVS')
        elif hasattr(mask, 'uv_name'):
            split.prop(mask, "uv_name", text="")
        else:
            split.label(text="N/A")

    # === DECAL-SPECIFIC CONTROLS ===
    elif texcoord_type == 'Decal':
        coord_col.separator(factor=0.3)
        _draw_mask_decal_controls(coord_col, mask)


def _draw_mask_decal_controls(layout, mask):
    """Draw Decal-specific controls for mask.

    Args:
        layout: UI layout
        mask: YLayerMask instance
    """
    # Get the texcoord node which holds the empty object reference
    mask_tree = get_mask_tree(mask)
    texcoord = mask_tree.nodes.get(mask.texcoord) if mask_tree and hasattr(mask, 'texcoord') else None

    # === Decal Object selector ===
    if texcoord and hasattr(texcoord, 'object'):
        obj_row = layout.row(align=True)
        obj_row.scale_y = 1.1
        split = obj_row.split(factor=0.3, align=True)
        split.label(text="Object")
        split.prop(texcoord, "object", text="")

        layout.separator(factor=0.3)

    # === Decal Distance slider ===
    if hasattr(mask, 'decal_distance_value'):
        dist_row = layout.row(align=True)
        dist_row.scale_y = 1.1
        split = dist_row.split(factor=0.3, align=True)
        split.label(text="Distance")
        draw_input_prop(split, mask, 'decal_distance_value', text="")

        layout.separator(factor=0.3)

    # === Select Decal Object button ===
    btn_row = layout.row(align=True)
    btn_row.scale_y = 1.1
    btn_row.context_pointer_set('entity', mask)
    btn_row.operator("wm.m_select_decal_object", text="Select Decal Object", icon='EMPTY_SINGLE_ARROW')

    layout.separator(factor=0.3)

    # === Set Position to Cursor button ===
    pos_row = layout.row(align=True)
    pos_row.scale_y = 1.1
    pos_row.context_pointer_set('entity', mask)
    pos_row.operator("wm.m_set_decal_object_position_to_cursor", text="Set Position to Cursor", icon='CURSOR')

    # === Stick to Surface toggle ===
    decal_obj = get_decal_object(mask)
    if decal_obj and hasattr(decal_obj, 'mp_decal'):
        layout.separator(factor=0.3)
        shrink_row = layout.row(align=True)
        shrink_row.scale_y = 1.1
        shrink_row.prop(decal_obj.mp_decal, 'enable_shrinkwrap', text="Stick to Surface", icon='MOD_SHRINKWRAP')


def _draw_mask_transform(layout, mask):
    """Draw transform controls for mask using its mapping node.

    Shows coordinate section and offset/rotation/scale in a clean 3-column grid layout.

    Args:
        layout: UI layout to draw into
        mask: YLayerMask with mapping node
    """
    # === COORDINATE SECTION ===
    _draw_mask_coordinate_section(layout, mask)

    # For Decal coordinate type, skip the transform controls
    texcoord_type = getattr(mask, 'texcoord_type', 'UV')
    if texcoord_type == 'Decal':
        return

    layout.separator(factor=0.3)

    mapping = get_mask_mapping_node(mask)
    if not mapping:
        return

    # Main container
    main_box = layout.box()
    main_col = main_box.column(align=True)

    # === OFFSET / ROTATION / SCALE in 3 columns ===
    grid_row = main_col.row(align=True)

    # --- Offset Column ---
    offset_col = grid_row.column(align=True)
    offset_col.label(text="Offset")
    if len(mapping.inputs) > 1:
        offset_input = mapping.inputs[1]
        offset_col.prop(offset_input, "default_value", index=0, text="X")
        offset_col.prop(offset_input, "default_value", index=1, text="Y")
        offset_col.prop(offset_input, "default_value", index=2, text="Z")

    # --- Rotation Column ---
    rot_col = grid_row.column(align=True)
    rot_col.label(text="Rotation")
    if len(mapping.inputs) > 2:
        rotation_input = mapping.inputs[2]
        rot_col.prop(rotation_input, "default_value", index=0, text="X")
        rot_col.prop(rotation_input, "default_value", index=1, text="Y")
        rot_col.prop(rotation_input, "default_value", index=2, text="Z")

    # --- Scale Column ---
    scale_col = grid_row.column(align=True)

    # Scale header with lock toggle
    scale_header = scale_col.row(align=True)
    scale_header.label(text="Scale")
    if hasattr(mask, 'enable_uniform_scale'):
        lock_icon = 'LOCKED' if mask.enable_uniform_scale else 'UNLOCKED'
        scale_header.prop(mask, "enable_uniform_scale", text="", icon=lock_icon, emboss=False)

    if len(mapping.inputs) > 3:
        scale_input = mapping.inputs[3]
        if hasattr(mask, 'enable_uniform_scale') and mask.enable_uniform_scale:
            # Uniform scale
            draw_input_prop(scale_col, mask, 'uniform_scale_value', text="XYZ")
        else:
            # Non-uniform scale
            scale_col.prop(scale_input, "default_value", index=0, text="X")
            scale_col.prop(scale_input, "default_value", index=1, text="Y")
            scale_col.prop(scale_input, "default_value", index=2, text="Z")

    # === Additional Options Row ===
    main_col.separator(factor=0.5)

    options_row = main_col.row(align=True)

    # Vector Type dropdown
    options_row.prop(mapping, "vector_type", text="")

    # Blur Vector toggle for masks
    if hasattr(mask, 'enable_blur_vector'):
        blur_sub = options_row.row(align=True)
        blur_sub.prop(mask, "enable_blur_vector", text="", icon='MOD_SMOOTH')
        if mask.enable_blur_vector and hasattr(mask, 'blur_vector_factor'):
            blur_sub.prop(mask, "blur_vector_factor", text="Blur")


def _draw_coordinate_section(layout, layer):
    """Draw coordinate type selector and type-specific controls.

    Shows:
    - Coordinate dropdown (Generated, Normal, UV, Object, Camera, Window, Reflection, Decal)
    - UV Map selector (when UV)
    - Projection Blend slider (when Generated or Object)
    - Decal controls (when Decal)

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    texcoord_type = getattr(layer, 'texcoord_type', 'UV')

    # Main coordinate box
    coord_box = layout.box()
    coord_col = coord_box.column(align=True)

    # === COORDINATE TYPE DROPDOWN ===
    coord_row = coord_col.row(align=True)
    coord_row.scale_y = 1.1
    split = coord_row.split(factor=0.3, align=True)
    split.label(text="Coordinate")
    split.prop(layer, "texcoord_type", text="")

    # === UV-SPECIFIC CONTROLS ===
    if texcoord_type == 'UV':
        coord_col.separator(factor=0.3)
        _draw_uv_controls(coord_col, layer)

    # === GENERATED/OBJECT-SPECIFIC CONTROLS ===
    elif texcoord_type in {'Generated', 'Object'}:
        coord_col.separator(factor=0.3)
        _draw_projection_blend(coord_col, layer)

    # === DECAL-SPECIFIC CONTROLS ===
    elif texcoord_type == 'Decal':
        coord_col.separator(factor=0.3)
        _draw_decal_controls(coord_col, layer)


def _draw_uv_controls(layout, layer):
    """Draw UV Map selector for UV coordinate type.

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    # Get active object to access UV layers
    obj = bpy.context.active_object
    is_mesh = obj and obj.type == 'MESH' and obj.data

    uv_row = layout.row(align=True)
    uv_row.scale_y = 1.1
    split = uv_row.split(factor=0.3, align=True)
    split.label(text="UV Map")

    if is_mesh and hasattr(layer, 'uv_name'):
        split.prop_search(layer, "uv_name", obj.data, "uv_layers", text="", icon='GROUP_UVS')
    elif hasattr(layer, 'uv_name'):
        split.prop(layer, "uv_name", text="")
    else:
        split.label(text="N/A")


def _draw_projection_blend(layout, layer):
    """Draw projection blend slider for Generated/Object coordinate types.

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    if not hasattr(layer, 'projection_blend'):
        return

    blend_row = layout.row(align=True)
    blend_row.scale_y = 1.1
    split = blend_row.split(factor=0.3, align=True)
    split.label(text="Projection Blend")
    split.prop(layer, "projection_blend", text="", slider=True)


def _draw_decal_controls(layout, layer):
    """Draw Decal-specific controls.

    Shows:
    - Decal Object selector
    - Decal Distance slider
    - Select Decal Object button
    - Set Position to Cursor button
    - Stick to Surface toggle

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    # Get the texcoord node which holds the empty object reference
    layer_tree = get_layer_tree(layer)
    texcoord = layer_tree.nodes.get(layer.texcoord) if layer_tree and hasattr(layer, 'texcoord') else None

    # === Decal Object selector ===
    if texcoord and hasattr(texcoord, 'object'):
        obj_row = layout.row(align=True)
        obj_row.scale_y = 1.1
        split = obj_row.split(factor=0.3, align=True)
        split.label(text="Object")
        split.prop(texcoord, "object", text="")

        layout.separator(factor=0.3)

    # === Decal Distance slider ===
    if hasattr(layer, 'decal_distance_value'):
        dist_row = layout.row(align=True)
        dist_row.scale_y = 1.1
        split = dist_row.split(factor=0.3, align=True)
        split.label(text="Distance")
        draw_input_prop(split, layer, 'decal_distance_value', text="")

        layout.separator(factor=0.3)

    # === Select Decal Object button ===
    btn_row = layout.row(align=True)
    btn_row.scale_y = 1.1
    btn_row.context_pointer_set('entity', layer)
    btn_row.operator("wm.m_select_decal_object", text="Select Decal Object", icon='EMPTY_SINGLE_ARROW')

    layout.separator(factor=0.3)

    # === Set Position to Cursor button ===
    pos_row = layout.row(align=True)
    pos_row.scale_y = 1.1
    pos_row.context_pointer_set('entity', layer)
    pos_row.operator("wm.m_set_decal_object_position_to_cursor", text="Set Position to Cursor", icon='CURSOR')

    # === Stick to Surface toggle ===
    decal_obj = get_decal_object(layer)
    if decal_obj and hasattr(decal_obj, 'mp_decal'):
        layout.separator(factor=0.3)
        shrink_row = layout.row(align=True)
        shrink_row.scale_y = 1.1
        shrink_row.prop(decal_obj.mp_decal, 'enable_shrinkwrap', text="Stick to Surface", icon='MOD_SHRINKWRAP')
