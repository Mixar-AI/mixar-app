# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer tree input/output management functions.

This module handles checking and updating all inputs and outputs for layer node trees,
including property inputs, channel inputs/outputs, UV inputs, texcoord inputs, and
viewer outputs.
"""

import re

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.constants import LAYER_ALPHA_VIEWER, LAYER_VIEWER
from .inputs import get_tree_inputs, remove_tree_input
from .outputs import create_output
from ...layer.check_layers import check_need_prev_normal, get_layer_enabled
from ...layer.layer_utils import get_layer_index, get_transition_bump_channel
from ...subtree.get_subtree import get_tree
from .input_outputs_channel_ios import (
    cleanup_invalid_ios,
    create_background_inputs,
    create_channel_ios,
    create_uv_and_texcoord_inputs,
)
from .input_outputs_layer_props import (
    create_channel_prop_inputs,
    create_layer_prop_inputs,
    create_mask_prop_inputs,
)


def check_layer_tree_ios(layer, tree=None, remove_props=False, hard_reset=False):
    """Check and update all inputs and outputs for a layer's node tree.

    This function manages the complete input/output configuration for a layer's node tree,
    including property inputs, channel inputs/outputs, UV inputs, texcoord inputs, and
    viewer outputs. It creates, updates, or removes sockets based on the layer's current
    state and configuration.

    Args:
        layer: The layer object to check and update inputs/outputs for.
        tree (optional): The node tree to modify. If None, retrieves it from the layer.
            Defaults to None.
        remove_props (bool, optional): If True, skips creating property inputs.
            Defaults to False.
        hard_reset (bool, optional): If True, removes all inputs before recreating them.
            Defaults to False.

    Returns:
        bool: True if any changes were made to the tree, False otherwise.
    """

    mp = layer.id_data.mp
    if not tree: tree = get_tree(layer)
    root_tree = layer.id_data
    layer_node = root_tree.nodes.get(layer.group_node)

    # Remove all inputs first if hard reset is True
    if hard_reset:
        for inp in reversed(get_tree_inputs(tree)):
            remove_tree_input(tree, inp)

    dirty = False

    input_index = 0
    output_index = 0
    valid_inputs = []
    valid_outputs = []

    has_parent = layer.parent_idx != -1
    need_prev_normal = check_need_prev_normal(layer)

    layer_enabled = get_layer_enabled(layer)

    trans_bump_ch = get_transition_bump_channel(layer)

    # Rename fcurve and driver data path before rearranging the inputs
    if root_tree.animation_data:
        # Example: nodes["Group.003"].inputs[9].default_value'

        if root_tree.animation_data.action:
            for fc in root_tree.animation_data.action.fcurves:
                m = re.match(r'^nodes\["' + layer_node.name + r'"\]\.inputs\[(\d+)\]\.default_value$', fc.data_path)
                if m:
                    inp = layer_node.inputs[int(m.group(1))]
                    fc.data_path = 'mp.layers[' + str(get_layer_index(layer)) + ']' + inp.name

        for driver in root_tree.animation_data.drivers:
            m = re.match(r'^nodes\["' + layer_node.name + r'"\]\.inputs\[(\d+)\]\.default_value$', driver.data_path)
            if m:
                inp = layer_node.inputs[int(m.group(1))]
                driver.data_path = 'mp.layers[' + str(get_layer_index(layer)) + ']' + inp.name

    # Prop inputs
    if not remove_props and layer_enabled:
        # Layer prop inputs
        input_index, dirty = create_layer_prop_inputs(layer, mp, valid_inputs, input_index, dirty, layer_enabled, trans_bump_ch)

        # Channel prop inputs
        input_index, dirty = create_channel_prop_inputs(layer, mp, valid_inputs, input_index, dirty, trans_bump_ch)

        # Mask prop inputs
        input_index, dirty = create_mask_prop_inputs(layer, valid_inputs, input_index, dirty)

    # Tree input and outputs for channels
    input_index, output_index, dirty = create_channel_ios(
        layer, mp, tree, valid_inputs, valid_outputs, input_index, output_index, dirty,
        layer_enabled, need_prev_normal, has_parent
    )

    # Tree background inputs
    if layer.type in {'BACKGROUND', 'GROUP'}:
        input_index, dirty = create_background_inputs(layer, mp, tree, valid_inputs, input_index, dirty)

    # Create UV and texcoord inputs
    input_index, dirty = create_uv_and_texcoord_inputs(layer, mp, tree, valid_inputs, input_index, dirty, layer_enabled)

    # Viewer outputs
    if mp.layer_preview_mode:
        dirty = create_output(tree, LAYER_VIEWER, 'NodeSocketColor', valid_outputs, output_index, dirty)
        output_index += 1

        dirty = create_output(tree, LAYER_ALPHA_VIEWER, 'NodeSocketColor', valid_outputs, output_index, dirty)
        output_index += 1

    # Cleanup invalid IOs
    cleanup_invalid_ios(layer, tree, layer_node, valid_inputs, valid_outputs)

    return dirty
