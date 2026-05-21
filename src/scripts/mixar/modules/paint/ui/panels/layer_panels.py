# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Panel definitions for Mixar layers system"""

import bpy
from bpy.types import Panel

from ..utils.ui_helpers import draw_layer_item, draw_layer_settings, draw_top_toolbar, draw_materials_section
from ..utils.ui_helpers_mask import draw_mask_settings
from ..utils.ui_refresh import update_mixar_ui

# Import from helper modules
from .bake_panel_helpers import (
    is_baked_to_layer_type,
    draw_baked_maps_section,
    draw_baked_layer_item,
    draw_bake_operations_section,
    draw_bake_to_layer_section,
    draw_surface_effects_row,
    draw_geometry_row,
    draw_cleanup_section,
)
from .preferences_panel_helpers import (
    draw_image_settings,
    draw_ui_options,
    draw_rendering_options,
    draw_layer_node_options,
    draw_update_settings,
    draw_developer_options,
    draw_danger_zone,
)
from .channels_panel_helpers import (
    draw_channels_content,
    draw_channel_item,
)

# Re-export all helper functions for backward compatibility
__all__ = [
    # Bake panel helpers
    'is_baked_to_layer_type',
    'draw_baked_maps_section',
    'draw_baked_layer_item',
    'draw_bake_operations_section',
    'draw_bake_to_layer_section',
    'draw_surface_effects_row',
    'draw_geometry_row',
    'draw_cleanup_section',
    # Preferences panel helpers
    'draw_image_settings',
    'draw_ui_options',
    'draw_rendering_options',
    'draw_layer_node_options',
    'draw_update_settings',
    'draw_developer_options',
    'draw_danger_zone',
    # Channels panel helpers
    'draw_channels_content',
    'draw_channel_item',
    # Panel classes
    'LAYERS_PT_Main',
    'LAYERS_PT_Layers',
    'LAYERS_PT_Settings',
    'LAYERS_PT_Bake',
    'LAYERS_PT_Preferences',
    'LAYERS_PT_Channels',
    'classes',
]


# Base class for all Layers panels
class LAYERS_PT_Main:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "layers"

    @classmethod
    def poll(cls, context):
        """Determines if the panel should be displayed.

        Args:
            context (bpy.types.Context): The current Blender context.

        Returns:
            bool: True if a scene exists, False otherwise.
        """
        return context.scene is not None


# Main Layers panel
class LAYERS_PT_Layers(LAYERS_PT_Main, Panel):
    bl_label = "Layers"
    bl_idname = "LAYERS_PT_Layers"

    def draw(self, context):
        """Draws the main Layers panel UI.

        This panel displays the layer list, toolbar, and create material button.
        Updates the UI cache before drawing to sync backend state with frontend.

        Args:
            context (bpy.types.Context): The current Blender context.

        Returns:
            None
        """
        # UPDATE UI PROPS FIRST - Mixar Paint pattern adapted for Properties panels
        # This syncs backend (YLayer/mp) -> frontend (WindowManager.mixar_ui.ui_layers)
        # WindowManager is writable even in Properties panel draw context
        update_mixar_ui()

        layout = self.layout
        wm = context.window_manager

        # Check if mixar_ui exists
        if not hasattr(wm, 'mixar_ui'):
            layout.label(text="Paint backend not initialized", icon='ERROR')
            return

        # Check if mpui exists (required for materials section)
        if not hasattr(wm, 'mpui'):
            layout.label(text="Paint UI not initialized", icon='ERROR')
            return

        mixar_ui = wm.mixar_ui

        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=True)

        # ========== MATERIALS SECTION ==========
        # Draw materials UI list at the top (Mixar Paint pattern)
        draw_materials_section(context, main_col)

        # No layers - show create material button
        if len(mixar_ui.ui_layers) == 0:
            self._draw_empty_state(context, main_col)
            return

        # Get backend mp for UIList
        obj = context.active_object
        mp = None
        if obj and obj.active_material and obj.active_material.use_nodes:
            mat = obj.active_material
            for n in mat.node_tree.nodes:
                if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                    mp = n.node_tree.mp
                    break

        if not mp:
            main_col.label(text="No Mixar material found", icon='INFO')
            return

        # ========== CHANNEL FILTER DROPDOWN (Substance 3D Painter style) ==========
        channel_row = main_col.row(align=True)
        channel_row.scale_y = 1.2
        channel_row.prop(mixar_ui, "active_channel_filter", text="")

        main_col.separator(factor=0.5)

        # Top toolbar (only show when layers exist)
        draw_top_toolbar(context, main_col)

        main_col.separator()

        # ========== LAYER LIST (UIList with drag-and-drop) ==========
        row = main_col.row()

        # UIList for layers - Substance 3D Painter style
        row.template_list(
            "LAYERS_UL_layer_list", "",
            mp, "layers",
            mp, "active_layer_index",
            rows=8
        )

        # Side column with move/action buttons
        col = row.column(align=True)
        col.operator("wm.m_move_layer", icon='TRIA_UP', text="").direction = 'UP'
        col.operator("wm.m_move_layer", icon='TRIA_DOWN', text="").direction = 'DOWN'
        col.separator()
        col.operator("wm.m_copy_layer", icon='COPYDOWN', text="")
        col.operator("wm.m_paste_layer", icon='PASTEDOWN', text="")
        col.operator("layers.remove_active_layer", icon='TRASH', text="")

    def _draw_empty_state(self, context, main_col):
        """Draw the empty state UI when no layers exist.

        Args:
            context: Blender context
            main_col: Main column layout
        """
        main_col.separator(factor=2)

        # Info box
        info_box = main_col.box()
        info_col = info_box.column(align=True)
        info_col.scale_y = 1.2
        info_col.label(text="No layer based material", icon="INFO")
        info_col.label(text="Create one to start working with layers")

        main_col.separator(factor=1)

        # Create button
        create_row = main_col.row(align=True)
        create_row.scale_y = 2.0
        create_row.operator(
            "layers.create_material", text="Create Layer Based Material", icon="ADD"
        )

        # Poll check - only enabled for mesh objects
        obj = context.active_object
        is_valid_mesh = obj is not None and obj.type == "MESH"
        create_row.enabled = is_valid_mesh

        if not is_valid_mesh:
            main_col.separator(factor=0.5)
            warning_box = main_col.box()
            warning_box.label(
                text="Select a mesh object to create material", icon="ERROR"
            )


# Settings sub-panel
class LAYERS_PT_Settings(LAYERS_PT_Main, Panel):
    bl_label = "Settings"
    bl_idname = "LAYERS_PT_Settings"
    bl_options = set()  # Panel open by default

    def draw(self, context):
        """Draws the Settings panel UI.

        Displays channel and mask settings for the currently active layer.
        Syncs UI state before accessing backend layer data.

        Args:
            context (bpy.types.Context): The current Blender context.

        Returns:
            None
        """
        layout = self.layout
        wm = context.window_manager

        # Ensure UI is synced before drawing settings
        update_mixar_ui()

        # Check if mixar_ui exists
        if not hasattr(wm, 'mixar_ui'):
            layout.label(text="No layer selected", icon="INFO")
            return

        mixar_ui = wm.mixar_ui

        # Check if there's an active layer
        if len(mixar_ui.ui_layers) == 0:
            layout.label(text="No layer selected", icon="INFO")
            return

        if mixar_ui.active_layer_index < 0 or mixar_ui.active_layer_index >= len(mixar_ui.ui_layers):
            layout.label(text="No layer selected", icon="INFO")
            return

        # Get active layer from UI cache
        ui_layer = mixar_ui.ui_layers[mixar_ui.active_layer_index]

        # Get backend layer for settings (it has channels and masks)
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            layout.label(text="No active material", icon="INFO")
            return

        mat = obj.active_material
        # Find Mixar group node
        node = None
        for n in mat.node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                node = n
                break

        if not node:
            layout.label(text="No Mixar node found", icon="INFO")
            return

        tree = node.node_tree
        mp = tree.mp

        if ui_layer.mixar_layer_idx < 0 or ui_layer.mixar_layer_idx >= len(mp.layers):
            layout.label(text="Backend layer not found", icon="INFO")
            return

        # Get backend layer (YLayer) which has channels and masks
        backend_layer = mp.layers[ui_layer.mixar_layer_idx]

        # Check if we're editing a mask (Substance Painter-style sub-layer selection)
        if mixar_ui.editing_mask_index >= 0:
            if mixar_ui.editing_mask_index < len(backend_layer.masks):
                mask = backend_layer.masks[mixar_ui.editing_mask_index]

                # Draw "Back to Layer" button at top
                back_row = layout.row()
                back_row.scale_y = 1.3
                back_row.operator("layers.deselect_mask", text="Back to Layer", icon='BACK')
                layout.separator()

                # Draw full mask settings only
                draw_mask_settings(layout, mask, mixar_ui.editing_mask_index, backend_layer)
                return

        # Default: draw layer settings
        draw_layer_settings(context, layout, backend_layer)


# Bake section panel
class LAYERS_PT_Bake(LAYERS_PT_Main, Panel):
    bl_label = "Bake"
    bl_idname = "LAYERS_PT_Bake"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        """Draws the Bake panel UI.

        Displays sections for:
        - Baked Maps: Preview toggles for existing baked-to-layer maps
        - Bake Mesh Maps: Buttons to create new procedural bake layers (AO, Pointiness, etc.)

        Args:
            context (bpy.types.Context): The current Blender context.

        Returns:
            None
        """
        from ...core.node.node_utils import get_active_mpaint_node

        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        # Get active mpaint node
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            layout.label(text="No active Mixar node", icon='INFO')
            return

        mp = node.node_tree.mp
        wm = context.window_manager
        mixar_ui = wm.mixar_ui

        # ========== BAKED MAPS SECTION ==========
        draw_baked_maps_section(layout, mp, mixar_ui)

        # ========== BAKE OPERATIONS SECTION (commented in original) ==========
        draw_bake_operations_section(layout, mixar_ui)

        # ========== BAKE TO LAYER SECTION ==========
        box = draw_bake_to_layer_section(layout, mixar_ui)

        # ========== CLEANUP SECTION ==========
        draw_cleanup_section(layout, mixar_ui, box)


# Preferences sub-panel
class LAYERS_PT_Preferences(LAYERS_PT_Main, Panel):
    bl_label = "Preferences"
    bl_idname = "LAYERS_PT_Preferences"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        """Draws the Preferences panel UI.

        Displays user preferences organized in sections:
        - Image Settings: Default sizes and atlas configuration
        - UI Options: Preview modes and display preferences
        - Rendering Options: Bake device and rendering settings
        - Default Layer/Node Options: Layer creation defaults
        - Update Settings: Auto-update configuration
        - Developer Options: Debug and experimental features

        Args:
            context (bpy.types.Context): The current Blender context.

        Returns:
            None
        """
        layout = self.layout
        scene = context.scene
        prefs = scene.mixar_paint_preferences

        layout.use_property_split = True
        layout.use_property_decorate = False

        # ========== IMAGE SETTINGS ==========
        draw_image_settings(layout, prefs)

        layout.separator()

        # ========== UI OPTIONS ==========
        draw_ui_options(layout, prefs)

        layout.separator()

        # ========== RENDERING OPTIONS ==========
        draw_rendering_options(layout, prefs)

        layout.separator()

        # ========== DEFAULT LAYER/NODE OPTIONS ==========
        draw_layer_node_options(layout, prefs)

        layout.separator()

        # ========== UPDATE SETTINGS ==========
        draw_update_settings(layout, prefs)

        layout.separator()

        # ========== DEVELOPER OPTIONS ==========
        draw_developer_options(layout, prefs)

        layout.separator()

        # ========== DANGER ZONE ==========
        draw_danger_zone(layout)


# Channels panel
class LAYERS_PT_Channels(LAYERS_PT_Main, Panel):
    bl_label = "Channels"
    bl_idname = "LAYERS_PT_Channels"
    bl_parent_id = "LAYERS_PT_Layers"

    def draw(self, _context):
        """Draws the Channels panel UI.

        Currently a placeholder panel for future channel management functionality.
        Shows a message if no active Mixar node is found.

        Args:
            _context (bpy.types.Context): The current Blender context (unused).

        Returns:
            None
        """
        from ...core.node.node_utils import get_active_mpaint_node

        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        # Get active mpaint node
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            layout.label(text="No active Mixar node", icon='INFO')
            return

        # mp = node.node_tree.mp
        # draw_channels_content(layout, mp)


# Classes for registration
classes = (
    LAYERS_PT_Layers,
    LAYERS_PT_Settings,
    LAYERS_PT_Bake,
    # LAYERS_PT_Channels,
    LAYERS_PT_Preferences,
)
