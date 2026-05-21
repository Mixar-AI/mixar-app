# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer projection callback functions.

This module contains callbacks for:
- Layer projection type changes
- Projection hardness
- Projection axis
- UV extension
- Channel source transform
- Layer projection checking utilities
"""

import re

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.io.input_outputs.input_outputs import check_layer_tree_ios
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.mappings import update_mapping
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes
from ....core.node.get_nodes import get_channel_source, get_channel_source_1, get_layer_source
from ....core.subtree.get_subtree import get_tree


def check_layer_projections(layer):
    """Check and update projection types for layer image sources.

    Args:
        layer: YLayer object to check projections for.
    """
    # Delayed import to avoid circular dependency
    from .layer_uv_callbacks import check_layer_projection_blends

    # Set image source projection
    if layer.type == "IMAGE":
        source = get_layer_source(layer)
        source.projection = (
            "BOX" if layer.texcoord_type in {"Generated", "Object"} else "FLAT"
        )

    # Set channel override images
    for ch in layer.channels:
        if ch.override and ch.override_type == "IMAGE":
            source = get_channel_source(ch, layer)
            source.projection = (
                "BOX" if layer.texcoord_type in {"Generated", "Object"} else "FLAT"
            )

        if ch.override_1 and ch.override_1_type == "IMAGE":
            source = get_channel_source_1(ch, layer)
            source.projection = (
                "BOX" if layer.texcoord_type in {"Generated", "Object"} else "FLAT"
            )

    # Check projection blends
    check_layer_projection_blends(layer)


def recheck_background_layers_ios(mp, index_dict):
    """Recheck and update background layer IOs after layer reordering.

    Args:
        mp: MPaint data structure.
        index_dict (dict): Dictionary mapping layer names to previous indices.
    """
    for i, layer in enumerate(mp.layers):
        if layer.type != "BACKGROUND":
            continue
        if index_dict[layer.name] != i or len(mp.layers) != len(index_dict):
            check_all_layer_channel_io_and_nodes(layer, do_recursive=False)
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)


def update_layer_projection(self, context):
    """Update callback for layer projection type changes.

    Args:
        self: The property being updated (MLayer/YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    tree = get_tree(layer)
    logger.debug(f"Layer projection type changed to: {layer.projection_type}")

    # Map our projection_type to Blender's Image Texture projection values
    projection_map = {
        'UV': 'FLAT',
        'TRIPLANAR': 'BOX',
        'PLANAR': 'FLAT',
        'SPHERICAL': 'SPHERE',
        'CYLINDRICAL': 'TUBE',
        'DECAL': 'FLAT',
    }

    # Update texcoord_type based on projection type
    if layer.projection_type == 'UV':
        if layer.texcoord_type not in {'UV'}:
            mp.halt_update = True
            layer.texcoord_type = 'UV'
            mp.halt_update = False
    elif layer.projection_type == 'DECAL':
        if layer.texcoord_type != 'Decal':
            mp.halt_update = True
            layer.texcoord_type = 'Decal'
            mp.halt_update = False
    elif layer.projection_type in {'TRIPLANAR', 'SPHERICAL', 'CYLINDRICAL', 'PLANAR'}:
        if layer.texcoord_type not in {'Object', 'Generated'}:
            mp.halt_update = True
            layer.texcoord_type = 'Object'
            mp.halt_update = False

    # Update image source projection if applicable
    if layer.type in {'IMAGE', 'COLOR'}:
        source = get_layer_source(layer, tree)
        if source and hasattr(source, 'projection'):
            source.projection = projection_map.get(layer.projection_type, 'FLAT')

            if layer.projection_type == 'TRIPLANAR' and hasattr(source, 'projection_blend'):
                source.projection_blend = layer.projection_hardness

    # Rebuild layer nodes
    check_all_layer_channel_io_and_nodes(layer)

    # Reconnect and rearrange nodes
    check_layer_tree_ios(layer, tree)
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(layer.id_data)
    rearrange_mp_nodes(layer.id_data)


def update_projection_hardness(self, context):
    """Update callback for projection hardness (triplanar blend sharpness) changes.

    Args:
        self: The property being updated (MLayer/YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self

    if layer.projection_type != 'TRIPLANAR':
        return

    tree = get_tree(layer)
    source = get_layer_source(layer, tree)

    if source and hasattr(source, 'projection_blend'):
        source.projection_blend = layer.projection_hardness
        logger.debug(f"Projection hardness updated to: {layer.projection_hardness}")


def update_projection_axis(self, context):
    """Update callback for projection axis changes (PLANAR/CYLINDRICAL).

    Args:
        self: The property being updated (MLayer/YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self

    if layer.projection_type not in {'PLANAR', 'CYLINDRICAL'}:
        return

    update_mapping(layer)
    logger.debug(f"Projection axis updated to: {layer.projection_axis}")


def update_uv_extension(self, context):
    """Update callback for UV extension/wrap mode changes.

    Args:
        self: The property being updated (MLayer/YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    tree = get_tree(layer)
    source = get_layer_source(layer, tree)

    if source and hasattr(source, 'extension'):
        source.extension = layer.uv_extension
        logger.debug(f"UV extension updated to: {layer.uv_extension}")


def update_channel_source_transform(self, context):
    """Update callback for channel override source transform changes.

    Args:
        self: The property being updated (MLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    ch = self

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", ch.path_from_id())
    if not m:
        return

    layer_idx = int(m.group(1))
    if layer_idx >= len(mp.layers):
        return
    layer = mp.layers[layer_idx]

    tree = get_tree(layer)
    if not tree:
        return

    mapping = tree.nodes.get(ch.source_mapping)
    if not mapping:
        logger.debug(f"No mapping node found for channel source transform")
        return

    if ch.source_uniform_scale_enabled:
        scale = (ch.source_uniform_scale_value,) * 3
    else:
        scale = ch.source_scale[:]

    old_rot = tuple(mapping.inputs[2].default_value)
    new_rot = tuple(ch.source_rotation[:])

    mapping.inputs[1].default_value = ch.source_translation[:]
    mapping.inputs[2].default_value = new_rot
    mapping.inputs[3].default_value = scale

    actual_rot = tuple(mapping.inputs[2].default_value)
    logger.debug(f"Channel source mapping update: old_rot={old_rot}, new_rot={new_rot}, actual_rot={actual_rot}")
    logger.debug(f"  trans={ch.source_translation[:]} scale={scale}")
