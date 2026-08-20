# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
MPaint UI Base - Core UI property groups that must load first.

This module is in the properties/ folder to ensure it loads before other UI modules
that depend on the mpui property (due to bootstrap's priority loading order).

Contains all UI PropertyGroup classes that MPaintUI depends on, using lazy-import
wrappers for update callbacks to avoid circular dependencies at load time.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .....config.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lazy-import update callback wrappers
# ---------------------------------------------------------------------------

def _update_modifier_ui(self, context):
    from .update_callbacks import update_modifier_ui
    update_modifier_ui(self, context)


def _update_channel_ui(self, context):
    from .update_callbacks import update_channel_ui
    update_channel_ui(self, context)


def _update_noncontextual_channel_ui(self, context):
    from .update_callbacks import update_noncontextual_channel_ui
    update_noncontextual_channel_ui(self, context)


def _update_mask_channel_ui(self, context):
    from .update_callbacks import update_mask_channel_ui
    update_mask_channel_ui(self, context)


def _update_mask_ui(self, context):
    from .update_callbacks import update_mask_ui
    update_mask_ui(self, context)


def _update_layer_ui(self, context):
    from .update_callbacks import update_layer_ui
    update_layer_ui(self, context)


def _update_bake_target_ui(self, context):
    from .update_callbacks import update_bake_target_ui
    update_bake_target_ui(self, context)


# ---------------------------------------------------------------------------
# UI PropertyGroup classes (ordered by dependency)
# ---------------------------------------------------------------------------

class MModifierUI(bpy.types.PropertyGroup):
    expand_content: BoolProperty(default=True, update=_update_modifier_ui)


class MChannelUI(bpy.types.PropertyGroup):
    expand_content: BoolProperty(
        name="Channel Options", description="Expand channel options",
        default=False, update=_update_channel_ui,
    )
    expand_bump_settings: BoolProperty(
        name="Bump", description="Expand bump settings",
        default=False, update=_update_channel_ui,
    )
    expand_intensity_settings: BoolProperty(
        name="Intensity", description="Expand intensity settings",
        default=False, update=_update_channel_ui,
    )
    expand_base_vector: BoolProperty(
        name="Base Vector", description="Expand base vector options",
        default=True, update=_update_channel_ui,
    )
    expand_transition_bump_settings: BoolProperty(
        name="Transition Bump", description="Expand transition bump settings",
        default=True, update=_update_channel_ui,
    )
    expand_transition_ramp_settings: BoolProperty(
        name="Transition Ramp", description="Expand transition ramp settings",
        default=True, update=_update_channel_ui,
    )
    expand_transition_ao_settings: BoolProperty(
        name="Transition AO", description="Expand transition AO settings",
        default=True, update=_update_channel_ui,
    )
    expand_subdiv_settings: BoolProperty(
        name="Displacement Subdivision",
        description="Expand displacement subdivision settings",
        default=False, update=_update_channel_ui,
    )
    expand_parallax_settings: BoolProperty(
        name="Parallax", description="Expand parallax settings",
        default=False, update=_update_channel_ui,
    )
    expand_alpha_settings: BoolProperty(
        name="Channel Alpha", description="Expand alpha settings",
        default=False, update=_update_channel_ui,
    )
    expand_bake_to_vcol_settings: BoolProperty(
        name="Bake to Vertex Color",
        description="Expand bake to vertex color settings",
        default=False, update=_update_channel_ui,
    )
    expand_input_bump_settings: BoolProperty(
        name="Input Bump", description="Expand input bump settings",
        default=False, update=_update_channel_ui,
    )
    expand_smooth_bump_settings: BoolProperty(
        name="Smooth Bump", description="Expand smooth bump settings",
        default=False, update=_update_channel_ui,
    )
    expand_input_settings: BoolProperty(
        name="Input", description="Expand input settings",
        default=True, update=_update_channel_ui,
    )
    expand_blend_settings: BoolProperty(
        name="Blend", description="Expand blend settings",
        default=False, update=_update_channel_ui,
    )
    expand_source: BoolProperty(
        name="Channel Source", description="Expand channel source settings",
        default=True, update=_update_channel_ui,
    )
    expand_source_1: BoolProperty(
        name="Channel Normal Source",
        description="Expand channel normal source settings",
        default=True, update=_update_channel_ui,
    )
    expand_baked_data: BoolProperty(
        name="Baked Channel Data", description="Expand baked channel data",
        default=False, update=_update_noncontextual_channel_ui,
    )
    modifiers: CollectionProperty(type=MModifierUI)
    modifiers_1: CollectionProperty(type=MModifierUI)


class MMaskChannelUI(bpy.types.PropertyGroup):
    expand_content: BoolProperty(
        name="Mask Channel Options",
        description="Expand mask channel options",
        default=False, update=_update_mask_channel_ui,
    )


class MMaskUI(bpy.types.PropertyGroup):
    expand_content: BoolProperty(
        name="Mask Options", description="Expand mask options",
        default=True, update=_update_mask_ui,
    )
    expand_channels: BoolProperty(
        name="Mask Channel", description="Expand mask channels",
        default=True, update=_update_mask_ui,
    )
    expand_source: BoolProperty(
        name="Mask Source", description="Expand mask source options",
        default=True, update=_update_mask_ui,
    )
    expand_vector: BoolProperty(
        name="Mask Vector", description="Expand mask vector options",
        default=True, update=_update_mask_ui,
    )
    channels: CollectionProperty(type=MMaskChannelUI)
    modifiers: CollectionProperty(type=MModifierUI)


class MLayerUI(bpy.types.PropertyGroup):
    expand_content: BoolProperty(
        name="Layer Options", description="Expand layer options",
        default=False, update=_update_layer_ui,
    )
    expand_vector: BoolProperty(
        name="Layer Vector", description="Expand layer vector options",
        default=False, update=_update_layer_ui,
    )
    expand_masks: BoolProperty(
        name="Masks", description="Expand all masks",
        default=False, update=_update_layer_ui,
    )
    expand_source: BoolProperty(
        name="Layer Source", description="Expand layer source options",
        default=False, update=_update_layer_ui,
    )
    expand_channels: BoolProperty(
        name="Layer Channels", description="Expand layer channels",
        default=True, update=_update_layer_ui,
    )
    channels: CollectionProperty(type=MChannelUI)
    masks: CollectionProperty(type=MMaskUI)
    modifiers: CollectionProperty(type=MModifierUI)


class MBakeTargetUI(bpy.types.PropertyGroup):
    """UI expansion state for a single bake target."""
    expand_content: BoolProperty(
        name='Bake Target Options',
        description='Expand bake target options',
        default=True, update=_update_bake_target_ui,
    )
    expand_r: BoolProperty(
        name='R Channel',
        description='Expand bake target R channel options',
        default=False, update=_update_bake_target_ui,
    )
    expand_g: BoolProperty(
        name='G Channel',
        description='Expand bake target G channel options',
        default=False, update=_update_bake_target_ui,
    )
    expand_b: BoolProperty(
        name='B Channel',
        description='Expand bake target B channel options',
        default=False, update=_update_bake_target_ui,
    )
    expand_a: BoolProperty(
        name='A Channel',
        description='Expand bake target A channel options',
        default=False, update=_update_bake_target_ui,
    )


# ---------------------------------------------------------------------------
# Top-level UI property groups
# ---------------------------------------------------------------------------

class MMaterialUI(bpy.types.PropertyGroup):
    """UI state for material-level Mixar properties."""
    name: StringProperty(default='')
    active_mpaint_node: StringProperty(default='')


class MPaintUI(bpy.types.PropertyGroup):
    """Core UI state manager for Mixar paint system.

    This class stores UI expansion states, active indices, and other
    transient UI state that doesn't need to be saved with the file.
    """
    show_object: BoolProperty(
        name='Active Object', description='Show active object options',
        default=False,
    )
    show_materials: BoolProperty(
        name='Materials', description='Show material lists',
        default=False,
    )
    show_channels: BoolProperty(
        name='Channels', description='Show channel lists',
        default=True,
    )
    show_layers: BoolProperty(
        name='Layers', description='Show layer lists',
        default=True,
    )
    show_bake_targets: BoolProperty(
        name='Custom Bake Targets',
        description='Show custom bake target lists',
        default=False,
    )
    show_stats: BoolProperty(
        name='Stats', description='Show node stats',
        default=False,
    )
    show_test: BoolProperty(
        name='Tests', description='Show test sections',
        default=False,
    )
    show_support: BoolProperty(
        name='Support', description='Show support',
        default=False,
    )
    expand_channels: BoolProperty(
        name='Show Channel Toggle',
        description="Show layer channels toggle",
        default=False,
    )
    expand_mask_channels: BoolProperty(
        name='Expand all mask channels',
        description='Expand all mask channels',
        default=False,
    )

    # To store active node and tree
    tree_name: StringProperty(default='')

    # Layer related UI
    layer_idx: IntProperty(default=0)
    layer_ui: PointerProperty(type=MLayerUI)

    # Group channel related UI
    channel_idx: IntProperty(default=0)
    channel_ui: PointerProperty(type=MChannelUI)
    channels: CollectionProperty(type=MChannelUI)
    modifiers: CollectionProperty(type=MModifierUI)

    # Bake target related UI
    bake_target_idx: IntProperty(default=0)
    bake_target_ui: PointerProperty(type=MBakeTargetUI)

    # Update related
    need_update: BoolProperty(default=False)
    halt_prop_update: BoolProperty(default=False)

    # HACK: For some reason active float image will glitch after auto save
    # This prop will notify if float image is active after saving
    refresh_image_hack: BoolProperty(default=False)

    materials: CollectionProperty(type=MMaterialUI)
    active_mat: StringProperty(default='')
    active_mpaint_node: StringProperty(default='')

    hide_update: BoolProperty(default=False)


# Classes to register - order matters for dependencies
classes = [
    MModifierUI,
    MChannelUI,
    MMaskChannelUI,
    MMaskUI,
    MLayerUI,
    MBakeTargetUI,
    MMaterialUI,
    MPaintUI,
]


def register():
    """Register core UI property groups.

    This must run before any other UI modules that depend on mpui.
    """
    logger.debug("Registering MPaintUI base classes")

    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise

    # Register on both Scene and WindowManager for compatibility
    if not hasattr(bpy.types.Scene, 'mpui'):
        bpy.types.Scene.mpui = PointerProperty(type=MPaintUI)
    if not hasattr(bpy.types.WindowManager, 'mpui'):
        bpy.types.WindowManager.mpui = PointerProperty(type=MPaintUI)

    logger.info("MPaintUI base registered successfully")


def unregister():
    """Unregister core UI property groups."""
    logger.debug("Unregistering MPaintUI base classes")

    if hasattr(bpy.types.WindowManager, 'mpui'):
        del bpy.types.WindowManager.mpui
    if hasattr(bpy.types.Scene, 'mpui'):
        del bpy.types.Scene.mpui

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

    logger.info("MPaintUI base unregistered successfully")
