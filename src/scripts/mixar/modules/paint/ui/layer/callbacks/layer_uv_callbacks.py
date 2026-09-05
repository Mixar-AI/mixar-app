# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer channel property callback functions for UV, projection, and override operations.

This module contains callbacks for UV name changes, projection blends, texcoord type,
and override color/value changes.
"""

import re

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.element.check_elements import check_uvmap_on_other_objects_with_same_mat
from ....core.element.update_uv import refresh_temp_uv, set_uv_neighbor_resolution
from ....core.io.input_outputs.input_outputs import check_layer_tree_ios
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_layers import is_layer_vdm
from ....core.layer.layer_utils import (
    get_height_channel,
    get_smooth_bump_channel,
    get_uv_layers,
)
from ....core.lib.lib_operations import get_neighbor_uv_tree_name
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.node.create_nodes import replace_new_node
from ....core.node.get_nodes import (
    get_channel_source,
    get_channel_source_1,
    get_layer_source,
)
from ....core.subtree.check_subtree import check_mask_uv_neighbor
from ....core.subtree.get_subtree import get_tree
from ....utils.blender_commons import get_active_material, get_active_object
from ....utils.constants import TEMP_UV


def update_uv_name(self, context):
    """Update callback for layer UV map name changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    obj = get_active_object()
    mat = get_active_material(obj)
    group_tree = self.id_data
    mp = group_tree.mp
    if mp.halt_update:
        return

    wm = context.window_manager
    if not hasattr(wm, 'mpui'):
        return
    mpui = wm.mpui
    layer = self
    active_layer = mp.layers[mp.active_layer_index]
    tree = get_tree(layer)
    if not tree:
        return

    nodes = tree.nodes

    # Use first uv if temp uv or empty is selected
    if layer.uv_name in {TEMP_UV, ""}:
        if len(mp.uvs) > 0:
            for uv in mp.uvs:
                layer.uv_name = uv.name
                break

    # Update uv layer
    if (
        obj.type == "MESH"
        and not any([m for m in layer.masks if m.active_edit])
        and layer == active_layer
    ):

        if layer.segment_name != "":
            refresh_temp_uv(obj, layer)
        else:
            uv_layers = get_uv_layers(obj)
            uv_layers.active = uv_layers.get(layer.uv_name)

            if is_layer_vdm(layer):
                uv_layers.active.active_render = True

        # Check for other objects with same material
        check_uvmap_on_other_objects_with_same_mat(mat, layer.uv_name)

    # Update global uv
    check_uv_nodes(mp)

    # Update uv neighbor
    smooth_bump_ch = get_smooth_bump_channel(layer)
    if (
        smooth_bump_ch
        and smooth_bump_ch.enable
        and (
            smooth_bump_ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}
            or smooth_bump_ch.enable_transition_bump
        )
    ):
        uv_neighbor = replace_new_node(
            tree,
            layer,
            "uv_neighbor",
            "ShaderNodeGroup",
            "Neighbor UV",
            get_neighbor_uv_tree_name(layer.texcoord_type, entity=layer),
            return_status=False,
            hard_replace=True,
        )
        set_uv_neighbor_resolution(layer, uv_neighbor)
        if smooth_bump_ch.override and smooth_bump_ch.override_type != "DEFAULT":
            uv_neighbor = replace_new_node(
                tree,
                smooth_bump_ch,
                "uv_neighbor",
                "ShaderNodeGroup",
                "Neighbor UV",
                get_neighbor_uv_tree_name(layer.texcoord_type, entity=layer),
                return_status=False,
                hard_replace=True,
            )
            set_uv_neighbor_resolution(smooth_bump_ch, uv_neighbor)

        # Update neighbor uv if mask bump is active
        for i, mask in enumerate(layer.masks):
            check_mask_uv_neighbor(tree, layer, mask, i)

    # Update normal process uv
    normal_ch = get_height_channel(layer)
    if normal_ch:
        normal_proc = nodes.get(normal_ch.normal_proc)
        if hasattr(normal_proc, "uv_map"):
            normal_proc.uv_map = layer.uv_name

    # Update layer tree inputs
    check_layer_tree_ios(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)


def check_layer_projection_blends(layer):
    """Check and update projection blend settings for layer sources.

    Args:
        layer: YLayer object to check projection blends for.
    """

    if layer.type == "IMAGE":
        source = get_layer_source(layer)
        if hasattr(source, "projection_blend"):
            source.projection_blend = layer.projection_blend

    for ch in layer.channels:
        if ch.override and ch.override_type == "IMAGE":
            source = get_channel_source(ch, layer)
            if hasattr(source, "projection_blend"):
                source.projection_blend = layer.projection_blend

        if ch.override_1 and ch.override_1_type == "IMAGE":
            source = get_channel_source_1(ch, layer)
            if hasattr(source, "projection_blend"):
                source.projection_blend = layer.projection_blend


def update_projection_blend(self, context):
    """Update callback for projection blend value changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    check_layer_projection_blends(self)


def update_texcoord_type(self, context):
    """Update callback for layer texture coordinate type changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """

    # Delayed import to avoid circular dependency
    from .layer_state_callbacks import check_layer_projections

    mp = self.id_data.mp
    layer = self
    tree = get_tree(layer)


    if mp.halt_update:
        return

    # Update global uv
    check_uv_nodes(mp)

    # Update uv neighbor
    smooth_bump_ch = get_smooth_bump_channel(layer)
    if (
        smooth_bump_ch
        and smooth_bump_ch.enable
        and (
            smooth_bump_ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}
            or smooth_bump_ch.enable_transition_bump
        )
    ):
        uv_neighbor = replace_new_node(
            tree,
            layer,
            "uv_neighbor",
            "ShaderNodeGroup",
            "Neighbor UV",
            get_neighbor_uv_tree_name(layer.texcoord_type, entity=layer),
            hard_replace=True,
        )
        set_uv_neighbor_resolution(layer, uv_neighbor)
        if smooth_bump_ch.override and smooth_bump_ch.override_type != "DEFAULT":
            uv_neighbor = replace_new_node(
                tree,
                smooth_bump_ch,
                "uv_neighbor",
                "ShaderNodeGroup",
                "Neighbor UV",
                get_neighbor_uv_tree_name(layer.texcoord_type, entity=layer),
                hard_replace=True,
            )
            set_uv_neighbor_resolution(smooth_bump_ch, uv_neighbor)

    # Update layer tree inputs
    check_all_layer_channel_io_and_nodes(layer, tree)

    # Check layer projections
    check_layer_projections(layer)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)


def update_override_color_value(self, context):
    """Update callback for channel override color/value changes.

    Updates the source node's default value when override_color or override_value
    changes. This enables real-time material updates when editing metallic,
    roughness, or other channel values.

    Also auto-enables ch.override when the value is changed (for non-COLOR layers),
    since the override value only takes effect when override is True.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    from ....utils.common import get_entity_input_name

    mp = self.id_data.mp
    if mp.halt_update:
        return

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return

    layer_idx = int(m.group(1))
    ch_idx = int(m.group(2))
    layer = mp.layers[layer_idx]
    root_ch = mp.channels[ch_idx]
    ch = self
    root_tree = self.id_data

    # Invalidate cached layer thumbnails so color/value edits show up
    # (root_tree is the material node tree; its name matches the
    # material_name key used when the list draws thumbnails)
    from ...utils.thumbnail_generator import invalidate_layer_thumbnail
    invalidate_layer_thumbnail(layer.name, root_tree.name)

    tree = get_tree(layer)
    if not tree:
        return

    # Note: Auto-enable of override removed - user now has explicit toggle in UI
    # Override is enabled by default for VALUE/NORMAL channels in paint layers
    # (set in layer_create_helpers.py)

    # For OVERRIDE type (and legacy DEFAULT), the value is stored in the layer node's input socket
    # Socket is created when override_type in ('DEFAULT', 'OVERRIDE')
    if ch.override_type in ('DEFAULT', 'OVERRIDE'):
        layer_node = root_tree.nodes.get(layer.group_node)
        if layer_node:
            if root_ch.type == 'VALUE':
                input_name = get_entity_input_name(ch, 'override_value')
                inp = layer_node.inputs.get(input_name)
                if inp:
                    inp.default_value = ch.override_value
                    logger.debug(
                        "update_override_color_value: Updated layer input %s to %s",
                        input_name, ch.override_value
                    )
                    return
            else:
                input_name = get_entity_input_name(ch, 'override_color')
                inp = layer_node.inputs.get(input_name)
                if inp:
                    rgba = tuple(ch.override_color) + (1.0,)
                    inp.default_value = rgba
                    logger.debug(
                        "update_override_color_value: Updated layer input %s to %s",
                        input_name, ch.override_color[:]
                    )
                    return

    # Get the channel source node (for non-DEFAULT override types)
    source = tree.nodes.get(ch.source) if ch.source else None

    # Update the source node's default value based on channel type
    if source and hasattr(source, 'outputs') and len(source.outputs) > 0:
        if root_ch.type == 'VALUE':
            # For VALUE channels (Metallic, Roughness, etc.)
            # Check source node type to avoid setting float on RGBA output
            if source.bl_idname == 'ShaderNodeValue':
                if hasattr(source.outputs[0], 'default_value'):
                    source.outputs[0].default_value = ch.override_value
            elif source.bl_idname == 'ShaderNodeRGB':
                # Source is RGB node - need to trigger reconnection to create VALUE node
                logger.warning(
                    "VALUE channel %s has RGB source, triggering reconnection",
                    root_ch.name
                )
                reconnect_layer_nodes(layer, ch_idx)
                reconnect_mp_nodes(self.id_data)
                return
            else:
                logger.warning(
                    "VALUE channel %s has unexpected source type: %s",
                    root_ch.name, source.bl_idname
                )
        else:
            # For RGB channels
            if hasattr(source.outputs[0], 'default_value'):
                # Ensure we have RGBA format
                rgba = list(ch.override_color) + [1.0]
                source.outputs[0].default_value = rgba
        logger.debug(
            "update_override_color_value: Updated channel %s source to %s",
            root_ch.name, ch.override_value if root_ch.type == 'VALUE' else ch.override_color[:]
        )
        return

    # If no channel source, trigger reconnection to apply changes
    reconnect_layer_nodes(layer, ch_idx)
    reconnect_mp_nodes(self.id_data)

    logger.debug(
        "update_override_color_value: Reconnected for channel %s with value %s",
        root_ch.name, ch.override_value if root_ch.type == 'VALUE' else ch.override_color[:]
    )
