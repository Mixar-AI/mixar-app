# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property input creation helpers for layer tree IOs.

This module contains helper functions for creating property inputs
for layers, channels, and masks in layer node trees.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.common import is_mask_using_vector
from ...layer.check_layers import is_layer_using_vector
from ...layer.get_channels import get_channel_enabled
from .input_outputs_props import create_prop_input


def create_layer_prop_inputs(layer, mp, valid_inputs, input_index, dirty, layer_enabled, trans_bump_ch):
    """Create property inputs for layer-level properties.

    Args:
        layer: The layer object.
        mp: The material paint object.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.
        layer_enabled: Whether the layer is enabled.
        trans_bump_ch: Transition bump channel if any.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    dirty = create_prop_input(layer, 'intensity_value', valid_inputs, input_index, dirty)
    input_index += 1

    # Layer prop inputs
    if layer.enable_blur_vector:
        dirty = create_prop_input(layer, 'blur_vector_factor', valid_inputs, input_index, dirty)
        input_index += 1

    if layer.texcoord_type == 'Decal':
        dirty = create_prop_input(layer, 'decal_distance_value', valid_inputs, input_index, dirty)
        input_index += 1

    if layer.enable_uniform_scale and is_layer_using_vector(layer) and layer.segment_name == '':
        dirty = create_prop_input(layer, 'uniform_scale_value', valid_inputs, input_index, dirty)
        input_index += 1

    # Edge Detect
    if layer.type == 'EDGE_DETECT':
        dirty = create_prop_input(layer, 'edge_detect_radius', valid_inputs, input_index, dirty)
        input_index += 1

    # AO
    elif layer.type == 'AO':
        dirty = create_prop_input(layer, 'ao_distance', valid_inputs, input_index, dirty)
        input_index += 1

    return input_index, dirty


def create_channel_prop_inputs(layer, mp, valid_inputs, input_index, dirty, trans_bump_ch):
    """Create property inputs for channel-level properties.

    Args:
        layer: The layer object.
        mp: The material paint object.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.
        trans_bump_ch: Transition bump channel if any.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    for i, ch in enumerate(layer.channels):
        if not get_channel_enabled(ch): continue

        root_ch = mp.channels[i]

        # Create intensity socket
        dirty = create_prop_input(ch, 'intensity_value', valid_inputs, input_index, dirty)
        input_index += 1

        # Create override inputs for OVERRIDE type (slider/color values)
        # Also handle legacy DEFAULT type for backward compatibility
        if ch.override_type in ('DEFAULT', 'OVERRIDE'):
            if root_ch.type == 'VALUE':
                # Create override_value input for VALUE channels (Metallic, Roughness)
                dirty = create_prop_input(ch, 'override_value', valid_inputs, input_index, dirty)
                input_index += 1
            else:
                # Create override_color input for RGB channels (Color)
                dirty = create_prop_input(ch, 'override_color', valid_inputs, input_index, dirty)
                input_index += 1

        if root_ch.type == 'NORMAL':
            input_index, dirty = _create_normal_channel_inputs(ch, layer, root_ch, valid_inputs, input_index, dirty)
        elif trans_bump_ch:
            input_index, dirty = _create_trans_bump_channel_inputs(ch, valid_inputs, input_index, dirty)

        if ch.enable_transition_ramp:
            dirty = create_prop_input(ch, 'transition_ramp_intensity_value', valid_inputs, input_index, dirty)
            input_index += 1

        if ch.enable_transition_ao:
            dirty = create_prop_input(ch, 'transition_ao_intensity', valid_inputs, input_index, dirty)
            input_index += 1

            dirty = create_prop_input(ch, 'transition_ao_power', valid_inputs, input_index, dirty)
            input_index += 1

            dirty = create_prop_input(ch, 'transition_ao_color', valid_inputs, input_index, dirty)
            input_index += 1

            dirty = create_prop_input(ch, 'transition_ao_inside_intensity', valid_inputs, input_index, dirty)
            input_index += 1

    return input_index, dirty


def _create_normal_channel_inputs(ch, layer, root_ch, valid_inputs, input_index, dirty):
    """Create property inputs for normal channel properties.

    Args:
        ch: The channel object.
        layer: The layer object.
        root_ch: The root channel object.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    if layer.type != 'GROUP':

        # Height/bump distance input
        if ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
            dirty = create_prop_input(ch, 'bump_distance', valid_inputs, input_index, dirty)
            input_index += 1

        # Height/bump midlevel input
        if ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
            dirty = create_prop_input(ch, 'bump_midlevel', valid_inputs, input_index, dirty)
            input_index += 1

        # Normal map strength input
        if ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
            dirty = create_prop_input(ch, 'normal_strength', valid_inputs, input_index, dirty)
            input_index += 1
        elif ch.normal_map_type == 'VECTOR_DISPLACEMENT_MAP':
            dirty = create_prop_input(ch, 'vdisp_strength', valid_inputs, input_index, dirty)
            input_index += 1

        # Smooth bump multiplier input:
        if root_ch.enable_smooth_bump:
            if ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
                dirty = create_prop_input(ch, 'bump_smooth_multiplier', valid_inputs, input_index, dirty)
                input_index += 1

    # Transition bump inputs
    if ch.enable_transition_bump:
        dirty = create_prop_input(ch, 'transition_bump_distance', valid_inputs, input_index, dirty)
        input_index += 1

        dirty = create_prop_input(ch, 'transition_bump_value', valid_inputs, input_index, dirty)
        input_index += 1

        dirty = create_prop_input(ch, 'transition_bump_second_edge_value', valid_inputs, input_index, dirty)
        input_index += 1

        # Transition bump crease factor input
        if ch.transition_bump_crease and not ch.transition_bump_flip:
            dirty = create_prop_input(ch, 'transition_bump_crease_factor', valid_inputs, input_index, dirty)
            input_index += 1

            dirty = create_prop_input(ch, 'transition_bump_crease_power', valid_inputs, input_index, dirty)
            input_index += 1

        if ch.transition_bump_falloff and ch.transition_bump_falloff_type == 'EMULATED_CURVE':
            dirty = create_prop_input(ch, 'transition_bump_falloff_emulated_curve_fac', valid_inputs, input_index, dirty)
            input_index += 1

    return input_index, dirty


def _create_trans_bump_channel_inputs(ch, valid_inputs, input_index, dirty):
    """Create property inputs for transition bump channel properties.

    Args:
        ch: The channel object.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    dirty = create_prop_input(ch, 'transition_bump_fac', valid_inputs, input_index, dirty)
    input_index += 1

    if ch.enable_transition_ramp:
        dirty = create_prop_input(ch, 'transition_bump_second_fac', valid_inputs, input_index, dirty)
        input_index += 1

    return input_index, dirty


def create_mask_prop_inputs(layer, valid_inputs, input_index, dirty):
    """Create property inputs for mask-level properties.

    Args:
        layer: The layer object.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    for mask in layer.masks:
        if not mask.enable: continue

        # Create intensity socket
        dirty = create_prop_input(mask, 'intensity_value', valid_inputs, input_index, dirty)
        input_index += 1

        if mask.enable_uniform_scale and is_mask_using_vector(mask) and mask.segment_name == '':
            dirty = create_prop_input(mask, 'uniform_scale_value', valid_inputs, input_index, dirty)
            input_index += 1

        # Mask blur vector
        if mask.enable_blur_vector:
            dirty = create_prop_input(mask, 'blur_vector_factor', valid_inputs, input_index, dirty)
            input_index += 1

        # Mask decal distance
        if mask.texcoord_type == 'Decal':
            dirty = create_prop_input(mask, 'decal_distance_value', valid_inputs, input_index, dirty)
            input_index += 1

        # Color ID
        if mask.type == 'COLOR_ID':
            dirty = create_prop_input(mask, 'color_id', valid_inputs, input_index, dirty)
            input_index += 1

        # Edge Detect
        elif mask.type == 'EDGE_DETECT':
            dirty = create_prop_input(mask, 'edge_detect_radius', valid_inputs, input_index, dirty)
            input_index += 1

        # AO
        elif mask.type == 'AO':
            dirty = create_prop_input(mask, 'ao_distance', valid_inputs, input_index, dirty)
            input_index += 1

    return input_index, dirty
