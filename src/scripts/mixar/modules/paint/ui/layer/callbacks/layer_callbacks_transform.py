# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer transform callback functions.

This module contains callbacks for:
- Layer transform (translation, rotation, scale)
- Layer blur vector effects
- Layer uniform scale
- Layer edge detection
"""

from ....core.io.input_outputs.input_outputs import check_layer_tree_ios
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes
from ....core.layer.mappings import update_mapping
from ....core.lib.lib import BLUR_VECTOR
from ....core.node.create_nodes import new_node
from ....core.node.get_nodes import get_layer_source
from ....core.node.node_utils import get_node_tree_lib, remove_node
from ....core.node.update_nodes import update_entity_uniform_scale_enabled
from ....core.subtree.get_subtree import get_tree


def update_layer_transform(self, context):
    """Update callback for layer transform (translation, rotation, scale) changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    update_mapping(self)


def update_layer_blur_vector(self, context):
    """Update callback for layer blur vector enable/disable.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    tree = get_tree(layer)

    if layer.enable_blur_vector:
        blur_vector = new_node(
            tree, layer, "blur_vector", "ShaderNodeGroup", "Blur Vector"
        )
        blur_vector.node_tree = get_node_tree_lib(BLUR_VECTOR)
        blur_vector.inputs[0].default_value = layer.blur_vector_factor
    else:
        remove_node(tree, layer, "blur_vector")

    check_layer_tree_ios(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)


def update_layer_blur_vector_factor(self, context):
    """Update callback for layer blur vector factor value changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    tree = get_tree(layer)

    blur_vector = tree.nodes.get(layer.blur_vector)

    if blur_vector:
        blur_vector.inputs[0].default_value = layer.blur_vector_factor


def update_layer_uniform_scale_enabled(self, context):
    """Update callback for layer uniform scale enable/disable.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    update_entity_uniform_scale_enabled(layer)

    check_layer_tree_ios(layer)
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)


def update_layer_edge_detect_radius(self, context):
    """Update callback for edge detection radius changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    layer = self

    source = get_layer_source(layer)
    if source:
        source.inputs[0].default_value = self.edge_detect_radius
