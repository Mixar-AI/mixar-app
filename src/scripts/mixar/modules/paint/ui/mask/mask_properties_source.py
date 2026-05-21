# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update callbacks for mask source input and hemisphere-related changes."""

import re

from ...core.element.check_processes import check_layer_bump_process
from ...core.io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes
from ...core.lib.lib import HEMI
from ...core.lib.lib_operations import duplicate_lib_node_tree
from ...core.node.create_nodes import check_new_node, replace_new_node
from ...core.node.get_nodes import get_mask_source
from ...core.node.node_utils import remove_node
from ...core.subtree.get_subtree import get_mask_tree, get_tree
from ..mask.mask_operators_helper import setup_edge_detect_source


def update_mask_source_input(self, context):
    """Update callback when mask source input channel changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]

    mask = self
    tree = get_mask_tree(mask)

    if mask.source_input in {"R", "G", "B"}:
        check_new_node(
            tree,
            mask,
            "separate_color_channels",
            "ShaderNodeSeparateXYZ",
            "Separate Color",
        )
    else:
        remove_node(tree, mask, "separate_color_channels")

    # Reconnect nodes
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)


def update_mask_hemi_space(self, context):
    """Update callback when hemisphere lighting space changes for HEMI masks.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    if self.type != "HEMI":
        return

    source = get_mask_source(self)
    trans = source.node_tree.nodes.get("Vector Transform")
    if trans:
        trans.convert_from = self.hemi_space


def update_mask_hemi_camera_ray_mask(self, context):
    """Update callback when hemisphere camera ray mask setting changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]

    tree = get_mask_tree(self)
    source = get_mask_source(self)

    if source:

        # Check if source has the inputs, if not reload the node
        if "Camera Ray Mask" not in source.inputs:
            source = replace_new_node(
                tree,
                self,
                "source",
                "ShaderNodeGroup",
                "Mask Source",
                HEMI,
                force_replace=True,
            )
            duplicate_lib_node_tree(source)
            trans = source.node_tree.nodes.get("Vector Transform")
            if trans:
                trans.convert_from = self.hemi_space

            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)

        source.inputs["Camera Ray Mask"].default_value = (
            1.0 if self.hemi_camera_ray_mask else 0.0
        )


def update_mask_hemi_use_prev_normal(self, context):
    """Update callback when use previous normal setting changes for lighting masks.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    if self.type == "EDGE_DETECT":
        source = get_mask_source(self)
        setup_edge_detect_source(self, source)

    check_layer_tree_ios(layer, tree)
    check_layer_bump_process(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)
