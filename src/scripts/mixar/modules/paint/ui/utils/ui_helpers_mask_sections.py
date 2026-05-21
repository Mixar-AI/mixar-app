# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Section drawing helper functions for mask UI.

Organized into logical sections with consistent styling:
- Basic Settings: Source, Blend, Intensity, Source Input
- Channel Toggles: Collapsible channel enable/disable
- Source Properties: Dynamic node properties
- Type-Specific: HEMI, COLOR_ID, OBJECT_INDEX, EDGE_DETECT, AO settings
- Mapping: Vector, UV, Blur, Decal controls
- Modifiers: Modifier stack with add/remove
"""

from ...core.node.get_nodes import get_mask_source
from ...core.subtree.get_subtree import get_mask_tree
from ..operators.decal_operators import get_decal_object
from .ui_helpers_base import draw_input_prop
from .ui_helpers_mask_utils import get_node_drawing_functions

# Consistent UI constants
LABEL_FACTOR = 0.35
HEADER_SCALE = 1.2
CONTENT_SCALE = 1.1


def _get_mask_source_label(mask):
    """Get the display label for the mask source dropdown.

    Args:
        mask: MLayerMask instance

    Returns:
        str: Label to display for the source (e.g., image name, vcol name, or type label)
    """
    from ...utils.constants import mask_type_labels

    try:
        source = get_mask_source(mask)

        if mask.type == 'IMAGE':
            if source and source.image:
                return source.image.name
            return 'Image'
        elif mask.type == 'VCOL':
            if source and hasattr(source, 'attribute_name') and source.attribute_name != '':
                return source.attribute_name
            return 'Vertex Color'
        elif mask.type == 'MODIFIER':
            if mask.modifier_type == 'INVERT':
                return 'Invert'
            elif mask.modifier_type == 'RAMP':
                return 'Ramp'
            elif mask.modifier_type == 'CURVE':
                return 'Curve'
            return 'Modifier'
        else:
            return mask_type_labels.get(mask.type, mask.type)
    except Exception:
        return mask.type if mask else 'Unknown'


# =============================================================================
# MASK HEADER
# =============================================================================

def draw_mask_header(layout, mask, layer):
    """Draw mask header with name, enable toggle, and remove button.

    Args:
        layout: UI layout (column)
        mask: YMask instance
        layer: YLayer instance
    """
    header_box = layout.box()
    row = header_box.row(align=True)
    row.scale_y = HEADER_SCALE

    # Left: mask name and icon
    left_row = row.row(align=True)
    left_row.label(text=mask.name, icon='MOD_MASK')

    # Spacer
    row.separator()

    # Right: enable toggle + remove button
    row.prop(mask, "enable", text="", toggle=True, icon='HIDE_OFF' if mask.enable else 'HIDE_ON')

    row.context_pointer_set('layer', layer)
    row.context_pointer_set('mask', mask)
    row.operator("wm.m_remove_layer_mask", text="", icon='X', emboss=False)


# =============================================================================
# CHANNEL TOGGLES INLINE (no dropdown)
# =============================================================================

def draw_mask_channel_toggles_inline(layout, mask, layer):
    """Draw channel toggles inline without dropdown header.

    Args:
        layout: UI layout (column) - content is drawn directly here
        mask: YMask instance
        layer: YLayer instance
    """
    if len(mask.channels) == 0:
        return

    mp = layer.id_data.mp
    channels_per_row = 5

    for i in range(0, len(mask.channels), channels_per_row):
        row = layout.row(align=True)
        row.scale_y = CONTENT_SCALE

        for j in range(channels_per_row):
            idx = i + j
            if idx >= len(mask.channels):
                break

            mask_ch = mask.channels[idx]
            root_ch = mp.channels[idx] if idx < len(mp.channels) else None

            if root_ch:
                ch_name = root_ch.name if hasattr(root_ch, 'name') else f"Ch{idx}"
                row.prop(mask_ch, "enable", text=ch_name, toggle=True)


# =============================================================================
# CORE SETTINGS CONTENT
# =============================================================================

def draw_mask_core_settings_content(layout, mask, layer=None):
    """Draw core mask settings: Source, Blend+Intensity row, Source Input.

    Layout:
    - Source dropdown
    - Separator
    - Blend and Intensity in one row
    - Separator
    - Source Input (conditional)

    Args:
        layout: UI layout (column) - content is drawn directly here
        mask: MLayerMask instance
        layer: MLayer instance (optional, for context)
    """
    content = layout.column(align=True)
    content.scale_y = CONTENT_SCALE

    # add a separator
    content.separator(factor=1.5)

    # Source row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Source")
    menu_row = split.row(align=True)
    menu_row.context_pointer_set('mask', mask)
    if layer:
        menu_row.context_pointer_set('layer', layer)
    source_label = _get_mask_source_label(mask)
    menu_row.menu("MASKS_MT_mask_source_menu", text=source_label)

    # Separator
    content.separator(factor=1.0)

    # Blend and Intensity in one row
    row = content.row(align=True)

    # Blend half
    blend_split = row.split(factor=0.5, align=True)
    blend_row = blend_split.row(align=True)
    blend_row.label(text="Blend")
    blend_row.prop(mask, "blend_type", text="")

    # Intensity half
    intensity_row = blend_split.row(align=True)
    intensity_row.label(text="Intensity")
    intensity_row.prop(mask, "intensity_value", text="", slider=True)

    # Source Input row (conditional - only for IMAGE and VCOL masks)
    if mask.type in {'IMAGE', 'VCOL'}:
        content.separator(factor=1.0)
        row = content.row(align=True)
        split = row.split(factor=LABEL_FACTOR, align=True)
        split.label(text="Source Input")
        split.prop(mask, "source_input", text="")


# =============================================================================
# SOURCE PROPERTIES BOX (always expanded, no dropdown)
# =============================================================================

def draw_mask_source_props_box(layout, mask):
    """Draw source properties in its own box (always expanded, no dropdown).

    Args:
        layout: UI layout (column)
        mask: YMask instance
    """
    # Mask types that can be baked to image (procedural/geometry-based)
    BAKEABLE_MASK_TYPES = {
        'AO', 'EDGE_DETECT', 'HEMI', 'BACKFACE', 'OBJECT_INDEX', 'COLOR_ID',
        'NOISE', 'BRICK', 'CHECKER', 'GRADIENT', 'MAGIC', 'GABOR', 'VORONOI', 'WAVE'
    }

    source_node = get_mask_source(mask)

    # Only show box if there's content to display
    if not source_node and mask.type not in BAKEABLE_MASK_TYPES:
        return

    section_box = layout.box()
    content = section_box.column(align=True)
    content.scale_y = CONTENT_SCALE

    # Header label
    header = content.row(align=True)
    header.scale_y = HEADER_SCALE
    header.label(text="Source Properties", icon='NODE_MATERIAL')

    content.separator(factor=0.3)

    if source_node:
        draw_node_props_dynamic, draw_node_group_inputs = get_node_drawing_functions()
        # Pass use_box=False to avoid nested boxes inside our section box
        if source_node.bl_idname == 'ShaderNodeGroup':
            draw_node_group_inputs(content, source_node, any_override=False, use_box=False)
        else:
            draw_node_props_dynamic(content, source_node, any_override=False, use_box=False)
    else:
        content.label(text="No source node", icon='INFO')

    # Add bake controls for bakeable mask types
    if mask.type in BAKEABLE_MASK_TYPES:
        content.separator(factor=0.5)

        # Check if mask has been baked (use_baked has update callback that triggers UI refresh)
        has_baked = mask.baked_source != "" or mask.use_baked

        if has_baked:
            # Show baked image name
            from ...core.subtree.get_subtree import get_mask_tree
            mask_tree = get_mask_tree(mask)
            baked_node = mask_tree.nodes.get(mask.baked_source) if mask_tree else None

            if baked_node and baked_node.image:
                img_row = content.row(align=True)
                split = img_row.split(factor=LABEL_FACTOR, align=True)
                split.label(text="Baked Image")
                split.label(text=baked_node.image.name, icon='IMAGE_DATA')

            content.separator(factor=0.3)

            # Bake control buttons row
            bake_row = content.row(align=True)
            bake_row.scale_y = 1.2
            bake_row.context_pointer_set('entity', mask)

            # Rebake button
            bake_row.operator("wm.m_bake_entity_to_image", text="Rebake", icon='FILE_REFRESH')

            # Use Baked toggle
            bake_row.prop(mask, "use_baked", text="Use Baked", toggle=True, icon='CHECKMARK' if mask.use_baked else 'CHECKBOX_DEHLT')

            # Remove baked button
            bake_row.operator("wm.m_remove_baked_entity", text="", icon='X')
        else:
            # Not baked - show Bake as Image button
            bake_row = content.row(align=True)
            bake_row.scale_y = 1.2
            bake_row.context_pointer_set('entity', mask)
            bake_row.operator("wm.m_bake_entity_to_image", text="Bake as Image", icon='RENDER_RESULT')


# =============================================================================
# BASIC SETTINGS SECTION (legacy - kept for compatibility)
# =============================================================================

def draw_mask_basic_props_content(layout, mask, layer=None):
    """Draw basic mask properties content without wrapping box.

    Contains: Source, Blend, Intensity, Source Input (conditional)

    Args:
        layout: UI layout (column) - content is drawn directly here
        mask: MLayerMask instance
        layer: MLayer instance (optional, for context)
    """
    content = layout.column(align=True)
    content.scale_y = CONTENT_SCALE

    # Source row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Source")
    menu_row = split.row(align=True)
    menu_row.context_pointer_set('mask', mask)
    if layer:
        menu_row.context_pointer_set('layer', layer)
    source_label = _get_mask_source_label(mask)
    menu_row.menu("MASKS_MT_mask_source_menu", text=source_label)

    # Blend row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Blend")
    split.prop(mask, "blend_type", text="")

    # Intensity row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Intensity")
    split.prop(mask, "intensity_value", text="", slider=True)

    # Source Input row (conditional - only for IMAGE and VCOL masks)
    if mask.type in {'IMAGE', 'VCOL'}:
        row = content.row(align=True)
        split = row.split(factor=LABEL_FACTOR, align=True)
        split.label(text="Source Input")
        split.prop(mask, "source_input", text="")


# =============================================================================
# CHANNEL TOGGLES SECTION
# =============================================================================

def draw_mask_channel_toggles_content(layout, mask, layer):
    """Draw channel toggles section content (collapsible, no wrapping box).

    Args:
        layout: UI layout (column) - content is drawn directly here
        mask: YMask instance
        layer: YLayer instance
    """
    if len(mask.channels) == 0:
        return

    # Header with expand arrow (inline, no box)
    header = layout.row(align=True)
    header.scale_y = HEADER_SCALE
    icon = 'DOWNARROW_HLT' if mask.expand_channels else 'RIGHTARROW'
    header.prop(mask, "expand_channels", text="", icon=icon, emboss=False)
    header.label(text="Affects Channels", icon='NODE_TEXTURE')

    # Content
    if mask.expand_channels:
        content = layout.column(align=True)
        content.separator(factor=0.3)

        mp = layer.id_data.mp
        channels_per_row = 5

        for i in range(0, len(mask.channels), channels_per_row):
            row = content.row(align=True)
            row.scale_y = CONTENT_SCALE

            for j in range(channels_per_row):
                idx = i + j
                if idx >= len(mask.channels):
                    break

                mask_ch = mask.channels[idx]
                root_ch = mp.channels[idx] if idx < len(mp.channels) else None

                if root_ch:
                    ch_name = root_ch.name if hasattr(root_ch, 'name') else f"Ch{idx}"
                    row.prop(mask_ch, "enable", text=ch_name, toggle=True)


# =============================================================================
# SOURCE PROPERTIES SECTION
# =============================================================================

def draw_mask_source_props_content(layout, mask):
    """Draw source properties section content (collapsible, no wrapping box).

    Args:
        layout: UI layout (column) - content is drawn directly here
        mask: YMask instance
    """
    # Mask types that can be baked to image (procedural/geometry-based)
    BAKEABLE_MASK_TYPES = {
        'AO', 'EDGE_DETECT', 'HEMI', 'BACKFACE', 'OBJECT_INDEX', 'COLOR_ID',
        'NOISE', 'BRICK', 'CHECKER', 'GRADIENT', 'MAGIC', 'GABOR', 'VORONOI', 'WAVE'
    }

    # Header with expand arrow (inline, no box)
    header = layout.row(align=True)
    header.scale_y = HEADER_SCALE
    icon = 'DOWNARROW_HLT' if mask.expand_source else 'RIGHTARROW'
    header.prop(mask, "expand_source", text="", icon=icon, emboss=False)
    header.label(text="Source Properties", icon='NODE_MATERIAL')

    # Content
    if mask.expand_source:
        content = layout.column(align=True)
        content.scale_y = CONTENT_SCALE
        content.separator(factor=0.3)

        source_node = get_mask_source(mask)

        if source_node:
            draw_node_props_dynamic, draw_node_group_inputs = get_node_drawing_functions()
            # Pass use_box=False to avoid nested boxes inside our section box
            if source_node.bl_idname == 'ShaderNodeGroup':
                draw_node_group_inputs(content, source_node, any_override=False, use_box=False)
            else:
                draw_node_props_dynamic(content, source_node, any_override=False, use_box=False)
        else:
            content.label(text="No source node", icon='INFO')

        # Add bake controls for bakeable mask types
        if mask.type in BAKEABLE_MASK_TYPES:
            content.separator(factor=0.5)

            # Check if mask has been baked (use_baked has update callback that triggers UI refresh)
            has_baked = mask.baked_source != "" or mask.use_baked

            if has_baked:
                # Show baked image name
                from ...core.subtree.get_subtree import get_mask_tree
                mask_tree = get_mask_tree(mask)
                baked_node = mask_tree.nodes.get(mask.baked_source) if mask_tree else None

                if baked_node and baked_node.image:
                    img_row = content.row(align=True)
                    split = img_row.split(factor=LABEL_FACTOR, align=True)
                    split.label(text="Baked Image")
                    split.label(text=baked_node.image.name, icon='IMAGE_DATA')

                content.separator(factor=0.3)

                # Bake control buttons row
                bake_row = content.row(align=True)
                bake_row.scale_y = 1.2
                bake_row.context_pointer_set('entity', mask)

                # Rebake button
                bake_row.operator("wm.m_bake_entity_to_image", text="Rebake", icon='FILE_REFRESH')

                # Use Baked toggle
                bake_row.prop(mask, "use_baked", text="Use Baked", toggle=True, icon='CHECKMARK' if mask.use_baked else 'CHECKBOX_DEHLT')

                # Remove baked button
                bake_row.operator("wm.m_remove_baked_entity", text="", icon='X')
            else:
                # Not baked - show Bake as Image button
                bake_row = content.row(align=True)
                bake_row.scale_y = 1.2
                bake_row.context_pointer_set('entity', mask)
                bake_row.operator("wm.m_bake_entity_to_image", text="Bake as Image", icon='RENDER_RESULT')


# =============================================================================
# TYPE-SPECIFIC PROPERTIES SECTIONS
# =============================================================================

def draw_mask_type_specific_props(layout, mask):
    """Draw type-specific properties for mask.

    Args:
        layout: UI layout (column)
        mask: YMask instance
    """
    if mask.type == 'HEMI':
        _draw_hemi_props(layout, mask)
    elif mask.type == 'COLOR_ID':
        _draw_color_id_props(layout, mask)
    elif mask.type == 'OBJECT_INDEX':
        _draw_object_index_props(layout, mask)
    elif mask.type == 'EDGE_DETECT':
        _draw_edge_detect_props(layout, mask)
    elif mask.type == 'AO':
        _draw_ao_props(layout, mask)


def _draw_hemi_props(layout, mask):
    """Draw HEMI mask properties in organized section."""
    section_box = layout.box()

    # Header
    header = section_box.row(align=True)
    header.scale_y = HEADER_SCALE
    header.label(text="Lighting Settings", icon='LIGHT_SUN')

    # Content
    content = section_box.column(align=True)
    content.scale_y = CONTENT_SCALE

    # Space row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Space")
    split.prop(mask, "hemi_space", text="")

    # Checkbox
    content.separator(factor=0.5)
    content.prop(mask, "hemi_use_prev_normal", text="Use Previous Normal")


def _draw_color_id_props(layout, mask):
    """Draw COLOR_ID mask properties in organized section."""
    section_box = layout.box()

    # Header
    header = section_box.row(align=True)
    header.scale_y = HEADER_SCALE
    header.label(text="Color ID", icon='COLOR')

    # Content
    content = section_box.column(align=True)
    content.scale_y = 1.3  # Slightly larger for color picker

    content.prop(mask, "color_id", text="")


def _draw_object_index_props(layout, mask):
    """Draw OBJECT_INDEX mask properties in organized section."""
    section_box = layout.box()

    # Header
    header = section_box.row(align=True)
    header.scale_y = HEADER_SCALE
    header.label(text="Object Index", icon='OBJECT_DATA')

    # Content
    content = section_box.column(align=True)
    content.scale_y = CONTENT_SCALE

    # Index row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Index")
    split.prop(mask, "object_index", text="")


def _draw_edge_detect_props(layout, mask):
    """Draw EDGE_DETECT mask properties in organized section."""
    section_box = layout.box()

    # Header
    header = section_box.row(align=True)
    header.scale_y = HEADER_SCALE
    header.label(text="Edge Detection", icon='EDGESEL')

    # Content
    content = section_box.column(align=True)
    content.scale_y = CONTENT_SCALE

    # Radius row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Radius")
    split.prop(mask, "edge_detect_radius", text="", slider=True)

    # Checkbox
    content.separator(factor=0.5)
    content.prop(mask, "hemi_use_prev_normal", text="Use Previous Normal")


def _draw_ao_props(layout, mask):
    """Draw AO mask properties in organized section."""
    section_box = layout.box()

    # Header
    header = section_box.row(align=True)
    header.scale_y = HEADER_SCALE
    header.label(text="Ambient Occlusion", icon='SHADING_RENDERED')

    # Content
    content = section_box.column(align=True)
    content.scale_y = CONTENT_SCALE

    # Distance row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Distance")
    split.prop(mask, "ao_distance", text="", slider=True)

    # Checkbox
    content.separator(factor=0.5)
    content.prop(mask, "hemi_use_prev_normal", text="Use Previous Normal")


# =============================================================================
# MAPPING SECTION
# =============================================================================

def draw_mask_mapping_section(layout, mask):
    """Draw mapping section for mask (collapsible).

    Args:
        layout: UI layout (column)
        mask: YMask instance
    """
    section_box = layout.box()

    # Header with expand arrow
    header = section_box.row(align=True)
    header.scale_y = HEADER_SCALE
    icon = 'DOWNARROW_HLT' if mask.expand_vector else 'RIGHTARROW'
    header.prop(mask, "expand_vector", text="", icon=icon, emboss=False)
    header.label(text="Mapping", icon='UV')

    if not mask.expand_vector:
        return

    # Content
    content = section_box.column(align=True)
    content.scale_y = CONTENT_SCALE
    content.separator(factor=0.3)

    # Vector / Coordinate Type row
    row = content.row(align=True)
    split = row.split(factor=LABEL_FACTOR, align=True)
    split.label(text="Vector")
    split.prop(mask, "texcoord_type", text="")

    # UV Map selector (conditional)
    if mask.texcoord_type == 'UV':
        row = content.row(align=True)
        split = row.split(factor=LABEL_FACTOR, align=True)
        split.label(text="UV Map")
        split.prop(mask, "uv_name", text="")

    # Decal properties (conditional)
    if mask.texcoord_type == 'Decal':
        content.separator(factor=0.5)
        _draw_decal_props_content(content, mask)

    # Blur controls (conditional)
    if hasattr(mask, 'enable_blur_vector'):
        content.separator(factor=0.5)
        content.prop(mask, "enable_blur_vector", text="Enable Blur")

        if mask.enable_blur_vector:
            row = content.row(align=True)
            split = row.split(factor=LABEL_FACTOR, align=True)
            split.label(text="Blur Factor")
            split.prop(mask, "blur_vector_factor", text="", slider=True)


def _draw_decal_props_content(content, mask):
    """Draw decal-specific properties inside a content column."""
    mask_tree = get_mask_tree(mask)
    texcoord = mask_tree.nodes.get(mask.texcoord) if mask_tree else None

    # Decal Object row
    if texcoord and hasattr(texcoord, 'object'):
        row = content.row(align=True)
        split = row.split(factor=LABEL_FACTOR, align=True)
        split.label(text="Decal Object")
        split.prop(texcoord, "object", text="")

    # Decal Distance row
    if hasattr(mask, 'decal_distance_value'):
        row = content.row(align=True)
        split = row.split(factor=LABEL_FACTOR, align=True)
        split.label(text="Distance")
        draw_input_prop(split, mask, 'decal_distance_value', text="")

    content.separator(factor=0.5)

    # Operator buttons (side by side)
    ops_row = content.row(align=True)
    ops_row.context_pointer_set('entity', mask)
    ops_row.operator("wm.m_select_decal_object", text="Select", icon='RESTRICT_SELECT_OFF')
    ops_row.operator("wm.m_set_decal_object_position_to_cursor", text="To Cursor", icon='CURSOR')

    # Stick to Surface checkbox
    decal_obj = get_decal_object(mask)
    if decal_obj and hasattr(decal_obj, 'mp_decal'):
        content.separator(factor=0.3)
        content.prop(decal_obj.mp_decal, 'enable_shrinkwrap', text="Stick to Surface", icon='MOD_SHRINKWRAP')


# =============================================================================
# MODIFIERS SECTION
# =============================================================================

def draw_mask_modifiers_section(layout, mask, layer):
    """Draw modifiers section for mask (collapsible).

    Args:
        layout: UI layout (column)
        mask: YMask instance
        layer: YLayer instance
    """
    section_box = layout.box()

    # Header with expand arrow and add button
    header = section_box.row(align=True)
    header.scale_y = HEADER_SCALE

    icon = 'DOWNARROW_HLT' if mask.expand_modifiers else 'RIGHTARROW'
    header.prop(mask, "expand_modifiers", text="", icon=icon, emboss=False)
    header.label(text="Modifiers", icon='MODIFIER')

    # Spacer to push add button to right
    header.separator()

    header.context_pointer_set('layer', layer)
    header.context_pointer_set('mask', mask)
    header.menu("MASK_MODIFIERS_MT_add_menu", text="", icon='ADD')

    if not mask.expand_modifiers:
        return

    # Content
    content = section_box.column(align=True)
    content.separator(factor=0.3)

    if len(mask.modifiers) == 0:
        info_row = content.row(align=True)
        info_row.scale_y = 1.0
        info_row.label(text="No modifiers", icon='INFO')
    else:
        for mod in mask.modifiers:
            _draw_single_modifier(content, mod, mask, layer)


def _draw_single_modifier(layout, mod, mask, layer):
    """Draw a single mask modifier in a sub-box."""
    mod_box = layout.box()
    mod_col = mod_box.column(align=True)

    # Modifier header row
    mod_row = mod_col.row(align=True)
    mod_row.scale_y = CONTENT_SCALE

    # Enable toggle
    mod_row.prop(mod, "enable", text="", icon='CHECKBOX_HLT' if mod.enable else 'CHECKBOX_DEHLT')

    # Modifier type label
    mod_type_label = mod.type.replace('_', ' ').title()
    mod_row.label(text=mod_type_label)

    # Spacer
    mod_row.separator()

    # Context pointers for operators
    mod_row.context_pointer_set('layer', layer)
    mod_row.context_pointer_set('mask', mask)
    mod_row.context_pointer_set('modifier', mod)

    # Move up/down buttons
    up_op = mod_row.operator("wm.m_move_mask_modifier", text="", icon='TRIA_UP', emboss=False)
    up_op.direction = 'UP'
    down_op = mod_row.operator("wm.m_move_mask_modifier", text="", icon='TRIA_DOWN', emboss=False)
    down_op.direction = 'DOWN'

    # Remove button
    mod_row.operator("wm.m_remove_mask_modifier", text="", icon='X', emboss=False)

    # Modifier content (when enabled)
    if mod.enable:
        mod_col.separator(factor=0.2)

        if mod.type == 'RAMP':
            mod_tree = get_mask_tree(mask)
            if mod_tree and mod.ramp:
                ramp_node = mod_tree.nodes.get(mod.ramp)
                if ramp_node and hasattr(ramp_node, 'color_ramp'):
                    mod_col.template_color_ramp(ramp_node, "color_ramp", expand=True)

        elif mod.type == 'CURVE':
            mod_tree = get_mask_tree(mask)
            if mod_tree and mod.curve:
                curve_node = mod_tree.nodes.get(mod.curve)
                if curve_node and hasattr(curve_node, 'mapping'):
                    mod_col.template_curve_mapping(curve_node, "mapping", type='COLOR')

    layout.separator(factor=0.2)
