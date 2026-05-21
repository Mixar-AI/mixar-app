# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI Property groups for the paint module.

This module defines PropertyGroup classes that manage UI state such as
expansion states for various panels and sections.
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty

# Import all update callbacks for use in PropertyGroup definitions
from .update_callbacks import (
    update_layer_ui,
    update_channel_ui,
    update_modifier_ui,
    update_noncontextual_channel_ui,
    update_mask_ui,
    update_bake_target_ui,
    update_mask_channel_ui,
)

# Re-export all update callbacks for backward compatibility
__all__ = [
    # Update callbacks
    "update_layer_ui",
    "update_channel_ui",
    "update_modifier_ui",
    "update_noncontextual_channel_ui",
    "update_mask_ui",
    "update_bake_target_ui",
    "update_mask_channel_ui",
    # PropertyGroup classes
    "MModifierUI",
    "MChannelUI",
    "MMaskChannelUI",
    "MMaskUI",
    "MLayerUI",
    "MBakeTargetUI",
]


class MModifierUI(bpy.types.PropertyGroup):
    # name : StringProperty(default='')
    expand_content: BoolProperty(default=True, update=update_modifier_ui)


class MChannelUI(bpy.types.PropertyGroup):
    # name : StringProperty(default='')
    expand_content: BoolProperty(
        name="Channel Options",
        description="Expand channel options",
        default=False,
        update=update_channel_ui,
    )

    expand_bump_settings: BoolProperty(
        name="Bump",
        description="Expand bump settings",
        default=False,
        update=update_channel_ui,
    )

    expand_intensity_settings: BoolProperty(
        name="Intensity",
        description="Expand intensity settings",
        default=False,
        update=update_channel_ui,
    )

    expand_base_vector: BoolProperty(
        name="Base Vector",
        description="Expand base vector options",
        default=True,
        update=update_channel_ui,
    )

    expand_transition_bump_settings: BoolProperty(
        name="Transition Bump",
        description="Expand transition bump settings",
        default=True,
        update=update_channel_ui,
    )

    expand_transition_ramp_settings: BoolProperty(
        name="Transition Ramp",
        description="Expand transition ramp settings",
        default=True,
        update=update_channel_ui,
    )

    expand_transition_ao_settings: BoolProperty(
        name="Transition AO",
        description="Expand transition AO settings",
        default=True,
        update=update_channel_ui,
    )

    expand_subdiv_settings: BoolProperty(
        name="Displacement Subdivision",
        description="Expand displacement subdivision settings",
        default=False,
        update=update_channel_ui,
    )

    expand_parallax_settings: BoolProperty(
        name="Parallax",
        description="Expand parallax settings",
        default=False,
        update=update_channel_ui,
    )

    expand_alpha_settings: BoolProperty(
        name="Channel Alpha",
        description="Expand alpha settings",
        default=False,
        update=update_channel_ui,
    )

    expand_bake_to_vcol_settings: BoolProperty(
        name="Bake to Vertex Color",
        description="Expand bake to vertex color settings",
        default=False,
        update=update_channel_ui,
    )

    expand_input_bump_settings: BoolProperty(
        name="Input Bump",
        description="Expand input bump settings",
        default=False,
        update=update_channel_ui,
    )

    expand_smooth_bump_settings: BoolProperty(
        name="Smooth Bump",
        description="Expand smooth bump settings",
        default=False,
        update=update_channel_ui,
    )

    expand_input_settings: BoolProperty(
        name="Input",
        description="Expand input settings",
        default=True,
        update=update_channel_ui,
    )

    expand_blend_settings: BoolProperty(
        name="Blend",
        description="Expand blend settings",
        default=False,
        update=update_channel_ui,
    )

    expand_source: BoolProperty(
        name="Channel Source",
        description="Expand channel source settings",
        default=True,
        update=update_channel_ui,
    )

    expand_source_1: BoolProperty(
        name="Channel Normal Source",
        description="Expand channel normal source settings",
        default=True,
        update=update_channel_ui,
    )

    expand_baked_data: BoolProperty(
        name="Baked Channel Data",
        description="Expand baked channel data",
        default=False,
        update=update_noncontextual_channel_ui,
    )

    modifiers: CollectionProperty(type=MModifierUI)
    modifiers_1: CollectionProperty(type=MModifierUI)


class MMaskChannelUI(bpy.types.PropertyGroup):
    expand_content: BoolProperty(
        name="Mask Channel Options",
        description="Expand mask channel options",
        default=False,
        update=update_mask_channel_ui,
    )


class MMaskUI(bpy.types.PropertyGroup):
    # name : StringProperty(default='')
    expand_content: BoolProperty(
        name="Mask Options",
        description="Expand mask options",
        default=True,
        update=update_mask_ui,
    )

    expand_channels: BoolProperty(
        name="Mask Channel",
        description="Expand mask channels",
        default=True,
        update=update_mask_ui,
    )

    expand_source: BoolProperty(
        name="Mask Source",
        description="Expand mask source options",
        default=True,
        update=update_mask_ui,
    )

    expand_vector: BoolProperty(
        name="Mask Vector",
        description="Expand mask vector options",
        default=True,
        update=update_mask_ui,
    )

    channels: CollectionProperty(type=MMaskChannelUI)
    modifiers: CollectionProperty(type=MModifierUI)


class MLayerUI(bpy.types.PropertyGroup):
    # name : StringProperty(default='')

    expand_content: BoolProperty(
        name="Layer Options",
        description="Expand layer options",
        default=False,
        update=update_layer_ui,
    )

    expand_vector: BoolProperty(
        name="Layer Vector",
        description="Expand layer vector options",
        default=False,
        update=update_layer_ui,
    )

    expand_masks: BoolProperty(
        name="Masks",
        description="Expand all masks",
        default=False,
        update=update_layer_ui,
    )

    expand_source: BoolProperty(
        name="Layer Source",
        description="Expand layer source options",
        default=False,
        update=update_layer_ui,
    )

    expand_channels: BoolProperty(
        name="Layer Channels",
        description="Expand layer channels",
        default=True,
        update=update_layer_ui,
    )

    channels: CollectionProperty(type=MChannelUI)
    masks: CollectionProperty(type=MMaskUI)
    modifiers: CollectionProperty(type=MModifierUI)


class MBakeTargetUI(bpy.types.PropertyGroup):
    expand_content: BoolProperty(
        name='Bake Target Options',
        description='Expand bake target options',
        default=True,
        update=update_bake_target_ui
    )

    expand_r: BoolProperty(
        name='R Channel',
        description='Expand bake target R channel options',
        default=False,
        update=update_bake_target_ui
    )

    expand_g: BoolProperty(
        name='G Channel',
        description='Expand bake target R channel options',
        default=False,
        update=update_bake_target_ui
    )

    expand_b: BoolProperty(
        name='B Channel',
        description='Expand bake target B channel options',
        default=False,
        update=update_bake_target_ui
    )

    expand_a: BoolProperty(
        name='A Channel',
        description='Expand bake target A channel options',
        default=False,
        update=update_bake_target_ui
    )
