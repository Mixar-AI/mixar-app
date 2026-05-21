# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Layer fill and UV transform settings."""

from ...core.node.get_nodes import get_layer_source, get_tree


def draw_fill_settings(layout, layer):
    """Draw fill settings for Fill layers (IMAGE/MATERIAL source types).

    Shows:
    - Projection type dropdown (UV, Tri-planar, Planar, Spherical, Cylindrical)
    - Hardness slider (if Tri-planar projection)
    - UV Wrap dropdown (if UV projection)
    - Filtering dropdown (Bilinear, Closest, Cubic) - from source node

    Only shown for Fill layers with IMAGE or MATERIAL source type.

    Args:
        layout: UI layout to draw into
        layer: Backend YLayer
    """
    # Only for Fill layers with IMAGE or MATERIAL source
    if layer.type != 'COLOR' or layer.source_type == 'SOLID_COLOR':
        return

    # Get source node for interpolation property
    tree = get_tree(layer)
    source_node = get_layer_source(layer, tree) if tree else None

    # ========== PROJECTION TYPE ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Projection")
    split.prop(layer, "projection_type", text="")

    layout.separator(factor=0.3)

    # Triplanar hardness slider (only for TRIPLANAR)
    if layer.projection_type == 'TRIPLANAR':
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Hardness")
        split.prop(layer, "projection_hardness", text="", slider=True)

        layout.separator(factor=0.3)

    # ========== UV WRAP (only for UV projection) ==========
    if layer.projection_type == 'UV':
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="UV Wrap")
        split.prop(layer, "uv_extension", text="")

        layout.separator(factor=0.3)

    # ========== FILTERING (from source node) ==========
    if source_node and hasattr(source_node, 'interpolation'):
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Filtering")
        split.prop(source_node, "interpolation", text="")

        layout.separator(factor=0.3)


def draw_uv_transform_settings(layout, layer):
    """Draw UV transformation settings for Fill layers.

    Shows:
    - Coordinate Type dropdown (UV, Object, Decal, etc.)
    - UV Map selector (if texcoord_type == 'UV')
    - Tiling (Scale) with X, Y and uniform lock
    - Rotation slider
    - Offset (Translation) X, Y

    Only shown for Fill layers with IMAGE or MATERIAL source type.

    Args:
        layout: UI layout to draw into
        layer: Backend YLayer
    """
    # Only for Fill layers with IMAGE or MATERIAL source
    if layer.type != 'COLOR' or layer.source_type == 'SOLID_COLOR':
        return

    # ========== COORDINATE TYPE ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Coordinate")
    split.prop(layer, "texcoord_type", text="")

    layout.separator(factor=0.3)

    # UV selector (only if texcoord_type is UV)
    if layer.texcoord_type == 'UV':
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.3
        split = box_row.split(factor=0.3, align=True)
        split.label(text="UV Map")
        split.prop(layer, "uv_name", text="")

        layout.separator(factor=0.3)

    # ========== TILING (SCALE) ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Tiling")

    # Tiling X, lock button, Tiling Y
    tiling_row = split.row(align=True)
    tiling_row.prop(layer, "scale", index=0, text="X")

    # Uniform scale lock button
    lock_icon = 'LOCKED' if layer.enable_uniform_scale else 'UNLOCKED'
    tiling_row.prop(layer, "enable_uniform_scale", text="", icon=lock_icon, toggle=True)

    tiling_row.prop(layer, "scale", index=1, text="Y")

    layout.separator(factor=0.3)

    # ========== ROTATION ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Rotation")
    # Only show Z rotation (most common for 2D textures)
    split.prop(layer, "rotation", index=2, text="", slider=True)

    layout.separator(factor=0.3)

    # ========== OFFSET (TRANSLATION) ==========
    box_row = layout.box().row(align=True)
    box_row.scale_y = 1.3
    split = box_row.split(factor=0.3, align=True)
    split.label(text="Offset")

    # Offset X, Y
    offset_row = split.row(align=True)
    offset_row.prop(layer, "translation", index=0, text="X")
    offset_row.prop(layer, "translation", index=1, text="Y")


def draw_coordinate_settings(layout, layer):
    """Draw coordinate and transform settings for Fill layers.

    DEPRECATED: Use draw_fill_settings() and draw_uv_transform_settings() instead.
    Kept for backward compatibility.

    Only shown for Fill layers (type='COLOR'), not Paint layers.
    Includes:
    - Coordinate Type dropdown (UV, Object, Decal, etc.)
    - UV Map selector (if texcoord_type == 'UV')
    - Projection Type dropdown (UV, Tri-planar, Planar, Spherical, Cylindrical)
    - Hardness slider (if projection_type == 'TRIPLANAR')
    - Offset (translation)
    - Rotation
    - Scale

    Args:
        layout: UI layout to draw into
        layer: Backend YLayer
    """
    # Skip for Paint layers - they use UV by default
    if layer.type == 'IMAGE':
        return

    # Use new split functions
    draw_fill_settings(layout, layer)
    draw_uv_transform_settings(layout, layer)
