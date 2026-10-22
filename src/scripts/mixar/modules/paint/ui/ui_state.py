# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modern UI state manager for Mixar layers system.

This module contains the MixarUIState and MixarUILayer property groups
for managing modern Mixar UI components, replacing the legacy mpui pattern.
"""

import json

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from .channel_filter import get_channel_filter_items


def update_brush_value(self, context):
    """Update callback to sync brush_value slider with brush color (grayscale).

    When the brush_value property changes, this sets the brush color to a grayscale
    value (R=G=B=value) so that VALUE channels (Metallic, Roughness) paint correctly.

    Args:
        self: MixarUIState instance.
        context: Blender context.
    """
    if not context.tool_settings or not context.tool_settings.image_paint:
        return

    image_paint = context.tool_settings.image_paint
    brush = image_paint.brush
    if not brush:
        return

    # Get unified paint settings
    ups = image_paint.unified_paint_settings
    value = self.brush_value

    # Set brush color to grayscale (R=G=B=value)
    if ups.use_unified_color:
        ups.color = (value, value, value)
    else:
        brush.color = (value, value, value)

    # Also save to per-channel storage
    try:
        values = json.loads(self.channel_brush_values) if self.channel_brush_values else {}
    except json.JSONDecodeError:
        values = {}
    values[self.active_channel_filter] = value
    self.channel_brush_values = json.dumps(values)


def update_active_channel_filter(self, context):
    """Save current brush_value and load value for new channel.

    When the channel filter selection changes, this callback:
    1. Saves the current brush_value for the previous channel
    2. Loads the stored brush_value for the newly selected channel

    Args:
        self: MixarUIState instance.
        context: Blender context.
    """
    try:
        values = json.loads(self.channel_brush_values) if self.channel_brush_values else {}
    except json.JSONDecodeError:
        values = {}

    old_channel = self.prev_channel_filter
    new_channel = self.active_channel_filter

    # Save current value to old channel
    if old_channel and old_channel != new_channel:
        values[old_channel] = self.brush_value

    # Load value for new channel (default 1.0)
    self.brush_value = values.get(new_channel, 1.0)

    # Store and track
    self.channel_brush_values = json.dumps(values)
    self.prev_channel_filter = new_channel


class MixarUILayer(bpy.types.PropertyGroup):
    """UI representation of a layer (stored in WindowManager for Properties panel compatibility)."""
    # Copy of essential properties from MixarLayer for read-only display
    name: StringProperty(name="Layer Name", default="Layer")
    layer_type: StringProperty(name="Layer Type", default="FILL")
    visible: BoolProperty(name="Visible", default=True)
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0)
    blend_mode: StringProperty(name="Blend Mode", default="MIX")
    mixar_layer_idx: IntProperty(name="Backend Index", default=-1)

    # Color tag for organization (tiny color picker in layer list)
    layer_color: bpy.props.FloatVectorProperty(
        name="Layer Color Tag",
        description="Color tag for layer organization",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.8, 0.8, 0.8, 1.0)
    )

    # Multi-selection for layer group operations
    selected: BoolProperty(
        name="Selected for Group",
        description="Select layer for batch operations (move to group, etc.)",
        default=False
    )


def _get_brush_model_items(self, context):
    """Dynamic enum callback for brush generation models.

    Sources the generation catalog's ``brush_gen`` service (surface
    "paint"); falls back to hardcoded flash/pro (offline / pre-auth).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_model_enum_items,
            is_loaded,
        )
        if is_loaded():
            items = get_model_enum_items("brush_gen")
            if items:
                return items
    except Exception:
        pass
    return [("flash", "Flash", "Fast generation"), ("pro", "Pro", "Higher quality")]


class MixarUIState(bpy.types.PropertyGroup):
    """Modern UI state manager for Mixar layers system.

    Stores UI expansion states, context tracking, and refresh control flags.
    This replaces the legacy mpui pattern for new Mixar UI components.
    Pattern based on Mixar Paint's MPaintUI but modernized for Mixar.

    IMPORTANT: Stores layers collection here (not in Scene) for Properties panel compatibility.
    Properties panels have read-only Scene context during draw, but WindowManager is always writable.
    """

    # Panel expansion states
    expand_layers: BoolProperty(
        name='Expand Layers',
        description='Show layers panel expanded',
        default=True
    )

    expand_channels: BoolProperty(
        name='Expand Channels',
        description='Show channel settings expanded',
        default=True
    )

    expand_masks: BoolProperty(
        name='Expand Masks',
        description='Show mask settings expanded',
        default=True
    )

    expand_source: BoolProperty(
        name='Expand Properties',
        description='Show layer properties/source expanded',
        default=False
    )

    expand_content: BoolProperty(
        name='Expand Content',
        description='Show layer content settings expanded',
        default=True
    )

    expand_vector: BoolProperty(
        name='Expand Vector',
        description='Show vector/transform settings expanded',
        default=False
    )

    expand_transform: BoolProperty(
        name='Expand Transform',
        description='Show coordinate and transform settings expanded',
        default=True
    )

    expand_blending: BoolProperty(
        name='Expand Blending',
        description='Show blending settings expanded',
        default=True
    )

    expand_preferences: BoolProperty(
        name='Expand Preferences',
        description='Show preferences panel expanded',
        default=False
    )

    # Bake panel expansion states
    expand_baked_maps: BoolProperty(
        name='Expand Baked Maps',
        description='Show baked maps section expanded',
        default=True
    )

    expand_bake_operations: BoolProperty(
        name='Expand Bake Operations',
        description='Show bake operations section expanded',
        default=False
    )

    expand_bake_to_layer: BoolProperty(
        name='Expand Bake to Layer',
        description='Show bake to layer section expanded',
        default=True
    )

    expand_cleanup: BoolProperty(
        name='Expand Cleanup',
        description='Show cleanup section expanded',
        default=False
    )

    # Context tracking - used to detect state changes
    active_material_name: StringProperty(
        name='Active Material Name',
        description='Cached name of active material for change detection',
        default=''
    )

    active_tree_name: StringProperty(
        name='Active Tree Name',
        description='Cached name of active node tree for change detection',
        default=''
    )

    active_layer_index: IntProperty(
        name='Active Layer Index',
        description='Cached active layer index for change detection',
        default=0
    )

    editing_mask_index: IntProperty(
        name='Editing Mask Index',
        description='Index of mask being edited in Properties panel (-1 = show layer settings)',
        default=-1
    )

    # Refresh control flags - Mixar Paint pattern
    needs_ui_refresh: BoolProperty(
        name='Needs UI Refresh',
        description='Flag to request UI rebuild on next draw cycle',
        default=False
    )

    halt_prop_update: BoolProperty(
        name='Halt Property Update',
        description='Prevents property update callbacks during UI rebuild (prevents circular updates)',
        default=False
    )

    # UI layers collection (writable even in Properties panels)
    # This mirrors scene.mixar_layers for display purposes
    ui_layers: CollectionProperty(type=MixarUILayer)

    # Channel filter for Substance 3D Painter-style layer display
    # Controls which channel's blend mode and opacity are shown inline
    active_channel_filter: EnumProperty(
        name='Channel',
        description='Channel context for layer blend mode and opacity display',
        items=get_channel_filter_items,
        update=update_active_channel_filter,
    )

    # Brush value for VALUE channels (Metallic, Roughness)
    # Syncs with brush color as grayscale (R=G=B=value)
    brush_value: FloatProperty(
        name='Brush Value',
        description='Brush grayscale value for VALUE channels (synced with brush color)',
        min=0.0,
        max=1.0,
        default=1.0,
        subtype='FACTOR',
        update=update_brush_value,
    )

    # Brush luminance - calculated from brush color for display
    # Read-only, updated dynamically in UI draw code
    brush_luminance: FloatProperty(
        name='Luminance',
        description='Luminance value calculated from brush color',
        min=0.0,
        max=1.0,
        default=1.0,
        subtype='FACTOR',
    )

    # Per-channel brush value persistence
    # Stores brush values as JSON so each channel remembers its setting
    channel_brush_values: StringProperty(
        name='Channel Brush Values',
        description='JSON-serialized per-channel brush values',
        default='{}',
    )

    prev_channel_filter: StringProperty(
        name='Previous Channel Filter',
        description='Tracks previous channel for brush value persistence',
        default='',
    )

    # Brush panel expansion states (for Paint Layer brush properties)
    expand_brush_settings: BoolProperty(name='Expand Brush Settings', default=True)
    expand_color_picker: BoolProperty(name='Expand Color Picker', default=True)
    expand_color_palette: BoolProperty(name='Expand Color Palette', default=False)
    expand_procedural_params: BoolProperty(name='Expand Parameters', default=True)
    expand_brush_advanced: BoolProperty(name='Expand Advanced', default=False)
    expand_brush_texture: BoolProperty(name='Expand Texture', default=False)
    expand_brush_texture_mask: BoolProperty(name='Expand Texture Mask', default=False)
    expand_brush_stroke: BoolProperty(name='Expand Stroke', default=False)
    expand_brush_falloff: BoolProperty(name='Expand Falloff', default=False)
    expand_brush_cursor: BoolProperty(name='Expand Cursor', default=False)
    expand_brush_symmetry: BoolProperty(name='Expand Symmetry', default=True)
    expand_brush_options: BoolProperty(name='Expand Options', default=True)

    # ========== BAKING SPACE TABS ==========
    baking_panel_tab: EnumProperty(
        name='Baking Panel Tab',
        description='Active tab in the baking panel',
        items=[
            ('MESH_BAKING', 'Mesh Baking', 'Bake mesh maps (AO, Cavity, etc.)'),
            ('ASSETS', 'Assets', 'Procedural materials and assets'),
            ('TEXTURE_EXPORT', 'Texture Export', 'Bake and export texture channels'),
            ('ASSET_EXPORT', 'Asset Export', 'Bake textures and export mesh'),
        ],
        default='MESH_BAKING'
    )

    # ========== MATERIAL LIBRARY (ASSETS TAB) ==========
    material_library_search: StringProperty(
        name='Search Materials',
        description='Filter materials by name',
        default=''
    )

    material_library_category: StringProperty(
        name='Material Category',
        description='Currently selected material category',
        default='ALL'
    )

    # ========== TEXTURE SETS SPACE TABS ==========
    texture_sets_tab: EnumProperty(
        name='Texture Sets Tab',
        description='Active tab in the Texture Sets panel',
        items=[
            ('TEXTURE_SETS', 'Texture Sets', 'Material slots and texture set management'),
            ('CHANNEL_SETTINGS', 'Channel Settings', 'Channel configuration for the project'),
        ],
        default='TEXTURE_SETS'
    )

    # ========== MAIN TABS (CHANNELS/BRUSH) ==========
    main_panel_tab: EnumProperty(
        name='Main Panel Tab',
        description='Active tab in the main panel',
        items=[
            ('CHANNELS', 'Channels', 'Channel master settings'),
            ('BRUSH', 'Brush', 'Brush settings'),
        ],
        default='CHANNELS'
    )

    # ========== MASK PANEL TABS ==========
    mask_panel_tab: EnumProperty(
        name='Mask Panel Tab',
        description='Active tab when editing a mask',
        items=[
            ('MASK', 'Mask Settings', 'Mask properties and settings'),
            ('BRUSH', 'Brush', 'Brush settings for mask painting'),
        ],
        default='MASK'
    )

    # ========== BRUSH SUBTABS ==========
    brush_subtab: EnumProperty(
        name='Brush Subtab',
        description='Active subtab in the brush panel',
        items=[
            ('TOOL', 'Tool', 'General brush tool settings'),
            ('ALPHA', 'Alpha', 'Alpha/texture settings'),
            ('FALLOFF', 'Falloff', 'Brush falloff and cursor settings'),
        ],
        default='TOOL'
    )

    # Alpha subtab expand states
    expand_alpha_advanced: BoolProperty(
        name='Expand Alpha Advanced',
        description='Show advanced alpha settings',
        default=False
    )

    # Falloff subtab expand states
    expand_falloff_curve: BoolProperty(
        name='Expand Curve',
        description='Show curve preset section expanded',
        default=True
    )

    expand_falloff_normal: BoolProperty(
        name='Expand Normal Falloff',
        description='Show normal falloff section expanded',
        default=True
    )

    expand_falloff_cursor: BoolProperty(
        name='Expand Cursor Display',
        description='Show cursor display settings expanded',
        default=True
    )

    expand_falloff_overlay: BoolProperty(
        name='Expand Overlay',
        description='Show overlay opacity settings expanded',
        default=False
    )

    # ========== BRUSH TEXTURE GENERATION ==========
    brush_texture_prompt: StringProperty(
        name='Brush Texture Prompt',
        description='Enter a description for the brush texture you want to generate',
        default='',
        maxlen=1024,
    )

    brush_gen_in_progress: BoolProperty(
        name='Brush Generation In Progress',
        description='Whether brush texture generation is currently running',
        default=False
    )

    brush_gen_progress: FloatProperty(
        name='Brush Generation Progress',
        description='Current progress of brush texture generation (0.0 to 1.0)',
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )

    brush_gen_status: StringProperty(
        name='Brush Generation Status',
        description='Current status message for brush texture generation',
        default=''
    )

    brush_gen_model: EnumProperty(
        name='Model', description='AI model for brush generation',
        items=_get_brush_model_items,
    )
    brush_gen_ref_image: StringProperty(
        name='Reference Image', description='Reference image in bpy.data.images',
        default='',
    )

    # Asset export settings are in MAssetExportSettings (wm.mixar_asset_export)
