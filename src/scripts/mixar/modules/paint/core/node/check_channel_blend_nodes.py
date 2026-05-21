# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Channel blend node management for paint layers.

This module handles creation and updating of blend type nodes for layer channels.
"""

from ...utils.blender_commons import get_active_material
from ...utils.common import set_mix_clamp
from ...utils.constants import EMISSION_VIEWER
from ..layer.check_layers import (
    is_layer_using_normal_map,
    is_normal_process_needed,
)
from ..layer.get_channels import get_channel_enabled
from ..layer.layer_utils import get_root_height_channel, update_preview_mix
from ..lib.lib import (
    OVERLAY_NORMAL,
    OVERLAY_NORMAL_STRAIGHT_OVER,
    STRAIGHT_OVER,
    STRAIGHT_OVER_BG,
    STRAIGHT_OVER_BG_BW,
    STRAIGHT_OVER_BG_VEC,
    STRAIGHT_OVER_BW,
    STRAIGHT_OVER_VEC,
    VECTOR_MIX,
)
from ..node.node_utils import remove_node
from ..subtree.get_subtree import get_tree
from ..lib.lib_operations import duplicate_lib_node_tree
from .check_channel_normal_nodes import check_channel_normal_map_nodes
from .create_nodes import new_node
from .update_nodes import replace_new_mix_node, replace_new_node

# Re-export functions from helper modules for backward compatibility
from .check_channel_helpers import (
    is_valid_to_remove_bump_nodes,
    check_create_height_pack,
    check_create_spread_alpha,
)
from .check_parallax_nodes import check_parallax_prep_nodes

# Expose all public functions via __all__
__all__ = [
    "is_valid_to_remove_bump_nodes",
    "check_parallax_prep_nodes",
    "check_create_height_pack",
    "check_create_spread_alpha",
    "check_blend_type_nodes",
]


def _fix_blend_group_internal_nodes(node_tree, blend_type, duplicate_nested=True):
    """Fix blend_type for internal nodes in a GROUP blend node.

    Recursively processes nodes inside group node trees to ensure:
    - Nodes with "src1" in name are set to MULTIPLY
    - Other mix nodes use the specified blend_type (if provided)

    Parameters:
        node_tree: The node tree to process.
        blend_type: The blend type to use for non-src1 mix nodes.
                   If None, only src1 nodes are fixed to MULTIPLY.
        duplicate_nested: Whether to duplicate nested groups before modifying.
    """
    if not node_tree:
        return

    for node in node_tree.nodes:
        # Check for mix nodes (MIX_RGB for older Blender, MIX for newer)
        if node.type in {"MIX_RGB", "MIX"} and hasattr(node, 'blend_type'):
            # "* src1" nodes should always be MULTIPLY
            # Check both name and label for "src1"
            node_identifier = (node.name + " " + (node.label or "")).lower()
            if "src1" in node_identifier:
                if node.blend_type != "MULTIPLY":
                    node.blend_type = "MULTIPLY"
            elif blend_type is not None:
                # Main mix node uses channel's blend_type
                if node.blend_type != blend_type:
                    node.blend_type = blend_type

        # Recursively handle nested groups (like "~yPL Straight Over Mix" inside blend)
        # This handles the case where Normal channel's "~yPL Straight Over Vector Mix"
        # contains "~yPL Straight Over Mix" which contains "* src1"
        if node.type == "GROUP" and hasattr(node, 'node_tree') and node.node_tree:
            # Duplicate nested group to avoid modifying shared library node tree
            if duplicate_nested and '_Copy' not in node.node_tree.name:
                duplicate_lib_node_tree(node)
            _fix_blend_group_internal_nodes(node.node_tree, blend_type, duplicate_nested)


def check_blend_type_nodes(root_ch, layer, ch):
    """
    Check and update all blend type related nodes for a channel.

    Parameters:
        root_ch: Root channel object.
        layer: Layer object containing the channel.
        ch: Channel to check blend type nodes for.

    Returns:
        True if any nodes were modified and reconnection is needed, False otherwise.
    """

    # print("Checking blend type nodes. Layer: " + layer.name + ' Channel: ' + root_ch.name)

    mp = layer.id_data.mp
    tree = get_tree(layer)
    nodes = tree.nodes
    blend = nodes.get(ch.blend)

    need_reconnect = False

    # Update normal map nodes
    need_reconnect = check_channel_normal_map_nodes(
        tree, layer, root_ch, ch, need_reconnect
    )

    # Extra alpha
    # Lazy import to avoid circular dependency
    from .check_channel_normal_nodes import check_extra_alpha
    need_reconnect = check_extra_alpha(layer, need_reconnect)

    has_parent = layer.parent_idx != -1

    # Check if channel is enabled
    channel_enabled = get_channel_enabled(ch, layer, root_ch)

    # Background layer always using mix blend type
    if layer.type == "BACKGROUND":
        blend_type = "MIX"
    else:
        blend_type = ch.blend_type

    # Layer intensity nodes
    if channel_enabled:
        layer_intensity = tree.nodes.get(ch.layer_intensity)
        if not layer_intensity:
            layer_intensity = new_node(
                tree, ch, "layer_intensity", "ShaderNodeMath", "Layer Opacity"
            )
            layer_intensity.operation = "MULTIPLY"
    else:
        if remove_node(tree, ch, "layer_intensity"):
            need_reconnect = True

    if root_ch.type in {"RGB", "VALUE"}:
        need_reconnect = _check_rgb_value_blend_nodes(
            tree, layer, root_ch, ch, blend, blend_type,
            channel_enabled, has_parent, need_reconnect
        )

    elif root_ch.type == "NORMAL":
        need_reconnect = _check_normal_blend_nodes(
            tree, layer, root_ch, ch, blend,
            channel_enabled, has_parent, need_reconnect
        )

    # Update preview mode node
    if mp.layer_preview_mode:
        mat = get_active_material()
        preview = mat.node_tree.nodes.get(EMISSION_VIEWER)
        if preview:
            update_preview_mix(ch, preview)

    return need_reconnect


def _check_rgb_value_blend_nodes(tree, layer, root_ch, ch, blend, blend_type,
                                  channel_enabled, has_parent, need_reconnect):
    """
    Check and update blend nodes for RGB and VALUE channel types.

    Parameters:
        tree: Node tree containing the nodes.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check.
        blend: Current blend node.
        blend_type: Type of blend to use.
        channel_enabled: Whether the channel is enabled.
        has_parent: Whether the layer has a parent.
        need_reconnect: Current reconnect status.

    Returns:
        Updated need_reconnect status.
    """
    if channel_enabled:
        if root_ch.type == "RGB":
            blend, need_reconnect = _create_rgb_blend_node(
                tree, layer, ch, blend_type, has_parent, root_ch, need_reconnect
            )
        elif root_ch.type == "VALUE":
            blend, need_reconnect = _create_value_blend_node(
                tree, layer, ch, blend_type, has_parent, root_ch, need_reconnect
            )

        if blend.type in {"MIX_RGB", "MIX"}:
            if blend.blend_type != blend_type:
                blend.blend_type = blend_type
        elif blend.type == "GROUP" and hasattr(blend, 'node_tree') and blend.node_tree:
            # For GROUP blend nodes, duplicate the node tree first to avoid modifying
            # shared library node tree, then fix internal mix node blend_types
            if '_Copy' not in blend.node_tree.name:
                duplicate_lib_node_tree(blend)
            _fix_blend_group_internal_nodes(blend.node_tree, blend_type)

        if blend.type == "GROUP" and "Clamp" in blend.inputs:
            blend.inputs["Clamp"].default_value = 1.0 if ch.use_clamp else 0.0
        else:
            set_mix_clamp(blend, ch.use_clamp)

        # Intensity nodes
        intensity = tree.nodes.get(ch.intensity)
        if not intensity:
            intensity = new_node(
                tree, ch, "intensity", "ShaderNodeMath", "Channel Opacity"
            )
            intensity.operation = "MULTIPLY"

        # Channel intensity
        intensity.inputs[1].default_value = ch.intensity_value

    else:
        if remove_node(tree, ch, "blend"):
            need_reconnect = True
        if remove_node(tree, ch, "intensity"):
            need_reconnect = True
        if remove_node(tree, ch, "extra_alpha"):
            need_reconnect = True

    return need_reconnect


def _create_rgb_blend_node(tree, layer, ch, blend_type, has_parent, root_ch, need_reconnect):
    """
    Create or update blend node for RGB channel type.

    Parameters:
        tree: Node tree containing the nodes.
        layer: Layer object.
        ch: Channel to update.
        blend_type: Type of blend to use.
        has_parent: Whether the layer has a parent.
        root_ch: Root channel object.
        need_reconnect: Current reconnect status.

    Returns:
        Tuple of (blend_node, need_reconnect).
    """
    if (has_parent or root_ch.enable_alpha) and blend_type == "MIX":
        if (
            layer.type == "BACKGROUND"
            and not (
                ch.enable_transition_ramp
                and ch.transition_ramp_intensity_unlink
                and ch.transition_ramp_blend_type == "MIX"
            )
            and not (
                ch.enable_transition_ramp
                and layer.parent_idx != -1
                and ch.transition_ramp_blend_type == "MIX"
            )
        ):
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                STRAIGHT_OVER_BG,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )
        else:
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                STRAIGHT_OVER,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )
    else:
        blend, need_reconnect = replace_new_mix_node(
            tree,
            ch,
            "blend",
            "Blend",
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )

    return blend, need_reconnect


def _create_value_blend_node(tree, layer, ch, blend_type, has_parent, root_ch, need_reconnect):
    """
    Create or update blend node for VALUE channel type.

    Parameters:
        tree: Node tree containing the nodes.
        layer: Layer object.
        ch: Channel to update.
        blend_type: Type of blend to use.
        has_parent: Whether the layer has a parent.
        root_ch: Root channel object.
        need_reconnect: Current reconnect status.

    Returns:
        Tuple of (blend_node, need_reconnect).
    """
    if (has_parent or root_ch.enable_alpha) and blend_type == "MIX":
        if layer.type == "BACKGROUND":
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                STRAIGHT_OVER_BG_BW,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )
        else:
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                STRAIGHT_OVER_BW,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )
    else:
        blend, need_reconnect = replace_new_mix_node(
            tree,
            ch,
            "blend",
            "Blend",
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
            data_type='FLOAT',  # VALUE channels use float mix, not RGBA
        )

    return blend, need_reconnect


def _check_normal_blend_nodes(tree, layer, root_ch, ch, blend,
                               channel_enabled, has_parent, need_reconnect):
    """
    Check and update blend nodes for NORMAL channel type.

    Parameters:
        tree: Node tree containing the nodes.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check.
        blend: Current blend node.
        channel_enabled: Whether the channel is enabled.
        has_parent: Whether the layer has a parent.
        need_reconnect: Current reconnect status.

    Returns:
        Updated need_reconnect status.
    """
    if channel_enabled and (
        is_layer_using_normal_map(layer) or root_ch.enable_alpha
    ):
        blend, need_reconnect = _create_normal_blend_node(
            tree, layer, ch, has_parent, root_ch, need_reconnect
        )

        # For GROUP blend nodes, duplicate the node tree first to avoid modifying
        # shared library node tree, then ensure "* src1" nodes are set to MULTIPLY
        if blend and blend.type == "GROUP" and hasattr(blend, 'node_tree') and blend.node_tree:
            if '_Copy' not in blend.node_tree.name:
                duplicate_lib_node_tree(blend)
            _fix_blend_group_internal_nodes(blend.node_tree, None)
    else:
        if remove_node(tree, ch, "blend"):
            need_reconnect = True

    # Handle intensity nodes for normal channels
    need_reconnect = _check_normal_intensity_nodes(
        tree, layer, root_ch, ch, channel_enabled, need_reconnect
    )

    return need_reconnect


def _create_normal_blend_node(tree, layer, ch, has_parent, root_ch, need_reconnect):
    """
    Create or update blend node for NORMAL channel type.

    Parameters:
        tree: Node tree containing the nodes.
        layer: Layer object.
        ch: Channel to update.
        has_parent: Whether the layer has a parent.
        root_ch: Root channel object.
        need_reconnect: Current reconnect status.

    Returns:
        Tuple of (blend_node, need_reconnect).
    """
    if (has_parent or root_ch.enable_alpha) and ch.normal_blend_type in {
        "MIX",
        "COMPARE",
    }:
        if layer.type == "BACKGROUND":
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                STRAIGHT_OVER_BG_VEC,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )
        else:
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                STRAIGHT_OVER_VEC,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )

    elif ch.normal_blend_type == "OVERLAY":
        if has_parent:
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                OVERLAY_NORMAL_STRAIGHT_OVER,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )
        else:
            blend, need_reconnect = replace_new_node(
                tree,
                ch,
                "blend",
                "ShaderNodeGroup",
                "Blend",
                OVERLAY_NORMAL,
                return_status=True,
                hard_replace=True,
                dirty=need_reconnect,
            )

    elif ch.normal_blend_type in {"MIX", "COMPARE"}:
        blend, need_reconnect = replace_new_node(
            tree,
            ch,
            "blend",
            "ShaderNodeGroup",
            "Blend",
            VECTOR_MIX,
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )

    return blend, need_reconnect


def _check_normal_intensity_nodes(tree, layer, root_ch, ch, channel_enabled, need_reconnect):
    """
    Check and update intensity nodes for NORMAL channel type.

    Parameters:
        tree: Node tree containing the nodes.
        layer: Layer object.
        root_ch: Root channel object.
        ch: Channel to check.
        channel_enabled: Whether the channel is enabled.
        need_reconnect: Current reconnect status.

    Returns:
        Updated need_reconnect status.
    """
    if channel_enabled and (
        (
            layer.type == "GROUP"
            and is_layer_using_normal_map(layer)
            and not is_normal_process_needed(layer)
        )
        or (
            layer.type != "GROUP"
            and ch.normal_map_type
            in {"NORMAL_MAP", "BUMP_NORMAL_MAP", "VECTOR_DISPLACEMENT_MAP"}
            and not ch.enable_transition_bump
        )
    ):
        # Intensity nodes
        intensity = tree.nodes.get(ch.intensity)
        if not intensity:
            intensity = new_node(
                tree, ch, "intensity", "ShaderNodeMath", "Channel Opacity"
            )
            intensity.operation = "MULTIPLY"

        # Channel intensity
        intensity.inputs[1].default_value = ch.intensity_value

    else:
        if remove_node(tree, ch, "intensity"):
            need_reconnect = True

    return need_reconnect
