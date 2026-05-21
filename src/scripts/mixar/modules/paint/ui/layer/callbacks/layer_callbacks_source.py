# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer source callback functions.

This module contains callbacks for:
- Layer source type changes
- Layer color shortcuts
- Layer baked image settings
"""

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.io.input_outputs.input_outputs import check_layer_tree_ios
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_channels import check_start_end_root_ch_nodes
from ....core.layer.layer_utils import get_layer_index
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.node.create_nodes import new_node
from ....core.node.get_nodes import get_layer_source
from ....core.subtree.get_subtree import get_tree


def update_layer_color_chortcut(self, context):
    """Update callback for layer color shortcut changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    layer = self
    mp = layer.id_data.mp
    if mp.halt_update:
        return

    # If color shortcut is active, disable other shortcut
    if layer.type == "COLOR" and layer.color_shortcut:

        for m in layer.modifiers:
            m.shortcut = False

        for ch in layer.channels:
            for m in ch.modifiers:
                m.shortcut = False


def update_layer_use_baked(self, context):
    """Update callback for layer use baked image setting.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    mp = self.id_data.mp
    tree = get_tree(layer)

    # Update global uv
    check_uv_nodes(mp)

    # Update layer tree inputs
    check_all_layer_channel_io_and_nodes(layer)
    check_start_end_root_ch_nodes(self.id_data)

    # Refresh active image by setting active layer
    if get_layer_index(layer) == mp.active_layer_index:
        mp.active_layer_index = mp.active_layer_index

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)


def update_layer_source_type(self, context):
    """Update callback for layer source type changes (Solid Color/Image/Material).

    This callback is triggered when the user changes the source_type property
    of a Fill layer. Replaces the source node with the appropriate type:
    - SOLID_COLOR: ShaderNodeRGB
    - IMAGE: ShaderNodeTexImage
    - MATERIAL: ShaderNodeGroup (placeholder until material is selected)

    Args:
        self: The property being updated (MLayer/YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    logger.debug(f"Layer source type changed to: {layer.source_type}")

    # Only for Fill layers
    if layer.type != 'COLOR':
        return

    tree = get_tree(layer)
    if not tree:
        logger.warning("Could not get layer tree for source type change")
        return

    # Get current source node
    old_source = get_layer_source(layer, tree)
    old_location = old_source.location.copy() if old_source else (0, 0)

    # Determine new node type based on source_type
    node_type_map = {
        'SOLID_COLOR': 'ShaderNodeRGB',
        'IMAGE': 'ShaderNodeTexImage',
        'MATERIAL': 'ShaderNodeRGB',  # Placeholder until material is selected
    }
    new_node_type = node_type_map.get(layer.source_type, 'ShaderNodeRGB')

    # Check if we need to replace the node (different type)
    if old_source and old_source.bl_idname == new_node_type:
        logger.debug(f"Source node already correct type: {new_node_type}")
        return

    # Remove old source first to avoid reference issues
    if old_source:
        logger.debug(f"Removing old source node: {old_source.name} ({old_source.bl_idname})")
        tree.nodes.remove(old_source)
        layer.source = ""

    # Create new source node
    new_source = new_node(tree, layer, 'source', new_node_type, label='Source')
    if new_source:
        new_source.location = old_location

        # Configure new node based on type
        if layer.source_type == 'SOLID_COLOR':
            new_source.outputs[0].default_value = (0.5, 0.5, 0.5, 1.0)
        elif layer.source_type == 'IMAGE':
            new_source.interpolation = 'Linear'
            new_source.extension = layer.uv_extension if hasattr(layer, 'uv_extension') else 'REPEAT'
            projection_map = {
                'UV': 'FLAT',
                'TRIPLANAR': 'BOX',
                'PLANAR': 'FLAT',
                'SPHERICAL': 'SPHERE',
                'CYLINDRICAL': 'TUBE',
            }
            new_source.projection = projection_map.get(layer.projection_type, 'FLAT')
            if layer.projection_type == 'TRIPLANAR':
                new_source.projection_blend = layer.projection_hardness

        logger.debug(f"Created new source node: {new_source.name} ({new_node_type})")

    # Update channel enable states based on source type
    for i in range(len(mp.channels)):
        if i < len(layer.channels):
            root_ch = mp.channels[i]
            if layer.source_type == 'SOLID_COLOR':
                layer.channels[i].enable = (root_ch.type == 'RGB')
            else:
                layer.channels[i].enable = True

    # Reconnect and rearrange nodes
    check_layer_tree_ios(layer, tree)
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)
