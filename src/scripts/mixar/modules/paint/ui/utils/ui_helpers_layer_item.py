# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Layer item rendering in the layer list."""

from ...core.node.get_nodes import get_layer_source, get_tree
from ...core.subtree.get_subtree import get_upper_neighbor, get_lower_neighbor
from ...core.layer.layer_utils import is_top_member, is_bottom_member
from ...core.layer.get_layers import get_layer_depth


def draw_layer_item(context, layout, layer, index, total_items):
    """Draw individual layer with all controls visible.

    Renders a complete layer item in the UI with:
    - Active indicator (blue highlight)
    - Multi-selection checkbox
    - Visibility toggle (eye icon)
    - Layer type icon (based on backend layer type)
    - Clickable layer name for selection
    - Edit button for layer settings
    - Image status indicators (dirty/packed)
    - Color tag picker
    - Reorder arrows (up/down)
    - Three-dot menu for batch operations

    Args:
        context: Blender context containing active object and window manager.
        layout: Blender UI layout to draw the layer item into.
        layer: MixarLayer UI property representing the layer.
        index (int): Index of this layer in the layer list.
        total_items (int): Total number of layers in the list.
    """
    wm = context.window_manager

    # Check if this layer is active
    is_active = False
    if hasattr(wm, 'mixar_ui'):
        is_active = wm.mixar_ui.active_layer_index == index

    # Get backend layer for proper property access and determine layer type
    backend_layer = None
    layer_type_icon = 'MESH_PLANE'  # Default for FILL
    tree = None
    obj = context.active_object
    if obj and obj.active_material and obj.active_material.use_nodes:
        mat = obj.active_material
        node = None
        for n in mat.node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                node = n
                break

        if node and layer.mixar_layer_idx >= 0:
            tree = node.node_tree
            mp = tree.mp
            if layer.mixar_layer_idx < len(mp.layers):
                backend_layer = mp.layers[layer.mixar_layer_idx]

                # Determine icon based on actual backend layer type
                if backend_layer.type == 'COLOR':
                    layer_type_icon = 'COLOR'  # Fill layer
                elif backend_layer.type == 'IMAGE':
                    layer_type_icon = 'BRUSHES_ALL'  # Paint layer
                elif backend_layer.type == 'GROUP':
                    layer_type_icon = 'GROUP'  # Layer group
                elif backend_layer.type in ('VCOL', 'HEMI', 'AO'):
                    layer_type_icon = 'OUTLINER_DATA_LIGHTPROBE'  # Special layers
                elif backend_layer.type == 'PROCEDURAL':
                    layer_type_icon = 'MATERIAL'  # Procedural/other
                else:
                    layer_type_icon = 'TEXTURE'  # Procedural/other

    # Create main box for rest of content
    layer_box = layout.box()

    # Main row with all elements
    row = layer_box.row(align=True)
    row.scale_y = 1.3

    # Add indentation for nested layers (layers inside groups) using blank icons like Mixar Paint
    if backend_layer and backend_layer.parent_idx != -1:
        depth = get_layer_depth(backend_layer)
        # Add multiple blank icons per depth level for better visual separation
        for i in range(depth):
            row.label(text='', icon='BLANK1')
            row.label(text='', icon='BLANK1')

    # Blue active indicator - add blue selection indicator on left edge if active
    if is_active:
        active_indicator = row.row(align=True)
        active_indicator.scale_x = 0.2
        active_indicator.enabled = True
        # Use an operator button in "pressed" state for blue color
        active_indicator.operator("layers.select_layer", text="", emboss=True, depress=True).index = index
        row.separator(factor=0.3)

    check_box = row.row(align=True)
    check_box.scale_x = 1.1
    check_box.prop(layer, "selected", text="", toggle=True, icon='CHECKBOX_HLT' if layer.selected else 'CHECKBOX_DEHLT', emboss=False)

    row.separator(factor=1.0)
    # === LEFT SIDE CONTROLS (icons with MORE spacing) ===
    # 2. Visibility toggle (eye icon)
    vis_col = row.row(align=True)
    vis_col.scale_x = 1.0
    if backend_layer:
        icon_vis = 'HIDE_OFF' if backend_layer.enable else 'HIDE_ON'
        vis_col.prop(backend_layer, "enable", text="", icon=icon_vis, emboss=False)
    else:
        icon_vis = 'HIDE_OFF' if layer.visible else 'HIDE_ON'
        vis_col.prop(layer, "visible", text="", icon=icon_vis, emboss=False)

    row.separator(factor=1.0)

    # 3. Layer type icon - SINGLE ICON based on actual type
    type_col = row.row(align=True)
    type_col.scale_x = 1.0
    type_col.label(text="", icon=layer_type_icon)

    row.separator(factor=1.0)

    # === MIDDLE SECTION (layer name - takes remaining space) ===
    label_text = layer.name
    image = None

    if backend_layer:
        if backend_layer.type == 'IMAGE':
            src = get_layer_source(backend_layer, tree)
            if src and hasattr(src, 'image') and src.image:
                image = src.image

    # Clickable name for selection (takes all remaining space)
    name_btn = row.operator("layers.select_layer", text=label_text, emboss=False)
    name_btn.index = index

    # === RIGHT SIDE CONTROLS (fixed width) ===
    row.separator(factor=0.8)

    # Image indicators (dirty/packed)
    if image:
        if image.is_dirty:
            row.separator(factor=0.5)
            dirty_col = row.row(align=True)
            dirty_col.scale_x = 0.8
            dirty_col.label(text="", icon='RADIOBUT_ON')
        if image.packed_file:
            row.separator(factor=0.5)
            pack_col = row.row(align=True)
            pack_col.scale_x = 0.8
            pack_col.label(text="", icon='PACKAGE')

    row.separator(factor=0.8)

    # 5. Color tag - clickable color swatch (built-in color picker on click)
    color_col = row.row(align=True)

    # 6. Reorder arrows (up/down) - compact column
    arrows_col = row.column(align=True)
    arrows_col.scale_x = 1.0
    arrows_col.scale_y = 0.5

    # Up button
    row_up = arrows_col.row(align=True)
    use_group_menu_up = False
    if backend_layer:
        # Check if layer is top member of a group (needs to move out)
        if is_top_member(backend_layer):
            row_up.menu("LAYERS_MT_move_in_out_group", text="", icon='TRIA_UP')
            use_group_menu_up = True
        else:
            # Check if upper neighbor is a group or has different parent
            upper_idx, upper_layer = get_upper_neighbor(backend_layer)
            if upper_layer and (upper_layer.type == 'GROUP' or upper_layer.parent_idx != backend_layer.parent_idx):
                row_up.menu("LAYERS_MT_move_in_out_group", text="", icon='TRIA_UP')
                use_group_menu_up = True

    if not use_group_menu_up:
        # Regular move
        op_up = row_up.operator("wm.m_move_layer", text="", icon='TRIA_UP', emboss=False)
        op_up.direction = 'UP'
        op_up.layer_idx = layer.mixar_layer_idx

    row_up.enabled = index > 0

    # Down button
    row_down = arrows_col.row(align=True)
    use_group_menu_down = False
    if backend_layer:
        # Check if layer is bottom member of a group (needs to move out)
        if is_bottom_member(backend_layer):
            row_down.menu("LAYERS_MT_move_in_out_group", text="", icon='TRIA_DOWN')
            use_group_menu_down = True
        else:
            # Check if lower neighbor is a group with same parent
            lower_idx, lower_layer = get_lower_neighbor(backend_layer)
            if lower_layer and (lower_layer.type == 'GROUP' and lower_layer.parent_idx == backend_layer.parent_idx):
                row_down.menu("LAYERS_MT_move_in_out_group", text="", icon='TRIA_DOWN')
                use_group_menu_down = True

    if not use_group_menu_down:
        # Regular move
        op_down = row_down.operator("wm.m_move_layer", text="", icon='TRIA_DOWN', emboss=False)
        op_down.direction = 'DOWN'
        op_down.layer_idx = layer.mixar_layer_idx

    row_down.enabled = index < total_items - 1

    row.separator(factor=0.8)

    # 7. Three-dot menu for batch operations on selected layers
    menu_col = row.row(align=True)
    menu_col.scale_x = 0.8
    menu_col.operator("layers.selected_layers_menu", text="", icon='THREE_DOTS', emboss=False).layer_index = index
