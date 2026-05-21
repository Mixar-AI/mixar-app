# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Substance Painter-style FILL section UI for Fill layers.

This module draws the unified FILL section combining:
- Projection controls (UV, Triplanar, Planar, Spherical, Cylindrical, Decal)
- Mode-specific settings (UV Map, Wrap, Hardness, Decal Object)
- Transform controls (Offset, Rotation, Scale)
- Filtering
- Blending (Opacity, Blend Mode)
"""

from ...core.node.get_nodes import get_layer_source, get_tree
from ...core.subtree.get_subtree import get_tree as get_layer_tree
from .ui_helpers_base import draw_input_prop
from ..operators.decal_operators import get_decal_object


def draw_fill_section(context, layout, layer):
    """Draw Substance Painter-style FILL section for Fill layers.

    Contains all projection, transform, filtering, and blending controls
    in a single collapsible section matching SP's Properties panel layout.

    Args:
        context: Blender context
        layout: UI layout to draw into
        layer: Backend YLayer
    """
    # Only show for Fill layers (type='COLOR') with IMAGE or MATERIAL source
    if layer.type != 'COLOR' or layer.source_type == 'SOLID_COLOR':
        return

    # Get global UI state for expand toggle
    wm = context.window_manager
    ui_state = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

    # Get expand state (use expand_content for FILL section)
    expand_fill = ui_state.expand_content if ui_state else True

    # ========== FILL HEADER ==========
    header_box = layout.box()
    header_row = header_box.row(align=True)
    header_row.scale_y = 1.3

    # Collapse arrow icon
    icon = 'DOWNARROW_HLT' if expand_fill else 'RIGHTARROW'
    if ui_state:
        header_row.prop(ui_state, "expand_content", text="", icon=icon, emboss=False)
    header_row.label(text="FILL", icon='SHADING_TEXTURE')

    if not expand_fill:
        return

    layout.separator(factor=0.5)

    # ========== PROJECTION MODE ==========
    _draw_projection_controls(layout, layer)

    layout.separator(factor=0.5)

    # ========== TRANSFORM CONTROLS ==========
    # Transform controls moved to unified transform panel in properties_panel.py
    # See ui_helpers_unified_transform.py for the consolidated transform UI

    # ========== FILTERING ==========
    _draw_filtering_controls(layout, layer)

    layout.separator(factor=0.5)

    # ========== BLENDING CONTROLS ==========
    _draw_blending_controls(layout, layer)


def _draw_projection_controls(layout, layer):
    """Draw projection mode and mode-specific controls.

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    # Projection Type dropdown
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Projection")
    split.prop(layer, "projection_type", text="")

    layout.separator(factor=0.3)

    # Mode-specific controls
    if layer.projection_type == 'UV':
        # UV Map selector
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="UV Map")
        split.prop(layer, "uv_name", text="")

        layout.separator(factor=0.3)

        # Wrap mode
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Wrap")
        split.prop(layer, "uv_extension", text="")

    elif layer.projection_type == 'TRIPLANAR':
        # Triplanar hardness/blend
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Blend")
        split.prop(layer, "projection_hardness", text="", slider=True)

    elif layer.projection_type == 'PLANAR':
        # Planar axis selector
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Axis")
        axis_row = split.row(align=True)
        axis_row.prop_enum(layer, "projection_axis", "X")
        axis_row.prop_enum(layer, "projection_axis", "Y")
        axis_row.prop_enum(layer, "projection_axis", "Z")

    elif layer.projection_type == 'CYLINDRICAL':
        # Cylindrical axis selector (cylinder axis)
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Axis")
        axis_row = split.row(align=True)
        axis_row.prop_enum(layer, "projection_axis", "X")
        axis_row.prop_enum(layer, "projection_axis", "Y")
        axis_row.prop_enum(layer, "projection_axis", "Z")

    elif layer.projection_type == 'DECAL':
        # Get the texcoord node which holds the empty object reference
        layer_tree = get_layer_tree(layer)
        texcoord = layer_tree.nodes.get(layer.texcoord) if layer_tree else None

        # Decal Object selector
        if texcoord and hasattr(texcoord, 'object'):
            box_row = layout.box().row(align=True)
            box_row.scale_y = 1.3
            split = box_row.split(factor=0.3, align=True)
            split.label(text="Object")
            split.prop(texcoord, "object", text="")

            layout.separator(factor=0.3)

        # Decal Distance slider
        if hasattr(layer, 'decal_distance_value'):
            box_row = layout.box().row(align=True)
            box_row.scale_y = 1.3
            split = box_row.split(factor=0.3, align=True)
            split.label(text="Distance")
            draw_input_prop(split, layer, 'decal_distance_value', text="")

            layout.separator(factor=0.3)

        # Select Decal Object button
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        box_row.context_pointer_set('entity', layer)
        box_row.operator("wm.m_select_decal_object", text="Select Decal Object", icon='EMPTY_SINGLE_ARROW')

        layout.separator(factor=0.3)

        # Set Position to Cursor button
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        box_row.context_pointer_set('entity', layer)
        box_row.operator("wm.m_set_decal_object_position_to_cursor", text="Set Position to Cursor", icon='CURSOR')

        layout.separator(factor=0.3)

        # Shrinkwrap constraint toggle
        decal_obj = get_decal_object(layer)
        if decal_obj and hasattr(decal_obj, 'mp_decal'):
            box_row = layout.box().row(align=True)
            box_row.scale_y = 1.3
            box_row.prop(decal_obj.mp_decal, 'enable_shrinkwrap', text="Stick to Surface", icon='MOD_SHRINKWRAP')

    # SPHERICAL doesn't need extra controls - projects from center


def _draw_transform_controls(layout, layer):
    """Draw transform controls (offset, rotation, scale).

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    # ========== OFFSET (TRANSLATION) ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Offset")

    offset_row = split.row(align=True)
    offset_row.prop(layer, "translation", index=0, text="X")
    offset_row.prop(layer, "translation", index=1, text="Y")
    # Show Z offset for 3D projection modes
    if layer.projection_type in {'TRIPLANAR', 'SPHERICAL', 'CYLINDRICAL', 'PLANAR'}:
        offset_row.prop(layer, "translation", index=2, text="Z")

    layout.separator(factor=0.3)

    # ========== ROTATION ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Rotation")

    # For 3D projection modes, show all three rotation axes
    if layer.projection_type in {'TRIPLANAR', 'SPHERICAL', 'CYLINDRICAL', 'PLANAR'}:
        rot_row = split.row(align=True)
        rot_row.prop(layer, "rotation", index=0, text="X")
        rot_row.prop(layer, "rotation", index=1, text="Y")
        rot_row.prop(layer, "rotation", index=2, text="Z")
    else:
        # Z rotation only for UV projection
        split.prop(layer, "rotation", index=2, text="", slider=True)

    layout.separator(factor=0.3)

    # ========== SCALE (TILING) ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Scale")

    scale_row = split.row(align=True)
    scale_row.prop(layer, "scale", index=0, text="X")

    # Uniform scale lock button
    lock_icon = 'LOCKED' if layer.enable_uniform_scale else 'UNLOCKED'
    scale_row.prop(layer, "enable_uniform_scale", text="", icon=lock_icon, toggle=True)

    scale_row.prop(layer, "scale", index=1, text="Y")

    # Show Z scale for 3D projection modes
    if layer.projection_type in {'TRIPLANAR', 'SPHERICAL', 'CYLINDRICAL', 'PLANAR'}:
        scale_row.prop(layer, "scale", index=2, text="Z")


def _draw_filtering_controls(layout, layer):
    """Draw filtering (interpolation) control.

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    # Get source node for interpolation property
    tree = get_tree(layer)
    source_node = get_layer_source(layer, tree) if tree else None

    if source_node and hasattr(source_node, 'interpolation'):
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Filtering")
        split.prop(source_node, "interpolation", text="")


def _draw_blending_controls(layout, layer):
    """Draw blending controls (opacity and blend mode).

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    # Master Opacity slider
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Opacity")
    split.prop(layer, "intensity_value", text="", slider=True)

    layout.separator(factor=0.3)

    # Linked Blend Mode row
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Blend")

    # Link toggle + blend mode dropdown
    blend_row = split.row(align=True)
    link_icon = 'LINKED' if layer.blend_linked else 'UNLINKED'
    blend_row.prop(layer, "blend_linked", text="", icon=link_icon, toggle=True)
    blend_row.prop(layer, "linked_blend_type", text="")
