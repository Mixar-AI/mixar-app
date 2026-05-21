# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Layer settings panel.

Implements Substance Painter-style layout:
- Fill layers: FILL + MATERIAL sections (flat, no masks)
- Paint layers: BRUSH SETTINGS + CHANNELS + MASKS sections
"""

import bpy

from ...core.layer.layer_utils import get_layer_index
from ...core.node.get_nodes import get_layer_source
from ...core.subtree.get_subtree import get_tree
from .ui_helpers_mask import draw_mask_settings
from .ui_helpers_layer_fill import draw_fill_section
from .ui_helpers_layer_material import draw_material_section
from .ui_helpers_layer_source import draw_node_group_inputs


def _get_draw_channel_settings():
    """Lazy import to avoid circular dependency with ui_helpers."""
    from .ui_helpers import draw_channel_settings
    return draw_channel_settings


def _get_draw_brush_settings():
    """Lazy import to avoid circular dependency with ui_helpers."""
    from .ui_helpers import draw_brush_settings
    return draw_brush_settings


def draw_layer_settings(context, layout, layer):
    """Draw comprehensive settings for the active layer.

    Implements Substance Painter-style layout:
    - Fill layers (type='COLOR'): FILL + MATERIAL (flat, no masks)
    - Group layers (type='GROUP'): BLENDING + CHANNELS + MASKS
    - Paint layers (type='IMAGE'): BRUSH SETTINGS + CHANNELS + MASKS

    Args:
        context: Blender context (used to access global UI state)
        layout: UI layout to draw into
        layer: Backend YLayer with channels and masks
    """
    main_col = layout.column(align=True)
    main_col.use_property_split = False

    # Get mp (root) to access channel names
    mp = layer.id_data.mp

    # Get global UI state
    wm = context.window_manager
    ui_state = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

    # Route based on layer type
    if layer.type == 'COLOR':
        # ========== FILL LAYER: FLAT LAYOUT ==========
        _draw_fill_layer_settings(context, main_col, layer, mp)
    elif layer.type == 'GROUP':
        # ========== GROUP LAYER: BLENDING + CHANNELS + MASKS ==========
        _draw_group_layer_settings(context, main_col, layer, mp, ui_state)
    elif layer.type == 'PROCEDURAL':
        # ========== PROCEDURAL LAYER: MATERIAL + PARAMS + CHANNELS ==========
        _draw_procedural_layer_settings(context, main_col, layer, mp, ui_state)
    else:
        # ========== PAINT LAYER: ORIGINAL LAYOUT ==========
        _draw_paint_layer_settings(context, main_col, layer, mp)

        main_col.separator(factor=1)

        # ========== MASKS SECTION (PAINT LAYERS ONLY) ==========
        _draw_masks_section(context, main_col, layer, ui_state)


def _draw_fill_layer_settings(context, layout, layer, mp):
    """Draw settings for Fill layers (Substance Painter style).

    Shows: FILL section + MATERIAL section

    Args:
        context: Blender context
        layout: UI layout (column)
        layer: Backend YLayer
        mp: Root MPaint property group
    """
    # ========== FILL SECTION ==========
    # Contains projection, transforms, filtering, blending
    draw_fill_section(context, layout, layer)

    layout.separator(factor=1)

    # ========== MATERIAL SECTION ==========
    # Contains source type, source controls, channel list
    draw_material_section(context, layout, layer, mp)


def _draw_group_layer_settings(context, layout, layer, mp, ui_state):
    """Draw settings for Group layers (same style as Fill layers).

    Shows just the channel list like Fill layers - no dropdown sections.

    Args:
        context: Blender context
        layout: UI layout (column)
        layer: Backend YLayer (GROUP type)
        mp: Root MPaint property group
        ui_state: MixarUIState or None
    """
    # ========== CHANNEL LIST (same as Fill layer) ==========
    _draw_group_channel_list(context, layout, layer, mp)


def _draw_procedural_layer_settings(context, layout, layer, mp, ui_state=None):
    """Draw settings for Procedural layers.

    Shows: Material info → Parameters (collapsible) → Channels with blend/opacity

    Args:
        context: Blender context
        layout: UI layout (column)
        layer: Backend YLayer (PROCEDURAL type)
        mp: Root MPaint property group
        ui_state: MixarUIState or None
    """
    # ========== MATERIAL INFO HEADER ==========
    material_name = ''
    material_id = getattr(layer, 'procedural_material_id', '')

    if material_id:
        try:
            from ...procedural_materials import material_registry
            material = material_registry.get_material(material_id)
            if material:
                material_name = material.name
            else:
                material_name = material_id
        except Exception:
            material_name = material_id

    if not material_name:
        # Fallback: try to get name from source node group
        tree = get_tree(layer)
        source = get_layer_source(layer, tree)
        if source and hasattr(source, 'node_tree') and source.node_tree:
            material_name = source.node_tree.name

    if material_name:
        mat_header = layout.box()
        mat_row = mat_header.row(align=True)
        mat_row.scale_y = 1.5
        mat_row.label(text=material_name, icon='MATERIAL')

        # Change material button
        mat_row.operator(
            "layers.procedural_material_library_popup", text="", icon='FILE_REFRESH'
        )

        layout.separator(factor=0.5)

    # ========== PARAMETERS SECTION (collapsible) ==========
    tree = get_tree(layer)
    source = get_layer_source(layer, tree)

    if source and source.bl_idname == 'ShaderNodeGroup' and source.node_tree:
        # Check if there are any displayable inputs
        _hidden_vectors = {'Vector', 'UV', 'Normal', 'Tangent'}
        has_inputs = any(
            inp.type in ('VALUE', 'INT', 'BOOLEAN', 'RGBA', 'VECTOR', 'STRING')
            for inp in source.inputs
            if not (inp.type == 'VECTOR' and inp.name in _hidden_vectors)
        )

        if has_inputs:
            param_header_box = layout.box()
            param_header_row = param_header_box.row(align=True)
            param_header_row.scale_y = 1.3

            expand_params = ui_state.expand_procedural_params if ui_state else True
            icon = 'DOWNARROW_HLT' if expand_params else 'RIGHTARROW'
            if ui_state:
                param_header_row.prop(
                    ui_state, "expand_procedural_params",
                    text="", icon=icon, emboss=False
                )
            param_header_row.label(text="Parameters", icon='PREFERENCES')

            if expand_params:
                layout.separator(factor=0.3)
                draw_node_group_inputs(layout, source, False, use_box=True)

            layout.separator(factor=1)

    # ========== CHANNELS SECTION ==========
    _draw_procedural_channel_list(context, layout, layer, mp)

    # ========== MASKS SECTION ==========
    layout.separator(factor=1)
    _draw_masks_section(context, layout, layer, ui_state)


def _draw_procedural_channel_list(context, layout, layer, mp):
    """Draw channel list for Procedural layers.

    Shows each channel with enable toggle, blend mode, and opacity.

    Args:
        context: Blender context
        layout: UI layout
        layer: Backend YLayer (PROCEDURAL type)
        mp: Root MPaint property group
    """
    ch_header = layout.row(align=True)
    ch_header.scale_y = 1.2
    ch_header.label(text="Channels", icon='NODE_TEXTURE')

    layout.separator(factor=0.3)

    for i, channel in enumerate(layer.channels):
        if i >= len(mp.channels):
            continue
        root_ch = mp.channels[i]
        _draw_group_channel_row(layout, channel, root_ch, layer)


def _draw_group_channel_list(context, layout, layer, mp):
    """Draw channel list for Group layers (same style as Fill layers).

    Args:
        context: Blender context
        layout: UI layout
        layer: Backend YLayer (GROUP type)
        mp: Root MPaint property group
    """
    # Channel header row (same as Fill layer)
    ch_header = layout.row(align=True)
    ch_header.scale_y = 1.2
    ch_header.label(text="Channels", icon='NODE_TEXTURE')
    ch_header.menu("CHANNELS_MT_add_channel_menu", text="", icon='ADD')

    layout.separator(factor=0.3)

    # Draw each channel row
    for i, channel in enumerate(layer.channels):
        if i >= len(mp.channels):
            continue

        root_ch = mp.channels[i]
        _draw_group_channel_row(layout, channel, root_ch, layer)


def _draw_group_channel_row(layout, channel, root_ch, layer):
    """Draw a single channel row for Group layer (similar to Fill layer style).

    Args:
        layout: UI layout
        channel: YLayerChannel
        root_ch: MPaintChannel (root channel)
        layer: Backend YLayer (GROUP type)
    """
    is_normal = root_ch.type == "NORMAL"

    box = layout.box()
    box.scale_y = 1.2

    # Header row
    header = box.row(align=True)
    header.scale_y = 1.3

    # Enable toggle
    header.prop(channel, "enable", text="")

    # Channel name
    split = header.split(factor=0.25, align=True)
    name_col = split.row(align=True)
    name_col.enabled = channel.enable
    name_col.label(text=root_ch.name)

    # Controls area - blend mode dropdown
    ctrl_row = split.row(align=True)
    ctrl_row.enabled = channel.enable

    # Blend mode for this channel
    if is_normal:
        ctrl_row.prop(channel, "normal_blend_type", text="")
        # Write Height toggle inline for Normal channel
        ctrl_row.prop(channel, 'write_height', text="", icon='IPO_ELASTIC', toggle=True)
    else:
        ctrl_row.prop(channel, "blend_type", text="")

    # Opacity slider
    opacity_row = ctrl_row.row(align=True)
    opacity_row.prop(channel, "intensity_value", text="", slider=True)

    layout.separator(factor=0.2)


def _draw_paint_layer_settings(context, layout, layer, mp):
    """Draw settings for Paint layers (original layout).

    Shows: BRUSH SETTINGS + CHANNELS sections

    Args:
        context: Blender context
        layout: UI layout (column)
        layer: Backend YLayer
        mp: Root MPaint property group
    """
    wm = context.window_manager
    ui_state = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

    # ========== BRUSH SETTINGS SECTION ==========
    _get_draw_brush_settings()(context, layout, layer)

    # ========== BLENDING SECTION ==========
    blending_header_box = layout.box()
    blending_header_row = blending_header_box.row(align=True)
    blending_header_row.scale_y = 1.3

    expand_blending = ui_state.expand_blending if ui_state else True
    icon = 'DOWNARROW_HLT' if expand_blending else 'RIGHTARROW'
    if ui_state:
        blending_header_row.prop(
            ui_state, "expand_blending", text="", icon=icon, emboss=False
        )
    blending_header_row.label(text="Blending", icon='NODE_COMPOSITING')

    if expand_blending:
        layout.separator(factor=0.5)

        # Master Opacity slider
        opacity_box = layout.box().row(align=True)
        opacity_box.scale_y = 1.3
        opacity_split = opacity_box.split(factor=0.3, align=True)
        opacity_split.label(text="Opacity")
        opacity_split.prop(layer, "intensity_value", text="", slider=True)

        layout.separator(factor=0.3)

        # Linked Blend Mode row
        blend_box = layout.box().row(align=True)
        blend_box.scale_y = 1.3
        blend_split = blend_box.split(factor=0.3, align=True)
        blend_split.label(text="Blend")

        blend_row = blend_split.row(align=True)
        link_icon = 'LINKED' if layer.blend_linked else 'UNLINKED'
        blend_row.prop(layer, "blend_linked", text="", icon=link_icon, toggle=True)
        blend_row.prop(layer, "linked_blend_type", text="")

    layout.separator(factor=1)

    # ========== CHANNELS SECTION ==========
    channels_title_box = layout.box()
    channels_title_row = channels_title_box.row(align=True)
    channels_title_row.scale_y = 1.3

    expand_channels = ui_state.expand_channels if ui_state else True
    icon = 'DOWNARROW_HLT' if expand_channels else 'RIGHTARROW'
    if ui_state:
        channels_title_row.prop(
            ui_state, "expand_channels", text="", icon=icon, emboss=False
        )
    channels_title_row.label(text="Channels", icon='NODE_TEXTURE')

    if expand_channels:
        layout.separator(factor=0.5)

        # Channel toggles
        ch_toggle_container = layout.row(align=True)
        ch_toggle_box = ch_toggle_container.box()

        channel_abbrev = {
            "Color": "Color", "Metallic": "Metallic", "Roughness": "Roughness",
            "Normal": "Normal", "Height": "Height", "Transmission": "Transmission",
            "Emission": "Emission", "Alpha": "Alpha", "Displacement": "Displacement",
        }

        buttons_per_row = 5
        num_channels = len(layer.channels)

        for i, channel in enumerate(layer.channels):
            if i >= len(mp.channels):
                continue

            root_ch = mp.channels[i]

            if i % buttons_per_row == 0:
                ch_row = ch_toggle_box.row(align=True)
                ch_row.alignment = 'LEFT'
                ch_row.scale_y = 1.3

            abbrev = channel_abbrev.get(root_ch.name, root_ch.name)
            ch_row.prop(channel, "enable", text=abbrev, toggle=True)

        if num_channels > 0:
            remaining_slots = buttons_per_row - (num_channels % buttons_per_row)
            if remaining_slots < buttons_per_row:
                for _ in range(remaining_slots):
                    ch_row.label(text="")

        add_ch_col = ch_toggle_container.row(align=True)
        add_ch_col.alignment = 'RIGHT'
        add_ch_col.scale_x = 2.0
        add_ch_col.scale_y = 2.0
        add_ch_col.menu("CHANNELS_MT_add_channel_menu", text="", icon='ADD')

        layout.separator(factor=1)

        # Channel settings for enabled channels
        for i, channel in enumerate(layer.channels):
            if channel.enable and i < len(mp.channels):
                root_ch = mp.channels[i]
                _get_draw_channel_settings()(context, layout, channel, root_ch, layer)


def _draw_masks_section(context, layout, layer, ui_state):
    """Draw the MASKS section (shared by Fill and Paint layers).

    Args:
        context: Blender context
        layout: UI layout (column)
        layer: Backend YLayer
        ui_state: MixarUIState or None
    """
    masks_header_box = layout.box()
    mask_header = masks_header_box.row(align=True)
    mask_header.scale_y = 1.3

    expand_masks = ui_state.expand_masks if ui_state else False
    icon = 'DOWNARROW_HLT' if expand_masks else 'RIGHTARROW'
    if ui_state:
        mask_header.prop(ui_state, "expand_masks", text="", icon=icon, emboss=False)

    mask_header.label(text="Masks", icon='MOD_MASK')
    mask_header.menu("MASKS_MT_add_mask_menu", text="", icon='ADD')

    if expand_masks:
        layout.separator(factor=0.5)

        if len(layer.masks) > 0:
            wm = context.window_manager
            editing_mask_idx = -1
            if hasattr(wm, 'mixar_ui'):
                editing_mask_idx = wm.mixar_ui.editing_mask_index

            if 0 <= editing_mask_idx < len(layer.masks):
                mask = layer.masks[editing_mask_idx]

                back_row = layout.row()
                back_row.scale_y = 1.3
                back_row.operator(
                    "layers.deselect_mask", text="Back to Layer", icon='BACK'
                )
                layout.separator()

                draw_mask_settings(layout, mask, editing_mask_idx, layer)
            else:
                for i, mask in enumerate(layer.masks):
                    _draw_mask_header_row(layout, mask, i, layer)
        else:
            empty_box = layout.box()
            empty_row = empty_box.row()
            empty_row.alignment = 'CENTER'
            empty_row.label(text="No masks", icon='INFO')


def _draw_mask_header_row(layout, mask, mask_idx, layer):
    """Draw a clickable mask row that selects the mask for editing.

    Same style as layer rows - flat appearance, highlighted only when selected.

    Args:
        layout: UI layout
        mask: YMask instance
        mask_idx: Index of mask in layer.masks
        layer: Parent YLayer
    """
    # Check if this mask is selected
    wm = bpy.context.window_manager
    is_selected = False
    if hasattr(wm, 'mixar_ui'):
        is_selected = (wm.mixar_ui.editing_mask_index == mask_idx)

    # Use box only when selected (same as layer rows)
    if is_selected:
        container = layout.box()
        row = container.row(align=True)
    else:
        row = layout.row(align=True)

    row.scale_y = 1.4  # Same height as layer rows

    # Indentation for nested appearance
    row.label(text="", icon='BLANK1')

    # Placeholder for expand button (masks don't have sub-items)
    row.label(text="", icon='BLANK1')

    # Visibility toggle (eye icon)
    vis_icon = 'HIDE_OFF' if mask.enable else 'HIDE_ON'
    row.prop(mask, "enable", text="", icon=vis_icon, emboss=False)

    # Mask icon based on type
    mask_icons = {
        'IMAGE': 'IMAGE_DATA',
        'VCOL': 'VPAINT_HLT',
        'NOISE': 'TEXTURE',
        'VORONOI': 'TEXTURE',
        'BRICK': 'TEXTURE',
        'CHECKER': 'TEXTURE',
        'GRADIENT': 'TEXTURE',
        'MAGIC': 'TEXTURE',
        'WAVE': 'TEXTURE',
        'GABOR': 'TEXTURE',
        'HEMI': 'LIGHT_SUN',
        'COLOR_ID': 'COLOR',
        'OBJECT_INDEX': 'OBJECT_DATA',
        'BACKFACE': 'FACESEL',
        'AO': 'SHADING_RENDERED',
        'EDGE_DETECT': 'EDGESEL',
    }
    icon = mask_icons.get(mask.type, 'MOD_MASK')
    row.label(text="", icon=icon)

    # Clickable mask name (emboss=False like layers)
    layer_idx = get_layer_index(layer)
    if layer_idx is None:
        layer_idx = -1
    op = row.operator("layers.select_mask", text=mask.name, emboss=False)
    op.layer_index = layer_idx
    op.mask_index = mask_idx

    # Blend mode (same width as layers)
    blend_row = row.row(align=True)
    blend_row.ui_units_x = 3.5
    blend_row.prop(mask, "blend_type", text="")

    # Opacity (same width as layers)
    int_row = row.row(align=True)
    int_row.ui_units_x = 2.5
    int_row.prop(mask, "intensity_value", text="", slider=False)
