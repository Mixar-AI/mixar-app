# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for bake panel UI drawing."""

import bpy
from ...core.node.get_nodes import get_layer_source


def is_baked_to_layer_type(layer, mp):
    """Check if a layer is a 'Bake to Layer' type (should be hidden from main list).

    Args:
        layer: Backend YLayer object
        mp: MPaint root property group

    Returns:
        bool: True if layer is a baked-to-layer type, False otherwise
    """
    if layer.type != "IMAGE":
        return False

    source = get_layer_source(layer)
    if not source or not source.image:
        return False

    img = source.image
    # Check if image is baked but NOT a baked channel (i.e., it's a "Bake to Layer" type)
    # This matches the pattern used in bake_to_layer_operators.py line 522-524
    return img.m_bake_info.is_baked and not img.m_bake_info.is_baked_channel


def draw_baked_maps_section(layout, mp, mixar_ui):
    """Draw the baked maps section showing existing baked-to-layer maps.

    Args:
        layout: Blender layout object
        mp: MPaint root property group
        mixar_ui: Mixar UI property group
    """
    # List all baked-to-layer types with preview toggle
    baked_layers = []
    for layer in mp.layers:
        if is_baked_to_layer_type(layer, mp):
            baked_layers.append(layer)

    if not baked_layers:
        return

    box = layout.box()

    # Collapsible header
    header_row = box.row(align=True)
    header_row.scale_y = 1.3
    collapse_icon = 'DOWNARROW_HLT' if mixar_ui.expand_baked_maps else 'RIGHTARROW'
    header_row.prop(mixar_ui, "expand_baked_maps", text="", icon=collapse_icon, emboss=False)
    header_row.label(text="Baked Maps", icon='IMAGE_DATA')

    # Content (only if expanded)
    if mixar_ui.expand_baked_maps:
        col = box.column(align=True)
        col.separator(factor=0.5)

        for layer in baked_layers:
            draw_baked_layer_item(col, layer, mp)

    layout.separator(factor=1)


def draw_baked_layer_item(col, layer, mp):
    """Draw a single baked layer item with preview toggle.

    Args:
        col: Blender column layout
        layer: Backend layer object
        mp: MPaint root property group
    """
    # Check if this layer is currently being previewed
    is_previewing = (mp.layer_preview_mode and
                   mp.active_layer_index >= 0 and
                   mp.active_layer_index < len(mp.layers) and
                   mp.layers[mp.active_layer_index].name == layer.name)

    # Get bake type info for display
    source = get_layer_source(layer)
    bake_type_name = layer.name
    bake_type_icon = 'TEXTURE'
    if source and source.image:
        bake_type = source.image.m_bake_info.bake_type
        # Get appropriate icon based on bake type
        type_icons = {
            'AO': 'SHADING_RENDERED',
            'POINTINESS': 'SHARPCURVE',
            'CAVITY': 'SMOOTHCURVE',
            'DUST': 'PARTICLES',
            'PAINT_BASE': 'BRUSHES_ALL',
            'BEVEL_MASK': 'MOD_BEVEL',
            'BEVEL_NORMAL': 'MOD_BEVEL',
            'SELECTED_VERTICES': 'VERTEXSEL',
            'MULTIRES_NORMAL': 'MOD_MULTIRES',
            'MULTIRES_DISPLACEMENT': 'MOD_MULTIRES',
            'OTHER_OBJECT_NORMAL': 'OBJECT_DATA',
            'OTHER_OBJECT_EMISSION': 'OBJECT_DATA',
            'OTHER_OBJECT_CHANNELS': 'OBJECT_DATA',
            'FLOW': 'FORCE_WIND',
            'OBJECT_SPACE_NORMAL': 'NORMALS_FACE',
        }
        bake_type_icon = type_icons.get(bake_type, 'TEXTURE')

    # Preview toggle button - bigger and clearer
    row = col.row(align=True)
    row.scale_y = 1.3

    preview_icon = 'HIDE_OFF' if is_previewing else 'HIDE_ON'
    preview_text = "Preview: " + bake_type_name
    op = row.operator("wm.m_toggle_baked_layer_preview", text=preview_text, icon=preview_icon, depress=is_previewing)
    op.layer_name = layer.name

    col.separator(factor=0.3)


def draw_bake_operations_section(layout, mixar_ui):
    """Draw the bake operations section with bake buttons.

    Args:
        layout: Blender layout object
        mixar_ui: Mixar UI property group
    """
    # Content (only if expanded)
    if not mixar_ui.expand_bake_operations:
        return

    box = layout.box()
    col = box.column(align=True)
    col.separator(factor=0.5)

    # Bake all channels - check if operator can run
    row = col.row(align=True)
    row.scale_y = 1.1
    row.operator("wm.m_bake_channels", text="Bake All Channels", icon='RENDER_STILL')
    # Enable only if operator poll passes
    row.enabled = hasattr(bpy.ops.wm, 'm_bake_channels') and bpy.ops.wm.m_bake_channels.poll()

    col.separator(factor=0.5)

    # Bake to vertex color
    row = col.row(align=True)
    row.scale_y = 1.1
    row.operator("wm.m_bake_channel_to_vcol", text="Bake to Vertex Color", icon='VPAINT_HLT')
    row.enabled = hasattr(bpy.ops.wm, 'm_bake_channel_to_vcol') and bpy.ops.wm.m_bake_channel_to_vcol.poll()

    col.separator(factor=0.5)

    # Bake temp image
    row = col.row(align=True)
    row.scale_y = 1.1
    row.operator("wm.m_bake_temp_image", text="Bake Temporary Image", icon='IMAGE_DATA')
    row.enabled = hasattr(bpy.ops.wm, 'm_bake_temp_image') and bpy.ops.wm.m_bake_temp_image.poll()


def draw_bake_to_layer_section(layout, mixar_ui):
    """Draw the bake to layer section with mesh map bake buttons.

    Args:
        layout: Blender layout object
        mixar_ui: Mixar UI property group
    """
    box = layout.box()

    # Collapsible header
    header_row = box.row(align=True)
    header_row.scale_y = 1.3
    collapse_icon = 'DOWNARROW_HLT' if mixar_ui.expand_bake_to_layer else 'RIGHTARROW'
    header_row.prop(mixar_ui, "expand_bake_to_layer", text="", icon=collapse_icon, emboss=False)
    header_row.label(text="Bake Mesh Maps", icon='RENDERLAYERS')

    # Content (only if expanded)
    if mixar_ui.expand_bake_to_layer:
        col = box.column(align=True)
        col.separator(factor=0.5)

        # Surface Effects row (5 tabs)
        draw_surface_effects_row(col)

        col.separator(factor=0.5)

        # Geometry row (4 tabs)
        draw_geometry_row(col)

    layout.separator(factor=1)

    return box


def draw_surface_effects_row(col):
    """Draw the surface effects bake buttons row.

    Args:
        col: Blender column layout
    """
    surface_row = col.row(align=True)
    surface_row.scale_y = 1.3

    op = surface_row.operator("wm.m_bake_to_layer", text="AO")
    op.type = 'AO'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = surface_row.operator("wm.m_bake_to_layer", text="Pointiness")
    op.type = 'POINTINESS'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = surface_row.operator("wm.m_bake_to_layer", text="Cavity")
    op.type = 'CAVITY'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = surface_row.operator("wm.m_bake_to_layer", text="Dust")
    op.type = 'DUST'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = surface_row.operator("wm.m_bake_to_layer", text="Paint Base")
    op.type = 'PAINT_BASE'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False


def draw_geometry_row(col):
    """Draw the geometry bake buttons row.

    Args:
        col: Blender column layout
    """
    geom_row = col.row(align=True)
    geom_row.scale_y = 1.3

    op = geom_row.operator("wm.m_bake_to_layer", text="Bevel")
    op.type = 'BEVEL_MASK'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = geom_row.operator("wm.m_bake_to_layer", text="Bevel Normal")
    op.type = 'BEVEL_NORMAL'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = geom_row.operator("wm.m_bake_to_layer", text="Selected Verts")
    op.type = 'SELECTED_VERTICES'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = geom_row.operator("wm.m_bake_to_layer", text="Position")
    op.type = 'POSITION'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False


def draw_cleanup_section(layout, mixar_ui, box):
    """Draw the cleanup section with delete buttons.

    Args:
        layout: Blender layout object
        mixar_ui: Mixar UI property group
        box: Box layout to add content to
    """
    # Content (only if expanded)
    if not mixar_ui.expand_cleanup:
        return

    col = box.column(align=True)
    col.separator(factor=0.5)

    # Delete baked images
    row = col.row(align=True)
    row.scale_y = 1.1
    row.operator("wm.m_delete_baked_channel_images", text="Delete Baked Images", icon='TRASH')
    row.enabled = hasattr(bpy.ops.wm, 'm_delete_baked_channel_images') and bpy.ops.wm.m_delete_baked_channel_images.poll()
