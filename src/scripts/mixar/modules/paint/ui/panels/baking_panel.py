# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Baking Space Panel

Panel definition for texture baking and export options.
Includes channel baking, mesh map generation, and preview functionality.
"""

import bpy
from bpy.types import Panel

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
    # Check if image is baked but NOT a baked channel
    return img.m_bake_info.is_baked and not img.m_bake_info.is_baked_channel


def _draw_placeholder_ui(layout, context):
    """Draw placeholder UI when no layer-based material is active.

    Args:
        layout: Blender UI layout
        context: Blender context
    """
    box = layout.box()
    col = box.column(align=True)

    # Icon and title
    row = col.row()
    row.alignment = 'CENTER'
    row.label(text="", icon='TEXTURE')

    col.separator(factor=0.5)

    # Main message
    row = col.row()
    row.alignment = 'CENTER'
    row.label(text="No Layer-Based Material Active")

    col.separator(factor=0.5)

    # Instructions
    col = box.column(align=True)
    col.scale_y = 0.9
    col.label(text="To use texture baking:", icon='DOT')
    col.label(text="  1. Select an object with a Mixar material")
    col.label(text="  2. Or create a new layer-based material")

    col.separator()

    # Action buttons
    col = box.column(align=True)
    col.scale_y = 1.2

    # New material button
    if context.active_object and context.active_object.type == 'MESH':
        col.operator("layers.create_material", text="Create New Material", icon='ADD')
    else:
        row = col.row()
        row.enabled = False
        row.operator("layers.create_material", text="Create New Material", icon='ADD')
        col.label(text="(Select a mesh object first)", icon='INFO')

    layout.separator()

    # Quick tips box
    box = layout.box()
    box.label(text="Quick Tips", icon='LIGHT')
    col = box.column(align=True)
    col.scale_y = 0.85
    col.label(text="Bake channels to high-res textures")
    col.label(text="Generate mesh maps (AO, Cavity, etc.)")
    col.label(text="Export textures for game engines")


def _draw_bake_channels_section(layout, mp):
    """Draw the bake channels section.

    Args:
        layout: Blender UI layout
        mp: MPaint property group
    """
    box = layout.box()
    box.label(text="Bake Channels", icon='RENDER_STILL')

    col = box.column(align=True)
    col.scale_y = 1.3

    # Bake all channels
    row = col.row(align=True)
    bake_op = row.operator("wm.m_bake_channels", text="Bake All Channels", icon='RENDER_STILL')
    bake_op.only_active_channel = False
    if hasattr(bpy.ops.wm, 'm_bake_channels'):
        row.enabled = bpy.ops.wm.m_bake_channels.poll()
    else:
        row.enabled = False

    col.separator()

    # Bake to vertex color
    # row = col.row(align=True)
    # row.operator("wm.m_bake_channel_to_vcol", text="Bake to Vertex Color", icon='VPAINT_HLT')
    # if hasattr(bpy.ops.wm, 'm_bake_channel_to_vcol'):
    #     row.enabled = bpy.ops.wm.m_bake_channel_to_vcol.poll()
    # else:
    #     row.enabled = False


def _draw_mesh_maps_section(layout):
    """Draw the mesh maps baking section.

    Args:
        layout: Blender UI layout
    """
    box = layout.box()
    box.label(text="Bake Mesh Maps", icon='RENDERLAYERS')

    col = box.column(align=True)

    # Surface Effects row
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

    col.separator(factor=0.5)

    # More bake options row
    more_row = col.row(align=True)
    more_row.scale_y = 1.3

    op = more_row.operator("wm.m_bake_to_layer", text="Dust")
    op.type = 'DUST'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = more_row.operator("wm.m_bake_to_layer", text="Paint Base")
    op.type = 'PAINT_BASE'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    op = more_row.operator("wm.m_bake_to_layer", text="Bevel")
    op.type = 'BEVEL_MASK'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False

    col.separator(factor=0.5)

    # Position map row
    pos_row = col.row(align=True)
    pos_row.scale_y = 1.3

    op = pos_row.operator("wm.m_bake_to_layer", text="Position")
    op.type = 'POSITION'
    op.target_type = 'PREVIEW'
    op.overwrite_current = False


def _draw_baked_channels_section(layout, mp, node):
    """Draw the view baked channels section.

    Args:
        layout: Blender UI layout
        mp: MPaint property group
        node: The Mixar node tree

    Returns:
        bool: True if section was drawn, False otherwise
    """
    tree = node.node_tree
    baked_channels = []
    for ch in mp.channels:
        baked_node = tree.nodes.get(ch.baked)
        if baked_node and baked_node.image:
            baked_channels.append((ch, baked_node.image))

    # Show section if there are baked channels OR if baked mode is active
    if not baked_channels and not mp.use_baked:
        return False

    box = layout.box()

    # Header with baked mode indicator
    header_row = box.row(align=True)
    baked_active_icon = 'CHECKBOX_HLT' if mp.use_baked else 'RENDERLAYERS'
    header_row.label(text="View Baked Channels", icon=baked_active_icon)

    col = box.column(align=True)

    # Return to Material View button (prominent when baked mode is on)
    if mp.use_baked:
        col.separator(factor=0.5)
        return_row = col.row(align=True)
        return_row.scale_y = 1.5
        return_row.alert = True
        op = return_row.operator(
            "wm.m_toggle_baked_channel_preview",
            text="Return to Material View",
            icon='MATERIAL'
        )
        op.channel_name = ""  # Empty name = disable baked mode
        col.separator(factor=0.5)

    # Preview All Baked Channels button with Export All
    if baked_channels:
        is_all_baked_preview = mp.use_baked and not mp.preview_mode
        all_row = col.row(align=True)
        all_row.scale_y = 1.3

        # 80% - Preview button
        all_row.operator(
            "wm.m_preview_all_baked_channels",
            text="Preview All Baked" if not is_all_baked_preview else "Previewing All Baked",
            icon='NODE_COMPOSITING',
            depress=is_all_baked_preview
        )

        # 20% - Export All button (use scale_x to control width)
        export_sub = all_row.row(align=True)
        export_sub.scale_x = 1.5
        export_sub.operator(
            "wm.m_export_all_baked_channels",
            text="",
            icon='EXPORT'
        )
        col.separator(factor=1.5)

    # List baked channels with toggle buttons for individual preview
    if baked_channels:
        for ch, image in baked_channels:
            # Check if this channel is currently being previewed individually
            is_previewing = (
                mp.preview_mode
                and mp.active_channel_index >= 0
                and mp.active_channel_index < len(mp.channels)
                and mp.channels[mp.active_channel_index].name == ch.name
            )

            # Get channel type icon
            type_icons = {
                'RGB': 'IMAGE_RGB',
                'VALUE': 'IMAGE_RGB_ALPHA',
                'NORMAL': 'NORMALS_FACE',
            }
            ch_icon = type_icons.get(ch.type, 'TEXTURE')

            row = col.row(align=True)
            row.scale_y = 1.2

            # Preview toggle button (takes most of the space)
            preview_icon = 'HIDE_OFF' if is_previewing else 'HIDE_ON'
            op = row.operator(
                "wm.m_toggle_baked_channel_preview",
                text=ch.name,
                icon=preview_icon,
                depress=is_previewing
            )
            op.channel_name = ch.name

            # Export button (smaller, on the right)
            export_sub = row.row(align=True)
            export_sub.scale_x = 1.5
            exp_op = export_sub.operator(
                "wm.m_export_baked_channel",
                text="",
                icon='EXPORT'
            )
            exp_op.channel_name = ch.name

            col.separator(factor=0.3)
    else:
        col.label(text="No baked channels yet", icon='INFO')
        col.label(text="Use 'Bake All Channels' above")

    layout.separator()
    return True


def _get_baked_mesh_map_images():
    """Find all baked mesh map images from bpy.data.images.

    Returns:
        list: List of baked mesh map images (is_baked=True, is_baked_channel=False)
    """
    baked_images = []
    for image in bpy.data.images:
        bi = image.m_bake_info
        # is_baked=True: was baked
        # is_baked_channel=False: not a channel bake (those go to channels section)
        if bi.is_baked and not bi.is_baked_channel:
            baked_images.append(image)
    return baked_images


def _get_material_category_items():
    """Get list of material categories for dropdown display.

    Returns:
        list: List of (identifier, display_name) tuples.
    """
    from ...procedural_materials import material_registry

    items = [('ALL', 'All Categories')]
    try:
        categories = material_registry.get_categories()
        for cat in categories:
            display_name = cat.replace('_', ' ').title()
            items.append((cat, display_name))
    except Exception:
        pass
    return items


def _draw_inline_material_library(layout, context):
    """Draw the material library directly in the panel.

    Args:
        layout: Blender UI layout
        context: Blender context
    """
    from ...procedural_materials import material_registry
    from ..utils.material_preview_manager import load_material_preview

    wm = context.window_manager
    mixar_ui = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

    if not mixar_ui:
        layout.label(text="UI state not available", icon='ERROR')
        return

    # === HEADER: Search and Category Filter ===
    header_box = layout.box()
    header_col = header_box.column(align=True)

    # Search row
    search_row = header_col.row(align=True)
    search_row.prop(mixar_ui, "material_library_search", text="", icon='VIEWZOOM')
    if mixar_ui.material_library_search:
        search_row.operator("wm.m_clear_material_search", text="", icon='X')

    # Category filter row - using a dropdown menu
    cat_row = header_col.row(align=True)
    cat_row.menu("BAKING_MT_material_category", text=_get_category_display_name(mixar_ui.material_library_category))

    # === GET FILTERED MATERIALS ===
    try:
        category = mixar_ui.material_library_category
        search_text = mixar_ui.material_library_search.lower()

        if category == 'ALL':
            materials = material_registry.get_all_materials()
        else:
            materials = material_registry.get_materials_by_category(category)

        # Apply search filter
        if search_text:
            materials = [m for m in materials if search_text in m.name.lower()]

        # === MATERIAL COUNT ===
        count_row = header_col.row()
        count_row.label(text=f"{len(materials)} materials")

        layout.separator()

        # === MATERIAL GRID ===
        if not materials:
            layout.label(text="No materials found", icon='INFO')
            return

        # Get preferences for UI settings
        from ...utils.preferences import get_mixar_paint_preferences
        prefs = get_mixar_paint_preferences()
        if prefs:
            columns = getattr(prefs, 'material_ui_columns', 4)
            scale = getattr(prefs, 'material_image_scale', 3.0)
        else:
            columns = 4
            scale = 3.0

        # Create grid layout for materials
        grid_box = layout.box()
        grid = grid_box.grid_flow(
            row_major=True,
            columns=columns,
            even_columns=True,
            even_rows=True,
            align=True
        )

        # Draw each material
        for material in materials:
            # Material item container
            item_col = grid.column(align=True)
            item_box = item_col.box()
            item_inner = item_box.column(align=True)

            # Thumbnail
            icon_id = load_material_preview(material)
            if icon_id:
                item_inner.template_icon(icon_value=icon_id, scale=scale)
            else:
                item_inner.label(text="", icon='MATERIAL')

            # Material name (truncated)
            name_display = material.name[:16] + "..." if len(material.name) > 16 else material.name
            name_row = item_inner.row(align=True)
            name_row.alignment = 'CENTER'
            name_row.scale_y = 0.8
            name_row.label(text=name_display)

            # Add to layer button
            op = item_inner.operator(
                "layers.add_custom_procedural_layer",
                text="Add to Layer",
                icon='ADD',
            )
            op.material_id = material.material_id

    except Exception as e:
        layout.label(text=f"Error: {str(e)}", icon='ERROR')


def _get_category_display_name(category_id):
    """Get display name for a category ID.

    Args:
        category_id: Category identifier string.

    Returns:
        str: Human-readable category name.
    """
    if category_id == 'ALL':
        return "All Categories"
    return category_id.replace('_', ' ').title()


class BAKING_MT_material_category(bpy.types.Menu):
    """Material category selection menu"""
    bl_idname = "BAKING_MT_material_category"
    bl_label = "Select Category"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        mixar_ui = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

        if not mixar_ui:
            return

        categories = _get_material_category_items()
        for cat_id, cat_name in categories:
            op = layout.operator(
                "wm.m_set_material_category",
                text=cat_name,
                icon='CHECKMARK' if mixar_ui.material_library_category == cat_id else 'NONE'
            )
            op.category = cat_id


class BAKING_OT_set_material_category(bpy.types.Operator):
    """Set material library category filter"""
    bl_idname = "wm.m_set_material_category"
    bl_label = "Set Category"
    bl_options = {'INTERNAL'}

    category: bpy.props.StringProperty(default='ALL')

    def execute(self, context):
        wm = context.window_manager
        if hasattr(wm, 'mixar_ui'):
            wm.mixar_ui.material_library_category = self.category
        return {'FINISHED'}


def _draw_procedural_materials_section(layout):
    """Draw the procedural materials section for Assets tab.

    Args:
        layout: Blender UI layout
    """
    # Use inline material library instead of popup button
    _draw_inline_material_library(layout, bpy.context)


def _draw_baked_textures_section(layout, mp):
    """Draw the preview baked textures section.

    Args:
        layout: Blender UI layout
        mp: MPaint property group

    Returns:
        bool: True if section was drawn, False otherwise
    """
    # Get baked mesh map images directly from bpy.data.images
    baked_images = _get_baked_mesh_map_images()

    # Check if image preview is active
    is_image_preview_active = mp.image_preview_name != ""

    if not baked_images and not is_image_preview_active:
        return False

    box = layout.box()

    # Header with preview indicator
    header_row = box.row(align=True)
    preview_active_icon = 'HIDE_OFF' if is_image_preview_active else 'IMAGE_DATA'
    header_row.label(text="Preview Baked Textures", icon=preview_active_icon)

    col = box.column(align=True)

    # Return to Material View button (prominent when in preview mode)
    if is_image_preview_active:
        col.separator(factor=0.5)
        return_row = col.row(align=True)
        return_row.scale_y = 1.5
        return_row.alert = True
        op = return_row.operator(
            "wm.m_toggle_baked_image_preview",
            text="Return to Material View",
            icon='MATERIAL'
        )
        op.image_name = ""  # Empty name = disable preview
        col.separator(factor=0.5)

    # Icon mapping for bake types
    type_icons = {
        'AO': 'SHADING_RENDERED',
        'POINTINESS': 'SHARPCURVE',
        'CAVITY': 'SMOOTHCURVE',
        'DUST': 'PARTICLES',
        'PAINT_BASE': 'BRUSHES_ALL',
        'BEVEL_MASK': 'MOD_BEVEL',
        'BEVEL_NORMAL': 'MOD_BEVEL',
        'POSITION': 'EMPTY_AXIS',
        'SELECTED_VERTICES': 'VERTEXSEL',
        'MULTIRES_NORMAL': 'MOD_MULTIRES',
        'MULTIRES_DISPLACEMENT': 'MOD_MULTIRES',
        'FLOW': 'FORCE_WIND',
        'OBJECT_SPACE_NORMAL': 'NORMALS_FACE',
    }

    # List baked images with toggle buttons
    if baked_images:
        # Add Export All row at the top if multiple textures
        if len(baked_images) > 1:
            all_row = col.row(align=True)
            all_row.scale_y = 1.3

            # Label takes most space
            all_row.label(text="All Baked Textures", icon='RENDERLAYERS')

            # Export All button (smaller, on the right)
            export_sub = all_row.row(align=True)
            export_sub.scale_x = 1.5
            export_sub.operator(
                "wm.m_export_all_baked_textures",
                text="",
                icon='EXPORT'
            )
            col.separator(factor=0.5)

        for image in baked_images:
            # Check if this image is currently being previewed
            is_previewing = mp.image_preview_name == image.name

            # Get bake type info for display
            bake_type = image.m_bake_info.bake_type
            bake_type_icon = type_icons.get(bake_type, 'TEXTURE')

            row = col.row(align=True)
            row.scale_y = 1.2

            # Preview toggle button (takes most of the space)
            preview_icon = 'HIDE_OFF' if is_previewing else 'HIDE_ON'
            op = row.operator(
                "wm.m_toggle_baked_image_preview",
                text=image.name,
                icon=preview_icon,
                depress=is_previewing
            )
            op.image_name = image.name

            # Export button (smaller, on the right)
            export_sub = row.row(align=True)
            export_sub.scale_x = 1.5
            exp_op = export_sub.operator(
                "wm.m_export_baked_texture",
                text="",
                icon='EXPORT'
            )
            exp_op.image_name = image.name

            col.separator(factor=0.3)
    else:
        col.label(text="No baked textures yet", icon='INFO')

    layout.separator()
    return True


class BAKING_PT_main(Panel):
    """Baking Panel - Texture baking and export options"""
    bl_label = ""
    bl_idname = "BAKING_PT_main"
    bl_space_type = 'BAKING'
    bl_region_type = 'WINDOW'
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout

        # Top padding
        for _ in range(2):
            layout.separator()

        from ...core.node.node_utils import get_active_mpaint_node

        # Get active mpaint node
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            _draw_placeholder_ui(layout, context)
            return

        mp = node.node_tree.mp
        wm = context.window_manager
        mixar_ui = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

        # ========== TAB ROW ==========
        tab_row = layout.row(align=True)
        tab_row.scale_y = 1.5
        tab_row.prop(mixar_ui, "baking_panel_tab", expand=True)

        layout.separator()

        # ========== CONDITIONAL SECTIONS BASED ON TAB ==========
        if mixar_ui.baking_panel_tab == 'MESH_BAKING':
            # MESH BAKING TAB
            # - Bake Mesh Maps section
            # - Preview Baked Textures section

            _draw_mesh_maps_section(layout)

            layout.separator()

            _draw_baked_textures_section(layout, mp)

        elif mixar_ui.baking_panel_tab == 'ASSETS':
            # ASSETS TAB
            # - Procedural Materials section

            _draw_procedural_materials_section(layout)

        elif mixar_ui.baking_panel_tab == 'TEXTURE_EXPORT':
            # TEXTURE EXPORT TAB
            # - Bake Channels section
            # - View Baked Channels section
            # - Export Textures section

            _draw_bake_channels_section(layout, mp)

            layout.separator()

            _draw_baked_channels_section(layout, mp, node)

            # Export Textures section — Bake Targets + Export Actions
            from .export_panel_helpers import draw_export_textures_section
            draw_export_textures_section(layout, mp, node)

        elif mixar_ui.baking_panel_tab == 'ASSET_EXPORT':
            # ASSET EXPORT TAB
            # - Bake & Create Export Material section
            # - Export format tabs (glTF / OBJ / FBX)

            from .asset_export_panel_helpers import draw_asset_export_section
            draw_asset_export_section(layout, mp, node, context)


classes = (
    BAKING_MT_material_category,
    BAKING_OT_set_material_category,
    BAKING_PT_main,
)
