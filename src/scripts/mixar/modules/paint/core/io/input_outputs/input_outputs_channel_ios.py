# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel input/output creation helpers for layer tree IOs.

This module contains helper functions for creating channel inputs and outputs
in layer node trees, including normal channel displacement IOs and background inputs.
"""

import re

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.common import is_mask_using_vector
from ....utils.constants import (
    channel_socket_input_bl_idnames,
    channel_socket_output_bl_idnames,
    io_names,
    io_suffix,
    nsew_letters,
)
from ...element.check_processes import is_tangent_input_needed
from ...element.check_uv import is_uv_input_needed
from .inputs import create_input, get_tree_inputs, remove_tree_input
from .outputs import create_output, get_tree_outputs, remove_tree_output
from ...layer.check_layers import (
    get_mask_enabled,
    is_height_process_needed,
    is_layer_using_normal_map,
    is_layer_using_vector,
    is_vdisp_process_needed,
)
from ...layer.get_channels import get_channel_enabled
from ...node.node_utils import is_normal_height_input_connected
from ...subtree.get_subtree import has_channel_children


def _set_nested_attr(obj, prop_path, val, socket_type):
    """Safely set a nested attribute on an object using attribute navigation.

    This function safely navigates through a property path like 'channels[0].override_value'
    and sets the value on the target attribute, avoiding the security risks of exec().

    Args:
        obj: The root object to start navigation from.
        prop_path: Property path string like 'channels[0].override_value'.
        val: The value to set.
        socket_type: Socket type to determine value format.

    Raises:
        AttributeError: If an attribute in the path doesn't exist.
        IndexError: If an index in the path is out of range.
        ValueError: If the property path format is invalid.
    """
    import re

    # Split path into parts, handling both attribute access and indexing
    # e.g., 'channels[0].override_value' -> ['channels', '[0]', 'override_value']
    parts = re.split(r'\.(?![^\[]*\])', prop_path)

    # Navigate to the parent object
    current = obj
    for i, part in enumerate(parts[:-1]):
        # Check for array indexing
        match = re.match(r'(\w+)\[(\d+)\]', part)
        if match:
            attr_name = match.group(1)
            index = int(match.group(2))
            collection = getattr(current, attr_name)
            if index >= len(collection):
                raise IndexError(
                    f"Index {index} out of range for '{attr_name}' (length {len(collection)}) "
                    f"in path '{prop_path}'"
                )
            current = collection[index]
        else:
            current = getattr(current, part)

    # Get the final attribute name
    final_part = parts[-1]
    match = re.match(r'(\w+)\[(\d+)\]', final_part)

    if match:
        # The final part has indexing (e.g., 'values[0]')
        attr_name = match.group(1)
        index = int(match.group(2))
        target = getattr(current, attr_name)
        if index >= len(target):
            raise IndexError(
                f"Index {index} out of range for '{attr_name}' (length {len(target)}) "
                f"in path '{prop_path}'"
            )
        if socket_type in {'NodeSocketColor', 'RGBA'}:
            target[index] = (val[0], val[1], val[2])
        else:
            target[index] = val
    else:
        # Simple attribute assignment
        if socket_type in {'NodeSocketColor', 'RGBA'}:
            setattr(current, final_part, (val[0], val[1], val[2]))
        else:
            setattr(current, final_part, val)


def create_channel_ios(layer, mp, tree, valid_inputs, valid_outputs, input_index, output_index, dirty, layer_enabled, need_prev_normal, has_parent):
    """Create channel inputs and outputs.

    Args:
        layer: The layer object.
        mp: The material paint object.
        tree: The node tree.
        valid_inputs: List to track valid inputs.
        valid_outputs: List to track valid outputs.
        input_index: Current input index.
        output_index: Current output index.
        dirty: Current dirty state.
        layer_enabled: Whether layer is enabled.
        need_prev_normal: Whether previous normal is needed.
        has_parent: Whether layer has a parent.

    Returns:
        tuple: (input_index, output_index, dirty) - Updated values.
    """
    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        channel_enabled = get_channel_enabled(ch, layer, root_ch)

        force_normal_input = root_ch.type == 'NORMAL' and need_prev_normal and layer_enabled

        if channel_enabled or force_normal_input:
            dirty = create_input(tree, root_ch.name, channel_socket_input_bl_idnames[root_ch.type],
                    valid_inputs, input_index, dirty)
            input_index += 1

        if channel_enabled:
            dirty = create_output(tree, root_ch.name, channel_socket_output_bl_idnames[root_ch.type],
                    valid_outputs, output_index, dirty)
            output_index += 1

        # Alpha IO
        if root_ch.enable_alpha or has_parent:

            name = root_ch.name + io_suffix['ALPHA']

            if channel_enabled or force_normal_input:
                dirty = create_input(tree, name, 'NodeSocketFloatFactor', valid_inputs, input_index, dirty)
                input_index += 1

            if channel_enabled:
                dirty = create_output(tree, name, 'NodeSocketFloat', valid_outputs, output_index, dirty)
                output_index += 1

        # Displacement IO
        if root_ch.type == 'NORMAL':
            input_index, output_index, dirty = _create_normal_channel_ios(
                root_ch, tree, valid_inputs, valid_outputs, input_index, output_index, dirty,
                channel_enabled, force_normal_input, has_parent
            )

    return input_index, output_index, dirty


def _create_normal_channel_ios(root_ch, tree, valid_inputs, valid_outputs, input_index, output_index, dirty, channel_enabled, force_normal_input, has_parent):
    """Create inputs and outputs for normal channel displacement.

    Args:
        root_ch: The root channel object.
        tree: The node tree.
        valid_inputs: List to track valid inputs.
        valid_outputs: List to track valid outputs.
        input_index: Current input index.
        output_index: Current output index.
        dirty: Current dirty state.
        channel_enabled: Whether channel is enabled.
        force_normal_input: Whether to force normal input.
        has_parent: Whether layer has a parent.

    Returns:
        tuple: (input_index, output_index, dirty) - Updated values.
    """
    name = root_ch.name + io_suffix['HEIGHT']

    if channel_enabled or force_normal_input:
        dirty = create_input(tree, name, 'NodeSocketFloatFactor', valid_inputs, input_index, dirty)
        input_index += 1

    if channel_enabled:
        dirty = create_output(tree, name, 'NodeSocketFloat', valid_outputs, output_index, dirty)
        output_index += 1

    if root_ch.enable_smooth_bump:

        for letter in nsew_letters:

            name = root_ch.name + ' Height ' + letter.upper()

            if channel_enabled or force_normal_input:
                dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
                input_index += 1

            if channel_enabled:
                dirty = create_output(tree, name, 'NodeSocketFloat', valid_outputs, output_index, dirty)
                output_index += 1

    if has_parent or (is_normal_height_input_connected(root_ch) and root_ch.enable_smooth_bump):

        name = root_ch.name + io_suffix['HEIGHT'] + io_suffix['ALPHA']

        if channel_enabled or force_normal_input:
            dirty = create_input(tree, name, 'NodeSocketFloatFactor', valid_inputs, input_index, dirty)
            input_index += 1

        if channel_enabled:
            dirty = create_output(tree, name, 'NodeSocketFloat', valid_outputs, output_index, dirty)
            output_index += 1

        if root_ch.enable_smooth_bump:

            for letter in nsew_letters:
                name = root_ch.name + ' Height ' + letter.upper() + io_suffix['ALPHA']

                if channel_enabled or force_normal_input:
                    dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
                    input_index += 1

                if channel_enabled:
                    dirty = create_output(tree, name, 'NodeSocketFloat', valid_outputs, output_index, dirty)
                    output_index += 1

    name = root_ch.name + io_suffix['MAX_HEIGHT']

    if channel_enabled or force_normal_input:

        dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
        input_index += 1

    if channel_enabled:
        dirty = create_output(tree, name, 'NodeSocketFloat', valid_outputs, output_index, dirty)
        output_index += 1

    name = root_ch.name + io_suffix['VDISP']

    if channel_enabled or force_normal_input:

        dirty = create_input(tree, name, 'NodeSocketVector', valid_inputs, input_index, dirty)
        input_index += 1

    if channel_enabled:
        dirty = create_output(tree, name, 'NodeSocketVector', valid_outputs, output_index, dirty)
        output_index += 1

    if has_parent:
        name = root_ch.name + io_suffix['VDISP'] + io_suffix['ALPHA']

        if channel_enabled:

            dirty = create_input(tree, name, 'NodeSocketFloatFactor', valid_inputs, input_index, dirty)
            input_index += 1

        if channel_enabled:
            dirty = create_output(tree, name, 'NodeSocketFloat', valid_outputs, output_index, dirty)
            output_index += 1

    return input_index, output_index, dirty


def create_background_inputs(layer, mp, tree, valid_inputs, input_index, dirty):
    """Create background inputs for BACKGROUND and GROUP layer types.

    Args:
        layer: The layer object.
        mp: The material paint object.
        tree: The node tree.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        channel_enabled = get_channel_enabled(ch, layer, root_ch)

        if not channel_enabled: continue

        root_ch = mp.channels[i]

        # For GROUP layers, create GROUP inputs when children have this channel enabled
        # For BACKGROUND layers, create BACKGROUND inputs for non-NORMAL channels
        # For NORMAL channel on GROUP, also check is_layer_using_normal_map for the main normal input
        should_create_channel_input = (
            root_ch.type != 'NORMAL' or
            (layer.type == 'GROUP' and (
                is_layer_using_normal_map(layer, root_ch) or
                has_channel_children(layer, root_ch)
            ))
        )

        if should_create_channel_input:
            name = root_ch.name + io_suffix[layer.type]
            dirty = create_input(
                tree, name, channel_socket_input_bl_idnames[root_ch.type],
                valid_inputs, input_index, dirty
            )
            input_index += 1

            # Alpha Input
            if root_ch.enable_alpha or layer.type == 'GROUP':

                name = root_ch.name + io_suffix['ALPHA'] + io_suffix[layer.type]
                dirty = create_input(
                    tree, name, 'NodeSocketFloatFactor',
                    valid_inputs, input_index, dirty
                )
                input_index += 1

        # Displacement Input
        if root_ch.type == 'NORMAL' and layer.type == 'GROUP':
            input_index, dirty = _create_group_displacement_inputs(layer, root_ch, tree, valid_inputs, input_index, dirty)

    return input_index, dirty


def _create_group_displacement_inputs(layer, root_ch, tree, valid_inputs, input_index, dirty):
    """Create displacement inputs for GROUP layer type.

    Args:
        layer: The layer object.
        root_ch: The root channel object.
        tree: The node tree.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    if is_height_process_needed(layer):

        name = root_ch.name + io_suffix['HEIGHT'] + io_suffix['GROUP']
        dirty = create_input(tree, name, 'NodeSocketFloat',
                valid_inputs, input_index, dirty)
        input_index += 1

        if root_ch.enable_smooth_bump:

            for letter in nsew_letters:
                name = root_ch.name + io_suffix['HEIGHT_' + letter.upper()] + io_suffix['GROUP']
                dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
                input_index += 1

        name = root_ch.name + io_suffix['HEIGHT'] + io_suffix['ALPHA'] + io_suffix['GROUP']
        dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
        input_index += 1

        if root_ch.enable_smooth_bump:

            for letter in nsew_letters:
                name = root_ch.name + io_suffix['HEIGHT_' + letter.upper()] + io_suffix['ALPHA'] + io_suffix['GROUP']
                dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
                input_index += 1

        name = root_ch.name + io_suffix['MAX_HEIGHT'] + io_suffix['GROUP']
        dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
        input_index += 1

    if is_vdisp_process_needed(layer):

        name = root_ch.name + io_suffix['VDISP'] + io_suffix['GROUP']
        dirty = create_input(tree, name, 'NodeSocketVector',
                valid_inputs, input_index, dirty)
        input_index += 1

        name = root_ch.name + io_suffix['VDISP'] + io_suffix['ALPHA'] + io_suffix['GROUP']
        dirty = create_input(tree, name, 'NodeSocketFloat', valid_inputs, input_index, dirty)
        input_index += 1

    return input_index, dirty


def create_uv_and_texcoord_inputs(layer, mp, tree, valid_inputs, input_index, dirty, layer_enabled):
    """Create UV and texcoord inputs.

    Args:
        layer: The layer object.
        mp: The material paint object.
        tree: The node tree.
        valid_inputs: List to track valid inputs.
        input_index: Current input index.
        dirty: Current dirty state.
        layer_enabled: Whether layer is enabled.

    Returns:
        tuple: (input_index, dirty) - Updated values.
    """
    # Create UV inputs
    for uv in mp.uvs:
        if is_uv_input_needed(layer, uv.name):
            name = uv.name + io_suffix['UV']
            dirty = create_input(tree, name, 'NodeSocketVector', valid_inputs, input_index, dirty)
            input_index += 1

        if is_tangent_input_needed(layer, uv.name):

            name = uv.name + io_suffix['TANGENT']
            dirty = create_input(tree, name, 'NodeSocketVector', valid_inputs, input_index, dirty)
            input_index += 1

            name = uv.name + io_suffix['BITANGENT']
            dirty = create_input(tree, name, 'NodeSocketVector', valid_inputs, input_index, dirty)
            input_index += 1

    # Other than uv texcoord name container
    texcoords = []

    # Check layer texcoords
    if layer_enabled and layer.texcoord_type not in {'UV', 'Decal'} and is_layer_using_vector(layer):
        texcoords.append(layer.texcoord_type)

    for mask in layer.masks:
        if get_mask_enabled(mask, layer) and mask.texcoord_type not in {'UV', 'Decal', 'Layer'} and mask.type not in {'VCOL', 'COLOR_ID', 'OBJECT_INDEX', 'HEMI'} and mask.texcoord_type not in texcoords:
            texcoords.append(mask.texcoord_type)

    for texcoord in texcoords:
        name = io_names[texcoord]
        dirty = create_input(tree, name, 'NodeSocketVector', valid_inputs, input_index, dirty)
        input_index += 1

    return input_index, dirty


def cleanup_invalid_ios(layer, tree, layer_node, valid_inputs, valid_outputs):
    """Remove invalid inputs and outputs from the tree.

    Args:
        layer: The layer object.
        tree: The node tree.
        layer_node: The layer's group node.
        valid_inputs: List of valid inputs to keep.
        valid_outputs: List of valid outputs to keep.
    """
    # Deleting invalid inputs
    for i, inp in enumerate(get_tree_inputs(tree)):
        if inp not in valid_inputs:
            # Set input prop before deleting input socket
            if inp.name.startswith('.'):
                # Validate channel index before saving - skip if index is out of range
                # Input names like '.channels[4].override_value' may reference removed channels
                match = re.search(r'\.channels\[(\d+)\]', inp.name)
                if match:
                    channel_idx = int(match.group(1))
                    if channel_idx >= len(layer.channels):
                        # Channel was removed, skip saving value and just remove the input
                        remove_tree_input(tree, inp)
                        continue

                # Set value back to prop using safe attribute access
                val = layer_node.inputs.get(inp.name).default_value
                socket_type = inp.socket_type

                # Parse the property path to get the attribute chain
                # inp.name is like '.channels[0].override_value'
                try:
                    prop_path = inp.name.lstrip('.')
                    # Navigate to the target object and set the value safely
                    _set_nested_attr(layer, prop_path, val, socket_type)
                except (AttributeError, IndexError, ValueError) as e:
                    # Expected errors from invalid paths or removed channels
                    logger.warning(
                        "Could not save layer input '%s' (type: %s, value: %s): %s",
                        inp.name, socket_type, val, e
                    )
                except Exception as e:
                    # Unexpected error - log at error level with stack trace
                    logger.error(
                        "Unexpected error setting layer input '%s': %s",
                        inp.name, e, exc_info=True
                    )

            # Remove input socket
            remove_tree_input(tree, inp)

    # Deleting invalid outputs
    for outp in get_tree_outputs(tree):
        if outp not in valid_outputs:
            remove_tree_output(tree, outp)
