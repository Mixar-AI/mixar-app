# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Layer source properties."""

from ...core.node.get_nodes import get_layer_source, get_tree

# Re-export transform functions for backward compatibility
from .ui_helpers_layer_transform import (
    draw_fill_settings,
    draw_uv_transform_settings,
    draw_coordinate_settings,
)


def draw_source_properties(layout, layer, _mp):
    """Draw source node properties (MatPlus style)

    For Fill layers (type='COLOR'), shows:
    - Layer Source dropdown (Solid Color, Image, Material)
    - Properties based on source_type

    Args:
        layout: UI layout to draw into
        layer: Backend YLayer
        _mp: Root MPaint node tree property group (unused but kept for API compatibility)
    """
    # Get the source node using the proper helper function
    # Source nodes are inside the layer's group node tree, not the root tree
    tree = get_tree(layer)
    source_node = get_layer_source(layer, tree)

    if not source_node or layer.type in {'BACKGROUND', 'GROUP'}:
        return

    # Check if any channel has override enabled - if so, gray out source properties
    any_override = any(ch.override for ch in layer.channels)

    # ========== LAYER SOURCE DROPDOWN (only for Fill/COLOR layers) ==========
    if layer.type == 'COLOR':
        # Layer Source header
        source_header_box = layout.box()
        source_header_row = source_header_box.row(align=True)
        source_header_row.scale_y = 1.3
        source_header_row.label(text="Layer Source", icon='NODE_MATERIAL')

        layout.separator(factor=0.5)

        # Source type dropdown
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Source")
        split.prop(layer, "source_type", text="")

        layout.separator(factor=0.5)

    # Create Properties header box (MatPlus style)
    header_box = layout.box()
    header_row = header_box.row(align=True)
    header_row.scale_y = 1.3
    header_row.label(text="Properties", icon='PREFERENCES')

    layout.separator(factor=0.5)

    # Route based on layer type and source_type
    if layer.type == 'COLOR':
        # Fill layer - route based on source_type
        if layer.source_type == 'SOLID_COLOR':
            # Solid color - use existing dynamic drawing for ShaderNodeRGB
            draw_node_props_dynamic(layout, source_node, any_override)
        elif layer.source_type == 'IMAGE':
            # Image source - show image properties
            draw_image_source_properties(layout, source_node, layer, any_override)
        elif layer.source_type == 'MATERIAL':
            # Material source - show material selector and parameters
            draw_material_source_properties(layout, source_node, layer, any_override)
    else:
        # Non-Fill layers - use original routing
        if source_node.bl_idname == 'ShaderNodeGroup':
            # Custom node group (e.g., from material_registry) - use input introspection
            draw_node_group_inputs(layout, source_node, any_override)
        else:
            # Built-in node - use RNA introspection
            draw_node_props_dynamic(layout, source_node, any_override)


def draw_node_group_inputs(layout, node_group_instance, any_override, use_box=True):
    """Draw inputs for custom node groups (ShaderNodeGroup) - fully dynamic (MatPlus style)

    This handles custom procedural materials from material_registry.

    Args:
        layout: UI layout to draw into
        node_group_instance: ShaderNodeGroup instance
        any_override: Whether any channel has override enabled (grays out controls)
        use_box: If True, wrap each property in a box. If False, use plain rows.
    """
    if not node_group_instance.node_tree:
        if use_box:
            empty_box = layout.box()
            empty_row = empty_box.row()
        else:
            empty_row = layout.row()
        empty_row.alignment = 'CENTER'
        empty_row.label(text="No node group loaded", icon='INFO')
        return

    # UV/coordinate inputs that should never be exposed in the properties panel
    _HIDDEN_VECTOR_NAMES = {'Vector', 'UV', 'Normal', 'Tangent'}

    # Iterate through node instance inputs (not node_tree interface)
    # The node instance has .inputs which are the actual input sockets
    for input_socket in node_group_instance.inputs:
        # Skip internal UV/coordinate vector inputs
        if input_socket.type == 'VECTOR' and input_socket.name in _HIDDEN_VECTOR_NAMES:
            continue

        # Draw the input based on its type
        if input_socket.type in ('VALUE', 'INT', 'BOOLEAN', 'RGBA', 'VECTOR', 'STRING'):
            # Create row (with or without box wrapper)
            if use_box:
                row = layout.box().row(align=True)
                row.scale_y = 1.3
                layout.separator(factor=0.3)
            else:
                row = layout.row(align=True)
            row.enabled = not any_override  # Gray out if override is active

            # Property name (left side)
            split = row.split(factor=0.35, align=True)
            split.label(text=input_socket.name)

            # Property control (right side, remaining space)
            split.prop(input_socket, 'default_value', text='')


def draw_node_props_dynamic(layout, source_node, any_override, use_box=True):
    """Dynamically draw ALL properties of any node - fully introspective (MatPlus style)

    This uses Blender's RNA introspection to find and display all editable
    properties without hardcoding node types. Works for any current or future node.

    Args:
        layout: UI layout to draw into
        source_node: Source node to introspect
        any_override: Whether any channel has override enabled (grays out controls)
        use_box: If True, wrap each property in a box. If False, use plain rows.
    """
    # Special handling for ShaderNodeRGB (Fill Layer) - color is in output socket
    if source_node.bl_idname == 'ShaderNodeRGB':
        # Draw the fill color prominently
        if use_box:
            row = layout.box().row(align=True)
            row.scale_y = 1.5  # Slightly larger for color picker
            layout.separator(factor=0.3)
        else:
            row = layout.row(align=True)
        row.enabled = not any_override

        # Property name (left side)
        split = row.split(factor=0.35, align=True)
        split.label(text="Fill Color")

        # Color picker (right side)
        split.prop(source_node.outputs[0], 'default_value', text='')

        return  # No other properties needed for RGB node

    # Properties to skip (internal Blender node properties)
    skip_props = {
        'name', 'label', 'bl_idname', 'bl_label', 'bl_description', 'bl_rna',
        'type', 'parent', 'location', 'location_absolute', 'warning_propagation', 'width', 'height', 'width_hidden',
        'dimensions', 'select', 'show_options', 'show_preview', 'hide',
        'mute', 'color', 'use_custom_color', 'inputs', 'outputs',
        'internal_links', 'rna_type', 'bl_width_min', 'bl_width_max',
        'bl_height_min', 'bl_height_max', 'bl_static_type', 'bl_icon',
        'bl_width_default', 'bl_height_default', 'show_texture',
        'texture_mapping', 'color_mapping', 'image', 'image_user'
    }

    # Step 1: Draw node-level properties (enums, floats, ints, bools)
    # These are properties like noise_dimensions, wave_type, etc.
    for prop in source_node.bl_rna.properties:
        prop_name = prop.identifier

        # Skip unwanted/internal properties
        if prop_name in skip_props or prop.is_readonly:
            continue

        # Only show common editable property types (MatPlus style)
        if prop.type in {'ENUM', 'FLOAT', 'INT', 'BOOLEAN'}:
            # Create row (with or without box wrapper)
            if use_box:
                row = layout.box().row(align=True)
                row.scale_y = 1.3
                layout.separator(factor=0.3)
            else:
                row = layout.row(align=True)
            row.enabled = not any_override  # Gray out if override is active

            # Property name (left side)
            split = row.split(factor=0.35, align=True)
            split.label(text=prop.name)

            # Property control (right side, remaining space)
            split.prop(source_node, prop_name, text='')

    # Step 2: Draw input sockets (Scale, Detail, Roughness, Color1, etc.)
    for inp in source_node.inputs:
        # Skip Vector/UV inputs
        if inp.type == 'VECTOR' and inp.name in {'Vector', 'UV'}:
            continue

        # Skip hidden inputs
        if inp.hide:
            continue

        # Show value/color/bool inputs (MatPlus style)
        if inp.type in ('VALUE', 'RGBA', 'INT', 'BOOLEAN', 'STRING'):
            # Create row (with or without box wrapper)
            if use_box:
                row = layout.box().row(align=True)
                row.scale_y = 1.3
                layout.separator(factor=0.3)
            else:
                row = layout.row(align=True)
            row.enabled = not any_override  # Gray out if override is active

            # Property name (left side)
            split = row.split(factor=0.35, align=True)
            split.label(text=inp.name)

            # Property control (right side, remaining space)
            split.prop(inp, 'default_value', text='')


def draw_image_source_properties(layout, source_node, layer, any_override):
    """Draw properties for image source fill layer.

    Shows image-specific properties including:
    - Image selector (template_ID)
    - Interpolation dropdown
    - Extension dropdown
    - Color space

    Args:
        layout: UI layout to draw into
        source_node: ShaderNodeTexImage node
        layer: Backend YLayer
        any_override: Whether any channel has override enabled (grays out controls)
    """
    if source_node.bl_idname != 'ShaderNodeTexImage':
        return

    # Image selector
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    box_row.enabled = not any_override

    split = box_row.split(factor=0.3, align=True)
    split.label(text="Image")
    split.template_ID(source_node, "image", open="image.open")

    layout.separator(factor=0.3)

    if source_node.image:
        # Interpolation
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Interpolation")
        split.prop(source_node, "interpolation", text="")

        layout.separator(factor=0.3)

        # Extension
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Extension")
        split.prop(source_node, "extension", text="")

        layout.separator(factor=0.3)

        # Color space
        if hasattr(source_node.image, 'colorspace_settings'):
            box_row = layout.box().row(align=True)
            box_row.scale_y = 1.3
            split = box_row.split(factor=0.3, align=True)
            split.label(text="Color Space")
            split.prop(source_node.image.colorspace_settings, "name", text="")

            layout.separator(factor=0.3)


def draw_material_source_properties(layout, source_node, layer, any_override):
    """Draw properties for material source fill layer.

    Shows:
    - Material selector button (opens procedural material library)
    - Current material name and change/clear buttons if material is loaded
    - Material node group inputs if loaded

    Args:
        layout: UI layout to draw into
        source_node: Source node (ShaderNodeGroup if material is loaded)
        layer: Backend YLayer
        any_override: Whether any channel has override enabled (grays out controls)
    """
    # Check if a procedural material is loaded
    has_material = (
        source_node.bl_idname == 'ShaderNodeGroup' and
        source_node.node_tree is not None
    )

    # Get material info from layer's procedural_material_id if available
    material_id = getattr(layer, 'procedural_material_id', '')
    material_name = ''

    if material_id:
        # Try to get material name from registry
        try:
            from ...procedural_materials import material_registry
            material = material_registry.get_material(material_id)
            if material:
                material_name = material.name
            else:
                material_name = material_id
        except Exception:
            material_name = material_id
    elif has_material and source_node.node_tree:
        # Fallback to node tree name
        material_name = source_node.node_tree.name

    if has_material and material_name:
        # ========== CURRENT MATERIAL DISPLAY ==========
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.5
        box_row.enabled = not any_override

        split = box_row.split(factor=0.3, align=True)
        split.label(text="Material")

        # Material name and buttons
        mat_row = split.row(align=True)
        mat_row.label(text=material_name, icon='MATERIAL')

        # Change button - opens material library
        mat_row.operator("layers.procedural_material_library_popup", text="", icon='FILE_REFRESH')

        # Clear button
        mat_row.operator("layers.clear_layer_material", text="", icon='X')

        layout.separator(factor=0.5)

        # ========== MATERIAL PARAMETERS ==========
        if source_node.node_tree:
            # Header for parameters
            param_header = layout.box().row(align=True)
            param_header.scale_y = 1.2
            param_header.label(text="Parameters", icon='PROPERTIES')

            layout.separator(factor=0.3)

            # Draw node group inputs
            draw_node_group_inputs(layout, source_node, any_override)
    else:
        # ========== NO MATERIAL - SHOW SELECTOR ==========
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.5
        box_row.enabled = not any_override

        split = box_row.split(factor=0.3, align=True)
        split.label(text="Material")

        # "Select Material" button that opens the library popup
        split.operator("layers.procedural_material_library_popup", text="Select Material", icon='NODE_MATERIAL')

        layout.separator(factor=0.3)

        # Info label
        info_row = layout.row()
        info_row.alignment = 'CENTER'
        info_row.label(text="No procedural material selected", icon='INFO')
