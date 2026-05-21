# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint UI property groups for Mixar.

This module contains the legacy MPaintUI and MMaterialUI property groups
for managing paint-related UI state in Blender.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .properties.ui_properties import (
    MBakeTargetUI,
    MChannelUI,
    MLayerUI,
    MModifierUI,
)


class MMaterialUI(bpy.types.PropertyGroup):
    """UI property group for material settings.

    Stores material name and active mpaint node reference.
    """
    name: StringProperty(default='')
    active_mpaint_node: StringProperty(default='')


class MPaintUI(bpy.types.PropertyGroup):
    """Main paint UI property group.

    Stores UI expansion states, layer/channel indices, and material references
    for the paint module interface.
    """
    show_object: BoolProperty(
        name='Active Object',
        description='Show active object options',
        default=False
    )

    show_materials: BoolProperty(
        name='Materials',
        description='Show material lists',
        default=False
    )

    show_channels: BoolProperty(
        name='Channels',
        description='Show channel lists',
        default=True
    )

    show_layers: BoolProperty(
        name='Layers',
        description='Show layer lists',
        default=True
    )

    show_bake_targets: BoolProperty(
        name='Custom Bake Targets',
        description='Show custom bake target lists',
        default=False
    )

    show_stats: BoolProperty(
        name='Stats',
        description='Show node stats',
        default=False
    )

    show_test: BoolProperty(
        name='Tests',
        description='Show test sections',
        default=False
    )

    show_support: BoolProperty(
        name='Support',
        description='Show support',
        default=False
    )

    expand_channels: BoolProperty(
        name='Show Channel Toggle',
        description="Show layer channels toggle",
        default=False
    )

    expand_mask_channels: BoolProperty(
        name='Expand all mask channels',
        description='Expand all mask channels',
        default=False
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
